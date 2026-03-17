# app/api/pms/pms_checkin.py
"""
PMS Check-in API - Handle guest check-in
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload

from ...db.models import Branch, HotelRoom, HotelRoomType, HotelStay, HotelStayStatus, HotelGuest
from ...db.session import get_db
from ...core.utils import VN_TZ
from .pms_helpers import (
    _require_login, _is_admin, _active_branch, _now_vn, 
    _calc_price, _get_occupied_rooms_for_dates, _parse_birth
)

router = APIRouter()


# ─────────────────────────── API: Check-in ─────────────────────────────

@router.post("/api/pms/checkin", tags=["PMS"])
async def api_checkin(
    request: Request,
    room_id: int = Form(...),
    stay_type: str = Form("night"),
    check_in_at: str = Form(...),
    check_out_at: str = Form(""),
    deposit: float = Form(0),
    notes: str = Form(""),
    guest_name: str = Form(...),
    guest_cccd: str = Form(...),
    guest_gender: str = Form(""),
    guest_birth: str = Form(""),
    guest_phone: str = Form(""),
    guest_id_expire: str = Form(""),
    vehicle: str = Form(""),
    city: str = Form(""),
    district: str = Form(""),
    ward: str = Form(""),
    address: str = Form(""),
    address_type: str = Form("new"),
    require_invoice: bool = Form(False),
    tax_code: str = Form(""),
    tax_contact: str = Form(""),
    guest_notes: str = Form(""),
    extra_guests: str = Form(""),
    guest_id: Optional[int] = Form(None),  # For updating existing guest
    db: Session = Depends(get_db),
):
    """
    Check-in: Tạo mới stay + guest(s)
    """
    user = _require_login(request)
    branch_name = _active_branch(request)
    is_admin = _is_admin(user)

    # Get room first
    room = (
        db.query(HotelRoom)
        .options(joinedload(HotelRoom.room_type_obj))
        .filter(HotelRoom.id == room_id, HotelRoom.is_active == True)
        .first()
    )
    if not room:
        raise HTTPException(status_code=400, detail="Không tìm thấy phòng")

    # Get branch from room instead of session
    branch = db.query(Branch).filter(Branch.id == room.branch_id).first()
    if not branch:
        raise HTTPException(status_code=400, detail="Không tìm thấy chi nhánh cho phòng này")

    rt = room.room_type_obj
    if not rt:
        raise HTTPException(status_code=400, detail="Phòng chưa có loại phòng")

    # Parse datetime
    try:
        ci = datetime.fromisoformat(check_in_at).astimezone(VN_TZ)
    except:
        raise HTTPException(status_code=400, detail="Check-in datetime không hợp lệ")

    co = None
    if check_out_at:
        try:
            co = datetime.fromisoformat(check_out_at).astimezone(VN_TZ)
            if co <= ci:
                raise HTTPException(status_code=400, detail="Check-out phải sau check-in")
        except HTTPException:
            raise
        except:
            raise HTTPException(status_code=400, detail="Check-out datetime không hợp lệ")
    else:
        if stay_type == "night":
            co = ci.replace(hour=12, minute=0, second=0)  # Default 12:00 next day

    # Check if room is occupied
    if co:
        occupied = _get_occupied_rooms_for_dates(db, branch.id, ci, co)
        if room.id in occupied:
            raise HTTPException(status_code=400, detail="Phòng đã có người đặt trong thời gian này")

    # Calculate price
    total_price = _calc_price(stay_type, rt, ci, co or ci)

    # Create stay
    stay = HotelStay(
        branch_id=branch.id,
        room_id=room.id,
        stay_type=stay_type,
        check_in_at=ci,
        check_out_at=co,
        total_price=total_price,
        deposit=deposit,
        notes=notes,
        require_invoice=require_invoice,
        tax_code=tax_code if require_invoice else None,
        tax_contact=tax_contact if require_invoice else None,
        status=HotelStayStatus.ACTIVE,
    )
    db.add(stay)
    db.flush()

    # Create or update primary guest
    birth_date = _parse_birth(guest_birth)
    
    if guest_id:
        # Update existing guest
        primary_guest = db.query(HotelGuest).filter(HotelGuest.id == guest_id).first()
        if primary_guest:
            primary_guest.full_name = guest_name
            primary_guest.cccd = guest_cccd
            primary_guest.gender = guest_gender
            primary_guest.birth_date = birth_date
            primary_guest.phone = guest_phone
            primary_guest.id_expire = _parse_birth(guest_id_expire)
            primary_guest.vehicle = vehicle
            primary_guest.city = city
            primary_guest.district = district
            primary_guest.ward = ward
            primary_guest.address = address
            primary_guest.address_type = address_type
            primary_guest.notes = guest_notes
            primary_guest.tax_code = tax_code if require_invoice else None
            primary_guest.invoice_contact = tax_contact if require_invoice else None
            primary_guest.stay_id = stay.id  # Link to new stay
    else:
        # Create new guest
        primary_guest = HotelGuest(
            stay_id=stay.id,
            full_name=guest_name,
            cccd=guest_cccd,
            gender=guest_gender,
            birth_date=birth_date,
            phone=guest_phone,
            id_expire=_parse_birth(guest_id_expire),
            vehicle=vehicle,
            city=city,
            district=district,
            ward=ward,
            address=address,
            address_type=address_type,
            notes=guest_notes,
            is_primary=True,
            tax_code=tax_code if require_invoice else None,
            invoice_contact=tax_contact if require_invoice else None,
        )
        db.add(primary_guest)

    # Create extra guests
    if extra_guests:
        try:
            extra_list = json.loads(extra_guests)
            if isinstance(extra_list, list):
                for eg_data in extra_list:
                    eg_birth = _parse_birth(eg_data.get("birth_date"))
                    eg = HotelGuest(
                        stay_id=stay.id,
                        full_name=eg_data.get("full_name", ""),
                        cccd=eg_data.get("cccd", ""),
                        gender=eg_data.get("gender", ""),
                        birth_date=eg_birth,
                        phone=eg_data.get("phone", ""),
                        vehicle=eg_data.get("vehicle", ""),
                        notes=eg_data.get("notes", ""),
                        is_primary=False,
                    )
                    db.add(eg)
        except:
            pass  # Ignore invalid JSON

    db.commit()

    msg_prefix = "Cập nhật" if guest_id else "Check-in"
    return JSONResponse({
        "message": f"{msg_prefix} thành công! Phòng {room.room_number}",
        "stay_id": stay.id,
        "room_number": room.room_number,
        "check_in_at": ci.isoformat(),
        "check_out_at": co.isoformat() if co else None,
        "total_price": total_price,
        "deposit": deposit,
    })


@router.get("/api/pms/checkin-info/{room_id}", tags=["PMS"])
async def api_checkin_info(
    request: Request,
    room_id: int,
    db: Session = Depends(get_db),
):
    """Lấy thông tin phòng cho check-in"""
    user = _require_login(request)

    room = (
        db.query(HotelRoom)
        .options(joinedload(HotelRoom.room_type_obj))
        .filter(HotelRoom.id == room_id, HotelRoom.is_active == True)
        .first()
    )
    if not room:
        raise HTTPException(status_code=404, detail="Không tìm thấy phòng")

    rt = room.room_type_obj
    if not rt:
        raise HTTPException(status_code=400, detail="Phòng chưa có loại phòng")

    return JSONResponse({
        "room_id": room.id,
        "room_number": room.room_number,
        "room_type": rt.name,
        "room_type_id": rt.id,
        "max_guests": rt.max_guests,
        "price_per_night": float(rt.price_per_night),
        "price_per_hour": float(rt.price_per_hour),
        "price_next_hour": float(rt.price_next_hour),
        "min_hours": rt.min_hours,
        "promo": {
            "start_time": rt.promo_start_time.isoformat() if rt.promo_start_time else None,
            "end_time": rt.promo_end_time.isoformat() if rt.promo_end_time else None,
            "discount_percent": float(rt.promo_discount_percent),
        } if rt.promo_discount_percent > 0 else None,
    })