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

# [SỬA ĐỔI QUAN TRỌNG] 1. Định nghĩa Middleware tùy chỉnh
@app.middleware("http")
async def ensure_active_branch_in_session(request: Request, call_next):
    """
    Middleware này chạy trước mỗi request.
    Nếu User đã đăng nhập nhưng Session bị mất 'active_branch' (do reload trang hoặc vào thẳng link),
    nó sẽ tự động vào DB lấy lại.
    
    CẬP NHẬT: Áp dụng cho TẤT CẢ nhân viên (thường + quản lý) để base.html luôn hiển thị chi nhánh.
    """
    # 1. Lấy thông tin từ session hiện tại
    user_data = request.session.get("user")
    active_branch = request.session.get("active_branch")
    
    # 2. [ĐÃ XÓA] Logic kiểm tra special_roles
    # Trước đây: special_roles = ["admin", "boss", "quanly", "ktv"]
    
    # 3. Kiểm tra điều kiện: Đã login + Chưa có branch trong session
    # Bỏ điều kiện "if role in special_roles" để áp dụng cho tất cả mọi người
    if user_data and not active_branch:
        # Mở kết nối DB tạm thời
        db = SessionLocal()
        try:
            # Truy vấn User để lấy last_active_branch mới nhất từ DB
            current_user = db.query(User).filter(User.id == user_data.get("id")).first()
            
            # Nếu trong DB có lưu chi nhánh lần cuối, nạp lại vào Session
            if current_user and current_user.last_active_branch:
                request.session["active_branch"] = current_user.last_active_branch
        except Exception as e:
            # Chỉ log lỗi, không làm crash ứng dụng
            logger.error(f"Middleware Error (Restore Branch): {e}")
        finally:
            db.close()
    
    # 4. Tiếp tục xử lý request như bình thường
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