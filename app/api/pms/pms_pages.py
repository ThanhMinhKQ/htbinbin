# app/api/pms/pms_pages.py
"""
PMS Pages - Dashboard, Booking, and Setup pages
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ...db.models import Branch, HotelRoomType
from ...db.session import get_db
from .pms_helpers import _require_login, _is_admin, _is_manager, _active_branch

router = APIRouter()

BASE_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


HOTEL_BRANCH_NAME_RE = re.compile(r"\bbin\s*bin\s*hotel\s*(?:b)?(\d+)\b", re.IGNORECASE)
HOTEL_BRANCH_CODE_RE = re.compile(r"^B(\d+)$", re.IGNORECASE)


def _hotel_branch_number(branch: Branch) -> int | None:
    name_match = HOTEL_BRANCH_NAME_RE.search(branch.name or "")
    if name_match:
        return int(name_match.group(1))
    code_match = HOTEL_BRANCH_CODE_RE.match(branch.branch_code or "")
    if code_match:
        return int(code_match.group(1))
    return None


def _hotel_branch_sort_key(branch: Branch):
    number = _hotel_branch_number(branch)
    return (
        number if number is not None else 10**9,
        (branch.name or "").lower(),
        branch.id or 0,
    )


def _hotel_branch_display_name(branch: Branch | None) -> str:
    number = _hotel_branch_number(branch) if branch else None
    if number is not None:
        return f"Bin Bin Hotel {number}"
    return branch.name if branch else ""


def _hotel_branches(db: Session) -> list[Branch]:
    branches = (
        db.query(Branch)
        .filter(or_(Branch.name.ilike("%Bin Bin Hotel%"), Branch.branch_code.ilike("B%")))
        .all()
    )
    hotel_branches = sorted(
        [branch for branch in branches if _hotel_branch_number(branch) is not None],
        key=_hotel_branch_sort_key,
    )
    for branch in hotel_branches:
        branch.pms_display_name = _hotel_branch_display_name(branch)
    return hotel_branches


def _hotel_branch_or_none(branch: Branch | None) -> Branch | None:
    if branch and _hotel_branch_number(branch) is not None:
        return branch
    return None


# ─────────────────────────── UI Pages ───────────────────────────────

@router.get("/pms", response_class=HTMLResponse, tags=["PMS"])
def pms_dashboard(request: Request, db: Session = Depends(get_db)):
    user = _require_login(request)
    branch_code = _active_branch(request)
    is_admin = _is_admin(user)
    is_manager = _is_manager(user)

    # Lấy thông tin branch từ DB (theo branch_code)
    branch = None
    if branch_code and branch_code not in ("HỆ THỐNG", "Chưa phân bổ"):
        branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()

    branches = _hotel_branches(db) if is_admin else []
    selected_branch = _hotel_branch_or_none(branch) or (branches[0] if is_admin and branches else None)

    return templates.TemplateResponse(request, "pms/dashboard.html", {
        "request": request,
        "user": user,
        "active_page": "pms",
        "branch": selected_branch,
        "branches": branches,
        "is_admin": is_admin,
        "is_manager": is_manager,
        "branch_code": branch_code,
        "branch_name": _hotel_branch_display_name(selected_branch),
        "stats": {
            "total_rooms": 0,
            "occupied_rooms": 0,
            "vacant_rooms": 0,
            "checkout_today": 0,
            "checkin_today": 0,
            "occupancy_rate": 0,
            "revenue_today": 0,
            "revenue_month": 0,
            "average_rate": 0,
        },
        "room_types": [],
    })


@router.get("/pms/booking", response_class=HTMLResponse, tags=["PMS"])
def pms_booking(request: Request, db: Session = Depends(get_db)):
    """Trang quản lý và tạo đặt phòng."""
    user = _require_login(request)
    branch_code = _active_branch(request)
    is_admin = _is_admin(user)
    is_manager = _is_manager(user)
    branch = None
    if branch_code and branch_code not in ("HỆ THỐNG", "Chưa phân bổ"):
        branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()
    branches = _hotel_branches(db)
    visible_branches = branches if is_admin else []
    room_types = []
    selected_branch = _hotel_branch_or_none(branch) or (branches[0] if is_admin and branches else None)
    if selected_branch:
        room_types = (
            db.query(HotelRoomType)
            .filter(HotelRoomType.branch_id == selected_branch.id, HotelRoomType.is_active == True)
            .order_by(HotelRoomType.sort_order, HotelRoomType.name)
            .all()
        )
    boot_data = {
        "isAdmin": is_admin,
        "branchId": selected_branch.id if selected_branch else None,
        "branches": [{"id": b.id, "name": _hotel_branch_display_name(b), "branch_code": b.branch_code} for b in visible_branches],
        "transferBranches": [{"id": b.id, "name": _hotel_branch_display_name(b), "branch_code": b.branch_code} for b in branches],
        "roomTypes": [
            {"id": t.id, "name": t.name, "price_per_night": float(t.price_per_night or 0), "max_guests": t.max_guests or 1}
            for t in room_types
        ],
    }
    return templates.TemplateResponse(request, "pms/booking.html", {
        "request": request,
        "user": user,
        "active_page": "pms_booking",
        "branch": selected_branch,
        "branches": visible_branches,
        "is_admin": is_admin,
        "is_manager": is_manager,
        "branch_code": branch_code,
        "branch_name": _hotel_branch_display_name(selected_branch),
        "room_types": room_types,
        "boot_json": json.dumps(boot_data, ensure_ascii=False),
    })


@router.get("/pms/room-status", response_class=HTMLResponse, tags=["PMS"])
def pms_room_status(request: Request, db: Session = Depends(get_db)):
    """Trang tình trạng phòng theo ngày và theo tháng."""
    user = _require_login(request)
    branch_code = _active_branch(request)
    is_admin = _is_admin(user)
    is_manager = _is_manager(user)
    branch = None
    if branch_code and branch_code not in ("HỆ THỐNG", "Chưa phân bổ"):
        branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()
    branches = _hotel_branches(db) if is_admin else []
    selected_branch = _hotel_branch_or_none(branch) or (branches[0] if is_admin and branches else None)
    boot_data = {
        "isAdmin": is_admin,
        "branchId": selected_branch.id if selected_branch else None,
        "branches": [{"id": b.id, "name": _hotel_branch_display_name(b), "branch_code": b.branch_code} for b in branches],
    }
    return templates.TemplateResponse(request, "pms/room_status.html", {
        "request": request,
        "user": user,
        "active_page": "pms_room_status",
        "branch": selected_branch,
        "branches": branches,
        "is_admin": is_admin,
        "is_manager": is_manager,
        "branch_code": branch_code,
        "branch_name": _hotel_branch_display_name(selected_branch),
        "boot_json": json.dumps(boot_data, ensure_ascii=False),
    })


@router.get("/pms/setup", response_class=HTMLResponse, tags=["PMS"])
def pms_setup(request: Request, db: Session = Depends(get_db)):
    """Trang cấu hình phòng - chỉ admin"""
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Không có quyền truy cập")

    branches = _hotel_branches(db)
    tab = (request.query_params.get("tab") or "types").strip().lower()
    if tab not in ("types", "rooms"):
        tab = "types"
    return templates.TemplateResponse(request, "pms/room_setup.html", {
        "request": request,
        "user": user,
        "active_page": "pms_setup",
        "pms_setup_tab": tab,
        "branches": branches,
        "is_admin": True,
    })


@router.get("/pms/history", response_class=HTMLResponse, tags=["PMS"])
def pms_room_history(request: Request, db: Session = Depends(get_db)):
    """Trang lịch sử phòng - giống sơ đồ phòng, hiển thị các lưu trú đã checkout."""
    user = _require_login(request)
    branch_code = _active_branch(request)
    is_admin = _is_admin(user)
    is_manager = _is_manager(user)

    branch = None
    if branch_code and branch_code not in ("HỆ THỐNG", "Chưa phân bổ"):
        branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()

    branches = _hotel_branches(db) if is_admin else []
    selected_branch = _hotel_branch_or_none(branch) or (branches[0] if is_admin and branches else None)
    boot_data = {
        "isAdmin": is_admin,
        "branchId": selected_branch.id if selected_branch else None,
    }

    return templates.TemplateResponse(request, "pms/room_history.html", {
        "request": request,
        "user": user,
        "active_page": "pms_history",
        "branch": selected_branch,
        "branches": branches,
        "is_admin": is_admin,
        "is_manager": is_manager,
        "branch_code": branch_code,
        "branch_name": _hotel_branch_display_name(selected_branch),
        "boot_json": json.dumps(boot_data, ensure_ascii=False),
    })


@router.get("/pms/crm", response_class=HTMLResponse, tags=["PMS - CRM"])
def pms_crm_dashboard(request: Request, db: Session = Depends(get_db)):
    """Trang CRM Dashboard - Quản lý khách hàng."""
    user = _require_login(request)
    branch_code = _active_branch(request)
    is_admin = _is_admin(user)
    is_manager = _is_manager(user)

    branch = None
    if branch_code and branch_code not in ("HỆ THỐNG", "Chưa phân bổ"):
        branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()

    branches = _hotel_branches(db) if is_admin else []
    branch = _hotel_branch_or_none(branch)

    return templates.TemplateResponse(request, "pms/crm_dashboard.html", {
        "request": request,
        "user": user,
        "active_page": "pms_crm",
        "branch": branch,
        "branches": branches,
        "is_admin": is_admin,
        "is_manager": is_manager,
        "branch_code": branch_code,
        "branch_name": _hotel_branch_display_name(branch),
    })


@router.get("/pms/crm/guest/{guest_id}", response_class=HTMLResponse, tags=["PMS - CRM"])
def pms_crm_guest_detail(request: Request, guest_id: int, db: Session = Depends(get_db)):
    """Trang chi tiết khách hàng 360° - CRM."""
    user = _require_login(request)
    branch_code = _active_branch(request)
    is_admin = _is_admin(user)
    is_manager = _is_manager(user)

    branch = None
    if branch_code and branch_code not in ("HỆ THỐNG", "Chưa phân bổ"):
        branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()

    return templates.TemplateResponse(request, "pms/crm_guest_detail.html", {
        "request": request,
        "user": user,
        "active_page": "pms_crm",
        "branch": branch,
        "is_admin": is_admin,
        "is_manager": is_manager,
        "branch_code": branch_code,
        "branch_name": _hotel_branch_display_name(branch),
        "guest_id": guest_id,
    })


@router.get("/pms/guest-history", response_class=HTMLResponse, tags=["PMS"])
def pms_guest_history(request: Request, guest_id: int = None, db: Session = Depends(get_db)):
    """Trang lịch sử khách - xem lịch sử lưu trú theo khách hàng."""
    user = _require_login(request)
    branch_code = _active_branch(request)
    is_admin = _is_admin(user)
    is_manager = _is_manager(user)

    branch = None
    if branch_code and branch_code not in ("HỆ THỐNG", "Chưa phân bổ"):
        branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()

    branches = _hotel_branches(db) if is_admin else []
    branch = _hotel_branch_or_none(branch)

    return templates.TemplateResponse(request, "pms/guest_history.html", {
        "request": request,
        "user": user,
        "active_page": "pms_guest_history",
        "branch": branch,
        "branches": branches,
        "is_admin": is_admin,
        "is_manager": is_manager,
        "branch_code": branch_code,
        "branch_name": _hotel_branch_display_name(branch),
        "guest_id": guest_id,
    })
