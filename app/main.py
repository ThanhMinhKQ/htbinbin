# app/main.py
import os
import atexit
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware # Cần import cái này
from apscheduler.schedulers.background import BackgroundScheduler

# --- IMPORT MODULES ---
from .api import (
    users, attendance, tasks, lost_and_found, 
    choose_function, utils, calendar, qr_checkin, 
    results, export, service, shift_report
)

from .core.config import settings, logger
from .core.utils import VN_TZ
from .db.session import SessionLocal, engine, Base
from .db.utils import reset_all_sequences, sync_employees_on_startup
from .db.models import User
from .services.missing_attendance_service import run_daily_absence_check
from .services.task_service import update_overdue_tasks_status
from .services.lost_and_found_service import update_disposable_items_status

# --- KHỞI TẠO APP ---
app = FastAPI(
    title="Bin Bin Hotel Management System",
    description="Hệ thống quản lý nội bộ khách sạn Bin Bin.",
    version="1.0.0"
)

# --- MIDDLEWARE ---

@app.middleware("http")
async def ensure_active_branch_in_session(request: Request, call_next):
    # 1. Lấy thông tin từ session
    user_data = request.session.get("user")
    active_branch = request.session.get("active_branch")
    
    # 2. Logic: Nếu đã login (có user) nhưng chưa có active_branch (hoặc active_branch bị N/A)
    if user_data and not active_branch:
        db = SessionLocal()
        try:
            # Truy vấn lại user mới nhất từ DB để lấy Role chuẩn
            current_user = db.query(User).filter(User.id == user_data.get("id")).first()
            
            if current_user:
                # Xử lý Role: chuyển về chữ thường và cắt khoảng trắng thừa
                role = str(current_user.department.role_code if current_user.department else "").strip().lower()
                
                # Check danh sách quyền Admin mở rộng
                admin_roles = ["admin", "superadmin", "quanly", "manager", "boss", "giamdoc"]
                
                if role in admin_roles:
                    request.session["active_branch"] = "HỆ THỐNG"
                    logger.info(f"Middleware: Đã set 'HỆ THỐNG' cho user {current_user.employee_code} (Role: {role})")
                
                elif current_user.last_active_branch:
                    request.session["active_branch"] = current_user.last_active_branch
                
                else:
                    request.session["active_branch"] = "Chưa phân bổ"

        except Exception as e:
            logger.error(f"Middleware Error: {e}")
        finally:
            db.close()
    
    response = await call_next(request)
    return response

# [QUAN TRỌNG] 2. Add SessionMiddleware SAU CÙNG
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)


# --- STATIC FILES ---
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# --- STARTUP EVENT ---
@app.on_event("startup")
async def startup_event():
    """
    Khởi tạo DB và Scheduler khi ứng dụng bắt đầu.
    """
    logger.info("🚀 Bắt đầu quá trình khởi động ứng dụng...")

    # Tạo bảng nếu chưa có
    Base.metadata.create_all(bind=engine)
    
    try:
        # Dùng context manager để đảm bảo đóng session an toàn
        with SessionLocal() as db:
            reset_all_sequences(db)
            sync_employees_on_startup(db)

        # Logic Scheduler (chỉ chạy ở process chính để tránh duplicate khi dev reload)
        if os.environ.get("UVICORN_RELOAD") != "true":
            scheduler = BackgroundScheduler(timezone=str(VN_TZ))
            
            # 7:05 sáng hàng ngày check vắng mặt
            scheduler.add_job(
                run_daily_absence_check, 
                'cron', hour=7, minute=5, 
                misfire_grace_time=900, id="daily_absence_check"
            )
            
            # 30 phút/lần update task quá hạn
            scheduler.add_job(
                update_overdue_tasks_status, 
                'cron', hour='0-23', minute='*/30', 
                misfire_grace_time=300, id="update_overdue_tasks"
            )
            
            scheduler.start()
            atexit.register(lambda: scheduler.shutdown())
            logger.info("✅ Các tác vụ nền (Scheduler) đã được lập lịch.")

    except Exception as e:
        logger.error(f"❌ Lỗi khởi động: {e}", exc_info=True)
    
    logger.info("✅ Startup hoàn tất.")


# --- ROUTERS ---
# 1. Các router có prefix (tiền tố URL)
app.include_router(attendance.router, prefix="/attendance", tags=["Attendance"])
app.include_router(calendar.router, prefix="/attendance", tags=["Calendar"])
app.include_router(qr_checkin.router, prefix="/attendance", tags=["QR Check-in"])
app.include_router(results.router, prefix="/attendance", tags=["Results"])
app.include_router(service.router, prefix="/service", tags=["Service"])
app.include_router(lost_and_found.router, prefix="/lost-and-found", tags=["Lost & Found"])
app.include_router(shift_report.router, prefix="/shift-report", tags=["Shift Report"])

# 2. Các router KHÔNG có prefix (Root level)
app.include_router(users.router, tags=["Authentication"]) 
app.include_router(tasks.router, tags=["Tasks"])
app.include_router(choose_function.router, tags=["Core UI"])
app.include_router(utils.router, tags=["Utilities"])
app.include_router(export.router, tags=["Export"])


# --- ROOT ENDPOINT ---
@app.get("/", include_in_schema=False)
def root(request: Request):
    """
    Điều hướng người dùng về trang chủ hoặc đăng nhập
    """
    if request.session.get("user"):
        return RedirectResponse(url="/choose-function", status_code=303)
    return RedirectResponse(url="/login", status_code=303)
