import os
import json
from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from ...db.session import get_db
from ...db.models import (
    Branch, Product, ProductCategory, Warehouse
)

router = APIRouter()

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
templates = Jinja2Templates(directory=os.path.join(APP_ROOT, "app", "templates"))


def _natural_branch_key(branch_code: Optional[str]) -> tuple[int, int, str]:
    code = (branch_code or "").upper()
    if code == "ADMIN":
        return (0, 0, code)
    if code.startswith("B") and code[1:].isdigit():
        return (1, int(code[1:]), code)
    if code:
        return (2, 0, code)
    return (3, 0, "")


def _warehouse_sort_key(warehouse: Warehouse) -> tuple[int, int, int, str, int, str]:
    branch = getattr(warehouse, "branch", None)
    branch_code = getattr(branch, "branch_code", None)
    branch_rank, branch_number, branch_text = _natural_branch_key(branch_code)
    warehouse_type = (warehouse.type or "").upper()
    special_rank = 0 if warehouse_type == "MAIN" or branch_rank == 0 else 1 if warehouse_type == "TRANSIT" else 2
    type_rank = 0 if special_rank < 2 else 1
    return (type_rank, special_rank, branch_number, branch_text, warehouse.sort_order or 0, warehouse.name or "")

@router.get("/", response_class=HTMLResponse)
async def inventory_page(request: Request, db: Session = Depends(get_db)):
    """Trang chủ kho: Hiển thị Dashboard tồn kho"""
    user_data = request.session.get("user")
    if not user_data:
         return templates.TemplateResponse(request, "auth/login.html", {"request": request})

    branches = db.query(Branch).filter(Branch.branch_code.notin_(['admin', 'boss'])).all()
    categories = db.query(ProductCategory).all()

    return templates.TemplateResponse(request, "inventory/master_data.html", {
        "request": request,
        "user": user_data,
        "branches": branches,
        "categories": categories,
        "active_page": "inventory"
    })

@router.get("/manager", response_class=HTMLResponse)
async def manager_dashboard(
    request: Request, 
    page: int = 1,
    per_page: int = 10,
    branch_id: Optional[int] = None,
    warehouse_id: Optional[int] = None, # [NEW]
    db: Session = Depends(get_db)
):
    """Dashboard dành riêng cho Quản lý Kho (Updated: UI giống Reception + Chọn chi nhánh)"""
    user_data = request.session.get("user")
    allowed_roles = ["admin", "manager", "quanly", "boss"]
    if not user_data or user_data.get("role") not in allowed_roles:
         return templates.TemplateResponse(request, "403.html", {"request": request})

    # [NEW] 1. Fetch Branches for Selector
    # Allow Admin to see all branches including 'admin' (Head Office)
    # [MODIFIED] Filter: Only show ADMIN and "Bin Bin Hotel" branches (B1...B17)
    # Hide: KTV, QL, BOSS, DI DONG
    all_branches = db.query(Branch).order_by(Branch.id).all()
    branches = sorted(
        [
            b for b in all_branches
            if b.branch_code.upper() == 'ADMIN' or (b.branch_code.upper().startswith('B') and b.branch_code[1:].isdigit())
        ],
        key=lambda b: _natural_branch_key(b.branch_code)
    )
    
    # [NEW] 2. Determine Current Branch ID & Warehouse ID
    current_branch_id = branch_id # Deprecated but kept for compatibility
    current_warehouse_id = warehouse_id
    
    # Logic: Warehouse selection takes precedence. If Warehouse selected, set Branch automatically.
    # If no warehouse selected, try to find default based on Branch or User.
    
    if current_warehouse_id:
        selected_wh = db.query(Warehouse).get(current_warehouse_id)
        if selected_wh:
            current_branch_id = selected_wh.branch_id # Might be None for Main Warehouse
    
    if not current_warehouse_id:
        # Fallback 1: If branch_id provided, pick first warehouse of that branch
        if branch_id:
            # Check if Admin Branch (ID logic might vary, usually Admin has warehouses with no branch_id)
            # Simplification: Just pick first warehouse linked to this branch
            wh = db.query(Warehouse).filter(Warehouse.branch_id == branch_id).first()
            if wh: 
                current_warehouse_id = int(wh.id)  # type: ignore[arg-type]
        
        # Fallback 2: Default Admin Warehouse (Kho Tổng)
        if not current_warehouse_id:
             # Find "Kho Tổng"
             main_wh = db.query(Warehouse).filter(Warehouse.type == 'MAIN').first()
             if main_wh:
                 current_warehouse_id = int(main_wh.id)  # type: ignore[arg-type]
    
    # Fallback 3: First available warehouse
    if not current_warehouse_id:
        first_wh = db.query(Warehouse).first()
        if first_wh:
            current_warehouse_id = int(first_wh.id)  # type: ignore[arg-type]

    # 3. Fetch Master Data
    products = db.query(Product).options(joinedload(Product.category)).filter(Product.is_active == True).all()
    categories = db.query(ProductCategory).all()
    warehouses = sorted(
        db.query(Warehouse).options(joinedload(Warehouse.branch)).all(),
        key=_warehouse_sort_key
    )

    products_data = [
        {
            "id": p.id, 
            "name": p.name, 
            "code": p.code, 
            "base_unit": p.base_unit, 
            "packing_unit": p.packing_unit or "",
            "conversion_rate": p.conversion_rate,
            "category_id": p.category_id,
            "category_name": p.category.name if p.category else "Khác",
            "cost_price": float(p.cost_price) if p.cost_price else 0.0  # type: ignore[arg-type]
        } for p in products
    ]
    products_json = json.dumps(products_data)
    
    # 4. User Role
    from ...db.models import User
    user_role = user_data.get("role")
    if user_data and user_data.get("id"):
        user_obj = db.query(User).options(joinedload(User.department)).filter(User.id == user_data["id"]).first()
        if user_obj:
             if user_obj.department:
                 user_role = user_obj.department.role_code
             else:
                 user_role = user_obj.role

    # 5. Fetch Initial Requests (with date filter matching client defaults)
    from .requests import get_request_tickets
    
    # [FIX] Sync date filter with client-side Alpine defaults (current month)
    today = date.today()
    default_date_from = date(today.year, today.month, 1).strftime('%Y-%m-%d')
    if today.month == 12:
        next_month_first = date(today.year + 1, 1, 1)
    else:
        next_month_first = date(today.year, today.month + 1, 1)
    last_day = (next_month_first - timedelta(days=1))
    default_date_to = last_day.strftime('%Y-%m-%d')
    
    initial_data = await get_request_tickets(
        dest_warehouse_id=current_warehouse_id,  # type: ignore[arg-type]
        date_from=default_date_from,
        date_to=default_date_to,
        page=page,
        per_page=per_page,
        db=db
    )
    
    if isinstance(initial_data, list):
        initial_records = initial_data
        total_records = len(initial_records)
        total_pages = 1
    else:
        initial_records = initial_data.get("records", [])
        total_records = initial_data.get("totalRecords", 0)
        total_pages = initial_data.get("totalPages", 1)

    return templates.TemplateResponse(request, "inventory/manager/index.html", {
        "request": request,
        "user": user_data,
        "user_role": user_role,
        "products_json": products_json,
        "categories_json": json.dumps([{"id": c.id, "name": c.name} for c in categories]),
        "active_page": "inventory_manager",
        "current_branch_id": current_branch_id,
        "current_warehouse_id": current_warehouse_id, # [NEW]
        "branches": branches,
        "warehouses": warehouses,
        "initial_records": initial_records,
        "total_records": total_records,
        "total_pages": total_pages,
        "current_page": page,
        "per_page": per_page
    })

@router.get("/master-data", response_class=HTMLResponse)
async def master_data_page(request: Request, db: Session = Depends(get_db)):
    """Trang quản lý Danh mục & Sản phẩm & Kho"""
    user_data = request.session.get("user")
    if not user_data or user_data.get("role") not in ["admin", "manager", "quanly", "boss"]:
         return templates.TemplateResponse(request, "403.html", {"request": request})

    branches_list = db.query(Branch).all()

    return templates.TemplateResponse(request, "inventory/master_data/index.html", {
        "request": request,
        "user": user_data,
        "branches": branches_list, 
        "active_page": "inventory_master"
    })

from .requests import get_request_tickets

@router.get("/reception", response_class=HTMLResponse)
async def reception_request_page(
    request: Request, 
    page: int = 1,
    per_page: int = 10,
    db: Session = Depends(get_db)
):
    """Trang tạo yêu cầu cho Lễ tân"""
    user_data = request.session.get("user")
    
    if not user_data:
        return RedirectResponse(url="/login", status_code=302)

    products = db.query(Product).options(joinedload(Product.category)).filter(Product.is_active == True).all()
    categories = db.query(ProductCategory).all()
    
    products_data = [
        {
            "id": p.id, 
            "name": p.name, 
            "code": p.code, 
            "base_unit": p.base_unit, 
            "packing_unit": p.packing_unit or "",
            "conversion_rate": p.conversion_rate,
            "category_id": p.category_id,
            "category_name": p.category.name if p.category else "Khác",
            "cost_price": float(p.cost_price) if p.cost_price else 0.0  # type: ignore[arg-type]
        } for p in products
    ]
    products_json = json.dumps(products_data)
    
    # [FIX] Get user's actual branch from database instead of session
    from ...db.models import User, AttendanceRecord
    
    current_branch_id = None
    user_role = None
    
    if user_data and user_data.get("id"):
        user_id = user_data["id"]
        user_obj = db.query(User).options(joinedload(User.department), joinedload(User.main_branch)).filter(User.id == user_id).first()
        
        if user_obj:
            # 1. PRIORITY: Check for Active Attendance (OT / Current Shift)
            # Find closest attendance record for today
            today = date.today()
            active_attendance = db.query(AttendanceRecord).filter(
                AttendanceRecord.user_id == user_id,
                func.date(AttendanceRecord.attendance_datetime) == today
            ).order_by(AttendanceRecord.attendance_datetime.desc()).first()

            if active_attendance:
                 current_branch_id = active_attendance.branch_id
            
            # 2. FALLBACK: User's Main Branch
            if not current_branch_id and user_obj.main_branch_id:
                current_branch_id = user_obj.main_branch_id
                
            # Get user role from department
            if user_obj.department:
                user_role = user_obj.department.role_code

    warehouses = sorted(
        db.query(Warehouse).options(joinedload(Warehouse.branch)).all(),
        key=_warehouse_sort_key
    )
    
    # [NEW] Find warehouse ID for the current branch
    current_warehouse_id = None
    if current_branch_id:
        # Find the first warehouse belonging to this branch
        branch_warehouse = db.query(Warehouse).filter(Warehouse.branch_id == current_branch_id).first()
        if branch_warehouse:
            current_warehouse_id = int(branch_warehouse.id)  # type: ignore[arg-type]

    
    # [FIX] Fetch initial requests data (with date filter matching client defaults)
    today_r = date.today()
    default_date_from_r = date(today_r.year, today_r.month, 1).strftime('%Y-%m-%d')
    if today_r.month == 12:
        next_month_first_r = date(today_r.year + 1, 1, 1)
    else:
        next_month_first_r = date(today_r.year, today_r.month + 1, 1)
    last_day_r = (next_month_first_r - timedelta(days=1))
    default_date_to_r = last_day_r.strftime('%Y-%m-%d')
    
    initial_data = await get_request_tickets(
        dest_warehouse_id=current_warehouse_id,  # type: ignore[arg-type]
        date_from=default_date_from_r,
        date_to=default_date_to_r,
        page=page,
        per_page=per_page,
        db=db
    )
    
    # Handle empty result/list fallback (safety check)
    if isinstance(initial_data, list):
         # Should not happen if page is passed, but safe defaults
        initial_records = initial_data
        total_records = len(initial_records)
        total_pages = 1
    else:
        initial_records = initial_data.get("records", [])
        total_records = initial_data.get("totalRecords", 0)
        total_pages = initial_data.get("totalPages", 1)

    return templates.TemplateResponse(request, "inventory/reception_request.html", {
        "request": request,
        "user": user_data,
        "user_role": user_role,  # [NEW] Pass role to template
        "products_json": products_json,
        "categories_json": json.dumps([{"id": c.id, "name": c.name} for c in categories]),
        "active_page": "inventory_request",
        "current_branch_id": current_branch_id,
        "current_warehouse_id": current_warehouse_id,  # [NEW] Pass warehouse ID
        "warehouses": warehouses,
        # Pagination Data
        "initial_records": initial_records,
        "total_records": total_records,
        "total_pages": total_pages,
        "current_page": page,
        "per_page": per_page
    })
