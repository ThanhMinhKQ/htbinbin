# app/api/pms/pms_helpers.py
"""
PMS Shared Helpers - Common functions used across PMS modules
"""
from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta, date
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func

from ...core.config import logger
from ...core.utils import VN_TZ
from ...db.models import (
    Branch, HotelRoom, HotelRoomType, HotelStay, HotelStayStatus,
    HotelGuest, User,
)
from ...db.session import get_db


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _require_login(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    return user


def _is_admin(user: dict) -> bool:
    role = (user.get("role") or "").strip().lower()
    return role in {"admin", "quanly", "manager", "boss", "giamdoc", "superadmin"}


def _is_manager(user: dict) -> bool:
    role = (user.get("role") or "").strip().lower()
    return role in {"admin", "quanly", "manager", "boss", "giamdoc", "superadmin", "dieuhanh"}


def _active_branch(request: Request) -> str:
    """Lấy active branch từ session, fallback về DB nếu cần"""
    branch_code = request.session.get("active_branch")
    if branch_code:
        return branch_code

    # Fallback: thử lấy từ DB user
    user = request.session.get("user")
    if user:
        # Lấy user_id từ session
        user_id = user.get("id")
        if user_id:
            # Import get_db tại đây để tránh circular import
            from ...db.session import SessionLocal
            with SessionLocal() as db:
                u = db.query(User).filter(User.id == user_id).first()
                if u and u.last_active_branch_id and u.last_active_branch:
                    return u.last_active_branch.branch_code
    return ""


def _get_active_branch_code(request: Request, db: Session) -> str:
    """Lấy active branch code với DB session (dùng trong API handlers)"""
    branch_code = request.session.get("active_branch")
    if branch_code:
        return branch_code

    user = request.session.get("user")
    if user and user.get("id"):
        u = db.query(User).filter(User.id == user["id"]).first()
        if u and u.last_active_branch_id and u.last_active_branch:
            return u.last_active_branch.branch_code
    return ""


def _now_vn() -> datetime:
    return datetime.now(VN_TZ)


def _get_branch_by_code(branch_code: str, db: Session) -> Optional[Branch]:
    """Lấy branch từ branch_code"""
    if branch_code and branch_code not in ("HỆ THỐNG", "Chưa phân bổ"):
        return db.query(Branch).filter(Branch.branch_code == branch_code).first()
    return None


def _get_occupied_rooms_for_dates(db: Session, branch_id: int, check_in: datetime, check_out: datetime) -> List[int]:
    """
    Lấy danh sách các phòng đang bận trong khoảng thời gian.
    """
    occupied = db.query(HotelStay.room_id).filter(
        HotelStay.branch_id == branch_id,
        HotelStay.status == HotelStayStatus.ACTIVE,
        or_(
            and_(HotelStay.check_in_at <= check_in, HotelStay.check_out_at >= check_in),
            and_(HotelStay.check_in_at < check_out, HotelStay.check_out_at >= check_out),
            and_(HotelStay.check_in_at >= check_in, HotelStay.check_out_at <= check_out)
        )
    ).distinct().all()
    return [o[0] for o in occupied]


def _calc_price(stay_type: str, room_type: Optional[HotelRoomType],
                check_in: datetime, check_out: datetime, apply_promo: bool = True) -> float:
    """Tính tiền phòng theo loại lưu trú."""
    if not room_type:
        return 0.0

    if stay_type == "hour":
        total_hours = math.ceil((check_out - check_in).total_seconds() / 3600)
        min_hours = room_type.min_hours if room_type.min_hours is not None else 1
        total_hours = max(min_hours, total_hours)
        
        price_per_hour = float(room_type.price_per_hour or 0)
        price_next_hour = float(room_type.price_next_hour or 0)
        
        base_cost = price_per_hour * min_hours
        extra_hours = total_hours - min_hours
        extra_cost = price_next_hour * extra_hours
        return base_cost + extra_cost
    else:
        nights = math.ceil((check_out - check_in).total_seconds() / 86400)
        nights = max(1, nights)

        price_per_night = float(room_type.price_per_night or 0)

        if apply_promo and room_type.promo_start_time and room_type.promo_end_time and room_type.promo_discount_percent and room_type.promo_discount_percent > 0:
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
        # Filter only guests who haven't checked out yet
        staying_guests = [g for g in active_stay.guests if not g.check_out_at]
        primary = next((g for g in staying_guests if g.is_primary), None)
        all_guests = staying_guests
        d["stay"] = {
            "id": active_stay.id,
            "stay_type": active_stay.stay_type,
            "check_in_at": active_stay.check_in_at.isoformat(),
            "check_out_at": active_stay.check_out_at.isoformat() if active_stay.check_out_at else None,
            "guest_count": len(staying_guests),
            "primary_guest": primary.full_name if primary else (staying_guests[0].full_name if staying_guests else "—"),
            "vehicle": active_stay.vehicle if hasattr(active_stay, 'vehicle') else None,
            "guests": [
                {
                    "id": g.id, "full_name": g.full_name, "cccd": g.cccd,
                    "gender": g.gender, "phone": g.phone,
                    "birth_date": g.birth_date.isoformat() if g.birth_date else None,
                    "is_primary": g.is_primary,
                    "notes": g.notes,
                    "check_out_at": g.check_out_at.isoformat() if g.check_out_at else None,
                }
                for g in staying_guests
            ],
        }
    return d


def _get_pms_stats(db: Session, branch_id: Optional[int] = None, start_date: Optional[date] = None, end_date: Optional[date] = None) -> Dict[str, Any]:
    """
    Tính toán thống kê PMS.
    """
    today = _now_vn().date()
    start_date = start_date or today
    end_date = end_date or today

    query = db.query(HotelRoom).filter(HotelRoom.is_active == True)
    if branch_id:
        query = query.filter(HotelRoom.branch_id == branch_id)
    all_rooms = query.all()
    total_rooms = len(all_rooms)

    occupied_ids = set()
    checkin_today = 0
    checkout_today = 0

    for room in all_rooms:
        for stay in room.stays:
            if stay.status == HotelStayStatus.ACTIVE:
                occupied_ids.add(room.id)
            if stay.check_in_at.date() == today:
                checkin_today += 1
            if stay.check_out_at and stay.check_out_at.date() == today:
                checkout_today += 1

    vacant_rooms = total_rooms - len(occupied_ids)
    occupancy_rate = (len(occupied_ids) / total_rooms * 100) if total_rooms > 0 else 0

    # Revenue today
    today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=VN_TZ)
    today_end = datetime.combine(today, datetime.max.time()).replace(tzinfo=VN_TZ)

    revenue_query = db.query(func.sum(HotelStay.total_price)).filter(
        HotelStay.check_in_at >= today_start,
        HotelStay.check_in_at <= today_end,
        HotelStay.status.in_([HotelStayStatus.ACTIVE, HotelStayStatus.CHECKED_OUT])
    )
    if branch_id:
        revenue_query = revenue_query.filter(HotelStay.branch_id == branch_id)
    revenue_today = revenue_query.scalar() or 0

    # Revenue this month
    month_start = today.replace(day=1)
    month_start_dt = datetime.combine(month_start, datetime.min.time()).replace(tzinfo=VN_TZ)
    revenue_query_month = db.query(func.sum(HotelStay.total_price)).filter(
        HotelStay.check_in_at >= month_start_dt,
        HotelStay.status.in_([HotelStayStatus.ACTIVE, HotelStayStatus.CHECKED_OUT])
    )
    if branch_id:
        revenue_query_month = revenue_query_month.filter(HotelStay.branch_id == branch_id)
    revenue_month = revenue_query_month.scalar() or 0

    # Average rate
    avg_rate = revenue_today / len(occupied_ids) if len(occupied_ids) > 0 else 0

    return {
        "total_rooms": total_rooms,
        "occupied_rooms": len(occupied_ids),
        "vacant_rooms": vacant_rooms,
        "checkout_today": checkout_today,
        "checkin_today": checkin_today,
        "occupancy_rate": round(occupancy_rate, 1),
        "revenue_today": float(revenue_today),
        "revenue_month": float(revenue_month),
        "average_rate": float(avg_rate),
    }


def _parse_birth(s: Optional[str]):
    if not s:
        return None
    try:
        from datetime import date as date_type
        return date_type.fromisoformat(s)
    except Exception:
        return None