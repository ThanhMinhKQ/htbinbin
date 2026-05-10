# app/services/guest_crm_service.py
"""
Guest CRM Service - Business logic for Guest Relationship Management
Quản lý thông tin khách hàng, phân loại thành viên, theo dõi lịch sử
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from ..db.models import (
    Guest, GuestMembership, GuestStaySummary, GuestServiceUsage,
    GuestPaymentSummary, GuestActivity, HotelStay, HotelGuest,
    HotelRoom, HotelRoomType, Folio, FolioTransaction, Payment,
    Branch, MemberTier, HotelStayStatus, CrmMembershipSetting,
)
from ..core.utils import VN_TZ
from .folio_service import get_folio_financial_totals, rebalance_folio


def _now_vn() -> datetime:
    return datetime.now(VN_TZ)


# ====================================================================
# MEMBERSHIP TIER LOGIC
# ====================================================================

# Threshold definitions (POINTS)
# Tỷ lệ: 1 điểm / 1000 VND
MEMBERSHIP_THRESHOLDS = {
    MemberTier.BASIC: Decimal("0"),
    MemberTier.SILVER: Decimal("5000"),       # ~5 triệu VND
    MemberTier.GOLD: Decimal("15000"),        # ~15 triệu VND
    MemberTier.PLATINUM: Decimal("40000"),    # ~40 triệu VND
    MemberTier.VIP: Decimal("100000"),         # ~100 triệu VND
}

# Points per 1000 VND spent
POINTS_PER_1000_VND = 1  # 1 điểm / 1000đ


DEFAULT_MEMBERSHIP_TIER_SETTINGS = [
    {
        "tier": MemberTier.BASIC.value,
        "display_name": "Khách thường",
        "threshold": 0,
        "points_multiplier": 1,
        "discount_percent": 0,
        "benefits": {
            "early_checkin": False,
            "late_checkout": False,
            "priority_service": False,
            "free_upgrade": False,
            "dedicated_manager": False,
        },
    },
    {
        "tier": MemberTier.SILVER.value,
        "display_name": "Thành viên Bạc",
        "threshold": 5000,
        "points_multiplier": 1.5,
        "discount_percent": 5,
        "benefits": {
            "early_checkin": True,
            "late_checkout": False,
            "priority_service": False,
            "free_upgrade": False,
            "dedicated_manager": False,
        },
    },
    {
        "tier": MemberTier.GOLD.value,
        "display_name": "Thành viên Vàng",
        "threshold": 15000,
        "points_multiplier": 2,
        "discount_percent": 10,
        "benefits": {
            "early_checkin": True,
            "late_checkout": True,
            "priority_service": True,
            "free_upgrade": False,
            "dedicated_manager": False,
        },
    },
    {
        "tier": MemberTier.PLATINUM.value,
        "display_name": "Thành viên Bạch Kim",
        "threshold": 40000,
        "points_multiplier": 3,
        "discount_percent": 15,
        "benefits": {
            "early_checkin": True,
            "late_checkout": True,
            "priority_service": True,
            "free_upgrade": True,
            "dedicated_manager": False,
        },
    },
    {
        "tier": MemberTier.VIP.value,
        "display_name": "Khách VIP",
        "threshold": 100000,
        "points_multiplier": 5,
        "discount_percent": 20,
        "benefits": {
            "early_checkin": True,
            "late_checkout": True,
            "priority_service": True,
            "free_upgrade": True,
            "dedicated_manager": True,
        },
    },
]


def _default_membership_settings() -> Dict[str, Any]:
    return {
        "points_per_1000_vnd": POINTS_PER_1000_VND,
        "tiers": [dict(t, benefits=dict(t.get("benefits") or {})) for t in DEFAULT_MEMBERSHIP_TIER_SETTINGS],
    }


def _normalize_tier_settings(raw_tiers: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    defaults = {item["tier"]: item for item in DEFAULT_MEMBERSHIP_TIER_SETTINGS}
    incoming = {str(item.get("tier", "")).upper(): item for item in (raw_tiers or []) if item.get("tier")}
    normalized: List[Dict[str, Any]] = []

    for tier in MemberTier:
        base = defaults[tier.value]
        item = incoming.get(tier.value, {})
        benefits = dict(base.get("benefits") or {})
        benefits.update(item.get("benefits") or {})
        normalized.append({
            "tier": tier.value,
            "display_name": str(item.get("display_name") or base["display_name"]).strip(),
            "threshold": float(item.get("threshold", base["threshold"]) or 0),
            "points_multiplier": float(item.get("points_multiplier", base["points_multiplier"]) or 1),
            "discount_percent": float(item.get("discount_percent", base["discount_percent"]) or 0),
            "benefits": benefits,
        })

    normalized.sort(key=lambda t: list(MemberTier).index(MemberTier(t["tier"])))
    return normalized


def get_membership_settings(db: Optional[Session] = None) -> Dict[str, Any]:
    """Lấy cấu hình tích điểm/hạng CRM từ DB, fallback về mặc định."""
    settings = _default_membership_settings()
    if not db:
        return settings

    cached = db.info.get("crm_membership_settings") if hasattr(db, "info") else None
    if cached:
        return cached

    row = db.query(CrmMembershipSetting).filter(CrmMembershipSetting.id == 1).first()
    if not row:
        db.info["crm_membership_settings"] = settings
        return settings

    settings["points_per_1000_vnd"] = float(row.points_per_1000_vnd or POINTS_PER_1000_VND)
    settings["tiers"] = _normalize_tier_settings(row.tiers)
    settings["updated_at"] = row.updated_at.isoformat() if row.updated_at else None
    settings["updated_by"] = row.updated_by
    db.info["crm_membership_settings"] = settings
    return settings


def save_membership_settings(db: Session, payload: Dict[str, Any], user_id: Optional[int] = None) -> Dict[str, Any]:
    """Lưu cấu hình CRM membership từ giao diện quản trị."""
    points_per_1000 = Decimal(str(payload.get("points_per_1000_vnd", POINTS_PER_1000_VND)))
    if points_per_1000 <= 0:
        raise ValueError("Tỷ lệ điểm phải lớn hơn 0")

    tiers = _normalize_tier_settings(payload.get("tiers") or [])
    last_threshold = Decimal("-1")
    for item in tiers:
        threshold = Decimal(str(item.get("threshold", 0)))
        if threshold < 0:
            raise ValueError("Ngưỡng điểm không được âm")
        if threshold < last_threshold:
            raise ValueError("Ngưỡng điểm phải tăng dần theo thứ tự hạng")
        last_threshold = threshold
        if Decimal(str(item.get("points_multiplier", 1))) <= 0:
            raise ValueError("Hệ số điểm phải lớn hơn 0")
        discount = Decimal(str(item.get("discount_percent", 0)))
        if discount < 0 or discount > 100:
            raise ValueError("Giảm giá phải nằm trong khoảng 0-100%")

    row = db.query(CrmMembershipSetting).filter(CrmMembershipSetting.id == 1).first()
    if not row:
        row = CrmMembershipSetting(id=1)
        db.add(row)

    row.points_per_1000_vnd = points_per_1000
    row.tiers = tiers
    row.updated_by = user_id
    db.info.pop("crm_membership_settings", None)
    db.flush()
    return get_membership_settings(db)


def get_membership_thresholds(db: Optional[Session] = None) -> Dict[MemberTier, Decimal]:
    settings = get_membership_settings(db)
    return {
        MemberTier(item["tier"]): Decimal(str(item.get("threshold", 0)))
        for item in settings["tiers"]
    }


def calculate_tier(total_points: Decimal, db: Optional[Session] = None) -> MemberTier:
    """Tính tier dựa trên tổng điểm thưởng"""
    points = Decimal(str(total_points)) if not isinstance(total_points, Decimal) else total_points

    thresholds = get_membership_thresholds(db)
    if points >= thresholds[MemberTier.VIP]:
        return MemberTier.VIP
    elif points >= thresholds[MemberTier.PLATINUM]:
        return MemberTier.PLATINUM
    elif points >= thresholds[MemberTier.GOLD]:
        return MemberTier.GOLD
    elif points >= thresholds[MemberTier.SILVER]:
        return MemberTier.SILVER
    return MemberTier.BASIC


def calculate_loyalty_points(amount: Decimal, db: Optional[Session] = None) -> int:
    """Tính điểm thưởng từ số tiền"""
    settings = get_membership_settings(db)
    return int(float(amount) / 1000 * float(settings.get("points_per_1000_vnd") or POINTS_PER_1000_VND))


def calculate_folio_crm_amounts(db: Session, folio: Optional[Folio]) -> Dict[str, Decimal]:
    """Tính số tiền CRM theo tiền thực thu/cọc, không tính phần khách còn nợ."""
    zero = Decimal("0")
    if not folio:
        return {
            "total_charge": zero,
            "discount": zero,
            "final_amount": zero,
            "deposit_paid": zero,
            "payments_paid": zero,
            "paid_amount": zero,
            "debt_amount": zero,
        }

    rebalance_folio(db, folio)
    totals = get_folio_financial_totals(db, [folio.id]).get(folio.id, {})

    total_charge = totals.get("charge", zero) or zero
    discount = totals.get("discount", zero) or zero
    deposit_paid = totals.get("deposit_used", zero) or zero
    payments_paid = totals.get("payment", zero) or zero
    final_amount = max(zero, total_charge - discount)
    paid_amount = min(final_amount, deposit_paid + payments_paid)
    debt_amount = max(zero, final_amount - paid_amount)

    return {
        "total_charge": total_charge,
        "discount": discount,
        "final_amount": final_amount,
        "deposit_paid": deposit_paid,
        "payments_paid": payments_paid,
        "paid_amount": paid_amount,
        "debt_amount": debt_amount,
    }


def paid_amount_from_stay_summary(summary: GuestStaySummary) -> Decimal:
    """Số tiền thực thu ghi nhận cho một stay summary."""
    return max(
        Decimal("0"),
        (summary.final_amount or Decimal("0")) - (summary.debt_amount or Decimal("0")),
    )


def recalculate_membership_financials(db: Session, guest_id: int) -> GuestMembership:
    """Đồng bộ lại tổng tiền, điểm thưởng và hạng từ GuestStaySummary."""
    membership = get_or_create_membership(db, guest_id)
    summaries = db.query(GuestStaySummary).filter(
        GuestStaySummary.guest_id == guest_id
    ).all()

    paid_total = Decimal("0")
    total_points = Decimal("0")
    for summary in summaries:
        guest_count = db.query(func.count(HotelGuest.id)).filter(
            HotelGuest.stay_id == summary.stay_id,
            HotelGuest.guest_id.isnot(None),
        ).scalar() or 1
        split_amount = paid_amount_from_stay_summary(summary) / Decimal(max(1, guest_count))
        paid_total += split_amount
        total_points += Decimal(str(calculate_loyalty_points(split_amount, db)))

    tier_multiplier = Decimal(str(_get_tier_multiplier(membership.tier, db)))
    loyalty_points = int(total_points * tier_multiplier)

    membership.total_stays = len(summaries)
    membership.total_nights = sum(s.nights or 0 for s in summaries)
    membership.total_spent = paid_total
    membership.total_deposit = sum(s.deposit_paid or Decimal("0") for s in summaries)
    membership.total_debt = sum(s.debt_amount or Decimal("0") for s in summaries)
    membership.loyalty_points = loyalty_points
    membership.points_balance = loyalty_points - (membership.points_redeemed or 0)

    new_tier = calculate_tier(membership.points_balance or Decimal("0"), db)
    if new_tier != membership.tier:
        membership.tier = new_tier
        membership.tier_updated_at = _now_vn()

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if guest:
        guest.total_stays = membership.total_stays
        if summaries:
            guest.last_seen_at = max(s.check_out_at or s.check_in_at for s in summaries)
        if guest.tags is None:
            guest.tags = []
        if new_tier != MemberTier.BASIC and new_tier.value not in guest.tags:
            guest.tags = guest.tags + [new_tier.value]

    db.flush()
    return membership


def sync_guest_crm_after_debt_payment(
    db: Session,
    folio: Folio,
    payment: Optional[Payment] = None,
    tx: Optional[FolioTransaction] = None,
) -> int:
    """Cập nhật CRM sau khi thu nợ/thu thêm cho folio đã checkout."""
    if not folio or not folio.stay_id:
        return 0

    stay = db.query(HotelStay).filter(HotelStay.id == folio.stay_id).first()
    if not stay:
        return 0

    amounts = calculate_folio_crm_amounts(db, folio)
    new_debt = amounts["debt_amount"]
    debt_status = "settled" if new_debt <= Decimal("0") else "partial"
    checkout_summary = "normal" if new_debt <= Decimal("0") else "debt"

    hotel_guests = db.query(HotelGuest).filter(
        HotelGuest.stay_id == stay.id,
        HotelGuest.guest_id.isnot(None),
    ).all()

    room_number = None
    if stay.room_id:
        room = db.query(HotelRoom).filter(HotelRoom.id == stay.room_id).first()
        room_number = room.room_number if room else None

    updated = 0
    for hg in hotel_guests:
        guest_id = hg.guest_id
        summary = db.query(GuestStaySummary).filter(
            GuestStaySummary.guest_id == guest_id,
            GuestStaySummary.stay_id == stay.id,
        ).first()
        if summary:
            summary.total_charge = amounts["total_charge"]
            summary.discount = amounts["discount"]
            summary.deposit_paid = amounts["deposit_paid"]
            summary.final_amount = amounts["final_amount"]
            summary.debt_amount = new_debt
            summary.debt_status = debt_status
            summary.checkout_summary = checkout_summary
            summary.payment_methods = list(set((summary.payment_methods or []) + ([payment.method.value if hasattr(payment.method, "value") else str(payment.method)] if payment else [])))
            updated += 1

        if payment:
            existing = db.query(GuestPaymentSummary).filter(
                GuestPaymentSummary.guest_id == guest_id,
                GuestPaymentSummary.payment_id == payment.id,
            ).first()
            if not existing:
                db.add(GuestPaymentSummary(
                    guest_id=guest_id,
                    stay_id=stay.id,
                    folio_id=folio.id,
                    payment_id=payment.id,
                    branch_id=stay.branch_id,
                    amount=payment.amount,
                    payment_type="DEBT_PAYMENT",
                    payment_method=payment.method.value if hasattr(payment.method, "value") else str(payment.method),
                    transaction_code=payment.transaction_code,
                    room_number=room_number,
                    paid_at=payment.paid_at or _now_vn(),
                    is_voided=payment.is_refunded or False,
                    void_reason=payment.refund_reason,
                ))
        elif tx:
            tx_code = tx.shift_transaction.transaction_code if tx.shift_transaction else None
            existing = db.query(GuestPaymentSummary).filter(
                GuestPaymentSummary.guest_id == guest_id,
                GuestPaymentSummary.folio_id == folio.id,
                GuestPaymentSummary.transaction_code == tx_code,
                GuestPaymentSummary.amount == abs(tx.amount),
                GuestPaymentSummary.payment_type == "DEBT_PAYMENT",
            ).first()
            if not existing:
                db.add(GuestPaymentSummary(
                    guest_id=guest_id,
                    stay_id=stay.id,
                    folio_id=folio.id,
                    payment_id=None,
                    branch_id=stay.branch_id,
                    amount=abs(tx.amount),
                    payment_type="DEBT_PAYMENT",
                    payment_method=tx.shift_transaction.payment_method.value if tx.shift_transaction and hasattr(tx.shift_transaction.payment_method, "value") else "RECORD",
                    transaction_code=tx_code,
                    room_number=room_number,
                    paid_at=tx.created_at or _now_vn(),
                ))

        recalculate_membership_financials(db, guest_id)

    db.flush()
    return updated


def get_guest_risk_flags(db: Session, guest_id: int) -> Dict[str, Any]:
    """Trả về cảnh báo vận hành cho CRM/check-in."""
    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        return {
            "guest_id": guest_id,
            "is_blacklisted": False,
            "has_unpaid_debt": False,
            "unpaid_debt_amount": 0.0,
            "warnings": [],
        }

    debt_total = db.query(
        func.coalesce(func.sum(GuestStaySummary.debt_amount), 0)
    ).filter(
        GuestStaySummary.guest_id == guest_id,
        GuestStaySummary.debt_amount > 0,
        GuestStaySummary.debt_status.in_(["pending", "partial"]),
    ).scalar() or Decimal("0")

    warnings = []
    if guest.is_blacklisted:
        warnings.append({
            "type": "blacklist",
            "level": "danger",
            "message": "Khách đang nằm trong danh sách đen.",
        })
    if debt_total > 0:
        warnings.append({
            "type": "debt",
            "level": "warning",
            "amount": float(debt_total),
            "message": f"Khách còn nợ {float(debt_total):,.0f}đ chưa thanh toán.",
        })

    return {
        "guest_id": guest_id,
        "is_blacklisted": bool(guest.is_blacklisted),
        "has_unpaid_debt": debt_total > 0,
        "unpaid_debt_amount": float(debt_total),
        "warnings": warnings,
    }


def _get_tier_multiplier(tier: MemberTier, db: Optional[Session] = None) -> float:
    """Lấy multiplier cho điểm thưởng theo tier"""
    settings = get_membership_settings(db)
    tier_value = tier.value if hasattr(tier, "value") else str(tier)
    for item in settings["tiers"]:
        if item["tier"] == tier_value:
            return float(item.get("points_multiplier") or 1)
    return 1.0


def get_tier_multiplier(tier: MemberTier, db: Optional[Session] = None) -> float:
    return _get_tier_multiplier(tier, db)


def get_or_create_membership(db: Session, guest_id: int) -> GuestMembership:
    """Lấy hoặc tạo membership record"""
    membership = db.query(GuestMembership).filter(
        GuestMembership.guest_id == guest_id
    ).first()
    
    if not membership:
        membership = GuestMembership(guest_id=guest_id)
        db.add(membership)
        db.flush()
    
    return membership


def update_membership_stats(
    db: Session,
    guest_id: int,
    stay_summary: Optional[GuestStaySummary] = None,
    new_spent: Decimal = None,
    new_payment: Decimal = None,
    new_debt: Decimal = None,
    new_refund: Decimal = None,
    points_earned: int = None,
) -> GuestMembership:
    """
    Cập nhật thống kê membership sau mỗi lần checkout
    """
    membership = get_or_create_membership(db, guest_id)
    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    
    if not guest:
        return membership
    
    # Update counts from stay_summary if provided
    if stay_summary:
        membership.total_stays = (membership.total_stays or 0) + 1
        membership.total_nights = (membership.total_nights or 0) + (stay_summary.nights or 0)
        membership.total_spent = membership.total_spent + paid_amount_from_stay_summary(stay_summary)
        membership.total_deposit = membership.total_deposit + (stay_summary.deposit or Decimal("0"))
        membership.total_debt = membership.total_debt + (stay_summary.debt_amount or Decimal("0"))
        
        # Update favorite branch
        if not membership.favorite_branch_id:
            membership.favorite_branch_id = stay_summary.branch_id
        
        # Update favorite room type
        if stay_summary.room_type_name:
            membership.favorite_room_type = stay_summary.room_type_name
    
    # Manual updates
    if new_spent is not None:
        membership.total_spent = membership.total_spent + new_spent
    
    if new_payment is not None:
        membership.total_deposit = membership.total_deposit + new_payment
    
    if new_debt is not None:
        membership.total_debt = membership.total_debt + new_debt
    
    if new_refund is not None:
        membership.total_refund = membership.total_refund + new_refund
    
    # Update loyalty points
    if points_earned is not None:
        membership.loyalty_points = (membership.loyalty_points or 0) + points_earned
        membership.points_balance = membership.loyalty_points - (membership.points_redeemed or 0)
    
    # Recalculate tier dựa trên điểm thưởng
    new_tier = calculate_tier(membership.points_balance or Decimal("0"), db)
    if new_tier != membership.tier:
        membership.tier = new_tier
        membership.tier_updated_at = _now_vn()
    
    # Update guest's tags
    if guest.tags is None:
        guest.tags = []
    if new_tier != MemberTier.BASIC and new_tier.value not in guest.tags:
        guest.tags = guest.tags + [new_tier.value]
    
    db.flush()
    return membership


# ====================================================================
# STAY SUMMARY MANAGEMENT
# ====================================================================

def create_stay_summary(
    db: Session,
    guest_id: int,
    stay: HotelStay,
    folio: Optional[Folio] = None,
    guest_count: int = 1,
) -> GuestStaySummary:
    """
    Tạo GuestStaySummary khi checkout
    """
    # Get room info
    room = db.query(HotelRoom).filter(HotelRoom.id == stay.room_id).first()
    room_type = db.query(HotelRoomType).filter(HotelRoomType.id == room.room_type_id).first() if room else None
    
    # Calculate nights
    nights = 0
    if stay.check_in_at and stay.check_out_at:
        nights = (stay.check_out_at.date() - stay.check_in_at.date()).days
        if nights < 0:
            nights = 0
    
    # Get payment methods used
    payment_methods = []
    if folio:
        for p in folio.payments or []:
            if p.method and p.method.value not in payment_methods:
                payment_methods.append(p.method.value)
    
    # Calculate final amount
    total_charge = Decimal("0")
    discount = Decimal("0")
    deposit_paid = Decimal("0")
    final_amount = Decimal("0")
    debt_amount = Decimal("0")
    
    if folio:
        amounts = calculate_folio_crm_amounts(db, folio)
        total_charge = amounts["total_charge"]
        discount = amounts["discount"]
        deposit_paid = amounts["deposit_paid"]
        final_amount = amounts["final_amount"]
        debt_amount = amounts["debt_amount"]
    
    # Determine summary
    checkout_summary = "normal"
    debt_status = "none"
    if debt_amount > 0:
        checkout_summary = "debt"
        debt_status = "pending"
    elif folio and folio.debt_status not in (None, "none"):
        debt_status = folio.debt_status
    
    summary = GuestStaySummary(
        guest_id=guest_id,
        stay_id=stay.id,
        branch_id=stay.branch_id,
        room_number=room.room_number if room else None,
        room_type_name=room_type.name if room_type else None,
        floor=room.floor if room else None,
        check_in_at=stay.check_in_at,
        check_out_at=stay.check_out_at or _now_vn(),
        nights=nights,
        total_charge=total_charge,
        discount=discount,
        deposit=stay.deposit or Decimal("0"),
        deposit_type=stay.deposit_type,
        deposit_paid=deposit_paid,
        final_amount=final_amount,
        debt_amount=debt_amount,
        stay_type=stay.stay_type.value if stay.stay_type else None,
        pricing_mode=stay.pricing_mode_final or stay.pricing_mode_initial,
        guest_count=guest_count,
        status=stay.status.value if stay.status else None,
        checkout_summary=checkout_summary,
        payment_methods=payment_methods,
        vehicle=stay.vehicle,
        source="pms",
        debt_status=debt_status,
    )
    
    db.add(summary)
    db.flush()
    return summary


def get_guest_stay_summaries(
    db: Session,
    guest_id: int,
    limit: int = 50,
    offset: int = 0,
    branch_id: Optional[int] = None,
    status: Optional[str] = None,
) -> List[GuestStaySummary]:
    """Lấy danh sách lưu trú của khách"""
    q = db.query(GuestStaySummary).filter(GuestStaySummary.guest_id == guest_id)
    
    if branch_id:
        q = q.filter(GuestStaySummary.branch_id == branch_id)
    if status:
        q = q.filter(GuestStaySummary.status == status)
    
    return q.order_by(desc(GuestStaySummary.check_in_at)).offset(offset).limit(limit).all()


# ====================================================================
# SERVICE USAGE MANAGEMENT
# ====================================================================

def create_service_usage(
    db: Session,
    guest_id: int,
    stay: HotelStay,
    service_category: str,
    service_name: str,
    amount: Decimal,
    quantity: Decimal = Decimal("1"),
    unit_price: Decimal = None,
    room_number: str = None,
    product_id: int = None,
    folio_transaction_id: int = None,
    stock_movement_id: int = None,
    created_by: int = None,
    used_at: datetime = None,
) -> GuestServiceUsage:
    """Tạo record sử dụng dịch vụ"""
    usage = GuestServiceUsage(
        guest_id=guest_id,
        stay_id=stay.id,
        branch_id=stay.branch_id,
        service_category=service_category,
        service_name=service_name,
        product_id=product_id,
        quantity=quantity,
        unit_price=unit_price or amount / quantity if quantity > 0 else amount,
        total_amount=amount,
        room_number=room_number or (stay.room.room_number if stay.room else None),
        used_at=used_at or _now_vn(),
        folio_transaction_id=folio_transaction_id,
        stock_movement_id=stock_movement_id,
        created_by=created_by,
    )
    db.add(usage)
    db.flush()
    return usage


def create_service_usage_from_folio_transaction(
    db: Session,
    guest_id: int,
    stay: HotelStay,
    tx: FolioTransaction,
) -> Optional[GuestServiceUsage]:
    """Tạo GuestServiceUsage từ FolioTransaction"""
    if tx.is_voided:
        return None
    
    # Map transaction type to service category
    # Chỉ xử lý các loại thực tế có trong hệ thống
    tx_type = tx.transaction_type.value if hasattr(tx.transaction_type, 'value') else str(tx.transaction_type)
    
    category_map = {
        "MINIBAR_CHARGE": "MINIBAR",
        "SERVICE_CHARGE": "SERVICE",
    }
    
    category = category_map.get(tx_type, "OTHER")
    
    # Get room number
    room = db.query(HotelRoom).filter(HotelRoom.id == stay.room_id).first()
    room_number = room.room_number if room else None
    
    return create_service_usage(
        db=db,
        guest_id=guest_id,
        stay=stay,
        service_category=category,
        service_name=tx.description or category,
        amount=abs(tx.amount),
        quantity=tx.quantity or Decimal("1"),
        unit_price=tx.unit_price,
        room_number=room_number,
        product_id=tx.reference_id if tx.reference_type == "inventory" else None,
        folio_transaction_id=tx.id,
        created_by=tx.created_by,
        used_at=tx.created_at,
    )


def get_guest_service_usages(
    db: Session,
    guest_id: int,
    limit: int = 100,
    offset: int = 0,
    category: Optional[str] = None,
    date_from: datetime = None,
    date_to: datetime = None,
) -> List[GuestServiceUsage]:
    """Lấy danh sách dịch vụ đã sử dụng"""
    q = db.query(GuestServiceUsage).filter(GuestServiceUsage.guest_id == guest_id)
    
    if category:
        q = q.filter(GuestServiceUsage.service_category == category)
    if date_from:
        q = q.filter(GuestServiceUsage.used_at >= date_from)
    if date_to:
        q = q.filter(GuestServiceUsage.used_at <= date_to)
    
    return q.order_by(desc(GuestServiceUsage.used_at)).offset(offset).limit(limit).all()


def get_guest_service_stats(
    db: Session,
    guest_id: int,
) -> Dict[str, Any]:
    """Lấy thống kê dịch vụ của khách - dùng SQL aggregation"""
    # Get total count and total spent
    agg = db.query(
        func.count(GuestServiceUsage.id).label('total_count'),
        func.coalesce(func.sum(GuestServiceUsage.total_amount), 0).label('total_amount')
    ).filter(GuestServiceUsage.guest_id == guest_id).first()

    # Get by category
    cat_agg = db.query(
        GuestServiceUsage.service_category,
        func.count(GuestServiceUsage.id).label('count'),
        func.coalesce(func.sum(GuestServiceUsage.total_amount), 0).label('amount')
    ).filter(GuestServiceUsage.guest_id == guest_id).group_by(GuestServiceUsage.service_category).all()

    by_category = {}
    for cat in cat_agg:
        by_category[cat.service_category] = {
            "count": cat.count,
            "amount": float(cat.amount)
        }

    return {
        "total_services": agg.total_count or 0,
        "total_spent": float(agg.total_amount) if agg.total_amount else 0,
        "by_category": by_category,
    }


# ====================================================================
# PAYMENT SUMMARY MANAGEMENT
# ====================================================================

def create_payment_summary(
    db: Session,
    guest_id: int,
    stay: HotelStay,
    payment: Payment,
    payment_type: str = "PAYMENT",
    room_number: str = None,
) -> GuestPaymentSummary:
    """Tạo record thanh toán"""
    summary = GuestPaymentSummary(
        guest_id=guest_id,
        stay_id=stay.id,
        folio_id=payment.folio_id,
        payment_id=payment.id,
        branch_id=stay.branch_id,
        amount=payment.amount,
        payment_type=payment_type,
        payment_method=payment.method.value if hasattr(payment.method, 'value') else str(payment.method),
        transaction_code=payment.transaction_code,
        room_number=room_number or (stay.room.room_number if stay.room else None),
        paid_at=payment.paid_at or _now_vn(),
        is_voided=payment.is_refunded or False,
        void_reason=payment.refund_reason,
    )
    db.add(summary)
    db.flush()
    return summary


def get_guest_payment_history(
    db: Session,
    guest_id: int,
    limit: int = 100,
    offset: int = 0,
    method: Optional[str] = None,
    payment_type: Optional[str] = None,
) -> List[GuestPaymentSummary]:
    """Lấy lịch sử thanh toán"""
    q = db.query(GuestPaymentSummary).filter(GuestPaymentSummary.guest_id == guest_id)
    
    if method:
        q = q.filter(GuestPaymentSummary.payment_method == method)
    if payment_type:
        q = q.filter(GuestPaymentSummary.payment_type == payment_type)
    
    return q.order_by(desc(GuestPaymentSummary.paid_at)).offset(offset).limit(limit).all()


def get_guest_payment_stats(
    db: Session,
    guest_id: int,
) -> Dict[str, Any]:
    """Lấy thống kê thanh toán"""
    payments = db.query(GuestPaymentSummary).filter(
        GuestPaymentSummary.guest_id == guest_id,
        GuestPaymentSummary.is_voided == False,
    ).all()
    
    total_deposit = Decimal("0")
    total_payment = Decimal("0")
    total_refund = Decimal("0")
    by_method = {}
    
    for p in payments:
        if p.payment_type == "DEPOSIT":
            total_deposit += p.amount
        elif p.payment_type in ("PAYMENT", "DEBT_PAYMENT"):
            total_payment += p.amount
        elif p.payment_type == "REFUND":
            total_refund += p.amount
        
        method = p.payment_method
        if method not in by_method:
            by_method[method] = {"count": 0, "amount": Decimal("0")}
        by_method[method]["count"] += 1
        by_method[method]["amount"] += p.amount
    
    return {
        "total_transactions": len(payments),
        "total_deposit": float(total_deposit),
        "total_payment": float(total_payment),
        "total_refund": float(total_refund),
        "net_spent": float(total_payment - total_refund),
        "by_method": {
            k: {"count": v["count"], "amount": float(v["amount"])}
            for k, v in by_method.items()
        },
    }


# ====================================================================
# GUEST COMPREHENSIVE PROFILE
# ====================================================================

def get_guest_comprehensive_profile(
    db: Session,
    guest_id: int,
    include_activities: bool = True,
    include_stays: bool = True,
    include_services: bool = True,
    include_payments: bool = True,
) -> Dict[str, Any]:
    """
    Lấy toàn bộ thông tin khách hàng
    """
    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        return None
    
    # Get membership
    membership = db.query(GuestMembership).filter(
        GuestMembership.guest_id == guest_id
    ).first()
    
    # Get recent stays
    stay_summaries = []
    if include_stays:
        stay_summaries = get_guest_stay_summaries(db, guest_id, limit=10)
    
    # Get service stats
    service_stats = {}
    if include_services:
        service_stats = get_guest_service_stats(db, guest_id)
    
    # Get payment stats
    payment_stats = {}
    if include_payments:
        payment_stats = get_guest_payment_stats(db, guest_id)
    
    # Get recent activities
    recent_activities = []
    if include_activities:
        activities = db.query(GuestActivity).filter(
            GuestActivity.guest_id == guest_id
        ).order_by(desc(GuestActivity.created_at)).limit(20).all()
        recent_activities = [
            {
                "id": a.id,
                "activity_type": a.activity_type,
                "activity_group": a.activity_group,
                "title": a.title,
                "description": a.description,
                "amount": float(a.amount) if a.amount else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in activities
        ]
    
    # Build tier info
    tier_info = {
        "tier": membership.tier.value if membership else MemberTier.BASIC.value,
        "tier_display": _tier_display_name(membership.tier if membership else MemberTier.BASIC, db),
        "total_spent": float(membership.total_spent) if membership else 0,
        "total_stays": membership.total_stays if membership else 0,
        "total_nights": membership.total_nights if membership else 0,
        "loyalty_points": membership.points_balance if membership else 0,
        "favorite_branch": None,
        "favorite_room_type": membership.favorite_room_type if membership else None,
        "preferred_payment": membership.preferred_payment_method if membership else None,
    }
    
    if membership and membership.favorite_branch_id:
        branch = db.query(Branch).filter(Branch.id == membership.favorite_branch_id).first()
        tier_info["favorite_branch"] = branch.name if branch else None
        
    # Recalculate stats from GuestStaySummary as source of truth
    stats_q = db.query(
        func.count(GuestStaySummary.id).label('total_stays'),
        func.coalesce(func.sum(GuestStaySummary.nights), 0).label('total_nights'),
        func.coalesce(func.sum(
            func.coalesce(GuestStaySummary.final_amount, 0) - func.coalesce(GuestStaySummary.debt_amount, 0)
        ), 0).label('total_spent')
    ).filter(GuestStaySummary.guest_id == guest_id).first()
    
    tier_info["total_stays"] = stats_q.total_stays or 0
    tier_info["total_nights"] = stats_q.total_nights or 0
    tier_info["total_spent"] = float(stats_q.total_spent or 0)
    
    # Recalculate tier dựa trên điểm thưởng
    actual_tier = calculate_tier(membership.points_balance if membership else Decimal("0"), db)
    tier_info["tier"] = actual_tier.value
    tier_info["tier_display"] = _tier_display_name(actual_tier, db)

    return {
        "guest": {
            "id": guest.id,
            "full_name": guest.full_name,
            "phone": guest.phone,
            "email": guest.email,
            "cccd": guest.cccd,
            "date_of_birth": guest.date_of_birth.isoformat() if guest.date_of_birth else None,
            "gender": guest.gender,
            "nationality": guest.nationality,
            "default_address": guest.default_address,
            "first_seen_at": guest.first_seen_at.isoformat() if guest.first_seen_at else None,
            "last_seen_at": guest.last_seen_at.isoformat() if guest.last_seen_at else None,
            "is_blacklisted": guest.is_blacklisted,
            "tags": guest.tags or [],
        },
        "membership": tier_info,
        "stay_summaries": [
            {
                "id": s.id,
                "stay_id": s.stay_id,
                "room_number": s.room_number,
                "room_type_name": s.room_type_name,
                "check_in_at": s.check_in_at.isoformat() if s.check_in_at else None,
                "check_out_at": s.check_out_at.isoformat() if s.check_out_at else None,
                "nights": s.nights,
                "total_charge": float(s.total_charge) if s.total_charge else 0,
                "discount": float(s.discount) if s.discount else 0,
                "final_amount": float(s.final_amount) if s.final_amount else 0,
                "debt_amount": float(s.debt_amount) if s.debt_amount else 0,
                "payment_methods": s.payment_methods or [],
                "checkout_summary": s.checkout_summary,
                "branch_id": s.branch_id,
            }
            for s in stay_summaries
        ],
        "service_stats": service_stats,
        "payment_stats": payment_stats,
        "recent_activities": recent_activities,
    }


def _tier_display_name(tier: MemberTier, db: Optional[Session] = None) -> str:
    """Lấy tên hiển thị của tier"""
    settings = get_membership_settings(db)
    tier_value = tier.value if hasattr(tier, "value") else str(tier)
    for item in settings["tiers"]:
        if item["tier"] == tier_value:
            return item.get("display_name") or tier_value
    return tier_value


def get_tier_benefits(tier: MemberTier, db: Optional[Session] = None) -> Dict[str, Any]:
    """Lấy quyền lợi của từng bậc"""
    settings = get_membership_settings(db)
    tier_value = tier.value if hasattr(tier, "value") else str(tier)
    for item in settings["tiers"]:
        if item["tier"] == tier_value:
            return {
                "name": item.get("display_name") or tier_value,
                "points_multiplier": item.get("points_multiplier") or 1,
                "discount_percent": item.get("discount_percent") or 0,
                **(item.get("benefits") or {}),
            }
    return get_tier_benefits(MemberTier.BASIC, db) if tier_value != MemberTier.BASIC.value else {}


# ====================================================================
# BATCH PROCESSING (for data migration)
# ====================================================================

def batch_create_stay_summaries(db: Session, guest_id: int = None, batch_size: int = 100) -> Dict[str, int]:
    """
    Tạo stay summaries hàng loạt cho tất cả guests hoặc guest cụ thể
    Dùng cho migration data
    """
    q = db.query(HotelStay).filter(HotelStay.status != HotelStayStatus.ACTIVE)
    
    if guest_id:
        # Get all stay_ids for this guest
        hotel_guest_subq = db.query(HotelGuest.stay_id).filter(
            HotelGuest.guest_id == guest_id
        ).subquery()
        q = q.filter(HotelStay.id.in_(hotel_guest_subq))
    
    # Process in batches
    total_created = 0
    processed_stays = set()
    
    offset = 0
    while True:
        stays = q.offset(offset).limit(batch_size).all()
        if not stays:
            break
        
        for stay in stays:
            # Get all guests for this stay
            hotel_guests = db.query(HotelGuest).filter(
                HotelGuest.stay_id == stay.id,
                HotelGuest.guest_id.isnot(None),
            ).all()
            
            if not hotel_guests:
                continue
            
            folio = db.query(Folio).filter(Folio.stay_id == stay.id).first()
            
            for hg in hotel_guests:
                # Check if already exists
                existing = db.query(GuestStaySummary).filter(
                    GuestStaySummary.guest_id == hg.guest_id,
                    GuestStaySummary.stay_id == stay.id,
                ).first()
                
                if existing:
                    continue
                
                try:
                    # Get room info via query (relationship may not be loaded)
                    room = db.query(HotelRoom).filter(HotelRoom.id == stay.room_id).first()
                    room_type = db.query(HotelRoomType).filter(HotelRoomType.id == room.room_type_id).first() if room else None

                    summary = create_stay_summary(
                        db=db,
                        guest_id=hg.guest_id,
                        stay=stay,
                        folio=folio,
                        guest_count=len(hotel_guests),
                    )

                    # Create GuestStayMapping
                    from ..db.models import GuestStayMapping
                    existing_mapping = db.query(GuestStayMapping).filter(
                        GuestStayMapping.guest_id == hg.guest_id,
                        GuestStayMapping.stay_id == stay.id,
                    ).first()
                    if not existing_mapping:
                        mapping = GuestStayMapping(
                            guest_id=hg.guest_id,
                            stay_id=stay.id,
                            branch_id=stay.branch_id,
                            room_number=room.room_number if room else None,
                            check_in_at=stay.check_in_at,
                            check_out_at=stay.check_out_at,
                            is_primary=getattr(hg, 'is_primary', False),
                        )
                        db.add(mapping)

                    from .guest_crm_integration import _create_service_usages, _create_payment_summaries
                    _create_service_usages(db=db, guest_id=hg.guest_id, stay=stay, folio=folio)
                    _create_payment_summaries(db=db, guest_id=hg.guest_id, stay=stay, folio=folio)

                    # Create activities for timeline
                    if stay.check_in_at:
                        db.add(GuestActivity(
                            guest_id=hg.guest_id,
                            activity_type="CHECK_IN",
                            activity_group="stay",
                            title=f"Nhận phòng {room.room_number if room else ''}",
                            stay_id=stay.id,
                            branch_id=stay.branch_id,
                            created_at=stay.check_in_at
                        ))
                    if stay.check_out_at:
                        db.add(GuestActivity(
                            guest_id=hg.guest_id,
                            activity_type="CHECK_OUT",
                            activity_group="stay",
                            title=f"Trả phòng {room.room_number if room else ''}",
                            stay_id=stay.id,
                            branch_id=stay.branch_id,
                            created_at=stay.check_out_at
                        ))
                    
                    total_created += 1
                except Exception as e:
                    import logging
                    logging.error(f"Error batch creating summary for guest {hg.guest_id}: {e}", exc_info=True)

            processed_stays.add(stay.id)
        
        offset += batch_size
    
    return {
        "total_created": total_created,
        "stays_processed": len(processed_stays),
    }


def recalculate_all_memberships(db: Session) -> Dict[str, int]:
    """Recalculate tất cả memberships dựa trên stay summaries"""
    memberships_updated = 0
    
    # Get all guests who have a membership or have stay summaries
    guests = db.query(Guest).all()
    
    for guest in guests:
        membership = get_or_create_membership(db, guest.id)
        
        # Calculate from stay summaries
        summaries = db.query(GuestStaySummary).filter(
            GuestStaySummary.guest_id == guest.id
        ).all()
        
        old_tier = membership.tier
        
        membership.total_stays = len(summaries)
        membership.total_nights = sum(s.nights or 0 for s in summaries)
        
        paid_total = Decimal("0")
        for s in summaries:
            hotel_guest_count = db.query(func.count(HotelGuest.id)).filter(
                HotelGuest.stay_id == s.stay_id,
                HotelGuest.guest_id.isnot(None),
            ).scalar() or 1
            paid_total += paid_amount_from_stay_summary(s) / Decimal(max(1, hotel_guest_count))
        membership.total_spent = paid_total
        membership.total_deposit = sum(s.deposit_paid or Decimal("0") for s in summaries)
        membership.total_debt = sum(s.debt_amount or Decimal("0") for s in summaries)
        
        # Calculate points dựa trên stay summaries
        # Nếu guest_count > 1, điểm được tính chia đều cho mỗi người
        # Ví dụ: 3 khách ở 900.000 -> mỗi người tính 300.000 để ra điểm
        # 300.000 / 1000 = 300 điểm
        # Sau đó nhân multiplier theo tier tại thời điểm checkout (dùng tier hiện tại vì đã tính lại tier)
        total_points = Decimal("0")
        for s in summaries:
            # Lấy guest_count từ HotelGuest (fix guest_count bị null)
            hotel_guest_count = db.query(func.count(HotelGuest.id)).filter(
                HotelGuest.stay_id == s.stay_id,
                HotelGuest.guest_id.isnot(None),
            ).scalar() or 1
            
            guest_count = max(1, hotel_guest_count)
            paid_amount = paid_amount_from_stay_summary(s)
            split_amount = paid_amount / Decimal(guest_count)
            points_for_stay = Decimal(str(calculate_loyalty_points(split_amount, db)))
            total_points += points_for_stay
        
        # Áp dụng tier multiplier (dùng tier hiện tại sau khi đã tính lại)
        tier_multiplier = Decimal(str(_get_tier_multiplier(membership.tier, db)))
        total_points = int(total_points * tier_multiplier)
        membership.loyalty_points = total_points
        membership.points_balance = membership.loyalty_points - (membership.points_redeemed or 0)
        new_tier = calculate_tier(membership.points_balance or Decimal("0"), db)
        if new_tier != membership.tier:
            membership.tier = new_tier
            membership.tier_updated_at = _now_vn()
        
        # Update Guest table
        guest = db.query(Guest).filter(Guest.id == membership.guest_id).first()
        if guest:
            guest.total_stays = membership.total_stays
            if summaries:
                guest.last_seen_at = max(s.check_out_at or s.check_in_at for s in summaries)
            
            if guest.tags is None:
                guest.tags = []
            if new_tier != MemberTier.BASIC and new_tier.value not in guest.tags:
                guest.tags = guest.tags + [new_tier.value]
        
        # Update favorite branch (most frequent)
        from collections import Counter
        branch_counts = Counter(s.branch_id for s in summaries if s.branch_id)
        if branch_counts:
            membership.favorite_branch_id = branch_counts.most_common(1)[0][0]
        
        # Update favorite room type (most frequent)
        room_type_counts = Counter(s.room_type_name for s in summaries if s.room_type_name)
        if room_type_counts:
            membership.favorite_room_type = room_type_counts.most_common(1)[0][0]

        # Update preferred payment method
        from ..db.models import GuestPaymentSummary
        payment_methods = db.query(GuestPaymentSummary.payment_method).filter(
            GuestPaymentSummary.guest_id == guest.id
        ).all()
        if payment_methods:
            pm_counts = Counter(pm[0] for pm in payment_methods if pm[0])
            if pm_counts:
                membership.preferred_payment_method = pm_counts.most_common(1)[0][0]
        
        memberships_updated += 1
    
    db.flush()
    return {"memberships_updated": memberships_updated}
