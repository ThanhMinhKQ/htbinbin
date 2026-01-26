# app/api/shift_report.py
# (ĐÃ NHÂN BẢN VÀ CHỈNH SỬA TỪ lost_and_found.py)

from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
import math
import random
from pydantic import BaseModel
import string # THÊM: Để tạo mã giao dịch

# Import từ các module đã tái cấu trúc
from ..db.session import get_db
# SỬA: Import model mới (Giả định)
from ..db.models import User, ShiftReportTransaction, Branch, Department, ShiftReportStatus, TransactionType, ShiftCloseLog, User
from ..core.security import get_active_branch
from ..core.config import logger, BRANCHES, SHIFT_TRANSACTION_TYPES # THÊM: Import cấu hình mới
from ..core.utils import VN_TZ

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

def get_date_range_filter(from_date_str: Optional[str], to_date_str: Optional[str]):
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
    status_val = transaction.status.value if hasattr(transaction.status, 'value') else transaction.status
    type_val = transaction.transaction_type.value if hasattr(transaction.transaction_type, 'value') else transaction.transaction_type

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
        "amount": transaction.amount,
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
        "status_raw": status_val
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

    if user_data.get("role") not in ["admin", "boss"]:
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
            filter_conditions = [fts_condition]

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

    order_expression = sort_column_map.get(sort_by, ShiftReportTransaction.created_datetime)

    # Nếu sắp xếp theo người ghi nhận, cần join với bảng User
    if sort_by == 'recorded_by':
        query = query.join(ShiftReportTransaction.recorder, isouter=True)

    # Áp dụng sắp xếp
    query = query.order_by(sort_direction(order_expression), desc(ShiftReportTransaction.id))

    # Áp dụng Keyset Pagination nếu có cursor
    if last_created_datetime and last_id is not None:
        try:
            cursor_dt = datetime.fromisoformat(last_created_datetime)
            
            # SỬA: Dùng created_datetime
            query = query.filter(
                tuple_(ShiftReportTransaction.created_datetime, ShiftReportTransaction.id) < (cursor_dt, last_id)
            )
        except (ValueError, TypeError):
            logger.warning(f"Cursor không hợp lệ: last_created_datetime={last_created_datetime}, last_id={last_id}")
            query = query.offset((page - 1) * per_page) # Fallback
    elif page > 1:
        query = query.offset((page - 1) * per_page)

    items = query.limit(per_page).all()
    return items, total_records

# ----------------------------------------------------------------------
# ENDPOINT TẢI TRANG (SỬA)
# ----------------------------------------------------------------------
@router.get("", response_class=HTMLResponse)
async def shift_report_page(
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

    all_branches_obj = db.query(Branch).filter(func.lower(Branch.branch_code).notin_(['admin', 'boss'])).all()

    b_branches = []
    other_branches = []
    for b in all_branches_obj:
        branch_code = b.branch_code
        if branch_code.startswith('B') and branch_code[1:].isdigit():
            b_branches.append(branch_code)
        else:
            other_branches.append(branch_code)
    b_branches.sort(key=lambda x: int(x[1:]))
    other_branches.sort()
    display_branches = b_branches + other_branches

    # === BẮT ĐẦU SỬA LỖI LOGIC CHI NHÁNH ===
    
    active_branch = "" # Sẽ lưu chi nhánh hoạt động của Lễ tân
    
    if user_data.get("role") == 'letan':
        # 1. Ưu tiên hàng đầu: Chi nhánh đã chọn chủ động (GPS/chọn tay)
        session_branch = request.session.get("active_branch")
        if session_branch:
            active_branch = session_branch
        else:
            # 2. Nếu không có, query DB để lấy `last_active_branch`
            user_from_db = db.query(User).filter(User.id == user_data.get("id")).first()
            if user_from_db and user_from_db.last_active_branch:
                active_branch = user_from_db.last_active_branch # <-- Đây là B10
            else:
                # 3. Nếu vẫn không có, dùng chi nhánh chính (mặc định)
                active_branch = user_data.get("branch", "")
    
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
    
    # SỬA: Dùng biến `active_branch` đã được xác định ở trên
    if user_data.get("role") == 'letan' and not chi_nhanh:
        # `active_branch` đã chứa B10 (hoặc chi nhánh đúng)
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
    return templates.TemplateResponse("shift_report.html", {
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
@router.get("/api", response_model=ShiftTransactionsResponse)
async def api_shift_report_transactions(
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
    if recorded_by_string and '(' in recorded_by_string and ')' in recorded_by_string:
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
    try:
        amount = int(amount_str)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Số tiền không hợp lệ.")
        
    if not transaction_type or transaction_type not in TransactionType._value2member_map_:
        raise HTTPException(status_code=400, detail="Loại giao dịch không hợp lệ.")

    # THÊM: Tạo mã giao dịch
    transaction_code = generate_transaction_code(db, branch.branch_code)

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
    # SỬA: Refresh quan hệ
    db.refresh(new_transaction, ["branch", "recorder"]) 
    return {"status": "success", "message": "Đã thêm giao dịch thành công.", "item": _serialize_transaction(new_transaction)}

# ----------------------------------------------------------------------
# ENDPOINT CHỈNH SỬA (SỬA)
# ----------------------------------------------------------------------
@router.post("/edit-details/{item_id}", response_model=dict)
async def edit_shift_transaction_details( # SỬA
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
):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Unauthorized")

    allowed_roles = ["letan", "quanly", "admin", "boss"]
    if user_data.get("role") not in allowed_roles:
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
    item.transaction_type = transaction_type
    try:
        item.amount = int(amount)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Số tiền không hợp lệ.")
    item.room_number = room_number # THÊM
    item.transaction_info = transaction_info # THÊM
    item.recorder_id = recorder.id if recorder else item.recorder_id 
    item.branch_id = branch.id
    
    # XOÁ: Logic cập nhật cho status RETURNED, DISPOSED

    db.commit()
    # SỬA: Refresh quan hệ
    db.refresh(item, ["branch", "recorder", "closer", "deleter"])
    return {"status": "success", "message": "Đã cập nhật giao dịch thành công.", "item": _serialize_transaction(item)}

# ----------------------------------------------------------------------
# ENDPOINT CẬP NHẬT TRẠNG THÁI (SỬA)
# ----------------------------------------------------------------------
@router.post("/update/{item_id}", response_model=dict)
async def update_shift_transaction_status( # SỬA
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
    
    allowed_roles = ["letan", "quanly", "admin", "boss"]
    if user_data.get("role") not in allowed_roles:
        raise HTTPException(status_code=403, detail="Bạn không có quyền thực hiện.")

    now = datetime.now(VN_TZ)
    
    # SỬA: Logic action mới
    if action == "close":
        if item.status != ShiftReportStatus.PENDING:
             raise HTTPException(status_code=400, detail="Giao dịch đã được xử lý trước đó.")
        item.status = ShiftReportStatus.CLOSED
        item.closed_datetime = now
        item.closer_id = user_data.get("id") # Giả định model có trường closer_id
    
    # XOÁ: Logic action "return" và "dispose"
    
    db.commit()
    # SỬA: Refresh TẤT CẢ các quan hệ
    db.refresh(item, ["branch", "recorder", "closer", "deleter"])
    return {"status": "success", "message": "Đã cập nhật trạng thái.", "item": _serialize_transaction(item)}

# ----------------------------------------------------------------------
# ENDPOINT XÓA (SỬA: Chỉ đổi tên model/status)
# ----------------------------------------------------------------------
@router.post("/delete/{item_id}", response_class=JSONResponse)
async def delete_shift_transaction( # SỬA
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

    if user_role in ["admin", "boss"] and hard_delete:
        item_id_to_delete = item.id
        
        # 1. Tìm tất cả các bản ghi ShiftCloseLog có chứa ID của giao dịch này
        logs_to_update = db.query(ShiftCloseLog).filter(
            ShiftCloseLog.closed_transaction_ids.isnot(None), # Đảm bảo cột không phải NULL
            ShiftCloseLog.closed_transaction_ids.cast(JSONB).op("?")(str(item_id_to_delete))
        ).all()

        for log_entry in logs_to_update:
            # 2. Xóa ID của giao dịch khỏi danh sách
            current_ids = log_entry.closed_transaction_ids
            if not isinstance(current_ids, list):
                logger.warning(f"closed_transaction_ids cho log {log_entry.id} không phải là list: {current_ids}")
                continue

            # Lọc bỏ ID của giao dịch đã xóa
            try:
                current_ids = [tx_id for tx_id in current_ids if tx_id != item_id_to_delete]
            except TypeError: # Xử lý trường hợp các phần tử có thể là string nếu JSON không chặt chẽ
                current_ids = [tx_id for tx_id in current_ids if str(tx_id) != str(item_id_to_delete)]

            log_entry.closed_transaction_ids = current_ids

            if not current_ids:
                # Nếu không còn giao dịch nào, xóa bản ghi log
                db.delete(log_entry)
                logger.info(f"ShiftCloseLog {log_entry.id} đã bị xóa do không còn giao dịch nào.")
            else:
                # 3. Tính toán lại doanh thu dựa trên các giao dịch còn lại
                remaining_transactions = db.query(ShiftReportTransaction).filter(
                    ShiftReportTransaction.id.in_(current_ids)
                ).all()

                closed_online_revenue = 0
                closed_branch_revenue = 0
                
                for tx in remaining_transactions:
                    if tx.transaction_type in [
                        TransactionType.OTA, 
                        TransactionType.UNC, 
                        TransactionType.CARD, 
                        TransactionType.COMPANY_ACCOUNT,
                        TransactionType.CASH_EXPENSE,
                        TransactionType.OTHER
                    ]:
                        closed_online_revenue += tx.amount
                    elif tx.transaction_type == TransactionType.BRANCH_ACCOUNT:
                        closed_branch_revenue += tx.amount
                
                log_entry.closed_online_revenue = closed_online_revenue
                log_entry.closed_branch_revenue = closed_branch_revenue
                logger.info(f"ShiftCloseLog {log_entry.id} đã tính toán lại doanh thu sau khi xóa giao dịch {item_id_to_delete}.")

        db.delete(item)
        db.commit()
        return JSONResponse({
            "status": "success", 
            "message": "Đã xóa vĩnh viễn giao dịch.",
            "deleted_id": item_id_to_delete,
            "hard_delete": True
        })
    else:
        # SỬA: Dùng status mới
        item.status = ShiftReportStatus.DELETED
        item.deleter_id = user_data.get("id")
        item.deleted_datetime = now
        db.commit()
        db.refresh(item, ["branch", "recorder", "closer", "deleter"]) # SỬA
        return JSONResponse({
            "status": "success", 
            "message": "Đã xóa giao dịch thành công.",
            "item": _serialize_transaction(item), # SỬA
            "hard_delete": False
        })

# ----------------------------------------------------------------------
# ENDPOINT XÓA HÀNG LOẠT (SỬA: Chỉ đổi tên model/status)
# ----------------------------------------------------------------------
@router.post("/batch-delete", response_model=dict)
async def batch_delete_shift_transactions( # SỬA
    payload: BatchDeleteTransactionsPayload, # SỬA: Dùng schema mới
    request: Request,
    db: Session = Depends(get_db)
):
    user_data = request.session.get("user")
    user_role = user_data.get("role") if user_data else None
    if not user_role:
        raise HTTPException(status_code=403, detail="Unauthorized")

    if not payload.ids:
        return JSONResponse({"status": "noop", "message": "Không có mục nào được chọn."})

    try:
        if user_role in ["admin", "boss"]:
            # SỬA LỖI: Chỉ cho phép xóa vĩnh viễn các giao dịch chưa được kết ca.
            # Lấy các bản ghi hợp lệ để xóa từ DB.
            transactions_to_delete = db.query(ShiftReportTransaction).filter(
                ShiftReportTransaction.id.in_(payload.ids),
                ShiftReportTransaction.status != ShiftReportStatus.CLOSED
            ).all()
            
            if not transactions_to_delete:
                return JSONResponse({
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
                    current_ids = log_entry.closed_transaction_ids
                    if not isinstance(current_ids, list):
                        logger.warning(f"closed_transaction_ids cho log {log_entry.id} không phải là list: {current_ids}")
                        continue

                    try:
                        current_ids = [tx_id for tx_id in current_ids if tx_id != item_id_to_delete]
                    except TypeError:
                        current_ids = [tx_id for tx_id in current_ids if str(tx_id) != str(item_id_to_delete)]

                    log_entry.closed_transaction_ids = current_ids

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
                        for tx in remaining_transactions:
                            if tx.transaction_type in [
                                TransactionType.OTA, 
                                TransactionType.UNC, 
                                TransactionType.CARD, 
                                TransactionType.COMPANY_ACCOUNT,
                                TransactionType.CASH_EXPENSE,
                                TransactionType.OTHER
                            ]:
                                closed_online_revenue += tx.amount
                            elif tx.transaction_type == TransactionType.BRANCH_ACCOUNT:
                                closed_branch_revenue += tx.amount
                        log_entry.closed_online_revenue = closed_online_revenue
                        log_entry.closed_branch_revenue = closed_branch_revenue
                        logger.info(f"ShiftCloseLog {log_entry.id} revenues recalculated after transaction {item_id_to_delete} removal.")
                
                db.delete(item)
                deleted_ids.append(item_id_to_delete)
            db.commit()
            return JSONResponse({
                "status": "success", 
                "message": f"Đã xóa vĩnh viễn {len(deleted_ids)} mục.",
                "ids": ids_to_process,
                "hard_delete": True
            })
        else:
            now = datetime.now(VN_TZ)
            deleter_id = user_data.get("id")
            
            # SỬA LỖI: Chỉ cho phép xóa mềm các giao dịch đang PENDING.
            # Lấy các ID hợp lệ từ DB trước khi cập nhật.
            valid_ids_query = db.query(ShiftReportTransaction.id).filter(
                ShiftReportTransaction.id.in_(payload.ids),
                ShiftReportTransaction.status == ShiftReportStatus.PENDING
            )
            ids_to_process = [item[0] for item in valid_ids_query.all()]

            if not ids_to_process:
                return JSONResponse({"status": "noop", "message": "Không có giao dịch nào ở trạng thái 'Chờ xử lý' để xóa."})

            num_updated = db.query(ShiftReportTransaction).filter(
                ShiftReportTransaction.id.in_(ids_to_process)
            ).update({
                "status": ShiftReportStatus.DELETED.value, # SỬA
                "deleter_id": deleter_id,
                "deleted_datetime": now
            }, synchronize_session=False)
            
            db.commit()
            
            # SỬA: Query model mới
            updated_items = db.query(ShiftReportTransaction).options(
                joinedload(ShiftReportTransaction.branch),
                joinedload(ShiftReportTransaction.recorder),
                joinedload(ShiftReportTransaction.closer),
                joinedload(ShiftReportTransaction.deleter)
            ).filter(ShiftReportTransaction.id.in_(ids_to_process)).all()
            
            serialized_items = [_serialize_transaction(item) for item in updated_items] # SỬA

            return JSONResponse({
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
async def batch_close_transactions(
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
    if not user_data or user_data.get("role") not in ["letan", "quanly", "admin", "boss"]:
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
        closed_transactions = [] # Khởi tạo list rỗng

        # 2. SỬA: Chỉ thực hiện update nếu CÓ giao dịch để update
        if transaction_ids_to_close:
            # Cập nhật trạng thái cho các giao dịch đang chờ xử lý
            num_updated = db.query(ShiftReportTransaction).filter(
                ShiftReportTransaction.id.in_(transaction_ids_to_close)
            ).update({
                "status": ShiftReportStatus.CLOSED.value,
                "closer_id": closer_id,
                "closed_datetime": now
            }, synchronize_session=False)

            db.commit()
            
            # Lấy các giao dịch vừa được cập nhật để tính tổng doanh thu
            closed_transactions = db.query(ShiftReportTransaction).filter(
                ShiftReportTransaction.id.in_(transaction_ids_to_close)
            ).all()

            # Lấy lại các item vừa cập nhật để trả về cho frontend
            updated_items = db.query(ShiftReportTransaction).options(
                joinedload(ShiftReportTransaction.branch),
                joinedload(ShiftReportTransaction.recorder),
                joinedload(ShiftReportTransaction.closer),
                joinedload(ShiftReportTransaction.deleter)
            ).filter(ShiftReportTransaction.id.in_(transaction_ids_to_close)).all()

        # 3. SỬA: LUÔN LUÔN ghi nhận vào bảng ShiftCloseLog
        try:
            # Tính toán doanh thu (sẽ là 0 nếu closed_transactions rỗng)
            closed_online_revenue = sum(
                t.amount for t in closed_transactions 
                if t.transaction_type in [
                    TransactionType.OTA, 
                    TransactionType.UNC, 
                    TransactionType.CARD, 
                    TransactionType.COMPANY_ACCOUNT,
                    TransactionType.CASH_EXPENSE,
                    TransactionType.OTHER
                ]
            )

            closed_branch_revenue = sum(
                t.amount for t in closed_transactions
                if t.transaction_type == TransactionType.BRANCH_ACCOUNT
            )

            pms_val = str(payload.pms_revenue) 
            pms_revenue_int = int(pms_val.replace('.', '').replace(',', ''))
            
            branch_obj = db.query(Branch).filter(Branch.branch_code == payload.branch).first()
            if not branch_obj:
                logger.error(f"Không tìm thấy chi nhánh '{payload.branch}' để ghi log kết ca.", exc_info=True)
                # Vẫn tiếp tục, branch_id sẽ là None
            
            new_log_entry = ShiftCloseLog(
                branch_id=branch_obj.id if branch_obj else None,
                closer_id=closer_id,
                closed_datetime=now,
                pms_revenue=pms_revenue_int,
                closed_online_revenue=closed_online_revenue,
                closed_branch_revenue=closed_branch_revenue,
                closed_transaction_ids=transaction_ids_to_close # Sẽ là [] nếu không có giao dịch
            )
            db.add(new_log_entry)
            db.commit()
            
            db.refresh(new_log_entry) # <--- THÊM DÒNG NÀY
            new_log_id = new_log_entry.id # <--- THÊM DÒNG NÀY
        
        except Exception as log_error:
            logger.error(f"Lỗi khi ghi nhận ShiftCloseLog: {log_error}", exc_info=True)
            # Không raise lỗi để không ảnh hưởng đến kết quả trả về cho user
            new_log_id = None # <--- THÊM DÒNG NÀY

        # 4. Trả về kết quả thành công
        # Frontend (hàm executeBatchClose) đã xử lý 'success' đúng
        return {"status": "success", "message": f"Đã kết ca thành công {num_updated} giao dịch.", "items": [_serialize_transaction(item) for item in updated_items], "log_id": new_log_id}

    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi kết ca hàng loạt: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi server khi kết ca.")

@router.get("/api/dashboard-summary")
async def get_dashboard_summary(
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
        active_branch_for_letan = None
        branch_filter_value = chi_nhanh

        if user_data.get("role") == 'letan':
            active_branch_for_letan = get_active_branch(request, db, user_data)
            branch_filter_value = active_branch_for_letan # Lễ tân bắt buộc lọc theo chi nhánh của mình

        # --- 2. QUERY 1: LỊCH SỬ KẾT CA (Recent Closes) ---
        # Query này độc lập, luôn Join Branch và Closer để lấy tên hiển thị
        history_query = db.query(ShiftCloseLog).join(ShiftCloseLog.branch).join(ShiftCloseLog.closer)
        
        if branch_filter_value:
            history_query = history_query.filter(Branch.branch_code == branch_filter_value)
        
        if date_filters_log:
            history_query = history_query.filter(*date_filters_log)

        recent_closes = history_query.with_entities(
            ShiftCloseLog.id,
            ShiftCloseLog.pms_revenue,
            ShiftCloseLog.closed_online_revenue,
            ShiftCloseLog.closed_branch_revenue,
            ShiftCloseLog.closed_datetime,
            Branch.branch_code,
            User.name.label("closer_name")
        ).order_by(desc(ShiftCloseLog.closed_datetime)).limit(50).all() # Limit 50 để không quá tải

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
        # - Đã kết ca (CLOSED): Lọc theo ngày kết ca (closed_datetime) -> Để khớp với Doanh thu PMS (ShiftCloseLog)
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

        # Định nghĩa các Case tính toán
        online_rev_case = case(
            (ShiftReportTransaction.transaction_type.in_(['COMPANY_ACCOUNT', 'OTA', 'UNC', 'CARD', 'CASH_EXPENSE', 'OTHER']), ShiftReportTransaction.amount), else_=0
        )
        branch_rev_case = case(
            (ShiftReportTransaction.transaction_type == 'BRANCH_ACCOUNT', ShiftReportTransaction.amount), else_=0
        )
        expense_case = case(
            (ShiftReportTransaction.transaction_type == 'CASH_EXPENSE', ShiftReportTransaction.amount), else_=0
        )

        revenue_stats = tx_query.with_entities(
            func.sum(case((ShiftReportTransaction.status == ShiftReportStatus.CLOSED.value, online_rev_case), else_=0)).label('closed_online'),
            func.sum(case((ShiftReportTransaction.status == ShiftReportStatus.PENDING.value, online_rev_case), else_=0)).label('pending_online'),
            func.sum(case((ShiftReportTransaction.status == ShiftReportStatus.CLOSED.value, expense_case), else_=0)).label('closed_expense'),
            func.sum(case((ShiftReportTransaction.status == ShiftReportStatus.PENDING.value, expense_case), else_=0)).label('pending_expense'),
            func.sum(case((ShiftReportTransaction.status == ShiftReportStatus.CLOSED.value, branch_rev_case), else_=0)).label('closed_branch'),
            func.sum(case((ShiftReportTransaction.status == ShiftReportStatus.PENDING.value, branch_rev_case), else_=0)).label('pending_branch')
        ).first()

        # --- 5. QUERY 4: BẢNG XẾP HẠNG (Ranking) ---
        # Chỉ chạy khi Admin/Boss và KHÔNG chọn chi nhánh cụ thể
        final_branch_ranking = []
        if user_data.get("role") in ['admin', 'boss'] and not chi_nhanh:
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
            # Để đơn giản và nhanh, ta chỉ map PMS revenue vào
            for item in pms_ranking:
                final_branch_ranking.append({
                    "branch": item.branch_code,
                    "pms_revenue": float(item.total_pms or 0),
                    "closed_revenue": 0, # Có thể query thêm nếu cần chi tiết
                    "pending_revenue": 0
                })

        # --- 6. TRẢ VỀ KẾT QUẢ ---
        return JSONResponse(content={
            "status": "success",
            "data": {
                "by_branch": final_branch_ranking,
                "total_pms_revenue": float(log_summary.total_pms or 0.0),
                "total_cash_revenue": (float(log_summary.total_pms or 0.0) - float(log_summary.total_closed_online or 0.0) - float(log_summary.total_closed_branch or 0.0)),
                
                "recent_closes": ([{
                        "id": r.id, 
                        "pms_revenue": r.pms_revenue, 
                        "closed_online_revenue": r.closed_online_revenue,
                        "closed_branch_revenue": r.closed_branch_revenue,
                        "closed_datetime": r.closed_datetime.isoformat(), 
                        "branch_code": r.branch_code, 
                        "closer_name": r.closer_name
                    } for r in recent_closes] if recent_closes else []),
                
                "by_type": {
                    "closed_online": float(revenue_stats.closed_online or 0.0),
                    "pending_online": float(revenue_stats.pending_online or 0.0),
                    "closed_expense": float(revenue_stats.closed_expense or 0.0),
                    "pending_expense": float(revenue_stats.pending_expense or 0.0),
                    "closed_branch": float(revenue_stats.closed_branch or 0.0),
                    "pending_branch": float(revenue_stats.pending_branch or 0.0),
                }
            }
        })

    except Exception as e:
        logger.error(f"Lỗi khi lấy dữ liệu dashboard giao ca: {e}", exc_info=True)
        # Trả về data rỗng thay vì 500 để Frontend không bị crash
        return JSONResponse(content={
            "status": "error", 
            "message": str(e),
            "data": { 
                "by_branch": [], "recent_closes": [], 
                "by_type": {"closed_online":0, "pending_online":0, "closed_branch":0, "pending_branch":0},
                "total_pms_revenue": 0, "total_cash_revenue": 0 
            }
        })

@router.get("/api/shift-close-details/{log_id}", response_model=dict)
async def get_shift_close_details(
    log_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user_data = request.session.get("user")
    if not user_data or user_data.get("role") not in ["admin", "boss", "quanly", "letan"]:
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập chức năng này.")

    log_entry = db.query(ShiftCloseLog).options(
        joinedload(ShiftCloseLog.branch),
        joinedload(ShiftCloseLog.closer)
    ).filter(ShiftCloseLog.id == log_id).first()

    if not log_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi kết ca.")

    transaction_ids = log_entry.closed_transaction_ids or []
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
        "pms_revenue": log_entry.pms_revenue,
        "closed_online_revenue": log_entry.closed_online_revenue,
        "closed_branch_revenue": log_entry.closed_branch_revenue,
        "cash_revenue": (log_entry.pms_revenue or 0) - (log_entry.closed_online_revenue or 0) - (log_entry.closed_branch_revenue or 0),
        "closed_datetime": log_entry.closed_datetime.isoformat(),
        "branch_code": log_entry.branch.branch_code if log_entry.branch else "N/A",
        "closer_name": log_entry.closer.name if log_entry.closer else "N/A"
    }

    return JSONResponse(content={
        "status": "success",
        "log_details": log_details,
        "transactions": [_serialize_transaction(tx) for tx in transactions]
    })

@router.post("/api/undo-shift-close/{log_id}", response_model=dict)
async def undo_shift_close(
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
    if not user_data or user_data.get("role") not in ["admin", "boss"]:
        raise HTTPException(status_code=403, detail="Bạn không có quyền thực hiện hành động này.")

    log_entry = db.query(ShiftCloseLog).filter(ShiftCloseLog.id == log_id).first()
    if not log_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi kết ca.")

    transaction_ids = log_entry.closed_transaction_ids

    try:
        # Hoàn tác trạng thái các giao dịch
        if transaction_ids:
            db.query(ShiftReportTransaction).filter(
                ShiftReportTransaction.id.in_(transaction_ids)
            ).update({"status": ShiftReportStatus.PENDING.value}, synchronize_session=False)

        # Xóa bản ghi log
        db.delete(log_entry)
        db.commit()
        return {"status": "success", "message": "Đã hoàn tác kết ca thành công."}
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi hoàn tác kết ca (log_id: {log_id}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi server khi hoàn tác kết ca.")

@router.delete("/api/delete-shift-close/{log_id}", response_model=dict)
async def delete_shift_close(
    log_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    API để xóa vĩnh viễn một lần kết ca và tất cả các giao dịch liên quan.
    Chỉ dành cho admin/boss.
    """
    user_data = request.session.get("user")
    if not user_data or user_data.get("role") not in ["admin", "boss"]:
        raise HTTPException(status_code=403, detail="Bạn không có quyền thực hiện hành động này.")

    log_entry = db.query(ShiftCloseLog).filter(ShiftCloseLog.id == log_id).first()
    if not log_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi kết ca.")

    transaction_ids = log_entry.closed_transaction_ids

    try:
        # Xóa các giao dịch liên quan
        if transaction_ids:
            db.query(ShiftReportTransaction).filter(
                ShiftReportTransaction.id.in_(transaction_ids)
            ).delete(synchronize_session=False)

        # Xóa bản ghi log
        db.delete(log_entry)
        db.commit()
        return {"status": "success", "message": "Đã xóa vĩnh viễn lần kết ca và các giao dịch liên quan."}
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi xóa vĩnh viễn kết ca (log_id: {log_id}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi server khi xóa kết ca.")

@router.get("/api/monthly-summary")
async def get_monthly_summary(
    request: Request,
    year: int,
    db: Session = Depends(get_db)
):
    """
    API để lấy tổng hợp doanh thu theo từng tháng của một năm.
    Chỉ tính các giao dịch đã ở trạng thái "Đã kết ca".
    """
    user_data = request.session.get("user")
    if not user_data or user_data.get("role") not in ["admin", "boss"]:
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập chức năng này.")

    try:
        # Định nghĩa các biểu thức case cho từng loại doanh thu
        online_revenue_case = case(
            (ShiftReportTransaction.transaction_type.in_([
                'COMPANY_ACCOUNT', 'OTA', 'UNC', 'CARD', 'CASH_EXPENSE', 'OTHER'
            ]), ShiftReportTransaction.amount),
            else_=0
        )
        branch_revenue_case = case(
            (ShiftReportTransaction.transaction_type == 'BRANCH_ACCOUNT', ShiftReportTransaction.amount),
            else_=0
        )

        # Query để lấy tổng doanh thu theo tháng
        results = db.query(
            extract('month', ShiftReportTransaction.created_datetime).label('month'),
            func.sum(online_revenue_case).label('online_revenue'),
            func.sum(branch_revenue_case).label('branch_revenue')
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
            # SỬA LỖI: Chuyển đổi giá trị Decimal từ DB sang float để JSONResponse có thể xử lý.
            # `or 0.0` vẫn được giữ lại để xử lý trường hợp không có dữ liệu (giá trị là None).
            {
                "month": i, 
                "online_revenue": float(summary_by_month.get(i, {}).get('online_revenue') or 0.0), 
                "branch_revenue": float(summary_by_month.get(i, {}).get('branch_revenue') or 0.0)
            }
            for i in range(1, 13)
        ]

        return JSONResponse(content={"status": "success", "data": final_summary})
    except Exception as e:
        logger.error(f"Lỗi khi lấy báo cáo tháng: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi server khi lấy báo cáo tháng.")

class UndoTransactionPayload(BaseModel):
    log_id: int
    transaction_id: int

@router.post("/api/undo-transaction-from-log", response_model=dict)
async def undo_transaction_from_log(
    payload: UndoTransactionPayload,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    API để hoàn tác một giao dịch cụ thể từ một lần kết ca.
    """
    user_data = request.session.get("user")
    if not user_data or user_data.get("role") not in ["admin", "boss"]:
        raise HTTPException(status_code=403, detail="Bạn không có quyền thực hiện hành động này.")

    log_entry = db.query(ShiftCloseLog).filter(ShiftCloseLog.id == payload.log_id).first()
    if not log_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi kết ca.")

    transaction_to_undo = db.query(ShiftReportTransaction).filter(ShiftReportTransaction.id == payload.transaction_id).first()
    if not transaction_to_undo:
        raise HTTPException(status_code=404, detail="Không tìm thấy giao dịch để hoàn tác.")

    if transaction_to_undo.id not in log_entry.closed_transaction_ids:
        raise HTTPException(status_code=400, detail="Giao dịch không thuộc về lần kết ca này.")

    # Hoàn tác giao dịch
    transaction_to_undo.status = ShiftReportStatus.PENDING
    transaction_to_undo.closer_id = None
    transaction_to_undo.closed_datetime = None

    # Cập nhật lại bản ghi log
    remaining_ids = [tx_id for tx_id in log_entry.closed_transaction_ids if tx_id != transaction_to_undo.id]
    log_entry.closed_transaction_ids = remaining_ids

    if remaining_ids:
        remaining_transactions = db.query(ShiftReportTransaction).filter(
            ShiftReportTransaction.id.in_(remaining_ids)
        ).all()

        log_entry.closed_online_revenue = sum(
            t.amount for t in remaining_transactions 
            if t.transaction_type in [
                TransactionType.OTA, 
                TransactionType.UNC, 
                TransactionType.CARD, 
                TransactionType.COMPANY_ACCOUNT,
                TransactionType.CASH_EXPENSE,
                TransactionType.OTHER
            ]
        )
        log_entry.closed_branch_revenue = sum(
            t.amount for t in remaining_transactions
            if t.transaction_type == TransactionType.BRANCH_ACCOUNT
        )
    else:
        # Nếu không còn giao dịch nào, xóa luôn bản ghi log
        db.delete(log_entry)

    db.commit()
    return {"status": "success", "message": "Đã hoàn tác giao dịch thành công."}


@router.get("/api/pending-summary")
async def get_pending_summary(
    request: Request,
    branch: str,
    db: Session = Depends(get_db)
):
    """
    API để lấy tổng số tiền của các giao dịch đang ở trạng thái PENDING
    cho một chi nhánh cụ thể.
    """
    user_data = request.session.get("user")
    if not user_data or user_data.get("role") not in ["admin", "boss", "letan", "quanly"]:
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập chức năng này.")

    try:
        total_revenue_case = case(
            (ShiftReportTransaction.transaction_type.in_([
                'COMPANY_ACCOUNT', 
                'OTA', 
                'UNC', 
                'CARD', 
                'BRANCH_ACCOUNT', 
                'CASH_EXPENSE',
                'OTHER'
            ]), ShiftReportTransaction.amount),
            # BỎ dòng trừ tiền, tất cả đều cộng
            else_=0
        )

        # Query để tính tổng số tiền của các giao dịch PENDING
        pending_sum = db.query(func.sum(total_revenue_case)).join(
            Branch, ShiftReportTransaction.branch_id == Branch.id
        ).filter(
            Branch.branch_code == branch,
            ShiftReportTransaction.status == ShiftReportStatus.PENDING
        ).scalar() or 0

        return JSONResponse(content={"status": "success", "total_pending_amount": float(pending_sum)})
    except Exception as e:
        logger.error(f"Lỗi khi lấy tổng hợp giao dịch chờ xử lý cho chi nhánh '{branch}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi server khi lấy dữ liệu.")

class DeleteTransactionFromLogPayload(BaseModel):
    log_id: int

# app/api/shift_report.py

@router.get("/api/all-pending")
async def get_all_pending_for_branch(
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

        return JSONResponse(content={
            "status": "success", 
            "transactions": results 
        })
    except Exception as e:
        logger.error(f"Lỗi khi lấy tất cả giao dịch chờ xử lý cho chi nhánh '{branch}': {e}", exc_info=True)
        # Sửa lại return để Frontend nhận được thông báo lỗi rõ ràng hơn thay vì crash
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@router.post("/api/delete-transaction-from-log/{transaction_id}", response_model=dict)
async def delete_transaction_from_log(
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
    if not user_data or user_data.get("role") not in ["admin", "boss"]:
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

    if transaction_to_delete.id not in (log_entry.closed_transaction_ids or []):
        raise HTTPException(status_code=400, detail="Giao dịch không thuộc về lần kết ca này.")

    # Xóa giao dịch
    db.delete(transaction_to_delete)

    # Cập nhật lại bản ghi log
    remaining_ids = [tx_id for tx_id in log_entry.closed_transaction_ids if tx_id != transaction_to_delete.id]
    log_entry.closed_transaction_ids = remaining_ids

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
                        closed_online_revenue += tx.amount
                    
                    elif tx.transaction_type == TransactionType.BRANCH_ACCOUNT:
                        closed_branch_revenue += tx.amount
        
        log_entry.closed_online_revenue = closed_online_revenue
        log_entry.closed_branch_revenue = closed_branch_revenue

    db.commit()

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