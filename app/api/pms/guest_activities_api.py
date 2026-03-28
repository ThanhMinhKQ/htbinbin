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

from ...db.models import Guest, GuestActivity, HotelGuest, HotelStay
from ...db.session import get_db
from .pms_helpers import _require_login
from .guest_activity import (
    ActivityType, ActivityGroup, ActorType, Source,
    get_guest_timeline, get_guest_stats, get_stay_timeline, get_stay_activity_stats,
    log_activity,
    log_complaint, log_profile_updated, log_blacklisted,
)
from ...core.utils import VN_TZ

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
            parsed_date_from = datetime.fromisoformat(date_from).astimezone(VN_TZ)
        if date_to:
            parsed_date_to = datetime.fromisoformat(date_to).astimezone(VN_TZ)
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
            parsed_date_from = datetime.fromisoformat(date_from).astimezone(VN_TZ)
        if date_to:
            parsed_date_to = datetime.fromisoformat(date_to).astimezone(VN_TZ)
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
