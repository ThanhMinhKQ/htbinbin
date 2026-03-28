# app/api/pms/pms_stays.py
"""
PMS Stays API - Stay management (detail, update, transfer)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request, Query
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload

from ...db.models import Branch, Guest, HotelRoom, HotelRoomType, HotelStay, HotelStayStatus, HotelGuest
from ...db.session import get_db
from .pms_helpers import (
    _require_login, _is_admin, _active_branch, _now_vn, _calc_price,
    _get_occupied_rooms_for_dates, _room_to_dict, VN_TZ
)
from .vn_address import convert_old_to_new_sync
from .guest_activity import log_room_change, log_guest_added_to_stay

router = APIRouter()
logger = logging.getLogger(__name__)


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
        "vehicle": stay.vehicle if hasattr(stay, 'vehicle') else None,
        "guests": [
            {
                "id": g.id,
                "crm_guest_id": g.guest_id,
                "full_name": g.full_name,
                "cccd": g.cccd,
                "gender": g.gender,
                "phone": g.phone,
                "birth_date": g.birth_date.isoformat() if g.birth_date else None,
                "is_primary": g.is_primary,
                "notes": g.notes,
                "address": g.address,
                "address_type": g.address_type,
                "city": g.city,
                "district": g.district,
                "ward": g.ward,
                "old_city": getattr(g, 'old_city', None),
                "old_district": getattr(g, 'old_district', None),
                "old_ward": getattr(g, 'old_ward', None),
                "id_expire": g.id_expire.isoformat() if g.id_expire else None,
                "id_type": g.id_type,
                "tax_code": g.tax_code,
                "invoice_contact": g.invoice_contact,
                "nationality": g.nationality,
                "check_in_at": g.check_in_at.isoformat() if g.check_in_at else None,
                "check_out_at": g.check_out_at.isoformat() if g.check_out_at else None,
            }
            for g in stay.guests  # Trả tất cả guests
        ],
    })


class UpdateStayRequest(BaseModel):
    check_in_at: Optional[str] = None
    check_out_at: Optional[str] = None
    stay_type: Optional[str] = None
    deposit: Optional[float] = None
    notes: Optional[str] = None
    tax_code: Optional[str] = None
    tax_contact: Optional[str] = None


@router.put("/api/pms/stays/{stay_id}", tags=["PMS"])
async def api_update_stay(
    request: Request,
    stay_id: int,
    body: UpdateStayRequest = Body(...),
    db: Session = Depends(get_db),
):
    """Cập nhật thông tin lưu trú"""
    logger.info(f"[UPDATE_STAY] stay_id={stay_id}, check_in_at={body.check_in_at}, check_out_at={body.check_out_at}")
    
    user = _require_login(request)

    stay = db.query(HotelStay).filter(HotelStay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")

    if stay.status != HotelStayStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Chỉ có thể cập nhật lưu trú đang hoạt động")

    check_in_at = body.check_in_at
    check_out_at = body.check_out_at
    stay_type = body.stay_type
    deposit = body.deposit
    notes = body.notes
    tax_code = body.tax_code
    tax_contact = body.tax_contact

    # Parse check_in_at
    if check_in_at and check_in_at.strip():
        try:
            ci_str = check_in_at.strip()
            if len(ci_str) == 16:
                ci_str += ':00'
            stay.check_in_at = datetime.fromisoformat(ci_str).astimezone(VN_TZ)
        except ValueError as e:
            logger.error(f"[UPDATE_STAY] check_in_at parse error: {e}, value={check_in_at}")
            raise HTTPException(status_code=400, detail=f"Check-in datetime không hợp lệ: {check_in_at}")

    # Parse check_out_at
    if check_out_at and check_out_at.strip():
        try:
            co_str = check_out_at.strip()
            if len(co_str) == 16:
                co_str += ':00'
            stay.check_out_at = datetime.fromisoformat(co_str).astimezone(VN_TZ)
        except ValueError as e:
            logger.error(f"[UPDATE_STAY] check_out_at parse error: {e}, value={check_out_at}")
            raise HTTPException(status_code=400, detail=f"Check-out datetime không hợp lệ: {check_out_at}")

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

    if check_in_at or check_out_at or stay_type:
        stay.total_price = _calc_price(stay.stay_type, stay.room.room_type_obj, stay.check_in_at, stay.check_out_at)

    db.commit()

    return JSONResponse({
        "message": "Cập nhật thành công",
        "stay_id": stay.id,
        "total_price": float(stay.total_price),
        "check_out_at": stay.check_out_at.isoformat() if stay.check_out_at else None
    })


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
    old_room_number = old_room.room_number
    stay.room_id = new_room_id

    # ── Guest Activity Logging ─────────────────────────────────────────────────
    primary_guest = db.query(HotelGuest).filter(
        HotelGuest.stay_id == stay_id,
        HotelGuest.is_primary == True
    ).first()
    if primary_guest and primary_guest.guest_id:
        log_room_change(
            db, stay, primary_guest,
            from_room=old_room_number,
            to_room=new_room.room_number,
            actor_id=user.get("id")
        )

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
    notes: str = Form(""),
    id_type: str = Form("cccd"),
    id_expire: str = Form(""),
    address: str = Form(""),
    address_type: str = Form("new"),
    city: str = Form(""),
    district: str = Form(""),
    ward: str = Form(""),
    nationality: str = Form("VNM - Việt Nam"),
    # Old-address tracking fields (sent by frontend when address_type='old')
    old_city: str = Form(""),
    old_district: str = Form(""),
    old_ward: str = Form(""),
    # Converted new values from client-side (fallback to server-side conversion if empty)
    new_city: str = Form(""),
    new_ward: str = Form(""),
    tax_code: str = Form(""),
    invoice_contact: str = Form(""),
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

    # Ensure guest CCCD is not active in another room
    if cccd and len(cccd.strip()) >= 3:
        active_guest = (
            db.query(HotelGuest.cccd, HotelRoom.room_number)
            .join(HotelStay, HotelGuest.stay_id == HotelStay.id)
            .join(HotelRoom, HotelStay.room_id == HotelRoom.id)
            .filter(
                HotelGuest.cccd == cccd.strip(),
                HotelStay.status == HotelStayStatus.ACTIVE,
                HotelGuest.check_out_at == None
            ).first()
        )
        if active_guest:
            raise HTTPException(status_code=400, detail=f"Khách hàng có số giấy tờ {active_guest.cccd} đang lưu trú tại phòng {active_guest.room_number}. Không thể thêm.")

    # Parse birth date
    birth = None
    if birth_date:
        try:
            birth = datetime.strptime(birth_date, "%Y-%m-%d").date()
        except:
            pass

    # Parse id_expire
    id_exp = None
    if id_expire:
        try:
            id_exp = datetime.strptime(id_expire, "%Y-%m-%d").date()
        except:
            pass

    # ── Address resolution (same logic as checkin) ────────────────────────────
    _city_s = city.strip()
    _ward_s = ward.strip()
    _dist_s = district.strip()
    _addr_s = address.strip()

    old_city_v, old_district_v, old_ward_v = None, None, None
    new_city_v, new_ward_v = None, None
    new_district_v = None

    if address_type == "old" and _ward_s:
        old_city_v     = old_city.strip() or _city_s
        old_district_v = old_district.strip() or _dist_s
        old_ward_v     = old_ward.strip() or _ward_s
        # Prefer client-side conversion results; fallback to server-side
        if not new_city.strip() or not new_ward.strip():
            conv = convert_old_to_new_sync(old_ward_v, old_city_v, old_district_v)
        if new_city.strip():
            new_city_v = new_city.strip()
        else:
            new_city_v = conv.get("new_province", old_city_v)
        if new_ward.strip():
            new_ward_v = new_ward.strip()
        else:
            new_ward_v = conv.get("new_ward", old_ward_v)
    else:
        new_city_v     = _city_s
        new_ward_v     = _ward_s
        new_district_v = _dist_s

    # Resolve Guest master
    guest_master = None
    if cccd and len(cccd.strip()) >= 3:
        guest_master = db.query(Guest).filter(Guest.cccd == cccd.strip()).first()
        if guest_master:
            guest_master.full_name = full_name
            guest_master.phone = phone
            guest_master.gender = gender
            guest_master.nationality = nationality or guest_master.nationality
            # Lưu full formatted address (địa bàn mới)
            _parts = [p for p in [_addr_s, new_ward_v, new_district_v, new_city_v] if p]
            if _parts:
                guest_master.default_address = ", ".join(_parts)
            guest_master.last_seen_at = _now_vn()
        else:
            guest_master = Guest(
                full_name=full_name,
                cccd=cccd.strip(),
                phone=phone,
                gender=gender,
                nationality=nationality,
                default_address=", ".join([p for p in [_addr_s, new_ward_v, new_district_v, new_city_v] if p]) or None,
                first_seen_at=_now_vn(),
                last_seen_at=_now_vn(),
                total_stays=1,
            )
            db.add(guest_master)
        db.flush()

    # Create guest
    guest = HotelGuest(
        stay_id=stay_id,
        guest_id=guest_master.id if guest_master else None,
        full_name=full_name,
        cccd=cccd,
        gender=gender,
        birth_date=birth,
        phone=phone,
        notes=notes,
        id_type=id_type,
        id_expire=id_exp,
        address=_addr_s,
        address_type=address_type,
        city=new_city_v,
        district=new_district_v,
        ward=new_ward_v,
        nationality=nationality,
        old_city=old_city_v,
        old_district=old_district_v,
        old_ward=old_ward_v,
        tax_code=tax_code or None,
        invoice_contact=invoice_contact or None,
        is_primary=False,
        check_in_at=_now_vn(),
    )
    db.add(guest)
    db.flush()
    log_guest_added_to_stay(db, stay, guest, actor_id=user.get("id"))
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
    
    raw_guests = (
        db.query(HotelGuest)
        .filter(HotelGuest.cccd.ilike(f"%{cccd.strip()}%"))
        .order_by(HotelGuest.created_at.desc())
        .limit(50)
        .all()
    )
    
    unique_guests = {}
    for g in raw_guests:
        if g.cccd:
            key = g.cccd.strip().upper()
            if key not in unique_guests:
                unique_guests[key] = g
                if len(unique_guests) >= 10:
                    break
                    
    guests = list(unique_guests.values())
    
    return JSONResponse({
        "guests": [
            {
                "id": g.id,
                "full_name": g.full_name,
                "cccd": g.cccd,
                "gender": g.gender,
                "phone": g.phone,
                "birth_date": g.birth_date.isoformat() if g.birth_date else None,
                "id_expire": g.id_expire.isoformat() if g.id_expire else None,
                "address": g.address,
                "address_type": g.address_type if hasattr(g, 'address_type') else None,
                "city": g.city,
                "district": g.district,
                "ward": g.ward,
                "old_city": getattr(g, 'old_city', None),
                "old_district": getattr(g, 'old_district', None),
                "old_ward": getattr(g, 'old_ward', None),
                "notes": g.notes,
                "nationality": getattr(g, 'nationality', 'VNM - Việt Nam'),
                "tax_code": getattr(g, 'tax_code', None),
                "invoice_contact": getattr(g, 'invoice_contact', None),
                "id_type": g.id_type,
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
                "id_expire": guest.id_expire.isoformat() if guest.id_expire else None,
                "address": guest.address,
                "address_type": guest.address_type if hasattr(guest, 'address_type') else None,
                "city": guest.city,
                "district": guest.district,
                "ward": guest.ward,
                "old_city": getattr(guest, 'old_city', None),
                "old_district": getattr(guest, 'old_district', None),
                "old_ward": getattr(guest, 'old_ward', None),
                "notes": guest.notes,
                "nationality": getattr(guest, 'nationality', 'VNM - Việt Nam'),
                "tax_code": getattr(guest, 'tax_code', None),
                "invoice_contact": getattr(guest, 'invoice_contact', None),
                "id_type": guest.id_type,
            }
        })
    
    return JSONResponse({"exists": False, "guest": None})


@router.get("/api/pms/guests/check-active-cccd", tags=["PMS"])
async def api_check_active_cccd(
    request: Request,
    cccd: str = Query(..., description="Số giấy tờ cần kiểm tra"),
    exclude_stay_id: Optional[int] = Query(None, description="ID stay để loại trừ"),
    db: Session = Depends(get_db),
):
    """Kiểm tra xem số giấy tờ có đang ở phòng ACTIVE hay không"""
    user = _require_login(request)
    if not cccd or len(cccd.strip()) < 3:
        return JSONResponse({"is_active": False})
    
    cccd_stripped = cccd.strip()
    logger.info(f"[check-active-cccd] Searching for CCCD: {cccd_stripped}, exclude_stay_id: {exclude_stay_id}")
    
    # First check with exact match
    query = (
        db.query(HotelGuest.cccd, HotelRoom.room_number, HotelStay.status, HotelGuest.check_out_at)
        .join(HotelStay, HotelGuest.stay_id == HotelStay.id)
        .join(HotelRoom, HotelStay.room_id == HotelRoom.id)
        .filter(
            HotelGuest.cccd == cccd_stripped,
            HotelStay.status == HotelStayStatus.ACTIVE,
            HotelGuest.check_out_at == None
        )
    )
    if exclude_stay_id:
        query = query.filter(HotelStay.id != exclude_stay_id)
        
    active_guest = query.first()
    logger.info(f"[check-active-cccd] Exact match result: {active_guest}")
    if active_guest:
        return JSONResponse({
            "is_active": True,
            "room_number": active_guest.room_number,
            "cccd": active_guest.cccd
        })
    
    # Also check with LIKE for partial match
    query_like = (
        db.query(HotelGuest.cccd, HotelRoom.room_number, HotelStay.status, HotelGuest.check_out_at)
        .join(HotelStay, HotelGuest.stay_id == HotelStay.id)
        .join(HotelRoom, HotelStay.room_id == HotelRoom.id)
        .filter(
            HotelGuest.cccd.ilike(f"%{cccd_stripped}%"),
            HotelStay.status == HotelStayStatus.ACTIVE,
            HotelGuest.check_out_at == None
        )
    )
    if exclude_stay_id:
        query_like = query_like.filter(HotelStay.id != exclude_stay_id)
    
    active_guest_like = query_like.first()
    logger.info(f"[check-active-cccd] LIKE match result: {active_guest_like}")
    if active_guest_like:
        return JSONResponse({
            "is_active": True,
            "room_number": active_guest_like.room_number,
            "cccd": active_guest_like.cccd
        })
        
    return JSONResponse({"is_active": False})

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
    notes: Optional[str] = Form(None),
    id_type: Optional[str] = Form(None),
    id_expire: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    address_type: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    district: Optional[str] = Form(None),
    ward: Optional[str] = Form(None),
    old_city: Optional[str] = Form(None),
    old_district: Optional[str] = Form(None),
    old_ward: Optional[str] = Form(None),
    nationality: Optional[str] = Form(None),
    tax_code: Optional[str] = Form(None),
    invoice_contact: Optional[str] = Form(None),
    check_out_at: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Cập nhật thông tin khách hoặc checkout khách"""
    user = _require_login(request)

    # Support JSON body for check_out_at (from frontend checkout)
    body = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = await request.json()
        except:
            pass

    guest = db.query(HotelGuest).filter(HotelGuest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    if full_name is not None:
        guest.full_name = full_name
    if cccd is not None:
        new_cccd = cccd.strip()
        if new_cccd and len(new_cccd) >= 3 and new_cccd != (guest.cccd and guest.cccd.strip()):
            active_guest = (
                db.query(HotelGuest.cccd, HotelRoom.room_number)
                .join(HotelStay, HotelGuest.stay_id == HotelStay.id)
                .join(HotelRoom, HotelStay.room_id == HotelRoom.id)
                .filter(
                    HotelGuest.cccd == new_cccd,
                    HotelStay.status == HotelStayStatus.ACTIVE,
                    HotelGuest.check_out_at == None
                ).first()
            )
            if active_guest:
                raise HTTPException(status_code=400, detail=f"Khách hàng có số giấy tờ {active_guest.cccd} đang lưu trú tại phòng {active_guest.room_number}. Không thể cập nhật.")
        guest.cccd = cccd
    if gender is not None:
        guest.gender = gender
    if birth_date is not None:
        if birth_date:
            try:
                guest.birth_date = datetime.strptime(birth_date, "%Y-%m-%d").date()
            except:
                pass
        else:
            guest.birth_date = None
    if phone is not None:
        guest.phone = phone
    if notes is not None:
        guest.notes = notes
    if id_type is not None:
        guest.id_type = id_type
    if id_expire is not None:
        if id_expire:
            try:
                guest.id_expire = datetime.strptime(id_expire, "%Y-%m-%d").date()
            except:
                pass
        else:
            guest.id_expire = None
    if address is not None:
        guest.address = address
    if address_type is not None:
        guest.address_type = address_type
    if city is not None:
        guest.city = city
    if district is not None:
        guest.district = district
    if ward is not None:
        guest.ward = ward
    # old_* chỉ ghi khi mode='old' VÀ có giá trị; xóa khi mode='new'
    # (để DB luôn nhất quán: địa bàn nào thì lưu địa bàn đó)
    if address_type == "old":
        if old_city is not None and old_city:
            guest.old_city = old_city
        if old_district is not None and old_district:
            guest.old_district = old_district
        if old_ward is not None and old_ward:
            guest.old_ward = old_ward
    elif address_type == "new":
        guest.old_city = None
        guest.old_district = None
        guest.old_ward = None
    if nationality is not None:
        guest.nationality = nationality
    if tax_code is not None:
        guest.tax_code = tax_code if tax_code else None
    if invoice_contact is not None:
        guest.invoice_contact = invoice_contact if invoice_contact else None

    # Get check_out_at from JSON body or Form field
    final_check_out_at = body.get("check_out_at") if body else None
    if final_check_out_at is None and check_out_at is not None:
        final_check_out_at = check_out_at

    if final_check_out_at and str(final_check_out_at).strip():
        try:
            co_str = str(final_check_out_at).strip()
            if len(co_str) == 16:
                co_str += ':00'
            guest.check_out_at = datetime.fromisoformat(co_str).astimezone(VN_TZ)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Check-out datetime không hợp lệ: {final_check_out_at}")

    db.commit()

    return JSONResponse({"message": "Cập nhật thành công", "guest_id": guest.id})

