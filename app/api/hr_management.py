# app/api/hr_management.py
# Module quản lý nhân sự - Chỉ dành cho admin và boss

from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional
import os
import calendar
from datetime import datetime, date as date_type, timedelta, timezone
from pathlib import Path

from ..db.session import get_db
from ..db.models import User, Branch, Department, AttendanceRecord, ServiceRecord
from ..core.config import logger
from ..core.utils import VN_TZ

router = APIRouter()

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
templates = Jinja2Templates(directory=os.path.join(APP_ROOT, "templates"))
PROJECT_ROOT = Path(APP_ROOT).parent
AVATAR_UPLOAD_DIR = PROJECT_ROOT / "uploads" / "hr_avatars"

# ====================================================================
# HELPERS
# ====================================================================

def require_admin(request: Request):
    """Dependency: chỉ cho phép admin/boss truy cập."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập.")
    if user.get("role", "").lower() not in ["admin", "boss"]:
        raise HTTPException(status_code=403, detail="Chỉ admin hoặc boss mới có quyền truy cập.")
    return user


def avatar_url_for_user(user_id: int) -> Optional[str]:
    """Avatar lưu dạng file theo user_id, không cần migration DB."""
    for ext in ("webp", "jpg", "jpeg", "png"):
        candidate = AVATAR_UPLOAD_DIR / f"user_{user_id}.{ext}"
        if candidate.exists():
            return f"/uploads/hr_avatars/{candidate.name}?v={int(candidate.stat().st_mtime)}"
    return None


def user_to_dict(user: User) -> dict:
    # Tính số ngày hoạt động kể từ ngày tạo
    account_age_days = None
    if user.created_at:
        now = datetime.now(timezone.utc)
        created = user.created_at
        if created.tzinfo is None:
            from datetime import timezone as _tz
            created = created.replace(tzinfo=_tz.utc)
        account_age_days = (now - created).days

    return {
        "id": user.id,
        "employee_id": user.employee_id,
        "employee_code": user.employee_code,
        "name": user.name,
        "department_id": user.department_id,
        "department_name": user.department.name if user.department else None,
        "role_code": user.department.role_code if user.department else None,
        "main_branch_id": user.main_branch_id,
        "branch_name": user.main_branch.name if user.main_branch else None,
        "branch_code": user.main_branch.branch_code if user.main_branch else None,
        "shift": user.shift,
        "is_active": user.is_active,
        "phone_number": user.phone_number,
        "email": user.email,
        "avatar_url": avatar_url_for_user(user.id),
        # Thông tin cá nhân bổ sung
        "cccd": user.cccd,
        "date_of_birth": user.date_of_birth.isoformat() if user.date_of_birth else None,
        "address": user.address,
        "gender": user.gender,
        # Thời gian hoạt động
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "account_age_days": account_age_days,
    }


def get_month_bounds(year: Optional[int], month: Optional[int]) -> tuple[datetime, datetime, int, int]:
    now = datetime.now(VN_TZ)
    selected_year = year or now.year
    selected_month = month or now.month
    if selected_month < 1 or selected_month > 12:
        raise HTTPException(status_code=400, detail="Tháng không hợp lệ.")
    start_date = date_type(selected_year, selected_month, 1)
    next_month = date_type(selected_year + 1, 1, 1) if selected_month == 12 else date_type(selected_year, selected_month + 1, 1)
    return (
        VN_TZ.localize(datetime.combine(start_date, datetime.min.time())),
        VN_TZ.localize(datetime.combine(next_month, datetime.min.time())),
        selected_year,
        selected_month,
    )


def get_work_day(dt: datetime) -> date_type:
    local_dt = dt.astimezone(VN_TZ) if dt.tzinfo else dt.replace(tzinfo=timezone.utc).astimezone(VN_TZ)
    return local_dt.date() - timedelta(days=1) if local_dt.hour < 7 else local_dt.date()


def normalize_service_type(service_type: Optional[str]) -> str:
    value = (service_type or "").strip().lower()
    if value in {"giặt", "giat", "laundry"} or "giặt" in value or "giat" in value:
        return "laundry"
    if value in {"ủi", "ui", "là", "la", "ironing"} or "ủi" in value or "ui" in value:
        return "ironing"
    return "other"


# ====================================================================
# PYDANTIC SCHEMAS
# ====================================================================

class EmployeeCreate(BaseModel):
    employee_id: str
    employee_code: str
    name: str
    department_id: int
    main_branch_id: int
    shift: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = "123456"
    is_active: Optional[bool] = True

class EmployeeUpdate(BaseModel):
    employee_code: Optional[str] = None
    name: Optional[str] = None
    department_id: Optional[int] = None
    main_branch_id: Optional[int] = None
    shift: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    # Thông tin cá nhân bổ sung
    cccd: Optional[str] = None
    date_of_birth: Optional[str] = None  # ISO date string: "YYYY-MM-DD"
    address: Optional[str] = None
    gender: Optional[str] = None  # Nam / Nữ / Khác

class ResetPasswordPayload(BaseModel):
    new_password: str

class BranchUpdate(BaseModel):
    name: str

class EmployeeCreateFull(BaseModel):
    employee_id: str
    employee_code: str
    name: str
    department_id: int
    main_branch_id: int
    shift: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = "123456"
    is_active: Optional[bool] = True
    # Thông tin cá nhân bổ sung
    cccd: Optional[str] = None
    date_of_birth: Optional[str] = None  # ISO date string: "YYYY-MM-DD"
    address: Optional[str] = None
    gender: Optional[str] = None  # Nam / Nữ / Khác


# ====================================================================
# PAGE ROUTE
# ====================================================================

@router.get("/admin/hr", response_class=HTMLResponse)
def hr_management_page(request: Request, _=Depends(require_admin)):
    """Trang quản lý nhân sự - chỉ admin/boss."""
    user = dict(request.session.get("user") or {})
    if user.get("id"):
        user["avatar_url"] = avatar_url_for_user(user["id"])
    return templates.TemplateResponse(request, "hr_management.html", {
        "request": request,
        "user": user,
        "active_page": "hr-management",
    })


# ====================================================================
# EMPLOYEE ENDPOINTS
# ====================================================================

@router.get("/api/hr/employees", response_class=JSONResponse)
def get_employees(
    request: Request,
    branch_id: Optional[int] = None,
    department_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    sort_by: Optional[str] = "branch",
    sort_dir: Optional[str] = "asc",
    db: Session = Depends(get_db),
    _=Depends(require_admin)
):
    """Lấy danh sách nhân viên với bộ lọc và sắp xếp an toàn."""
    query = db.query(User).options(
        joinedload(User.department),
        joinedload(User.main_branch)
    )

    if branch_id is not None:
        query = query.filter(User.main_branch_id == branch_id)
    if department_id is not None:
        query = query.filter(User.department_id == department_id)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (User.name.ilike(pattern)) |
            (User.employee_code.ilike(pattern)) |
            (User.employee_id.ilike(pattern))
        )

    sort_key = (sort_by or "branch").lower()
    sort_direction = (sort_dir or "asc").lower()
    if sort_direction not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="Hướng sắp xếp không hợp lệ.")

    sort_columns = {
        "employee_id": [User.employee_id, User.name],
        "name": [User.name, User.employee_id],
        "employee_code": [User.employee_code, User.name],
        "branch": [Branch.branch_code, Branch.name, User.name],
        "branch_code": [Branch.branch_code, Branch.name, User.name],
        "branch_name": [Branch.name, Branch.branch_code, User.name],
        "role": [Department.name, Department.role_code, User.name],
        "department": [Department.name, Department.role_code, User.name],
        "department_name": [Department.name, Department.role_code, User.name],
        "shift": [User.shift, User.name],
        "status": [User.is_active, User.name],
        "is_active": [User.is_active, User.name],
        "created_at": [User.created_at, User.name],
    }
    if sort_key not in sort_columns:
        raise HTTPException(status_code=400, detail="Cột sắp xếp không hợp lệ.")

    if sort_key in {"branch", "branch_code", "branch_name"}:
        query = query.outerjoin(User.main_branch)
    elif sort_key in {"role", "department", "department_name"}:
        query = query.outerjoin(User.department)

    descending = sort_direction == "desc"
    order_by = []
    for index, column in enumerate(sort_columns[sort_key]):
        reverse = descending and index == 0
        order_by.append(column.desc() if reverse else column.asc())
    order_by.append(User.id.asc())

    users = query.order_by(*order_by).all()
    return JSONResponse(content=[user_to_dict(u) for u in users])


@router.get("/api/hr/dashboard", response_class=JSONResponse)
def get_hr_dashboard(
    request: Request,
    year: Optional[int] = None,
    month: Optional[int] = None,
    branch_id: Optional[int] = None,
    department_id: Optional[int] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(require_admin)
):
    """Dashboard nhân sự theo tháng: công, nghỉ, giặt/ủi, sinh nhật, giới tính."""
    start_dt, end_dt, selected_year, selected_month = get_month_bounds(year, month)
    today = datetime.now(VN_TZ).date()
    month_last_day = date_type(selected_year, selected_month, calendar.monthrange(selected_year, selected_month)[1])
    days_to_count = today.day if selected_year == today.year and selected_month == today.month else month_last_day.day

    employee_query = db.query(User).options(joinedload(User.department), joinedload(User.main_branch))
    if branch_id is not None:
        employee_query = employee_query.filter(User.main_branch_id == branch_id)
    if department_id is not None:
        employee_query = employee_query.filter(User.department_id == department_id)
    if search:
        pattern = f"%{search}%"
        employee_query = employee_query.filter(
            (User.name.ilike(pattern)) |
            (User.employee_code.ilike(pattern)) |
            (User.employee_id.ilike(pattern))
        )

    employee_pool = employee_query.order_by(User.main_branch_id, User.name).all()
    employee_ids = [u.id for u in employee_pool]
    employee_stats = {
        u.id: {
            "employee": user_to_dict(u),
            "total_work_units": 0.0,
            "worked_days": set(),
            "absence_days": 0,
            "laundry_quantity": 0,
            "ironing_quantity": 0,
            "overtime_days": set(),
        }
        for u in employee_pool
    }

    if employee_ids:
        attendance_query = db.query(AttendanceRecord).filter(
            AttendanceRecord.user_id.in_(employee_ids),
            AttendanceRecord.attendance_datetime >= start_dt,
            AttendanceRecord.attendance_datetime < end_dt,
        )
        if branch_id is not None:
            attendance_query = attendance_query.filter(AttendanceRecord.branch_id == branch_id)
        attendance_records = attendance_query.all()

        for rec in attendance_records:
            stat = employee_stats.get(rec.user_id)
            if not stat:
                continue
            work_units = float(rec.work_units or 0)
            stat["total_work_units"] += work_units
            work_day = get_work_day(rec.attendance_datetime)
            if work_day.month == selected_month and work_day.year == selected_year and work_units > 0:
                stat["worked_days"].add(work_day)
            if rec.is_overtime or work_units > 1:
                stat["overtime_days"].add(work_day)

        service_query = db.query(ServiceRecord).filter(
            ServiceRecord.user_id.in_(employee_ids),
            ServiceRecord.service_datetime >= start_dt,
            ServiceRecord.service_datetime < end_dt,
        )
        if branch_id is not None:
            service_query = service_query.filter(ServiceRecord.branch_id == branch_id)
        service_records = service_query.all()

        for rec in service_records:
            stat = employee_stats.get(rec.user_id)
            if not stat:
                continue
            quantity = int(rec.quantity or 0)
            service_kind = normalize_service_type(rec.service_type)
            if service_kind == "laundry":
                stat["laundry_quantity"] += quantity
            elif service_kind == "ironing":
                stat["ironing_quantity"] += quantity

    for stat in employee_stats.values():
        stat["absence_days"] = max(0, days_to_count - len(stat["worked_days"]))

    rows = []
    for stat in employee_stats.values():
        emp = stat["employee"]
        rows.append({
            **emp,
            "total_work_units": round(stat["total_work_units"], 2),
            "worked_days": len(stat["worked_days"]),
            "absence_days": stat["absence_days"],
            "laundry_quantity": stat["laundry_quantity"],
            "ironing_quantity": stat["ironing_quantity"],
            "overtime_days": len(stat["overtime_days"]),
        })

    active_rows = [r for r in rows if r.get("is_active")]
    gender_counts = {
        "male": sum(1 for r in active_rows if (r.get("gender") or "").strip().lower() in {"nam", "male", "m"}),
        "female": sum(1 for r in active_rows if (r.get("gender") or "").strip().lower() in {"nữ", "nu", "female", "f"}),
    }
    gender_counts["other"] = max(0, len(active_rows) - gender_counts["male"] - gender_counts["female"])

    birthdays = sorted(
        [
            r for r in active_rows
            if r.get("date_of_birth") and date_type.fromisoformat(r["date_of_birth"]).month == selected_month
        ],
        key=lambda r: (date_type.fromisoformat(r["date_of_birth"]).day, r.get("name") or "")
    )

    branch_staff = [
        r for r in active_rows
        if branch_id is None or r.get("main_branch_id") == branch_id
    ]

    today_start = VN_TZ.localize(datetime.combine(today, datetime.min.time()))
    today_end = today_start + timedelta(days=1)
    today_active_by_user = {}
    if employee_ids:
        today_active_query = (
            db.query(AttendanceRecord)
            .options(joinedload(AttendanceRecord.user), joinedload(AttendanceRecord.branch))
            .filter(
                AttendanceRecord.user_id.in_(employee_ids),
                AttendanceRecord.attendance_datetime >= today_start,
                AttendanceRecord.attendance_datetime < today_end,
                AttendanceRecord.work_units > 0,
            )
        )
        if branch_id is not None:
            today_active_query = today_active_query.filter(AttendanceRecord.branch_id == branch_id)
        for rec in today_active_query.all():
            if rec.user and rec.user.is_active:
                today_active_by_user[rec.user_id] = {
                    **user_to_dict(rec.user),
                    "active_branch_code": rec.branch.branch_code if rec.branch else None,
                    "active_branch_name": rec.branch.name if rec.branch else None,
                }

    def top_by(key: str, reverse: bool = True):
        import re as _re
        hotel_rows = [r for r in active_rows if _re.match(r"^B\d+$", str(r.get("branch_code") or ""), _re.IGNORECASE)]
        if reverse:
            ranked = sorted(hotel_rows, key=lambda r: (-(r.get(key) or 0), r.get("name") or ""))
        else:
            ranked = sorted(hotel_rows, key=lambda r: (r.get(key) or 0, r.get("name") or ""))
        return ranked[:5]

    total_work_units = sum(r["total_work_units"] for r in active_rows)
    total_laundry = sum(r["laundry_quantity"] for r in active_rows)
    total_ironing = sum(r["ironing_quantity"] for r in active_rows)

    return JSONResponse(content={
        "period": {
            "year": selected_year,
            "month": selected_month,
            "days_to_count": days_to_count,
        },
        "summary": {
            "active_employees": len(active_rows),
            "inactive_employees": len(rows) - len(active_rows),
            "total_work_units": round(total_work_units, 2),
            "total_absence_days": sum(r["absence_days"] for r in active_rows),
            "total_laundry": total_laundry,
            "total_ironing": total_ironing,
            "birthday_count": len(birthdays),
            "male_count": gender_counts["male"],
            "female_count": gender_counts["female"],
            "other_gender_count": gender_counts["other"],
            "branch_staff_count": len(branch_staff),
            "today_active_count": len(today_active_by_user),
        },
        "rankings": {
            "most_work": top_by("total_work_units"),
            "most_absent": top_by("absence_days"),
            "most_laundry": top_by("laundry_quantity"),
            "most_ironing": top_by("ironing_quantity"),
        },
        "birthdays": birthdays,
        "gender_counts": gender_counts,
        "branch_staff": sorted(branch_staff, key=lambda r: (r.get("department_name") or "", r.get("name") or ""))[:20],
        "today_active_employees": sorted(today_active_by_user.values(), key=lambda r: (r.get("active_branch_code") or "", r.get("name") or "")),
        "employees": sorted(active_rows, key=lambda r: (-(r.get("total_work_units") or 0), r.get("name") or "")),
    })


@router.post("/api/hr/me/avatar", response_class=JSONResponse)
async def upload_my_avatar(
    request: Request,
    file: UploadFile = File(...),
    _=Depends(require_admin)
):
    """Cập nhật ảnh đại diện cho người đang đăng nhập."""
    user = request.session.get("user") or {}
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập.")

    content_type = (file.content_type or "").lower()
    allowed_types = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }
    if content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ ảnh JPG, PNG hoặc WEBP.")

    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Ảnh đại diện tối đa 2MB.")

    AVATAR_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for old_file in AVATAR_UPLOAD_DIR.glob(f"user_{user_id}.*"):
        old_file.unlink(missing_ok=True)

    ext = allowed_types[content_type]
    avatar_path = AVATAR_UPLOAD_DIR / f"user_{user_id}.{ext}"
    avatar_path.write_bytes(content)

    avatar_url = avatar_url_for_user(user_id)
    request.session["user"]["avatar_url"] = avatar_url
    logger.info(f"[HR] Cập nhật ảnh đại diện user_id={user_id}")
    return JSONResponse(content={"success": True, "avatar_url": avatar_url})


@router.post("/api/hr/employees", response_class=JSONResponse)
def create_employee(
    request: Request,
    payload: EmployeeCreateFull,
    db: Session = Depends(get_db),
    _=Depends(require_admin)
):
    """Tạo nhân viên mới."""
    # Kiểm tra trùng employee_id / employee_code
    existing_by_id = db.query(User).filter(User.employee_id == payload.employee_id).first()
    if existing_by_id:
        raise HTTPException(status_code=400, detail=f"Mã nhân viên '{payload.employee_id}' đã tồn tại.")

    existing_by_code = db.query(User).filter(User.employee_code == payload.employee_code).first()
    if existing_by_code:
        raise HTTPException(status_code=400, detail=f"Mã đăng nhập '{payload.employee_code}' đã tồn tại.")

    # Kiểm tra branch và department hợp lệ
    branch = db.query(Branch).filter(Branch.id == payload.main_branch_id).first()
    if not branch:
        raise HTTPException(status_code=400, detail="Chi nhánh không tồn tại.")

    department = db.query(Department).filter(Department.id == payload.department_id).first()
    if not department:
        raise HTTPException(status_code=400, detail="Phòng ban không tồn tại.")

    new_user = User(
        employee_id=payload.employee_id,
        employee_code=payload.employee_code,
        name=payload.name,
        department_id=payload.department_id,
        main_branch_id=payload.main_branch_id,
        shift=payload.shift,
        phone_number=payload.phone_number,
        email=payload.email,
        password=payload.password or "123456",
        is_active=payload.is_active if payload.is_active is not None else True,
        cccd=payload.cccd,
        date_of_birth=date_type.fromisoformat(payload.date_of_birth) if payload.date_of_birth else None,
        address=payload.address,
        gender=payload.gender,
    )
    db.add(new_user)
    try:
        db.commit()
        db.refresh(new_user)
        # Re-load relationships
        db.refresh(new_user)
        user = db.query(User).options(
            joinedload(User.department),
            joinedload(User.main_branch)
        ).filter(User.id == new_user.id).first()
        logger.info(f"[HR] Tạo nhân viên mới: {new_user.name} ({new_user.employee_id})")
        return JSONResponse(content={"success": True, "employee": user_to_dict(user)})
    except Exception as e:
        db.rollback()
        logger.error(f"[HR] Lỗi tạo nhân viên: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi hệ thống khi tạo nhân viên.")


@router.put("/api/hr/employees/{user_id}", response_class=JSONResponse)
def update_employee(
    request: Request,
    user_id: int,
    payload: EmployeeUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_admin)
):
    """Cập nhật thông tin nhân viên."""
    user = db.query(User).options(
        joinedload(User.department),
        joinedload(User.main_branch)
    ).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="Nhân viên không tồn tại.")

    if payload.employee_code is not None:
        # Kiểm tra không bị trùng code với người khác
        conflict = db.query(User).filter(
            User.employee_code == payload.employee_code,
            User.id != user_id
        ).first()
        if conflict:
            raise HTTPException(status_code=400, detail=f"Mã đăng nhập '{payload.employee_code}' đã được dùng bởi nhân viên khác.")
        user.employee_code = payload.employee_code

    if payload.name is not None:
        user.name = payload.name
    if payload.department_id is not None:
        dept = db.query(Department).filter(Department.id == payload.department_id).first()
        if not dept:
            raise HTTPException(status_code=400, detail="Phòng ban không tồn tại.")
        user.department_id = payload.department_id
    if payload.main_branch_id is not None:
        branch = db.query(Branch).filter(Branch.id == payload.main_branch_id).first()
        if not branch:
            raise HTTPException(status_code=400, detail="Chi nhánh không tồn tại.")
        user.main_branch_id = payload.main_branch_id
    if payload.shift is not None:
        user.shift = payload.shift
    if payload.phone_number is not None:
        user.phone_number = payload.phone_number
    if payload.email is not None:
        user.email = payload.email
    if payload.is_active is not None:
        user.is_active = payload.is_active
    # Thông tin cá nhân bổ sung
    if payload.cccd is not None:
        user.cccd = payload.cccd if payload.cccd.strip() else None
    if payload.date_of_birth is not None:
        user.date_of_birth = date_type.fromisoformat(payload.date_of_birth) if payload.date_of_birth.strip() else None
    if payload.address is not None:
        user.address = payload.address if payload.address.strip() else None
    if payload.gender is not None:
        user.gender = payload.gender if payload.gender.strip() else None

    try:
        db.commit()
        # Re-load relationships after commit
        updated_user = db.query(User).options(
            joinedload(User.department),
            joinedload(User.main_branch)
        ).filter(User.id == user_id).first()
        logger.info(f"[HR] Cập nhật nhân viên: {user.name} ({user.employee_id})")
        return JSONResponse(content={"success": True, "employee": user_to_dict(updated_user)})
    except Exception as e:
        db.rollback()
        logger.error(f"[HR] Lỗi cập nhật nhân viên: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi hệ thống khi cập nhật nhân viên.")


@router.post("/api/hr/employees/{user_id}/reset-password", response_class=JSONResponse)
def reset_employee_password(
    request: Request,
    user_id: int,
    payload: ResetPasswordPayload,
    db: Session = Depends(get_db),
    _=Depends(require_admin)
):
    """Đặt lại mật khẩu cho nhân viên."""
    if not payload.new_password or len(payload.new_password) < 4:
        raise HTTPException(status_code=400, detail="Mật khẩu phải có ít nhất 4 ký tự.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Nhân viên không tồn tại.")

    user.password = payload.new_password
    try:
        db.commit()
        logger.info(f"[HR] Đặt lại mật khẩu cho: {user.name} ({user.employee_id})")
        return JSONResponse(content={"success": True, "message": f"Đã đặt lại mật khẩu cho {user.name}."})
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Lỗi hệ thống khi đặt lại mật khẩu.")


# ====================================================================
# BRANCH ENDPOINTS
# ====================================================================

@router.get("/api/hr/branches", response_class=JSONResponse)
def get_branches(
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(require_admin)
):
    """Lấy danh sách chi nhánh kèm số lượng nhân viên active."""
    from sqlalchemy import text
    branches = db.query(Branch).order_by(
        text("CAST(NULLIF(REGEXP_REPLACE(branch_code, '[^0-9]', '', 'g'), '') AS INTEGER) NULLS LAST"),
        Branch.branch_code
    ).all()

    # Đếm số nhân viên active theo branch
    counts = dict(
        db.query(User.main_branch_id, func.count(User.id))
        .filter(User.is_active == True)
        .group_by(User.main_branch_id)
        .all()
    )

    result = []
    for b in branches:
        result.append({
            "id": b.id,
            "branch_code": b.branch_code,
            "name": b.name,
            "address": b.address,
            "active_employee_count": counts.get(b.id, 0),
        })
    return JSONResponse(content=result)


@router.put("/api/hr/branches/{branch_id}", response_class=JSONResponse)
def update_branch(
    request: Request,
    branch_id: int,
    payload: BranchUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_admin)
):
    """Cập nhật tên chi nhánh."""
    branch = db.query(Branch).filter(Branch.id == branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Chi nhánh không tồn tại.")

    if not payload.name or not payload.name.strip():
        raise HTTPException(status_code=400, detail="Tên chi nhánh không được để trống.")

    old_name = branch.name
    branch.name = payload.name.strip()
    try:
        db.commit()
        logger.info(f"[HR] Đổi tên chi nhánh {branch.branch_code}: '{old_name}' → '{branch.name}'")
        return JSONResponse(content={
            "success": True,
            "message": f"Đã đổi tên thành công.",
            "branch": {"id": branch.id, "branch_code": branch.branch_code, "name": branch.name}
        })
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Lỗi hệ thống khi cập nhật chi nhánh.")


# ====================================================================
# DEPARTMENT ENDPOINTS
# ====================================================================

@router.get("/api/hr/departments", response_class=JSONResponse)
def get_departments(
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(require_admin)
):
    """Lấy danh sách phòng ban/role (bỏ boss và khac)."""
    EXCLUDED_ROLES = {"boss", "khac"}
    departments = (
        db.query(Department)
        .filter(~Department.role_code.in_(EXCLUDED_ROLES))
        .order_by(Department.name)
        .all()
    )
    return JSONResponse(content=[
        {"id": d.id, "role_code": d.role_code, "name": d.name}
        for d in departments
    ])
