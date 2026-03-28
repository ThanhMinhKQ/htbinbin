# app/api/pms/pms_pages.py
"""
PMS Pages - Dashboard, Booking, and Setup pages
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ...db.models import Branch, HotelRoomType
from ...db.session import get_db
from .pms_helpers import _require_login, _is_admin, _is_manager, _active_branch, _get_pms_stats

router = APIRouter()

BASE_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ─────────────────────────── UI Pages ───────────────────────────────

@router.get("/pms", response_class=HTMLResponse, tags=["PMS"])
async def pms_dashboard(request: Request, db: Session = Depends(get_db)):
    user = _require_login(request)
    branch_code = _active_branch(request)
    is_admin = _is_admin(user)
    is_manager = _is_manager(user)

    # Lấy thông tin branch từ DB (theo branch_code)
    branch = None
    if branch_code and branch_code not in ("HỆ THỐNG", "Chưa phân bổ"):
        branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()

    branches = []
    if is_admin:
        # Sắp xếp theo thứ tự tự nhiên: B1, B2, B3... thay vì B1, B10, B11, B2...
        branches_raw = db.query(Branch).filter(Branch.branch_code.like('B%')).order_by(Branch.branch_code).all()
        import re
        def natural_key(code):
            parts = re.split(r'(\d+)', code)
            return [(int(p) if p.isdigit() else p.lower()) for p in parts]
        branches = sorted(branches_raw, key=lambda b: natural_key(b.branch_code))

    # Get stats for dashboard
    stats = _get_pms_stats(db, branch.id if branch else None)
    room_types = []
    if branch:
        room_types = (
            db.query(HotelRoomType)
            .filter(HotelRoomType.branch_id == branch.id, HotelRoomType.is_active == True)
            .order_by(HotelRoomType.sort_order, HotelRoomType.name)
            .all()
        )
    elif is_admin and branches:
        bid = branches[0].id
        room_types = (
            db.query(HotelRoomType)
            .filter(HotelRoomType.branch_id == bid, HotelRoomType.is_active == True)
            .order_by(HotelRoomType.sort_order, HotelRoomType.name)
            .all()
        )

    return templates.TemplateResponse("pms/dashboard.html", {
        "request": request,
        "user": user,
        "active_page": "pms",
        "branch": branch,
        "branches": branches,
        "is_admin": is_admin,
        "is_manager": is_manager,
        "branch_code": branch_code,
        "branch_name": branch.name if branch else "",
        "stats": stats,
        "room_types": room_types,
    })


@router.get("/pms/booking", response_class=HTMLResponse, tags=["PMS"])
async def pms_booking(request: Request, db: Session = Depends(get_db)):
    """Trang quản lý đặt phòng - tìm phòng trống."""
    user = _require_login(request)
    branch_code = _active_branch(request)
    is_admin = _is_admin(user)
    branch = None
    if branch_code and branch_code not in ("HỆ THỐNG", "Chưa phân bổ"):
        branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()
    branches = []
    if is_admin:
        branches = db.query(Branch).filter(Branch.branch_code.like('B%')).order_by(Branch.branch_code).all()
    room_types = []
    if branch:
        room_types = (
            db.query(HotelRoomType)
            .filter(HotelRoomType.branch_id == branch.id, HotelRoomType.is_active == True)
            .order_by(HotelRoomType.sort_order, HotelRoomType.name)
            .all()
        )
    elif is_admin and branches:
        bid = branches[0].id
        room_types = (
            db.query(HotelRoomType)
            .filter(HotelRoomType.branch_id == bid, HotelRoomType.is_active == True)
            .order_by(HotelRoomType.sort_order, HotelRoomType.name)
            .all()
        )
    return templates.TemplateResponse("pms/booking.html", {
        "request": request,
        "user": user,
        "active_page": "pms_booking",
        "branch": branch,
        "branches": branches,
        "is_admin": is_admin,
        "branch_code": branch_code,
        "branch_name": branch.name if branch else "",
        "room_types": room_types,
    })


@router.get("/pms/setup", response_class=HTMLResponse, tags=["PMS"])
async def pms_setup(request: Request, db: Session = Depends(get_db)):
    """Trang cấu hình phòng - chỉ admin"""
    user = _require_login(request)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Không có quyền truy cập")

    branches = db.query(Branch).filter(Branch.branch_code.like('B%')).order_by(Branch.branch_code).all()
    tab = (request.query_params.get("tab") or "types").strip().lower()
    if tab not in ("types", "rooms"):
        tab = "types"
    return templates.TemplateResponse("pms/room_setup.html", {
        "request": request,
        "user": user,
        "active_page": "pms_setup",
        "pms_setup_tab": tab,
        "branches": branches,
        "is_admin": True,
    })