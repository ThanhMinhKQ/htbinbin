# app/api/pms/pms_admin.py
"""
PMS Admin API - CRUD for rooms, room types (admin only)
"""
from __future__ import annotations

from datetime import time as dt_time
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload

from ...db.models import Branch, HotelRoom, HotelRoomType, HotelStay, HotelStayStatus
from ...db.session import get_db
from .pms_helpers import _require_login, _is_admin, _active_branch

router = APIRouter()


# ─────────────────────────── API: Room Types ─────────────────────────────

@router.get("/api/pms/admin/room-types", tags=["PMS"])
async def api_admin_get_room_types(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Lấy danh sách loại phòng (admin)"""
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Không có quyền")

    q = db.query(HotelRoomType).filter(HotelRoomType.is_active == True)
    if branch_id:
        q = q.filter(HotelRoomType.branch_id == branch_id)

    types = q.order_by(HotelRoomType.sort_order, HotelRoomType.name).all()

    return JSONResponse([
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "price_per_night": float(t.price_per_night),
            "price_per_hour": float(t.price_per_hour),
            "price_next_hour": float(t.price_next_hour),
            "promo_start_time": t.promo_start_time.isoformat() if t.promo_start_time else None,
            "promo_end_time": t.promo_end_time.isoformat() if t.promo_end_time else None,
            "promo_discount_percent": float(t.promo_discount_percent),
            "min_hours": t.min_hours,
            "max_guests": t.max_guests,
            "branch_id": t.branch_id,
        }
        for t in types
    ])


@router.post("/api/pms/admin/room-types", tags=["PMS"])
async def api_admin_create_room_type(
    request: Request,
    name: str = Form(...),
    branch_id: int = Form(...),
    description: str = Form(""),
    price_per_night: float = Form(0),
    price_per_hour: float = Form(0),
    price_next_hour: float = Form(0),
    min_hours: int = Form(1),
    max_guests: int = Form(2),
    promo_start_time: Optional[str] = Form(None),
    promo_end_time: Optional[str] = Form(None),
    promo_discount_percent: float = Form(0),
    db: Session = Depends(get_db),
):
    """Tạo loại phòng mới (admin)"""
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Không có quyền")

    # Validate branch
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=400, detail="Không tìm thấy chi nhánh")

    # Check duplicate name
    existing = db.query(HotelRoomType).filter(
        HotelRoomType.branch_id == branch_id,
        HotelRoomType.name == name,
        HotelRoomType.is_active == True
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Tên loại phòng đã tồn tại")

    # Parse promo times
    promo_start = None
    promo_end = None
    if promo_start_time:
        try:
            promo_start = dt_time.fromisoformat(promo_start_time)
        except:
            pass
    if promo_end_time:
        try:
            promo_end = dt_time.fromisoformat(promo_end_time)
        except:
            pass

    rt = HotelRoomType(
        branch_id=branch_id,
        name=name,
        description=description,
        price_per_night=price_per_night,
        price_per_hour=price_per_hour,
        price_next_hour=price_next_hour,
        min_hours=min_hours,
        max_guests=max_guests,
        promo_start_time=promo_start,
        promo_end_time=promo_end,
        promo_discount_percent=promo_discount_percent,
    )
    db.add(rt)
    db.commit()

    return JSONResponse({
        "message": "Tạo loại phòng thành công",
        "room_type_id": rt.id,
    })


@router.put("/api/pms/admin/room-types/{type_id}", tags=["PMS"])
async def api_admin_update_room_type(
    request: Request,
    type_id: int,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    price_per_night: Optional[float] = Form(None),
    price_per_hour: Optional[float] = Form(None),
    price_next_hour: Optional[float] = Form(None),
    min_hours: Optional[int] = Form(None),
    max_guests: Optional[int] = Form(None),
    promo_start_time: Optional[str] = Form(None),
    promo_end_time: Optional[str] = Form(None),
    promo_discount_percent: Optional[float] = Form(None),
    db: Session = Depends(get_db),
):
    """Cập nhật loại phòng (admin)"""
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Không có quyền")

    rt = db.query(HotelRoomType).filter(HotelRoomType.id == type_id).first()
    if not rt:
        raise HTTPException(status_code=404, detail="Không tìm thấy loại phòng")

    if name is not None:
        rt.name = name
    if description is not None:
        rt.description = description
    if price_per_night is not None:
        rt.price_per_night = price_per_night
    if price_per_hour is not None:
        rt.price_per_hour = price_per_hour
    if price_next_hour is not None:
        rt.price_next_hour = price_next_hour
    if min_hours is not None:
        rt.min_hours = min_hours
    if max_guests is not None:
        rt.max_guests = max_guests

    if promo_start_time is not None:
        try:
            rt.promo_start_time = dt_time.fromisoformat(promo_start_time)
        except:
            rt.promo_start_time = None
    if promo_end_time is not None:
        try:
            rt.promo_end_time = dt_time.fromisoformat(promo_end_time)
        except:
            rt.promo_end_time = None
    if promo_discount_percent is not None:
        rt.promo_discount_percent = promo_discount_percent

    db.commit()

    return JSONResponse({"message": "Cập nhật thành công"})


@router.delete("/api/pms/admin/room-types/{type_id}", tags=["PMS"])
async def api_admin_delete_room_type(
    request: Request,
    type_id: int,
    db: Session = Depends(get_db),
):
    """Xóa loại phòng (admin)"""
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Không có quyền")

    rt = db.query(HotelRoomType).filter(HotelRoomType.id == type_id).first()
    if not rt:
        raise HTTPException(status_code=404, detail="Không tìm thấy loại phòng")

    # Check if any rooms use this type
    rooms = db.query(HotelRoom).filter(
        HotelRoom.room_type_id == type_id,
        HotelRoom.is_active == True
    ).count()
    if rooms > 0:
        raise HTTPException(status_code=400, detail=f"Có {rooms} phòng đang sử dụng loại phòng này")

    rt.is_active = False
    db.commit()

    return JSONResponse({"message": "Xóa loại phòng thành công"})


# ─────────────────────────── API: Rooms ─────────────────────────────

@router.get("/api/pms/admin/rooms", tags=["PMS"])
async def api_admin_get_rooms(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Lấy danh sách phòng (admin)"""
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Không có quyền")

    q = (
        db.query(HotelRoom)
        .options(joinedload(HotelRoom.room_type_obj))
        .filter(HotelRoom.is_active == True)
    )
    if branch_id:
        q = q.filter(HotelRoom.branch_id == branch_id)

    rooms = q.order_by(HotelRoom.floor, HotelRoom.sort_order, HotelRoom.room_number).all()

    return JSONResponse([
        {
            "id": r.id,
            "room_number": r.room_number,
            "floor": r.floor,
            "notes": r.notes,
            "room_type_id": r.room_type_id,
            "room_type_name": r.room_type_obj.name if r.room_type_obj else None,
            "price_per_night": float(r.room_type_obj.price_per_night) if r.room_type_obj and r.room_type_obj.price_per_night else 0,
            "price_per_hour": float(r.room_type_obj.price_per_hour) if r.room_type_obj and r.room_type_obj.price_per_hour else 0,
            "price_next_hour": float(r.room_type_obj.price_next_hour) if r.room_type_obj and r.room_type_obj.price_next_hour else 0,
            "branch_id": r.branch_id,
            "sort_order": r.sort_order,
        }
        for r in rooms
    ])


@router.post("/api/pms/admin/rooms", tags=["PMS"])
async def api_admin_create_room(
    request: Request,
    room_number: str = Form(...),
    branch_id: int = Form(...),
    room_type_id: Optional[int] = Form(None),
    floor: int = Form(...),
    notes: str = Form(""),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
):
    """Tạo phòng mới (admin)"""
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Không có quyền")

    # Validate room type if provided
    rt = None
    if room_type_id:
        rt = db.query(HotelRoomType).filter(HotelRoomType.id == room_type_id).first()
        if not rt:
            raise HTTPException(status_code=400, detail="Không tìm thấy loại phòng")

    # Check duplicate
    existing = db.query(HotelRoom).filter(
        HotelRoom.branch_id == branch_id,
        HotelRoom.room_number == room_number,
        HotelRoom.is_active == True
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Số phòng đã tồn tại")

    room = HotelRoom(
        branch_id=branch_id,
        room_type_id=room_type_id,
        room_number=room_number,
        floor=floor,
        notes=notes,
        sort_order=sort_order,
    )
    db.add(room)
    db.commit()

    return JSONResponse({
        "message": "Tạo phòng thành công",
        "room_id": room.id,
    })


@router.put("/api/pms/admin/rooms/{room_id}", tags=["PMS"])
async def api_admin_update_room(
    request: Request,
    room_id: int,
    room_number: Optional[str] = Form(None),
    room_type_id: Optional[int] = Form(None),
    floor: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    sort_order: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """Cập nhật phòng (admin)"""
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Không có quyền")

    room = db.query(HotelRoom).filter(HotelRoom.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Không tìm thấy phòng")

    if room_number is not None:
        room.room_number = room_number
    if room_type_id is not None:
        room.room_type_id = room_type_id
    if floor is not None:
        room.floor = floor
    if notes is not None:
        room.notes = notes
    if sort_order is not None:
        room.sort_order = sort_order

    db.commit()

    return JSONResponse({"message": "Cập nhật thành công"})


@router.delete("/api/pms/admin/rooms/{room_id}", tags=["PMS"])
async def api_admin_delete_room(
    request: Request,
    room_id: int,
    db: Session = Depends(get_db),
):
    """Xóa phòng (admin)"""
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Không có quyền")

    room = db.query(HotelRoom).filter(HotelRoom.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Không tìm thấy phòng")

    # Check if room has active stays
    active_stays = db.query(HotelStay).filter(
        HotelStay.room_id == room_id,
        HotelStay.status == HotelStayStatus.ACTIVE
    ).count()
    if active_stays > 0:
        raise HTTPException(status_code=400, detail="Phòng đang có khách ở")

    room.is_active = False
    db.commit()

    return JSONResponse({"message": "Xóa phòng thành công"})