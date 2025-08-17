from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi import Query
from typing import Dict

router = APIRouter(prefix="/attendance", tags=["Attendance"])
templates = Jinja2Templates(directory="templates")

# ====== Trang attendance test ======
@router.get("/", response_class=HTMLResponse)
def attendance_page(request: Request):
    # Tạm truyền branch_id để test
    branch_id = "Bin Bin Hotel 1"  
    return templates.TemplateResponse("attendance.html", {
        "request": request,
        "branch_id": branch_id
    })
    result = attendance_service.push_bulk_checkin(records)
    return result

@router.post("/checkin_single")
def checkin_single_endpoint(record: Dict):
    if not record:
        raise HTTPException(status_code=400, detail="Dữ liệu check-in trống")
    result = attendance_service.push_single_checkin(record)
    return result

# ====== API lấy dữ liệu nhân viên từ file employees.py ======
@router.get("/api/employees/by-branch/{branch_id}")
def get_employees_by_branch(branch_id: str, request: Request):
    """
    Lấy danh sách nhân viên theo chi nhánh:
    - Lễ tân: trả về chính lễ tân đó + các nhân viên BP, BV, các bộ phận khác (trừ quản lý, KTV, lễ tân khác)
    - Role khác: trả về đầy đủ nhân viên của chi nhánh (trừ quản lý, KTV)
    """
    def get_role(emp):
        code = emp.get("code", "").upper()
        if "LT" in code:
            return "letan"
        if "BP" in code:
            return "buongphong"
        if "BV" in code:
            return "baove"
        if "QL" in code:
            return "quanly"
        if "KTV" in code:
            return "ktv"
        return "khac"

    user = request.session.get("user")
    result = []

    if user and user.get("role") == "letan":
        for emp in employees:
            if emp["branch"] != branch_id:
                continue
            role = get_role(emp)
            if role in ["quanly", "ktv"]:
                continue
            if role == "letan":
                # Chỉ lấy đúng lễ tân đăng nhập
                if emp.get("code") == user.get("code"):
                    result.append(emp)
            else:
                # Lấy tất cả nhân viên không phải lễ tân
                result.append(emp)
    else:
        # Các role khác: lấy tất cả trừ quản lý và KTV
        for emp in employees:
            if emp["branch"] != branch_id:
                continue
            role = get_role(emp)
            if role not in ["quanly", "ktv"]:
                result.append(emp)

    return result

@router.get("/api/employees/search")
def search_employees(q: str = Query(...)):
    q_lower = q.lower()
    return [emp for emp in employees if q_lower in emp["name"].lower() or q_lower in emp["code"].lower()]

# ====== Trang attendance test ======
@router.get("/", response_class=HTMLResponse)
def attendance_page(request: Request):
    branch_id = "Bin Bin Hotel 1"
    return templates.TemplateResponse("attendance.html", {
        "request": request,
        "branch_id": branch_id
    })