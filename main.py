from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from utils import parse_datetime_input, format_datetime_display, is_overdue

from database import SessionLocal
from models import User, Task
from config import DATABASE_URL, SMTP_CONFIG, ALERT_EMAIL
from database import init_db

from sqlalchemy.orm import Session
from sqlalchemy import or_, cast, Date
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
import os, asyncio, re, json 
from email.message import EmailMessage 
import aiosmtplib
from datetime import datetime, timedelta, timezone

from employees import employees  # import danh sách nhân viên tĩnh

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Định nghĩa múi giờ Việt Nam (UTC+7)
VN_TZ = timezone(timedelta(hours=7))

from urllib.parse import parse_qs, urlencode

def clean_query_string(query: str) -> str:
    parsed = parse_qs(query)
    # Loại bỏ các key không mong muốn
    parsed.pop("success", None)
    parsed.pop("action", None)
    return urlencode(parsed, doseq=True)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="binbin-hotel-secret")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

BRANCHES = [
    "B1", "B2", "B3",
    "B5", "B6", "B7",
    "B8", "B9", "B10",
    "B11", "B12", "B14",
    "B15"
]

from math import radians, cos, sin, sqrt, atan2

branchCoordinates = {
    "B1": [10.727298831515066,106.6967154830272],
    "B2": [10.740600,106.695797],
    "B3": [10.733902,106.708781],
    "B5": [10.73780906347085,106.70517496567874],
    "B6": [10.729986861681768,106.70690372549372],
    "B7": [10.744230207012244,106.6965025304644],
    "B8": [10.741408,106.699883],
    "B9": [10.740970,106.699825],
    "B10": [10.814503,106.670873],
    "B11": [10.77497650247788,106.75134333045331],
    "B12": [10.778874744587053,106.75266727478706],
    "B14": [10.742557513695218,106.69945313180673],
    "B15": [10.775572501574938,106.75167172807936],
}

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # bán kính trái đất km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

@app.post("/attendance/api/detect-branch")
async def detect_branch(request: Request):
    data = await request.json()
    lat, lng = data.get("lat"), data.get("lng")
    if lat is None or lng is None:
        return JSONResponse({"error": "Thiếu tọa độ"}, status_code=400)

    nearest_branch = None
    min_distance = float("inf")
    for branch, coords in branchCoordinates.items():
        dist = haversine(lat, lng, coords[0], coords[1])
        if dist < min_distance:
            min_distance = dist
            nearest_branch = branch

    # Nếu khoảng cách quá xa (>1km) thì coi như không hợp lệ
    if min_distance > 1:
        return JSONResponse({"error": "Không xác định được chi nhánh"}, status_code=404)

    # Lưu vào session để UI tự nhận
    request.session["active_branch"] = nearest_branch
    return {"branch": nearest_branch, "distance_km": round(min_distance, 3)}

@app.get("/attendance/ui", response_class=HTMLResponse)
def attendance_ui(request: Request):
    ua = request.headers.get("user-agent", "").lower()
    if not ("mobi" in ua or "android" in ua or "iphone" in ua):
        return HTMLResponse("<h2>Chỉ hỗ trợ trên điện thoại!</h2>", status_code=403)

    user_data = request.session.get("user")
    if not user_data:
        return RedirectResponse("/login", status_code=303)
    active_branch = request.session.get("active_branch") or user_data.get("branch", "")
    csrf_token = get_csrf_token(request)
    return templates.TemplateResponse("attendance.html", {
        "request": request,
        "branch_id": active_branch,
        "csrf_token": csrf_token,
        "branches": BRANCHES,
        "user": user_data,
        "login_code": user_data.get("code", ""),
    })

from urllib.parse import urlencode

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    """Route gốc, chuyển hướng người dùng dựa trên trạng thái đăng nhập."""
    if request.session.get("user"):
        return RedirectResponse("/home", status_code=303)
    return RedirectResponse("/login", status_code=303)

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    # Nếu người dùng đã đăng nhập VÀ đây không phải là redirect sau khi đăng nhập thành công,
    # thì mới chuyển hướng về trang chủ.
    if request.session.get("user") and "success=1" not in str(request.query_params):
        return RedirectResponse("/home", status_code=303)
    error = request.query_params.get("error", "")
    role = request.query_params.get("role", "")
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
        "role": role
    })



@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    request.session.clear()
    # Chỉ cho phép các role được đăng nhập
    allowed_roles = ["letan", "quanly", "ktv", "admin", "boss"]
    user = db.query(User).filter(
        User.code == username,
        User.password == password,
        User.role.in_(allowed_roles)
    ).first()

    if user:
        request.session["user"] = {
            "code": user.code,
            "role": user.role,
            "branch": user.branch,
            "name": user.name
        }
        return RedirectResponse("/login?success=1", status_code=303)
    else:
        guessed_role = ""
        if username.lower().startswith("b") and "lt" in username.lower():
            guessed_role = "letan"
        elif username.lower().startswith("ktv"):
            guessed_role = "ktv"
        elif username.lower() in ["ql", "admin"]:
            guessed_role = "quanly"

        query = urlencode({
            "error": "Mã nhân viên hoặc mật khẩu sai",
            "role": guessed_role
        })
        return RedirectResponse(f"/login?{query}", status_code=303)

@app.get("/choose-function", response_class=HTMLResponse)
def choose_function_page(request: Request):
    user_data = request.session.get("user")
    if not user_data:
        return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse("choose_function.html", {
        "request": request,
        "user": user_data
    })

from fastapi import APIRouter
import secrets

attendance_router = APIRouter(prefix="/attendance", tags=["Attendance"])

# --- CSRF Token Management ---
def generate_csrf_token():
    return secrets.token_urlsafe(32)

def get_csrf_token(request: Request):
    token = request.session.get("csrf_token")
    if not token:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
    return token

def validate_csrf(request: Request):
    token = request.headers.get("X-CSRF-Token") or request.query_params.get("csrf_token")
    session_token = request.session.get("csrf_token")
    if not session_token or token != session_token:
        raise HTTPException(status_code=403, detail="CSRF token không hợp lệ")

# --- Attendance UI ---
@app.get("/attendance/ui", response_class=HTMLResponse)
def attendance_ui(request: Request):
    user_data = request.session.get("user")
    if not user_data:
        return RedirectResponse("/login", status_code=303)
    active_branch = request.session.get("active_branch") or user_data.get("branch", "")
    csrf_token = get_csrf_token(request)
    # Truyền mã nhân viên đăng nhập cho frontend để luôn hiển thị trong danh sách điểm danh
    return templates.TemplateResponse("attendance.html", {
        "request": request,
        "branch_id": active_branch,
        "csrf_token": csrf_token,
        # "branches": BRANCHES,
        "user": user_data,
        "login_code": user_data.get("code", ""),  # thêm dòng này
    })

# --- Switch active branch ---
# @app.post("/attendance/switch-branch")
# async def switch_branch(request: Request, branch_id: str = Form(...)):
#     user = request.session.get("user")
#     if not user:
#         return RedirectResponse("/login", status_code=303)
#     # Only letan and quanly can switch branch
#     if user.get("role") not in ["letan", "quanly"]:
#         raise HTTPException(status_code=403, detail="Không có quyền đổi chi nhánh")
#     request.session["active_branch"] = branch_id
#     # Audit log
#     print(f"[AUDIT] {user['code']} switched active branch to {branch_id}")
#     return RedirectResponse("/attendance/ui", status_code=303)

# --- Get CSRF token ---
@app.get("/attendance/csrf-token")
def attendance_csrf_token(request: Request):
    token = get_csrf_token(request)
    return {"csrf_token": token}

# --- Employees by branch (include 'all') ---
@app.get("/attendance/api/employees/by-branch/{branch_id}", response_class=JSONResponse)
def get_employees_by_branch(branch_id: str, db: Session = Depends(get_db), request: Request = None):
    try:
        user = request.session.get("user") if request else None
        now_hour = datetime.now(VN_TZ).hour
        # Xác định ca dựa theo giờ
        shift_code = "CS" if 7 <= now_hour < 19 else "CT"

        def filter_by_shift(query):
            return query.filter(User.code.ilike(f"%{shift_code}%"))

        if user and user.get("role") == "letan":
            # Lấy chính lễ tân đang đăng nhập (chỉ nếu mã của họ đúng ca)
            lt_self = db.query(User).filter(
                User.code == user.get("code"),
                User.branch == branch_id,
                User.code.ilike(f"%{shift_code}%")
            )

            # Lấy các bộ phận khác cùng chi nhánh, bỏ quản lý, KTV, lễ tân khác
            others = db.query(User).filter(
                User.branch == branch_id,
                ~User.role.in_(["quanly", "ktv", "letan"]),
                User.code.ilike(f"%{shift_code}%")
            )

            employees = lt_self.union_all(others).order_by(User.name).all()

        else:
            # Các role khác: lấy toàn bộ (trừ quản lý, KTV) theo ca
            employees = db.query(User).filter(
                User.branch == branch_id,
                ~User.role.in_(["quanly", "ktv"]),
                User.code.ilike(f"%{shift_code}%")
            ).order_by(User.name).all()

        employee_list = [
            {
                "code": emp.code,
                "name": emp.name,
                "department": emp.role,
                "branch": emp.branch,
            }
            for emp in employees
        ]
        return JSONResponse(content=employee_list)

    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Lỗi server: {str(e)}"})

# --- Employee search ---
@app.get("/attendance/api/employees/search", response_class=JSONResponse)
def search_employees(q: str = "", db: Session = Depends(get_db)):
    """
    API để tìm kiếm nhân viên theo mã hoặc tên để thêm vào danh sách điểm danh.
    """
    if not q:
        return JSONResponse(content=[], status_code=400)

    search_pattern = f"%{q}%"
    employees = db.query(User).filter(
        or_(User.code.ilike(search_pattern), User.name.ilike(search_pattern))
    ).limit(20).all()  # Giới hạn 20 kết quả để tránh quá tải

    employee_list = [{"code": emp.code, "name": emp.name, "department": emp.role, "branch": emp.branch} for emp in employees]
    return JSONResponse(content=employee_list)

def serialize_task(task: dict) -> dict:
    def to_str(val):
        if isinstance(val, datetime):
            return val.isoformat()
        return val or ""

    return {
        "id": task.get("id"),
        "chi_nhanh": task.get("chi_nhanh"),
        "phong": task.get("phong"),
        "mo_ta": task.get("mo_ta"),
        "ngay_tao": to_str(task.get("ngay_tao")),
        "han_hoan_thanh": format_datetime_display(task.get("han_hoan_thanh"), with_time=False),
        "han_hoan_thanh_raw": to_str(task.get("han_hoan_thanh")),
        "trang_thai": task.get("trang_thai"),
        "nguoi_tao": task.get("nguoi_tao"),
        "ghi_chu": task.get("ghi_chu") or "",
        "nguoi_thuc_hien": task.get("nguoi_thuc_hien", ""),
        "ngay_hoan_thanh": to_str(task.get("ngay_hoan_thanh")),
        "han_hoan_thanh": task.get("han_hoan_thanh"),
    }

@app.get("/home", response_class=HTMLResponse)
def home(request: Request, chi_nhanh: str = "", search: str = "", trang_thai: str = "", han_hoan_thanh: str = "", page: int = 1, per_page: int = 8, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    today = datetime.now(VN_TZ)
    if page == 1 and not search and not trang_thai and not han_hoan_thanh:
        overdue_tasks = db.query(Task).filter(
            Task.trang_thai == "Đang chờ",
            Task.han_hoan_thanh < today
        ).all()
        for t in overdue_tasks:
            t.trang_thai = "Quá hạn"
        if overdue_tasks:
            db.commit()

    if not user_data:
        return RedirectResponse("/login", status_code=303)

    # Tiếp tục xử lý nếu người dùng đã đăng nhập
    username = user_data["code"]
    role = user_data["role"]
    user_branch = user_data["branch"]
    user_name = user_data["name"]

    tasks_query = db.query(Task)
    if role != "quanly":
        tasks_query = tasks_query.filter(Task.trang_thai != "Đã xoá")

    if role == "letan":
        chi_nhanh = user_branch
        tasks_query = tasks_query.filter(Task.chi_nhanh == chi_nhanh)
    elif chi_nhanh:
        tasks_query = tasks_query.filter(Task.chi_nhanh == chi_nhanh)

    if search:
        clean_search = re.sub(r'\s+', ' ', search).strip()
        search_pattern = f"%{clean_search}%"
        tasks_query = tasks_query.filter(
            Task.chi_nhanh.ilike(search_pattern) |
            Task.phong.ilike(search_pattern) |
            Task.mo_ta.ilike(search_pattern) |
            Task.trang_thai.ilike(search_pattern) |
            Task.nguoi_tao.ilike(search_pattern) |
            Task.nguoi_thuc_hien.ilike(search_pattern) |
            Task.ghi_chu.ilike(search_pattern)
        )

    if trang_thai:
        tasks_query = tasks_query.filter(Task.trang_thai == trang_thai)

    if han_hoan_thanh:
        try:
            han_date = datetime.strptime(han_hoan_thanh, "%Y-%m-%d").date()
            tasks_query = tasks_query.filter(func.date(Task.han_hoan_thanh) == han_date)
        except Exception as e:
            print("Lỗi định dạng ngày lọc:", e)

    rows_all = tasks_query.all()

    order = {
        "Quá hạn": 0,
        "Đang chờ": 1,
        "Hoàn thành": 2,
        "Đã xoá": 3
    }
    rows_all.sort(key=lambda t: (
        order.get(t.trang_thai, 99),
        t.han_hoan_thanh or datetime.max
    ))

    total_tasks = len(rows_all)
    total_pages = max(1, (total_tasks + per_page - 1) // per_page)
    start = (page - 1) * per_page
    rows = rows_all[start:start + per_page]

    tasks = []
    chi_nhanhs_set = set()
    for t in rows:
        chi_nhanhs_set.add(t.chi_nhanh)
        task_data = {
            "id": t.id,
            "chi_nhanh": t.chi_nhanh,
            "phong": t.phong,
            "mo_ta": t.mo_ta,
            "ngay_tao": format_datetime_display(t.ngay_tao, with_time=True),
            "han_hoan_thanh": format_datetime_display(t.han_hoan_thanh, with_time=False),
            "han_hoan_thanh_raw": t.han_hoan_thanh,
            "trang_thai": t.trang_thai,
            "nguoi_tao": t.nguoi_tao,
            "ghi_chu": t.ghi_chu or "",
            "nguoi_thuc_hien": t.nguoi_thuc_hien,
            "ngay_hoan_thanh": format_datetime_display(t.ngay_hoan_thanh, with_time=True) if t.ngay_hoan_thanh else "",
            "is_overdue": is_overdue(t),
        }
        tasks.append(task_data)
    
    def parse_display_datetime(s: str) -> datetime:
        try:
            return datetime.strptime(s, "%d/%m/%Y %H:%M")
        except:
            return datetime.min

    # ✅ Thống kê
    today = datetime.now()
    thong_ke = {
        "tong_cong_viec": len(rows_all),
        "hoan_thanh": sum(1 for t in rows_all if t.trang_thai == "Hoàn thành"),
        "hoan_thanh_tuan": sum(
            1 for t in rows_all if t.trang_thai == "Hoàn thành" and
            t.ngay_hoan_thanh and
            t.ngay_hoan_thanh >= today.replace(hour=0, minute=0) - timedelta(days=today.weekday())
        ),
        "hoan_thanh_thang": sum(
            1 for t in rows_all if t.trang_thai == "Hoàn thành" and
            t.ngay_hoan_thanh and
            t.ngay_hoan_thanh.month == today.month
        ),
        "dang_cho": sum(1 for t in rows_all if t.trang_thai == "Đang chờ"),
        "qua_han": sum(1 for t in rows_all if t.trang_thai == "Quá hạn"),
    }

    tasks_serialized = [serialize_task(t) for t in tasks]

    from urllib.parse import urlencode

    query_params = {
        "search": search,
        "trang_thai": trang_thai,
        "han_hoan_thanh": han_hoan_thanh,
        "chi_nhanh": chi_nhanh,
    }
    query_string = "&" + urlencode({k: v for k, v in query_params.items() if v}) if any(query_params.values()) else ""

    query_for_calendar = db.query(Task)
    if role != "quanly":
        query_for_calendar = query_for_calendar.filter(Task.trang_thai != "Đã xoá")


    # Áp dụng bộ lọc nếu có
    if role == "letan":
        query_for_calendar = query_for_calendar.filter(Task.chi_nhanh == user_branch)
    elif chi_nhanh:
        query_for_calendar = query_for_calendar.filter(Task.chi_nhanh == chi_nhanh)

    if search:
        clean_search = re.sub(r'\s+', ' ', search).strip()
        search_pattern = f"%{clean_search}%"
        query_for_calendar = query_for_calendar.filter(
            Task.chi_nhanh.ilike(search_pattern) |
            Task.phong.ilike(search_pattern) |
            Task.mo_ta.ilike(search_pattern) |
            Task.trang_thai.ilike(search_pattern) |
            Task.nguoi_tao.ilike(search_pattern) |
            Task.nguoi_thuc_hien.ilike(search_pattern) |
            Task.ghi_chu.ilike(search_pattern)
        )

    if trang_thai:
        query_for_calendar = query_for_calendar.filter(Task.trang_thai == trang_thai)

    if han_hoan_thanh:
        try:
            han_date = datetime.strptime(han_hoan_thanh, "%Y-%m-%d").date()
            query_for_calendar = query_for_calendar.filter(func.date(Task.han_hoan_thanh) == han_date)
        except Exception as e:
            print("Lỗi định dạng ngày lọc (calendar):", e)

    # Lấy toàn bộ tasks cho Calendar
    all_tasks_for_calendar = query_for_calendar.all()


    all_tasks_for_calendar_serialized = [
        {
            "id": t.id,
            "phong": t.phong,
            "mo_ta": t.mo_ta,
            "han_hoan_thanh": t.han_hoan_thanh.strftime("%Y-%m-%d") if t.han_hoan_thanh else "",
            "han_hoan_thanh_raw": t.han_hoan_thanh.strftime("%d/%m/%Y") if t.han_hoan_thanh else "",
            "trang_thai": t.trang_thai
        } for t in all_tasks_for_calendar
    ]

    # ✅ Trả về template
    return templates.TemplateResponse("home.html", {
        "request": request,
        "tasks": tasks_serialized,
        "user": username,
        "role": role,
        "user_name": user_name,
        "search": search,
        "trang_thai": trang_thai,
        "chi_nhanh": chi_nhanh,
        "chi_nhanhs": sorted(chi_nhanhs_set),
        "user_chi_nhanh": user_branch,
        "branches": BRANCHES,
        "now": today,
        "thong_ke": thong_ke,
        "page": page,
        "total_pages": total_pages,
        "per_page": per_page,
        "query_string": query_string,
        "all_tasks_for_calendar": all_tasks_for_calendar_serialized,
    })


from typing import Optional

@app.post("/add")
def add_task(
    request: Request,
    chi_nhanh: Optional[str] = Form(None),
    phong: str = Form(...),
    mo_ta: str = Form(...),
    han_hoan_thanh: str = Form(...),
    nguoi_tao: str = Form(...),
    ghi_chu: str = Form(""),
    db: Session = Depends(get_db)
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

    role = user.get("role")
    user_branch = user.get("branch")

    # ✅ Nếu không phải quản lý/ktv thì ép chi nhánh từ session
    if role not in ["quanly", "ktv"]:
        chi_nhanh = user_branch

    if not chi_nhanh:
        raise HTTPException(status_code=400, detail="Không xác định được chi nhánh")

    han = parse_datetime_input(han_hoan_thanh)
    now = datetime.now(VN_TZ)
    trang_thai = "Quá hạn" if han < now else "Đang chờ"

    new_task = Task(
        chi_nhanh=chi_nhanh,
        phong=phong,
        mo_ta=mo_ta,
        ngay_tao=now,
        han_hoan_thanh=han,
        trang_thai=trang_thai,
        nguoi_tao=nguoi_tao,
        ghi_chu=ghi_chu
    )
    db.add(new_task)
    db.commit()

    raw_query = request.scope.get("query_string", b"").decode()
    clean_query = clean_query_string(raw_query)
    redirect_url = f"/home?{clean_query}&success=1&action=add" if clean_query else "/home?success=1&action=add"

    return RedirectResponse(redirect_url, status_code=303)

from fastapi.responses import JSONResponse

@app.post("/complete/{task_id}")
async def complete_task(task_id: int, request: Request, nguoi_thuc_hien: str = Form(...), db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy công việc")

    task.trang_thai = "Hoàn thành"
    task.nguoi_thuc_hien = nguoi_thuc_hien
    task.ngay_hoan_thanh = datetime.now(VN_TZ)
    db.commit()

    if request.query_params.get("json") == "1":
        return JSONResponse({"success": True, "task_id": task_id})

    raw_query = request.scope.get("query_string", b"").decode()
    clean_query = clean_query_string(raw_query)
    redirect_url = f"/home?{clean_query}&success=1&action=complete" if clean_query else "/home?success=1&action=complete"
    return RedirectResponse(redirect_url, status_code=303)

@app.post("/delete/{task_id}")
async def delete_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user_code = request.session.get("user", {}).get("code", "")
    user = db.query(User).filter(User.code == user_code).first()
    if not user:
        return RedirectResponse("/login", status_code=303)

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy công việc")

    if user.role == "quanly":
        db.delete(task)
    else:
        task.trang_thai = "Đã xoá"
    db.commit()

    if request.query_params.get("json") == "1":
        return JSONResponse({"success": True, "task_id": task_id})

    raw_query = request.scope.get("query_string", b"").decode()
    clean_query = clean_query_string(raw_query)
    redirect_url = f"/home?{clean_query}&success=1&action=delete" if clean_query else "/home?success=1&action=delete"
    return RedirectResponse(redirect_url, status_code=303)


from typing import Optional

@app.post("/edit/{task_id}")
async def edit_submit(
    request: Request,
    task_id: int,
    chi_nhanh: Optional[str] = Form(None),
    phong: str = Form(...),
    mo_ta: str = Form(...),
    han_hoan_thanh: str = Form(...),
    ghi_chu: str = Form(""),
    db: Session = Depends(get_db)
):
    # Lấy session user
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

    role = user.get("role")
    user_branch = user.get("branch")

    # Nếu không phải quản lý hoặc kỹ thuật viên thì ép chi nhánh từ session
    if role not in ["quanly", "ktv"]:
        chi_nhanh = user_branch

    if not chi_nhanh:
        raise HTTPException(status_code=400, detail="Không xác định được chi nhánh")

    # Tìm công việc cần sửa
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy công việc")

    # Parse hạn hoàn thành
    han = parse_datetime_input(han_hoan_thanh)
    now = datetime.now(VN_TZ)

    # Cập nhật dữ liệu
    task.chi_nhanh = chi_nhanh
    task.phong = phong
    task.mo_ta = mo_ta
    task.han_hoan_thanh = han
    task.ghi_chu = ghi_chu
    task.trang_thai = "Quá hạn" if han < now else "Đang chờ"

    db.commit()

    # Lấy query_string để redirect giữ lại filter
    form_data = await request.form()
    redirect_query = form_data.get("redirect_query", "")

    return RedirectResponse(f"/home?success=1&action=update{('&' + redirect_query) if redirect_query else ''}", status_code=303)

from fastapi import Request

@app.get("/send-overdue-alerts")
async def send_overdue_alerts(request: Request, db: Session = Depends(get_db)):
    try:
        now = datetime.now(VN_TZ)

        # Cập nhật trạng thái "Quá hạn"
        overdue_to_update = db.query(Task).filter(
            Task.trang_thai == "Đang chờ",
            Task.han_hoan_thanh < now
        ).all()
        for task in overdue_to_update:
            task.trang_thai = "Quá hạn"
        if overdue_to_update:
            db.commit()

        # Lấy công việc quá hạn
        tasks = db.query(Task).filter(
            Task.trang_thai == "Quá hạn"
        ).order_by(Task.chi_nhanh.asc(), Task.phong.asc()).all()

        if not tasks:
            return JSONResponse({"message": "Không có công việc quá hạn."})

        from collections import defaultdict
        grouped = defaultdict(list)
        for t in tasks:
            grouped[t.chi_nhanh].append(t)

        base_url = str(request.base_url).rstrip("/")
        total_sent = 0

        for chi_nhanh, task_list in grouped.items():
            # Bảng HTML có kẻ dòng, căn giữa tiêu đề, chữ căn đều
            rows_html = "\n".join([
                f"""
                <tr style="border-bottom:1px solid #e5e7eb;">
                    <td style="padding:10px;">{t.phong}</td>
                    <td style="padding:10px;">
                        <a href="{base_url}/edit/{t.id}" target="_blank" style="color:#2563eb; text-decoration:none;">
                            {t.mo_ta}
                        </a>
                    </td>
                    <td style="padding:10px;">{t.ghi_chu or ''}</td>
                </tr>
                """ for t in task_list
            ])

            subject = f"🕹 CẢNH BÁO: {len(task_list)} công việc quá hạn tại {chi_nhanh}"

            body = f"""
            <html>
            <body style="font-family:Segoe UI, sans-serif; font-size:15px; color:#1f2937; background-color:#f9fafb; padding:24px;">
                <div style="max-width:700px; margin:auto; background:white; padding:24px; border-radius:8px; border:1px solid #e5e7eb; text-align:justify;">
                    <h2 style="color:#dc2626; font-weight:600; margin-bottom:16px; font-size:20px; text-align:center;">
                        {chi_nhanh} CẢNH BÁO CÔNG VIỆC QUÁ HẠN
                    </h2>

                    <p style="font-size:15px; line-height:1.6;">
                        🍀 Hệ thống ghi nhận có <strong>{len(task_list)} công việc</strong> tại chi nhánh <strong>{chi_nhanh}</strong> đang quá hạn xử lý.<br></p>
                    
                    <table style="
                        width:100%;
                        border-collapse:collapse;
                        margin-top:20px;
                        font-size:14px;
                        background-color:white;
                        box-shadow:0 0 8px rgba(0,0,0,0.04);
                    ">
                        <thead style="background-color: #f3f4f6;">
                            <tr style="border-bottom:1px solid #d1d5db;">
                                <th style="text-align:center; padding:10px; border:1px solid #d1d5db;">Phòng</th>
                                <th style="text-align:center; padding:10px; border:1px solid #d1d5db;">Mô tả</th>
                                <th style="text-align:center; padding:10px; border:1px solid #d1d5db;">Ghi chú</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows_html}
                        </tbody>
                    </table>

                    <p style="font-size:15px; line-height:1.6;"> ❗️ Vui lòng kiểm tra và xử lý kịp thời để đảm bảo tiến độ công việc. </p>

                    <p style="margin-top:16px; font-size:13px; color:#9ca3af;">
                        (Email tự động từ hệ thống quản lý công việc Bin Bin Hotel.)
                    </p>
                </div>
            </body>
            </html>
            """

            await send_alert_email(ALERT_EMAIL, subject, body, html=True)
            total_sent += len(task_list)

        return JSONResponse({"sent_total": total_sent, "branches": list(grouped.keys())})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

def seed_users():
    allowed_login_roles = ["letan", "quanly", "ktv", "admin", "boss"]
    db = SessionLocal()
    try:
        seen_codes = set()
        for emp in employees:
            code = emp.get("code", "")
            if not code or code in seen_codes:
                continue  # bỏ qua nhân viên trùng mã
            seen_codes.add(code)
            name = emp.get("name", "")
            branch = emp.get("branch", "")
            role = emp.get("role", "")
            if not role:
                # fallback logic nếu thiếu trường role
                if "LT" in code:
                    role = "letan"
                elif "BP" in code:
                    role = "buongphong"
                elif "BV" in code:
                    role = "baove"
                elif "QL" in code:
                    role = "quanly"
                elif "KTV" in code:
                    role = "ktv"
                elif code.lower() in ["admin", "boss"]:
                    role = code.lower()
                else:
                    role = "khac"
            password = "999" if role in allowed_login_roles else ""
            existing = db.query(User).filter(User.code == code).first()
            if existing:
                if existing.password != password:
                    existing.password = password
                existing.name = name
                existing.role = role
                existing.branch = branch
            else:
                db.add(User(code=code, name=name, password=password, role=role, branch=branch))
        db.commit()
    finally:
        db.close()

def sync_employees_to_db():
    """
    Xóa toàn bộ bảng User và thêm lại từ danh sách employees.py.
    Đảm bảo dữ liệu luôn đồng bộ với employees.py.
    """
    db = SessionLocal()
    try:
        db.query(User).delete()
        allowed_login_roles = ["letan", "quanly", "ktv", "admin", "boss"]
        for emp in employees:
            code = emp.get("code", "")
            if not code:
                continue
            name = emp.get("name", "")
            branch = emp.get("branch", "")
            role = emp.get("role", "")
            # Nếu thiếu role thì tự động nhận diện
            if not role:
                if "LT" in code:
                    role = "letan"
                elif "BP" in code:
                    role = "buongphong"
                elif "BV" in code:
                    role = "baove"
                elif "QL" in code:
                    role = "quanly"
                elif "KTV" in code:
                    role = "ktv"
                elif code.lower() in ["admin", "boss"]:
                    role = code.lower()
                else:
                    role = "khac"
            password = emp.get("password") or (
                "999" if role in allowed_login_roles else ""
            )

            db.add(User(code=code, name=name, password=password, role=role, branch=branch))
        db.commit()
    finally:
        db.close()

@app.get("/sync-employees")
def sync_employees_endpoint(request: Request):
    """
    Endpoint để đồng bộ lại dữ liệu nhân viên từ employees.py vào database.
    Chỉ cho phép admin hoặc boss thực hiện.
    """
    user = request.session.get("user")
    if not user or user.get("role") not in ["admin", "boss"]:
        raise HTTPException(status_code=403, detail="Chỉ admin hoặc boss mới được đồng bộ nhân viên.")
    sync_employees_to_db()
    return {"status": "success", "message": "Đã đồng bộ lại danh sách nhân viên từ employees.py"}

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

@app.on_event("startup")
def startup():
    init_db()
    sync_employees_to_db()
    # Nếu cần theo dõi file employees.py thì khởi động thread ở đây
    import threading
    import time
    EMPLOYEES_FILE = os.path.join(os.path.dirname(__file__), "employees.py")
    _last_mtime = None
    def watch_employees_file():
        nonlocal _last_mtime
        while True:
            try:
                mtime = os.path.getmtime(EMPLOYEES_FILE)
                if _last_mtime is None:
                    _last_mtime = mtime
                elif mtime != _last_mtime:
                    _last_mtime = mtime
                    print("[SYNC] employees.py thay đổi → đồng bộ DB...")
                    sync_employees_to_db()
                    print("[SYNC] Hoàn tất đồng bộ nhân viên từ employees.py")
            except FileNotFoundError:
                print("[SYNC] Không tìm thấy file employees.py")
            except Exception as e:
                print("[SYNC] Lỗi khi theo dõi employees.py:", e)
            time.sleep(5)
    threading.Thread(target=watch_employees_file, daemon=True).start()

if __name__ == "__main__":
    import uvicorn, os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

from services.attendance_service import push_bulk_checkin

@app.post("/attendance/checkin_bulk")
async def attendance_checkin_bulk(request: Request, db: Session = Depends(get_db)):
    validate_csrf(request)
    user = request.session.get("user")
    if not user or user.get("role") not in ["letan", "quanly"]:
        raise HTTPException(status_code=403, detail="Không có quyền điểm danh")

    active_branch = request.session.get("active_branch") or user.get("branch", "")
    raw_data = await request.json()

    if not isinstance(raw_data, list):
        raise HTTPException(status_code=400, detail="Payload phải là danh sách")

    # Chuẩn hóa key
    normalized_data = []
    for rec in raw_data:
        normalized_data.append({
            "sheet": rec.get("sheet"),
            "thoi_gian": rec.get("thoi_gian"),
            "ma_nv": rec.get("ma_nv"),
            "ten_nv": rec.get("ten_nv"),
            "chi_nhanh_chinh": rec.get("chi_nhanh_chinh"),
            "chi_nhanh_lam": rec.get("chi_nhanh_lam"),
            "la_tang_ca": rec.get("la_tang_ca"),
            "so_cong_nv": rec.get("so_cong_nv"),
            "ghi_chu": rec.get("ghi_chu", ""),
            # Các cột dịch vụ cần map đúng tên key
            "dich_vu": rec.get("dich_vu") or rec.get("service") or "",
            "so_phong": rec.get("so_phong") or rec.get("room_count") or "",
            "so_luong": rec.get("so_luong") or rec.get("item_count") or "",
        })

    result = push_bulk_checkin(normalized_data)
    inserted = result.get("inserted", 0)
    print(f"[AUDIT] {user['code']} đã lưu điểm danh {inserted} bản ghi cho branch {active_branch}")
    return {"status": "success", "inserted": inserted}

@app.get("/favicon.ico")
def favicon():
    # Nếu có file favicon.ico trong static thì trả về file đó
    favicon_path = os.path.join("static", "favicon.ico")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    # Nếu không có, trả về 1x1 PNG trắng
    png_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\xdac\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\x0b\x0c\x00\x00\x00\x00IEND\xaeB`\x82'
    return Response(content=png_data, media_type="image/png")

