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

from ...db.models import Branch, Guest, HotelRoom, HotelRoomType, HotelStay, HotelStayStatus, HotelGuest
from ...db.session import get_db
from ...core.utils import VN_TZ
from .pms_helpers import (
    _require_login, _is_admin, _active_branch, _now_vn,
    _calc_price, _get_occupied_rooms_for_dates, _parse_birth
)
from .vn_address import convert_old_to_new_sync
from .guest_activity import log_checkin, log_deposit

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
    guest_nationality: str = Form(""),
    guest_id_expire: str = Form(""),
    vehicle: str = Form(""),
    city: str = Form(""),
    district: str = Form(""),
    ward: str = Form(""),
    address: str = Form(""),
    address_type: str = Form("new"),
    new_city: str = Form(""),    # Tỉnh/TP mới (đã convert client-side hoặc để trống)
    new_ward: str = Form(""),    # Phường/Xã mới (đã convert client-side hoặc để trống)
    old_city: str = Form(""),    # Tỉnh/TP cũ (khi address_type='old')
    old_district: str = Form(""), # Quận/Huyện cũ (khi address_type='old')
    old_ward: str = Form(""),    # Phường/Xã cũ (khi address_type='old')
    require_invoice: bool = Form(False),
    tax_code: str = Form(""),
    tax_contact: str = Form(""),
    guest_notes: str = Form(""),
    guest_id_type: str = Form("cccd"),
    extra_guests: str = Form(""),
    deposit_type: str = Form(None),
    deposit_meta: str = Form(None),
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

    # Gather all CCCDs to verify they are not currently staying in another room
    all_cccds = []
    if guest_cccd and len(guest_cccd.strip()) >= 3:
        all_cccds.append(guest_cccd.strip())
    
    if extra_guests:
        try:
            extra_list = json.loads(extra_guests)
            if isinstance(extra_list, list):
                for eg_data in extra_list:
                    eg_cccd = eg_data.get("cccd", "")
                    if eg_cccd and len(eg_cccd.strip()) >= 3:
                        all_cccds.append(eg_cccd.strip())
        except:
            pass
            
    if all_cccds:
        active_guests = (
            db.query(HotelGuest.cccd, HotelRoom.room_number)
            .join(HotelStay, HotelGuest.stay_id == HotelStay.id)
            .join(HotelRoom, HotelStay.room_id == HotelRoom.id)
            .filter(
                HotelGuest.cccd.in_(all_cccds),
                HotelStay.status == HotelStayStatus.ACTIVE,
                HotelGuest.check_out_at == None  # Only check guests who haven't checked out
            )
            .all()
        )
        if active_guests:
            messages = [f"{c} (Phòng {r})" for c, r in active_guests]
            raise HTTPException(status_code=400, detail=f"Khách hàng có số giấy tờ đang lưu trú tại phòng khác không thể check-in: {', '.join(messages)}")

        # Check for duplicates within the same check-in request
        unique_cccds = list(set(all_cccds))
        if len(unique_cccds) != len(all_cccds):
            from collections import Counter
            cccd_counts = Counter(all_cccds)
            duplicates = {c: count for c, count in cccd_counts.items() if count > 1}
            dup_messages = [f"{c} ({count} lần)" for c, count in duplicates.items()]
            raise HTTPException(status_code=400, detail=f"Số giấy tờ bị trùng lặp trong cùng lần nhận phòng: {', '.join(dup_messages)}. Vui lòng xóa bớt các khách trùng lặp.")

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
        vehicle=vehicle,  # Vehicle gắn với lượt lưu trú
        tax_code=tax_code if require_invoice else None,
        tax_contact=tax_contact if require_invoice else None,
        deposit_type=deposit_type,
        deposit_meta=json.loads(deposit_meta) if deposit_meta else None,
        status=HotelStayStatus.ACTIVE,
    )
    db.add(stay)
    db.flush()

    # Parse guest birth date (needed for both master update and guest creation)
    birth_date = _parse_birth(guest_birth)
    id_expire_date = _parse_birth(guest_id_expire)

    # ── Address resolution (MUST be before guest master to compute _addr_s) ──────
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
        if not new_city.strip() or not new_ward.strip():
            conv = convert_old_to_new_sync(old_ward_v, old_city_v, old_district_v)
        new_city_v = new_city.strip() if new_city.strip() else conv.get("new_province", old_city_v)
        new_ward_v = new_ward.strip() if new_ward.strip() else conv.get("new_ward", old_ward_v)
    else:
        new_city_v     = _city_s
        new_ward_v     = _ward_s
        new_district_v = _dist_s

    # ── RESOLVE GUEST (CRM Master Record) ────────────────────────────────────
    guest_master = None
    if guest_cccd and len(guest_cccd.strip()) >= 3:
        guest_master = db.query(Guest).filter(Guest.cccd == guest_cccd.strip()).first()
        if guest_master:
            # Update master record with latest info
            guest_master.full_name = guest_name
            guest_master.phone = guest_phone
            guest_master.gender = guest_gender
            guest_master.date_of_birth = birth_date
            guest_master.nationality = guest_nationality or guest_master.nationality
            # Lưu full formatted address (địa bàn mới) vào default_address
            _parts = [p for p in [_addr_s, new_ward_v, new_district_v, new_city_v] if p]
            guest_master.default_address = ", ".join(_parts) if _parts else guest_master.default_address
            guest_master.last_seen_at = _now_vn()
            guest_master.total_stays = (guest_master.total_stays or 0) + 1
        else:
            # Create new master guest
            guest_master = Guest(
                full_name=guest_name,
                cccd=guest_cccd.strip(),
                phone=guest_phone,
                gender=guest_gender,
                date_of_birth=birth_date,
                nationality=guest_nationality,
                first_seen_at=_now_vn(),
                last_seen_at=_now_vn(),
                total_stays=1,
            )
            db.add(guest_master)
        db.flush()

    primary_guest = HotelGuest(
        stay_id=stay.id,
        guest_id=guest_master.id if guest_master else None,  # Link to master Guest
        full_name=guest_name,
        cccd=guest_cccd,
        gender=guest_gender,
        birth_date=birth_date,
        phone=guest_phone,
        id_expire=id_expire_date,
        city=new_city_v,
        district=new_district_v,
        ward=new_ward_v,
        address=_addr_s,
        address_type=address_type,
        old_city=old_city_v,
        old_district=old_district_v,
        old_ward=old_ward_v,
        id_type=guest_id_type,
        notes=guest_notes,
        is_primary=True,
        check_in_at=ci,
        nationality=guest_nationality,
        tax_code=tax_code or None,
        invoice_contact=tax_contact or None,
    )
    db.add(primary_guest)
    db.flush()

    # ── EXTRA GUESTS ────────────────────────────────────────────────────────────
    extra_guest_names = []
    if extra_guests:
        try:
            extra_list = json.loads(extra_guests)
            if isinstance(extra_list, list):
                for eg_data in extra_list:
                    eg_birth = _parse_birth(eg_data.get("birth_date"))
                    eg_cccd = eg_data.get("cccd", "")
                    eg_city = eg_data.get("city", "")
                    eg_ward = eg_data.get("ward", "")
                    eg_dist = eg_data.get("district", "")
                    eg_addr_type = eg_data.get("address_type", "new")
                    eg_existing_id = eg_data.get("id")  # Check for existing guest

                    # Same conversion logic for extra guests
                    # Note: in old-mode, city/ward from form are OLD values;
                    # new_city/new_ward carry client-side conversion results
                    eg_old_city_v, eg_old_district_v, eg_old_ward_v = None, None, None
                    eg_new_city_v, eg_new_ward_v, eg_new_district_v = eg_city, eg_ward, eg_dist
                    eg_client_new_city = eg_data.get("new_city", "")
                    eg_client_new_ward = eg_data.get("new_ward", "")
                    if eg_addr_type == "old" and eg_ward:
                        eg_old_city_v = eg_data.get("old_city") or eg_city
                        eg_old_district_v = eg_data.get("old_district") or eg_dist
                        eg_old_ward_v = eg_data.get("old_ward") or eg_ward
                        if not eg_client_new_city or not eg_client_new_ward:
                            conv = convert_old_to_new_sync(eg_old_ward_v, eg_old_city_v, eg_old_district_v)
                        eg_new_city_v = eg_client_new_city or (conv.get("new_province", eg_old_city_v) if 'conv' in dir() else eg_old_city_v)
                        eg_new_ward_v = eg_client_new_ward or (conv.get("new_ward", eg_old_ward_v) if 'conv' in dir() else eg_old_ward_v)

                    # Resolve guest master for extra guest
                    eg_guest_master = None
                    if eg_cccd and len(eg_cccd.strip()) >= 3:
                        eg_guest_master = db.query(Guest).filter(Guest.cccd == eg_cccd.strip()).first()
                        if eg_guest_master:
                            eg_guest_master.full_name = eg_data.get("full_name", "")
                            eg_guest_master.phone = eg_data.get("phone", "")
                            eg_guest_master.gender = eg_data.get("gender", "")
                            eg_guest_master.date_of_birth = eg_birth
                            eg_guest_master.nationality = eg_data.get("nationality", "") or eg_guest_master.nationality
                            # Lưu full formatted address (địa bàn mới)
                            eg_addr = eg_data.get("address", "")
                            eg_parts = [p for p in [eg_addr, eg_new_ward_v, eg_new_district_v, eg_new_city_v] if p]
                            eg_guest_master.default_address = ", ".join(eg_parts) if eg_parts else eg_guest_master.default_address
                            eg_guest_master.last_seen_at = _now_vn()
                            eg_guest_master.total_stays = (eg_guest_master.total_stays or 0) + 1
                        else:
                            eg_guest_master = Guest(
                                full_name=eg_data.get("full_name", ""),
                                cccd=eg_cccd.strip(),
                                phone=eg_data.get("phone", ""),
                                gender=eg_data.get("gender", ""),
                                date_of_birth=eg_birth,
                                nationality=eg_data.get("nationality", ""),
                                first_seen_at=_now_vn(),
                                last_seen_at=_now_vn(),
                                total_stays=1,
                            )
                            db.add(eg_guest_master)
                        db.flush()

                    # Check if this extra guest already exists
                    if eg_existing_id:
                        existing_eg = db.query(HotelGuest).filter(HotelGuest.id == eg_existing_id).first()
                        if existing_eg:
                            existing_eg.stay_id = stay.id
                            existing_eg.guest_id = eg_guest_master.id if eg_guest_master else None
                            existing_eg.check_in_at = ci
                            existing_eg.check_out_at = None
                            existing_eg.is_primary = False
                            existing_eg.full_name = eg_data.get("full_name", "")
                            existing_eg.gender = eg_data.get("gender", "")
                            existing_eg.birth_date = eg_birth
                            existing_eg.phone = eg_data.get("phone", "")
                            existing_eg.id_type = eg_data.get("id_type", "cccd")
                            existing_eg.notes = eg_data.get("notes", "")
                            existing_eg.city = eg_new_city_v
                            existing_eg.district = eg_new_district_v
                            existing_eg.ward = eg_new_ward_v
                            existing_eg.address = eg_data.get("address", "")
                            existing_eg.address_type = eg_addr_type
                            existing_eg.old_city = eg_old_city_v
                            existing_eg.old_district = eg_old_district_v
                            existing_eg.old_ward = eg_old_ward_v
                            existing_eg.nationality = eg_data.get("nationality", "VNM - Việt Nam")
                            existing_eg.tax_code = eg_data.get("tax_code") or None
                            existing_eg.invoice_contact = eg_data.get("invoice_contact") or None
                            continue  # Skip creating new guest

                    eg = HotelGuest(
                        stay_id=stay.id,
                        guest_id=eg_guest_master.id if eg_guest_master else None,  # Link to master Guest
                        full_name=eg_data.get("full_name", ""),
                        cccd=eg_cccd,
                        gender=eg_data.get("gender", ""),
                        birth_date=eg_birth,
                        phone=eg_data.get("phone", ""),
                        id_type=eg_data.get("id_type", "cccd"),
                        notes=eg_data.get("notes", ""),
                        city=eg_new_city_v,
                        district=eg_new_district_v,
                        ward=eg_new_ward_v,
                        address=eg_data.get("address", ""),
                        address_type=eg_addr_type,
                        old_city=eg_old_city_v,
                        old_district=eg_old_district_v,
                        old_ward=eg_old_ward_v,
                        is_primary=False,
                        check_in_at=ci,
                        nationality=eg_data.get("nationality", "VNM - Việt Nam"),
                        tax_code=eg_data.get("tax_code") or None,
                        invoice_contact=eg_data.get("invoice_contact") or None,
                    )
                    db.add(eg)
                    db.flush()
                    # Collect extra guest names for activity log
                    eg_name = eg_data.get("full_name", "")
                    if eg_name:
                        extra_guest_names.append(eg_name)

        except:
            pass  # Ignore invalid JSON

    db.commit()

    # ── Guest Activity Logging ────────────────────────────
    if primary_guest and primary_guest.id:
        total_guests = 1 + len(extra_guest_names)
        log_checkin(
            db, stay, primary_guest,
            actor_id=user.get("id"),
            guest_count=total_guests,
            extra_guest_names=extra_guest_names,
        )
        if deposit and deposit > 0:
            log_deposit(db, stay, primary_guest, deposit,
                       deposit_type=deposit_type or "cash",
                       actor_id=user.get("id"))

    return JSONResponse({
        "message": f"Check-in thành công! Phòng {room.room_number}",
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