# app/api/hr_management.py
# Module quản lý nhân sự - Chỉ dành cho admin và boss

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional
import os
from datetime import datetime, date as date_type, timezone

from ..db.session import get_db
from ..db.models import User, Branch, Department
from ..core.config import logger

router = APIRouter()

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
templates = Jinja2Templates(directory=os.path.join(APP_ROOT, "templates"))

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
        # Thông tin cá nhân bổ sung
        "cccd": user.cccd,
        "date_of_birth": user.date_of_birth.isoformat() if user.date_of_birth else None,
        "address": user.address,
        # Thời gian hoạt động
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "account_age_days": account_age_days,
    }


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


# ====================================================================
# PAGE ROUTE
# ====================================================================

@router.get("/admin/hr", response_class=HTMLResponse)
def hr_management_page(request: Request, _=Depends(require_admin)):
    """Trang quản lý nhân sự - chỉ admin/boss."""
    user = request.session.get("user")
    return templates.TemplateResponse("hr_management.html", {
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
    db: Session = Depends(get_db),
    _=Depends(require_admin)
):
    """Lấy danh sách nhân viên với bộ lọc."""
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

    users = query.order_by(User.main_branch_id, User.name).all()
    return JSONResponse(content=[user_to_dict(u) for u in users])


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
