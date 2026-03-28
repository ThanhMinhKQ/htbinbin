# app/api/pms/pms_rooms.py
"""
PMS Rooms - Room management, types, availability, and smart booking
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_

from ...db.models import Branch, HotelRoom, HotelRoomType, HotelStay, HotelStayStatus
from ...db.session import get_db
from .pms_helpers import (
    _require_login, _is_admin, _active_branch, _now_vn, _get_occupied_rooms_for_dates,
    _calc_price, _room_to_dict
)

router = APIRouter()


# ─────────────────────────── API: Rooms ─────────────────────────────

@router.get("/api/pms/rooms", tags=["PMS"])
async def api_get_rooms(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Lấy danh sách phòng cùng trạng thái hiện tại."""
    user = _require_login(request)
    is_admin = _is_admin(user)
    branch_code = _active_branch(request)

    # Xác định branch filter
    if is_admin and branch_id:
        target_branch_id = branch_id
    elif not is_admin:
        branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()
        target_branch_id = branch.id if branch else None
    else:
        target_branch_id = None

    q = (
        db.query(HotelRoom)
        .options(
            joinedload(HotelRoom.room_type_obj),
            joinedload(HotelRoom.stays).joinedload(HotelStay.guests),
        )
        .filter(HotelRoom.is_active == True)
        .order_by(HotelRoom.floor, HotelRoom.sort_order, HotelRoom.room_number)
    )
    if target_branch_id:
        q = q.filter(HotelRoom.branch_id == target_branch_id)

    rooms = q.all()

    result = []
    for room in rooms:
        active_stay = next(
            (s for s in room.stays if s.status == HotelStayStatus.ACTIVE),
            None
        )
        result.append(_room_to_dict(room, active_stay))

    floors: dict = {}
    for r in result:
        f = r["floor"]
        floors.setdefault(f, []).append(r)

    return JSONResponse({"floors": floors, "total_rooms": len(result)})


@router.get("/api/pms/room-types", tags=["PMS"])
async def api_get_room_types(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    is_admin = _is_admin(user)
    branch_code = _active_branch(request)

    q = db.query(HotelRoomType).filter(HotelRoomType.is_active == True)
    if branch_id:
        q = q.filter(HotelRoomType.branch_id == branch_id)
    elif not is_admin:
        branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()
        if branch:
            q = q.filter(HotelRoomType.branch_id == branch.id)

    types = q.order_by(HotelRoomType.sort_order, HotelRoomType.name).all()
    return JSONResponse([
        {
            "id": t.id, "name": t.name, "description": t.description,
            "price_per_night": float(t.price_per_night),
            "price_per_hour": float(t.price_per_hour),
            "price_next_hour": float(t.price_next_hour),
            "promo_start_time": t.promo_start_time.isoformat() if t.promo_start_time else None,
            "promo_end_time": t.promo_end_time.isoformat() if t.promo_end_time else None,
            "promo_discount_percent": float(t.promo_discount_percent),
            "min_hours": t.min_hours, "max_guests": t.max_guests,
        }
        for t in types
    ])


# ─────────────────────────── API: Available Rooms for Transfer ─────────────────────────

@router.get("/api/pms/rooms/available", tags=["PMS"])
async def api_get_available_rooms(
    request: Request,
    stay_id: int = Query(..., description="Stay ID to find available rooms for transfer"),
    db: Session = Depends(get_db),
):
    """Lấy danh sách phòng trống khả dụng cho chuyển phòng (loại trừ phòng hiện tại + phòng đã đặt)."""
    user = _require_login(request)
    branch_code = _active_branch(request)

    # Get current stay
    stay = (
        db.query(HotelStay)
        .options(joinedload(HotelStay.room))
        .filter(HotelStay.id == stay_id, HotelStay.status == HotelStayStatus.ACTIVE)
        .first()
    )
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")

    current_room_id = stay.room_id
    check_in = stay.check_in_at
    check_out = stay.check_out_at or _now_vn()
    branch_id = stay.branch_id

    # Get occupied room IDs in the stay date range
    occupied_ids = _get_occupied_rooms_for_dates(db, branch_id, check_in, check_out)

    # Query available rooms (not current, not occupied, same branch, active)
    q = (
        db.query(HotelRoom)
        .options(joinedload(HotelRoom.room_type_obj))
        .filter(
            HotelRoom.is_active == True,
            HotelRoom.id != current_room_id,
            HotelRoom.id.notin_(occupied_ids) if occupied_ids else True,
            HotelRoom.branch_id == branch_id,
        )
        .order_by(HotelRoom.floor, HotelRoom.sort_order, HotelRoom.room_number)
    )

    rooms = q.all()
    result = [
        {
            "id": r.id,
            "room_number": r.room_number,
            "floor": r.floor,
            "type_name": r.room_type_obj.name if r.room_type_obj else "—",
            "price_per_night": float(r.room_type_obj.price_per_night) if r.room_type_obj else 0,
            "status": "available",
        }
        for r in rooms
    ]

    return JSONResponse({
        "rooms": result,
        "current_room_id": current_room_id,
        "stay_id": stay_id,
    })


# ─────────────────────────── API: Smart Booking ─────────────────────────

@router.get("/api/pms/search-rooms", tags=["PMS"])
async def api_search_rooms(
    request: Request,
    check_in: str = Query(..., description="Check-in datetime ISO"),
    check_out: str = Query(..., description="Check-out datetime ISO"),
    stay_type: str = Query("night", description="night or hour"),
    guest_count: int = Query(1, ge=1, le=20),
    branch_id: Optional[int] = Query(None),
    room_type_id: Optional[int] = Query(None),
    budget_min: Optional[float] = Query(None),
    budget_max: Optional[float] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Smart Room Search - Tìm kiếm phòng thông minh
    """
    user = _require_login(request)
    is_admin = _is_admin(user)
    branch_code = _active_branch(request)

    # Parse datetime
    try:
        ci = datetime.fromisoformat(check_in).astimezone(VN_TZ)
        co = datetime.fromisoformat(check_out).astimezone(VN_TZ)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Định dạng datetime không hợp lệ")

    if co <= ci:
        raise HTTPException(status_code=400, detail="Check-out phải sau check-in")

    # Determine branch
    target_branch_id = branch_id
    if not target_branch_id and not is_admin:
        branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()
        if branch:
            target_branch_id = branch.id

    if not target_branch_id:
        raise HTTPException(status_code=400, detail="Cần chọn chi nhánh")

    # Get occupied rooms for the date range
    occupied_room_ids = _get_occupied_rooms_for_dates(db, target_branch_id, ci, co)

    # Build query for available rooms
    q = (
        db.query(HotelRoom)
        .options(joinedload(HotelRoom.room_type_obj))
        .filter(HotelRoom.is_active == True, HotelRoom.branch_id == target_branch_id)
    )

    if occupied_room_ids:
        q = q.filter(HotelRoom.id.notin_(occupied_room_ids))

    if room_type_id:
        q = q.filter(HotelRoom.room_type_id == room_type_id)

    rooms = q.order_by(HotelRoom.floor, HotelRoom.room_number).all()

    # Filter by guest capacity and budget
    available_rooms = []
    for room in rooms:
        rt = room.room_type_obj
        if not rt:
            continue

        if rt.max_guests < guest_count:
            continue

        price = _calc_price(stay_type, rt, ci, co, apply_promo=True)

        if budget_max and price > budget_max:
            continue
        if budget_min and price < budget_min:
            continue

        # Check for promo
        promo_info = None
        if rt.promo_start_time and rt.promo_end_time and rt.promo_discount_percent > 0:
            ci_time = ci.time()
            start = rt.promo_start_time
            end = rt.promo_end_time
            is_promo = False
            if start <= end:
                if start <= ci_time <= end:
                    is_promo = True
            else:
                if ci_time >= start or ci_time <= end:
                    is_promo = True
            if is_promo:
                promo_info = {
                    "discount_percent": float(rt.promo_discount_percent),
                    "valid_time": f"{rt.promo_start_time.strftime('%H:%M')} - {rt.promo_end_time.strftime('%H:%M')}"
                }

        available_rooms.append({
            "room_id": room.id,
            "room_number": room.room_number,
            "room_type": rt.name,
            "room_type_id": rt.id,
            "floor": room.floor,
            "max_guests": rt.max_guests,
            "price_per_night": float(rt.price_per_night),
            "price_per_hour": float(rt.price_per_hour),
            "calculated_price": round(price, 0),
            "promo": promo_info,
            "notes": room.notes,
        })

    # Sort by price (ascending)
    available_rooms.sort(key=lambda x: x["calculated_price"])

    # Get recommended rooms (best value)
    recommended = available_rooms[:3] if len(available_rooms) >= 3 else available_rooms

    return JSONResponse({
        "available_rooms": available_rooms,
        "recommended_rooms": recommended,
        "total_available": len(available_rooms),
        "search_params": {
            "check_in": check_in,
            "check_out": check_out,
            "stay_type": stay_type,
            "guest_count": guest_count,
        }
    })


@router.get("/api/pms/availability-calendar", tags=["PMS"])
async def api_availability_calendar(
    request: Request,
    branch_id: Optional[int] = Query(None),
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """
    Lịch availability theo ngày - Calendar View
    """
    user = _require_login(request)
    is_admin = _is_admin(user)
    branch_code = _active_branch(request)

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=VN_TZ)
    except:
        raise HTTPException(status_code=400, detail="Ngày không hợp lệ")

    target_branch_id = branch_id
    if not target_branch_id and not is_admin:
        branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()
        if branch:
            target_branch_id = branch.id

    if not target_branch_id:
        raise HTTPException(status_code=400, detail="Cần chọn chi nhánh")

    rooms = (
        db.query(HotelRoom)
        .options(joinedload(HotelRoom.room_type_obj))
        .filter(HotelRoom.is_active == True, HotelRoom.branch_id == target_branch_id)
        .order_by(HotelRoom.floor, HotelRoom.room_number)
        .all()
    )

    calendar = []
    for day_offset in range(days):
        day = start + timedelta(days=day_offset)
        day_start = day.replace(hour=0, minute=0, second=0)
        day_end = day.replace(hour=23, minute=59, second=59)

        occupied = db.query(HotelStay.room_id).filter(
            HotelStay.branch_id == target_branch_id,
            HotelStay.status == HotelStayStatus.ACTIVE,
            or_(
                and_(HotelStay.check_in_at <= day_start, HotelStay.check_out_at >= day_start),
                and_(HotelStay.check_in_at <= day_end, HotelStay.check_out_at >= day_end),
                and_(HotelStay.check_in_at >= day_start, HotelStay.check_out_at <= day_end)
            )
        ).distinct().all()
        occupied_ids = set([o[0] for o in occupied])

        day_data = {
            "date": day.strftime("%Y-%m-%d"),
            "day_name": day.strftime("%A"),
            "total_rooms": len(rooms),
            "occupied": len(occupied_ids),
            "vacant": len(rooms) - len(occupied_ids),
            "occupancy_rate": round(len(occupied_ids) / len(rooms) * 100, 1) if rooms else 0,
        }
        calendar.append(day_data)

    return JSONResponse({
        "calendar": calendar,
        "branch_id": target_branch_id,
        "start_date": start_date,
    })