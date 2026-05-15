# app/api/pms/pms_checkin.py
"""
PMS Check-in API - Handle guest check-in
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload

from ...db.models import (
    Branch, Guest, HotelRoom, HotelStay, HotelStayStatus, HotelGuest,
    HotelRoomType, PaymentMethod, FolioTransactionType,
    ShiftReportTransaction, ShiftReportStatus, ShiftPaymentMethod,
    Warehouse, InventoryLevel, StockMovement, TransactionTypeWMS,
    BookingStatus,
)
from ...db.session import get_db
from ...core.utils import VN_TZ
from ...core.config import logger
from ...services.folio_service import (
    create_folio,
    create_payment_with_transaction,
    create_charge_transaction,
)
from ...services.pricing_service import calculate_full_charge, get_engine_config
from .pms_helpers import (
    _require_login, _now_vn,
    _get_occupied_rooms_for_dates, _parse_birth,
)
from .vn_address import convert_old_to_new_sync
from .identity_parser import calc_expiry
from .guest_activity import log_checkin, log_deposit
from ...services.guest_crm_service import get_guest_risk_flags
from ...services.booking_service import BookingService
from ...services.room_inventory_service import InventoryService

router = APIRouter()


def _calc_cccd_expire_date_from_birth(birth_date):
    if not birth_date:
        return None
    expiry = calc_expiry(birth_date.strftime("%d/%m/%Y"))
    if not expiry or expiry == "Không thời hạn":
        return None
    try:
        return datetime.strptime(expiry, "%d/%m/%Y").date()
    except ValueError:
        return None


# ─────────────────────────── Helper: Ghi nhận Shift Report ─────────────────────

def _folio_payment_method(value: Optional[str]) -> PaymentMethod:
    method_map = {
        "CASH": PaymentMethod.CASH,
        "Chi nhánh": PaymentMethod.BRANCH,
        "BRANCH": PaymentMethod.BRANCH,
        "BRANCH_ACCOUNT": PaymentMethod.BRANCH,
        "CARD": PaymentMethod.CARD,
        "Quẹt thẻ": PaymentMethod.CARD,
        "VNPAY": PaymentMethod.CARD,
        "BANK_TRANSFER": PaymentMethod.BRANCH,
        "Chuyển khoản": PaymentMethod.BRANCH,
        "MOMO": PaymentMethod.BRANCH,
        "COMPANY": PaymentMethod.COMPANY,
        "Công ty": PaymentMethod.COMPANY,
        "OTA": PaymentMethod.OTA,
        "UNC": PaymentMethod.COMPANY,
    }
    if value in method_map:
        return method_map[value]
    try:
        return PaymentMethod(value or "CASH")
    except Exception:
        return PaymentMethod.CASH

def _log_deposit_to_shift_report(
    db: Session,
    branch_id: int,
    user_id: int,
    stay_id: int,
    folio_id: int,
    folio_transaction_id: int,
    amount: float,
    payment_method: str,
    deposit_type: str,
    room_number: str,
):
    """Ghi nhận tiền đặt cọc vào ShiftReportTransaction."""
    from ...services.shift_report_service import (
        _generate_shift_code,
        build_shift_transaction_info,
        normalize_shift_payment_method,
        shift_transaction_type_for_method,
    )

    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    branch_code = branch.branch_code if branch else "XX"

    # Dùng helper chuẩn hoá duy nhất: method ưu tiên `deposit_type` (chi tiết
    # phương thức khách chọn ở UI), fallback về `payment_method`.
    pm_enum = normalize_shift_payment_method(deposit_type or payment_method)
    tx_type = shift_transaction_type_for_method(pm_enum)

    description = build_shift_transaction_info(
        "Cọc",
        room_number=room_number,
        amount=int(amount),
        method=pm_enum,
    )

    new_tx = ShiftReportTransaction(
        transaction_code=_generate_shift_code(db, branch_code or "XX"),
        transaction_type=tx_type,
        amount=int(amount),
        room_number=room_number,
        transaction_info=description,
        branch_id=branch_id,
        recorder_id=user_id,
        created_datetime=datetime.now(VN_TZ),
        status=ShiftReportStatus.PENDING,
        stay_id=stay_id,
        folio_id=folio_id,
        folio_transaction_id=folio_transaction_id,
        payment_method=pm_enum,
        is_auto_posted=True,
    )
    db.add(new_tx)
    logger.info(
        f"[ShiftReport] Auto-posted deposit: {amount} for stay {stay_id}, "
        f"room {room_number}, method {pm_enum.value}, tx_type {tx_type.value}"
    )


# ─────────────────────────── API: Check-in ─────────────────────────────

@router.post("/api/pms/checkin", tags=["PMS"])
def api_checkin(
    request: Request,
    room_id: int = Form(...),
    stay_type: str = Form("AUTO"),
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
    risk_confirmed: bool = Form(False),
    extra_guests: str = Form(""),
    services: str = Form(""), # JSON list of {name, price, qty}
    deposit_type: str = Form(None),
    deposit_meta: str = Form(None),
    booking_id: Optional[int] = Form(None),
    ota_actual_total: Optional[float] = Form(None),
    pms_reference_total: Optional[float] = Form(None),
    ota_channel: str = Form(""),
    db: Session = Depends(get_db),
):
    """
    Check-in: Tạo mới stay + guest(s)
    """
    user = _require_login(request)

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

    booking = None
    booking_deposit_from_reservation = False
    if booking_id:
        from ...db.models import Booking
        booking = db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise HTTPException(status_code=404, detail="Không tìm thấy đặt phòng")
        if booking.reservation_status != "CONFIRMED":
            raise HTTPException(status_code=400, detail="Chỉ đặt phòng đã xác nhận mới được nhận phòng")
        if booking.branch_id and booking.branch_id != branch.id:
            raise HTTPException(status_code=400, detail="Phòng nhận không thuộc chi nhánh của đặt phòng")
        room_type_id = (booking.raw_data or {}).get("room_type_id")
        if room_type_id and room.room_type_id != int(room_type_id):
            raise HTTPException(status_code=400, detail="Phòng nhận không đúng loại phòng đã đặt")
        if booking.deposit_amount and booking.deposit_amount > 0:
            raw = dict(booking.raw_data or {})
            booking_deposit_from_reservation = True
            deposit = float(booking.deposit_amount or 0)
            deposit_type = deposit_type or booking.payment_method or raw.get("deposit_type") or "Chi nhánh"
            if not deposit_meta and raw.get("deposit_meta"):
                deposit_meta = json.dumps(raw.get("deposit_meta"))
            BookingService(db)._post_booking_deposit_once(booking, user.get("id"))
            raw = dict(booking.raw_data or {})
            booking.raw_data = raw
        if booking.booking_type == "OTA" and not ota_actual_total:
            ota_actual_total = float(booking.total_price or 0)
        if booking.booking_type == "OTA" and not ota_channel:
            ota_channel = booking.booking_source or (booking.raw_data or {}).get("ota_channel") or ""

    # Parse datetime
    try:
        ci = VN_TZ.localize(datetime.fromisoformat(check_in_at))
    except Exception:
        raise HTTPException(status_code=400, detail="Check-in datetime không hợp lệ")

    co = None
    if check_out_at:
        try:
            co = VN_TZ.localize(datetime.fromisoformat(check_out_at))
            if co <= ci:
                raise HTTPException(status_code=400, detail="Check-out phải sau check-in")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail="Check-out datetime không hợp lệ")

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

        existing_guest_ids = [
            row[0] for row in db.query(Guest.id).filter(
                Guest.cccd.in_(all_cccds),
                Guest.deleted_at.is_(None),
            ).all()
        ]
        if existing_guest_ids and not risk_confirmed:
            warnings = []
            risk_payloads = []
            for guest_id in existing_guest_ids:
                risk_flags = get_guest_risk_flags(db, guest_id)
                if risk_flags["is_blacklisted"] or risk_flags["has_unpaid_debt"]:
                    risk_payloads.append(risk_flags)
                    warnings.extend(risk_flags.get("warnings") or [])
            if risk_payloads:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "GUEST_RISK_CONFIRM_REQUIRED",
                        "message": "Khách có cảnh báo CRM. Cần xác nhận trước khi nhận phòng.",
                        "risk_flags": {
                            "is_blacklisted": any(r["is_blacklisted"] for r in risk_payloads),
                            "has_unpaid_debt": any(r["has_unpaid_debt"] for r in risk_payloads),
                            "unpaid_debt_amount": float(sum(Decimal(str(r["unpaid_debt_amount"])) for r in risk_payloads)),
                            "warnings": warnings,
                            "guests": risk_payloads,
                        },
                    },
                )

    # Create stay
    stay = HotelStay(
        branch_id=branch.id,
        room_id=room.id,
        stay_type=stay_type,
        check_in_at=ci,
        check_out_at=co,
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

    # ── Lock pricing mode at check-in ─────────────────────────────────────────
    # Compute ACTUAL pricing mode that will be charged.
    # - Không có checkout time → phòng giờ (HOURLY)
    # - Có checkout time → gọi engine so sánh HOURLY vs DAILY, ghi mode thực tế
    if co:
        _total, _bd = calculate_full_charge(stay_type, rt, ci, co)
        _mode = None
        for _item in _bd:
            if _item.get("mode") == "DAILY":
                _mode = "NIGHT"; break
            elif _item.get("mode") == "HOURLY":
                _mode = "HOUR"; break
        stay.pricing_mode_initial = _mode or "NIGHT"
    else:
        stay.pricing_mode_initial = "HOURLY"
    stay.pricing_locked = True
    if ota_actual_total and ota_actual_total > 0:
        stay.total_price = Decimal(str(ota_actual_total))
        stay.notes = (notes or "")
        stay.pricing_mode_initial = "OTA_MANUAL"

    # Parse guest birth date (needed for both master update and guest creation)
    birth_date = _parse_birth(guest_birth)
    id_expire_date = _parse_birth(guest_id_expire)
    if (guest_id_type or "").lower() == "cccd" and birth_date and not id_expire_date:
        id_expire_date = _calc_cccd_expire_date_from_birth(birth_date)

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
            risk_flags = get_guest_risk_flags(db, guest_master.id)
            if (risk_flags["is_blacklisted"] or risk_flags["has_unpaid_debt"]) and not risk_confirmed:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "GUEST_RISK_CONFIRM_REQUIRED",
                        "message": "Khách có cảnh báo CRM. Cần xác nhận trước khi nhận phòng.",
                        "risk_flags": risk_flags,
                    },
                )
        if guest_master:
            # Update master record with latest info
            guest_master.full_name = guest_name
            guest_master.phone = guest_phone
            guest_master.gender = guest_gender
            guest_master.date_of_birth = birth_date
            guest_master.nationality = guest_nationality or guest_master.nationality
            guest_master.id_expire = id_expire_date  # always update with latest from this stay
            guest_master.updated_by = user.get("id")
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
                id_expire=id_expire_date,
                nationality=guest_nationality,
                default_address=", ".join([p for p in [_addr_s, new_ward_v, new_district_v, new_city_v] if p]) or None,
                first_seen_at=_now_vn(),
                last_seen_at=_now_vn(),
                total_stays=1,
                created_by=user.get("id"),
                updated_by=user.get("id"),
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
        created_by=user.get("id"),
    )
    db.add(primary_guest)
    db.flush()

    # ── EXTRA GUESTS ────────────────────────────────────────────────────────────
    extra_guest_names = []
    _extra_hotel_guests = []  # Collect eg objects for timeline logging
    if extra_guests:
        try:
            extra_list = json.loads(extra_guests)
            if isinstance(extra_list, list):
                # Batch pre-fetch Guest masters: 1 query thay vì N query trong loop
                _eg_cccds = [eg.get("cccd", "").strip() for eg in extra_list if eg.get("cccd", "").strip() and len(eg.get("cccd", "").strip()) >= 3]
                _eg_masters_map = {}
                if _eg_cccds:
                    _eg_masters = db.query(Guest).filter(Guest.cccd.in_(_eg_cccds), Guest.deleted_at.is_(None)).all()
                    _eg_masters_map = {g.cccd: g for g in _eg_masters}

                # Batch pre-fetch existing HotelGuests: 1 query thay vì N
                _eg_existing_ids = [eg.get("id") for eg in extra_list if eg.get("id")]
                _eg_existing_map = {}
                if _eg_existing_ids:
                    _eg_existing_rows = db.query(HotelGuest).filter(HotelGuest.id.in_(_eg_existing_ids)).all()
                    _eg_existing_map = {g.id: g for g in _eg_existing_rows}

                for eg_data in extra_list:
                    eg_birth = _parse_birth(eg_data.get("birth_date"))
                    eg_id_type = (eg_data.get("id_type", "cccd") or "cccd").lower()
                    eg_id_expire = _parse_birth(eg_data.get("id_expire"))
                    if eg_id_type == "cccd" and eg_birth and not eg_id_expire:
                        eg_id_expire = _calc_cccd_expire_date_from_birth(eg_birth)
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
                        eg_guest_master = _eg_masters_map.get(eg_cccd.strip())
                        if eg_guest_master:
                            eg_guest_master.full_name = eg_data.get("full_name", "")
                            eg_guest_master.phone = eg_data.get("phone", "")
                            eg_guest_master.gender = eg_data.get("gender", "")
                            eg_guest_master.date_of_birth = eg_birth
                            eg_guest_master.nationality = eg_data.get("nationality", "") or eg_guest_master.nationality
                            eg_guest_master.id_expire = eg_id_expire
                            eg_guest_master.updated_by = user.get("id")
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
                                id_expire=eg_id_expire,
                                nationality=eg_data.get("nationality", ""),
                                default_address=", ".join([p for p in [eg_data.get("address", ""), eg_new_ward_v, eg_new_district_v, eg_new_city_v] if p]) or None,
                                first_seen_at=_now_vn(),
                                last_seen_at=_now_vn(),
                                total_stays=1,
                                created_by=user.get("id"),
                                updated_by=user.get("id"),
                            )
                            db.add(eg_guest_master)
                        db.flush()

                    # Check if this extra guest already exists
                    if eg_existing_id:
                        existing_eg = _eg_existing_map.get(eg_existing_id)
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
                            existing_eg.id_type = eg_id_type
                            existing_eg.id_expire = eg_id_expire
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
                            if existing_eg.guest_id:
                                _extra_hotel_guests.append(existing_eg)
                            continue  # Skip creating new guest

                    eg = HotelGuest(
                        stay_id=stay.id,
                        guest_id=eg_guest_master.id if eg_guest_master else None,  # Link to master Guest
                        full_name=eg_data.get("full_name", ""),
                        cccd=eg_cccd,
                        gender=eg_data.get("gender", ""),
                        birth_date=eg_birth,
                        phone=eg_data.get("phone", ""),
                        id_type=eg_id_type,
                        id_expire=eg_id_expire,
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
                        created_by=user.get("id"),
                    )
                    db.add(eg)
                    # Collect extra guest names for activity log
                    eg_name = eg_data.get("full_name", "")
                    if eg_name:
                        extra_guest_names.append(eg_name)
                    # Collect for timeline logging
                    _extra_hotel_guests.append(eg)

        except:
            pass  # Ignore invalid JSON

    # Flush tất cả extra guests 1 lần (thay vì flush từng guest trong loop)
    db.flush()

    # ── Create Folio (no room charge at check-in — settled at checkout) ─────────
    folio = create_folio(db=db, stay=stay)
    if ota_actual_total and ota_actual_total > 0:
        raw_meta = {
            "source": "ota_booking_checkin",
            "pricing_mode": "manual_channel_total",
            "ota_actual_total": float(ota_actual_total),
            "pms_reference_total": float(pms_reference_total or 0),
            "ota_price_delta": float(ota_actual_total) - float(pms_reference_total or 0),
            "ota_channel": ota_channel,
            "booking_id": booking.id if booking else None,
        }
        folio.notes = json.dumps(raw_meta, ensure_ascii=False)

    # ── Process extra services at check-in ────────────────────────────────────
    if services:
        try:
            svc_list = json.loads(services)
            if isinstance(svc_list, list):
                warehouse = db.query(Warehouse).filter(Warehouse.branch_id == branch.id, Warehouse.is_active == True).first()
                for s in svc_list:
                    s_name = s.get("name")
                    s_price = s.get("price", 0)
                    s_qty = s.get("qty", 1)
                    s_cat = s.get("category", "SERVICE")
                    product_id = s.get("product_id")
                    
                    tx_type = FolioTransactionType.SERVICE_CHARGE
                    if s_cat == "SURCHARGE":
                        tx_type = FolioTransactionType.SURCHARGE
                    if product_id:
                        tx_type = FolioTransactionType.MINIBAR_CHARGE

                    if s_name and s_price > 0:
                        qty_dec = Decimal(str(s_qty))
                        mov_id = None
                        
                        if product_id and warehouse:
                            inv = db.query(InventoryLevel).filter(
                                InventoryLevel.warehouse_id == warehouse.id,
                                InventoryLevel.product_id == product_id
                            ).with_for_update().first()
                            
                            if inv and inv.quantity >= qty_dec:
                                inv.quantity -= qty_dec
                                mov = StockMovement(
                                    warehouse_id=warehouse.id,
                                    product_id=product_id,
                                    transaction_type=TransactionTypeWMS.EXPORT_SERVICE,
                                    quantity_change=-qty_dec,
                                    balance_after=inv.quantity,
                                    ref_ticket_type="folio",
                                    ref_ticket_id=folio.id,
                                    created_at=datetime.now(VN_TZ),
                                    actor_id=user.get("id"),
                                )
                                db.add(mov)
                                db.flush()
                                mov_id = mov.id

                        create_charge_transaction(
                            db=db,
                            folio=folio,
                            tx_type=tx_type,
                            description=s_name,
                            amount=Decimal(str(s_price)) * qty_dec,
                            unit_price=Decimal(str(s_price)),
                            quantity=qty_dec,
                            created_by=user.get("id"),
                            reference_id=mov_id,
                            reference_type="inventory" if mov_id else None,
                        )
        except Exception as e:
            logger.error(f"[CHECKIN] Error processing initial services: {e}")

    shift_tx_id = None

    if deposit and deposit > 0:
        deposit_method = deposit_type or "CASH"
        pay_method = _folio_payment_method(deposit_method)

        payment, folio_tx = create_payment_with_transaction(
            db=db,
            folio=folio,
            amount=Decimal(str(deposit)),
            method=pay_method,
            created_by=user.get("id"),
            meta={
                "source": "reservation_deposit" if booking_deposit_from_reservation else "checkin_deposit",
                "booking_id": booking.id if booking_deposit_from_reservation and booking else None,
            },
            tx_type=FolioTransactionType.DEPOSIT_USED,
            description_prefix="Cọc đặt phòng" if booking_deposit_from_reservation else "Cọc",
            paid_at=ci,
        )

        if booking_deposit_from_reservation and booking:
            raw = dict(booking.raw_data or {})
            raw["deposit_applied_to_folio"] = True
            raw["deposit_folio_id"] = folio.id
            raw["deposit_folio_transaction_id"] = folio_tx.id
            raw["deposit_payment_id"] = payment.id
            booking.raw_data = raw
        else:
            _log_deposit_to_shift_report(
                db=db,
                branch_id=branch.id,
                user_id=user.get("id"),
                stay_id=stay.id,
                folio_id=folio.id,
                folio_transaction_id=folio_tx.id,
                amount=float(deposit),
                payment_method=deposit_method,
                deposit_type=deposit_type or "Chi nhánh",
                room_number=room.room_number,
            )

    db.flush()

    inventory = InventoryService(db)
    inventory_check_out = co.date() if co else ci.date()
    if inventory_check_out <= ci.date():
        inventory_check_out = ci.date() + timedelta(days=1)

    if booking:
        booking.stay_id = stay.id
        booking.assigned_room_id = room.id
        booking.reservation_status = "CHECKED_IN"
        booking.status = BookingStatus.CONFIRMED
        booking.updated_by = user.get("id")
        booking.updated_at = _now_vn()
        room_type_id = (booking.raw_data or {}).get("room_type_id") or room.room_type_id
        inventory.move_reserved_to_sold(
            booking.id,
            stay.id,
            branch.id,
            int(room_type_id),
            booking.check_in,
            booking.check_out,
            user.get("id"),
        )
    else:
        inventory.add_sold(
            stay.id,
            branch.id,
            room.room_type_id,
            ci.date(),
            inventory_check_out,
            user_id=user.get("id"),
        )

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

    # ── Log checkin cho TỪNG extra guest có guest_id ─────────────────────
    if _extra_hotel_guests:
        total_guests = 1 + len(_extra_hotel_guests)
        for eg in _extra_hotel_guests:
            if eg.guest_id:
                log_checkin(
                    db, stay, eg,
                    actor_id=user.get("id"),
                    guest_count=total_guests,
                    extra_guest_names=[eg.full_name for eg in _extra_hotel_guests],
                )

    db.commit()

    return JSONResponse({
        "message": f"Check-in thành công! Phòng {room.room_number}",
        "stay_id": stay.id,
        "room_number": room.room_number,
        "check_in_at": ci.isoformat(),
        "check_out_at": co.isoformat() if co else None,
        "deposit": deposit,
    })


@router.get("/api/pms/checkin-info/{room_id}", tags=["PMS"])
def api_checkin_info(
    request: Request,
    room_id: int,
    db: Session = Depends(get_db),
):
    """Lấy thông tin phòng cho check-in"""
    _require_login(request)

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
            "discount_amount": float(getattr(rt, "promo_discount_amount", 0) or 0),
            "discount_percent": float(rt.promo_discount_percent or 0),  # legacy
        } if ((getattr(rt, "promo_discount_amount", 0) or 0) > 0 or (rt.promo_discount_percent or 0) > 0) else None,
    })


# ─────────────────────────── API: Pricing Preview ─────────────────────────────

@router.post("/api/pms/pricing/preview", tags=["PMS"])
def api_pricing_preview(
    request: Request,
    room_type_id: int = Form(...),
    check_in: str = Form(...),
    check_out: str = Form(""),
    stay_type: str = Form("AUTO"),
    db: Session = Depends(get_db),
):
    """Preview pricing với breakdown 3 phần: Early → Core → Late."""
    _require_login(request)

    rt = db.query(HotelRoomType).filter(HotelRoomType.id == room_type_id).first()
    if not rt:
        raise HTTPException(status_code=404, detail="Loại phòng không tìm thấy")

    try:
        ci = VN_TZ.localize(datetime.fromisoformat(check_in))
        if check_out:
            co = VN_TZ.localize(datetime.fromisoformat(check_out))
        else:
            co = _now_vn()
    except Exception:
        raise HTTPException(status_code=400, detail="Datetime không hợp lệ")

    total, breakdown = calculate_full_charge(stay_type, rt, ci, co)

    pricing_mode = None
    for item in breakdown:
        if item.get("mode") == "DAILY":
            pricing_mode = "NIGHT"
            break
        elif item.get("mode") == "HOURLY":
            pricing_mode = "HOUR"
            break

    # Thêm slice_type vào mỗi breakdown item nếu chưa có
    for item in breakdown:
        if "slice_type" not in item:
            t = item.get("type")
            if t == "EARLY_CHECKIN_FEE":
                item["slice_type"] = "early"
            elif t == "LATE_CHECKOUT_FEE":
                item["slice_type"] = "late"
            elif t in ("ROOM_CHARGE", "HOURLY_CHARGE"):
                item["slice_type"] = "core"
            else:
                item["slice_type"] = "unknown"

    return JSONResponse({
        "total": float(round(total, 2)),
        "pricing_mode": pricing_mode,
        "breakdown": [
            {
                **b,
                "amount": float(round(b["amount"], 2)) if isinstance(b.get("amount"), Decimal) else b["amount"]
            }
            for b in breakdown
        ],
        "config": get_engine_config(rt),
    })
