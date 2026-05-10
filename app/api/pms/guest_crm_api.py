# app/api/pms/guest_crm_api.py
"""
Guest CRM API - Guest Relationship Management Endpoints
API quản lý thông tin khách hàng, phân loại thành viên, xem lịch sử
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_, and_

from ...db.models import (
    Guest, GuestMembership, GuestStaySummary, GuestServiceUsage,
    GuestPaymentSummary, GuestActivity, HotelStay, HotelGuest,
    HotelRoom, HotelRoomType, Folio, FolioTransaction, Payment, Branch, MemberTier,
    GuestPreference, User,
    HotelStayStatus,
)
from ...db.session import get_db
from ...services.guest_crm_service import (
    get_guest_comprehensive_profile,
    get_guest_stay_summaries,
    get_guest_service_usages,
    get_guest_service_stats,
    get_guest_payment_history,
    get_guest_payment_stats,
    update_membership_stats,
    create_stay_summary,
    create_service_usage_from_folio_transaction,
    create_payment_summary,
    calculate_tier,
    get_tier_benefits,
    get_membership_settings,
    save_membership_settings,
    get_membership_thresholds,
    get_guest_risk_flags,
)
from .pms_helpers import _require_login, _active_branch, _now_vn, _is_manager
from .guest_activity import ActivityType, ActivityGroup, ActorType, Source, log_activity, get_guest_timeline, get_guest_stats
from ...core.utils import VN_TZ

router = APIRouter()


class GuestBlacklistPayload(BaseModel):
    is_blacklisted: bool
    reason: Optional[str] = None


class CrmMembershipTierPayload(BaseModel):
    tier: str
    display_name: str
    threshold: float = 0
    points_multiplier: float = 1
    discount_percent: float = 0
    benefits: dict = Field(default_factory=dict)


class CrmMembershipSettingsPayload(BaseModel):
    points_per_1000_vnd: float
    tiers: List[CrmMembershipTierPayload]


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _duration_payload(check_in_at, check_out_at):
    if not check_in_at:
        return {
            "duration_minutes": 0,
            "duration_hours": 0,
            "duration_display": "-",
        }

    end_at = check_out_at or _now_vn()
    minutes = max(0, int((end_at - check_in_at).total_seconds() // 60))
    hours = round(minutes / 60, 1)
    days = minutes // 1440
    rem_hours = (minutes % 1440) // 60
    rem_minutes = minutes % 60

    if days > 0:
        parts = [f"{days} ngày"]
        if rem_hours:
            parts.append(f"{rem_hours} giờ")
        if rem_minutes and days == 0:
            parts.append(f"{rem_minutes} phút")
    elif rem_hours > 0:
        parts = [f"{rem_hours} giờ"]
        if rem_minutes:
            parts.append(f"{rem_minutes} phút")
    else:
        parts = [f"{rem_minutes} phút"]

    return {
        "duration_minutes": minutes,
        "duration_hours": hours,
        "duration_display": " ".join(parts),
    }


def _activity_payload(a: GuestActivity) -> dict:
    return {
        "id": a.id,
        "type": "activity",
        "activity_type": a.activity_type,
        "activity_group": a.activity_group,
        "title": a.title,
        "description": a.description,
        "stay_id": a.stay_id,
        "branch_id": a.branch_id,
        "amount": float(a.amount) if a.amount else None,
        "currency": a.currency,
        "actor_type": a.actor_type,
        "source": a.source,
        "extra_data": a.extra_data,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _payment_transaction_code(db: Session, payment: GuestPaymentSummary) -> Optional[str]:
    if payment.transaction_code:
        return payment.transaction_code
    if payment.payment_id:
        p = db.query(Payment).filter(Payment.id == payment.payment_id).first()
        if p and p.transaction_code:
            return p.transaction_code
    if payment.folio_id:
        tx = db.query(FolioTransaction).filter(
            FolioTransaction.folio_id == payment.folio_id,
            FolioTransaction.reference_type.in_(["payment", "payment_refund"]),
            FolioTransaction.reference_id == payment.payment_id,
        ).order_by(FolioTransaction.created_at.desc()).first() if payment.payment_id else None
        if tx and tx.shift_transaction:
            return tx.shift_transaction.transaction_code
    return None


def _stay_transfer_settlement_payload(db: Session, stay_id: int) -> Optional[dict]:
    tx = db.query(FolioTransaction).filter(
        FolioTransaction.stay_id == stay_id,
        FolioTransaction.reference_type == "room_bill_transfer",
        FolioTransaction.amount < 0,
        FolioTransaction.is_voided == False,
    ).order_by(FolioTransaction.created_at.desc()).first()
    if not tx:
        return None

    target_stay = db.query(HotelStay).filter(HotelStay.id == tx.reference_id).first() if tx.reference_id else None
    target_room = None
    if target_stay and target_stay.room_id:
        target_room = db.query(HotelRoom).filter(HotelRoom.id == target_stay.room_id).first()
    actor = db.query(User).filter(User.id == tx.created_by).first() if tx.created_by else None

    return {
        "type": "room_bill_transfer",
        "amount": float(abs(tx.amount or Decimal("0"))),
        "source_stay_id": stay_id,
        "target_stay_id": target_stay.id if target_stay else tx.reference_id,
        "target_room_number": target_room.room_number if target_room else None,
        "settled_by_user_id": actor.id if actor else tx.created_by,
        "settled_by_name": actor.name if actor else None,
        "settled_at": tx.created_at.isoformat() if tx.created_at else None,
        "description": tx.description,
    }


def _active_branch_id(request: Request, db: Session) -> Optional[int]:
    branch_code = _active_branch(request)
    if not branch_code:
        return None
    branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()
    return branch.id if branch else None


# ====================================================================
# GUEST SEARCH & LIST
# ====================================================================

@router.get("/api/pms/crm/guests/search", tags=["PMS - CRM"])
def api_search_guests(
    request: Request,
    q: Optional[str] = Query(default=None, description="Tìm theo tên, CCCD, SĐT, email"),
    cccd: Optional[str] = Query(default=None),
    phone: Optional[str] = Query(default=None),
    branch_id: Optional[int] = Query(default=None),
    tier: Optional[str] = Query(default=None),
    blacklist: Optional[bool] = Query(default=None),
    debt: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Tìm kiếm khách hàng
    """
    user = _require_login(request)

    q_clean = q.strip().lower() if q else ""

    # Base query
    query = db.query(Guest)

    # Search conditions
    if cccd:
        query = query.filter(Guest.cccd.ilike(f"%{cccd}%"))
    elif q_clean:
        # Search by name, cccd, phone, email
        query = query.filter(
            or_(
                func.lower(Guest.full_name).contains(q_clean),
                Guest.cccd.ilike(f"%{q_clean}%"),
                Guest.phone.ilike(f"%{q_clean}%"),
                Guest.email.ilike(f"%{q_clean}%"),
            )
        )

    if blacklist is not None:
        query = query.filter(Guest.is_blacklisted == blacklist)

    if debt in ("unpaid", "paid"):
        debt_guest_subq = db.query(GuestStaySummary.guest_id).filter(
            GuestStaySummary.debt_amount > 0,
            GuestStaySummary.debt_status.in_(["pending", "partial"]),
        ).subquery()
        if debt == "unpaid":
            query = query.filter(Guest.id.in_(debt_guest_subq))
        else:
            query = query.filter(~Guest.id.in_(debt_guest_subq))

    if tier:
        # Filter by membership tier
        subq = db.query(GuestMembership.guest_id).filter(
            GuestMembership.tier == tier
        ).subquery()
        query = query.filter(Guest.id.in_(subq))

    # Exclude deleted
    query = query.filter(Guest.deleted_at.is_(None))

    # Order by last seen
    query = query.order_by(Guest.last_seen_at.desc().nullslast())

    # Count total
    total = query.count()

    # Paginate
    guests = query.offset((page - 1) * page_size).limit(page_size).all()

    if not guests:
        return JSONResponse({
            "guests": [],
            "items": [],  # Backward compatibility
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total else 0,
        })

    # Batch load memberships
    guest_ids = [g.id for g in guests]
    memberships = db.query(GuestMembership).filter(
        GuestMembership.guest_id.in_(guest_ids)
    ).all()
    membership_map = {m.guest_id: m for m in memberships}

    # Batch load most recent HotelGuest address data for each guest
    # Use subquery to get the most recent HotelGuest per guest_id
    recent_hotel_guest_subq = (
        db.query(
            HotelGuest.guest_id,
            func.max(HotelGuest.id).label('max_hg_id')
        )
        .filter(
            HotelGuest.guest_id.in_(guest_ids),
            HotelGuest.guest_id.isnot(None)
        )
        .group_by(HotelGuest.guest_id)
        .subquery()
    )

    recent_hotel_guests = (
        db.query(HotelGuest)
        .join(
            recent_hotel_guest_subq,
            and_(
                HotelGuest.guest_id == recent_hotel_guest_subq.c.guest_id,
                HotelGuest.id == recent_hotel_guest_subq.c.max_hg_id
            )
        )
        .all()
    )
    hotel_guest_map = {hg.guest_id: hg for hg in recent_hotel_guests}

    # Batch load stay counts directly from GuestStaySummary
    stay_counts = db.query(
        GuestStaySummary.guest_id,
        func.count(GuestStaySummary.id).label('stay_count')
    ).filter(
        GuestStaySummary.guest_id.in_(guest_ids)
    ).group_by(GuestStaySummary.guest_id).all()
    stay_count_map = {row[0]: row[1] for row in stay_counts}

    debt_rows = db.query(
        GuestStaySummary.guest_id,
        func.coalesce(func.sum(GuestStaySummary.debt_amount), 0).label("debt_total"),
    ).filter(
        GuestStaySummary.guest_id.in_(guest_ids),
        GuestStaySummary.debt_amount > 0,
        GuestStaySummary.debt_status.in_(["pending", "partial"]),
    ).group_by(GuestStaySummary.guest_id).all()
    debt_map = {row.guest_id: row.debt_total or Decimal("0") for row in debt_rows}

    blacklist_activity_rows = []
    if blacklist:
        blacklist_activity_rows = db.query(
            GuestActivity,
            User.name.label("actor_name"),
            Branch.name.label("branch_name"),
        ).outerjoin(
            User, User.id == GuestActivity.actor_id
        ).outerjoin(
            Branch, Branch.id == GuestActivity.branch_id
        ).filter(
            GuestActivity.guest_id.in_(guest_ids),
            GuestActivity.activity_type == "BLACKLISTED",
        ).order_by(GuestActivity.created_at.desc()).all()

    blacklist_info_map = {}
    for activity, actor_name, branch_name in blacklist_activity_rows:
        if activity.guest_id in blacklist_info_map:
            continue
        blacklist_info_map[activity.guest_id] = {
            "reason": activity.description,
            "actor_name": actor_name,
            "branch_name": branch_name,
            "created_at": activity.created_at.isoformat() if activity.created_at else None,
        }

    # Batch load last stays (using subquery for latest stay per guest)
    last_stay_subq = (
        db.query(
            HotelGuest.guest_id,
            func.max(HotelStay.check_in_at).label('max_checkin')
        )
        .join(HotelStay, HotelStay.id == HotelGuest.stay_id)
        .filter(HotelGuest.guest_id.in_(guest_ids))
        .filter(HotelStay.status != HotelStayStatus.ACTIVE)
        .group_by(HotelGuest.guest_id)
        .subquery()
    )

    last_stays = (
        db.query(HotelStay, HotelGuest.guest_id.label('stay_guest_id'))
        .join(HotelGuest, HotelGuest.stay_id == HotelStay.id)
        .join(
            last_stay_subq,
            and_(
                HotelGuest.guest_id == last_stay_subq.c.guest_id,
                HotelStay.check_in_at == last_stay_subq.c.max_checkin
            )
        )
        .all()
    )
    stay_map = {row[1]: row[0] for row in last_stays}
    stay_ids = [row[0].id for row in last_stays]

    # Batch load rooms and branches
    room_map = {}
    branch_map = {}
    if stay_ids:
        rooms = db.query(HotelRoom).filter(HotelRoom.id.in_([row[0].room_id for row in last_stays if row[0].room_id])).all()
        room_map = {r.id: r.room_number for r in rooms}
        branch_ids = list(set(row[0].branch_id for row in last_stays if row[0].branch_id))
        if branch_ids:
            branches = db.query(Branch).filter(Branch.id.in_(branch_ids)).all()
            branch_map = {b.id: b.name for b in branches}

    # Build response
    results = []
    for g in guests:
        membership = membership_map.get(g.id)
        last_stay_data = stay_map.get(g.id)
        hg = hotel_guest_map.get(g.id)  # Most recent HotelGuest record

        last_room = None
        last_branch = None
        if last_stay_data:
            last_room = room_map.get(last_stay_data.room_id)
            last_branch = branch_map.get(last_stay_data.branch_id)

        results.append({
            "id": g.id,
            "full_name": g.full_name,
            "phone": g.phone,
            "email": g.email,
            "cccd": g.cccd,
            "date_of_birth": g.date_of_birth.isoformat() if g.date_of_birth else None,
            "birth_date": g.date_of_birth.isoformat() if g.date_of_birth else None,  # Alias for checkin form
            "gender": g.gender,
            "nationality": g.nationality,
            "id_expire": g.id_expire.isoformat() if g.id_expire else None,
            "id_type": getattr(hg, 'id_type', None) if hg else None,  # From most recent HotelGuest
            "default_address": g.default_address,
            # Address fields from most recent HotelGuest (for checkin form)
            "address": getattr(hg, 'address', None) if hg else None,
            "city": getattr(hg, 'city', None) if hg else None,
            "district": getattr(hg, 'district', None) if hg else None,
            "ward": getattr(hg, 'ward', None) if hg else None,
            "address_type": getattr(hg, 'address_type', None) if hg else None,
            "old_city": getattr(hg, 'old_city', None) if hg else None,
            "old_district": getattr(hg, 'old_district', None) if hg else None,
            "old_ward": getattr(hg, 'old_ward', None) if hg else None,
            "notes": getattr(hg, 'notes', None) if hg else None,
            "is_blacklisted": g.is_blacklisted,
            "blacklist_info": blacklist_info_map.get(g.id),
            "has_unpaid_debt": debt_map.get(g.id, Decimal("0")) > 0,
            "unpaid_debt_amount": float(debt_map.get(g.id, Decimal("0"))),
            "risk_flags": {
                "is_blacklisted": bool(g.is_blacklisted),
                "has_unpaid_debt": debt_map.get(g.id, Decimal("0")) > 0,
                "unpaid_debt_amount": float(debt_map.get(g.id, Decimal("0"))),
                "warnings": [
                    *([{
                        "type": "blacklist",
                        "level": "danger",
                        "message": "Khách đang nằm trong danh sách đen.",
                    }] if g.is_blacklisted else []),
                    *([{
                        "type": "debt",
                        "level": "warning",
                        "amount": float(debt_map.get(g.id, Decimal("0"))),
                        "message": f"Khách còn nợ {float(debt_map.get(g.id, Decimal('0'))):,.0f}đ chưa thanh toán.",
                    }] if debt_map.get(g.id, Decimal("0")) > 0 else []),
                ],
            },
            "last_seen_at": g.last_seen_at.isoformat() if g.last_seen_at else None,
            "total_stays": stay_count_map.get(g.id, 0),
            "tier": membership.tier.value if membership else MemberTier.BASIC.value,
            "tier_display": _tier_display_name(membership.tier if membership else MemberTier.BASIC, db),
            "total_spent": float(membership.total_spent) if membership else 0,
            "loyalty_points": membership.points_balance if membership else 0,
            "last_stay": {
                "room_number": last_room,
                "branch_name": last_branch,
                "check_in": last_stay_data.check_in_at.isoformat() if last_stay_data and last_stay_data.check_in_at else None,
            } if last_stay_data else None,
        })

    return JSONResponse({
        "guests": results,
        "items": results,  # Backward compatibility
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    })


@router.get("/api/pms/crm/guests/{guest_id}", tags=["PMS - CRM"])
def api_get_guest(
    request: Request,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """
    Lấy thông tin chi tiết khách hàng
    """
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    profile = get_guest_comprehensive_profile(
        db=db,
        guest_id=guest_id,
        include_stays=True,
        include_services=True,
        include_payments=True,
        include_activities=True,
    )

    return JSONResponse(profile)


@router.get("/api/pms/crm/guests/{guest_id}/profile", tags=["PMS - CRM"])
def api_get_guest_profile(
    request: Request,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """
    Lấy profile tóm tắt của khách
    """
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    membership = db.query(GuestMembership).filter(
        GuestMembership.guest_id == guest_id
    ).first()

    # Get all stats in a single query using subquery
    stats_q = db.query(
        func.count(GuestStaySummary.id).label('total_stays'),
        func.coalesce(func.sum(GuestStaySummary.nights), 0).label('total_nights'),
        func.coalesce(func.sum(
            func.coalesce(GuestStaySummary.final_amount, 0) - func.coalesce(GuestStaySummary.debt_amount, 0)
        ), 0).label('total_spent'),
        func.coalesce(func.sum(GuestStaySummary.debt_amount), 0).label('total_debt'),
    ).filter(GuestStaySummary.guest_id == guest_id).first()

    total_stays = stats_q.total_stays or 0
    total_nights = stats_q.total_nights or 0
    total_spent = stats_q.total_spent or Decimal("0")
    total_debt = stats_q.total_debt or Decimal("0")
    risk_flags = get_guest_risk_flags(db, guest_id)

    avg_per_stay = float(total_spent) / total_stays if total_stays > 0 else 0

    # Calculate current tier from points_balance
    current_points = float(membership.points_balance) if membership and membership.points_balance else 0
    current_tier = calculate_tier(Decimal(str(current_points)), db)
    
    # Get benefits for current tier
    benefits = get_tier_benefits(current_tier, db)

    # Build complete tier journey
    tier_order = list(MemberTier)
    current_idx = tier_order.index(current_tier)
    
    # All tiers for journey display
    all_tiers = []
    for i, tier in enumerate(tier_order):
        threshold = float(get_membership_thresholds(db)[tier])
        tier_points = current_points if tier == current_tier else (threshold if threshold > 0 else 0)
        
        # Progress within this tier (0-100%)
        if i < len(tier_order) - 1:
            next_threshold = float(get_membership_thresholds(db)[tier_order[i + 1]])
            tier_range = next_threshold - threshold
            if tier_range > 0:
                tier_progress = min(100, max(0, (current_points - threshold) / tier_range * 100))
            else:
                tier_progress = 100
        else:
            tier_progress = 100  # VIP is max
        
        all_tiers.append({
            "tier": tier.value,
            "tier_display": _tier_display_name(tier, db),
            "threshold": threshold,
            "threshold_display": f"{threshold:,.0f}" if threshold > 0 else "0",
            "is_current": tier == current_tier,
            "is_unlocked": current_points >= threshold,
            "progress_percent": tier_progress,
        })

    # Next tier info (for current tier)
    next_tier = tier_order[current_idx + 1] if current_idx < len(tier_order) - 1 else None
    next_tier_info = None
    if next_tier:
        next_threshold = float(get_membership_thresholds(db)[next_tier])
        remaining = next_threshold - current_points
        progress_percent = min(100, max(0, (current_points / next_threshold) * 100)) if next_threshold > 0 else 0
        next_tier_info = {
            "tier": next_tier.value,
            "tier_display": _tier_display_name(next_tier, db),
            "threshold": next_threshold,
            "threshold_display": f"{next_threshold:,.0f}",
            "remaining": max(0, remaining),
            "remaining_display": f"{max(0, remaining):,.0f}",
            "progress_percent": progress_percent,
        }

    # Preferences and favorites. Prefer stored membership fields, then derive from history.
    favorite_branch_id = membership.favorite_branch_id if membership else None
    favorite_room_type = membership.favorite_room_type if membership else None
    preferred_payment_method = membership.preferred_payment_method if membership else None

    if not favorite_branch_id:
        branch_row = db.query(
            GuestStaySummary.branch_id,
            func.count(GuestStaySummary.id).label("stay_count"),
        ).filter(
            GuestStaySummary.guest_id == guest_id,
            GuestStaySummary.branch_id.isnot(None),
        ).group_by(GuestStaySummary.branch_id).order_by(func.count(GuestStaySummary.id).desc()).first()
        favorite_branch_id = branch_row.branch_id if branch_row else None

    if not favorite_room_type:
        room_row = db.query(
            GuestStaySummary.room_type_name,
            func.count(GuestStaySummary.id).label("stay_count"),
        ).filter(
            GuestStaySummary.guest_id == guest_id,
            GuestStaySummary.room_type_name.isnot(None),
        ).group_by(GuestStaySummary.room_type_name).order_by(func.count(GuestStaySummary.id).desc()).first()
        favorite_room_type = room_row.room_type_name if room_row else None

    if not preferred_payment_method:
        payment_row = db.query(
            GuestPaymentSummary.payment_method,
            func.count(GuestPaymentSummary.id).label("payment_count"),
        ).filter(
            GuestPaymentSummary.guest_id == guest_id,
            GuestPaymentSummary.payment_method.isnot(None),
            GuestPaymentSummary.is_voided == False,
        ).group_by(GuestPaymentSummary.payment_method).order_by(func.count(GuestPaymentSummary.id).desc()).first()
        preferred_payment_method = payment_row.payment_method if payment_row else None

    favorite_branch_name = None
    if favorite_branch_id:
        favorite_branch = db.query(Branch).filter(Branch.id == favorite_branch_id).first()
        favorite_branch_name = favorite_branch.name if favorite_branch else None

    preferences = db.query(GuestPreference).filter(
        GuestPreference.guest_id == guest_id
    ).order_by(GuestPreference.preference_type.asc()).all()

    # Get all tiers for journey visualization
    tier_journey = all_tiers

    return JSONResponse({
        "guest": {
            "id": guest.id,
            "full_name": guest.full_name,
            "phone": guest.phone,
            "email": guest.email,
            "cccd": guest.cccd,
            "cccd_expire_date": guest.id_expire.isoformat() if guest.id_expire else None,
            "date_of_birth": guest.date_of_birth.isoformat() if guest.date_of_birth else None,
            "gender": guest.gender,
            "nationality": guest.nationality,
            "address": guest.default_address,
            "default_address": guest.default_address,
            "first_seen_at": guest.first_seen_at.isoformat() if guest.first_seen_at else None,
            "last_seen_at": guest.last_seen_at.isoformat() if guest.last_seen_at else None,
            "is_blacklisted": guest.is_blacklisted,
            "has_unpaid_debt": risk_flags["has_unpaid_debt"],
            "unpaid_debt_amount": risk_flags["unpaid_debt_amount"],
            "risk_flags": risk_flags,
            "tags": guest.tags or [],
        },
        "stats": {
            "total_stays": total_stays,
            "total_nights": int(total_nights) if total_nights else 0,
            "total_spent": float(total_spent),
            "total_spent_display": f"{float(total_spent):,.0f}",
            "avg_per_stay": round(avg_per_stay, 0),
            "avg_per_stay_display": f"{round(avg_per_stay, 0):,.0f}",
            "total_paid": float(total_spent),
            "total_debt": float(total_debt),
            "unpaid_debt": risk_flags["unpaid_debt_amount"],
        },
        "membership": {
            "tier": current_tier.value,
            "tier_display": _tier_display_name(current_tier, db),
            "total_spent": float(membership.total_spent or Decimal("0")) if membership else float(total_spent),
            "total_stays": total_stays,
            "total_nights": int(total_nights) if total_nights else 0,
            "total_debt": float(total_debt),
            "loyalty_points": int(current_points),
            "loyalty_points_display": f"{int(current_points):,}",
            "tier_updated_at": membership.tier_updated_at.isoformat() if membership and membership.tier_updated_at else None,
            "benefits": benefits,
            "next_tier": next_tier_info,
            "tier_journey": tier_journey,
            "favorite_branch": favorite_branch_name,
            "favorite_room_type": favorite_room_type,
            "preferred_payment_method": preferred_payment_method,
        },
        "profile": {
            "favorite": {
                "branch": favorite_branch_name,
                "room_type": favorite_room_type,
                "payment_method": preferred_payment_method,
            },
            "preferences": [
                {
                    "type": pref.preference_type,
                    "value": pref.preference_value,
                    "source": pref.source,
                    "confidence_score": pref.confidence_score,
                }
                for pref in preferences
            ],
            "notes": None,  # Can be extended later
        },
    })


# ====================================================================
# GUEST STAY HISTORIES
# ====================================================================

@router.get("/api/pms/crm/guests/{guest_id}/co-guests", tags=["PMS - CRM"])
def api_get_guest_co_guests(
    request: Request,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """
    Lấy danh sách khách cùng ở với khách này dựa trên GuestStayMapping.
    Trả về thông tin về các khách đã từng ở cùng phòng với khách này.
    """
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    from ...db.models import GuestStayMapping
    # Get all stay_ids where this guest stayed
    my_mappings = db.query(GuestStayMapping.stay_id).filter(
        GuestStayMapping.guest_id == guest_id
    ).all()
    stay_ids = [m.stay_id for m in my_mappings]

    if not stay_ids:
        return JSONResponse({
            "guest_id": guest_id,
            "guest_name": guest.full_name,
            "co_guests": [],
            "total_co_guests": 0,
        })

    # Find all other guests who stayed in these same stays
    co_guest_records = (
        db.query(
            GuestStayMapping.guest_id,
            GuestStayMapping.stay_id,
            GuestStayMapping.room_number,
            GuestStayMapping.check_in_at,
            GuestStayMapping.check_out_at,
            GuestStayMapping.is_primary,
            Guest.full_name,
            Guest.phone,
            Guest.cccd,
        )
        .join(Guest, Guest.id == GuestStayMapping.guest_id)
        .filter(GuestStayMapping.stay_id.in_(stay_ids))
        .filter(GuestStayMapping.guest_id != guest_id)
        .filter(Guest.deleted_at.is_(None))
        .order_by(GuestStayMapping.check_in_at.desc())
        .all()
    )

    # Group by co-guest and count how many times they stayed together
    co_guest_map = {}
    for record in co_guest_records:
        cg_id = record.guest_id
        if cg_id not in co_guest_map:
            co_guest_map[cg_id] = {
                "guest_id": cg_id,
                "full_name": record.full_name,
                "phone": record.phone,
                "cccd": record.cccd,
                "stay_count": 0,
                "stays": [],
            }
        co_guest_map[cg_id]["stay_count"] += 1
        co_guest_map[cg_id]["stays"].append({
            "stay_id": record.stay_id,
            "room_number": record.room_number,
            "check_in_at": record.check_in_at.isoformat() if record.check_in_at else None,
            "check_out_at": record.check_out_at.isoformat() if record.check_out_at else None,
        })

    # Get membership info for co-guests
    co_guest_ids = list(co_guest_map.keys())
    memberships = db.query(GuestMembership).filter(
        GuestMembership.guest_id.in_(co_guest_ids)
    ).all()
    membership_map = {m.guest_id: m for m in memberships}

    results = []
    for cg_id, data in co_guest_map.items():
        membership = membership_map.get(cg_id)
        results.append({
            "guest_id": data["guest_id"],
            "full_name": data["full_name"],
            "phone": data["phone"],
            "cccd": data["cccd"],
            "tier": membership.tier.value if membership else "BASIC",
            "tier_display": _tier_display_name(membership.tier if membership else MemberTier.BASIC, db),
            "total_stays": membership.total_stays if membership else 0,
            "total_spent": float(membership.total_spent) if membership else 0,
            "stay_count": data["stay_count"],
            "stays": data["stays"],
        })

    # Sort by stay_count descending (most frequently stayed together)
    results.sort(key=lambda x: x["stay_count"], reverse=True)

    return JSONResponse({
        "guest_id": guest_id,
        "guest_name": guest.full_name,
        "co_guests": results,
        "total_co_guests": len(results),
    })


@router.get("/api/pms/crm/guests/{guest_id}/stays", tags=["PMS - CRM"])
def api_get_guest_stays(
    request: Request,
    guest_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    branch_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Lấy lịch sử lưu trú của khách (ưu tiên GuestStaySummary, fallback về HotelStay)
    """
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    # Try GuestStaySummary first
    q = db.query(GuestStaySummary).filter(GuestStaySummary.guest_id == guest_id)
    if branch_id:
        q = q.filter(GuestStaySummary.branch_id == branch_id)

    total = q.count()
    summaries = q.order_by(GuestStaySummary.check_in_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    # If no summary data, fallback to HotelStay
    if total == 0:
        stay_q = db.query(HotelStay).join(
            HotelGuest, HotelGuest.stay_id == HotelStay.id
        ).filter(HotelGuest.guest_id == guest_id)
        
        total = stay_q.count()
        stays = stay_q.order_by(HotelStay.check_in_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()

        # Get branch and room data
        branch_ids = list(set(s.branch_id for s in stays if s.branch_id))
        branch_map = {b.id: b.name for b in db.query(Branch).filter(Branch.id.in_(branch_ids)).all()} if branch_ids else {}
        
        room_ids = list(set(s.room_id for s in stays if s.room_id))
        room_map = {r.id: r.room_number for r in db.query(HotelRoom).filter(HotelRoom.id.in_(room_ids)).all()} if room_ids else {}

        results = []
        for s in stays:
            duration = _duration_payload(s.check_in_at, s.check_out_at)
            activities = db.query(GuestActivity).filter(
                GuestActivity.guest_id == guest_id,
                GuestActivity.stay_id == s.id,
            ).order_by(GuestActivity.created_at.desc()).limit(20).all()
            results.append({
                "id": s.id,
                "stay_id": s.id,
                "room_number": room_map.get(s.room_id),
                "room_type_name": None,
                "floor": None,
                "branch_id": s.branch_id,
                "branch_name": branch_map.get(s.branch_id),
                "check_in_at": s.check_in_at.isoformat() if s.check_in_at else None,
                "check_out_at": s.check_out_at.isoformat() if s.check_out_at else None,
                **duration,
                "nights": (s.check_out_at - s.check_in_at).days if s.check_in_at and s.check_out_at else 0,
                "total_charge": 0,
                "discount": 0,
                "deposit": 0,
                "final_amount": 0,
                "debt_amount": 0,
                "stay_type": s.stay_type.value if s.stay_type else None,
                "pricing_mode": None,
                "guest_count": 1,
                "status": s.status.value if s.status else None,
                "checkout_summary": "normal" if s.status != HotelStayStatus.ACTIVE else None,
                "payment_methods": [],
                "vehicle": None,
                "source": "pms",
                "debt_status": "none",
                "activities": [_activity_payload(a) for a in activities],
            })
        
        return JSONResponse({
            "guest_id": guest_id,
            "guest_name": guest.full_name,
            "items": results,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total else 0,
        })

    # Original logic for when we have summary data
    branch_ids = list(set(s.branch_id for s in summaries if s.branch_id))
    branches = db.query(Branch).filter(Branch.id.in_(branch_ids)).all() if branch_ids else []
    branch_map = {b.id: b.name for b in branches}

    results = []
    for s in summaries:
        duration = _duration_payload(s.check_in_at, s.check_out_at)
        activities = db.query(GuestActivity).filter(
            GuestActivity.guest_id == guest_id,
            GuestActivity.stay_id == s.stay_id,
        ).order_by(GuestActivity.created_at.desc()).limit(20).all()
        transfer_settlement = _stay_transfer_settlement_payload(db, s.stay_id)
        results.append({
            "id": s.id,
            "stay_id": s.stay_id,
            "room_number": s.room_number,
            "room_type_name": s.room_type_name,
            "floor": s.floor,
            "branch_id": s.branch_id,
            "branch_name": branch_map.get(s.branch_id),
            "check_in_at": s.check_in_at.isoformat() if s.check_in_at else None,
            "check_out_at": s.check_out_at.isoformat() if s.check_out_at else None,
            **duration,
            "nights": s.nights,
            "total_charge": float(s.total_charge) if s.total_charge else 0,
            "discount": float(s.discount) if s.discount else 0,
            "deposit": float(s.deposit) if s.deposit else 0,
            "final_amount": float(s.final_amount) if s.final_amount else 0,
            "debt_amount": float(s.debt_amount) if s.debt_amount else 0,
            "stay_type": s.stay_type,
            "pricing_mode": s.pricing_mode,
            "guest_count": s.guest_count,
            "status": s.status,
            "checkout_summary": s.checkout_summary,
            "payment_methods": s.payment_methods or [],
            "vehicle": s.vehicle,
            "source": s.source,
            "debt_status": s.debt_status,
            "transfer_settlement": transfer_settlement,
            "activities": [_activity_payload(a) for a in activities],
        })

    return JSONResponse({
        "guest_id": guest_id,
        "guest_name": guest.full_name,
        "items": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    })


@router.get("/api/pms/crm/guests/{guest_id}/stays/{stay_id}/detail", tags=["PMS - CRM"])
def api_get_guest_stay_detail(
    request: Request,
    guest_id: int,
    stay_id: int,
    db: Session = Depends(get_db),
):
    """
    Lấy chi tiết một lần lưu trú cụ thể
    """
    user = _require_login(request)

    # Get summary
    summary = db.query(GuestStaySummary).filter(
        GuestStaySummary.guest_id == guest_id,
        GuestStaySummary.stay_id == stay_id,
    ).first()

    if not summary:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")

    # Get related data
    stay = db.query(HotelStay).filter(HotelStay.id == stay_id).first()
    branch = db.query(Branch).filter(Branch.id == summary.branch_id).first() if summary.branch_id else None

    # Get service usages for this stay
    services = db.query(GuestServiceUsage).filter(
        GuestServiceUsage.guest_id == guest_id,
        GuestServiceUsage.stay_id == stay_id,
    ).order_by(GuestServiceUsage.used_at).all()

    # Get payments for this stay
    payments = db.query(GuestPaymentSummary).filter(
        GuestPaymentSummary.guest_id == guest_id,
        GuestPaymentSummary.stay_id == stay_id,
    ).order_by(GuestPaymentSummary.paid_at).all()

    # Get activities for this stay
    activities = db.query(GuestActivity).filter(
        GuestActivity.guest_id == guest_id,
        GuestActivity.stay_id == stay_id,
    ).order_by(GuestActivity.created_at).all()

    return JSONResponse({
        "summary": {
            "id": summary.id,
            "stay_id": summary.stay_id,
            "room_number": summary.room_number,
            "room_type_name": summary.room_type_name,
            "floor": summary.floor,
            "branch_name": branch.name if branch else None,
            "check_in_at": summary.check_in_at.isoformat() if summary.check_in_at else None,
            "check_out_at": summary.check_out_at.isoformat() if summary.check_out_at else None,
            **_duration_payload(summary.check_in_at, summary.check_out_at),
            "nights": summary.nights,
            "total_charge": float(summary.total_charge) if summary.total_charge else 0,
            "discount": float(summary.discount) if summary.discount else 0,
            "deposit": float(summary.deposit) if summary.deposit else 0,
            "final_amount": float(summary.final_amount) if summary.final_amount else 0,
            "debt_amount": float(summary.debt_amount) if summary.debt_amount else 0,
            "stay_type": summary.stay_type,
            "pricing_mode": summary.pricing_mode,
            "guest_count": summary.guest_count,
            "status": summary.status,
            "payment_methods": summary.payment_methods or [],
            "vehicle": summary.vehicle,
            "source": summary.source,
            "debt_status": summary.debt_status,
        },
        "services": [
            {
                "id": s.id,
                "category": s.service_category,
                "name": s.service_name,
                "quantity": float(s.quantity) if s.quantity else 1,
                "unit_price": float(s.unit_price) if s.unit_price else 0,
                "total_amount": float(s.total_amount) if s.total_amount else 0,
                "room_number": s.room_number,
                "used_at": s.used_at.isoformat() if s.used_at else None,
            }
            for s in services
        ],
        "payments": [
            {
                "id": p.id,
                "type": p.payment_type,
                "method": p.payment_method,
                "amount": float(p.amount) if p.amount else 0,
                "transaction_code": _payment_transaction_code(db, p),
                "room_number": p.room_number,
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
                "is_voided": p.is_voided,
            }
            for p in payments
        ],
        "activities": [_activity_payload(a) for a in activities],
    })


# ====================================================================
# GUEST SERVICE USAGE
# ====================================================================

@router.get("/api/pms/crm/guests/{guest_id}/services", tags=["PMS - CRM"])
def api_get_guest_services(
    request: Request,
    guest_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Lấy lịch sử sử dụng dịch vụ
    """
    user = _require_login(request)

    # Verify guest
    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    q = db.query(GuestServiceUsage).filter(GuestServiceUsage.guest_id == guest_id)

    if category:
        q = q.filter(GuestServiceUsage.service_category == category)

    if date_from:
        try:
            df = VN_TZ.localize(datetime.fromisoformat(date_from))
            q = q.filter(GuestServiceUsage.used_at >= df)
        except:
            pass

    if date_to:
        try:
            dt = VN_TZ.localize(datetime.fromisoformat(date_to + " 23:59:59"))
            q = q.filter(GuestServiceUsage.used_at <= dt)
        except:
            pass

    total = q.count()
    usages = q.order_by(GuestServiceUsage.used_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    # Get stats
    stats = get_guest_service_stats(db, guest_id)

    # Batch fetch branches
    branch_ids = list(set(s.branch_id for s in usages if s.branch_id))
    branch_map = {}
    if branch_ids:
        branches = db.query(Branch).filter(Branch.id.in_(branch_ids)).all()
        branch_map = {b.id: b.name for b in branches}

    results = []
    for s in usages:
        results.append({
            "id": s.id,
            "stay_id": s.stay_id,
            "category": s.service_category,
            "name": s.service_name,
            "quantity": float(s.quantity) if s.quantity else 1,
            "unit_price": float(s.unit_price) if s.unit_price else 0,
            "total_amount": float(s.total_amount) if s.total_amount else 0,
            "room_number": s.room_number,
            "branch_name": branch_map.get(s.branch_id),
            "used_at": s.used_at.isoformat() if s.used_at else None,
        })

    return JSONResponse({
        "guest_id": guest_id,
        "guest_name": guest.full_name,
        "items": results,
        "stats": stats,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    })


# ====================================================================
# GUEST PAYMENT HISTORY
# ====================================================================

@router.get("/api/pms/crm/guests/{guest_id}/payments", tags=["PMS - CRM"])
def api_get_guest_payments(
    request: Request,
    guest_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    method: Optional[str] = Query(default=None),
    payment_type: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Lấy lịch sử thanh toán
    """
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    q = db.query(GuestPaymentSummary).filter(GuestPaymentSummary.guest_id == guest_id)

    if method:
        q = q.filter(GuestPaymentSummary.payment_method == method)

    if payment_type:
        q = q.filter(GuestPaymentSummary.payment_type == payment_type)

    total = q.count()
    payments = q.order_by(GuestPaymentSummary.paid_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    # Get stats
    stats = get_guest_payment_stats(db, guest_id)
    debt_q = db.query(
        func.coalesce(func.sum(GuestStaySummary.debt_amount), 0).label("total_debt")
    ).filter(
        GuestStaySummary.guest_id == guest_id,
        GuestStaySummary.debt_amount > 0,
    ).first()
    stats["total_debt"] = float(debt_q.total_debt or 0)

    results = []
    for p in payments:
        branch = db.query(Branch).filter(Branch.id == p.branch_id).first()
        results.append({
            "id": p.id,
            "stay_id": p.stay_id,
            "folio_id": p.folio_id,
            "payment_id": p.payment_id,
            "type": p.payment_type,
            "method": p.payment_method,
            "amount": float(p.amount) if p.amount else 0,
            "transaction_code": _payment_transaction_code(db, p),
            "room_number": p.room_number,
            "branch_name": branch.name if branch else None,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "is_voided": p.is_voided,
            "void_reason": p.void_reason,
        })

    return JSONResponse({
        "guest_id": guest_id,
        "guest_name": guest.full_name,
        "items": results,
        "stats": stats,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    })


# ====================================================================
# GUEST TIMELINE (Activities)
# ====================================================================

@router.get("/api/pms/crm/guests/{guest_id}/timeline", tags=["PMS - CRM"])
def api_get_guest_timeline_full(
    request: Request,
    guest_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    group: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Lấy timeline đầy đủ (hoạt động, thanh toán, dịch vụ)
    """
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    # Get activities
    q = db.query(GuestActivity).filter(GuestActivity.guest_id == guest_id)
    if group:
        q = q.filter(GuestActivity.activity_group == group)

    activities = q.order_by(GuestActivity.created_at.desc()).offset(offset).limit(limit).all()

    # Stats
    stats = get_guest_stats(db, guest_id)

    results = []
    for a in activities:
        results.append(_activity_payload(a))

    return JSONResponse({
        "guest_id": guest_id,
        "guest_name": guest.full_name,
        "items": results,
        "stats": stats,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "count": len(results),
        },
    })


# ====================================================================
# MEMBERSHIP MANAGEMENT
# ====================================================================

@router.get("/api/pms/memberships/tiers", tags=["PMS - CRM"])
def api_get_membership_tiers(request: Request, db: Session = Depends(get_db)):
    """
    Lấy danh sách bậc thành viên và quyền lợi
    """
    user = _require_login(request)

    tiers = []
    thresholds = get_membership_thresholds(db)
    for tier in MemberTier:
        threshold = float(thresholds.get(tier, Decimal("0")))
        tiers.append({
            "tier": tier.value,
            "tier_display": _tier_display_name(tier, db),
            "threshold": threshold,
            "threshold_display": f"{threshold:,.0f} điểm" if threshold > 0 else "Miễn phí",
            "benefits": get_tier_benefits(tier, db),
        })

    return JSONResponse({"tiers": tiers})


@router.get("/api/pms/crm/settings/membership", tags=["PMS - CRM"])
def api_get_crm_membership_settings(request: Request, db: Session = Depends(get_db)):
    _require_login(request)
    return JSONResponse(get_membership_settings(db))


@router.put("/api/pms/crm/settings/membership", tags=["PMS - CRM"])
def api_update_crm_membership_settings(
    request: Request,
    payload: CrmMembershipSettingsPayload,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Bạn không có quyền cập nhật thiết lập CRM")
    try:
        settings = save_membership_settings(db, payload.model_dump(), user_id=user.get("id"))
        db.commit()
        return JSONResponse({"status": "success", "settings": settings})
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/pms/crm/guests/{guest_id}/membership", tags=["PMS - CRM"])
def api_get_guest_membership(
    request: Request,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """
    Lấy thông tin thành viên của khách
    """
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    membership = db.query(GuestMembership).filter(
        GuestMembership.guest_id == guest_id
    ).first()

    if not membership:
        return JSONResponse({
            "guest_id": guest_id,
            "membership": None,
            "message": "Khách chưa có thông tin thành viên",
        })

    total_spent = db.query(
        func.coalesce(func.sum(
            func.coalesce(GuestStaySummary.final_amount, 0) - func.coalesce(GuestStaySummary.debt_amount, 0)
        ), 0)
    ).filter(
        GuestStaySummary.guest_id == guest_id
    ).scalar() or Decimal("0")

    # Calculate tier dựa trên điểm thưởng
    current_tier = calculate_tier(membership.points_balance or Decimal("0"), db)
    current_points = membership.points_balance or 0

    # Progress to next tier
    tier_order = list(MemberTier)
    current_idx = tier_order.index(current_tier)
    next_tier = tier_order[current_idx + 1] if current_idx < len(tier_order) - 1 else None

    next_tier_info = None
    if next_tier and current_tier != MemberTier.VIP:
        threshold = float(get_membership_thresholds(db)[next_tier])
        remaining = threshold - current_points
        next_tier_info = {
            "tier": next_tier.value,
            "tier_display": _tier_display_name(next_tier, db),
            "threshold": threshold,
            "remaining": max(0, remaining),
            "progress_percent": min(100, (current_points / threshold) * 100) if threshold > 0 else 100,
        }

    return JSONResponse({
        "guest_id": guest_id,
        "guest_name": guest.full_name,
        "membership": {
            "tier": membership.tier.value,
            "tier_display": _tier_display_name(membership.tier, db),
            "total_stays": membership.total_stays,
            "total_nights": membership.total_nights,
            "total_spent": float(membership.total_spent or Decimal("0")),
            "total_deposit": float(membership.total_deposit) if membership.total_deposit else 0,
            "total_debt": float(membership.total_debt) if membership.total_debt else 0,
            "loyalty_points": membership.loyalty_points,
            "points_balance": membership.points_balance or 0,
            "points_redeemed": membership.points_redeemed,
            "favorite_branch": membership.favorite_branch.name if membership.favorite_branch else None,
            "favorite_room_type": membership.favorite_room_type,
            "preferred_payment_method": membership.preferred_payment_method,
            "tier_updated_at": membership.tier_updated_at.isoformat() if membership.tier_updated_at else None,
            "benefits": get_tier_benefits(membership.tier, db),
        },
        "next_tier": next_tier_info,
        "current_points": current_points,
    })


@router.patch("/api/pms/crm/guests/{guest_id}/blacklist", tags=["PMS - CRM"])
def api_update_guest_blacklist(
    request: Request,
    guest_id: int,
    payload: GuestBlacklistPayload,
    db: Session = Depends(get_db),
):
    """Đánh dấu hoặc gỡ khách khỏi danh sách đen."""
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id, Guest.deleted_at.is_(None)).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    guest.is_blacklisted = payload.is_blacklisted
    guest.updated_by = user.get("id")
    branch_id = _active_branch_id(request, db)

    tags = list(guest.tags or [])
    if payload.is_blacklisted and "BLACKLIST" not in tags:
        tags.append("BLACKLIST")
    if not payload.is_blacklisted:
        tags = [t for t in tags if t != "BLACKLIST"]
    guest.tags = tags

    log_activity(
        db=db,
        guest_id=guest.id,
        activity_type="BLACKLISTED" if payload.is_blacklisted else "PROFILE_UPDATED",
        activity_group=ActivityGroup.SYSTEM,
        title="Đưa vào danh sách đen" if payload.is_blacklisted else "Gỡ khỏi danh sách đen",
        description=payload.reason or ("Khách được đưa vào danh sách đen" if payload.is_blacklisted else "Khách được gỡ khỏi danh sách đen"),
        branch_id=branch_id,
        actor_type=ActorType.USER,
        actor_id=user.get("id"),
        source=Source.PMS,
        extra_data={"is_blacklisted": payload.is_blacklisted, "reason": payload.reason},
    )

    db.commit()
    return JSONResponse({
        "guest_id": guest.id,
        "is_blacklisted": guest.is_blacklisted,
        "risk_flags": get_guest_risk_flags(db, guest.id),
    })


# ====================================================================
# GUEST LIST BY TIER
# ====================================================================

@router.get("/api/pms/crm/guests/tier/{tier}", tags=["PMS - CRM"])
def api_get_guests_by_tier(
    request: Request,
    tier: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Lấy danh sách khách theo bậc thành viên
    """
    user = _require_login(request)

    try:
        tier_enum = MemberTier(tier)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bậc thành viên không hợp lệ")

    # Get guest IDs with this tier
    subq = db.query(GuestMembership.guest_id).filter(
        GuestMembership.tier == tier_enum
    ).subquery()

    q = db.query(Guest).filter(Guest.id.in_(subq), Guest.deleted_at.is_(None))
    total = q.count()

    guests = q.order_by(Guest.last_seen_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    results = []
    for g in guests:
        membership = db.query(GuestMembership).filter(
            GuestMembership.guest_id == g.id
        ).first()

        results.append({
            "id": g.id,
            "full_name": g.full_name,
            "phone": g.phone,
            "cccd": g.cccd,
            "nationality": g.nationality,
            "is_blacklisted": g.is_blacklisted,
            "last_seen_at": g.last_seen_at.isoformat() if g.last_seen_at else None,
            "total_stays": membership.total_stays if membership else 0,
            "total_spent": float(membership.total_spent) if membership else 0,
            "loyalty_points": membership.points_balance if membership else 0,
        })

    return JSONResponse({
        "tier": tier,
        "tier_display": _tier_display_name(tier_enum, db),
        "items": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    })


# ====================================================================
# ANALYTICS & REPORTS
# ====================================================================

@router.get("/api/pms/crm/stats", tags=["PMS - CRM"])
def api_crm_stats(
    request: Request,
    q: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Thống kê CRM dashboard - alias cho /stats/overview
    """
    user = _require_login(request)
    
    # Total guests
    total_guests = db.query(func.count(Guest.id)).filter(
        Guest.deleted_at.is_(None)
    ).scalar() or 0
    
    # Search filter
    guest_filter = []
    if q:
        guest_filter = [
            or_(
                Guest.full_name.ilike(f"%{q}%"),
                Guest.phone.ilike(f"%{q}%"),
                Guest.cccd.ilike(f"%{q}%"),
                Guest.email.ilike(f"%{q}%"),
            )
        ]

    # Guests by tier
    tier_counts = {}
    for tier in MemberTier:
        query = db.query(func.count(GuestMembership.id)).filter(
            GuestMembership.tier == tier
        )
        if guest_filter:
            query = query.join(Guest, Guest.id == GuestMembership.guest_id).filter(*guest_filter)
        count = query.scalar() or 0
        tier_counts[tier.value] = count

    # Total stays & revenue from GuestStaySummary
    stays_q = db.query(GuestStaySummary)
    if guest_filter:
        stays_q = stays_q.join(Guest, Guest.id == GuestStaySummary.guest_id).filter(*guest_filter)
    
    total_stays = stays_q.count()
    total_revenue = stays_q.with_entities(
        func.coalesce(func.sum(
            func.coalesce(GuestStaySummary.final_amount, 0) - func.coalesce(GuestStaySummary.debt_amount, 0)
        ), 0)
    ).scalar() or Decimal("0")
    total_nights = stays_q.with_entities(func.coalesce(func.sum(GuestStaySummary.nights), 0)).scalar() or 0

    # Average
    avg_per_stay = float(total_revenue) / total_stays if total_stays > 0 else 0

    # New guests
    new_guests_q = db.query(func.count(Guest.id)).filter(Guest.deleted_at.is_(None))
    if guest_filter:
        new_guests_q = new_guests_q.filter(*guest_filter)
    new_guests = new_guests_q.scalar() or 0

    return JSONResponse({
        "total_guests": total_guests,
        "tier_distribution": tier_counts,
        "total_stays": total_stays,
        "total_revenue": float(total_revenue),
        "total_nights": int(total_nights) if total_nights else 0,
        "avg_per_stay": round(avg_per_stay, 0),
        "new_guests": new_guests,
        "repeat_guests": 0,
    })


@router.get("/api/pms/crm/stats/overview", tags=["PMS - CRM"])
def api_crm_overview_stats(
    request: Request,
    branch_id: Optional[int] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Thống kê tổng quan CRM
    """
    user = _require_login(request)

    # Base filters
    filter_args = []
    if branch_id:
        filter_args.append(GuestStaySummary.branch_id == branch_id)
    if date_from:
        try:
            df = VN_TZ.localize(datetime.fromisoformat(date_from))
            filter_args.append(GuestStaySummary.check_in_at >= df)
        except:
            pass
    if date_to:
        try:
            dt = VN_TZ.localize(datetime.fromisoformat(date_to + " 23:59:59"))
            filter_args.append(GuestStaySummary.check_in_at <= dt)
        except:
            pass

    # Total guests
    total_guests = db.query(func.count(Guest.id)).filter(
        Guest.deleted_at.is_(None)
    ).scalar() or 0

    # Guests by tier
    tier_counts = {}
    for tier in MemberTier:
        count = db.query(func.count(GuestMembership.id)).filter(
            GuestMembership.tier == tier
        ).scalar() or 0
        tier_counts[tier.value] = count

    # Total stays & revenue
    q = db.query(GuestStaySummary)
    if filter_args:
        q = q.filter(*filter_args)

    total_stays = q.count()
    revenue_expr = func.sum(
        func.coalesce(GuestStaySummary.final_amount, 0) - func.coalesce(GuestStaySummary.debt_amount, 0)
    )
    total_revenue = db.query(revenue_expr).filter(*filter_args).scalar() if filter_args else db.query(revenue_expr).scalar()
    total_revenue = total_revenue or Decimal("0")
    total_nights = db.query(func.sum(GuestStaySummary.nights)).filter(*filter_args).scalar() if filter_args else db.query(func.sum(GuestStaySummary.nights)).scalar()
    total_nights = total_nights or 0

    # Average
    avg_per_stay = float(total_revenue) / total_stays if total_stays > 0 else 0
    avg_per_night = float(total_revenue) / total_nights if total_nights > 0 else 0

    # New guests this period
    new_guests = db.query(func.count(Guest.id))
    if date_from:
        try:
            df = VN_TZ.localize(datetime.fromisoformat(date_from))
            new_guests = new_guests.filter(Guest.created_at >= df)
        except:
            pass
    if date_to:
        try:
            dt = VN_TZ.localize(datetime.fromisoformat(date_to + " 23:59:59"))
            new_guests = new_guests.filter(Guest.created_at <= dt)
        except:
            pass
    new_guests = new_guests.scalar() or 0

    # Repeat guests (more than 1 stay)
    repeat_guests = db.query(
        GuestStaySummary.guest_id,
        func.count(GuestStaySummary.id).label("stay_count")
    ).group_by(GuestStaySummary.guest_id).having(
        func.count(GuestStaySummary.id) > 1
    ).count()

    return JSONResponse({
        "total_guests": total_guests,
        "tier_distribution": tier_counts,
        "total_stays": total_stays,
        "total_revenue": float(total_revenue),
        "total_nights": int(total_nights) if total_nights else 0,
        "avg_per_stay": round(avg_per_stay, 0),
        "avg_per_night": round(avg_per_night, 0),
        "new_guests": new_guests,
        "repeat_guests": repeat_guests,
    })


@router.post("/api/pms/crm/admin/rebuild-memberships", tags=["PMS - CRM - Admin"])
def api_crm_rebuild_memberships(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Tính lại toàn bộ stats và tier cho tất cả thành viên dựa trên lịch sử (dành cho Admin).
    """
    user = _require_login(request)
    
    # Ở đây có thể add thêm check quyền admin: if not user.get("is_admin"): raise ...

    try:
        from ...services.guest_crm_service import recalculate_all_memberships, batch_create_stay_summaries
        
        # 1. Create missing stay summaries from past completed stays
        summaries_result = batch_create_stay_summaries(db)
        
        # 2. Recalculate stats based on all stay summaries
        result = recalculate_all_memberships(db)
        
        return JSONResponse({
            "status": "success",
            "message": f"Đã tính toán lại dữ liệu cho {result.get('memberships_updated', 0)} khách hàng. Tạo mới {summaries_result.get('total_created', 0)} lịch sử lưu trú.",
            "data": {
                "memberships": result,
                "summaries": summaries_result
            },
        })
    except Exception as e:
        import traceback
        return JSONResponse(
            status_code=500,
            content={"detail": f"Lỗi tính toán: {str(e)}\n{traceback.format_exc()}"}
        )

# ====================================================================
# HELPER FUNCTIONS
# ====================================================================

def _tier_display_name(tier: MemberTier, db: Optional[Session] = None) -> str:
    """Lấy tên hiển thị của tier"""
    if db:
        settings = get_membership_settings(db)
        tier_value = tier.value if hasattr(tier, "value") else str(tier)
        for item in settings.get("tiers", []):
            if item.get("tier") == tier_value:
                return item.get("display_name") or tier_value
    names = {
        MemberTier.BASIC: "Khách thường",
        MemberTier.SILVER: "Thành viên Bạc",
        MemberTier.GOLD: "Thành viên Vàng",
        MemberTier.PLATINUM: "Thành viên Bạch Kim",
        MemberTier.VIP: "Khách VIP",
    }
    return names.get(tier, tier.value)
