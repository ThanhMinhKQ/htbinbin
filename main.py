import secrets
from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from utils import parse_datetime_input, format_datetime_display, is_overdue
from fastapi import Request

from database import SessionLocal
from models import User, Task, AttendanceLog
from config import DATABASE_URL, SMTP_CONFIG, ALERT_EMAIL
from database import init_db

from sqlalchemy.orm import Session
from sqlalchemy import or_, cast, Date
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
import os, re
import socket
from email.message import EmailMessage 
from datetime import datetime, timedelta, timezone, date
from services.email_service import send_alert_email

from employees import employees  # import danh sách nhân viên tĩnh

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Định nghĩa múi giờ Việt Nam (UTC+7)
VN_TZ = timezone(timedelta(hours=7))

def get_current_work_shift():
    """
    Xác định ngày và ca làm việc hiện tại.
    - Ca ngày: 07:00 - 18:59
    - Ca đêm: 19:00 - 06:59
    - Thời gian từ 00:00 đến 06:59 được tính là ca đêm của ngày hôm trước.
    """
    now = datetime.now(VN_TZ)
    if now.hour < 7:
        work_date = now.date() - timedelta(days=1)
        shift = "night"
    elif 7 <= now.hour < 19:
        work_date = now.date()
        shift = "day"
    else:  # 19:00 trở đi
        work_date = now.date()
        shift = "night"
    return work_date, shift

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
    "B15", "B16"
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
    "B16": [10.760347394497392,106.69043939445082],
}

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # bán kính trái đất km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

@app.post("/attendance/api/detect-branch")
async def detect_branch(request: Request, db: Session = Depends(get_db)):
    special_roles = ["quanly", "ktv", "boss", "admin"]

    # Lấy user từ session (ưu tiên user, fallback pending_user)
    user_data = request.session.get("user") or request.session.get("pending_user")
    user_in_db = None
    if user_data:
        user_in_db = db.query(User).filter(User.code == user_data["code"]).first()

    # ===============================
    # 1. Role đặc biệt → bỏ qua GPS
    # ===============================
    if user_data and user_data.get("role") in special_roles:
        if user_in_db and user_in_db.branch:
            main_branch = user_in_db.branch
            request.session["active_branch"] = main_branch
            user_in_db.last_active_branch = main_branch
            db.commit()
            return {"branch": main_branch, "distance_km": 0}

        return JSONResponse(
            {"error": "Không thể lấy chi nhánh chính. Vui lòng liên hệ quản trị."},
            status_code=400,
        )

    # ===============================
    # 2. Role thường → dùng GPS
    # ===============================
    try:
        data = await request.json()
    except Exception:
        data = {}

    lat, lng = data.get("lat"), data.get("lng")
    if lat is None or lng is None:
        return JSONResponse(
            {"error": "Bạn vui lòng mở định vị trên điện thoại để lấy vị trí"},
            status_code=400,
        )

    # Tìm chi nhánh trong bán kính 200m
    nearby_branches = []
    for branch, coords in branchCoordinates.items():
        dist = haversine(lat, lng, coords[0], coords[1])
        if dist <= 0.2:  # trong 200m
            nearby_branches.append((branch, dist))

    if not nearby_branches:
        return JSONResponse(
            {"error": "Bạn đang ở quá xa khách sạn. Vui lòng điểm danh tại khách sạn."},
            status_code=403,
        )

    # Nếu có nhiều chi nhánh gần → cho frontend chọn
    if len(nearby_branches) > 1:
        choices = [
            {"branch": b, "distance_km": round(d, 3)}
            for b, d in sorted(nearby_branches, key=lambda x: x[1])
        ]
        return {"choices": choices}

    # Nếu chỉ có 1 chi nhánh gần → chọn luôn
    chosen_branch, min_distance = nearby_branches[0]

    request.session["active_branch"] = chosen_branch
    if user_in_db:
        user_in_db.last_active_branch = chosen_branch
        db.commit()

    return {"branch": chosen_branch, "distance_km": round(min_distance, 3)}

@app.post("/attendance/api/select-branch")
async def select_branch(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    branch = data.get("branch")

    user_data = request.session.get("user") or request.session.get("pending_user")
    if not user_data:
        return JSONResponse({"error": "User chưa đăng nhập"}, status_code=403)

    request.session["active_branch"] = branch

    # Lưu DB
    user_in_db = db.query(User).filter(User.code == user_data["code"]).first()
    if user_in_db:
        user_in_db.last_active_branch = branch
        db.commit()

    return {"branch": branch}

@app.get("/attendance/service", response_class=HTMLResponse)
def attendance_service_ui(request: Request, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data:
        return RedirectResponse("/login", status_code=303)
    checker_user = db.query(User).filter(User.code == user_data["code"]).first()
    active_branch = request.session.get("active_branch")
    # Nếu trong session không có, thử lấy từ DB (lần đăng nhập trước)
    if not active_branch and checker_user and hasattr(checker_user, 'last_active_branch') and checker_user.last_active_branch:
        active_branch = checker_user.last_active_branch
        request.session["active_branch"] = active_branch # Lưu lại vào session cho lần tải trang sau trong cùng phiên
    # Nếu vẫn không có, dùng chi nhánh mặc định của user
    if not active_branch:
        active_branch = user_data.get("branch", "")
    csrf_token = get_csrf_token(request)

    initial_employees = []
    # Lấy danh sách nhân viên BP đã được điểm danh lần cuối từ DB của lễ tân
    if checker_user and checker_user.last_checked_in_bp:
        service_checkin_codes = checker_user.last_checked_in_bp

        if service_checkin_codes:
            # Lấy thông tin chi tiết của các nhân viên đó
            employees_from_db = db.query(User).filter(User.code.in_(service_checkin_codes)).all()
            # Sắp xếp lại theo đúng thứ tự đã điểm danh
            emp_map = {emp.code: emp for emp in employees_from_db}
            sorted_employees = [emp_map[code] for code in service_checkin_codes if code in emp_map]
            
            initial_employees = [
                {"code": emp.code, "name": emp.name, "branch": emp.branch, "so_phong": "", "so_luong": "", "dich_vu": "", "ghi_chu": ""}
                for emp in sorted_employees
            ]

    response = templates.TemplateResponse("attendance_service.html", {
        "request": request,
        "branch_id": active_branch,
        "csrf_token": csrf_token,
        "user": user_data,
        "initial_employees": initial_employees,
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    """Route gốc, chuyển hướng người dùng dựa trên trạng thái đăng nhập."""
    if request.session.get("user"):
        return RedirectResponse("/login", status_code=303) 
    return RedirectResponse("/login", status_code=303)

# --- Sử dụng middleware này ở các route yêu cầu đăng nhập ---
@app.get("/choose-function", response_class=HTMLResponse)
async def choose_function(request: Request):
    if not require_checked_in_user(request): # This check also ensures user is in session
        return RedirectResponse("/login", status_code=303)

    # Nếu có flag after_checkin thì xóa để tránh dùng lại
    if request.session.get("after_checkin") == "choose_function":
        request.session.pop("after_checkin", None)

    response = templates.TemplateResponse(
        "choose_function.html", {"request": request, "user": request.session.get("user")}
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.get("/attendance/results", response_class=HTMLResponse)
def view_attendance_results(request: Request):
    """
    Route để hiển thị trang xem kết quả điểm danh.
    """
    if not require_checked_in_user(request):
        return RedirectResponse("/login", status_code=303)

    user_data = request.session.get("user")
    return templates.TemplateResponse("attendance_results.html", {
        "request": request,
        "user": user_data
    })

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    # Nếu người dùng đã đăng nhập VÀ đã điểm danh QR thành công hôm nay thì chuyển về trang chọn chức năng
    user = request.session.get("user")
    if user:
        today = date.today()
        db = SessionLocal()
        try:
            log = db.query(AttendanceLog).filter_by(user_code=user["code"], date=today).first()
            if log and log.checked_in:
                    return RedirectResponse(url="/choose-function", status_code=303)
        finally:
            db.close()
    error = request.query_params.get("error", "")
    role = request.query_params.get("role", "")
    response = templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
        "role": role
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    request.session.clear()
    allowed_roles = ["letan", "quanly", "ktv", "admin", "boss"]
    user = db.query(User).filter(
        User.code == username,
        User.password == password,
        User.role.in_(allowed_roles)
    ).first()

    if user:
        work_date, shift = get_current_work_shift()
        log = db.query(AttendanceLog).filter(
            AttendanceLog.user_code == user.code,
            AttendanceLog.date == work_date,
            AttendanceLog.shift == shift
        ).first()
        if log and log.checked_in:
            request.session["user"] = {
                "code": user.code,
                "role": user.role,
                "branch": user.branch,
                "name": user.name
            }
            request.session.pop("pending_user", None)
            return RedirectResponse("/choose-function", status_code=303)
        else:
            # Phân luồng cho mobile và desktop
            user_agent = request.headers.get("user-agent", "").lower()
            is_mobile = any(k in user_agent for k in ["mobi", "android", "iphone", "ipad"])

            if is_mobile:
                # Luồng mobile: Bỏ qua QR, coi như đã check-in và vào thẳng trang điểm danh
                if log:
                    log.checked_in = True
                else:
                    log = AttendanceLog(user_code=user.code, date=work_date, shift=shift, checked_in=True, token=secrets.token_urlsafe(16))
                    db.add(log)
                db.commit()

                # Đăng nhập cho user
                request.session["user"] = { "code": user.code, "role": user.role, "branch": user.branch, "name": user.name }
                request.session.pop("pending_user", None)
                # Chuyển hướng đến trang điểm danh
                return RedirectResponse("/attendance/ui", status_code=303)
            else:
                # Luồng desktop: Tạo token cho ca làm việc hiện tại
                if log and not log.checked_in:
                    token = log.token
                else: # Chưa có log cho ca này, tạo mới
                    token = secrets.token_urlsafe(24)
                    new_log = AttendanceLog(user_code=user.code, date=work_date, shift=shift, token=token, checked_in=False)
                    db.add(new_log)
                    db.commit()
                request.session["pending_user"] = { "code": user.code, "role": user.role, "branch": user.branch, "name": user.name }
                request.session["qr_token"] = token
                return RedirectResponse("/show_qr", status_code=303)
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

# --- Middleware kiểm tra trạng thái điểm danh QR ---
from datetime import date

def require_checked_in_user(request: Request):
    user = request.session.get("user")
    if not user:
        return False

    work_date, _ = get_current_work_shift()
    db = SessionLocal()
    try:
        # Kiểm tra xem có bất kỳ log nào đã check-in trong ngày làm việc hiện tại không
        # (ca ngày hoặc ca đêm).
        log = db.query(AttendanceLog).filter(
            AttendanceLog.user_code == user["code"],
            AttendanceLog.date == work_date,
            AttendanceLog.checked_in == True
        ).first()

        # Cho phép vào nếu có log checked_in trong DB hoặc vừa quét QR xong
        if (log and log.checked_in) or request.session.get("after_checkin") == "choose_function":
            return True
    finally:
        db.close()

    return False

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
    response = templates.TemplateResponse("attendance.html", {
        "request": request,
        "branch_id": active_branch,
        "csrf_token": csrf_token,
        # "branches": BRANCHES,
        "user": user_data,
        "login_code": user_data.get("code", ""),  # thêm dòng này
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# --- Get CSRF token ---
@app.get("/attendance/csrf-token")
def attendance_csrf_token(request: Request):
    token = get_csrf_token(request)
    return {"csrf_token": token}

@app.get("/attendance/api/employees/by-branch/{branch_id}", response_class=JSONResponse)
def get_employees_by_branch(branch_id: str, db: Session = Depends(get_db), request: Request = None):
    try:
        user = request.session.get("user") if request else None
        now_hour = datetime.now(VN_TZ).hour
        current_shift = "CS" if 7 <= now_hour < 19 else "CT"

        def match_shift(emp_code: str):
            emp_code = emp_code.upper()
            if "CS" in emp_code and current_shift != "CS":
                return False
            if "CT" in emp_code and current_shift != "CT":
                return False
            return True

        employees = []

        if user and user.get("role") == "letan":
            # ✅ Luôn thêm chính lễ tân đang đăng nhập
            lt_self = db.query(User).filter(
                User.code == user.get("code"),
                User.branch == branch_id
            ).all()
            # Các bộ phận khác cùng chi nhánh (bỏ quản lý, ktv, lễ tân khác)
            others = db.query(User).filter(
                User.branch == branch_id,
                ~User.role.in_(["quanly", "ktv", "letan"])
            ).all()
            others = [emp for emp in others if match_shift(emp.code)]
            employees = sorted(lt_self + others, key=lambda e: e.name)

        elif user and user.get("role") in ["quanly", "ktv", "admin", "boss"]:
            # ✅ Quản lý và KTV chỉ thấy chính họ (bỏ lọc chi nhánh, bỏ shift)
            employees = db.query(User).filter(
                User.code == user.get("code")
            ).all()

        else:
            # ✅ Logic chung cho các role khác
            employees = db.query(User).filter(
                User.branch == branch_id,
                ~User.role.in_(["quanly", "ktv", "admin", "boss"])
            ).all()
            employees = [emp for emp in employees if match_shift(emp.code)]
            employees.sort(key=lambda e: e.name)

        employee_list = [
            {"code": emp.code, "name": emp.name, "department": emp.role, "branch": emp.branch}
            for emp in employees
        ]
        return JSONResponse(content=employee_list)

    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"Lỗi server: {str(e)}"})

# --- Employee search ---
@app.get("/attendance/api/employees/search", response_class=JSONResponse)
def search_employees(
    q: str = "",
    branch_id: str = None,  # Thêm tham số để lọc theo chi nhánh
    only_bp: bool = False,
    loginCode: str = None,   # ✅ thêm tham số loginCode để phân biệt lễ tân đăng nhập
    db: Session = Depends(get_db)
):
    """
    API tìm kiếm nhân viên theo mã hoặc tên.
    - Nếu branch_id được cung cấp, chỉ tìm trong chi nhánh đó (ngoại trừ khi only_bp=True).
    - Nếu only_bp=True thì chỉ trả về nhân viên buồng phòng (mã chứa 'BP') từ TẤT CẢ các chi nhánh.
    - Mặc định loại bỏ role lễ tân, ngoại trừ lễ tân đang đăng nhập (loginCode).
    - Giới hạn 20 kết quả.
    """
    if not q:
        # Nếu không có query 'q' nhưng 'only_bp' là true,
        # cho phép tiếp tục để lấy toàn bộ nhân viên (thường là BP) của một chi nhánh.
        if not only_bp:
            return JSONResponse(content=[], status_code=400)
        search_pattern = "%"
    else:
        search_pattern = f"%{q}%"

    # Xây dựng query cơ bản
    query = db.query(User).filter(
        or_(
            User.code.ilike(search_pattern),
            User.name.ilike(search_pattern)
        )
    )

    # Thêm bộ lọc chi nhánh nếu được cung cấp (bỏ qua nếu tìm BP)
    if branch_id and not only_bp:
        query = query.filter(User.branch == branch_id)

    employees = query.limit(50).all()

    # ✅ Nếu chỉ tìm buồng phòng
    if only_bp:
        employees = [emp for emp in employees if "BP" in (emp.code or "").upper()]

    # ✅ Loại bỏ tất cả lễ tân khác, chỉ giữ lại đúng loginCode (nếu có)
    filtered = []
    for emp in employees:
        if (emp.role or "").lower() == "letan":
            if loginCode and emp.code == loginCode:
                filtered.append(emp)  # giữ lại chính lễ tân đăng nhập
        else:
            filtered.append(emp)
    employees = filtered[:20]

    employee_list = [
        {"code": emp.code, "name": emp.name, "department": emp.role, "branch": emp.branch}
        for emp in employees
    ]
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
    response = templates.TemplateResponse("home.html", {
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
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


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
    from database import init_db
    from utils import sync_employees_to_db_safe

    init_db()  # tạo bảng nếu chưa có

    try:
        seed_users()  # ✅ dùng seed thay vì sync xoá hết
        print("[SYNC] Hoàn tất đồng bộ nhân viên từ employees.py")
    except Exception as e:
        print("[STARTUP] Không thể đồng bộ nhân viên:", e)

    # Thread watch employees.py
    import threading, time, os
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
                    sync_employees_to_db_safe()
                    print("[SYNC] Hoàn tất đồng bộ nhân viên từ employees.py")
            except FileNotFoundError:
                print("[SYNC] Không tìm thấy file employees.py")
            except Exception as e:
                print("[SYNC] Lỗi khi theo dõi employees.py:", e)
            time.sleep(5)
    threading.Thread(target=watch_employees_file, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

def get_lan_ip():
    """Hàm này lấy địa chỉ IP nội bộ (LAN) của máy chủ."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Không cần phải kết nối được, chỉ là một mẹo để lấy IP
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1' # Fallback nếu không lấy được IP
    finally:
        s.close()
    return IP

@app.get("/show_qr", response_class=HTMLResponse)
async def show_qr(request: Request, db: Session = Depends(get_db)):
    user = request.session.get("pending_user") or request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

    work_date, shift = get_current_work_shift()
    log = db.query(AttendanceLog).filter(
        AttendanceLog.user_code == user["code"], # user là dict, nên dùng user["code"]
        AttendanceLog.date == work_date,
        AttendanceLog.shift == shift # user là dict, nên dùng user["code"]
    ).first()

    if log:
        if log.checked_in:
            # Nếu đã check-in thì không cần show_qr nữa → đi thẳng trang chọn chức năng
            return RedirectResponse("/choose-function", status_code=303)
        else:
            qr_token = log.token
    else:
        # Trường hợp này không nên xảy ra nếu luồng đăng nhập đúng, nhưng là fallback
        import uuid
        qr_token = str(uuid.uuid4())
        log = AttendanceLog(user_code=user["code"], date=work_date, shift=shift, token=qr_token, checked_in=False)
        db.add(log)
        db.commit()

    request.session["qr_token"] = qr_token
    
    # Lấy host và port từ request
    request_host = request.url.hostname
    port = request.url.port
    scheme = request.url.scheme

    # Nếu host là localhost, thay thế bằng IP LAN để điện thoại có thể truy cập
    if request_host in ["localhost", "127.0.0.1"]:
        lan_ip = get_lan_ip()
        base_url = f"{scheme}://{lan_ip}:{port}"
    else:
        base_url = str(request.base_url).strip("/")
    return templates.TemplateResponse("show_qr.html", {
        "request": request,
        "qr_token": qr_token,
        "base_url": base_url
    })

from services.attendance_service import push_bulk_checkin, get_attendance_by_checker

from fastapi import BackgroundTasks

from datetime import datetime
from pytz import timezone

@app.post("/attendance/checkin_bulk")
async def attendance_checkin_bulk(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    validate_csrf(request)

    user = request.session.get("user") or request.session.get("pending_user")
    if not user:
        raise HTTPException(status_code=403, detail="Không có quyền điểm danh.")

    raw_data = await request.json()
    if not isinstance(raw_data, list):
        raise HTTPException(status_code=400, detail="Payload phải là danh sách")

    # Lấy chi nhánh làm việc từ payload để cập nhật trạng thái.
    # Giả định tất cả record trong 1 lần gửi đều thuộc cùng 1 chi nhánh làm việc.
    active_branch_from_payload = None
    if raw_data: # Đảm bảo raw_data không rỗng
        active_branch_from_payload = raw_data[0].get("chi_nhanh_lam")

    nguoi_diem_danh_code = user.get("code")
    user_role = user.get("role")
    user_branch = user.get("branch")
    special_roles = ["quanly", "ktv", "admin", "boss"]

    # Đối với các vai trò đặc biệt (QL, KTV, admin, boss), họ chỉ điểm danh cho chính mình.
    # Chi nhánh làm việc sẽ được tự động gán bằng chi nhánh chính của họ, không cần chọn từ UI.
    if user_role in special_roles:
        active_branch_from_payload = user_branch

    normalized_data = []
    now_vn = datetime.now(timezone("Asia/Ho_Chi_Minh")).strftime("%Y-%m-%d %H:%M:%S")

    for rec in raw_data:
        normalized_data.append({
            # sheet target (nếu client gửi)
            "sheet": rec.get("sheet"),
            # thời gian: ưu tiên client, fallback giờ VN
            "thoi_gian": rec.get("thoi_gian") or now_vn,
            # nhân viên được điểm danh
            "ma_nv": rec.get("ma_nv"),
            "ten_nv": rec.get("ten_nv"),
            "chi_nhanh_chinh": rec.get("chi_nhanh_chinh"),
            "chi_nhanh_lam": active_branch_from_payload,
            # field bổ sung
            "la_tang_ca": "x" if rec.get("la_tang_ca") else "",
            "so_cong_nv": rec.get("so_cong_nv") or 1,
            "ghi_chu": rec.get("ghi_chu", ""),
            "dich_vu": rec.get("dich_vu") or rec.get("service") or "",
            "so_phong": rec.get("so_phong") or rec.get("room_count") or "",
            "so_luong": rec.get("so_luong") or rec.get("item_count") or "",

            # người đang login
            "nguoi_diem_danh": nguoi_diem_danh_code
        })

    # Lấy danh sách mã nhân viên BP vừa được điểm danh
    bp_codes = [
        rec.get("ma_nv") for rec in raw_data
        if "BP" in rec.get("ma_nv", "").upper()
    ]

    # Cập nhật DB cho lễ tân đang đăng nhập.
    if nguoi_diem_danh_code:
        checker_user = db.query(User).filter(User.code == nguoi_diem_danh_code).first()
        if checker_user:
            # 1. Cập nhật danh sách BP đã điểm danh để gợi ý ở trang Chấm dịch vụ
            checker_user.last_checked_in_bp = bp_codes

            # 2. Cập nhật chi nhánh làm việc cuối cùng
            if active_branch_from_payload and hasattr(checker_user, 'last_active_branch'):
                checker_user.last_active_branch = active_branch_from_payload
                # Đồng thời cập nhật session để có hiệu lực ngay lập tức
                request.session["active_branch"] = active_branch_from_payload

            db.commit()

    # ✅ chạy push_bulk_checkin ở background
    background_tasks.add_task(push_bulk_checkin, normalized_data)

    print(f"[AUDIT] {nguoi_diem_danh_code} gửi {len(normalized_data)} record điểm danh (ghi Sheets async)")
    return {"status": "queued", "inserted": len(normalized_data)}

@app.get("/api/attendance/last-checked-in-bp", response_class=JSONResponse)
def get_last_checked_in_bp(request: Request, db: Session = Depends(get_db)):
    """
    API trả về danh sách nhân viên buồng phòng mà lễ tân đã điểm danh lần cuối.
    Dùng cho nút "Tải lại" trên trang Chấm dịch vụ.
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Không có quyền truy cập.")

    checker_user = db.query(User).filter(User.code == user_data["code"]).first()
    if not checker_user or not checker_user.last_checked_in_bp:
        return JSONResponse(content=[])

    service_checkin_codes = checker_user.last_checked_in_bp
    
    if not service_checkin_codes:
        return JSONResponse(content=[])

    employees_from_db = db.query(User).filter(User.code.in_(service_checkin_codes)).all()
    # Sắp xếp lại theo đúng thứ tự đã điểm danh
    emp_map = {emp.code: emp for emp in employees_from_db}
    sorted_employees = [emp_map[code] for code in service_checkin_codes if code in emp_map]
    
    employee_list = [
        { "code": emp.code, "name": emp.name, "branch": emp.branch, "so_phong": "", "so_luong": "", "dich_vu": "", "ghi_chu": "" }
        for emp in sorted_employees
    ]
    return JSONResponse(content=employee_list)

@app.get("/api/attendance/results-by-checker")
async def api_get_attendance_results(request: Request):
    """
    API trả về kết quả điểm danh do người dùng đang đăng nhập thực hiện.
    """
    user = request.session.get("user")
    allowed_roles = ['letan', 'quanly', 'ktv', 'admin', 'boss']
    if not user or user.get("role") not in allowed_roles:
        raise HTTPException(status_code=403, detail="Bạn không có quyền truy cập chức năng này.")

    checker_code = user.get("code")
    if not checker_code:
        raise HTTPException(status_code=403, detail="Không tìm thấy mã người dùng.")

    results = get_attendance_by_checker(checker_code)
    return JSONResponse(content=results)

# --- QR Checkin APIs ---

@app.get("/attendance/checkin")
def attendance_checkin(request: Request, token: str, db: Session = Depends(get_db)):
    log = db.query(AttendanceLog).filter_by(token=token).first()
    if not log:
        return HTMLResponse("Token không hợp lệ!", status_code=400)

    if log.checked_in:
        return templates.TemplateResponse(
            "qr_invalid.html",
            {"request": request, "message": "Mã QR này đã được sử dụng để điểm danh và không còn hợp lệ."},
            status_code=403
        )

    user = db.query(User).filter_by(code=log.user_code).first()
    if not user:
        return HTMLResponse("Không tìm thấy user!", status_code=400)

    user_data = {
        "code": user.code,
        "role": user.role,
        "branch": user.branch,
        "name": user.name
    }

    request.session.pop("user", None)
    request.session["pending_user"] = user_data
    role = user_data.get("role", "")

    return templates.TemplateResponse("attendance.html", {
        "request": request,
        "role": role,
        "branch_id": user.branch,
        "csrf_token": get_csrf_token(request),
        "user": user_data,
        "login_code": user.code,
        "token": token
    })

@app.post("/attendance/checkin_success")
async def checkin_success(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    token = data.get("token")
    user_code = None

    # Luồng 1: Điểm danh qua QR code (có token)
    if token:
        log = db.query(AttendanceLog).filter_by(token=token).first()
        if not log:
            # Frontend mong đợi JSON, không phải HTML
            return JSONResponse({"success": False, "error": "Token không hợp lệ"}, status_code=400)
        user_code = log.user_code
    # Luồng 2: Điểm danh trực tiếp trên mobile (không có token)
    # Trong luồng này, user đã được đăng nhập và log.checked_in=True từ trước.
    # Endpoint này chỉ cần xác nhận và trả về redirect.
    else:
        user_session = request.session.get("user")
        if not user_session or not user_session.get("code"):
            return JSONResponse({"success": False, "error": "Yêu cầu không hợp lệ, không tìm thấy session người dùng."}, status_code=403)
        user_code = user_session.get("code")
        work_date, shift = get_current_work_shift()
        log = db.query(AttendanceLog).filter_by(user_code=user_code, date=work_date, shift=shift).first()

    if not log:
        return JSONResponse({"success": False, "error": "Không tìm thấy bản ghi điểm danh."}, status_code=404)
    log.checked_in = True
    db.commit()

    # Logic chung: tìm user, cập nhật session và trả về redirect
    user = db.query(User).filter_by(code=user_code).first()
    if user:
        request.session["user"] = {
            "code": user.code,
            "role": user.role,
            "branch": user.branch,
            "name": user.name
        }
        request.session["after_checkin"] = "choose_function"
        request.session.pop("pending_user", None)
        return JSONResponse({"success": True, "redirect_to": "/choose-function"})
    
    return JSONResponse({"success": False, "error": "Không tìm thấy người dùng"}, status_code=404)


@app.get("/attendance/checkin_status")
async def checkin_status(request: Request, token: str, db: Session = Depends(get_db)):
    log = db.query(AttendanceLog).filter_by(token=token).first()
    if not log:
        return JSONResponse(content={"checked_in": False})

    if log.checked_in:
        user = db.query(User).filter_by(code=log.user_code).first()
        if user:
            # Đăng nhập cho user ở session của máy tính
            request.session["user"] = {
                "code": user.code,
                "role": user.role,
                "branch": user.branch,
                "name": user.name,
            }
            request.session.pop("pending_user", None)
            return JSONResponse(content={"checked_in": True, "redirect_to": "choose-function"})

    return JSONResponse(content={"checked_in": False})

@app.get("/favicon.ico")
def favicon():
    # Nếu có file favicon.ico trong static thì trả về file đó
    favicon_path = os.path.join("static", "favicon.ico")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    # Nếu không có, trả về 1x1 PNG trắng
    png_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\xdac\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\x0b\x0c\x00\x00\x00\x00IEND\xaeB`\x82'
    return Response(content=png_data, media_type="image/png")
