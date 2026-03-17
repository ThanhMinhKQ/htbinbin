# app/api/pms/pms_stays.py
"""
PMS Stays API - Stay management (detail, update, transfer)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload

from ...db.models import Branch, HotelRoom, HotelRoomType, HotelStay, HotelStayStatus, HotelGuest
from ...db.session import get_db
from .pms_helpers import (
    _require_login, _is_admin, _active_branch, _now_vn, _calc_price, 
    _get_occupied_rooms_for_dates, _room_to_dict, VN_TZ
)

router = APIRouter()


# ─────────────────────────── API: Stay Detail ───────────────────────────

@router.get("/api/pms/stays/{stay_id}", tags=["PMS"])
async def api_get_stay(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
):
    """Lấy chi tiết lưu trú"""
    user = _require_login(request)

    stay = (
        db.query(HotelStay)
        .options(
            joinedload(HotelStay.room).joinedload(HotelRoom.room_type_obj),
            joinedload(HotelStay.guests),
        )
        .filter(HotelStay.id == stay_id)
        .first()
    )
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")

    room = stay.room
    rt = room.room_type_obj if room else None

    return JSONResponse({
        "id": stay.id,
        "room_id": stay.room_id,
        "room_number": room.room_number if room else "—",
        "room_type": rt.name if rt else "—",
        "max_guests": rt.max_guests if rt else 2,
        "stay_type": stay.stay_type,
        "check_in_at": stay.check_in_at.isoformat() if stay.check_in_at else None,
        "check_out_at": stay.check_out_at.isoformat() if stay.check_out_at else None,
        "total_price": float(stay.total_price) if stay.total_price else 0,
        "deposit": float(stay.deposit) if stay.deposit else 0,
        "extra_charge": float(getattr(stay, 'extra_charge', 0) or 0),
        "notes": stay.notes,
        "status": stay.status.value if stay.status else "unknown",
        "price_per_night": float(rt.price_per_night) if rt and rt.price_per_night else 0,
        "price_per_hour": float(rt.price_per_hour) if rt and rt.price_per_hour else 0,
        "price_next_hour": float(rt.price_next_hour) if rt and rt.price_next_hour else 0,
        "min_hours": rt.min_hours if rt else 1,
        "require_invoice": stay.require_invoice if hasattr(stay, 'require_invoice') else False,
        "tax_code": stay.tax_code if hasattr(stay, 'tax_code') else None,
        "tax_contact": stay.tax_contact if hasattr(stay, 'tax_contact') else None,
        "guests": [
            {
                "id": g.id,
                "full_name": g.full_name,
                "cccd": g.cccd,
                "gender": g.gender,
                "phone": g.phone,
                "birth_date": g.birth_date.isoformat() if g.birth_date else None,
                "is_primary": g.is_primary,
                "vehicle": g.vehicle,
                "notes": g.notes,
                "address": g.address,
                "city": g.city,
                "district": g.district,
                "ward": g.ward,
                "id_expire": g.id_expire.isoformat() if g.id_expire else None,
                "tax_code": g.tax_code,
                "invoice_contact": g.invoice_contact,
            }
            for g in stay.guests
        ],
    })


@router.put("/api/pms/stays/{stay_id}", tags=["PMS"])
async def api_update_stay(
    request: Request,
    stay_id: int,
    check_in_at: Optional[str] = Form(None),
    check_out_at: Optional[str] = Form(None),
    stay_type: Optional[str] = Form(None),
    deposit: Optional[float] = Form(None),
    notes: Optional[str] = Form(None),
    tax_code: Optional[str] = Form(None),
    tax_contact: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Cập nhật thông tin lưu trú"""
    user = _require_login(request)

    stay = db.query(HotelStay).filter(HotelStay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")

    if stay.status != HotelStayStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Chỉ có thể cập nhật lưu trú đang hoạt động")

    if check_in_at:
        try:
            stay.check_in_at = datetime.fromisoformat(check_in_at).astimezone(VN_TZ)
        except:
            raise HTTPException(status_code=400, detail="Check-in datetime không hợp lệ")

    if check_out_at:
        try:
            stay.check_out_at = datetime.fromisoformat(check_out_at).astimezone(VN_TZ)
        except:
            raise HTTPException(status_code=400, detail="Check-out datetime không hợp lệ")

    if stay_type:
        stay.stay_type = stay_type

    if deposit is not None:
        stay.deposit = deposit

    if notes is not None:
        stay.notes = notes

    if tax_code is not None:
        stay.tax_code = tax_code

    if tax_contact is not None:
        stay.tax_contact = tax_contact

    db.commit()

    return JSONResponse({"message": "Cập nhật thành công", "stay_id": stay.id})


# ─────────────────────────── API: Stay Transfer ───────────────────────────

@router.put("/api/pms/stays/{stay_id}/transfer", tags=["PMS"])
async def api_transfer_stay(
    request: Request,
    stay_id: int,
    new_room_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Chuyển phòng"""
    user = _require_login(request)
    branch_name = _active_branch(request)

    # Get current stay
    stay = (
        db.query(HotelStay)
        .options(joinedload(HotelStay.room))
        .filter(HotelStay.id == stay_id, HotelStay.status == HotelStayStatus.ACTIVE)
        .first()
    )
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")

    # Get new room
    new_room = (
        db.query(HotelRoom)
        .options(joinedload(HotelRoom.room_type_obj))
        .filter(HotelRoom.id == new_room_id, HotelRoom.is_active == True)
        .first()
    )
    if not new_room:
        raise HTTPException(status_code=404, detail="Không tìm thấy phòng mới")

    # Check if new room is available
    occupied = _get_occupied_rooms_for_dates(
        db, stay.branch_id, stay.check_in_at, stay.check_out_at or _now_vn()
    )
    if new_room_id in occupied:
        raise HTTPException(status_code=400, detail="Phòng mới đã có người đặt")

    # Update stay
    old_room = stay.room
    stay.room_id = new_room_id

    db.commit()

    return JSONResponse({
        "message": f"Chuyển phòng thành công từ {old_room.room_number} sang {new_room.room_number}",
        "stay_id": stay.id,
        "old_room": old_room.room_number,
        "new_room": new_room.room_number,
    })


# ─────────────────────────── API: Guest Management ───────────────────────────

@router.post("/api/pms/stays/{stay_id}/guests", tags=["PMS"])
async def api_add_guest_to_stay(
    request: Request,
    stay_id: int,
    full_name: str = Form(...),
    cccd: str = Form(""),
    gender: str = Form(""),
    birth_date: str = Form(""),
    phone: str = Form(""),
    vehicle: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    """Thêm khách vào lưu trú"""
    user = _require_login(request)

    stay = (
        db.query(HotelStay)
        .options(joinedload(HotelStay.guests), joinedload(HotelStay.room).joinedload(HotelRoom.room_type_obj))
        .filter(HotelStay.id == stay_id, HotelStay.status == HotelStayStatus.ACTIVE)
        .first()
    )
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")

    # Check guest capacity
    rt = stay.room.room_type_obj if stay.room else None
    max_guests = rt.max_guests if rt else 2
    if len(stay.guests) >= max_guests:
        raise HTTPException(status_code=400, detail=f"Phòng tối đa {max_guests} khách")

    # Parse birth date
    birth = None
    if birth_date:
        try:
            birth = datetime.strptime(birth_date, "%Y-%m-%d").date()
        except:
            pass

    # Create guest
    guest = HotelGuest(
        stay_id=stay_id,
        full_name=full_name,
        cccd=cccd,
        gender=gender,
        birth_date=birth,
        phone=phone,
        vehicle=vehicle,
        notes=notes,
        is_primary=False,
    )
    db.add(guest)
    db.commit()

    return JSONResponse({
        "message": f"Thêm khách {full_name} thành công",
        "guest_id": guest.id,
    })


@router.delete("/api/pms/stays/{stay_id}/guests/{guest_id}", tags=["PMS"])
async def api_remove_guest_from_stay(
    request: Request,
    stay_id: int,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """Xóa khách khỏi lưu trú"""
    user = _require_login(request)

    guest = db.query(HotelGuest).filter(
        HotelGuest.id == guest_id,
        HotelGuest.stay_id == stay_id
    ).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    if guest.is_primary:
        raise HTTPException(status_code=400, detail="Không thể xóa khách chính")

    guest_name = guest.full_name
    db.delete(guest)
    db.commit()

    return JSONResponse({
        "message": f"Xóa khách {guest_name} thành công",
    })


# ─────────────────────────── API: Guest Search by CCCD ───────────────────────────

@router.get("/api/pms/guests/search", tags=["PMS"])
async def api_search_guest(
    request: Request,
    cccd: str = Query(..., description="Số giấy tờ cần tìm kiếm"),
    db: Session = Depends(get_db),
):
    """Tìm kiếm khách hàng theo số giấy tờ (CCCD/CMND/Passport)"""
    user = _require_login(request)
    
    if not cccd or len(cccd.strip()) < 3:
        return JSONResponse({"guests": [], "message": "Cần nhập ít nhất 3 ký tự để tìm kiếm"})
    
    guests = (
        db.query(HotelGuest)
        .filter(HotelGuest.cccd.ilike(f"%{cccd.strip()}%"))
        .order_by(HotelGuest.created_at.desc())
        .limit(10)
        .all()
    )
    
    return JSONResponse({
        "guests": [
            {
                "id": g.id,
                "full_name": g.full_name,
                "cccd": g.cccd,
                "gender": g.gender,
                "phone": g.phone,
                "birth_date": g.birth_date.isoformat() if g.birth_date else None,
                "address": g.address,
                "city": g.city,
                "district": g.district,
                "ward": g.ward,
                "vehicle": g.vehicle,
                "notes": g.notes,
                "tax_code": g.tax_code,
                "invoice_contact": g.invoice_contact,
                "last_stay": None
            }
            for g in guests
        ]
    })


@router.get("/api/pms/guests/check-cccd", tags=["PMS"])
async def api_check_cccd_exists(
    request: Request,
    cccd: str = Query(..., description="Số giấy tờ cần kiểm tra"),
    exclude_stay_id: Optional[int] = Query(None, description="ID stay để loại trừ (khi update)"),
    db: Session = Depends(get_db),
):
    """Kiểm tra xem số giấy tờ đã tồn tại chưa"""
    user = _require_login(request)
    
    if not cccd or len(cccd.strip()) < 3:
        return JSONResponse({"exists": False, "guest": None})
    
    query = db.query(HotelGuest).filter(HotelGuest.cccd.ilike(f"%{cccd.strip()}%"))
    
    if exclude_stay_id:
        query = query.filter(HotelGuest.stay_id != exclude_stay_id)
    
    guest = query.first()
    
    if guest:
        return JSONResponse({
            "exists": True,
            "guest": {
                "id": guest.id,
                "full_name": guest.full_name,
                "cccd": guest.cccd,
                "gender": guest.gender,
                "phone": guest.phone,
                "birth_date": guest.birth_date.isoformat() if guest.birth_date else None,
                "address": guest.address,
            }
        })
    
    return JSONResponse({"exists": False, "guest": None})


# ─────────────────────────── API: Get/Update/Delete Guest by ID ───────────────────────────

@router.get("/api/pms/guests/{guest_id}", tags=["PMS"])
async def api_get_guest(
    request: Request,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """Lấy thông tin khách"""
    user = _require_login(request)

    guest = db.query(HotelGuest).filter(HotelGuest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    return JSONResponse({
        "id": guest.id,
        "full_name": guest.full_name,
        "cccd": guest.cccd,
        "gender": guest.gender,
        "phone": guest.phone,
        "birth_date": guest.birth_date.isoformat() if guest.birth_date else None,
        "is_primary": guest.is_primary,
    })


@router.put("/api/pms/guests/{guest_id}", tags=["PMS"])
async def api_update_guest(
    request: Request,
    guest_id: int,
    full_name: Optional[str] = Form(None),
    cccd: Optional[str] = Form(None),
    gender: Optional[str] = Form(None),
    birth_date: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    vehicle: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Cập nhật thông tin khách"""
    user = _require_login(request)

    guest = db.query(HotelGuest).filter(HotelGuest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    if full_name:
        guest.full_name = full_name
    if cccd is not None:
        guest.cccd = cccd
    if gender is not None:
        guest.gender = gender
    if birth_date:
        try:
            guest.birth_date = datetime.strptime(birth_date, "%Y-%m-%d").date()
        except:
            pass
    if phone is not None:
        guest.phone = phone
    if vehicle is not None:
        guest.vehicle = vehicle
    if notes is not None:
        guest.notes = notes

    db.commit()

    return JSONResponse({"message": "Cập nhật thành công", "guest_id": guest.id})

