# app/api/pms/guest_activities_api.py
"""
Guest Activities API - Timeline endpoints
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload

from ...db.models import Guest, GuestActivity, HotelGuest, HotelStay, HotelRoom, HotelRoomType, Folio, Branch, HotelStayStatus
from ...db.session import get_db
from .pms_helpers import _require_login, _active_branch, VN_TZ
from .guest_activity import (
    ActivityType, ActivityGroup, ActorType, Source,
    get_guest_timeline, get_guest_stats, get_stay_timeline, get_stay_activity_stats,
    log_activity,
    log_complaint, log_profile_updated, log_blacklisted,
)
from ...core.utils import VN_TZ
from sqlalchemy import func

router = APIRouter()


# ─────────────────────────── GET: Guest Timeline ───────────────────────────

@router.get("/api/pms/guests/{guest_id}/activities", tags=["PMS"])
async def api_get_guest_activities(
    request: Request,
    guest_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    activity_type: Optional[str] = Query(default=None),
    activity_group: Optional[str] = Query(default=None),
    stay_id: Optional[int] = Query(default=None),
    branch_id: Optional[int] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="ISO datetime"),
    date_to: Optional[str] = Query(default=None, description="ISO datetime"),
    db: Session = Depends(get_db),
):
    """
    Lấy timeline hoạt động của khách
    """
    user = _require_login(request)

    # Parse dates if provided
    parsed_date_from = None
    parsed_date_to = None
    try:
        if date_from:
            parsed_date_from = VN_TZ.localize(datetime.fromisoformat(date_from))
        if date_to:
            parsed_date_to = VN_TZ.localize(datetime.fromisoformat(date_to))
    except:
        pass

    activities = get_guest_timeline(
        db=db,
        guest_id=guest_id,
        limit=limit,
        offset=offset,
        activity_type=activity_type,
        activity_group=activity_group,
        stay_id=stay_id,
        branch_id=branch_id,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
    )

    # Get stats
    stats = get_guest_stats(db, guest_id)

    return JSONResponse({
        "activities": [
            {
                "id": a.id,
                "activity_type": a.activity_type,
                "activity_group": a.activity_group,
                "title": a.title,
                "description": a.description,
                "stay_id": a.stay_id,
                "booking_id": a.booking_id,
                "branch_id": a.branch_id,
                "amount": float(a.amount) if a.amount else None,
                "currency": a.currency,
                "actor_type": a.actor_type,
                "actor_id": a.actor_id,
                "source": a.source,
                "extra_data": a.extra_data,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in activities
        ],
        "stats": stats,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "count": len(activities),
        }
    })


@router.get("/api/pms/stays/{stay_id}/activities", tags=["PMS"])
async def api_get_stay_activities(
    request: Request,
    stay_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    activity_type: Optional[str] = Query(default=None),
    activity_group: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="ISO datetime"),
    date_to: Optional[str] = Query(default=None, description="ISO datetime"),
    db: Session = Depends(get_db),
):
    """Timeline theo lưu trú (mọi hoạt động gắn stay_id)."""
    user = _require_login(request)

    stay = db.query(HotelStay).filter(HotelStay.id == stay_id).first()
    if not stay:
        return JSONResponse(status_code=404, content={"detail": "Không tìm thấy lưu trú"})

    parsed_date_from = None
    parsed_date_to = None
    try:
        if date_from:
            parsed_date_from = VN_TZ.localize(datetime.fromisoformat(date_from))
        if date_to:
            parsed_date_to = VN_TZ.localize(datetime.fromisoformat(date_to))
    except Exception:
        pass

    activities = get_stay_timeline(
        db=db,
        stay_id=stay_id,
        limit=limit,
        offset=offset,
        activity_type=activity_type,
        activity_group=activity_group,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
    )
    stats = get_stay_activity_stats(db, stay_id)

    return JSONResponse({
        "activities": [
            {
                "id": a.id,
                "activity_type": a.activity_type,
                "activity_group": a.activity_group,
                "title": a.title,
                "description": a.description,
                "stay_id": a.stay_id,
                "booking_id": a.booking_id,
                "branch_id": a.branch_id,
                "amount": float(a.amount) if a.amount else None,
                "currency": a.currency,
                "actor_type": a.actor_type,
                "actor_id": a.actor_id,
                "source": a.source,
                "extra_data": a.extra_data,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in activities
        ],
        "stats": stats,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "count": len(activities),
        }
    })


# ─────────────────────────── GET: Activity Types ───────────────────────────

@router.get("/api/pms/activities/types", tags=["PMS"])
async def api_get_activity_types(request: Request):
    """Lấy danh sách activity types và groups"""
    user = _require_login(request)

    return JSONResponse({
        "types": {
            "stay": [
                ActivityType.CHECK_IN,
                ActivityType.CHECK_OUT,
                ActivityType.ROOM_CHANGE,
                ActivityType.EXTEND_STAY,
                ActivityType.EARLY_CHECKIN,
                ActivityType.LATE_CHECKOUT,
                ActivityType.GUEST_ADDED,
            ],
            "booking": [
                ActivityType.BOOKING_CREATED,
                ActivityType.BOOKING_MODIFIED,
                ActivityType.BOOKING_CANCELLED,
                ActivityType.NO_SHOW,
            ],
            "payment": [
                ActivityType.PAYMENT_RECEIVED,
                ActivityType.PAYMENT_REFUND,
                ActivityType.DEPOSIT_ADDED,
                ActivityType.DEPOSIT_USED,
            ],
            "service": [
                ActivityType.SERVICE_USED,
                ActivityType.MINIBAR_USED,
            ],
            "experience": [
                ActivityType.COMPLAINT,
                ActivityType.FEEDBACK,
                ActivityType.REVIEW,
                ActivityType.LOST_ITEM,
            ],
            "system": [
                ActivityType.PROFILE_UPDATED,
                ActivityType.MERGED,
                ActivityType.BLACKLISTED,
            ],
        },
        "groups": [
            ActivityGroup.STAY,
            ActivityGroup.BOOKING,
            ActivityGroup.PAYMENT,
            ActivityGroup.SERVICE,
            ActivityGroup.EXPERIENCE,
            ActivityGroup.SYSTEM,
        ]
    })


# ─────────────────────────── POST: Manual Activity (Internal) ──────────────

@router.post("/api/pms/activities", tags=["PMS"])
async def api_create_activity(
    request: Request,
    guest_id: int = Query(...),
    activity_type: str = Query(...),
    activity_group: str = Query(default=ActivityGroup.SYSTEM),
    title: str = Query(default=""),
    description: str = Query(default=""),
    stay_id: Optional[int] = Query(default=None),
    booking_id: Optional[int] = Query(default=None),
    branch_id: Optional[int] = Query(default=None),
    amount: Optional[float] = Query(default=None),
    source: str = Query(default=Source.PMS),
    extra_data: Optional[str] = Query(default=None, description="JSON string"),
    db: Session = Depends(get_db),
):
    """
    Tạo activity thủ công (internal use)
    """
    user = _require_login(request)

    # Verify guest exists
    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        return JSONResponse(status_code=404, content={"detail": "Không tìm thấy khách"})

    # Parse extra_data if provided
    parsed_extra = None
    if extra_data:
        import json
        try:
            parsed_extra = json.loads(extra_data)
        except:
            pass

    activity = log_activity(
        db=db,
        guest_id=guest_id,
        activity_type=activity_type,
        activity_group=activity_group,
        title=title,
        description=description,
        stay_id=stay_id,
        booking_id=booking_id,
        branch_id=branch_id,
        amount=amount,
        actor_type=ActorType.USER,
        actor_id=user.get("id"),
        source=source,
        extra_data=parsed_extra,
    )
    db.commit()

    return JSONResponse({
        "message": "Activity created",
        "id": activity.id,
    })


# ─────────────────────────── POST: Complaint ──────────────────────────────

@router.post("/api/pms/guests/{guest_id}/complaint", tags=["PMS"])
async def api_create_complaint(
    request: Request,
    guest_id: int,
    stay_id: int = Query(...),
    content: str = Query(...),
    db: Session = Depends(get_db),
):
    """Tạo complaint cho khách"""
    user = _require_login(request)

    # Get guest
    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        return JSONResponse(status_code=404, content={"detail": "Không tìm thấy khách"})

    # Get stay
    stay = db.query(HotelStay).filter(HotelStay.id == stay_id).first()
    if not stay:
        return JSONResponse(status_code=404, content={"detail": "Không tìm thấy lưu trú"})

    # Get primary guest
    hotel_guest = db.query(HotelGuest).filter(
        HotelGuest.stay_id == stay_id,
        HotelGuest.is_primary == True
    ).first()

    activity = log_complaint(
        db=db,
        stay=stay,
        hotel_guest=hotel_guest,
        content=content,
        actor_id=user.get("id"),
    )
    db.commit()

    return JSONResponse({
        "message": "Khiếu nại đã được ghi nhận",
        "id": activity.id,
    })


# ─────────────────────────── POST: Blacklist ──────────────────────────────

@router.post("/api/pms/guests/{guest_id}/blacklist", tags=["PMS"])
async def api_blacklist_guest(
    request: Request,
    guest_id: int,
    reason: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Thêm khách vào danh sách đen"""
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        return JSONResponse(status_code=404, content={"detail": "Không tìm thấy khách"})

    guest.is_blacklisted = True

    log_blacklisted(
        db=db,
        guest=guest,
        reason=reason,
        actor_id=user.get("id"),
    )
    db.commit()

    return JSONResponse({"message": "Đã thêm vào danh sách đen"})


# ─────────────────────────── DELETE: Remove from Blacklist ─────────────────

@router.delete("/api/pms/guests/{guest_id}/blacklist", tags=["PMS"])
async def api_unblacklist_guest(
    request: Request,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """Xóa khách khỏi danh sách đen"""
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        return JSONResponse(status_code=404, content={"detail": "Không tìm thấy khách"})

    guest.is_blacklisted = False
    db.commit()

    return JSONResponse({"message": "Đã xóa khỏi danh sách đen"})


# ─────────────────────────── GET: Guest History ───────────────────────────

@router.get("/api/pms/guests/{guest_id}/history", tags=["PMS"])
async def api_get_guest_history(
    request: Request,
    guest_id: int,
    branch_id: Optional[int] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="ISO date YYYY-MM-DD"),
    date_to: Optional[str] = Query(default=None, description="ISO date YYYY-MM-DD"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Lấy lịch sử lưu trú của 1 khách cụ thể (tất cả lưu trú đã checkout).
    """
    user = _require_login(request)
    branch_code = _active_branch(request)
    branch_id_from_session = None
    if branch_code and branch_code not in ("HỆ THỐNG", "Chưa phân bổ"):
        branch_obj = db.query(Branch).filter(Branch.branch_code == branch_code).first()
        branch_id_from_session = branch_obj.id if branch_obj else None
    effective_branch = branch_id or branch_id_from_session

    # Verify guest exists
    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        return JSONResponse(status_code=404, content={"detail": "Không tìm thấy khách"})

    # Get all HotelGuest records for this guest_id
    hotel_guest_subq = (
        db.query(HotelGuest.stay_id)
        .filter(HotelGuest.guest_id == guest_id)
        .subquery()
    )

    q = (
        db.query(HotelStay)
        .options(
            joinedload(HotelStay.room).joinedload(HotelRoom.room_type_obj),
            joinedload(HotelStay.guests),
        )
        .filter(HotelStay.id.in_(hotel_guest_subq))
        .filter(HotelStay.status != HotelStayStatus.ACTIVE)
    )

    if effective_branch:
        q = q.filter(HotelStay.branch_id == effective_branch)

    if date_from:
        try:
            df = VN_TZ.localize(datetime.fromisoformat(date_from))
            q = q.filter(HotelStay.check_in_at >= df)
        except Exception:
            pass

    if date_to:
        try:
            dt_str = date_to + " 23:59:59" if len(date_to) == 10 else date_to
            dt = VN_TZ.localize(datetime.fromisoformat(dt_str))
            q = q.filter(HotelStay.check_in_at <= dt)
        except Exception:
            pass

    total = q.order_by(HotelStay.check_in_at.desc()).count()
    stays = q.order_by(HotelStay.check_in_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    # Batch queries for folios
    stay_ids = [s.id for s in stays]
    folio_map = {}
    if stay_ids:
        folio_latest_sq = (
            db.query(Folio.stay_id, func.max(Folio.id).label("mx"))
            .filter(Folio.stay_id.in_(stay_ids))
            .group_by(Folio.stay_id)
            .subquery()
        )
        folios_batch = db.query(Folio).options(joinedload(Folio.transactions)).join(folio_latest_sq, Folio.id == folio_latest_sq.c.mx).all()
        folio_map = {f.stay_id: f for f in folios_batch}

    # Get branch info
    branch_map = {}
    branch_ids = list(set(s.branch_id for s in stays if s.branch_id))
    if branch_ids:
        branches = db.query(Branch).filter(Branch.id.in_(branch_ids)).all()
        branch_map = {b.id: b for b in branches}

    results = []
    for stay in stays:
        folio = folio_map.get(stay.id)
        branch = branch_map.get(stay.branch_id)

        # Find this guest's record in the stay
        this_guest_record = next(
            (g for g in (stay.guests or []) if g.guest_id == guest_id),
            None
        )

        summary = "normal"
        if folio and folio.debt_status not in (None, "none", "settled"):
            summary = "debt"
        elif folio and folio.refund_status in ("pending", "approved"):
            summary = "refund"

        # Get all guests in this stay
        all_guests_in_stay = [
            {
                "id": g.id,
                "full_name": g.full_name,
                "cccd": g.cccd,
                "phone": g.phone,
                "is_primary": g.is_primary,
            }
            for g in (stay.guests or [])
        ]

        results.append({
            "stay_id": stay.id,
            "room_id": stay.room_id,
            "room_number": stay.room.room_number if stay.room else "—",
            "room_floor": stay.room.floor if stay.room else None,
            "room_type_name": stay.room.room_type_obj.name if stay.room and stay.room.room_type_obj else "—",
            "branch_id": stay.branch_id,
            "branch_name": branch.name if branch else None,
            "guests": all_guests_in_stay,
            "check_in_at": stay.check_in_at.isoformat() if stay.check_in_at else None,
            "check_out_at": stay.check_out_at.isoformat() if stay.check_out_at else None,
            "total_price": float(folio.total_charge) if folio and folio.total_charge else float(stay.total_price) if stay.total_price else 0,
            "deposit": float(stay.deposit) if stay.deposit else 0,
            "status": stay.status.value if stay.status else None,
            "summary_status": summary,
            "folio": {
                "id": folio.id if folio else None,
                "balance": float(folio.balance) if folio and folio.balance else 0,
                "debt_amount": float(folio.debt_amount) if folio and folio.debt_amount else 0,
                "debt_status": folio.debt_status if folio else None,
                "refund_amount": float(folio.refund_amount) if folio and folio.refund_amount else 0,
                "refund_status": folio.refund_status if folio else None,
            } if folio else None,
        })

    # Get stats for this guest
    stats_query = (
        db.query(
            func.count(HotelStay.id).label("total_stays"),
            func.sum(HotelStay.total_price).label("total_spent"),
            func.sum(HotelStay.deposit).label("total_deposit"),
        )
        .filter(HotelStay.id.in_(hotel_guest_subq))
        .filter(HotelStay.status != HotelStayStatus.ACTIVE)
    )
    if effective_branch:
        stats_query = stats_query.filter(HotelStay.branch_id == effective_branch)
    stats_result = stats_query.first()

    return JSONResponse({
        "guest": {
            "id": guest.id,
            "full_name": guest.full_name,
            "cccd": guest.cccd,
            "phone": guest.phone,
            "email": guest.email,
            "is_blacklisted": guest.is_blacklisted,
        },
        "items": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
        "stats": {
            "total_stays": stats_result.total_stays or 0,
            "total_spent": float(stats_result.total_spent or 0),
            "total_deposit": float(stats_result.total_deposit or 0),
        },
    })
