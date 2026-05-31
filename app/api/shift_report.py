# app/api/shift_report.py
# (ĐÃ NHÂN BẢN VÀ CHỈNH SỬA TỪ lost_and_found.py)

from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional, Tuple, TypedDict, cast as typing_cast, Any
from datetime import datetime, timedelta
import math
import json
import random
import threading
import time as _time
from decimal import Decimal
from pydantic import BaseModel
import string # THÊM: Để tạo mã giao dịch


# ── Dashboard summary cache ──────────────────────────────────────────
# Cache in-process trong 30s cho /api/dashboard-summary để giảm tải khi
# nhiều client cùng poll. Invalidate khi có giao dịch mới (insert/update/
# delete/close) thông qua _invalidate_dashboard_cache().
_DASHBOARD_CACHE_TTL_SECONDS = 30.0
_dashboard_cache: dict[tuple, tuple[float, dict]] = {}
_dashboard_cache_lock = threading.Lock()


def _invalidate_dashboard_cache() -> None:
    with _dashboard_cache_lock:
        _dashboard_cache.clear()


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


class DecimalSafeJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
            cls=_DecimalEncoder,
        ).encode("utf-8")

# Import từ các module đã tái cấu trúc
from ..db.session import get_db
# SỬA: Import model mới (Giả định)
from ..db.models import User, ShiftReportTransaction, Branch, Department, ShiftReportStatus, TransactionType, ShiftCloseLog, User, Folio, FolioTransaction, Payment, ShiftPaymentMethod
from ..core.security import get_active_branch
from ..core.permissions import is_admin, is_manager, functional_code
from ..core.config import logger, BRANCHES, SHIFT_TRANSACTION_TYPES, hotel_branch_number, hotel_branch_display_name # THÊM: Import cấu hình mới
from ..core.utils import VN_TZ
from ..services.pricing_service import money

# --- IMPORT CÁC SCHEMAS MỚI (Giả định) ---
from ..schemas.shift_report import ( # SỬA: Schema mới
    BatchDeleteTransactionsPayload, BatchCloseTransactionsPayload,
    ShiftTransactionsResponse, ShiftTransactionDetails
)

from sqlalchemy.dialects.postgresql import JSONB # Import JSONB để cast và dùng toán tử JSONB
# Import các thành phần SQLAlchemy cần thiết
from sqlalchemy import cast, Date, desc, or_, and_, asc, case, func, tuple_, extract
from fastapi.encoders import jsonable_encoder
import os

router = APIRouter()

# Xác định đường dẫn tuyệt đối đến thư mục gốc của project 'app'
APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Tạo đường dẫn tuyệt đối đến thư mục templates
templates = Jinja2Templates(directory=os.path.join(APP_ROOT, "templates"))

# --- SỬA: Map trạng thái và loại giao dịch mới ---
SHIFT_STATUS_MAP = {
    "PENDING": "Chờ xử lý",
    "CLOSED": "Đã kết ca",
    "DELETED": "Đã xoá"
}

def map_status_to_vietnamese(status_value: Optional[str]) -> str:
    """Helper để map status enum value to Vietnamese string."""
    if not status_value:
        return ""
    return SHIFT_STATUS_MAP.get(status_value, status_value)

def map_type_to_vietnamese(type_value: Optional[str]) -> str:
    """Helper để map transaction type enum value to Vietnamese string."""
    if not type_value:
        return ""
    return SHIFT_TRANSACTION_TYPES.get(type_value, type_value) # SỬA: Dùng biến config mới

# --- THÊM: Helper tạo mã giao dịch ---
def generate_transaction_code(db: Session, branch_code: str) -> str:
    """Tạo mã giao dịch duy nhất theo format [BranchCode]-[5-Digits]"""
    while True:
        random_part = ''.join(random.choices(string.digits, k=5))
        code = f"{branch_code}-{random_part}"
        # Kiểm tra va chạm (dù rất hiếm)
        exists = db.query(ShiftReportTransaction).filter(ShiftReportTransaction.transaction_code == code).first()
        if not exists:
            return code

# Đảm bảo bạn đã import jsonable_encoder ở đầu file
from fastapi.encoders import jsonable_encoder

# Đảm bảo import này ở đầu file
from fastapi.encoders import jsonable_encoder

# Trong file app/api/shift_report.py

class ShiftSummary(TypedDict):
    gross_inflow: float
    refund_outflow: float
    net_total: float
    cash: float
    card: float
    bank_transfer: float
    company_unc: float
    ota: float
    debt: float
    non_cash: float
    count: int
    by_type: dict[str, float]
    by_method: dict[str, float]


def _model_value(value: Any) -> Any:
    return typing_cast(Any, value)


def _json_id_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    ids = []
    for item in value:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _set_model_attr(model: Any, name: str, value: Any) -> None:
    setattr(model, name, value)


def _shift_enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _is_shift_refund(tx: ShiftReportTransaction) -> bool:
    return _shift_enum_value(_model_value(tx.transaction_type)) == TransactionType.CASH_EXPENSE.value


def _infer_shift_payment_method(tx: ShiftReportTransaction) -> str:
    pm = _shift_enum_value(_model_value(tx.payment_method))
    if pm:
        return pm
    tx_type = _shift_enum_value(_model_value(tx.transaction_type))
    fallback = {
        TransactionType.OTHER.value: ShiftPaymentMethod.CASH.value,
        TransactionType.CARD.value: ShiftPaymentMethod.CARD.value,
        TransactionType.BRANCH_ACCOUNT.value: ShiftPaymentMethod.BANK_TRANSFER.value,
        TransactionType.COMPANY_ACCOUNT.value: ShiftPaymentMethod.UNC.value,
        TransactionType.OTA.value: ShiftPaymentMethod.OTA.value,
        TransactionType.UNC.value: ShiftPaymentMethod.DEBT.value,
        TransactionType.CASH_EXPENSE.value: ShiftPaymentMethod.CASH.value,
    }
    return fallback.get(tx_type, ShiftPaymentMethod.CASH.value)


def summarize_shift_transactions(transactions: list[ShiftReportTransaction]) -> ShiftSummary:
    summary: ShiftSummary = {
        "gross_inflow": 0.0,
        "refund_outflow": 0.0,
        "net_total": 0.0,
        "cash": 0.0,
        "card": 0.0,
        "bank_transfer": 0.0,
        "company_unc": 0.0,
        "ota": 0.0,
        "debt": 0.0,
        "non_cash": 0.0,
        "count": len(transactions),
        "by_type": {},
        "by_method": {},
    }
    method_key_map = {
        ShiftPaymentMethod.CASH.value: "cash",
        ShiftPaymentMethod.CARD.value: "card",
        ShiftPaymentMethod.BANK_TRANSFER.value: "bank_transfer",
        ShiftPaymentMethod.UNC.value: "company_unc",
        ShiftPaymentMethod.OTA.value: "ota",
        ShiftPaymentMethod.DEBT.value: "debt",
    }
    for tx in transactions:
        amount = float(_model_value(tx.amount) or 0)
        tx_type = _shift_enum_value(_model_value(tx.transaction_type)) or "OTHER"
        method = _infer_shift_payment_method(tx)
        summary["by_type"][tx_type] = summary["by_type"].get(tx_type, 0.0) + amount
        summary["by_method"][method] = summary["by_method"].get(method, 0.0) + amount
        if _is_shift_refund(tx):
            # Hoàn tiền theo từng quỹ (refund-aware, khớp classify_log_revenues):
            # - Tiền mặt → refund_outflow (chi tiền mặt quầy)
            # - CK chi nhánh / UNC → giảm đúng quỹ (trừ bucket + gross_inflow)
            if method == ShiftPaymentMethod.BANK_TRANSFER.value:
                summary["bank_transfer"] -= amount
                summary["gross_inflow"] -= amount
            elif method == ShiftPaymentMethod.UNC.value:
                summary["company_unc"] -= amount
                summary["gross_inflow"] -= amount
            else:
                summary["refund_outflow"] += amount
            continue
        summary["gross_inflow"] += amount
        key = method_key_map.get(method, "cash")
        if key == "cash":
            summary["cash"] += amount
        elif key == "card":
            summary["card"] += amount
        elif key == "bank_transfer":
            summary["bank_transfer"] += amount
        elif key == "company_unc":
            summary["company_unc"] += amount
        elif key == "ota":
            summary["ota"] += amount
        elif key == "debt":
            summary["debt"] += amount
    summary["non_cash"] = (
        summary["card"]
        + summary["bank_transfer"]
        + summary["company_unc"]
        + summary["ota"]
        + summary["debt"]
    )
    summary["net_total"] = summary["gross_inflow"] - summary["refund_outflow"]
    return summary


# ── Revenue classification for ShiftCloseLog ─────────────────────────
# Nguồn sự thật duy nhất cho phân loại online vs branch: dùng cho
# batch_close, undo_transaction_from_log, batch_delete_shift_transactions,
# và tất cả các báo cáo tổng hợp để đảm bảo con số không lệch nhau.
BRANCH_REVENUE_TYPES = (TransactionType.BRANCH_ACCOUNT,)
ONLINE_REVENUE_TYPES = (
    TransactionType.OTA,
    TransactionType.UNC,
    TransactionType.CARD,
    TransactionType.COMPANY_ACCOUNT,
    TransactionType.OTHER,
)


def _tx_type_value(tx: ShiftReportTransaction) -> str:
    raw = getattr(tx, "transaction_type", None)
    if hasattr(raw, "value"):
        return raw.value
    return str(raw or "")


def _is_branch_revenue(tx: ShiftReportTransaction) -> bool:
    return _tx_type_value(tx) in {t.value for t in BRANCH_REVENUE_TYPES}


def _is_online_revenue(tx: ShiftReportTransaction) -> bool:
    return _tx_type_value(tx) in {t.value for t in ONLINE_REVENUE_TYPES}


def _is_refund_tx(tx: ShiftReportTransaction) -> bool:
    return _tx_type_value(tx) == TransactionType.CASH_EXPENSE.value


def classify_log_revenues(
    transactions: list[ShiftReportTransaction],
) -> dict[str, int]:
    """
    Phân loại giao dịch cho ShiftCloseLog.

    - branch_revenue: tiền về quỹ chi nhánh (BRANCH_ACCOUNT)
    - online_revenue: tiền vào kênh ngoài/khoản phải thu (OTA, UNC, CARD,
      COMPANY_ACCOUNT, OTHER/tiền mặt đếm qua quầy)
    - refund_outflow: tách riêng để UI không nhầm tiền hoàn là doanh thu
    - pms_net: inflow thực - refund (dùng làm pms_revenue khi auto)
    """
    branch_total = 0
    online_total = 0
    refund_total = 0
    for tx in transactions:
        amount = int(getattr(tx, "amount", 0) or 0)
        if _is_refund_tx(tx):
            # Hoàn tiền: trừ khỏi ĐÚNG quỹ theo phương thức hoàn (refund-aware).
            # - Tiền mặt  → refund_outflow (chi tiền mặt quầy)
            # - CK chi nhánh (BANK_TRANSFER) → giảm quỹ chi nhánh
            # - UNC công ty (UNC)            → giảm doanh thu online/công ty
            refund_method = _infer_shift_payment_method(tx)
            if refund_method == ShiftPaymentMethod.BANK_TRANSFER.value:
                branch_total -= amount
            elif refund_method == ShiftPaymentMethod.UNC.value:
                online_total -= amount
            else:
                refund_total += amount
            continue
        if _is_branch_revenue(tx):
            branch_total += amount
        elif _is_online_revenue(tx):
            online_total += amount
    return {
        "branch_revenue": branch_total,
        "online_revenue": online_total,
        "refund_outflow": refund_total,
        "pms_net": branch_total + online_total - refund_total,
    }


def get_date_range_filter(from_date_str: Optional[str], to_date_str: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Chuyển đổi string input thành khoảng thời gian datetime có timezone.
    Trả về: (start_time, end_time) hoặc (None, None)
    """
    start_time = None
    end_time = None

    try:
        if from_date_str:
            f_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
            start_time = datetime.combine(f_date, datetime.min.time()).replace(tzinfo=VN_TZ)
        
        if to_date_str:
            t_date = datetime.strptime(to_date_str, "%Y-%m-%d").date()
            end_time = datetime.combine(t_date, datetime.max.time()).replace(tzinfo=VN_TZ)
            
    except ValueError:
        logger.warning(f"Lỗi định dạng ngày: from={from_date_str}, to={to_date_str}")
    
    return start_time, end_time

def _serialize_transaction(transaction: ShiftReportTransaction) -> dict:
    """
    Phiên bản tối ưu tốc độ: Trả về Dict trực tiếp, KHÔNG DÙNG jsonable_encoder.
    """
    # 1. Lấy giá trị Enum an toàn
    status_val = _shift_enum_value(_model_value(transaction.status))
    type_val = _shift_enum_value(_model_value(transaction.transaction_type))

    # 2. Xử lý quan hệ (Tránh truy cập nếu là None để không trigger lazy load thừa)
    branch_code = transaction.branch.branch_code if transaction.branch else "N/A"
    
    recorded_by_str = "N/A"
    if transaction.recorder:
        recorded_by_str = f"{transaction.recorder.name} ({transaction.recorder.employee_code})"

    closed_by_str = None
    if transaction.closer:
        closed_by_str = f"{transaction.closer.name} ({transaction.closer.employee_code})"

    deleted_by_str = None
    if transaction.deleter:
        deleted_by_str = f"{transaction.deleter.name} ({transaction.deleter.employee_code})"

    # 3. Format ngày tháng thủ công (Nhanh hơn để thư viện tự đoán)
    created_fmt = transaction.created_datetime.isoformat() if transaction.created_datetime else None
    closed_fmt = transaction.closed_datetime.isoformat() if transaction.closed_datetime else None
    deleted_fmt = transaction.deleted_datetime.isoformat() if transaction.deleted_datetime else None

    return {
        "id": transaction.id,
        "transaction_code": transaction.transaction_code,
        "amount": float(_model_value(transaction.amount)) if _model_value(transaction.amount) else 0,
        "room_number": transaction.room_number,
        "transaction_info": transaction.transaction_info,

        "created_datetime": created_fmt,
        "closed_datetime": closed_fmt,
        "deleted_datetime": deleted_fmt,

        "chi_nhanh": branch_code,
        "recorded_by": recorded_by_str,
        "closed_by": closed_by_str,
        "deleted_by": deleted_by_str,

        # Mapping hiển thị
        "status": map_status_to_vietnamese(status_val),
        "transaction_type_display": map_type_to_vietnamese(type_val),

        # Raw data
        "transaction_type": type_val,
        "status_raw": status_val,

        # ── PMS Integration ─────────────────────────────────────────
        "is_auto_posted": getattr(transaction, 'is_auto_posted', False),
        "payment_method": (
            transaction.payment_method.value
            if hasattr(transaction.payment_method, 'value')
            else (transaction.payment_method or "CASH")
        ),
        "stay_id": getattr(transaction, 'stay_id', None),
        "folio_id": getattr(transaction, 'folio_id', None),
        "folio_transaction_id": getattr(transaction, 'folio_transaction_id', None),
    }

# --- SỬA: Hàm filter chính ---
def _get_filtered_transactions(
    db: Session,
    user_data: dict,
    per_page: int,
    search: Optional[str] = None,
    status: Optional[str] = None,
    chi_nhanh: Optional[str] = None,
    # created_date: Optional[str] = None,  <-- XOÁ CÁI NÀY
    from_date: Optional[str] = None,    # <-- THÊM MỚI
    to_date: Optional[str] = None,      # <-- THÊM MỚI
    transaction_type: Optional[str] = None,
    recorded_by: Optional[str] = None,
    last_created_datetime: Optional[str] = None,
    last_id: Optional[int] = None,
    page: Optional[int] = 1,
    sort_by: Optional[str] = 'created_datetime',
    sort_order: Optional[str] = 'desc',
    active_branch_for_letan: Optional[str] = None
) -> Tuple[List[ShiftReportTransaction], int]:
    
    # ... (Giữ nguyên phần khởi tạo query và check role) ...
    query = db.query(ShiftReportTransaction).options(
        joinedload(ShiftReportTransaction.branch),
        joinedload(ShiftReportTransaction.recorder),
        joinedload(ShiftReportTransaction.closer),
        joinedload(ShiftReportTransaction.deleter)
    )

    if not is_admin(user_data):
        query = query.filter(ShiftReportTransaction.status != ShiftReportStatus.DELETED)

    if user_data.get("role") == 'letan':
        query = query.filter(ShiftReportTransaction.status != ShiftReportStatus.CLOSED)

    branch_to_filter = chi_nhanh
    if user_data.get("role") == 'letan' and not chi_nhanh:
        branch_to_filter = active_branch_for_letan

    if branch_to_filter:
        query = query.join(ShiftReportTransaction.branch).filter(Branch.branch_code == branch_to_filter)

    if status:
        if status == "DELETED":
            query = query.filter(ShiftReportTransaction.status == ShiftReportStatus.DELETED)
        else:
            query = query.filter(ShiftReportTransaction.status == status)
            
    if transaction_type:
        query = query.filter(ShiftReportTransaction.transaction_type == transaction_type)

    # --- LOGIC LỌC NGÀY MỚI (DATE RANGE) ---
    start_time, end_time = get_date_range_filter(from_date, to_date)
    
    if start_time and end_time:
        query = query.filter(ShiftReportTransaction.created_datetime.between(start_time, end_time))
    elif start_time:
        query = query.filter(ShiftReportTransaction.created_datetime >= start_time)
    elif end_time:
        query = query.filter(ShiftReportTransaction.created_datetime <= end_time)

    if search:
        search_term = search.strip()
        if search_term:
            # --- TỐI ƯU HÓA: SỬ DỤNG FULL-TEXT SEARCH ---
            # Sử dụng plainto_tsquery để xử lý an toàn các ký tự đặc biệt trong input của người dùng.
            # Toán tử @@ được tối ưu hóa để sử dụng GIN index trên cột fts_vector.
            fts_condition = ShiftReportTransaction.fts_vector.op("@@")(func.plainto_tsquery('simple', search_term))

            # Giữ lại logic tìm kiếm theo số tiền vì nó hiệu quả (tìm kiếm chính xác)
            filter_conditions: list[Any] = [fts_condition]

            # Kiểm tra xem chuỗi tìm kiếm có phải là số không
            # Loại bỏ dấu phẩy hoặc dấu chấm để xử lý số tiền như "100,000"
            numeric_search_term = search_term.replace(',', '').replace('.', '')
            if numeric_search_term.isdigit() or (numeric_search_term.startswith('-') and numeric_search_term[1:].isdigit()):
                # Nếu là số, thêm điều kiện tìm kiếm theo cột amount
                filter_conditions.append(ShiftReportTransaction.amount == int(numeric_search_term))

            query = query.filter(or_(*filter_conditions))

    # SỬA: Filter theo người ghi nhận
    if recorded_by:
        search_term = recorded_by.strip()
        if '(' in search_term and ')' in search_term:
            search_term = search_term.split('(')[-1].strip(')')
        search_pattern = f"%{search_term}%"
        query = query.join(ShiftReportTransaction.recorder).filter(
            or_(User.name.ilike(search_pattern), User.employee_code.ilike(search_pattern))
        )

    # Count
    count_q = query.with_entities(func.count(ShiftReportTransaction.id)).order_by(None)
    total_records = db.execute(count_q).scalar_one()

    # --- THÊM: Logic sắp xếp động ---
    sort_direction = desc if sort_order == 'desc' else asc
    sort_column_map = {
        'transaction_code': ShiftReportTransaction.transaction_code,
        'created_datetime': ShiftReportTransaction.created_datetime,
        'recorded_by': User.name,
        'room_number': ShiftReportTransaction.room_number,
        'transaction_type': ShiftReportTransaction.transaction_type,
        'amount': ShiftReportTransaction.amount,
        'status': case(
            (ShiftReportTransaction.status == ShiftReportStatus.PENDING, 1),
            (ShiftReportTransaction.status == ShiftReportStatus.CLOSED, 2),
            (ShiftReportTransaction.status == ShiftReportStatus.DELETED, 3),
            else_=4
        )
    }

    sort_key = sort_by or 'created_datetime'
    order_expression = sort_column_map.get(sort_key, ShiftReportTransaction.created_datetime)

    # Nếu sắp xếp theo người ghi nhận, cần join với bảng User
    if sort_by == 'recorded_by':
        query = query.join(ShiftReportTransaction.recorder, isouter=True)

    # Áp dụng sắp xếp
    query = query.order_by(sort_direction(order_expression), desc(ShiftReportTransaction.id))

    # Áp dụng Keyset Pagination nếu có cursor
    page_number = page or 1
    if last_created_datetime and last_id is not None:
        try:
            cursor_dt = datetime.fromisoformat(last_created_datetime)

            # SỬA: Dùng created_datetime
            query = query.filter(
                tuple_(ShiftReportTransaction.created_datetime, ShiftReportTransaction.id) < (cursor_dt, last_id)
            )
        except (ValueError, TypeError):
            logger.warning(f"Cursor không hợp lệ: last_created_datetime={last_created_datetime}, last_id={last_id}")
            page_index = (page_number - 1) if page_number > 0 else 0
            query = query.offset(page_index * per_page) # Fallback
    elif page_number > 1:
        query = query.offset((page_number - 1) * per_page)

    items = query.limit(per_page).all()
    return items, total_records

# ----------------------------------------------------------------------
# ENDPOINT TẢI TRANG (SỬA)
# ----------------------------------------------------------------------
@router.get("", response_class=HTMLResponse)
def shift_report_page(
    request: Request,
    db: Session = Depends(get_db),
    page: int = 1,
    per_page: int = 9,
    chi_nhanh: Optional[str] = None,
    status: Optional[str] = None,
    transaction_type: Optional[str] = None, # THÊM
):
    user_data = request.session.get("user")
    if not user_data:
        return RedirectResponse("/login", status_code=303)

    per_page = int(request.cookies.get('shiftReportPerPage', 9))

    all_branches_obj = db.query(Branch).all()
    display_branches = [
        {"code": b.branch_code, "label": hotel_branch_display_name(b.branch_code)}
        for b in all_branches_obj
        if hotel_branch_number(b.branch_code) is not None
    ]
    display_branches.sort(key=lambda x: hotel_branch_number(x["code"]))

    # === BẮT ĐẦU SỬA LỖI LOGIC CHI NHÁNH ===
    
    active_branch = ""
    if not is_admin(user_data):
        active_branch = get_active_branch(request, db, user_data) or ""
    
    # === KẾT THÚC SỬA LỖI ===

    # SỬA: Map trạng thái mới
    status_display_map = {
        s.value: map_status_to_vietnamese(s.value) 
        for s in ShiftReportStatus if s != ShiftReportStatus.DELETED
    }
    
    # SỬA: Sắp xếp lại loại giao dịch theo thứ tự mong muốn
    desired_order = ["BRANCH_ACCOUNT", "COMPANY_ACCOUNT", "OTA", "UNC", "CARD", "CASH_EXPENSE", "OTHER"]
    sorted_transaction_types = sorted(
        [t for t in TransactionType], 
        key=lambda t: desired_order.index(t.value) if t.value in desired_order else len(desired_order)
    )
    type_display_map = {
        key: value for key, value in SHIFT_TRANSACTION_TYPES.items()
    }
    
    # --- SỬA: SỬ DỤNG HÀM DỊCH VỤ ĐỂ LẤY DỮ LIỆU BAN ĐẦU ---
    branch_to_filter = chi_nhanh
    
    if not is_admin(user_data):
        branch_to_filter = active_branch

    # SỬA: Gọi hàm filter mới
    items, total_records = _get_filtered_transactions(
        db=db,
        user_data=user_data,
        per_page=per_page,
        page=page,
        chi_nhanh=branch_to_filter, # <-- `branch_to_filter` giờ đã đúng
        status=status,
        transaction_type=transaction_type,
        active_branch_for_letan=active_branch # <-- Truyền `active_branch` vào đây
    )
    
    initial_records = [_serialize_transaction(item) for item in items]
    total_pages = math.ceil(total_records / per_page) if per_page > 0 else 1

    # SỬA: Tên template và context
    return templates.TemplateResponse(request, "shift_report.html", {
        "request": request,
        "user": user_data,
        "statuses": [s for s in ShiftReportStatus if s != ShiftReportStatus.DELETED],
        "transaction_types": sorted_transaction_types,
        "status_display_map": status_display_map, 
        "type_display_map": type_display_map, 
        "initial_branch_filter": active_branch, # <-- Đảm bảo B10 được chọn
        "branches": display_branches, 
        "display_branches": display_branches,
        "branch_filter": chi_nhanh,
        "status_filter": status,
        "type_filter": transaction_type,
        "initial_records": initial_records,
        "current_page": page,
        "total_pages": total_pages,
        "total_records": total_records,
        "per_page": per_page,
        "active_page": "shift-report",
    })

# ----------------------------------------------------------------------
# ENDPOINT API CHO DASHBOARD (XOÁ)
# ----------------------------------------------------------------------
# @router.get("/api/dashboard-stats")
# ... (TOÀN BỘ ENDPOINT NÀY ĐÃ BỊ XOÁ) ...

# ----------------------------------------------------------------------
# ENDPOINT API LẤY DỮ LIỆU (SỬA)
# ----------------------------------------------------------------------
# Endpoint nhẹ để kiểm tra thay đổi (dùng cho polling)
@router.get("/api/changes")
def api_check_changes(
    request: Request,
    db: Session = Depends(get_db),
    since_id: int = 0,
    chi_nhanh: Optional[str] = None,
):
    """API nhẹ để kiểm tra có thay đổi mới không. Trả về ID lớn nhất.

    Sync handler — Starlette tự đẩy vào threadpool, tránh block event loop khi
    SQLAlchemy session là sync.
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Unauthorized")

    active_branch_for_letan = None
    if user_data.get("role") == 'letan' and not chi_nhanh:
        active_branch_for_letan = get_active_branch(request, db, user_data)

    branch_filter = chi_nhanh or active_branch_for_letan

    query = db.query(func.max(ShiftReportTransaction.id).label('max_id'))

    if branch_filter:
        query = query.join(ShiftReportTransaction.branch).filter(Branch.branch_code == branch_filter)

    result = query.first()
    current_max_id = result.max_id if result and result.max_id is not None else 0

    return DecimalSafeJSONResponse({
        "has_changes": current_max_id > since_id,
        "max_id": current_max_id if current_max_id > 0 else since_id,
    })


@router.get("/api", response_model=ShiftTransactionsResponse)
def api_shift_report_transactions(
    request: Request,
    db: Session = Depends(get_db),
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
    chi_nhanh: Optional[str] = None,
    # created_date: Optional[str] = None, <-- XOÁ
    from_date: Optional[str] = None,   # <-- THÊM
    to_date: Optional[str] = None,     # <-- THÊM
    transaction_type: Optional[str] = None,
    recorded_by: Optional[str] = None,
    last_created_datetime: Optional[str] = None,
    last_id: Optional[int] = None,
    sort_by: Optional[str] = 'created_datetime',
    sort_order: Optional[str] = 'desc',
):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Unauthorized")

    active_branch_for_letan = None
    if user_data.get("role") == 'letan' and not chi_nhanh:
        active_branch_for_letan = get_active_branch(request, db, user_data)

    items, total_records = _get_filtered_transactions(
        db=db,
        user_data=user_data,
        per_page=per_page,
        page=page,
        search=search,
        status=status,
        chi_nhanh=chi_nhanh,
        from_date=from_date, # <-- Truyền tham số mới
        to_date=to_date,     # <-- Truyền tham số mới
        transaction_type=transaction_type,
        recorded_by=recorded_by,
        last_created_datetime=last_created_datetime,
        last_id=last_id,
        sort_by=sort_by,
        sort_order=sort_order,
        active_branch_for_letan=active_branch_for_letan
    )
    
    results = [_serialize_transaction(item) for item in items]

    return {
        "records": results,
        "currentPage": page,
        "totalPages": math.ceil(total_records / per_page) if per_page > 0 else 1,
        "totalRecords": total_records
    }

# ----------------------------------------------------------------------
# ENDPOINT THÊM MỚI (SỬA)
# ----------------------------------------------------------------------
@router.post("/add", status_code=201, response_model=dict)
async def add_shift_transaction( # SỬA
    request: Request,
    db: Session = Depends(get_db)
):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Unauthorized")

    form_data = await request.form()
    
    # SỬA: Lấy dữ liệu form mới
    transaction_type = form_data.get("transaction_type")
    amount_str = form_data.get("amount")
    room_number = form_data.get("room_number") # THÊM
    transaction_info = form_data.get("transaction_info") # THÊM
    chi_nhanh_code_from_form = form_data.get("chi_nhanh")
    recorded_by_string = form_data.get("recorded_by")

    # --- Logic lấy recorder (Giữ nguyên) ---
    recorded_by_code = None
    if isinstance(recorded_by_string, str) and '(' in recorded_by_string and ')' in recorded_by_string:
        recorded_by_code = recorded_by_string.split('(')[-1].strip(')')

    recorder = None
    if recorded_by_code:
        recorder = db.query(User).filter(User.employee_code == recorded_by_code).first()
    if not recorder:
        recorder = db.query(User).filter(User.id == user_data["id"]).first()
    # --- Kết thúc logic recorder ---

    chi_nhanh_code = chi_nhanh_code_from_form
    
    if user_data.get("role") == 'letan':
        # Nếu Lễ tân, chúng ta CẦN một chi nhánh.
        # Nếu form (đã sửa ở HTML) gửi "B10", chi_nhanh_code sẽ là "B10".
        # Nếu form không gửi (lỗi), chúng ta phải tự tìm "B10".
        if not chi_nhanh_code:
            # 1. Ưu tiên session 'active_branch' (do GPS/chọn tay)
            active_branch_session = request.session.get("active_branch")
            if active_branch_session:
                chi_nhanh_code = active_branch_session
            else:
                # 2. Lấy last_active_branch từ DB
                user_from_db = db.query(User).filter(User.id == user_data.get("id")).first()
                if user_from_db and user_from_db.last_active_branch:
                    chi_nhanh_code = user_from_db.last_active_branch # Đây là "B10"
                else:
                    # 3. Fallback về chi nhánh chính (logic cũ)
                    chi_nhanh_code = user_data.get("branch", "")
    
    # Admin/Boss/Quản lý phải gửi chi nhánh từ form
    elif not chi_nhanh_code:
         raise HTTPException(status_code=400, detail="Quản trị viên phải chọn một chi nhánh.")

    branch = db.query(Branch).filter(Branch.branch_code == chi_nhanh_code).first()
    if not branch:
        raise HTTPException(status_code=400, detail=f"Chi nhánh không hợp lệ hoặc không tìm thấy: {chi_nhanh_code}")
    # --- Kết thúc logic chi nhánh (ĐÃ SỬA) ---

    # SỬA: Validate dữ liệu mới
    amount_value = amount_str if isinstance(amount_str, str) else None
    try:
        amount = int(amount_value) if amount_value is not None else 0
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Số tiền không hợp lệ.")

    if not transaction_type or transaction_type not in TransactionType._value2member_map_:
        raise HTTPException(status_code=400, detail="Loại giao dịch không hợp lệ.")

    # THÊM: Tạo mã giao dịch
    transaction_code = generate_transaction_code(db, _model_value(branch.branch_code))

    # SỬA: Tạo object model mới
    new_transaction = ShiftReportTransaction(
        transaction_code=transaction_code,
        transaction_type=transaction_type,
        amount=amount,
        room_number=room_number, # THÊM
        transaction_info=transaction_info, # THÊM
        branch_id=branch.id,
        recorder_id=recorder.id,
        created_datetime=datetime.now(VN_TZ),
        status=ShiftReportStatus.PENDING # Mặc định
    )
    
    db.add(new_transaction)
    db.commit()
    _invalidate_dashboard_cache()
    # SỬA: Refresh quan hệ
    db.refresh(new_transaction, ["branch", "recorder"])
    return {"status": "success", "message": "Đã thêm giao dịch thành công.", "item": _serialize_transaction(new_transaction)}


# ====================================================================
# ENDPOINT THÊM TỪ PMS (JSON) — Tự động ghi nhận thanh toán
# ====================================================================
class PMSAddShiftPayload(BaseModel):
    transaction_type: str
    amount: int
    room_number: Optional[str] = None
    transaction_info: Optional[str] = None
    chi_nhanh: Optional[str] = None
    payment_method: Optional[str] = None
    stay_id: Optional[int] = None
    folio_id: Optional[int] = None
    folio_transaction_id: Optional[int] = None
    is_auto_posted: bool = False


@router.post("/add-json", status_code=201, response_model=dict)
def add_shift_transaction_from_pms(
    payload: PMSAddShiftPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Endpoint nhận JSON từ PMS để tự động ghi nhận thanh toán vào Shift Report.
    Dùng khi khách thanh toán tại PMS.
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Unauthorized")

    # Xác định chi nhánh
    chi_nhanh_code = payload.chi_nhanh
    if not chi_nhanh_code:
        if user_data.get("role") == 'letan':
            active_branch_session = request.session.get("active_branch")
            if active_branch_session:
                chi_nhanh_code = active_branch_session
            else:
                user_from_db = db.query(User).filter(User.id == user_data.get("id")).first()
                if user_from_db and user_from_db.last_active_branch:
                    chi_nhanh_code = user_from_db.last_active_branch
                else:
                    chi_nhanh_code = user_data.get("branch", "")
        else:
            raise HTTPException(status_code=400, detail="Chi nhánh không được xác định.")

    branch = db.query(Branch).filter(Branch.branch_code == chi_nhanh_code).first()
    if not branch:
        raise HTTPException(status_code=400, detail=f"Không tìm thấy chi nhánh: {chi_nhanh_code}")

    # Xác định recorder (user hiện tại)
    recorder = db.query(User).filter(User.id == user_data.get("id")).first()
    if not recorder:
        raise HTTPException(status_code=400, detail="Không tìm thấy người ghi nhận.")

    # Validate
    if not payload.transaction_type or payload.transaction_type not in TransactionType._value2member_map_:
        raise HTTPException(status_code=400, detail=f"Loại giao dịch không hợp lệ: {payload.transaction_type}")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Số tiền phải lớn hơn 0.")

    # Validate payment_method nếu có
    payment_method_enum = None
    if payload.payment_method:
        try:
            from ..db.models import ShiftPaymentMethod
            payment_method_enum = ShiftPaymentMethod(payload.payment_method)
        except (ValueError, AttributeError):
            pass

    # Tạo mã giao dịch
    transaction_code = generate_transaction_code(db, _model_value(branch.branch_code))

    new_transaction = ShiftReportTransaction(
        transaction_code=transaction_code,
        transaction_type=payload.transaction_type,
        amount=payload.amount,
        room_number=payload.room_number,
        transaction_info=payload.transaction_info,
        branch_id=branch.id,
        recorder_id=recorder.id,
        created_datetime=datetime.now(VN_TZ),
        status=ShiftReportStatus.PENDING,
        # PMS Integration
        stay_id=payload.stay_id,
        folio_id=payload.folio_id,
        folio_transaction_id=payload.folio_transaction_id,
        payment_method=payment_method_enum,
        is_auto_posted=payload.is_auto_posted,
    )

    db.add(new_transaction)
    db.commit()
    _invalidate_dashboard_cache()
    db.refresh(new_transaction, ["branch", "recorder"])

    return {
        "status": "success",
        "message": "Đã ghi nhận giao dịch từ PMS.",
        "item": _serialize_transaction(new_transaction)
    }


# ----------------------------------------------------------------------
# ENDPOINT CHỈNH SỬA (SỬA)
# ----------------------------------------------------------------------
@router.get("/edit-source/{item_id}", response_model=dict)
def get_shift_edit_source(item_id: int, request: Request, db: Session = Depends(get_db)):
    """Trả về thông tin nguồn (truy vết) của một dòng giao ca trước khi cho user sửa.

    UI dùng kết quả này để render cảnh báo: dòng giao ca này đang link tới Folio nào,
    Payment nào, sửa sẽ tác động đến đâu — user phải xác nhận mới được cascade.
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Unauthorized")

    item = (
        db.query(ShiftReportTransaction)
        .options(
            joinedload(ShiftReportTransaction.folio).joinedload(Folio.stay),
            joinedload(ShiftReportTransaction.folio_transaction),
        )
        .filter(ShiftReportTransaction.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy giao dịch.")

    folio = getattr(item, "folio", None)
    folio_tx = getattr(item, "folio_transaction", None)

    payment = None
    if folio_tx is not None and folio_tx.reference_type == "payment" and folio_tx.reference_id:
        payment = db.query(Payment).filter(Payment.id == folio_tx.reference_id).first()

    room_number = item.room_number
    if not room_number and folio is not None and folio.stay is not None:
        stay_room = getattr(folio.stay, "room", None)
        if stay_room:
            room_number = getattr(stay_room, "room_number", None)

    payment_method_raw = (
        item.payment_method.value
        if hasattr(item.payment_method, "value")
        else (item.payment_method or "CASH")
    )

    impacts: list[str] = []
    if folio_tx is not None and not folio_tx.is_voided:
        impacts.append("folio_transaction")
    if folio is not None:
        impacts.append("folio_balance")
    if payment is not None and not payment.is_refunded:
        impacts.append("payment")

    folio_status = None
    if folio is not None and folio.status:
        folio_status = folio.status.value if hasattr(folio.status, "value") else str(folio.status)

    cascade_locked_reason = None
    if folio is not None and folio_status == "CLOSED":
        cascade_locked_reason = "Folio đã đóng — chỉ admin/boss mới được cascade."

    return {
        "id": item.id,
        "transaction_code": item.transaction_code,
        "amount": float(item.amount or 0),
        "transaction_type": _shift_enum_value(item.transaction_type),
        "payment_method": payment_method_raw,
        "is_auto_posted": bool(item.is_auto_posted),
        "room_number": room_number,
        "folio": {
            "id": folio.id,
            "folio_code": folio.folio_code,
            "status": folio_status,
            "balance": float(folio.balance or 0),
            "total_charge": float(folio.total_charge or 0),
            "total_paid": float(folio.total_paid or 0),
        } if folio is not None else None,
        "folio_transaction": {
            "id": folio_tx.id,
            "transaction_type": folio_tx.transaction_type.value if folio_tx.transaction_type else None,
            "description": folio_tx.description,
            "amount": float(folio_tx.amount or 0),
            "is_voided": bool(folio_tx.is_voided),
            "created_at": folio_tx.created_at.isoformat() if folio_tx.created_at else None,
        } if folio_tx is not None else None,
        "payment": {
            "id": payment.id,
            "amount": float(payment.amount or 0),
            "method": payment.method.value if payment.method else None,
            "status": payment.status.value if payment.status else None,
            "transaction_code": payment.transaction_code,
            "is_refunded": bool(payment.is_refunded),
            "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
        } if payment is not None else None,
        "impacts": impacts,
        "cascade_locked_reason": cascade_locked_reason,
    }


@router.post("/edit-details/{item_id}", response_model=dict)
def edit_shift_transaction_details( # SỬA
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    # SỬA: Các trường form mới
    transaction_type: str = Form(...),
    amount: str = Form(...),
    room_number: Optional[str] = Form(None), # THÊM
    transaction_info: Optional[str] = Form(None), # THÊM
    recorded_by: Optional[str] = Form(None),
    chi_nhanh: Optional[str] = Form(None),
    confirm_cascade: Optional[str] = Form("false"),  # User phải tick để cascade về folio/payment
):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Unauthorized")

    if not (functional_code(user_data) == "letan" or is_manager(user_data)):
        raise HTTPException(status_code=403, detail="Bạn không có quyền chỉnh sửa.")

    # SỬA: Query model mới
    item = db.query(ShiftReportTransaction).filter(ShiftReportTransaction.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy giao dịch.")

    # Chỉ cho phép sửa khi status là PENDING
    if item.status != ShiftReportStatus.PENDING:
        raise HTTPException(status_code=400, detail="Không thể sửa giao dịch đã kết ca hoặc đã xoá.")

    # (Logic lấy recorder và branch giữ nguyên)
    recorder = None
    if recorded_by:
        if '(' in recorded_by and ')' in recorded_by:
            recorded_by_code = recorded_by.split('(')[-1].strip(')')
            recorder = db.query(User).filter(User.employee_code == recorded_by_code).first()
            if not recorder:
                raise HTTPException(status_code=400, detail=f"Không tìm thấy người ghi nhận với mã: {recorded_by_code}")
    else:
        recorder = item.recorder

    branch = None
    if chi_nhanh:
        branch = db.query(Branch).filter(Branch.branch_code == chi_nhanh).first()
    if not branch and user_data.get("role") == 'letan':
        active_branch_code = get_active_branch(request, db, user_data)
        branch = db.query(Branch).filter(Branch.branch_code == active_branch_code).first()
    if not branch:
        raise HTTPException(status_code=400, detail="Chi nhánh không hợp lệ.")
    # ---

    # SỬA: Cập nhật các trường mới
    old_amount = _model_value(item.amount)
    old_tx_type = _shift_enum_value(item.transaction_type)
    try:
        new_amount = int(amount)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Số tiền không hợp lệ.")

    type_changed = transaction_type != old_tx_type
    amount_changed = new_amount != old_amount
    cascade_requested = str(confirm_cascade).lower() in ("true", "1", "yes", "on")

    # Suy ra payment_method mới từ transaction_type → đồng bộ về Folio/Payment
    from ..services.shift_report_service import (
        shift_method_from_tx_type,
        shift_method_to_payment_method,
        shift_payment_method_label,
    )
    new_shift_method = shift_method_from_tx_type(transaction_type, fallback=item.payment_method)

    _set_model_attr(item, "transaction_type", transaction_type)
    _set_model_attr(item, "amount", new_amount)
    _set_model_attr(item, "room_number", room_number)
    _set_model_attr(item, "transaction_info", transaction_info)
    _set_model_attr(item, "recorder_id", _model_value(recorder.id) if recorder else _model_value(item.recorder_id))
    _set_model_attr(item, "branch_id", _model_value(branch.id))
    if type_changed:
        _set_model_attr(item, "payment_method", new_shift_method)

    # Cascade: cập nhật FolioTransaction + Payment khi user xác nhận và có liên kết
    cascade_summary = {
        "folio_transaction": False,
        "payment": False,
        "folio_rebalanced": False,
        "skipped_reason": None,
    }

    folio_tx_id = _model_value(item.folio_transaction_id)
    needs_cascade = folio_tx_id and (amount_changed or type_changed)

    if needs_cascade and not cascade_requested:
        cascade_summary["skipped_reason"] = "Chưa xác nhận cascade — chỉ cập nhật giao ca."
    elif needs_cascade and cascade_requested:
        folio_tx = db.query(FolioTransaction).filter(FolioTransaction.id == folio_tx_id).first()
        if folio_tx and not _model_value(folio_tx.is_voided):
            folio = db.query(Folio).filter(Folio.id == _model_value(folio_tx.folio_id)).first() if _model_value(folio_tx.folio_id) else None
            folio_status_val = folio.status.value if folio and folio.status and hasattr(folio.status, "value") else None
            folio_locked = folio_status_val == "CLOSED" and not is_admin(user_data)
            if folio_locked:
                cascade_summary["skipped_reason"] = "Folio đã đóng — chỉ admin/boss mới được cascade."
            else:
                if amount_changed:
                    _set_model_attr(folio_tx, "amount", money(-new_amount))
                if type_changed:
                    new_label = shift_payment_method_label(new_shift_method)
                    base_desc = (folio_tx.description or "").split(" (", 1)[0]
                    _set_model_attr(folio_tx, "description", f"{base_desc} ({new_label})")
                cascade_summary["folio_transaction"] = True

                # Cascade Payment table khi folio_tx.reference_type='payment'
                if folio_tx.reference_type == "payment" and folio_tx.reference_id:
                    payment_row = db.query(Payment).filter(Payment.id == folio_tx.reference_id).first()
                    if payment_row and not _model_value(payment_row.is_refunded):
                        if amount_changed:
                            _set_model_attr(payment_row, "amount", money(new_amount))
                        if type_changed:
                            _set_model_attr(payment_row, "method", shift_method_to_payment_method(new_shift_method))
                        cascade_summary["payment"] = True

                if folio is not None:
                    from ..services.folio_service import rebalance_folio
                    rebalance_folio(db, folio)
                    cascade_summary["folio_rebalanced"] = True

    db.commit()
    _invalidate_dashboard_cache()
    # SỬA: Refresh quan hệ
    db.refresh(item, ["branch", "recorder", "closer", "deleter"])
    return {
        "status": "success",
        "message": "Đã cập nhật giao dịch thành công.",
        "item": _serialize_transaction(item),
        "cascade_folio_updated": cascade_summary["folio_transaction"],  # backward compat
        "cascade_summary": cascade_summary,
    }

# ----------------------------------------------------------------------
# ENDPOINT CẬP NHẬT TRẠNG THÁI (SỬA)
# ----------------------------------------------------------------------
@router.post("/update/{item_id}", response_model=dict)
def update_shift_transaction_status( # SỬA
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    action: str = Form(...),
    # XOÁ: Các form field không cần thiết
):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Unauthorized")

    # SỬA: Query model mới
    item = db.query(ShiftReportTransaction).filter(ShiftReportTransaction.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy giao dịch.")
    
    if not (functional_code(user_data) == "letan" or is_manager(user_data)):
        raise HTTPException(status_code=403, detail="Bạn không có quyền thực hiện.")

    now = datetime.now(VN_TZ)
    
    # SỬA: Logic action mới
    if action == "close":
        if item.status != ShiftReportStatus.PENDING:
             raise HTTPException(status_code=400, detail="Giao dịch đã được xử lý trước đó.")
        _set_model_attr(item, "status", ShiftReportStatus.CLOSED)
        _set_model_attr(item, "closed_datetime", now)
        _set_model_attr(item, "closer_id", user_data.get("id")) # Giả định model có trường closer_id
    
    # XOÁ: Logic action "return" và "dispose"
    
    db.commit()
    _invalidate_dashboard_cache()
    # SỬA: Refresh TẤT CẢ các quan hệ
    db.refresh(item, ["branch", "recorder", "closer", "deleter"])
    return {"status": "success", "message": "Đã cập nhật trạng thái.", "item": _serialize_transaction(item)}

# ----------------------------------------------------------------------
# ENDPOINT XÓA (SỬA: Chỉ đổi tên model/status)
# ----------------------------------------------------------------------
@router.post("/delete/{item_id}", response_class=DecimalSafeJSONResponse)
def delete_shift_transaction( # SỬA
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    hard_delete: bool = Form(False) 
):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Unauthorized")

    # SỬA: Query model mới
    item = db.query(ShiftReportTransaction).filter(ShiftReportTransaction.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    user_role = user_data.get("role")
    now = datetime.now(VN_TZ)

    # Cascade: void FolioTransaction nếu có liên kết
    cascade_folio_voided = False
    if item.folio_transaction_id and item.status == ShiftReportStatus.PENDING:
        folio_tx = db.query(FolioTransaction).filter(
            FolioTransaction.id == item.folio_transaction_id
        ).first()
        if folio_tx and not folio_tx.is_voided:
            from ..services.folio_service import mark_transaction_void
            try:
                mark_transaction_void(db, folio_tx, f"Xóa từ ShiftReport: {item.transaction_info or item.transaction_code}", user_data.get("id"))
                cascade_folio_voided = True
            except Exception:
                pass  # Nếu cascade thất bại vẫn tiếp tục xóa ShiftReport

    if is_admin(user_data) and hard_delete:
        item_id_to_delete = item.id
        
        # 1. Tìm tất cả các bản ghi ShiftCloseLog có chứa ID của giao dịch này
        logs_to_update = db.query(ShiftCloseLog).filter(
            ShiftCloseLog.closed_transaction_ids.isnot(None), # Đảm bảo cột không phải NULL
            ShiftCloseLog.closed_transaction_ids.cast(JSONB).op("?")(str(item_id_to_delete))
        ).all()

        for log_entry in logs_to_update:
            # 2. Xóa ID của giao dịch khỏi danh sách
            current_ids = _json_id_list(log_entry.closed_transaction_ids)
            if not current_ids:
                logger.warning(f"closed_transaction_ids cho log {log_entry.id} không phải list hợp lệ: {log_entry.closed_transaction_ids}")
                continue

            current_ids = [tx_id for tx_id in current_ids if tx_id != item_id_to_delete]

            _set_model_attr(log_entry, "closed_transaction_ids", current_ids)

            if not current_ids:
                # Nếu không còn giao dịch nào, xóa bản ghi log
                db.delete(log_entry)
                logger.info(f"ShiftCloseLog {log_entry.id} đã bị xóa do không còn giao dịch nào.")
            else:
                # 3. Tính toán lại doanh thu dựa trên các giao dịch còn lại
                remaining_transactions = db.query(ShiftReportTransaction).filter(
                    ShiftReportTransaction.id.in_(current_ids)
                ).all()

                revenues = classify_log_revenues(remaining_transactions)
                _set_model_attr(log_entry, "closed_online_revenue", revenues["online_revenue"])
                _set_model_attr(log_entry, "closed_branch_revenue", revenues["branch_revenue"])
                _set_model_attr(log_entry, "pms_revenue", revenues["pms_net"])
                logger.info(f"ShiftCloseLog {log_entry.id} đã tính toán lại doanh thu sau khi xóa giao dịch {item_id_to_delete}.")

        db.delete(item)
        db.commit()
        _invalidate_dashboard_cache()
        return DecimalSafeJSONResponse({
            "status": "success",
            "message": "Đã xóa vĩnh viễn giao dịch.",
            "deleted_id": item_id_to_delete,
            "hard_delete": True,
            "cascade_folio_voided": cascade_folio_voided,
        })
    else:
        # SỬA: Dùng status mới
        _set_model_attr(item, "status", ShiftReportStatus.DELETED)
        _set_model_attr(item, "deleter_id", user_data.get("id"))
        _set_model_attr(item, "deleted_datetime", now)
        db.commit()
        db.refresh(item, ["branch", "recorder", "closer", "deleter"]) # SỬA
        return DecimalSafeJSONResponse({
            "status": "success",
            "message": "Đã xóa giao dịch thành công.",
            "item": _serialize_transaction(item), # SỬA
            "hard_delete": False,
            "cascade_folio_voided": cascade_folio_voided,
        })

# ----------------------------------------------------------------------
# ENDPOINT XÓA HÀNG LOẠT (SỬA: Chỉ đổi tên model/status)
# ----------------------------------------------------------------------
@router.post("/batch-delete", response_model=dict)
def batch_delete_shift_transactions( # SỬA
    payload: BatchDeleteTransactionsPayload, # SỬA: Dùng schema mới
    request: Request,
    db: Session = Depends(get_db)
):
    user_data = request.session.get("user")
    user_role = user_data.get("role") if user_data else None
    if not user_role:
        raise HTTPException(status_code=403, detail="Unauthorized")

    if not payload.ids:
        return DecimalSafeJSONResponse({"status": "noop", "message": "Không có mục nào được chọn."})

    try:
        if is_admin(user_data):
            # SỬA LỖI: Chỉ cho phép xóa vĩnh viễn các giao dịch chưa được kết ca.
            # Lấy các bản ghi hợp lệ để xóa từ DB.
            transactions_to_delete = db.query(ShiftReportTransaction).filter(
                ShiftReportTransaction.id.in_(payload.ids),
                ShiftReportTransaction.status != ShiftReportStatus.CLOSED
            ).all()
            
            if not transactions_to_delete:
                return DecimalSafeJSONResponse({
                    "status": "noop", 
                    "message": "Không có giao dịch hợp lệ nào để xóa (các giao dịch đã kết ca không thể xóa).",
                })

            ids_to_process = [t.id for t in transactions_to_delete]

            deleted_ids = []
            for item_id_to_delete in ids_to_process:
                item = db.query(ShiftReportTransaction).filter(ShiftReportTransaction.id == item_id_to_delete).first()
                if not item:
                    logger.warning(f"Giao dịch {item_id_to_delete} không tìm thấy để xóa hàng loạt.")
                    continue

                # 1. Tìm tất cả các bản ghi ShiftCloseLog có chứa ID của giao dịch này
                logs_to_update = db.query(ShiftCloseLog).filter(
                    ShiftCloseLog.closed_transaction_ids.isnot(None),
                    ShiftCloseLog.closed_transaction_ids.cast(JSONB).op("?")(str(item_id_to_delete))
                ).all()

                for log_entry in logs_to_update:
                    # 2. Xóa ID của giao dịch khỏi danh sách
                    current_ids = _json_id_list(log_entry.closed_transaction_ids)
                    if not current_ids:
                        logger.warning(f"closed_transaction_ids cho log {log_entry.id} không phải list hợp lệ: {log_entry.closed_transaction_ids}")
                        continue

                    current_ids = [tx_id for tx_id in current_ids if tx_id != item_id_to_delete]

                    _set_model_attr(log_entry, "closed_transaction_ids", current_ids)

                    if not current_ids:
                        db.delete(log_entry)
                        logger.info(f"ShiftCloseLog {log_entry.id} đã bị xóa do không còn giao dịch nào.")
                    else:
                        # 3. Tính toán lại doanh thu dựa trên các giao dịch còn lại
                        remaining_transactions = db.query(ShiftReportTransaction).filter(
                            ShiftReportTransaction.id.in_(current_ids)
                        ).all()

                        closed_online_revenue = 0
                        closed_branch_revenue = 0
                        revenues = classify_log_revenues(remaining_transactions)
                        closed_online_revenue = revenues["online_revenue"]
                        closed_branch_revenue = revenues["branch_revenue"]
                        _set_model_attr(log_entry, "closed_online_revenue", closed_online_revenue)
                        _set_model_attr(log_entry, "closed_branch_revenue", closed_branch_revenue)
                        _set_model_attr(log_entry, "pms_revenue", revenues["pms_net"])
                        logger.info(f"ShiftCloseLog {log_entry.id} revenues recalculated after transaction {item_id_to_delete} removal.")
                
                db.delete(item)
                deleted_ids.append(item_id_to_delete)
            db.commit()
            _invalidate_dashboard_cache()
            return DecimalSafeJSONResponse({
                "status": "success",
                "message": f"Đã xóa vĩnh viễn {len(deleted_ids)} mục.",
                "ids": ids_to_process,
                "hard_delete": True
            })
        else:
            now = datetime.now(VN_TZ)
            deleter_id = user_data.get("id") if user_data else None
            
            # SỬA LỖI: Chỉ cho phép xóa mềm các giao dịch đang PENDING.
            # Lấy các ID hợp lệ từ DB trước khi cập nhật.
            valid_ids_query = db.query(ShiftReportTransaction.id).filter(
                ShiftReportTransaction.id.in_(payload.ids),
                ShiftReportTransaction.status == ShiftReportStatus.PENDING
            )
            ids_to_process = [item[0] for item in valid_ids_query.all()]

            if not ids_to_process:
                return DecimalSafeJSONResponse({"status": "noop", "message": "Không có giao dịch nào ở trạng thái 'Chờ xử lý' để xóa."})

            num_updated = db.query(ShiftReportTransaction).filter(
                ShiftReportTransaction.id.in_(ids_to_process)
            ).update({
                "status": ShiftReportStatus.DELETED.value, # SỬA
                "deleter_id": deleter_id,
                "deleted_datetime": now
            }, synchronize_session=False)

            db.commit()
            _invalidate_dashboard_cache()

            # SỬA: Query model mới
            updated_items = db.query(ShiftReportTransaction).options(
                joinedload(ShiftReportTransaction.branch),
                joinedload(ShiftReportTransaction.recorder),
                joinedload(ShiftReportTransaction.closer),
                joinedload(ShiftReportTransaction.deleter)
            ).filter(ShiftReportTransaction.id.in_(ids_to_process)).all()
            
            serialized_items = [_serialize_transaction(item) for item in updated_items] # SỬA

            return DecimalSafeJSONResponse({
                "status": "success", 
                "message": f"Đã xóa thành công {num_updated} mục.",
                "ids": ids_to_process,
                "items": serialized_items,
                "hard_delete": False
            })
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi xóa hàng loạt giao dịch: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi server khi xóa.")

# app/api/shift_report.py

@router.post("/batch-close", response_model=dict)
def batch_close_transactions(
    payload: BatchCloseTransactionsPayload,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    API để kết ca hàng loạt các giao dịch đang ở trạng thái PENDING.
    SỬA: API này sẽ LUÔN TẠO MỘT BẢN GHI LOG (ShiftCloseLog) 
    ngay cả khi không có giao dịch nào đang chờ xử lý (để ghi nhận ca 0-đồng).
    """
    user_data = request.session.get("user")
    if not user_data or not (functional_code(user_data) == "letan" or is_manager(user_data)):
        raise HTTPException(status_code=403, detail="Bạn không có quyền thực hiện hành động này.")

    try:
        now = datetime.now(VN_TZ)
        closer_id = user_data.get("id")

        # 1. Lấy danh sách ID các giao dịch PENDING
        pending_transactions_query = db.query(ShiftReportTransaction.id).join(
            Branch, ShiftReportTransaction.branch_id == Branch.id
        ).filter(
            Branch.branch_code == payload.branch,
            ShiftReportTransaction.status == ShiftReportStatus.PENDING
        )
        transaction_ids_to_close = [item[0] for item in pending_transactions_query.all()]
        
        num_updated = 0
        updated_items = []
        closed_transactions = []
        close_summary = summarize_shift_transactions([])

        if transaction_ids_to_close:
            num_updated = db.query(ShiftReportTransaction).filter(
                ShiftReportTransaction.id.in_(transaction_ids_to_close)
            ).update({
                "status": ShiftReportStatus.CLOSED.value,
                "closer_id": closer_id,
                "closed_datetime": now
            }, synchronize_session=False)

            db.commit()

            closed_transactions = db.query(ShiftReportTransaction).filter(
                ShiftReportTransaction.id.in_(transaction_ids_to_close)
            ).all()
            close_summary = summarize_shift_transactions(closed_transactions)

            updated_items = db.query(ShiftReportTransaction).options(
                joinedload(ShiftReportTransaction.branch),
                joinedload(ShiftReportTransaction.recorder),
                joinedload(ShiftReportTransaction.closer),
                joinedload(ShiftReportTransaction.deleter)
            ).filter(ShiftReportTransaction.id.in_(transaction_ids_to_close)).all()

        try:
            if payload.auto_pms:
                revenues = classify_log_revenues(closed_transactions)
                pms_revenue_int = revenues["pms_net"]
                online_revenue_int = revenues["online_revenue"]
                branch_revenue_int = revenues["branch_revenue"]
            else:
                pms_val = payload.pms_revenue
                pms_revenue_int = int(pms_val.replace('.', '').replace(',', ''))
                revenues = classify_log_revenues(closed_transactions)
                online_revenue_int = revenues["online_revenue"]
                branch_revenue_int = revenues["branch_revenue"]

            branch_obj = db.query(Branch).filter(Branch.branch_code == payload.branch).first()
            if not branch_obj:
                logger.error(f"Không tìm thấy chi nhánh '{payload.branch}' để ghi log kết ca.", exc_info=True)

            new_log_entry = ShiftCloseLog(
                branch_id=branch_obj.id if branch_obj else None,
                closer_id=closer_id,
                closed_datetime=now,
                pms_revenue=pms_revenue_int,
                closed_online_revenue=online_revenue_int,
                closed_branch_revenue=branch_revenue_int,
                closed_transaction_ids=transaction_ids_to_close
            )
            db.add(new_log_entry)
            db.commit()
            _invalidate_dashboard_cache()

            db.refresh(new_log_entry)
            new_log_id = new_log_entry.id

        except Exception as log_error:
            logger.error(f"Lỗi khi ghi nhận ShiftCloseLog: {log_error}", exc_info=True)
            new_log_id = None

        return {
            "status": "success",
            "message": f"Đã kết ca thành công {num_updated} giao dịch.",
            "items": [_serialize_transaction(item) for item in updated_items],
            "log_id": new_log_id,
            "summary": close_summary,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi kết ca hàng loạt: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi server khi kết ca.")

@router.get("/api/dashboard-summary")
def get_dashboard_summary(
    request: Request,
    db: Session = Depends(get_db),
    chi_nhanh: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    transaction_type: Optional[str] = None
):
    """
    API Dashboard tổng hợp (Phiên bản tách biệt Query - Fix triệt để lỗi mất dữ liệu/biểu đồ)
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập.")

    # Cache key bao gồm role + active branch để Lễ tân không thấy data của Admin.
    user_role = user_data.get("role")
    user_branch = user_data.get("branch") or user_data.get("active_branch") or ""
    cache_key = (
        user_role,
        user_branch,
        chi_nhanh or "",
        status or "",
        from_date or "",
        to_date or "",
        transaction_type or "",
    )
    now_mono = _time.monotonic()
    with _dashboard_cache_lock:
        cached = _dashboard_cache.get(cache_key)
        if cached and (now_mono - cached[0]) < _DASHBOARD_CACHE_TTL_SECONDS:
            return DecimalSafeJSONResponse(content=cached[1])

    try:
        # --- 1. CHUẨN BỊ BỘ LỌC CHUNG (FILTERS) ---
        # Thay vì add filter trực tiếp vào query, ta tạo danh sách điều kiện để tái sử dụng
        
        # Lọc ngày tháng
        start_time, end_time = get_date_range_filter(from_date, to_date)
        date_filters_tx = [] # Filter cho bảng Transaction
        date_filters_log = [] # Filter cho bảng Log

        if start_time:
            date_filters_tx.append(ShiftReportTransaction.created_datetime >= start_time)
            date_filters_log.append(ShiftCloseLog.closed_datetime >= start_time)
        
        if end_time:
            date_filters_tx.append(ShiftReportTransaction.created_datetime <= end_time)
            date_filters_log.append(ShiftCloseLog.closed_datetime <= end_time)
        
        # Mặc định tháng hiện tại nếu không chọn ngày (cho Admin/Boss)
        if not start_time and not end_time and user_data.get("role") != 'letan':
            now = datetime.now(VN_TZ)
            date_filters_tx.append(extract('month', ShiftReportTransaction.created_datetime) == now.month)
            date_filters_tx.append(extract('year', ShiftReportTransaction.created_datetime) == now.year)
            date_filters_log.append(extract('month', ShiftCloseLog.closed_datetime) == now.month)
            date_filters_log.append(extract('year', ShiftCloseLog.closed_datetime) == now.year)

        # Lọc chi nhánh
        branch_filter_value = chi_nhanh

        if not is_admin(user_data):
            branch_filter_value = get_active_branch(request, db, user_data)

        # --- 2. QUERY 1: LỊCH SỬ KẾT CA (Recent Closes) ---
        # Query này độc lập, luôn Join Branch và Closer để lấy tên hiển thị
        history_query = db.query(ShiftCloseLog).join(ShiftCloseLog.branch).join(ShiftCloseLog.closer)
        
        if branch_filter_value:
            history_query = history_query.filter(Branch.branch_code == branch_filter_value)
        
        if date_filters_log:
            history_query = history_query.filter(*date_filters_log)

        # Khi đã có bộ lọc thời gian (chọn ngày, hoặc mặc định tháng hiện tại của
        # admin/boss), kết quả đã bị giới hạn trong cửa sổ thời gian nên nâng trần
        # để không cắt cụt danh sách giữa tháng. Chỉ giữ trần thấp khi không có
        # bộ lọc nào (vd: letan không chọn ngày) để tránh tải toàn bộ lịch sử.
        recent_limit = 1000 if date_filters_log else 50
        recent_closes = history_query.with_entities(
            ShiftCloseLog.id,
            ShiftCloseLog.pms_revenue,
            ShiftCloseLog.closed_online_revenue,
            ShiftCloseLog.closed_branch_revenue,
            ShiftCloseLog.closed_datetime,
            Branch.branch_code,
            User.name.label("closer_name")
        ).order_by(desc(ShiftCloseLog.closed_datetime)).limit(recent_limit).all()

        # --- 3. QUERY 2: TỔNG HỢP LOG (Log Summary) ---
        # Query này để tính tổng PMS Revenue, Cash Revenue
        summary_log_query = db.query(ShiftCloseLog)
        
        # Nếu có lọc chi nhánh, phải join bảng Branch
        if branch_filter_value:
            summary_log_query = summary_log_query.join(ShiftCloseLog.branch).filter(Branch.branch_code == branch_filter_value)
        
        if date_filters_log:
            summary_log_query = summary_log_query.filter(*date_filters_log)

        log_summary = summary_log_query.with_entities(
            func.sum(ShiftCloseLog.pms_revenue).label('total_pms'),
            func.sum(ShiftCloseLog.closed_online_revenue).label('total_closed_online'),
            func.sum(ShiftCloseLog.closed_branch_revenue).label('total_closed_branch')
        ).first()
        total_pms_revenue = 0.0
        total_cash_revenue = 0.0
        if log_summary is not None:
            total_pms_revenue = float(log_summary.total_pms or 0.0)
            total_cash_revenue = float(log_summary.total_closed_branch or 0.0)

        # --- 4. QUERY 3: CHI TIẾT GIAO DỊCH (Transaction Summary) ---
        # Query này để tính Pending/Closed của Online, Branch...
        tx_query = db.query(ShiftReportTransaction)

        # Xử lý join và filter cho Transaction
        if branch_filter_value:
             tx_query = tx_query.join(ShiftReportTransaction.branch).filter(Branch.branch_code == branch_filter_value)

        # Lọc status
        if user_data.get("role") == 'letan':
            tx_query = tx_query.filter(ShiftReportTransaction.status == ShiftReportStatus.PENDING.value)
        else:
            tx_query = tx_query.filter(ShiftReportTransaction.status.in_([ShiftReportStatus.CLOSED.value, ShiftReportStatus.PENDING.value]))
            if status:
                 tx_query = tx_query.filter(ShiftReportTransaction.status == status)

        if transaction_type:
            tx_query = tx_query.filter(ShiftReportTransaction.transaction_type == transaction_type)
        
        # [FIX] Logic lọc ngày thông minh:
        # - Đã kết ca (CLOSED): Lọc theo ngày kết ca (closed_datetime) -> Để khớp với tiền ghi nhận (ShiftCloseLog)
        # - Chưa kết ca (PENDING): Lọc theo ngày tạo (created_datetime) -> Để hiển thị công việc tồn đọng hiện tại
        
        date_conditions = []
        if start_time:
             # Điều kiện: (Status=CLOSED AND closed >= start) OR (Status=PENDING AND created >= start)
             # Tuy nhiên, để tối ưu và chính xác, ta kết hợp cả start/end vào từng cụm
             pass 

        # Xây dựng bộ lọc OR
        or_conditions = []
        
        # 1. Logic cho CLOSED
        closed_filters = [ShiftReportTransaction.status == ShiftReportStatus.CLOSED.value]
        if start_time:
            closed_filters.append(ShiftReportTransaction.closed_datetime >= start_time)
        if end_time:
            closed_filters.append(ShiftReportTransaction.closed_datetime <= end_time)
        # Nếu filter theo năm/tháng (mặc định)
        if not start_time and not end_time and user_data.get("role") != 'letan' and date_filters_log:
             # Tái sử dụng date_filters_log nhưng áp dụng cho closed_datetime của transaction
             # Lưu ý: date_filters_log đang áp dụng cho ShiftCloseLog, cần map sang Transaction
             now = datetime.now(VN_TZ)
             closed_filters.append(extract('month', ShiftReportTransaction.closed_datetime) == now.month)
             closed_filters.append(extract('year', ShiftReportTransaction.closed_datetime) == now.year)

        # 2. Logic cho PENDING
        pending_filters = [ShiftReportTransaction.status == ShiftReportStatus.PENDING.value]
        if start_time:
            pending_filters.append(ShiftReportTransaction.created_datetime >= start_time)
        if end_time:
            pending_filters.append(ShiftReportTransaction.created_datetime <= end_time)
        if not start_time and not end_time and user_data.get("role") != 'letan':
             now = datetime.now(VN_TZ)
             pending_filters.append(extract('month', ShiftReportTransaction.created_datetime) == now.month)
             pending_filters.append(extract('year', ShiftReportTransaction.created_datetime) == now.year)

        # Kết hợp
        # AND (...closed flags...)
        closed_group = and_(*closed_filters)
        pending_group = and_(*pending_filters)

        tx_query = tx_query.filter(or_(closed_group, pending_group))

        # [REMOVED] date_filters_tx cũ (chỉ lọc theo created_datetime)
        # if date_filters_tx:
        #    tx_query = tx_query.filter(*date_filters_tx)

        tx_items = tx_query.all()
        closed_summary = summarize_shift_transactions([
            tx for tx in tx_items
            if _shift_enum_value(tx.status) == ShiftReportStatus.CLOSED.value
        ])
        pending_summary = summarize_shift_transactions([
            tx for tx in tx_items
            if _shift_enum_value(tx.status) == ShiftReportStatus.PENDING.value
        ])

        # --- 5. QUERY 4: BẢNG XẾP HẠNG (Ranking) ---
        # Chỉ chạy khi Admin/Boss và KHÔNG chọn chi nhánh cụ thể
        final_branch_ranking = []
        if is_admin(user_data) and not chi_nhanh:
            # Ranking dựa trên PMS từ bảng Log
            ranking_query = db.query(
                Branch.branch_code,
                func.sum(ShiftCloseLog.pms_revenue).label('total_pms')
            ).join(ShiftCloseLog.branch) # Join ngược từ Branch -> Log hoặc Log -> Branch đều được, ở đây query Log group by Branch
            
            # Reset query để join chuẩn từ Log
            ranking_query = db.query(ShiftCloseLog).join(ShiftCloseLog.branch)
            
            if date_filters_log:
                ranking_query = ranking_query.filter(*date_filters_log)
            
            pms_ranking = ranking_query.with_entities(
                Branch.branch_code,
                func.sum(ShiftCloseLog.pms_revenue).label('total_pms')
            ).group_by(Branch.branch_code).order_by(desc('total_pms')).all()

            # Lấy thêm info pending/closed revenue từ Transaction để hiển thị phụ (nếu cần)
            # Để đơn giản và nhanh, ta chỉ map recorded revenue vào
            for item in pms_ranking:
                final_branch_ranking.append({
                    "branch": item.branch_code,
                    "pms_revenue": float(item.total_pms or 0),
                    "closed_revenue": 0, # Có thể query thêm nếu cần chi tiết
                    "pending_revenue": 0
                })

        # --- 6. TRẢ VỀ KẾT QUẢ ---
        result_payload = {
            "status": "success",
            "data": {
                "by_branch": final_branch_ranking,
                "total_pms_revenue": float(total_pms_revenue or 0),
                "total_cash_revenue": float(total_cash_revenue or 0),
                "recent_closes": ([{
                        "id": r.id,
                        "pms_revenue": float(r.pms_revenue or 0),
                        "closed_online_revenue": float(r.closed_online_revenue or 0),
                        "closed_branch_revenue": float(r.closed_branch_revenue or 0),
                        "closed_datetime": r.closed_datetime.isoformat(),
                        "branch_code": r.branch_code,
                        "closer_name": r.closer_name
                    } for r in recent_closes] if recent_closes else []),
                "by_type": {
                    # closed_online/closed_branch lấy từ ShiftCloseLog để khớp với Biên bản giao ca
                    # (classify_log_revenues dùng transaction_type, summarize dùng payment_method — hai cách cho kết quả khác nhau)
                    "closed_online": float(log_summary.total_closed_online or 0) if log_summary else 0,
                    "pending_online": float(pending_summary["non_cash"] or 0),
                    "closed_expense": float(closed_summary["refund_outflow"] or 0),
                    "pending_expense": float(pending_summary["refund_outflow"] or 0),
                    "closed_branch": float(log_summary.total_closed_branch or 0) if log_summary else 0,
                    "pending_branch": float(pending_summary["cash"] or 0),
                    "closed_card": float(closed_summary["card"] or 0),
                    "pending_card": float(pending_summary["card"] or 0),
                    "closed_ota": float(closed_summary["ota"] or 0),
                    "pending_ota": float(pending_summary["ota"] or 0),
                    "closed_company_unc": float(closed_summary["company_unc"] or 0),
                    "pending_company_unc": float(pending_summary["company_unc"] or 0),
                    "closed_debt": float(closed_summary["debt"] or 0),
                    "pending_debt": float(pending_summary["debt"] or 0),
                    "closed_net": float(closed_summary["net_total"] or 0),
                    "pending_net": float(pending_summary["net_total"] or 0),
                }
            }
        }
        with _dashboard_cache_lock:
            _dashboard_cache[cache_key] = (_time.monotonic(), result_payload)
        return DecimalSafeJSONResponse(content=result_payload)

    except Exception as e:
        logger.error(f"Lỗi khi lấy dữ liệu dashboard giao ca: {e}", exc_info=True)
        # Trả về data rỗng thay vì 500 để Frontend không bị crash
        return DecimalSafeJSONResponse(content={
            "status": "error", 
            "message": str(e),
            "data": { 
                "by_branch": [], "recent_closes": [], 
                "by_type": {"closed_online":0, "pending_online":0, "closed_branch":0, "pending_branch":0},
                "total_pms_revenue": 0, "total_cash_revenue": 0 
            }
        })

@router.get("/api/shift-close-details/{log_id}", response_model=dict)
def get_shift_close_details(
    log_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user_data = request.session.get("user")
    if not user_data or not (functional_code(user_data) == "letan" or is_manager(user_data)):
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập chức năng này.")

    log_entry = db.query(ShiftCloseLog).options(
        joinedload(ShiftCloseLog.branch),
        joinedload(ShiftCloseLog.closer)
    ).filter(ShiftCloseLog.id == log_id).first()

    if not log_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi kết ca.")

    transaction_ids = _json_id_list(log_entry.closed_transaction_ids)
    transactions = []
    
    if transaction_ids:
        # --- SỬA LỖI Ở ĐÂY: Thêm joinedload để tránh lỗi Lazy Loading ---
        transactions = db.query(ShiftReportTransaction).options(
            joinedload(ShiftReportTransaction.branch),
            joinedload(ShiftReportTransaction.recorder),
            joinedload(ShiftReportTransaction.closer),
            joinedload(ShiftReportTransaction.deleter)
        ).filter(ShiftReportTransaction.id.in_(transaction_ids)).all()

    log_details = {
        "id": log_entry.id,
        "pms_revenue": float(log_entry.pms_revenue or 0),
        "closed_online_revenue": float(log_entry.closed_online_revenue or 0),
        "closed_branch_revenue": float(log_entry.closed_branch_revenue or 0),
        "cash_revenue": float((log_entry.pms_revenue or 0) - (log_entry.closed_online_revenue or 0) - (log_entry.closed_branch_revenue or 0)),
        "closed_datetime": log_entry.closed_datetime.isoformat(),
        "branch_code": log_entry.branch.branch_code if log_entry.branch else "N/A",
        "closer_name": log_entry.closer.name if log_entry.closer else "N/A"
    }

    return DecimalSafeJSONResponse(content={
        "status": "success",
        "log_details": log_details,
        "transactions": [_serialize_transaction(tx) for tx in transactions]
    })

@router.post("/api/undo-shift-close/{log_id}", response_model=dict)
def undo_shift_close(
    log_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    API để hoàn tác một lần kết ca.
    - Xóa bản ghi ShiftCloseLog.
    - Chuyển trạng thái các giao dịch liên quan về PENDING.
    """
    user_data = request.session.get("user")
    if not user_data or not is_admin(user_data):
        raise HTTPException(status_code=403, detail="Bạn không có quyền thực hiện hành động này.")

    log_entry = db.query(ShiftCloseLog).filter(ShiftCloseLog.id == log_id).first()
    if not log_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi kết ca.")

    transaction_ids = _json_id_list(log_entry.closed_transaction_ids)

    try:
        # Hoàn tác trạng thái các giao dịch
        if transaction_ids:
            db.query(ShiftReportTransaction).filter(
                ShiftReportTransaction.id.in_(transaction_ids)
            ).update({"status": ShiftReportStatus.PENDING.value}, synchronize_session=False)

        # Xóa bản ghi log
        db.delete(log_entry)
        db.commit()
        _invalidate_dashboard_cache()
        return {"status": "success", "message": "Đã hoàn tác kết ca thành công."}
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi hoàn tác kết ca (log_id: {log_id}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi server khi hoàn tác kết ca.")

@router.delete("/api/delete-shift-close/{log_id}", response_model=dict)
def delete_shift_close(
    log_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    API để xóa vĩnh viễn một lần kết ca và tất cả các giao dịch liên quan.
    Chỉ dành cho admin/boss.
    """
    user_data = request.session.get("user")
    if not user_data or not is_admin(user_data):
        raise HTTPException(status_code=403, detail="Bạn không có quyền thực hiện hành động này.")

    log_entry = db.query(ShiftCloseLog).filter(ShiftCloseLog.id == log_id).first()
    if not log_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi kết ca.")

    transaction_ids = _json_id_list(log_entry.closed_transaction_ids)

    try:
        # Xóa các giao dịch liên quan
        if transaction_ids:
            db.query(ShiftReportTransaction).filter(
                ShiftReportTransaction.id.in_(transaction_ids)
            ).delete(synchronize_session=False)

        # Xóa bản ghi log
        db.delete(log_entry)
        db.commit()
        _invalidate_dashboard_cache()
        return {"status": "success", "message": "Đã xóa vĩnh viễn lần kết ca và các giao dịch liên quan."}
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi xóa vĩnh viễn kết ca (log_id: {log_id}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi server khi xóa kết ca.")

@router.get("/api/monthly-summary")
def get_monthly_summary(
    request: Request,
    year: int,
    db: Session = Depends(get_db)
):
    """
    API để lấy tổng hợp doanh thu theo từng tháng của một năm.
    Chỉ tính các giao dịch đã ở trạng thái "Đã kết ca".
    """
    user_data = request.session.get("user")
    if not user_data or not is_admin(user_data):
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập chức năng này.")

    try:
        # Dùng đúng danh sách TransactionType như classify_log_revenues
        # để các báo cáo không lệch với số đã chốt trong ShiftCloseLog.
        online_type_values = [t.value for t in ONLINE_REVENUE_TYPES]
        branch_type_values = [t.value for t in BRANCH_REVENUE_TYPES]

        online_revenue_case = case(
            (ShiftReportTransaction.transaction_type.in_(online_type_values),
             ShiftReportTransaction.amount),
            else_=0
        )
        branch_revenue_case = case(
            (ShiftReportTransaction.transaction_type.in_(branch_type_values),
             ShiftReportTransaction.amount),
            else_=0
        )
        refund_case = case(
            (ShiftReportTransaction.transaction_type == TransactionType.CASH_EXPENSE.value,
             ShiftReportTransaction.amount),
            else_=0
        )

        # Query để lấy tổng doanh thu theo tháng
        results = db.query(
            extract('month', ShiftReportTransaction.created_datetime).label('month'),
            func.sum(online_revenue_case).label('online_revenue'),
            func.sum(branch_revenue_case).label('branch_revenue'),
            func.sum(refund_case).label('refund_outflow'),
        ).filter(
            extract('year', ShiftReportTransaction.created_datetime) == year,
            ShiftReportTransaction.status == ShiftReportStatus.CLOSED
        ).group_by(
            extract('month', ShiftReportTransaction.created_datetime)
        ).order_by(
            extract('month', ShiftReportTransaction.created_datetime)
        ).all()

        # Chuyển đổi kết quả thành dictionary để dễ xử lý
        summary_by_month = {res.month: res._asdict() for res in results}

        # Tạo mảng 12 tháng, điền dữ liệu từ query hoặc để là 0
        final_summary = [
            {
                "month": i,
                "online_revenue": float(summary_by_month.get(i, {}).get('online_revenue') or 0.0),
                "branch_revenue": float(summary_by_month.get(i, {}).get('branch_revenue') or 0.0),
                "refund_outflow": float(summary_by_month.get(i, {}).get('refund_outflow') or 0.0),
            }
            for i in range(1, 13)
        ]

        return DecimalSafeJSONResponse(content={"status": "success", "data": final_summary})
    except Exception as e:
        logger.error(f"Lỗi khi lấy báo cáo tháng: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi server khi lấy báo cáo tháng.")

class UndoTransactionPayload(BaseModel):
    log_id: int
    transaction_id: int

@router.post("/api/undo-transaction-from-log", response_model=dict)
def undo_transaction_from_log(
    payload: UndoTransactionPayload,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    API để hoàn tác một giao dịch cụ thể từ một lần kết ca.
    """
    user_data = request.session.get("user")
    if not user_data or not is_admin(user_data):
        raise HTTPException(status_code=403, detail="Bạn không có quyền thực hiện hành động này.")

    log_entry = db.query(ShiftCloseLog).filter(ShiftCloseLog.id == payload.log_id).first()
    if not log_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi kết ca.")

    transaction_to_undo = db.query(ShiftReportTransaction).filter(ShiftReportTransaction.id == payload.transaction_id).first()
    if not transaction_to_undo:
        raise HTTPException(status_code=404, detail="Không tìm thấy giao dịch để hoàn tác.")

    log_transaction_ids = _json_id_list(log_entry.closed_transaction_ids)
    transaction_id = _model_value(transaction_to_undo.id)
    if transaction_id not in log_transaction_ids:
        raise HTTPException(status_code=400, detail="Giao dịch không thuộc về lần kết ca này.")

    # Hoàn tác giao dịch
    _set_model_attr(transaction_to_undo, "status", ShiftReportStatus.PENDING)
    _set_model_attr(transaction_to_undo, "closer_id", None)
    _set_model_attr(transaction_to_undo, "closed_datetime", None)

    # Cập nhật lại bản ghi log
    remaining_ids = [tx_id for tx_id in log_transaction_ids if tx_id != transaction_id]
    _set_model_attr(log_entry, "closed_transaction_ids", remaining_ids)

    if remaining_ids:
        remaining_transactions = db.query(ShiftReportTransaction).filter(
            ShiftReportTransaction.id.in_(remaining_ids)
        ).all()

        revenues = classify_log_revenues(remaining_transactions)
        _set_model_attr(log_entry, "closed_online_revenue", revenues["online_revenue"])
        _set_model_attr(log_entry, "closed_branch_revenue", revenues["branch_revenue"])
        # Recompute pms_revenue to stay consistent with inflow - refund
        _set_model_attr(log_entry, "pms_revenue", revenues["pms_net"])
    else:
        # Nếu không còn giao dịch nào, xóa luôn bản ghi log
        db.delete(log_entry)

    db.commit()
    _invalidate_dashboard_cache()
    return {"status": "success", "message": "Đã hoàn tác giao dịch thành công."}


@router.get("/api/pending-summary")
def get_pending_summary(
    request: Request,
    branch: str,
    db: Session = Depends(get_db)
):
    """
    API để lấy tổng số tiền của các giao dịch đang ở trạng thái PENDING
    cho một chi nhánh cụ thể.

    Tối ưu: dùng SQL aggregate (SUM + CASE) thay vì load mọi row vào RAM rồi
    summarize trong Python. Chỉ trả về field client thực sự đọc.
    """
    user_data = request.session.get("user")
    if not user_data or not (functional_code(user_data) == "letan" or is_manager(user_data)):
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập chức năng này.")

    try:
        refund_type = TransactionType.CASH_EXPENSE.value
        refund_case = case(
            (ShiftReportTransaction.transaction_type == refund_type, ShiftReportTransaction.amount),
            else_=0,
        )
        inflow_case = case(
            (ShiftReportTransaction.transaction_type != refund_type, ShiftReportTransaction.amount),
            else_=0,
        )

        row = (
            db.query(
                func.coalesce(func.sum(inflow_case), 0).label("gross_inflow"),
                func.coalesce(func.sum(refund_case), 0).label("refund_outflow"),
                func.count(ShiftReportTransaction.id).label("count"),
            )
            .join(Branch, ShiftReportTransaction.branch_id == Branch.id)
            .filter(
                Branch.branch_code == branch,
                ShiftReportTransaction.status == ShiftReportStatus.PENDING,
            )
            .first()
        )

        gross_inflow = float(row.gross_inflow or 0) if row else 0.0
        refund_outflow = float(row.refund_outflow or 0) if row else 0.0
        net_total = gross_inflow - refund_outflow

        return DecimalSafeJSONResponse(content={
            "status": "success",
            "total_pending_amount": net_total,
            "summary": {
                "gross_inflow": gross_inflow,
                "refund_outflow": refund_outflow,
                "net_total": net_total,
                "count": int(row.count or 0) if row else 0,
            },
        })
    except Exception as e:
        logger.error(f"Lỗi khi lấy tổng hợp giao dịch chờ xử lý cho chi nhánh '{branch}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi server khi lấy dữ liệu.")

class DeleteTransactionFromLogPayload(BaseModel):
    log_id: int

# app/api/shift_report.py

@router.get("/api/all-pending")
def get_all_pending_for_branch(
    request: Request,
    branch: str, # Nhận chi nhánh từ query param
    db: Session = Depends(get_db),
    # THÊM: Chấp nhận các bộ lọc từ query params
    search: Optional[str] = None,
    transaction_type: Optional[str] = None
):
    """
    API mới: Lấy TẤT CẢ các giao dịch đang "Chờ xử lý"
    cho một chi nhánh cụ thể (dùng cho modal Giao Ca của Lễ tân).
    (ĐÃ SỬA: API này giờ đây chấp nhận các bộ lọc)
    """
    user_data = request.session.get("user")
    if not user_data or user_data.get("role") != "letan":
        raise HTTPException(status_code=403, detail="Chỉ Lễ tân mới có quyền truy cập.")
    
    # === BẮT ĐẦU SỬA LỖI LOGIC BẢO MẬT ===
    # Bảo mật: Đảm bảo Lễ tân chỉ truy vấn đúng chi nhánh HỌ ĐANG LÀM VIỆC (active_branch)
    active_branch = get_active_branch(request, db, user_data)
    if active_branch != branch:
        logger.warning(f"Bảo mật: Lễ tân {user_data.get('code')} (active: {active_branch}) đang cố truy cập Giao ca của chi nhánh {branch}.")
        raise HTTPException(status_code=403, detail="Không được phép truy cập dữ liệu Giao ca của chi nhánh khác.")

    try:
        # --- SỬA ĐOẠN GỌI HÀM NÀY ---
        items, total_records = _get_filtered_transactions(
            db=db,
            user_data=user_data,
            per_page=999,
            page=1,
            search=search,
            status="PENDING",
            chi_nhanh=branch,
            
            # LỖI Ở ĐÂY: Bạn đang truyền 'created_date' nhưng hàm _get_filtered_transactions đã xóa tham số này
            # created_date=created_date,  <-- XÓA DÒNG NÀY
            
            # THAY BẰNG: Truyền None hoặc giá trị rỗng cho from_date/to_date 
            # (Vì giao ca là lấy tất cả pending, không giới hạn ngày)
            from_date=None, 
            to_date=None,
            
            transaction_type=transaction_type,
            active_branch_for_letan=branch
        )
        
        results = [_serialize_transaction(item) for item in items]

        return DecimalSafeJSONResponse(content={
            "status": "success", 
            "transactions": results 
        })
    except Exception as e:
        logger.error(f"Lỗi khi lấy tất cả giao dịch chờ xử lý cho chi nhánh '{branch}': {e}", exc_info=True)
        # Sửa lại return để Frontend nhận được thông báo lỗi rõ ràng hơn thay vì crash
        return DecimalSafeJSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@router.post("/api/delete-transaction-from-log/{transaction_id}", response_model=dict)
def delete_transaction_from_log(
    transaction_id: int,
    payload: DeleteTransactionFromLogPayload,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    API để xóa vĩnh viễn một giao dịch cụ thể từ một lần kết ca.
    - Xóa bản ghi ShiftReportTransaction.
    - Cập nhật lại ShiftCloseLog (xóa ID, tính lại doanh thu).
    - Trả về thông tin log đã cập nhật.
    """
    user_data = request.session.get("user")
    if not user_data or not is_admin(user_data):
        raise HTTPException(status_code=403, detail="Bạn không có quyền thực hiện hành động này.")

    # SỬA LỖI: Eager load các relationship 'branch' và 'closer' để tránh DetachedInstanceError
    log_entry = db.query(ShiftCloseLog).options(
        joinedload(ShiftCloseLog.branch),
        joinedload(ShiftCloseLog.closer)
    ).filter(ShiftCloseLog.id == payload.log_id).first()
    if not log_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi kết ca.")

    transaction_to_delete = db.query(ShiftReportTransaction).filter(ShiftReportTransaction.id == transaction_id).first()
    if not transaction_to_delete:
        raise HTTPException(status_code=404, detail="Không tìm thấy giao dịch để xóa.")

    log_transaction_ids = _json_id_list(log_entry.closed_transaction_ids)
    transaction_id = _model_value(transaction_to_delete.id)
    if transaction_id not in log_transaction_ids:
        raise HTTPException(status_code=400, detail="Giao dịch không thuộc về lần kết ca này.")

    # Xóa giao dịch
    db.delete(transaction_to_delete)

    # Cập nhật lại bản ghi log
    remaining_ids = [tx_id for tx_id in log_transaction_ids if tx_id != transaction_id]
    _set_model_attr(log_entry, "closed_transaction_ids", remaining_ids)

    if not remaining_ids:
        # Nếu không còn giao dịch nào, xóa luôn bản ghi log
        db.delete(log_entry)
    else:
        # SỬA LỖI: Nếu còn giao dịch, phải tính toán lại doanh thu
        remaining_transactions = db.query(ShiftReportTransaction).filter(ShiftReportTransaction.id.in_(remaining_ids)).all()

        closed_online_revenue = 0
        closed_branch_revenue = 0
        for tx in remaining_transactions:
                    # SỬA: Thêm CASH_EXPENSE vào list cộng
                    if tx.transaction_type in [
                        TransactionType.OTA,
                        TransactionType.UNC,
                        TransactionType.CARD,
                        TransactionType.COMPANY_ACCOUNT,
                        TransactionType.CASH_EXPENSE,
                        TransactionType.OTHER
                    ]:
                        closed_online_revenue += _model_value(tx.amount)

                    elif tx.transaction_type == TransactionType.BRANCH_ACCOUNT:
                        closed_branch_revenue += _model_value(tx.amount)

        _set_model_attr(log_entry, "closed_online_revenue", closed_online_revenue)
        _set_model_attr(log_entry, "closed_branch_revenue", closed_branch_revenue)

    db.commit()
    _invalidate_dashboard_cache()

    # Chuẩn bị dữ liệu log đã cập nhật để trả về
    updated_log_details = {
        "id": log_entry.id,
        "pms_revenue": log_entry.pms_revenue,
        "closed_online_revenue": log_entry.closed_online_revenue,
        "closed_branch_revenue": log_entry.closed_branch_revenue,
        "cash_revenue": log_entry.pms_revenue - log_entry.closed_online_revenue - log_entry.closed_branch_revenue,
        "closed_datetime": log_entry.closed_datetime.isoformat(),
        "branch_code": log_entry.branch.branch_code if log_entry.branch else "N/A",
        "closer_name": log_entry.closer.name if log_entry.closer else "N/A"
    }

    return {"status": "success", "message": "Đã xóa giao dịch và cập nhật báo cáo kết ca.", "updated_log": updated_log_details}


# ====================================================================
# API MỚI: Lấy PMS checkout revenue để auto-fill khi kết ca
# ====================================================================

@router.get("/api/pms-pending-summary", response_model=dict)
def get_pms_pending_summary(
    request: Request,
    branch: str,
    db: Session = Depends(get_db),
):
    """
    Lấy tổng PMS checkout revenue chưa kết ca.
    Dùng để auto-fill recorded revenue khi kết ca.
    """
    user_data = request.session.get("user")
    if not user_data or not (functional_code(user_data) == "letan" or is_manager(user_data)):
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập chức năng này.")

    try:
        from ..services.shift_report_service import get_unclosed_pms_checkouts

        branch_obj = db.query(Branch).filter(Branch.branch_code == branch).first()
        if not branch_obj:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy chi nhánh: {branch}")

        result = get_unclosed_pms_checkouts(db, _model_value(branch_obj.id))

        return DecimalSafeJSONResponse(content={
            "status": "success",
            "total_pms_revenue": float(result["total"]),
            "by_method": {k: float(v) for k, v in result["by_method"].items()},
            "count": result["count"],
            "transactions": [
                {
                    "id": tx.id,
                    "transaction_code": tx.transaction_code,
                    "amount": float(tx.amount),
                    "payment_method": tx.payment_method.value if tx.payment_method else "CASH",
                    "room_number": tx.room_number,
                    "transaction_info": tx.transaction_info,
                    "folio_id": tx.folio_id,
                    "stay_id": tx.stay_id,
                }
                for tx in result["transactions"]
            ],
        })
    except Exception as e:
        logger.error(f"Lỗi khi lấy PMS pending summary cho chi nhánh '{branch}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi server khi lấy dữ liệu PMS.")


# ====================================================================
# API MỚI: Thống kê doanh thu cho Dashboard
# ====================================================================

@router.get("/api/analytics")
def get_shift_analytics(
    request: Request,
    db: Session = Depends(get_db),
    month: Optional[int] = None,
    year: Optional[int] = None,
    chi_nhanh: Optional[str] = None,
    view: Optional[str] = "month",
):
    """
    API Dashboard thống kê doanh thu theo tháng/năm và chi nhánh.
    Chỉ dành cho Admin/Boss/Quản lý.
    """
    user_data = request.session.get("user")
    if not user_data or not (functional_code(user_data) == "letan" or is_manager(user_data)):
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập chức năng này.")

    branch_filter_value = chi_nhanh
    if not is_admin(user_data):
        branch_filter_value = get_active_branch(request, db, user_data)

    now = datetime.now(VN_TZ)
    filter_month = month if month else now.month
    filter_year = year if year else now.year
    view_mode = "year" if view == "year" else "month"

    def _apply_branch(query, relation):
        if not branch_filter_value:
            return query
        return query.join(relation).filter(Branch.branch_code == branch_filter_value)

    def _log_period_filter(query):
        query = query.filter(extract('year', ShiftCloseLog.closed_datetime) == filter_year)
        if view_mode == "month":
            query = query.filter(extract('month', ShiftCloseLog.closed_datetime) == filter_month)
        return query

    def _tx_period_filter(query):
        if view_mode == "month":
            closed_period = and_(
                ShiftReportTransaction.status == ShiftReportStatus.CLOSED,
                extract('month', ShiftReportTransaction.closed_datetime) == filter_month,
                extract('year', ShiftReportTransaction.closed_datetime) == filter_year,
            )
            pending_period = and_(
                ShiftReportTransaction.status == ShiftReportStatus.PENDING,
                extract('month', ShiftReportTransaction.created_datetime) == filter_month,
                extract('year', ShiftReportTransaction.created_datetime) == filter_year,
            )
        else:
            closed_period = and_(
                ShiftReportTransaction.status == ShiftReportStatus.CLOSED,
                extract('year', ShiftReportTransaction.closed_datetime) == filter_year,
            )
            pending_period = and_(
                ShiftReportTransaction.status == ShiftReportStatus.PENDING,
                extract('year', ShiftReportTransaction.created_datetime) == filter_year,
            )
        return query.filter(or_(closed_period, pending_period))

    try:
        log_query = _log_period_filter(db.query(ShiftCloseLog))
        log_query = _apply_branch(log_query, ShiftCloseLog.branch)
        log_summary = log_query.with_entities(
            func.sum(ShiftCloseLog.pms_revenue).label('total_pms'),
            func.sum(ShiftCloseLog.closed_online_revenue).label('total_online'),
            func.sum(ShiftCloseLog.closed_branch_revenue).label('total_branch'),
            func.count(ShiftCloseLog.id).label('shift_count'),
        ).first()

        tx_query = _tx_period_filter(db.query(ShiftReportTransaction))
        tx_query = _apply_branch(tx_query, ShiftReportTransaction.branch)
        closed_transactions = tx_query.all()
        closed_summary = summarize_shift_transactions(closed_transactions)
        type_breakdown = closed_summary["by_type"]
        total_tx_count = closed_summary["count"]
        log_total_pms = log_summary.total_pms if log_summary is not None else None
        log_total_online = log_summary.total_online if log_summary is not None else None
        log_total_branch = log_summary.total_branch if log_summary is not None else None
        shift_count = log_summary.shift_count if log_summary is not None and log_summary.shift_count is not None else 0

        total_pms = float(log_total_pms or closed_summary["net_total"] or 0)
        total_online_closed = float(log_total_online or closed_summary["non_cash"] or 0)
        total_branch_closed = float(log_total_branch or 0)
        total_cash = total_pms - total_online_closed - total_branch_closed
        total_debt = float(closed_summary["debt"] or 0)
        total_ota = float(closed_summary["ota"] or 0)
        total_card = float(closed_summary["card"] or 0)
        total_expense = float(closed_summary["refund_outflow"] or 0)
        reconciled_total = float(closed_summary["net_total"] or 0)
        reconciliation_gap = total_pms - reconciled_total

        branch_rows_query = _log_period_filter(db.query(ShiftCloseLog).join(ShiftCloseLog.branch))
        if branch_filter_value:
            branch_rows_query = branch_rows_query.filter(Branch.branch_code == branch_filter_value)
        branch_rows = branch_rows_query.with_entities(
            Branch.branch_code,
            func.coalesce(func.sum(ShiftCloseLog.pms_revenue), 0).label('pms'),
            func.coalesce(func.sum(ShiftCloseLog.closed_online_revenue), 0).label('online'),
            func.coalesce(func.sum(ShiftCloseLog.closed_branch_revenue), 0).label('branch'),
            func.count(ShiftCloseLog.id).label('shift_count'),
        ).group_by(Branch.branch_code).all()

        branch_txs = _tx_period_filter(db.query(ShiftReportTransaction).join(ShiftReportTransaction.branch)).all()
        branch_tx_map: dict[str, list[ShiftReportTransaction]] = {}
        for tx in branch_txs:
            branch_code = tx.branch.branch_code if tx.branch else "N/A"
            if branch_filter_value and branch_code != branch_filter_value:
                continue
            branch_tx_map.setdefault(branch_code, []).append(tx)

        branch_ranking = []
        seen_branch_codes = set()
        for row in branch_rows:
            branch_code = row.branch_code
            seen_branch_codes.add(branch_code)
            summary = summarize_shift_transactions(branch_tx_map.get(branch_code, []))
            pms = float(row.pms or summary["net_total"] or 0)
            online = float(row.online or 0)
            branch_transfer = float(row.branch or 0)
            cash = pms - online - branch_transfer
            branch_ranking.append({
                "branch_code": branch_code,
                "pms_revenue": pms,
                "cash": cash,
                "online": online,
                "branch_transfer": branch_transfer,
                "card": summary["card"],
                "ota": summary["ota"],
                "company_unc": summary["company_unc"],
                "debt": summary["debt"],
                "refund_outflow": summary["refund_outflow"],
                "shift_count": int(row.shift_count or 0),
                "reconciliation_gap": pms - float(summary["net_total"] or 0),
            })
        for branch_code, txs in branch_tx_map.items():
            if branch_code in seen_branch_codes:
                continue
            summary = summarize_shift_transactions(txs)
            pms = float(summary["net_total"] or 0)
            branch_ranking.append({
                "branch_code": branch_code,
                "pms_revenue": pms,
                "cash": float(summary["cash"] or 0),
                "online": float((summary["non_cash"] or 0) - (summary["bank_transfer"] or 0)),
                "branch_transfer": float(summary["bank_transfer"] or 0),
                "card": summary["card"],
                "ota": summary["ota"],
                "company_unc": summary["company_unc"],
                "debt": summary["debt"],
                "refund_outflow": summary["refund_outflow"],
                "shift_count": 0,
                "reconciliation_gap": 0,
            })
        branch_ranking.sort(key=lambda item: item["pms_revenue"], reverse=True)

        daily_trend = []
        if view_mode == "month":
            daily_query = db.query(
                func.date(ShiftCloseLog.closed_datetime).label('date'),
                func.sum(ShiftCloseLog.pms_revenue).label('pms'),
                func.sum(ShiftCloseLog.closed_online_revenue).label('online'),
                func.sum(ShiftCloseLog.closed_branch_revenue).label('branch'),
            ).filter(
                extract('month', ShiftCloseLog.closed_datetime) == filter_month,
                extract('year', ShiftCloseLog.closed_datetime) == filter_year,
            )
            daily_query = _apply_branch(daily_query, ShiftCloseLog.branch)
            daily_stats = daily_query.group_by(func.date(ShiftCloseLog.closed_datetime)).order_by(func.date(ShiftCloseLog.closed_datetime)).all()
            for d in daily_stats:
                p = float(d.pms or 0)
                o = float(d.online or 0)
                b = float(d.branch or 0)
                daily_trend.append({
                    "date": d.date.isoformat() if d.date else "",
                    "pms": p,
                    "cash": p - o - b,
                    "online": o,
                    "branch": b,
                })

            daily_by_date = {item["date"]: item for item in daily_trend}
            tx_by_date: dict[str, list[ShiftReportTransaction]] = {}
            for tx in closed_transactions:
                trend_dt = tx.closed_datetime if _shift_enum_value(tx.status) == ShiftReportStatus.CLOSED.value else tx.created_datetime
                if trend_dt:
                    tx_by_date.setdefault(trend_dt.date().isoformat(), []).append(tx)
            for date_key, txs in tx_by_date.items():
                if date_key in daily_by_date:
                    continue
                summary = summarize_shift_transactions(txs)
                daily_trend.append({
                    "date": date_key,
                    "pms": float(summary["net_total"] or 0),
                    "cash": float(summary["cash"] or 0),
                    "online": float((summary["non_cash"] or 0) - (summary["bank_transfer"] or 0)),
                    "branch": float(summary["bank_transfer"] or 0),
                })
            daily_trend.sort(key=lambda item: item["date"])

        monthly_log_query = db.query(
            extract('month', ShiftCloseLog.closed_datetime).label('month'),
            func.sum(ShiftCloseLog.pms_revenue).label('pms'),
            func.sum(ShiftCloseLog.closed_online_revenue).label('online'),
            func.sum(ShiftCloseLog.closed_branch_revenue).label('branch'),
        ).filter(extract('year', ShiftCloseLog.closed_datetime) == filter_year)
        monthly_log_query = _apply_branch(monthly_log_query, ShiftCloseLog.branch)
        monthly_log_rows = monthly_log_query.group_by(extract('month', ShiftCloseLog.closed_datetime)).all()
        monthly_map = {int(row.month): row for row in monthly_log_rows}

        monthly_tx_query = db.query(ShiftReportTransaction).filter(
            or_(
                and_(
                    ShiftReportTransaction.status == ShiftReportStatus.CLOSED,
                    extract('year', ShiftReportTransaction.closed_datetime) == filter_year,
                ),
                and_(
                    ShiftReportTransaction.status == ShiftReportStatus.PENDING,
                    extract('year', ShiftReportTransaction.created_datetime) == filter_year,
                ),
            )
        )
        monthly_tx_query = _apply_branch(monthly_tx_query, ShiftReportTransaction.branch)
        monthly_txs = monthly_tx_query.all()
        monthly_tx_map: dict[int, list[ShiftReportTransaction]] = {}
        for tx in monthly_txs:
            trend_dt = tx.closed_datetime if _shift_enum_value(tx.status) == ShiftReportStatus.CLOSED.value else tx.created_datetime
            if not trend_dt:
                continue
            monthly_tx_map.setdefault(trend_dt.month, []).append(tx)

        has_analytics_data = bool(closed_transactions or branch_rows or monthly_txs)
        monthly_trend = []
        if has_analytics_data:
            for m in range(1, 13):
                row = monthly_map.get(m)
                summary = summarize_shift_transactions(monthly_tx_map.get(m, []))
                p = float(row.pms if row else summary["net_total"] or 0)
                o = float(row.online if row else (summary["non_cash"] or 0) - (summary["bank_transfer"] or 0))
                b = float(row.branch if row else summary["bank_transfer"] or 0)
                monthly_trend.append({
                    "month": m,
                    "label": f"T{m}",
                    "pms": p,
                    "cash": p - o - b,
                    "online": o,
                    "branch": b,
                    "debt": float(summary["debt"] or 0),
                    "expense": float(summary["refund_outflow"] or 0),
                })

        period_label = f"Năm {filter_year}" if view_mode == "year" else f"Tháng {filter_month}/{filter_year}"
        return DecimalSafeJSONResponse(content={
            "status": "success",
            "data": {
                "period": {"view": view_mode, "month": filter_month, "year": filter_year, "label": period_label},
                "has_data": has_analytics_data,
                "summary": {
                    "total_pms_revenue": total_pms,
                    "total_cash": total_cash,
                    "total_online": total_online_closed,
                    "total_branch_transfer": total_branch_closed,
                    "total_debt": total_debt,
                    "total_card": total_card,
                    "total_ota": total_ota,
                    "total_expense": total_expense,
                    "shift_close_count": shift_count,
                    "transaction_count": total_tx_count,
                    "reconciled_total": reconciled_total,
                    "reconciliation_gap": reconciliation_gap,
                },
                "by_branch": branch_ranking,
                "daily_trend": daily_trend,
                "monthly_trend": monthly_trend,
                "type_breakdown": type_breakdown,
            }
        })
    except Exception as e:
        logger.error(f"Lỗi API Analytics: {e}", exc_info=True)
        return DecimalSafeJSONResponse(content={
            "status": "error",
            "message": str(e),
            "data": {}
        }, status_code=500)
