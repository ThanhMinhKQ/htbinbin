# app/services/guest_crm_integration.py
"""
Guest CRM Integration - Hook vào checkout flow để ghi nhận dữ liệu CRM
Được gọi sau khi checkout thành công
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from sqlalchemy.orm import Session

from ..db.models import (
    Guest, GuestMembership, GuestStaySummary, GuestServiceUsage,
    GuestPaymentSummary, GuestStayMapping, HotelStay, HotelGuest, HotelRoom,
    Folio, FolioTransaction, Payment, MemberTier,
)
from ..services.guest_crm_service import (
    calculate_tier, calculate_loyalty_points, update_membership_stats,
    create_stay_summary, create_service_usage, create_payment_summary,
    get_or_create_membership, calculate_folio_crm_amounts, get_tier_multiplier,
)
from ..core.config import logger
from ..core.utils import VN_TZ


def _now_vn() -> datetime:
    return datetime.now(VN_TZ)


def _value(v):
    return v.value if hasattr(v, "value") else v


def on_checkout_complete(
    db: Session,
    stay_id: int,
    folio_id: int,
    user_id: Optional[int] = None,
) -> dict:
    """
    Hook được gọi sau khi checkout thành công.
    Ghi nhận tất cả dữ liệu cần thiết cho CRM:
    - GuestStayMapping (quan hệ khách cùng ở)
    - GuestStaySummary
    - GuestServiceUsage (từ FolioTransaction)
    - GuestPaymentSummary (từ Payment)
    - Cập nhật membership stats

    Args:
        db: Database session
        stay_id: ID của HotelStay đã checkout
        folio_id: ID của Folio sau checkout
        user_id: ID của user thực hiện checkout
    """
    results = {
        "stay_mappings_created": 0,
        "stay_summaries_created": 0,
        "service_usages_created": 0,
        "payment_summaries_created": 0,
        "memberships_updated": 0,
        "guests_processed": [],
    }

    # Fetch stay and folio within this transaction
    stay = db.query(HotelStay).filter(HotelStay.id == stay_id).first()
    if not stay:
        logger.warning(f"[CRM] Stay {stay_id} not found for CRM integration")
        return results

    folio = db.query(Folio).filter(Folio.id == folio_id).first()
    if not folio:
        logger.warning(f"[CRM] Folio {folio_id} not found for CRM integration")
        return results

    # Get all guests for this stay
    hotel_guests = db.query(HotelGuest).filter(
        HotelGuest.stay_id == stay_id,
        HotelGuest.guest_id.isnot(None),
    ).all()

    # Get all guest_ids for this stay
    guest_ids = [hg.guest_id for hg in hotel_guests if hg.guest_id]

    if not guest_ids:
        logger.warning(f"[CRM] No guests found for stay {stay_id}")
        return results

    num_guests = len(guest_ids)

    # 1. Tạo GuestStayMapping cho tất cả guests trong stay này
    from ..db.models import GuestStayMapping
    for guest_id in guest_ids:
        # Check if mapping already exists
        existing = db.query(GuestStayMapping).filter(
            GuestStayMapping.guest_id == guest_id,
            GuestStayMapping.stay_id == stay_id,
        ).first()
        if not existing:
            mapping = GuestStayMapping(
                guest_id=guest_id,
                stay_id=stay_id,
                branch_id=stay.branch_id,
                room_number=stay.room.room_number if stay.room else None,
                check_in_at=stay.check_in_at,
                check_out_at=stay.check_out_at,
                is_primary=(hotel_guests[0].guest_id == guest_id if hotel_guests else False),
            )
            db.add(mapping)
            results["stay_mappings_created"] += 1

    db.flush()

    # 2. Xử lý cho từng guest
    for guest_id in guest_ids:
        guest = db.query(Guest).filter(Guest.id == guest_id).first()
        if not guest:
            continue

        # 2a. Create Stay Summary
        try:
            summary = create_stay_summary(
                db=db,
                guest_id=guest_id,
                stay=stay,
                folio=folio,
                guest_count=num_guests,
            )
            results["stay_summaries_created"] += 1
        except Exception as e:
            logger.error(f"[CRM] Error creating stay summary for guest {guest_id}: {e}")

        # 2b. Create Service Usage records
        try:
            service_count = _create_service_usages(
                db=db,
                guest_id=guest_id,
                stay=stay,
                folio=folio,
            )
            results["service_usages_created"] += service_count
        except Exception as e:
            logger.error(f"[CRM] Error creating service usage for guest {guest_id}: {e}")

        # 2c. Create Payment Summary records
        try:
            payment_count = _create_payment_summaries(
                db=db,
                guest_id=guest_id,
                stay=stay,
                folio=folio,
            )
            results["payment_summaries_created"] += payment_count
        except Exception as e:
            logger.error(f"[CRM] Error creating payment summary for guest {guest_id}: {e}")

        # 2d. Update Membership
        try:
            _update_membership_on_checkout(
                db=db,
                guest_id=guest_id,
                stay=stay,
                folio=folio,
                num_guests=num_guests,
                user_id=user_id,
            )
            results["memberships_updated"] += 1
        except Exception as e:
            logger.error(f"[CRM] Error updating membership for guest {guest_id}: {e}")

        results["guests_processed"].append({
            "guest_id": guest_id,
            "guest_name": guest.full_name,
        })

    db.flush()
    return results


def _create_service_usages(
    db: Session,
    guest_id: int,
    stay: HotelStay,
    folio: Folio,
) -> int:
    """Tạo GuestServiceUsage records từ các FolioTransaction"""
    # Get service-related transactions
    service_types = ["MINIBAR_CHARGE", "SERVICE_CHARGE"]

    transactions = db.query(FolioTransaction).filter(
        FolioTransaction.folio_id == folio.id,
        FolioTransaction.transaction_type.in_(service_types),
        FolioTransaction.is_voided == False,
    ).all()

    count = 0
    for tx in transactions:
        # Check if already created
        existing = db.query(GuestServiceUsage).filter(
            GuestServiceUsage.folio_transaction_id == tx.id
        ).first()
        if existing:
            continue

        # Map transaction type to category
        # Chỉ xử lý các loại thực tế có trong hệ thống
        tx_type = tx.transaction_type.value if hasattr(tx.transaction_type, 'value') else str(tx.transaction_type)
        category_map = {
            "MINIBAR_CHARGE": "MINIBAR",
            "SERVICE_CHARGE": "SERVICE",
        }
        category = category_map.get(tx_type, "OTHER")

        # Get room number
        room_number = None
        if stay.room:
            room_number = stay.room.room_number

        usage = GuestServiceUsage(
            guest_id=guest_id,
            stay_id=stay.id,
            branch_id=stay.branch_id,
            service_category=category,
            service_name=tx.description or category,
            quantity=tx.quantity or Decimal("1"),
            unit_price=tx.unit_price,
            total_amount=abs(tx.amount),
            room_number=room_number,
            used_at=tx.created_at or _now_vn(),
            folio_transaction_id=tx.id,
            created_by=tx.created_by,
        )
        db.add(usage)
        count += 1

    if count > 0:
        db.flush()

    return count


def _create_payment_summaries(
    db: Session,
    guest_id: int,
    stay: HotelStay,
    folio: Folio,
) -> int:
    """Tạo GuestPaymentSummary records từ các Payment"""
    # Get all payments for this folio
    payments = db.query(Payment).filter(
        Payment.folio_id == folio.id,
    ).all()

    count = 0
    for payment in payments:
        # Check if already created
        existing = db.query(GuestPaymentSummary).filter(
            GuestPaymentSummary.guest_id == guest_id,
            GuestPaymentSummary.payment_id == payment.id,
        ).first()
        if existing:
            continue

        # Determine payment type
        payment_type = "PAYMENT"
        if "deposit" in (payment.meta or {}).get("source", "").lower():
            payment_type = "DEPOSIT"
        elif payment.is_refunded:
            payment_type = "REFUND"

        # Get room number
        room_number = None
        if stay.room:
            room_number = stay.room.room_number

        summary = GuestPaymentSummary(
            guest_id=guest_id,
            stay_id=stay.id,
            folio_id=folio.id,
            payment_id=payment.id,
            branch_id=stay.branch_id,
            amount=payment.amount,
            payment_type=payment_type,
            payment_method=payment.method.value if hasattr(payment.method, 'value') else str(payment.method),
            transaction_code=payment.transaction_code,
            room_number=room_number,
            paid_at=payment.paid_at or _now_vn(),
            is_voided=payment.is_refunded or False,
            void_reason=payment.refund_reason,
        )
        db.add(summary)
        count += 1

    # Also create summaries from FolioTransactions (for DEPOSIT_USED etc)
    payment_tx_types = ["DEPOSIT_USED", "PAYMENT", "DEBT_PAYMENT", "REFUND_PAYMENT"]
    transactions = db.query(FolioTransaction).filter(
        FolioTransaction.folio_id == folio.id,
        FolioTransaction.transaction_type.in_(payment_tx_types),
        FolioTransaction.is_voided == False,
    ).all()

    for tx in transactions:
        # Only process PAYMENT transactions that have payment reference (actual payments)
        if tx.reference_type == "payment" and tx.reference_id:
            continue  # Already handled above via Payment

        # Check if already created via payment
        if tx.reference_id:
            existing = db.query(GuestPaymentSummary).filter(
                GuestPaymentSummary.guest_id == guest_id,
                GuestPaymentSummary.payment_id == tx.reference_id,
            ).first()
            if existing:
                continue

        tx_type = tx.transaction_type.value if hasattr(tx.transaction_type, 'value') else str(tx.transaction_type)
        payment_type_map = {
            "DEPOSIT_USED": "DEPOSIT",
            "PAYMENT": "PAYMENT",
            "DEBT_PAYMENT": "PAYMENT",
            "REFUND_PAYMENT": "REFUND",
        }
        payment_type = payment_type_map.get(tx_type, "PAYMENT")

        room_number = None
        if stay.room:
            room_number = stay.room.room_number

        summary = GuestPaymentSummary(
            guest_id=guest_id,
            stay_id=stay.id,
            folio_id=folio.id,
            payment_id=None,
            branch_id=stay.branch_id,
            amount=abs(tx.amount),
            payment_type=payment_type,
            payment_method=_value(tx.shift_transaction.payment_method) if tx.shift_transaction and tx.shift_transaction.payment_method else "RECORD",
            transaction_code=tx.shift_transaction.transaction_code if tx.shift_transaction else None,
            room_number=room_number,
            paid_at=tx.created_at or _now_vn(),
        )
        db.add(summary)
        count += 1

    if count > 0:
        db.flush()

    return count


def _update_membership_on_checkout(
    db: Session,
    guest_id: int,
    stay: HotelStay,
    folio: Folio,
    num_guests: int = 1,
    user_id: Optional[int] = None,
) -> None:
    """Cập nhật membership stats sau checkout"""
    membership = get_or_create_membership(db, guest_id)
    guest = db.query(Guest).filter(Guest.id == guest_id).first()

    if not guest:
        return

    amounts = calculate_folio_crm_amounts(db, folio)
    paid_amount = amounts["paid_amount"]
    debt_amount = amounts["debt_amount"]
    
    # Chia tiền để tính điểm cho từng người (nếu có nhiều người)
    # Điểm chỉ tính trên tiền đã thu/cọc đã dùng, không tính phần còn nợ.
    split_paid_amount = paid_amount / Decimal(max(1, num_guests))

    # Update counts
    membership.total_stays = (membership.total_stays or 0) + 1

    # Calculate nights
    nights = 0
    if stay.check_in_at and stay.check_out_at:
        nights = (stay.check_out_at.date() - stay.check_in_at.date()).days
        if nights < 0:
            nights = 0

    membership.total_nights = (membership.total_nights or 0) + nights
    
    # Calculate room number from HotelStay.room relationship
    room_number = None
    if stay.room_id:
        room_obj = db.query(HotelRoom).filter(HotelRoom.id == stay.room_id).first()
        if room_obj:
            room_number = room_obj.room_number

    membership.total_spent = membership.total_spent + split_paid_amount
    membership.total_deposit = membership.total_deposit + min(paid_amount, stay.deposit or Decimal("0"))
    membership.total_debt = membership.total_debt + debt_amount

    # Calculate loyalty points dựa trên số tiền đã thu chia đều.
    # Ví dụ: 3 khách đã thanh toán 900.000 -> mỗi người được tính 300.000 để ra điểm
    # 300.000 / 1000 = 300 điểm base, sau đó nhân multiplier theo tier
    points_earned = calculate_loyalty_points(split_paid_amount, db)
    if points_earned > 0:
        tier_multiplier = get_tier_multiplier(membership.tier, db)
        points_earned = int(points_earned * tier_multiplier)
        membership.loyalty_points = (membership.loyalty_points or 0) + points_earned
        membership.points_balance = membership.loyalty_points - (membership.points_redeemed or 0)

        # Ghi log giao dịch điểm
        from ..db.models import GuestLoyaltyTransaction
        db.add(GuestLoyaltyTransaction(
            guest_id=guest_id,
            stay_id=stay.id,
            transaction_type="EARN",
            points=points_earned,
            reason=f"Tiền đã thanh toán phòng {room_number or ''} (chia {num_guests} người)" if num_guests > 1 else f"Tiền đã thanh toán phòng {room_number or ''}",
            created_by=user_id,
        ))

    # Recalculate tier dựa trên điểm thưởng
    new_tier = calculate_tier(membership.points_balance or Decimal("0"), db)
    if new_tier != membership.tier:
        membership.tier = new_tier
        membership.tier_updated_at = _now_vn()

        # Update guest tags
        if guest.tags is None:
            guest.tags = []
        if new_tier != MemberTier.BASIC and new_tier.value not in guest.tags:
            guest.tags = guest.tags + [new_tier.value]

    # Update last seen
    guest.last_seen_at = _now_vn()
    guest.total_stays = (guest.total_stays or 0) + 1

    db.flush()


def _get_tier_multiplier(tier: MemberTier) -> float:
    """Lấy multiplier cho điểm thưởng theo tier"""
    return get_tier_multiplier(tier)


def on_service_added(
    db: Session,
    guest_id: int,
    stay: HotelStay,
    tx: FolioTransaction,
) -> Optional[GuestServiceUsage]:
    """
    Hook được gọi khi có dịch vụ mới được thêm vào folio
    (minibar, laundry, restaurant, etc.)
    """
    if tx.is_voided:
        return None

    # Check if already created
    existing = db.query(GuestServiceUsage).filter(
        GuestServiceUsage.folio_transaction_id == tx.id
    ).first()
    if existing:
        return existing

    # Map transaction type to category
    # Chỉ xử lý các loại thực tế có trong hệ thống
    tx_type = tx.transaction_type.value if hasattr(tx.transaction_type, 'value') else str(tx.transaction_type)
    category_map = {
        "MINIBAR_CHARGE": "MINIBAR",
        "SERVICE_CHARGE": "SERVICE",
    }
    category = category_map.get(tx_type, "OTHER")

    room_number = None
    if stay.room:
        room_number = stay.room.room_number

    usage = create_service_usage(
        db=db,
        guest_id=guest_id,
        stay=stay,
        service_category=category,
        service_name=tx.description or category,
        amount=abs(tx.amount),
        quantity=tx.quantity or Decimal("1"),
        unit_price=tx.unit_price,
        room_number=room_number,
        folio_transaction_id=tx.id,
        created_by=tx.created_by,
        used_at=tx.created_at,
    )

    return usage


def on_payment_added(
    db: Session,
    guest_id: int,
    stay: HotelStay,
    payment: Payment,
    payment_type: str = "PAYMENT",
) -> Optional[GuestPaymentSummary]:
    """
    Hook được gọi khi có thanh toán mới
    """
    # Check if already created
    existing = db.query(GuestPaymentSummary).filter(
        GuestPaymentSummary.payment_id == payment.id
    ).first()
    if existing:
        return existing

    room_number = None
    if stay.room:
        room_number = stay.room.room_number

    summary = create_payment_summary(
        db=db,
        guest_id=guest_id,
        stay=stay,
        payment=payment,
        payment_type=payment_type,
        room_number=room_number,
    )

    return summary
