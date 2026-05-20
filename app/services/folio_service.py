from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..core.utils import VN_TZ
from ..db.models import (
    Folio,
    FolioStatus,
    FolioTransaction,
    FolioTransactionCategory,
    FolioTransactionType,
    HotelStay,
    Payment,
    PaymentMethod,
    PaymentStatus,
    ShiftReportStatus,
    ShiftReportTransaction,
)
from .pricing_service import money


def now_vn() -> datetime:
    return datetime.now(VN_TZ)


def generate_folio_code(db: Session, branch_id: int) -> str:
    today = now_vn().date()
    prefix = f"FOL-{today.strftime('%y%m%d')}-{branch_id:03d}"
    row = db.query(func.count(Folio.id)).filter(Folio.branch_id == branch_id).scalar() or 0
    return f"{prefix}-{row + 1:04d}"


def get_folio_financial_totals(db: Session, folio_ids: list[int]) -> dict[int, dict[str, Decimal]]:
    """Tổng hợp dòng tiền folio trong một query, tránh load toàn bộ transaction."""
    if not folio_ids:
        return {}

    zero = Decimal("0")
    rows = (
        db.query(
            FolioTransaction.folio_id,
            func.coalesce(func.sum(case(
                (
                    (
                        (FolioTransaction.amount > 0)
                        & (FolioTransaction.transaction_type.notin_([
                            FolioTransactionType.REFUND,
                            FolioTransactionType.REFUND_PAYMENT,
                        ]))
                    ),
                    FolioTransaction.amount,
                ),
                else_=0,
            )), 0).label("charge"),
            func.coalesce(func.sum(case(
                (
                    FolioTransaction.category == FolioTransactionCategory.DISCOUNT,
                    func.abs(FolioTransaction.amount),
                ),
                else_=0,
            )), 0).label("discount"),
            func.coalesce(func.sum(case(
                (
                    (
                        (FolioTransaction.amount < 0)
                        & (FolioTransaction.transaction_type.in_([
                            FolioTransactionType.PAYMENT,
                            FolioTransactionType.DEBT_PAYMENT,
                        ]))
                    ),
                    func.abs(FolioTransaction.amount),
                ),
                else_=0,
            )), 0).label("payment"),
            func.coalesce(func.sum(case(
                (
                    (
                        (FolioTransaction.amount < 0)
                        & (FolioTransaction.transaction_type == FolioTransactionType.DEPOSIT_USED)
                    ),
                    func.abs(FolioTransaction.amount),
                ),
                else_=0,
            )), 0).label("deposit_used"),
            func.coalesce(func.sum(case(
                (
                    (
                        (FolioTransaction.amount > 0)
                        & (
                            (FolioTransaction.category == FolioTransactionCategory.SERVICE)
                            | (FolioTransaction.transaction_type.in_([
                                FolioTransactionType.SERVICE_CHARGE,
                                FolioTransactionType.MINIBAR_CHARGE,
                            ]))
                        )
                    ),
                    FolioTransaction.amount,
                ),
                else_=0,
            )), 0).label("service_charge"),
            func.coalesce(func.sum(case(
                (
                    (
                        (FolioTransaction.amount > 0)
                        & (
                            (FolioTransaction.category.in_([
                                FolioTransactionCategory.SURCHARGE,
                                FolioTransactionCategory.OTHER,
                            ]))
                            | (FolioTransaction.transaction_type.in_([
                                FolioTransactionType.SURCHARGE,
                                FolioTransactionType.LATE_CHECKOUT_FEE,
                                FolioTransactionType.EARLY_CHECKIN_FEE,
                                FolioTransactionType.EXTRA_GUEST_FEE,
                            ]))
                        )
                    ),
                    FolioTransaction.amount,
                ),
                else_=0,
            )), 0).label("surcharge"),
            func.coalesce(func.sum(case(
                (
                    (
                        (FolioTransaction.amount > 0)
                        & (
                            (FolioTransaction.category == FolioTransactionCategory.ROOM)
                            | (FolioTransaction.transaction_type.in_([
                                FolioTransactionType.ROOM_CHARGE,
                                FolioTransactionType.HOURLY_CHARGE,
                            ]))
                        )
                    ),
                    FolioTransaction.amount,
                ),
                else_=0,
            )), 0).label("room_charge"),
        )
        .filter(
            FolioTransaction.folio_id.in_(folio_ids),
            FolioTransaction.is_voided == False,
        )
        .group_by(FolioTransaction.folio_id)
        .all()
    )

    totals = {
        folio_id: {
            "charge": zero,
            "discount": zero,
            "payment": zero,
            "deposit_used": zero,
            "service_charge": zero,
            "surcharge": zero,
            "room_charge": zero,
        }
        for folio_id in folio_ids
    }
    for row in rows:
        totals[row.folio_id] = {
            "charge": row.charge or zero,
            "discount": row.discount or zero,
            "payment": row.payment or zero,
            "deposit_used": row.deposit_used or zero,
            "service_charge": row.service_charge or zero,
            "surcharge": row.surcharge or zero,
            "room_charge": row.room_charge or zero,
        }
    return totals


def rebalance_folio(db: Session, folio_or_id) -> dict:
    # Support both folio object and folio_id
    if isinstance(folio_or_id, int):
        folio_id = folio_or_id
        folio = db.query(Folio).filter(Folio.id == folio_id).first()
        if not folio:
            return {"error": "Folio not found"}
    else:
        folio = folio_or_id
        folio_id = folio.id

    # total_charge = tổng amount > 0, LOẠI TRỪ REFUND + REFUND_PAYMENT
    charge = db.query(
        func.coalesce(func.sum(FolioTransaction.amount), 0)
    ).filter(
        FolioTransaction.folio_id == folio_id,
        FolioTransaction.amount > 0,
        FolioTransaction.is_voided == False,
        FolioTransaction.transaction_type.notin_([
            FolioTransactionType.REFUND,
            FolioTransactionType.REFUND_PAYMENT,
        ]),
    ).scalar() or Decimal("0")

    # total_discount = tổng amount của DISCOUNT (luôn là số âm trong DB, lấy abs)
    discount = db.query(
        func.coalesce(func.sum(func.abs(FolioTransaction.amount)), 0)
    ).filter(
        FolioTransaction.folio_id == folio_id,
        FolioTransaction.is_voided == False,
        FolioTransaction.category == FolioTransactionCategory.DISCOUNT,
    ).scalar() or Decimal("0")

    # total_paid = PAYMENT + DEPOSIT_USED (cả hai đều là tiền thực nhận)
    payment_paid = db.query(
        func.coalesce(func.sum(func.abs(FolioTransaction.amount)), 0)
    ).filter(
        FolioTransaction.folio_id == folio_id,
        FolioTransaction.amount < 0,
        FolioTransaction.is_voided == False,
        FolioTransaction.transaction_type.in_([
            FolioTransactionType.PAYMENT,
            FolioTransactionType.DEBT_PAYMENT,
        ]),
    ).scalar() or Decimal("0")

    deposit_used_paid = db.query(
        func.coalesce(func.sum(func.abs(FolioTransaction.amount)), 0)
    ).filter(
        FolioTransaction.folio_id == folio_id,
        FolioTransaction.amount < 0,
        FolioTransaction.is_voided == False,
        FolioTransaction.transaction_type == FolioTransactionType.DEPOSIT_USED,
    ).scalar() or Decimal("0")

    paid = payment_paid + deposit_used_paid

    # net_charge = charges - discounts
    net_charge = money(charge - discount)
    # balance = net_charge - total_paid (>0 = nợ, <0 = dư, 0 = đủ)
    balance = money(net_charge - paid)

    folio.total_charge = money(charge)
    folio.total_discount = money(discount)
    folio.total_paid = money(paid)
    folio.balance = balance

    db.flush()

    return {
        "folio_id": folio_id,
        "total_charge": float(folio.total_charge),
        "total_discount": float(folio.total_discount),
        "total_paid": float(folio.total_paid),
        "net_charge": float(net_charge),
        "balance": float(balance),
        "status": "ok"
    }


def recalculate_all_folios_cache(db: Session) -> dict:
    """Recalculate cache cho tất cả folios. Dùng để fix dữ liệu cũ."""
    folios = db.query(Folio).all()
    results = []
    for folio in folios:
        old_balance = folio.balance
        old_charge = folio.total_charge
        old_paid = folio.total_paid

        # Tính lại charge (loại trừ REFUND + REFUND_PAYMENT)
        charge = db.query(
            func.coalesce(func.sum(FolioTransaction.amount), 0)
        ).filter(
            FolioTransaction.folio_id == folio.id,
            FolioTransaction.amount > 0,
            FolioTransaction.is_voided == False,
            FolioTransaction.transaction_type.notin_([
                FolioTransactionType.REFUND,
                FolioTransactionType.REFUND_PAYMENT,
            ]),
        ).scalar() or Decimal("0")

        # Tính lại discount (category = DISCOUNT)
        discount = db.query(
            func.coalesce(func.sum(func.abs(FolioTransaction.amount)), 0)
        ).filter(
            FolioTransaction.folio_id == folio.id,
            FolioTransaction.is_voided == False,
            FolioTransaction.category == FolioTransactionCategory.DISCOUNT,
        ).scalar() or Decimal("0")

        # Tính lại paid (PAYMENT + DEPOSIT_USED)
        payment_paid = db.query(
            func.coalesce(func.sum(func.abs(FolioTransaction.amount)), 0)
        ).filter(
            FolioTransaction.folio_id == folio.id,
            FolioTransaction.amount < 0,
            FolioTransaction.is_voided == False,
            FolioTransaction.transaction_type.in_([
                FolioTransactionType.PAYMENT,
                FolioTransactionType.DEBT_PAYMENT,
            ]),
        ).scalar() or Decimal("0")

        deposit_used_paid = db.query(
            func.coalesce(func.sum(func.abs(FolioTransaction.amount)), 0)
        ).filter(
            FolioTransaction.folio_id == folio.id,
            FolioTransaction.amount < 0,
            FolioTransaction.is_voided == False,
            FolioTransaction.transaction_type == FolioTransactionType.DEPOSIT_USED,
        ).scalar() or Decimal("0")

        paid = payment_paid + deposit_used_paid

        # net_charge = charges - discounts
        net_charge = money(charge - discount)
        balance = money(net_charge - paid)

        folio.total_charge = money(charge)
        folio.total_discount = money(discount)
        folio.total_paid = money(paid)
        folio.balance = balance

        if old_balance != folio.balance or old_charge != folio.total_charge or old_paid != folio.total_paid:
            results.append({
                "folio_id": folio.id,
                "old": {"balance": str(old_balance), "charge": str(old_charge), "paid": str(old_paid)},
                "new": {"balance": str(folio.balance), "charge": str(folio.total_charge), "discount": str(folio.total_discount), "paid": str(folio.total_paid)},
            })

    return {"fixed_count": len(results), "changes": results}


def create_folio(
    db: Session,
    stay: HotelStay,
    notes: Optional[str] = None,
    currency: str = "VND",
    created_by: Optional[int] = None,
    invoice_name: Optional[str] = None,
    invoice_tax_code: Optional[str] = None,
    invoice_contact: Optional[str] = None,
    invoice_address: Optional[str] = None,
) -> Folio:
    folio = Folio(
        stay_id=stay.id,
        branch_id=stay.branch_id,
        folio_code=generate_folio_code(db, stay.branch_id),
        currency=currency,
        notes=notes,
        created_by=created_by,
        invoice_name=invoice_name or None,
        invoice_tax_code=invoice_tax_code or None,
        invoice_contact=invoice_contact or None,
        invoice_address=invoice_address or None,
    )
    db.add(folio)
    db.flush()
    rebalance_folio(db, folio)
    return folio


def transfer_transactions_between_folios(
    db: Session,
    source_folio: Folio,
    target_folio: Folio,
    tx_ids: list[int],
) -> list[FolioTransaction]:
    if source_folio.stay_id != target_folio.stay_id:
        raise ValueError("Không thể chuyển folio qua phòng/stay khác")

    txs = (
        db.query(FolioTransaction)
        .filter(
            FolioTransaction.id.in_(tx_ids),
            FolioTransaction.folio_id == source_folio.id,
        )
        .with_for_update()
        .all()
    )
    for tx in txs:
        tx.folio_id = target_folio.id

    rebalance_folio(db, source_folio)
    rebalance_folio(db, target_folio)
    return txs


def merge_folios(db: Session, target_folio: Folio, source_folio: Folio) -> None:
    if target_folio.id == source_folio.id:
        raise ValueError("Không thể gộp vào chính nó")
    if source_folio.stay_id != target_folio.stay_id:
        raise ValueError("Không cùng 1 phòng/stay")

    first_folio = (
        db.query(Folio)
        .filter(Folio.stay_id == source_folio.stay_id)
        .order_by(Folio.id.asc())
        .with_for_update()
        .first()
    )
    if first_folio and source_folio.id == first_folio.id:
        raise ValueError("Không thể xoá/gộp Hóa đơn gốc. Vui lòng gộp ngược lại vào Hóa đơn gốc.")

    db.query(FolioTransaction).filter(FolioTransaction.folio_id == source_folio.id).update({"folio_id": target_folio.id})
    db.query(Payment).filter(Payment.folio_id == source_folio.id).update({"folio_id": target_folio.id})
    db.flush()
    rebalance_folio(db, target_folio)
    db.delete(source_folio)


def tx_type_to_category(tx_type: FolioTransactionType) -> FolioTransactionCategory:
    mapping = {
        FolioTransactionType.ROOM_CHARGE: FolioTransactionCategory.ROOM,
        FolioTransactionType.HOURLY_CHARGE: FolioTransactionCategory.ROOM,
        FolioTransactionType.SERVICE_CHARGE: FolioTransactionCategory.SERVICE,
        FolioTransactionType.MINIBAR_CHARGE: FolioTransactionCategory.SERVICE,
        FolioTransactionType.SURCHARGE: FolioTransactionCategory.SURCHARGE,
        FolioTransactionType.LATE_CHECKOUT_FEE: FolioTransactionCategory.SURCHARGE,
        FolioTransactionType.EARLY_CHECKIN_FEE: FolioTransactionCategory.SURCHARGE,
        FolioTransactionType.EXTRA_GUEST_FEE: FolioTransactionCategory.SURCHARGE,
        FolioTransactionType.DISCOUNT_MANUAL: FolioTransactionCategory.DISCOUNT,
        FolioTransactionType.PROMOTION: FolioTransactionCategory.DISCOUNT,
        FolioTransactionType.OTA_COMMISSION: FolioTransactionCategory.DISCOUNT,
        FolioTransactionType.PAYMENT: FolioTransactionCategory.PAYMENT,
        FolioTransactionType.DEPOSIT_USED: FolioTransactionCategory.PAYMENT,
        FolioTransactionType.REFUND: FolioTransactionCategory.REFUND,
    }
    return mapping.get(tx_type, FolioTransactionCategory.OTHER)


def create_charge_transaction(
    db: Session,
    folio: Folio,
    tx_type: FolioTransactionType,
    description: str,
    amount: Decimal,
    created_by: Optional[int],
    quantity: Decimal = Decimal("1"),
    unit_price: Optional[Decimal] = None,
    reference_id: Optional[int] = None,
    reference_type: Optional[str] = None,
    skip_rebalance: bool = False,
) -> FolioTransaction:
    tx = FolioTransaction(
        folio_id=folio.id,
        stay_id=folio.stay_id,
        branch_id=folio.branch_id,
        transaction_type=tx_type,
        category=tx_type_to_category(tx_type),
        description=description,
        amount=money(amount),
        quantity=quantity,
        unit_price=money(unit_price) if unit_price is not None else None,
        reference_id=reference_id,
        reference_type=reference_type,
        created_by=created_by,
    )
    db.add(tx)
    if not skip_rebalance:
        rebalance_folio(db, folio)
    return tx


def create_discount_transaction(
    db: Session,
    folio: Folio,
    tx_type: FolioTransactionType,
    description: str,
    amount: Decimal,
    created_by: Optional[int],
) -> FolioTransaction:
    tx = FolioTransaction(
        folio_id=folio.id,
        stay_id=folio.stay_id,
        branch_id=folio.branch_id,
        transaction_type=tx_type,
        category=FolioTransactionCategory.DISCOUNT,
        description=description,
        amount=money(-amount),
        quantity=Decimal("1"),
        created_by=created_by,
    )
    db.add(tx)
    rebalance_folio(db, folio)
    return tx


def create_payment_with_transaction(
    db: Session,
    folio: Folio,
    amount: Decimal,
    method: PaymentMethod,
    created_by: Optional[int],
    transaction_code: Optional[str] = None,
    meta: Optional[dict] = None,
    tx_type: FolioTransactionType = FolioTransactionType.PAYMENT,
    description_prefix: str = "Thanh toán",
    paid_at: Optional[datetime] = None,
) -> tuple[Payment, FolioTransaction]:
    payment = Payment(
        folio_id=folio.id,
        stay_id=folio.stay_id,
        branch_id=folio.branch_id,
        amount=money(amount),
        method=method,
        status=PaymentStatus.SUCCESS,
        transaction_code=transaction_code or None,
        meta=meta,
        paid_at=paid_at or now_vn(),
        created_by=created_by,
    )
    db.add(payment)
    db.flush()

    tx = FolioTransaction(
        folio_id=folio.id,
        stay_id=folio.stay_id,
        branch_id=folio.branch_id,
        transaction_type=tx_type,
        category=FolioTransactionCategory.PAYMENT,
        description=f"{description_prefix} ({method.value})" + (f" — {transaction_code}" if transaction_code else ""),
        amount=money(-amount),
        reference_id=payment.id,
        reference_type="payment",
        created_by=created_by,
    )
    db.add(tx)
    rebalance_folio(db, folio)
    return payment, tx


def mark_transaction_void(db: Session, tx: FolioTransaction, reason: str, user_id: Optional[int]) -> None:
    tx.is_voided = True
    tx.void_reason = reason
    tx.void_by = user_id
    tx.void_at = now_vn()

    # Cascade: void ShiftReportTransaction nếu có liên kết
    if tx.shift_transaction_id:
        from ..db.models import ShiftReportTransaction, ShiftReportStatus
        shift_tx = db.query(ShiftReportTransaction).filter(
            ShiftReportTransaction.id == tx.shift_transaction_id
        ).first()
        if shift_tx and shift_tx.status == ShiftReportStatus.PENDING:
            shift_tx.status = ShiftReportStatus.DELETED
            shift_tx.deleter_id = user_id
            shift_tx.deleted_datetime = now_vn()

    rebalance_folio(db, tx.folio_id)


def refund_payment_and_create_transaction(
    db: Session,
    folio: Folio,
    payment: Payment,
    requested_amount: Decimal,
    reason: str,
    user_id: Optional[int],
) -> tuple[FolioTransaction, Decimal]:
    remaining_refundable = money(payment.amount - (payment.refunded_amount or Decimal("0")))
    refund_amount = requested_amount if requested_amount <= remaining_refundable else remaining_refundable
    if refund_amount <= Decimal("0"):
        raise ValueError("Payment không còn số dư để hoàn")

    payment.is_refunded = refund_amount == money(payment.amount)
    payment.refunded_amount = money((payment.refunded_amount or Decimal("0")) + refund_amount)
    payment.refund_reason = reason
    payment.refunded_by = user_id
    payment.refunded_at = now_vn()
    if payment.refunded_amount >= money(payment.amount):
        payment.status = PaymentStatus.REFUNDED

    tx = FolioTransaction(
        folio_id=folio.id,
        stay_id=folio.stay_id,
        branch_id=folio.branch_id,
        transaction_type=FolioTransactionType.REFUND,
        category=FolioTransactionCategory.REFUND,
        description=f"Hoàn tiền ({reason})",
        amount=refund_amount,
        reference_id=payment.id,
        reference_type="payment_refund",
        created_by=user_id,
    )
    db.add(tx)
    rebalance_folio(db, folio)
    return tx, refund_amount


def close_folio_with_balance_check(folio: Folio) -> None:
    if folio.balance > Decimal("0"):
        raise ValueError(f"Folio còn nợ {float(folio.balance):,.0f}đ — không thể đóng. Vui lòng thanh toán trước.")
    folio.status = FolioStatus.CLOSED
    folio.closed_at = now_vn()
