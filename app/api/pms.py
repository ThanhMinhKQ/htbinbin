# app/api/pms.py
"""
PMS - Property Management System
Quản lý bán phòng khách sạn Bin Bin
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from ..core.config import logger
from ..core.utils import VN_TZ
from ..db.models import (
    Branch, HotelRoom, HotelRoomType, HotelStay, HotelStayStatus,
    HotelGuest, User,
)
from ..db.session import get_db

router = APIRouter()

class FormulaSchema(BaseModel):
    name: str = "Công thức mặc định"
    formula_type: str = "Standard"
    vat: float = 0
    round_minutes: int = 1
    hour_first_count: int = 2
    hour_first_price: float = 0
    hour_next_price: float = 0
    night_price: float = 0
    night_checkin_time: Optional[str] = None
    night_checkout_time: Optional[str] = None
    night_start_window: Optional[str] = None
    night_end_window: Optional[str] = None
    night_extra_fee_per_hour: float = 0
    daily_price: float = 0
    daily_checkin_time: Optional[str] = None
    daily_checkout_time: Optional[str] = None
    daily_extra_fee_per_hour: float = 0

class RoomTypeCreateSchema(BaseModel):
    branch_id: int
    name: str
    description: Optional[str] = None
    capacity: int = 2
    is_active: bool = True
    sort_order: int = 0
    formulas: List[FormulaSchema] = []

class RoomTypeUpdateSchema(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    capacity: Optional[int] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    formulas: Optional[List[FormulaSchema]] = None


BASE_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ─────────────────────────── Helpers ────────────────────────────────

def _require_login(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    return user


def _is_admin(user: dict) -> bool:
    role = (user.get("role") or "").strip().lower()
    return role in {"admin", "quanly", "manager", "boss", "giamdoc", "superadmin"}


def _active_branch(request: Request) -> str:
    return request.session.get("active_branch") or ""


def _now_vn() -> datetime:
    return datetime.now(VN_TZ)


def _calc_price(stay_type: str, room_type: HotelRoomType,
                check_in: datetime, check_out: datetime) -> float:
    """Tính tiền phòng theo loại lưu trú."""
    if stay_type == "hour":
        total_hours = math.ceil((check_out - check_in).total_seconds() / 3600)
        total_hours = max(room_type.min_hours, total_hours)
        base_cost = float(room_type.price_per_hour) * room_type.min_hours
        extra_hours = total_hours - room_type.min_hours
        extra_cost = float(room_type.price_next_hour) * extra_hours
        return base_cost + extra_cost
    else:
        # Tính theo số đêm (mỗi ngày lịch = 1 đêm, tối thiểu 1)
        nights = math.ceil((check_out - check_in).total_seconds() / 86400)
        nights = max(1, nights)
        
        price_per_night = float(room_type.price_per_night)
        if room_type.promo_start_time and room_type.promo_end_time and room_type.promo_discount_percent > 0:
            ci_time = check_in.time()
            start = room_type.promo_start_time
            end = room_type.promo_end_time
            
            is_promo = False
            if start <= end:
                if start <= ci_time <= end:
                    is_promo = True
            else:
                if ci_time >= start or ci_time <= end:
                    is_promo = True
                    
            if is_promo:
                price_per_night = price_per_night * (1 - float(room_type.promo_discount_percent) / 100.0)
                
        return price_per_night * nights


def _room_to_dict(room: HotelRoom, active_stay: Optional[HotelStay] = None) -> dict:
    rt = room.room_type_obj
    d = {
        "id": room.id,
        "floor": room.floor,
        "room_number": room.room_number,
        "notes": room.notes,
        "room_type_id": room.room_type_id,
        "room_type_name": rt.name if rt else "—",
        "max_guests": rt.max_guests if rt else 2,
        "price_per_night": float(rt.price_per_night) if rt else 0,
        "price_per_hour": float(rt.price_per_hour) if rt else 0,
        "price_next_hour": float(rt.price_next_hour) if rt else 0,
        "promo_start_time": rt.promo_start_time.isoformat() if rt and rt.promo_start_time else None,
        "promo_end_time": rt.promo_end_time.isoformat() if rt and rt.promo_end_time else None,
        "promo_discount_percent": float(rt.promo_discount_percent) if rt else 0,
        "min_hours": rt.min_hours if rt else 1,
        "status": "OCCUPIED" if active_stay else "VACANT",
        "stay": None,
    }
    if active_stay:
        primary = next((g for g in active_stay.guests if g.is_primary), None)
        all_guests = active_stay.guests
        d["stay"] = {
            "id": active_stay.id,
            "stay_type": active_stay.stay_type,
            "check_in_at": active_stay.check_in_at.isoformat(),
            "guest_count": len(all_guests),
            "primary_guest": primary.full_name if primary else (all_guests[0].full_name if all_guests else "—"),
            "guests": [
                {
                    "id": g.id, "full_name": g.full_name, "cccd": g.cccd,
                    "gender": g.gender, "phone": g.phone,
                    "birth_date": g.birth_date.isoformat() if g.birth_date else None,
                    "is_primary": g.is_primary,
                }
                for g in all_guests
            ],
        }
    return d


# ─────────────────────────── UI Pages ───────────────────────────────

@router.get("/pms", response_class=HTMLResponse, tags=["PMS"])
async def pms_dashboard(request: Request, db: Session = Depends(get_db)):
    user = _require_login(request)
    branch_name = _active_branch(request)
    is_admin = _is_admin(user)

    # Lấy thông tin branch từ DB
    branch = None
    if branch_name and branch_name not in ("HỆ THỐNG", "Chưa phân bổ"):
        branch = db.query(Branch).filter(Branch.name == branch_name).first()

    branches = []
    if is_admin:
        branches = db.query(Branch).filter(Branch.name.like('Bin Bin Hotel%')).order_by(Branch.name).all()

    return templates.TemplateResponse("pms_dashboard.html", {
        "request": request,
        "user": user,
        "active_page": "pms",
        "branch": branch,
        "branches": branches,
        "is_admin": is_admin,
        "branch_name": branch_name,
    })


@router.get("/pms/setup", response_class=HTMLResponse, tags=["PMS"])
async def pms_setup(request: Request, db: Session = Depends(get_db)):
    """Trang cấu hình phòng - chỉ admin"""
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Không có quyền truy cập")

    branches = db.query(Branch).filter(Branch.name.like('Bin Bin Hotel%')).order_by(Branch.name).all()
    return templates.TemplateResponse("pms_room_setup.html", {
        "request": request,
        "user": user,
        "active_page": "pms",
        "branches": branches,
        "is_admin": True,
    })


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
    branch_name = _active_branch(request)

    # Xác định branch filter
    if is_admin and branch_id:
        target_branch_id = branch_id
    elif not is_admin:
        branch = db.query(Branch).filter(Branch.name == branch_name).first()
        target_branch_id = branch.id if branch else None
    else:
        target_branch_id = None  # admin, không chọn cụ thể → trả về theo branch_id param

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

    # Map stay hiện tại cho từng phòng
    result = []
    for room in rooms:
        active_stay = next(
            (s for s in room.stays if s.status == HotelStayStatus.ACTIVE),
            None
        )
        result.append(_room_to_dict(room, active_stay))

    # Group by floor
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
    branch_name = _active_branch(request)

    q = db.query(HotelRoomType).filter(HotelRoomType.is_active == True)
    if branch_id:
        q = q.filter(HotelRoomType.branch_id == branch_id)
    elif not is_admin:
        branch = db.query(Branch).filter(Branch.name == branch_name).first()
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


# ─────────────────────────── API: Check-in ──────────────────────────

@router.post("/api/pms/checkin", tags=["PMS"])
async def api_checkin(
    request: Request,
    room_id: int = Form(...),
    stay_type: str = Form(...),          # "night" | "hour"
    check_in_at: str = Form(...),        # ISO datetime
    check_out_at: Optional[str] = Form(None),   # dự kiến
    deposit: float = Form(0),
    notes: Optional[str] = Form(None),
    # Khách chính
    guest_name: str = Form(...),
    guest_cccd: Optional[str] = Form(None),
    guest_gender: Optional[str] = Form(None),
    guest_birth: Optional[str] = Form(None),
    guest_phone: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    user_id = user.get("id")

    room = db.query(HotelRoom).options(joinedload(HotelRoom.room_type_obj)).filter(
        HotelRoom.id == room_id, HotelRoom.is_active == True
    ).first()
    if not room:
        raise HTTPException(status_code=404, detail="Phòng không tồn tại")

    # Kiểm tra phòng đang trống
    existing = db.query(HotelStay).filter(
        HotelStay.room_id == room_id,
        HotelStay.status == HotelStayStatus.ACTIVE,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Phòng đang có khách!")

    # Parse datetime
    try:
        ci = datetime.fromisoformat(check_in_at).astimezone(VN_TZ)
    except Exception:
        ci = _now_vn()

    co = None
    if check_out_at:
        try:
            co = datetime.fromisoformat(check_out_at).astimezone(VN_TZ)
        except Exception:
            co = None

    # Tính tiền nếu có check_out
    price = 0.0
    if co and room.room_type_obj:
        price = _calc_price(stay_type, room.room_type_obj, ci, co)

    stay = HotelStay(
        room_id=room_id,
        branch_id=room.branch_id,
        stay_type=stay_type,
        check_in_at=ci,
        check_out_at=co,
        status=HotelStayStatus.ACTIVE,
        total_price=price,
        deposit=deposit,
        notes=notes,
        created_by=user_id,
    )
    db.add(stay)
    db.flush()  # Lấy stay.id

    # Thêm khách chính
    birth = None
    if guest_birth:
        try:
            from datetime import date as date_type
            birth = date_type.fromisoformat(guest_birth)
        except Exception:
            birth = None

    guest = HotelGuest(
        stay_id=stay.id,
        full_name=guest_name.strip(),
        cccd=guest_cccd or None,
        gender=guest_gender or None,
        birth_date=birth,
        phone=guest_phone or None,
        is_primary=True,
    )
    db.add(guest)
    db.commit()
    db.refresh(stay)

    logger.info(f"[PMS] Check-in phòng {room.room_number} – khách {guest_name}")
    return JSONResponse({"success": True, "stay_id": stay.id, "message": f"Check-in phòng {room.room_number} thành công!"})


# ─────────────────────────── API: Check-out ─────────────────────────

@router.post("/api/pms/checkout/{stay_id}", tags=["PMS"])
async def api_checkout(
    stay_id: int,
    request: Request,
    final_price: Optional[float] = Form(None),  # Cho phép override giá
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    _require_login(request)

    stay = db.query(HotelStay).options(
        joinedload(HotelStay.room).joinedload(HotelRoom.room_type_obj),
        joinedload(HotelStay.guests),
    ).filter(HotelStay.id == stay_id).first()

    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lượt lưu trú")
    if stay.status != HotelStayStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Lượt này đã kết thúc")

    now = _now_vn()
    stay.check_out_at = now
    stay.status = HotelStayStatus.CHECKED_OUT
    if notes:
        stay.notes = (stay.notes or "") + f"\n[CO] {notes}"

    # Tính lại giá nếu không override
    if final_price is not None:
        stay.total_price = final_price
    elif stay.room and stay.room.room_type_obj:
        stay.total_price = _calc_price(stay.stay_type, stay.room.room_type_obj, stay.check_in_at, now)

    db.commit()
    room_num = stay.room.room_number if stay.room else stay_id
    logger.info(f"[PMS] Check-out phòng {room_num} – stay #{stay_id}")
    return JSONResponse({
        "success": True,
        "total_price": float(stay.total_price),
        "message": f"Check-out phòng {room_num} thành công!",
    })


# ─────────────────────────── API: Add Guest ─────────────────────────

@router.post("/api/pms/stays/{stay_id}/guests", tags=["PMS"])
async def api_add_guest(
    stay_id: int,
    request: Request,
    full_name: str = Form(...),
    cccd: Optional[str] = Form(None),
    gender: Optional[str] = Form(None),
    birth_date: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    _require_login(request)
    stay = db.query(HotelStay).filter(HotelStay.id == stay_id, HotelStay.status == HotelStayStatus.ACTIVE).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lượt lưu trú đang hoạt động")

    birth = None
    if birth_date:
        try:
            from datetime import date as date_type
            birth = date_type.fromisoformat(birth_date)
        except Exception:
            pass

    guest = HotelGuest(
        stay_id=stay_id,
        full_name=full_name.strip(),
        cccd=cccd or None,
        gender=gender or None,
        birth_date=birth,
        phone=phone or None,
        is_primary=False,
    )
    db.add(guest)
    db.commit()
    return JSONResponse({"success": True, "message": "Đã thêm khách vào phòng"})


# ─────────────────────────── API: Transfer Room ─────────────────────

@router.put("/api/pms/stays/{stay_id}/transfer", tags=["PMS"])
async def api_transfer_room(
    stay_id: int,
    request: Request,
    new_room_id: int = Form(...),
    db: Session = Depends(get_db),
):
    _require_login(request)

    stay = db.query(HotelStay).filter(HotelStay.id == stay_id, HotelStay.status == HotelStayStatus.ACTIVE).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lượt lưu trú")

    new_room = db.query(HotelRoom).filter(HotelRoom.id == new_room_id, HotelRoom.is_active == True).first()
    if not new_room:
        raise HTTPException(status_code=404, detail="Phòng mới không tồn tại")

    # Kiểm tra phòng mới có trống không
    conflict = db.query(HotelStay).filter(
        HotelStay.room_id == new_room_id,
        HotelStay.status == HotelStayStatus.ACTIVE,
    ).first()
    if conflict:
        raise HTTPException(status_code=409, detail="Phòng mới đang có khách!")

    old_room_num = stay.room.room_number if stay.room else stay.room_id
    stay.room_id = new_room_id
    stay.notes = (stay.notes or "") + f"\n[ĐỔI PHÒNG] {old_room_num} → {new_room.room_number}"
    db.commit()
    return JSONResponse({"success": True, "message": f"Đã đổi sang phòng {new_room.room_number}"})


# ─────────────────────────── API: Stay History ──────────────────────

@router.get("/api/pms/stays", tags=["PMS"])
async def api_get_stays(
    request: Request,
    branch_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    is_admin = _is_admin(user)
    branch_name = _active_branch(request)

    q = db.query(HotelStay).options(
        joinedload(HotelStay.room),
        joinedload(HotelStay.guests),
    ).order_by(HotelStay.check_in_at.desc())

    if not is_admin:
        branch = db.query(Branch).filter(Branch.name == branch_name).first()
        if branch:
            q = q.filter(HotelStay.branch_id == branch.id)
    elif branch_id:
        q = q.filter(HotelStay.branch_id == branch_id)

    if status:
        q = q.filter(HotelStay.status == status)

    stays = q.limit(limit).all()

    return JSONResponse([
        {
            "id": s.id,
            "room_number": s.room.room_number if s.room else "?",
            "stay_type": s.stay_type,
            "check_in_at": s.check_in_at.isoformat(),
            "check_out_at": s.check_out_at.isoformat() if s.check_out_at else None,
            "status": s.status.value,
            "total_price": float(s.total_price),
            "guest_count": len(s.guests),
            "primary_guest": next((g.full_name for g in s.guests if g.is_primary), "—"),
        }
        for s in stays
    ])


@router.get("/api/pms/stays/{stay_id}", tags=["PMS"])
async def api_get_stay_detail(
    stay_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _require_login(request)
    stay = db.query(HotelStay).options(
        joinedload(HotelStay.room).joinedload(HotelRoom.room_type_obj),
        joinedload(HotelStay.guests),
    ).filter(HotelStay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy")

    rt = stay.room.room_type_obj if stay.room else None
    return JSONResponse({
        "id": stay.id,
        "room_number": stay.room.room_number if stay.room else "?",
        "room_type": rt.name if rt else "—",
        "stay_type": stay.stay_type,
        "check_in_at": stay.check_in_at.isoformat(),
        "check_out_at": stay.check_out_at.isoformat() if stay.check_out_at else None,
        "status": stay.status.value,
        "total_price": float(stay.total_price),
        "deposit": float(stay.deposit),
        "price_per_night": float(rt.price_per_night) if rt else 0,
        "price_per_hour": float(rt.price_per_hour) if rt else 0,
        "price_next_hour": float(rt.price_next_hour) if rt else 0,
        "min_hours": rt.min_hours if rt else 1,
        "notes": stay.notes,
        "guests": [
            {
                "id": g.id, "full_name": g.full_name, "cccd": g.cccd,
                "gender": g.gender, "phone": g.phone,
                "birth_date": g.birth_date.isoformat() if g.birth_date else None,
                "is_primary": g.is_primary,
            }
            for g in stay.guests
        ],
    })


# ─────────────────────── Admin: Room Type CRUD ──────────────────────

@router.get("/api/pms/admin/room-types", tags=["PMS Admin"])
async def admin_list_room_types(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403)

    q = db.query(HotelRoomType).order_by(HotelRoomType.branch_id, HotelRoomType.sort_order)
    if branch_id:
        q = q.filter(HotelRoomType.branch_id == branch_id)
    types = q.all()
    return JSONResponse([
        {
            "id": t.id, "branch_id": t.branch_id, "name": t.name,
            "description": t.description,
            "price_per_night": float(t.price_per_night),
            "price_per_hour": float(t.price_per_hour),
            "price_next_hour": float(t.price_next_hour),
            "promo_start_time": t.promo_start_time.isoformat() if t.promo_start_time else None,
            "promo_end_time": t.promo_end_time.isoformat() if t.promo_end_time else None,
            "promo_discount_percent": float(t.promo_discount_percent),
            "min_hours": t.min_hours, "max_guests": t.max_guests,
            "is_active": t.is_active, "sort_order": t.sort_order,
        }
        for t in types
    ])


@router.post("/api/pms/admin/room-types", tags=["PMS Admin"])
async def admin_create_room_type(
    request: Request,
    branch_id: int = Form(...),
    name: str = Form(...),
    description: Optional[str] = Form(None),
    price_per_night: float = Form(0),
    price_per_hour: float = Form(0),
    price_next_hour: float = Form(0),
    promo_start_time: Optional[str] = Form(None),
    promo_end_time: Optional[str] = Form(None),
    promo_discount_percent: float = Form(0),
    min_hours: int = Form(1),
    max_guests: int = Form(2),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403)

    start_time_parsed = None
    if promo_start_time:
        try: start_time_parsed = datetime.strptime(promo_start_time, "%H:%M").time()
        except Exception: pass
        
    end_time_parsed = None
    if promo_end_time:
        try: end_time_parsed = datetime.strptime(promo_end_time, "%H:%M").time()
        except Exception: pass

    rt = HotelRoomType(
        branch_id=branch_id, name=name.strip(), description=description,
        price_per_night=price_per_night, price_per_hour=price_per_hour,
        price_next_hour=price_next_hour, 
        promo_start_time=start_time_parsed, promo_end_time=end_time_parsed,
        promo_discount_percent=promo_discount_percent,
        min_hours=min_hours, max_guests=max_guests, sort_order=sort_order,
    )
    db.add(rt)
    db.commit()
    db.refresh(rt)
    return JSONResponse({"success": True, "id": rt.id, "message": "Tạo loại phòng thành công"})


@router.put("/api/pms/admin/room-types/{type_id}", tags=["PMS Admin"])
async def admin_update_room_type(
    type_id: int,
    request: Request,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    price_per_night: Optional[float] = Form(None),
    price_per_hour: Optional[float] = Form(None),
    price_next_hour: Optional[float] = Form(None),
    promo_start_time: Optional[str] = Form(None),
    promo_end_time: Optional[str] = Form(None),
    promo_discount_percent: Optional[float] = Form(None),
    min_hours: Optional[int] = Form(None),
    max_guests: Optional[int] = Form(None),
    is_active: Optional[bool] = Form(None),
    sort_order: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403)

    rt = db.query(HotelRoomType).filter(HotelRoomType.id == type_id).first()
    if not rt:
        raise HTTPException(status_code=404)

    if name is not None: rt.name = name.strip()
    if description is not None: rt.description = description
    if price_per_night is not None: rt.price_per_night = price_per_night
    if price_per_hour is not None: rt.price_per_hour = price_per_hour
    if price_next_hour is not None: rt.price_next_hour = price_next_hour

    if promo_start_time is not None:
        if promo_start_time == "":
            rt.promo_start_time = None
        else:
            try: rt.promo_start_time = datetime.strptime(promo_start_time, "%H:%M").time()
            except Exception: pass
            
    if promo_end_time is not None:
        if promo_end_time == "":
            rt.promo_end_time = None
        else:
            try: rt.promo_end_time = datetime.strptime(promo_end_time, "%H:%M").time()
            except Exception: pass
            
    if promo_discount_percent is not None: rt.promo_discount_percent = promo_discount_percent

    if min_hours is not None: rt.min_hours = min_hours
    if max_guests is not None: rt.max_guests = max_guests
    if is_active is not None: rt.is_active = is_active
    if sort_order is not None: rt.sort_order = sort_order

    db.commit()
    return JSONResponse({"success": True, "message": "Cập nhật loại phòng thành công"})


# ─────────────────────── Admin: Room CRUD ───────────────────────────

@router.get("/api/pms/admin/rooms", tags=["PMS Admin"])
async def admin_list_rooms(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403)

    q = (
        db.query(HotelRoom)
        .options(joinedload(HotelRoom.room_type_obj))
        .order_by(HotelRoom.branch_id, HotelRoom.floor, HotelRoom.sort_order, HotelRoom.room_number)
    )
    if branch_id:
        q = q.filter(HotelRoom.branch_id == branch_id)
    rooms = q.all()

    return JSONResponse([
        {
            "id": r.id, "branch_id": r.branch_id, "floor": r.floor,
            "room_number": r.room_number, "room_type_id": r.room_type_id,
            "room_type_name": r.room_type_obj.name if r.room_type_obj else "—",
            "price_per_night": float(r.room_type_obj.price_per_night) if r.room_type_obj and r.room_type_obj.price_per_night is not None else 0,
            "price_per_hour": float(r.room_type_obj.price_per_hour) if r.room_type_obj and r.room_type_obj.price_per_hour is not None else 0,
            "price_next_hour": float(r.room_type_obj.price_next_hour) if r.room_type_obj and r.room_type_obj.price_next_hour is not None else 0,
            "notes": r.notes, "is_active": r.is_active, "sort_order": r.sort_order,
        }
        for r in rooms
    ])


@router.post("/api/pms/admin/rooms", tags=["PMS Admin"])
async def admin_create_room(
    request: Request,
    branch_id: int = Form(...),
    floor: int = Form(...),
    room_number: str = Form(...),
    room_type_id: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403)

    # Kiểm tra trùng
    exist = db.query(HotelRoom).filter(
        HotelRoom.branch_id == branch_id,
        HotelRoom.room_number == room_number.strip()
    ).first()
    if exist:
        raise HTTPException(status_code=409, detail=f"Phòng {room_number} đã tồn tại trong chi nhánh này")

    room = HotelRoom(
        branch_id=branch_id, floor=floor, room_number=room_number.strip(),
        room_type_id=room_type_id, notes=notes, sort_order=sort_order,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return JSONResponse({"success": True, "id": room.id, "message": f"Tạo phòng {room_number} thành công"})


@router.put("/api/pms/admin/rooms/{room_id}", tags=["PMS Admin"])
async def admin_update_room(
    room_id: int,
    request: Request,
    floor: Optional[int] = Form(None),
    room_number: Optional[str] = Form(None),
    room_type_id: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    is_active: Optional[bool] = Form(None),
    sort_order: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403)

    room = db.query(HotelRoom).filter(HotelRoom.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404)

    if floor is not None: room.floor = floor
    if room_number is not None: room.room_number = room_number.strip()
    if room_type_id is not None: room.room_type_id = room_type_id
    if notes is not None: room.notes = notes
    if is_active is not None: room.is_active = is_active
    if sort_order is not None: room.sort_order = sort_order

    db.commit()
    return JSONResponse({"success": True, "message": "Cập nhật phòng thành công"})


@router.delete("/api/pms/admin/rooms/{room_id}", tags=["PMS Admin"])
async def admin_delete_room(
    room_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403)

    room = db.query(HotelRoom).filter(HotelRoom.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404)

    # Không xoá nếu đang có khách đang ở
    active = db.query(HotelStay).filter(
        HotelStay.room_id == room_id, HotelStay.status == HotelStayStatus.ACTIVE
    ).first()
    if active:
        raise HTTPException(status_code=409, detail="Phòng đang có khách, không thể xoá!")

    # Không xoá nếu có lịch sử lưu trú (tránh mất dữ liệu và lỗi RESTRICT)
    has_history = db.query(HotelStay).filter(HotelStay.room_id == room_id).first()
    if has_history:
        raise HTTPException(status_code=409, detail=f"Phòng đã có lịch sử lưu trú, không thể xoá vĩnh viễn. Hãy vô hiệu hoá phòng thay thế.")

    room_number = room.room_number
    db.delete(room)  # Hard delete
    db.commit()
    return JSONResponse({"success": True, "message": f"Đã xoá phòng {room_number} vĩnh viễn"})
