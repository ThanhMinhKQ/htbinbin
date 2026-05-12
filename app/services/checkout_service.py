"""
PMS Unified Checkout Service — Enterprise Checkout Orchestration

Nguyên tắc kiến trúc:
  1. Folio là NGUỒN DUY NHẤT cho mọi số liệu tài chính.
     stay.deposit / stay.total_price chỉ là cache/metadata.
  2. Mọi charge đều INSERT vào FolioTransaction, KHÔNG UPDATE existing rows.
  3. Sau khi INSERT, gọi rebalance_folio() rồi dùng folio.balance cho tính toán.
  4. stay.total_price = net_charge (charges - discounts) tại thời điểm checkout.
     Đây là SNAPSHOT chính xác — KHÔNG bao gồm REFUND hay REFUND_PAYMENT.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, Optional
from dataclasses import dataclass

from sqlalchemy.orm import Session, selectinload

from ..core.utils import VN_TZ
from ..db.models import (
    Booking,
    BookingStatus,
    DebtRecord,
    Folio,
    FolioStatus,
    FolioTransaction,
    FolioTransactionCategory,
    FolioTransactionType,
    HotelGuest,
    HotelRoom,
    HotelStay,
    HotelStayStatus,
    RoomCondition,
)
from .folio_service import get_folio_financial_totals, rebalance_folio
from .room_inventory_service import InventoryService
from .pricing_service import (
    calculate_full_charge,
    detect_pricing_mode_from_breakdown,
    money,
    MODE_TO_STAY_TYPE,
)


@dataclass
class CheckoutCharges:
    total: Decimal
    breakdown: list[dict]
    pricing_mode_final: Optional[str]
    room_charge: Decimal
    surcharge_total: Decimal
    discount_total: Decimal
    extra_charge: Decimal


def calculate_checkout_charges(
    db: Session,
    stay: HotelStay,
    room: HotelRoom,
    room_type_obj,
    now,
) -> CheckoutCharges:
    effective_mode = stay.pricing_mode_initial or "AUTO"
    effective_stay_type = MODE_TO_STAY_TYPE.get(effective_mode, "AUTO")

    room_charge_total, breakdown = calculate_full_charge(
        effective_stay_type, room_type_obj, stay.check_in_at, now
    )

    pricing_mode_final = detect_pricing_mode_from_breakdown(breakdown)

    surcharge_total = Decimal("0")
    for item in breakdown:
        t = item.get("type")
        if t in ("EARLY_CHECKIN_FEE", "LATE_CHECKOUT_FEE", "SURCHARGE"):
            surcharge_total += money(item.get("amount", 0))

    return CheckoutCharges(
        total=money(room_charge_total),
        breakdown=breakdown,
        pricing_mode_final=pricing_mode_final,
        room_charge=money(room_charge_total),
        surcharge_total=surcharge_total,
        discount_total=Decimal("0"),
        extra_charge=Decimal("0"),
    )


def execute_checkout(
    db: Session,
    stay_id: int,
    discount: Decimal,
    extra_charge: Decimal,
    user_id: Optional[int],
    now,
) -> dict:
    """
    Unified Checkout Flow — Tất cả trong một atomic transaction.

    Luồng:
      1. Lock stay + folio
      2. Tính pricing từ engine
      3. Post charges vào FolioTransaction (INSERT ONLY)
      4. Post discount/extra_charge
      5. Rebalance tất cả folios (1 lần duy nhất)
      6. Xử lý balance:
         - balance > 0  → DEBT status
         - balance < 0  → AUTO REFUND transaction
         - balance = 0  → CLOSED
      7. Update stay status + checkout time
      8. Update guest check_out_at
    """
    # ── 1. Lock & Fetch ──────────────────────────────────────────────────────
    stay = (
        db.query(HotelStay)
        .options(selectinload(HotelStay.room).selectinload(HotelRoom.room_type_obj))
        .filter(HotelStay.id == stay_id, HotelStay.status == HotelStayStatus.ACTIVE)
        .with_for_update()
        .first()
    )
    if not stay:
        raise ValueError("Không tìm thấy lưu trú hoặc đã trả phòng")

    room = stay.room
    rt = room.room_type_obj if room else None
    if not rt:
        raise ValueError("Thiếu thông tin loại phòng để tính tiền")

    # ── 2. Calculate Pricing ─────────────────────────────────────────────────
    is_ota_manual = stay.pricing_mode_initial == "OTA_MANUAL" and stay.total_price and stay.total_price > 0
    charges = calculate_checkout_charges(db, stay, room, rt, now)
    stay.pricing_mode_final = "OTA_MANUAL" if is_ota_manual else charges.pricing_mode_final

    # ── 3. Fetch & Lock Folios ───────────────────────────────────────────────
    folios = (
        db.query(Folio)
        .filter(Folio.stay_id == stay_id, Folio.status == FolioStatus.OPEN)
        .order_by(Folio.id.asc())
        .with_for_update()
        .all()
    )
    if not folios:
        raise ValueError("Không tìm thấy folio đang mở để tất toán")

    first_folio = folios[0]

    # ── 4. Post Room Charges to Folio ────────────────────────────────────────
    if is_ota_manual:
        db.add(FolioTransaction(
            folio_id=first_folio.id,
            stay_id=stay_id,
            branch_id=stay.branch_id,
            transaction_type=FolioTransactionType.ROOM_CHARGE,
            category=FolioTransactionCategory.ROOM,
            description="Tiền phòng OTA thực thu",
            amount=money(stay.total_price),
            quantity=Decimal("1"),
            unit_price=money(stay.total_price),
            reference_id=stay_id,
            reference_type="hotel_stay",
            created_by=user_id,
        ))
    else:
        for item in charges.breakdown:
            item_type = item.get("type")
            amount = money(item.get("amount", 0))

            if item_type == "EARLY_CHECKIN_FEE":
                tx_type = FolioTransactionType.EARLY_CHECKIN_FEE
                category = FolioTransactionCategory.SURCHARGE
            elif item_type == "LATE_CHECKOUT_FEE":
                tx_type = FolioTransactionType.LATE_CHECKOUT_FEE
                category = FolioTransactionCategory.SURCHARGE
            elif item_type == "ROOM_CHARGE":
                tx_type = FolioTransactionType.ROOM_CHARGE
                category = FolioTransactionCategory.ROOM
            elif item_type == "HOURLY_CHARGE":
                tx_type = FolioTransactionType.HOURLY_CHARGE
                category = FolioTransactionCategory.ROOM
            else:
                tx_type = FolioTransactionType.SURCHARGE
                category = FolioTransactionCategory.SURCHARGE

            db.add(FolioTransaction(
                folio_id=first_folio.id,
                stay_id=stay_id,
                branch_id=stay.branch_id,
                transaction_type=tx_type,
                category=category,
                description=item.get("description", item_type),
                amount=amount,
                quantity=Decimal("1"),
                unit_price=amount,
                reference_id=stay_id,
                reference_type="hotel_stay",
                created_by=user_id,
            ))

    # ── 5. Post Extra Charge ─────────────────────────────────────────────────
    if extra_charge > Decimal("0"):
        db.add(FolioTransaction(
            folio_id=first_folio.id,
            stay_id=stay_id,
            branch_id=stay.branch_id,
            transaction_type=FolioTransactionType.SURCHARGE,
            category=FolioTransactionCategory.SURCHARGE,
            description="Phí dịch vụ / bồi thường khác",
            amount=extra_charge,
            quantity=Decimal("1"),
            unit_price=extra_charge,
            reference_id=stay_id,
            reference_type="hotel_stay",
            created_by=user_id,
        ))

    # ── 6. Post Discount ─────────────────────────────────────────────────────
    if discount > Decimal("0"):
        db.add(FolioTransaction(
            folio_id=first_folio.id,
            stay_id=stay_id,
            branch_id=stay.branch_id,
            transaction_type=FolioTransactionType.DISCOUNT_MANUAL,
            category=FolioTransactionCategory.DISCOUNT,
            description="Giảm giá toàn bộ",
            amount=money(-discount),
            quantity=Decimal("1"),
            created_by=user_id,
        ))

    # Flush các charges, surcharge, discount vào DB trước
    db.flush()

    # ── 7. Rebalance All Folios — ONCE ───────────────────────────────────────
    for folio in folios:
        rebalance_folio(db, folio)
    # ── Tính balance bằng SQL aggregate một lượt cho toàn bộ folio ───────────
    folio_totals = get_folio_financial_totals(db, [f.id for f in folios])
    total_charge_calc = sum((folio_totals[f.id]["charge"] for f in folios), Decimal("0"))
    total_discount_calc = sum((folio_totals[f.id]["discount"] for f in folios), Decimal("0"))
    total_paid_calc = sum(
        (folio_totals[f.id]["payment"] + folio_totals[f.id]["deposit_used"] for f in folios),
        Decimal("0"),
    )
    deposit_used_total = sum((folio_totals[f.id]["deposit_used"] for f in folios), Decimal("0"))

    # net_charge = charges - discounts (tiền khách phải trả)
    net_charge = money(total_charge_calc - total_discount_calc)
    # balance = net_charge - total_paid (>0 = nợ, <0 = dư, 0 = đủ)
    total_balance = money(net_charge - total_paid_calc)

    # ── stay.total_price = SNAPSHOT tại thời điểm checkout ────────────────
    # = net_charge (charges - discounts), KHÔNG bao gồm REFUND
    final_total = net_charge

    # ── 8. Handle Balance & Folio Status ──────────────────────────────────────
    if total_balance > Decimal("0"):
        # CÓ NỢ → Checkout với DEBT
        for folio in folios:
            folio.status = FolioStatus.DEBT
            folio.debt_amount = folio.balance
            folio.debt_status = "pending"

        dr = DebtRecord(
            folio_id=first_folio.id,
            stay_id=stay_id,
            branch_id=first_folio.branch_id,
            debt_amount=total_balance,
            paid_amount=Decimal("0"),
            remaining_amount=total_balance,
            status="pending",
            note=None,
            created_by=user_id,
        )
        db.add(dr)

    elif total_balance < Decimal("0"):
        # DƯ TIỀN → Auto refund
        refund_amount = money(abs(total_balance))
        db.add(FolioTransaction(
            folio_id=first_folio.id,
            stay_id=stay_id,
            branch_id=stay.branch_id,
            transaction_type=FolioTransactionType.REFUND,
            category=FolioTransactionCategory.REFUND,
            description="Hoàn tiền tự động do khách trả dư khi checkout",
            amount=refund_amount,
            quantity=Decimal("1"),
            created_by=user_id,
        ))
        rebalance_folio(db, first_folio)

    # balance = 0 hoặc đã refund xong → CLOSED
    for folio in folios:
        if folio.balance <= Decimal("0"):
            folio.status = FolioStatus.CLOSED
            folio.closed_at = now

    # ── 9. Update Stay Status ───────────────────────────────────────────────
    stay.check_out_at = now
    stay.status = HotelStayStatus.CHECKED_OUT
    room.condition = RoomCondition.DIRTY
    stay.total_price = final_total
    stay.discount = discount
    stay.extra_charge = extra_charge

    booking = db.query(Booking).filter(Booking.stay_id == stay_id).first()
    inventory = InventoryService(db)
    if booking:
        booking.reservation_status = "CHECKED_OUT"
        booking.status = BookingStatus.COMPLETED
        booking.updated_by = user_id
        booking.updated_at = now
        room_type_id = (booking.raw_data or {}).get("room_type_id") or room.room_type_id
        inventory.release_sold(
            stay_id=stay_id,
            branch_id=stay.branch_id,
            room_type_id=int(room_type_id),
            check_in=booking.check_in,
            check_out=booking.check_out,
            user_id=user_id,
        )
    else:
        inv_check_in = stay.check_in_at.date()
        inv_check_out = now.date()
        if inv_check_out <= inv_check_in:
            inv_check_out = inv_check_in + timedelta(days=1)
        inventory.release_sold(
            stay_id=stay_id,
            branch_id=stay.branch_id,
            room_type_id=room.room_type_id,
            check_in=inv_check_in,
            check_out=inv_check_out,
            user_id=user_id,
        )

    # ── 10. Update Guest Check-out ──────────────────────────────────────────
    db.query(HotelGuest).filter(
        HotelGuest.stay_id == stay_id,
        HotelGuest.check_out_at == None,
    ).update({"check_out_at": now}, synchronize_session=False)

    # ── 11. Auto-post to Shift Report ──────────────────────────────────────
    shift_transactions = []
    try:
        from .shift_report_service import auto_post_checkout_to_shift
        shift_transactions = auto_post_checkout_to_shift(
            db=db,
            folios=folios,
            stay_id=stay_id,
            checkout_time=now,
            user_id=user_id,
            room_number=room.room_number,
        )
    except Exception:
        # Non-critical: shift report posting should not block checkout
        import logging
        logging.getLogger(__name__).warning(
            f"[ShiftReport] Auto-post failed for stay {stay_id}: check service availability"
        )

    # ── 12. Return Result ───────────────────────────────────────────────────
    if total_balance > Decimal("0"):
        checkout_status: Literal["checked_out_success", "checked_out_with_debt", "checked_out_with_refund"] = "checked_out_with_debt"
    elif total_balance < Decimal("0"):
        checkout_status = "checked_out_with_refund"
    else:
        checkout_status = "checked_out_success"

    return {
        "status": checkout_status,
        "debt": total_balance if total_balance > Decimal("0") else Decimal("0"),
        "refund": abs(total_balance) if total_balance < Decimal("0") else Decimal("0"),
        "deposit_used_total": float(money(deposit_used_total)),
        "stay": stay,
        "room": room,
        "folios": folios,
        "final_total": final_total,
        "breakdown": charges.breakdown,
        "pricing_mode_final": charges.pricing_mode_final,
        # ── Shift Report Integration ─────────────────────────────────────
        "shift_transactions_count": len(shift_transactions),
        "shift_transactions": [
            {
                "id": tx.id,
                "transaction_code": tx.transaction_code,
                "amount": float(tx.amount),
                "payment_method": tx.payment_method.value if tx.payment_method else "CASH",
                "room_number": tx.room_number,
            }
            for tx in shift_transactions
        ],
    }


def preview_checkout(
    db: Session,
    stay_id: int,
    discount: Decimal = Decimal("0"),
    extra_charge: Decimal = Decimal("0"),
    now=None,
) -> dict:
    """
    Preview checkout — tính trước không thay đổi gì.
    Dùng cho UI xem trước balance trước khi checkout thật sự.
    """
    stay = (
        db.query(HotelStay)
        .options(selectinload(HotelStay.room).selectinload(HotelRoom.room_type_obj))
        .filter(HotelStay.id == stay_id)
        .first()
    )
    if not stay:
        raise ValueError("Không tìm thấy lưu trú")

    room = stay.room
    rt = room.room_type_obj if room else None
    if not rt:
        raise ValueError("Thiếu thông tin loại phòng")

    effective_now = now or datetime.now(VN_TZ)

    # Đối với checked-out stays: dùng check_out_at thực tế thay vì now để tránh
    # pricing engine tính lại room_charge với end_time = hiện tại (sai số)
    # Đối với active stays: dùng now (thời gian thực)
    effective_end = (
        stay.check_out_at
        if stay.status == HotelStayStatus.CHECKED_OUT and stay.check_out_at
        else effective_now
    )

    # Pricing engine: tính room charge cho thời gian lưu trú
    pms_reference_mode = "AUTO" if stay.pricing_mode_initial == "OTA_MANUAL" else MODE_TO_STAY_TYPE.get(stay.pricing_mode_initial or "AUTO", "AUTO")
    room_charge_total, breakdown = calculate_full_charge(
        pms_reference_mode,
        rt,
        stay.check_in_at,
        effective_end,
    )

    pms_reference_room_charge = room_charge_total
    is_ota_manual = stay.pricing_mode_initial == "OTA_MANUAL" and stay.total_price and stay.total_price > 0
    if is_ota_manual:
        room_charge_total = money(stay.total_price)

    # Lấy folio hiện tại
    folios = (
        db.query(Folio)
        .filter(Folio.stay_id == stay_id)
        .order_by(Folio.id.asc())
        .all()
    )

    # Tính từ DB bằng aggregate, không kéo toàn bộ ledger về Python.
    folio_totals = get_folio_financial_totals(db, [f.id for f in folios])
    deposit_used = sum((folio_totals[f.id]["deposit_used"] for f in folios), Decimal("0"))
    effective_paid = sum((folio_totals[f.id]["payment"] for f in folios), Decimal("0"))
    existing_charges = sum((folio_totals[f.id]["charge"] for f in folios), Decimal("0"))
    existing_service_charges = sum((folio_totals[f.id]["service_charge"] for f in folios), Decimal("0"))
    existing_surcharge_charges = sum((folio_totals[f.id]["surcharge"] for f in folios), Decimal("0"))
    existing_discounts = sum((folio_totals[f.id]["discount"] for f in folios), Decimal("0"))

    # Projected balance: trừ cả payment lẫn deposit_used
    projected_charges = room_charge_total + existing_charges + extra_charge
    projected_discounts = discount + existing_discounts
    projected_balance = projected_charges - projected_discounts - effective_paid - deposit_used

    # net_charge = charges - discounts (tổng tiền khách phải trả sau khi giảm giá)
    net_charge = projected_charges - projected_discounts

    return {
        "stay_id": stay_id,
        "room_number": room.room_number if room else None,
        "check_in_at": stay.check_in_at.isoformat(),
        "check_out_at": effective_end.isoformat(),
        "room_charge": float(money(room_charge_total)),
        "existing_charges": float(money(existing_charges)),
        "existing_service_charges": float(money(existing_service_charges)),
        "existing_surcharge_charges": float(money(existing_surcharge_charges)),
        "extra_charge": float(money(extra_charge)),
        "discount": float(money(discount)),
        "existing_discounts": float(money(existing_discounts)),
        "total_discounts": float(money(projected_discounts)),
        "deposit_used": float(money(deposit_used)),
        "effective_paid": float(money(effective_paid)),
        "total_paid": float(money(effective_paid + deposit_used)),
        "net_charge": float(money(net_charge)),
        "projected_balance": float(money(projected_balance)),
        "final_total": float(money(net_charge)),
        "breakdown": [
            {**b, "amount": float(money(b.get("amount", 0)))}
            for b in breakdown
        ],
        "ota_price_mode": "manual_channel_total" if is_ota_manual else None,
        "ota_actual_total": float(money(room_charge_total)) if is_ota_manual else None,
        "pms_reference_total": float(money(pms_reference_room_charge)) if is_ota_manual else None,
        "ota_price_delta": float(money(room_charge_total - pms_reference_room_charge)) if is_ota_manual else None,
        "folio_summary": [
            {
                "id": f.id,
                "folio_code": f.folio_code,
                "total_charge": float(f.total_charge or Decimal("0")),
                "total_discount": float(f.total_discount or Decimal("0")),
                "net_charge": float((f.total_charge or Decimal("0")) - (f.total_discount or Decimal("0"))),
                "total_paid": float(f.total_paid or Decimal("0")),
                "balance": float(f.balance or Decimal("0")),
                "effective_paid": float(effective_paid),
                "deposit_used": float(deposit_used),
                "status": f.status.value if f.status else "OPEN",
            }
            for f in folios
        ],
        "needs_payment": projected_balance > 0,
        "needs_refund": projected_balance < 0,
    }
