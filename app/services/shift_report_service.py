"""
Shift Report Service — PMS Integration

Tự động tạo ShiftReportTransaction khi khách thanh toán từ PMS.
Mỗi thanh toán PMS → 1 dòng trong ShiftReport ở trạng thái PENDING,
transaction_type khớp với hình thức thanh toán (CASH/CARD/OTA/UNC/BRANCH_ACCOUNT).
"""
from __future__ import annotations

import random
import string
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from ..core.utils import VN_TZ
from ..db.models import (
    Folio,
    FolioStatus,
    FolioTransaction,
    FolioTransactionType,
    ShiftPaymentMethod,
    ShiftReportStatus,
    ShiftReportTransaction,
    TransactionType,
)


def now_vn() -> datetime:
    return datetime.now(VN_TZ)


def _generate_shift_code(db: Session, branch_code: str) -> str:
    """Tạo mã giao dịch duy nhất theo format [BranchCode]-[5-Digits]"""
    while True:
        random_part = ''.join(random.choices(string.digits, k=5))
        code = f"{branch_code}-{random_part}"
        exists = db.query(ShiftReportTransaction).filter(
            ShiftReportTransaction.transaction_code == code
        ).first()
        if not exists:
            return code


def _detect_payment_method(folio: Folio, db: Session) -> tuple[ShiftPaymentMethod, Decimal]:
    """
    Detect phương thức thanh toán từ FolioTransaction.
    Returns (payment_method, amount_paid).

    Priority:
      1. DEPOSIT_USED + PAYMENT → phương thức thực tế (CASH mặc định)
      2. PAYMENT → thẻ/chuyển khoản
      3. DEPOSIT_USED only → CASH
      4. Không có payment nào → DEBT (còn nợ)
    """
    txs = db.query(FolioTransaction).filter(
        FolioTransaction.folio_id == folio.id,
        FolioTransaction.is_voided == False,
    ).all()

    payments = [
        tx for tx in txs
        if tx.transaction_type in (
            FolioTransactionType.PAYMENT,
            FolioTransactionType.DEPOSIT_USED,
        ) and tx.amount < 0
    ]

    if not payments:
        return ShiftPaymentMethod.DEBT, Decimal("0")

    total_paid = sum(abs(tx.amount) for tx in payments)

    # Ưu tiên DEPOSIT_USED (thường là CASH)
    deposit_used = next(
        (tx for tx in payments if tx.transaction_type == FolioTransactionType.DEPOSIT_USED),
        None
    )
    if deposit_used:
        # Deposit luôn là CASH
        return ShiftPaymentMethod.CASH, total_paid

    # Kiểm tra PAYMENT
    payment_tx = next(
        (tx for tx in payments if tx.transaction_type == FolioTransactionType.PAYMENT),
        None
    )
    if payment_tx:
        # payment_method field trong FolioTransaction có thể ghi nhận phương thức
        pm = getattr(payment_tx, 'payment_method', None) or 'CASH'
        method_map = {
            'CREDIT_CARD': ShiftPaymentMethod.CARD,
            'BANK_TRANSFER': ShiftPaymentMethod.BANK_TRANSFER,
            'CASH': ShiftPaymentMethod.CASH,
            'OTA': ShiftPaymentMethod.OTA,
        }
        return method_map.get(pm, ShiftPaymentMethod.CASH), total_paid

    return ShiftPaymentMethod.DEBT, Decimal("0")


def normalize_shift_payment_method(method: str | ShiftPaymentMethod | None) -> ShiftPaymentMethod:
    if isinstance(method, ShiftPaymentMethod):
        return method
    value = str(method or "CASH").strip().upper()
    value = value.replace(" ", "_").replace("-", "_")
    aliases = {
        "CASH": ShiftPaymentMethod.CASH,
        "TIỀN_MẶT": ShiftPaymentMethod.CASH,
        "TIEN_MAT": ShiftPaymentMethod.CASH,
        "CARD": ShiftPaymentMethod.CARD,
        "CREDIT_CARD": ShiftPaymentMethod.CARD,
        "QUẸT_THẺ": ShiftPaymentMethod.CARD,
        "QUET_THE": ShiftPaymentMethod.CARD,
        "VNPAY": ShiftPaymentMethod.CARD,
        "BANK_TRANSFER": ShiftPaymentMethod.BANK_TRANSFER,
        "BRANCH": ShiftPaymentMethod.BANK_TRANSFER,
        "BRANCH_ACCOUNT": ShiftPaymentMethod.BANK_TRANSFER,
        "CHI_NHÁNH": ShiftPaymentMethod.BANK_TRANSFER,
        "CHI_NHANH": ShiftPaymentMethod.BANK_TRANSFER,
        "CHUYỂN_KHOẢN": ShiftPaymentMethod.BANK_TRANSFER,
        "CHUYEN_KHOAN": ShiftPaymentMethod.BANK_TRANSFER,
        "MOMO": ShiftPaymentMethod.BANK_TRANSFER,
        "COMPANY": ShiftPaymentMethod.UNC,
        "COMPANY_ACCOUNT": ShiftPaymentMethod.UNC,
        "CÔNG_TY": ShiftPaymentMethod.UNC,
        "CONG_TY": ShiftPaymentMethod.UNC,
        "UNC": ShiftPaymentMethod.UNC,
        "OTA": ShiftPaymentMethod.OTA,
        "DEBT": ShiftPaymentMethod.DEBT,
        "CÔNG_NỢ": ShiftPaymentMethod.DEBT,
        "CONG_NO": ShiftPaymentMethod.DEBT,
    }
    return aliases.get(value, ShiftPaymentMethod.CASH)


def shift_method_to_payment_method(pm: ShiftPaymentMethod | None) -> "PaymentMethod":
    """Convert ShiftPaymentMethod → folio Payment.method for keeping payments table in sync."""
    from ..db.models import PaymentMethod as _PaymentMethod
    mapping = {
        ShiftPaymentMethod.CASH: _PaymentMethod.CASH,
        ShiftPaymentMethod.CARD: _PaymentMethod.CARD,
        ShiftPaymentMethod.BANK_TRANSFER: _PaymentMethod.BRANCH,
        ShiftPaymentMethod.UNC: _PaymentMethod.COMPANY,
        ShiftPaymentMethod.OTA: _PaymentMethod.OTA,
        ShiftPaymentMethod.DEBT: _PaymentMethod.OTHER,
    }
    return mapping.get(pm or ShiftPaymentMethod.CASH, _PaymentMethod.CASH)


def shift_method_from_tx_type(
    tx_type: "TransactionType | str | None",
    fallback: ShiftPaymentMethod | None = None,
) -> ShiftPaymentMethod:
    """Suy ra ShiftPaymentMethod từ TransactionType (loại giao dịch ở giao ca).

    Dùng khi user sửa transaction_type ở popup giao ca → để cascade đúng
    payment_method xuống ShiftReport, FolioTransaction.description và Payment.method.
    """
    if tx_type is None:
        return fallback or ShiftPaymentMethod.CASH
    value = tx_type.value if hasattr(tx_type, "value") else str(tx_type)
    value = value.strip().upper()
    mapping = {
        "CARD": ShiftPaymentMethod.CARD,
        "BRANCH_ACCOUNT": ShiftPaymentMethod.BANK_TRANSFER,
        "COMPANY_ACCOUNT": ShiftPaymentMethod.UNC,
        "OTA": ShiftPaymentMethod.OTA,
        "UNC": ShiftPaymentMethod.DEBT,
        "OTHER": ShiftPaymentMethod.CASH,
        "CASH_EXPENSE": ShiftPaymentMethod.CASH,
    }
    return mapping.get(value, fallback or ShiftPaymentMethod.CASH)


def shift_payment_method_label(pm: ShiftPaymentMethod | None) -> str:
    labels = {
        ShiftPaymentMethod.CASH: "Tiền mặt",
        ShiftPaymentMethod.CARD: "Quẹt thẻ",
        ShiftPaymentMethod.BANK_TRANSFER: "Chuyển khoản chi nhánh",
        ShiftPaymentMethod.UNC: "Công ty / UNC",
        ShiftPaymentMethod.OTA: "OTA",
        ShiftPaymentMethod.DEBT: "Công nợ",
    }
    return labels.get(pm or ShiftPaymentMethod.CASH, "Tiền mặt")


def shift_transaction_type_for_method(
    pm: ShiftPaymentMethod | None,
    *,
    is_refund: bool = False,
) -> TransactionType:
    if is_refund:
        return TransactionType.CASH_EXPENSE
    mapping = {
        ShiftPaymentMethod.CASH: TransactionType.OTHER,
        ShiftPaymentMethod.CARD: TransactionType.CARD,
        ShiftPaymentMethod.BANK_TRANSFER: TransactionType.BRANCH_ACCOUNT,
        ShiftPaymentMethod.UNC: TransactionType.COMPANY_ACCOUNT,
        ShiftPaymentMethod.OTA: TransactionType.OTA,
        ShiftPaymentMethod.DEBT: TransactionType.UNC,
    }
    return mapping.get(pm or ShiftPaymentMethod.CASH, TransactionType.OTHER)


def _map_payment_method_to_transaction_type(
    pm: ShiftPaymentMethod,
) -> TransactionType:
    return shift_transaction_type_for_method(pm)


def build_shift_transaction_info(
    source: str,
    room_number: str = "",
    folio_code: str = "",
    guest_name: str = "",
    amount: Decimal | int | float | str = 0,
    method: str | ShiftPaymentMethod | None = None,
    reason: str | None = None,
) -> str:
    pm = normalize_shift_payment_method(method)
    parts = [source.strip()]
    if room_number:
        parts.append(str(room_number).strip())
    if folio_code:
        code = str(folio_code).strip()
        parts.append(code if code.startswith("#") else f"#{code}")
    if guest_name:
        parts.append(str(guest_name).strip())
    parts.append(shift_payment_method_label(pm))
    if reason:
        parts.append(str(reason).strip())
    return " - ".join(part for part in parts if part)


def _build_shift_description(
    folio: Folio,
    pm: ShiftPaymentMethod,
    amount: Decimal,
) -> str:
    folio_code = folio.folio_code or ""
    return build_shift_transaction_info(
        "Trả phòng",
        room_number=getattr(folio, 'room_number', None) or "",
        folio_code=folio_code,
        amount=amount,
        method=pm,
    )


def map_booking_payment_method(method: str) -> tuple[ShiftPaymentMethod, TransactionType]:
    pm = normalize_shift_payment_method(method or "Chi nhánh")
    return pm, shift_transaction_type_for_method(pm)


def post_booking_deposit_to_shift(
    db: Session,
    branch_id: int,
    user_id: Optional[int],
    booking_code: str,
    guest_name: str,
    amount,
    payment_method: str,
    room_label: str = "Đặt phòng",
) -> Optional[ShiftReportTransaction]:
    amount_dec = Decimal(str(amount or 0))
    if amount_dec <= 0:
        return None

    from ..db.models import Branch
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    branch_code = branch.branch_code if branch else "XX"
    pm, tx_type = map_booking_payment_method(payment_method)
    shift_tx = ShiftReportTransaction(
        transaction_code=_generate_shift_code(db, branch_code or "XX"),
        transaction_type=tx_type,
        amount=amount_dec,
        room_number=room_label,
        transaction_info=build_shift_transaction_info(
            "Cọc đặt phòng",
            room_number=room_label,
            folio_code=booking_code,
            guest_name=guest_name or "Khách",
            amount=amount_dec,
            method=pm,
        ),
        branch_id=branch_id,
        recorder_id=user_id,
        created_datetime=now_vn(),
        status=ShiftReportStatus.PENDING,
        payment_method=pm,
        is_auto_posted=True,
    )
    db.add(shift_tx)
    db.flush()
    return shift_tx


def sync_booking_deposit_to_shift(
    db: Session,
    booking,
    user_id: Optional[int],
) -> Optional[ShiftReportTransaction]:
    """Đồng bộ giao dịch cọc trong Sổ Giao ca khi đặt phòng được tạo/sửa.

    - Chưa từng ghi cọc + cọc mới > 0   → tạo mới (PENDING).
    - Giao dịch cọc còn PENDING          → sửa số tiền / phương thức tại chỗ;
                                           cọc về 0 → xoá mềm (DELETED).
    - Giao dịch cọc đã CHỐT (CLOSED)     → giữ nguyên dòng đã chốt, tạo bút toán
                                           điều chỉnh phần chênh lệch ở ca hiện tại.
    - Cọc đã áp vào folio (đã check-in)  → folio sở hữu dòng tiền, không đụng.

    Trả về giao dịch vừa tạo/sửa, hoặc None nếu không phát sinh thay đổi.
    """
    raw = dict(booking.raw_data or {})

    # Cọc đã chuyển vào folio lúc check-in: mọi điều chỉnh phải đi qua folio,
    # không sửa Sổ Giao ca ở đây để tránh ghi nhận trùng dòng tiền.
    if raw.get("deposit_applied_to_folio"):
        return None

    new_amount = Decimal(str(booking.deposit_amount or 0))
    method = booking.payment_method or raw.get("deposit_type") or "Chi nhánh"
    room_label = booking.room_type or "Đặt phòng"

    tx_id = raw.get("deposit_shift_transaction_id")
    existing = None
    if tx_id:
        existing = db.query(ShiftReportTransaction).filter(
            ShiftReportTransaction.id == tx_id
        ).first()

    # ── Chưa có giao dịch cọc hợp lệ (chưa post hoặc đã bị xoá) ──
    if existing is None or existing.status == ShiftReportStatus.DELETED:
        if new_amount <= 0:
            return None
        tx = post_booking_deposit_to_shift(
            db=db,
            branch_id=booking.branch_id,
            user_id=user_id,
            booking_code=booking.external_id,
            guest_name=booking.guest_name,
            amount=new_amount,
            payment_method=method,
            room_label=room_label,
        )
        if not tx:
            return None
        raw["deposit_shift_posted"] = True
        raw["deposit_shift_transaction_id"] = tx.id
        raw["deposit_shift_transaction_code"] = tx.transaction_code
        raw["deposit_applied_to_folio"] = False
        raw["deposit_shift_amount"] = float(new_amount)
        booking.raw_data = raw
        db.flush()
        return tx

    # ── Giao dịch còn PENDING: sửa tại chỗ ──
    if existing.status == ShiftReportStatus.PENDING:
        if new_amount <= 0:
            existing.status = ShiftReportStatus.DELETED
            existing.deleter_id = user_id
            existing.deleted_datetime = now_vn()
            raw["deposit_shift_amount"] = 0.0
            booking.raw_data = raw
            db.flush()
            return existing
        pm, tx_type = map_booking_payment_method(method)
        existing.amount = new_amount
        existing.payment_method = pm
        existing.transaction_type = tx_type
        existing.transaction_info = build_shift_transaction_info(
            "Cọc đặt phòng",
            room_number=room_label,
            folio_code=booking.external_id,
            guest_name=booking.guest_name or "Khách",
            amount=new_amount,
            method=pm,
        )
        raw["deposit_shift_amount"] = float(new_amount)
        booking.raw_data = raw
        db.flush()
        return existing

    # ── Giao dịch đã CHỐT (CLOSED): không sửa dòng đã chốt, tạo bút toán
    #    điều chỉnh phần chênh lệch ở ca hiện tại (PENDING). ──
    if existing.status == ShiftReportStatus.CLOSED:
        # Số tiền cọc mà Sổ Giao ca đang phản ánh (gồm cả các bút toán điều chỉnh
        # trước đó). Dùng để tính đúng chênh lệch khi sửa cọc nhiều lần.
        last_synced = Decimal(str(raw.get("deposit_shift_amount", existing.amount) or 0))
        diff = new_amount - last_synced
        if diff == 0:
            return None

        pm = existing.payment_method or normalize_shift_payment_method(method)
        old_int = int(last_synced)
        new_int = int(new_amount)
        if diff > 0:
            adj_type = shift_transaction_type_for_method(pm)
            adj_amount = diff
            reason = f"Tăng cọc {old_int:,}→{new_int:,}đ"
        else:
            adj_type = TransactionType.CASH_EXPENSE
            adj_amount = abs(diff)
            reason = f"Giảm cọc {old_int:,}→{new_int:,}đ"

        from ..db.models import Branch
        branch = db.query(Branch).filter(Branch.id == booking.branch_id).first()
        branch_code = branch.branch_code if branch else "XX"

        adj_tx = ShiftReportTransaction(
            transaction_code=_generate_shift_code(db, branch_code or "XX"),
            transaction_type=adj_type,
            amount=adj_amount,
            room_number=room_label,
            transaction_info=build_shift_transaction_info(
                "Điều chỉnh cọc đặt phòng",
                room_number=room_label,
                folio_code=booking.external_id,
                guest_name=booking.guest_name or "Khách",
                amount=adj_amount,
                method=pm,
                reason=reason,
            ),
            branch_id=booking.branch_id,
            recorder_id=user_id,
            created_datetime=now_vn(),
            status=ShiftReportStatus.PENDING,
            payment_method=pm,
            is_auto_posted=True,
        )
        db.add(adj_tx)
        raw["deposit_shift_amount"] = float(new_amount)
        booking.raw_data = raw
        db.flush()
        return adj_tx

    return None


def auto_post_checkout_to_shift(
    db: Session,
    folios: list[Folio],
    stay_id: int,
    checkout_time: datetime,
    user_id: int,
    room_number: str,
    refund_method: ShiftPaymentMethod | str | None = None,
) -> list[ShiftReportTransaction]:
    """
    Tự động tạo ShiftReportTransaction cho mỗi folio checkout.

    Args:
        db: SQLAlchemy session
        folios: Danh sách folio đã checkout
        stay_id: ID của HotelStay
        checkout_time: Thời điểm checkout
        user_id: ID user thực hiện checkout
        room_number: Số phòng

    Returns:
        Danh sách ShiftReportTransaction đã tạo
    """
    created_transactions = []

    for folio in folios:
        balance = folio.balance or Decimal("0")

        branch_id = folio.branch_id
        branch_code = ""
        if folio.branch:
            branch_code = folio.branch.branch_code or ""
        elif hasattr(folio, 'branch_id') and folio.branch_id:
            from ..db.models import Branch
            branch = db.query(Branch).filter(Branch.id == folio.branch_id).first()
            if branch:
                branch_code = branch.branch_code or ""

        folio_label = f"#{folio.folio_code or folio.id}"

        # ── XỬ LÝ REFUND (balance < 0) ──
        if balance < Decimal("0"):
            # Khách dư tiền → hoàn theo hình thức user chọn (refund_method).
            # transaction_type=CASH_EXPENSE đánh dấu "tiền ra"; payment_method
            # quyết định trừ vào quỹ nào (sổ ca refund-aware).
            refund_pm = normalize_shift_payment_method(refund_method) if refund_method else ShiftPaymentMethod.CASH
            transaction_code = _generate_shift_code(db, branch_code or "XX")
            shift_tx = ShiftReportTransaction(
                transaction_code=transaction_code,
                transaction_type=TransactionType.CASH_EXPENSE,
                amount=abs(balance),
                room_number=room_number,
                transaction_info=build_shift_transaction_info(
                    "Hoàn tiền",
                    room_number=room_number,
                    folio_code=folio_label,
                    amount=abs(balance),
                    method=refund_pm,
                    reason=f"Dư {int(abs(balance)):,}đ",
                ),
                branch_id=branch_id,
                recorder_id=user_id,
                created_datetime=checkout_time,
                status=ShiftReportStatus.PENDING,
                stay_id=stay_id,
                folio_id=folio.id,
                payment_method=refund_pm,
                is_auto_posted=True,
            )
            db.add(shift_tx)
            created_transactions.append(shift_tx)
            continue

        # ── ĐÃ THANH TOÁN ĐỦ (balance = 0) ──
        # Payment đã được ghi nhận vào shift report trực tiếp qua folio_api.py
        # → KHÔNG tạo thêm ở đây để tránh duplicate
        if balance == Decimal("0"):
            continue

        # ── XỬ LÝ CÔNG NỢ KHI CHECKOUT (balance > 0) ──
        # Khách chưa thanh toán đủ → ghi nhận là CÔNG NỢ (UNC = "Công nợ")
        payment_method = ShiftPaymentMethod.DEBT
        tx_type = _map_payment_method_to_transaction_type(payment_method)
        description = build_shift_transaction_info(
            "Công nợ",
            room_number=room_number,
            folio_code=folio_label,
            amount=balance,
            method=payment_method,
            reason=f"Còn thiếu {int(balance):,}đ",
        )
        transaction_code = _generate_shift_code(db, branch_code or "XX")

        shift_tx = ShiftReportTransaction(
            transaction_code=transaction_code,
            transaction_type=tx_type,  # UNC = "Công nợ"
            amount=abs(balance),
            room_number=room_number,
            transaction_info=description,
            branch_id=branch_id,
            recorder_id=user_id,
            created_datetime=checkout_time,
            status=ShiftReportStatus.PENDING,
            # PMS Integration fields
            stay_id=stay_id,
            folio_id=folio.id,
            payment_method=payment_method,
            is_auto_posted=True,
        )
        db.add(shift_tx)
        created_transactions.append(shift_tx)

    if created_transactions:
        db.flush()

    return created_transactions


def get_unclosed_pms_checkouts(
    db: Session,
    branch_id: int,
) -> dict:
    """
    Lấy tổng PMS checkout revenue chưa kết ca cho một chi nhánh.
    Dùng để auto-fill recorded revenue khi kết ca.

    Returns:
        {
            "total": Decimal,
            "by_method": {
                "CASH": Decimal,
                "CARD": Decimal,
                "BANK_TRANSFER": Decimal,
                "UNC": Decimal,
                "OTA": Decimal,
                "DEBT": Decimal,
            },
            "count": int,
            "transactions": [list of ShiftReportTransaction],
        }
    """
    from ..db.models import Branch

    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        return {"total": Decimal("0"), "by_method": {}, "count": 0, "transactions": []}

    txs = db.query(ShiftReportTransaction).filter(
        ShiftReportTransaction.branch_id == branch.id,
        ShiftReportTransaction.is_auto_posted == True,
        ShiftReportTransaction.status == ShiftReportStatus.PENDING,
    ).all()

    total = Decimal("0")
    by_method: dict[str, Decimal] = {}
    for tx in txs:
        total += abs(tx.amount)
        pm = tx.payment_method.value if tx.payment_method else "CASH"
        by_method[pm] = by_method.get(pm, Decimal("0")) + abs(tx.amount)

    return {
        "total": total,
        "by_method": by_method,
        "count": len(txs),
        "transactions": txs,
    }


def update_debt_shift_record(
    db: Session,
    folio_id: int,
    new_balance: Decimal,
    room_number: str = "",
) -> Optional[ShiftReportTransaction]:
    """
    Cập nhật bản ghi CÔNG NỢ cũ trong ShiftReport khi có thanh toán nợ.

    Logic:
    - Tìm bản ghi ShiftReportTransaction có folio_id khớp,
      payment_method=DEBT, transaction_type=UNC, status=PENDING
    - Nếu new_balance <= 0: Đã hết nợ → void/xóa bản ghi DEBT cũ
    - Nếu new_balance > 0: Vẫn còn nợ → cập nhật amount và description

    Args:
        db: SQLAlchemy session
        folio_id: ID folio đang thu nợ
        new_balance: Số dư mới sau khi thanh toán (folio.balance)
        room_number: Số phòng để cập nhật description

    Returns:
        Bản ghi DEBT đã cập nhật hoặc None nếu không tìm thấy
    """
    import logging
    logger = logging.getLogger("binbin-app")

    # Tìm bản ghi DEBT cũ trong shift report
    debt_tx = db.query(ShiftReportTransaction).filter(
        ShiftReportTransaction.folio_id == folio_id,
        ShiftReportTransaction.payment_method == ShiftPaymentMethod.DEBT,
        ShiftReportTransaction.transaction_type == TransactionType.UNC,
        ShiftReportTransaction.status == ShiftReportStatus.PENDING,
    ).first()

    if not debt_tx:
        logger.info(f"[DEBT_SYNC] No DEBT shift record found for folio_id={folio_id}")
        return None

    if new_balance <= Decimal("0"):
        # Hết nợ → xóa/void bản ghi DEBT cũ (soft delete)
        debt_tx.status = ShiftReportStatus.DELETED
        debt_tx.deleted_datetime = now_vn()
        debt_tx.transaction_info = (
            f"{debt_tx.transaction_info or ''} → Đã thanh toán hết nợ"
        )
        logger.info(
            f"[DEBT_SYNC] CLEARED: debt_tx id={debt_tx.id}, "
            f"folio_id={folio_id}, was={debt_tx.amount}, balance=0"
        )
    else:
        # Vẫn còn nợ → cập nhật số tiền nợ
        old_amount = debt_tx.amount
        debt_tx.amount = int(new_balance)
        folio_label = ""
        if debt_tx.folio:
            folio_label = f"#{debt_tx.folio.folio_code or debt_tx.folio_id}"
        debt_tx.transaction_info = build_shift_transaction_info(
            "Công nợ",
            room_number=room_number or debt_tx.room_number,
            folio_code=folio_label,
            amount=new_balance,
            method=ShiftPaymentMethod.DEBT,
            reason=f"Còn thiếu {int(new_balance):,}đ",
        )
        logger.info(
            f"[DEBT_SYNC] UPDATED: debt_tx id={debt_tx.id}, "
            f"folio_id={folio_id}, {old_amount} → {new_balance}"
        )

    db.flush()
    return debt_tx
