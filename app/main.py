# app/main.py
import warnings
warnings.filterwarnings("ignore", message=".*NotOpenSSLWarning.*")
warnings.filterwarnings("ignore", message=".*urllib3.*LibreSSL.*")
try:
    from urllib3.exceptions import NotOpenSSLWarning
    warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
except ImportError:
    pass

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
    results, export, service, shift_report, inventory,
    ota_dashboard, hr_management
)
from .api.pms import (
    pages_router as pms_pages,
    rooms_router as pms_rooms,
    checkin_router as pms_checkin,
    checkout_router as pms_checkout,
    stays_router as pms_stays,
    admin_router as pms_admin,
    vn_address_router as pms_vn_address,
    guest_activities_router as pms_guest_activities,
    cccd_scan_router as pms_cccd_scan,
)

from .core.config import settings, logger
from .core.utils import VN_TZ
from .db.session import SessionLocal, engine, _task_engine, Base
from .db.utils import reset_all_sequences, sync_employees_on_startup, sync_master_data
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

@app.middleware("http")
async def add_env_to_state(request: Request, call_next):
    request.state.is_prod = settings.ENVIRONMENT.lower() == "production"
    response = await call_next(request)
    return response

# [QUAN TRỌNG] 2. Add SessionMiddleware SAU CÙNG
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)


# --- STATIC FILES ---
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# --- UPLOAD FILES ---
uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
if not os.path.exists(uploads_dir):
    os.makedirs(uploads_dir)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

# --- STARTUP EVENT ---
@app.on_event("startup")
async def startup_event():
    """
    Khởi tạo DB và Scheduler khi ứng dụng bắt đầu.
    """
    logger.info("🚀 Bắt đầu quá trình khởi động ứng dụng...")

    # ── Retry DB startup (chịu transient Supabase errors: "DbHandler exited") ──
    import asyncio as _asyncio
    _max_startup_retries = 5
    _startup_retry_delays = [3, 6, 12, 20, 30]  # giây giữa các lần thử

    for _attempt in range(_max_startup_retries):
        try:
            # Tạo bảng nếu chưa có
            # Dùng _task_engine (NullPool) để tránh cạnh tranh connection pool
            Base.metadata.create_all(bind=_task_engine)

            # Dùng context manager để đảm bảo đóng session an toàn
            with SessionLocal() as db:
                reset_all_sequences(db)
                sync_master_data(db)
                sync_employees_on_startup(db)

            logger.info(f"✅ DB startup thành công (lần thử {_attempt + 1})")
            break  # Thành công → thoát retry loop

        except Exception as e:
            if _attempt < _max_startup_retries - 1:
                _wait = _startup_retry_delays[_attempt]
                logger.warning(
                    f"⚠️ DB startup lỗi (lần {_attempt + 1}/{_max_startup_retries}): {e}. "
                    f"Thử lại sau {_wait}s..."
                )
                await _asyncio.sleep(_wait)
            else:
                # Hết retry → vẫn tiếp tục khởi động (không crash app)
                # App sẽ hoạt động nhưng DB queries sẽ fail cho đến khi Supabase phục hồi
                logger.error(
                    f"❌ DB startup thất bại sau {_max_startup_retries} lần thử: {e}. "
                    "App vẫn khởi động — DB sẽ tự phục hồi khi Supabase ổn định."
                )
    # ──────────────────────────────────────────────────────────────────────────

    try:
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

            # --- GMAIL WATCH RENEWAL (Mỗi ngày 06:00) ---
            def renew_gmail_watch():
                try:
                    from app.services.ota_agent.gmail_service import gmail_service
                    result = gmail_service.watch_inbox()
                    if result:
                        logger.info(f"✅ [Scheduler] Gmail Watch gia hạn thành công! historyId={result.get('historyId')}")
                    else:
                        logger.warning("⚠️ [Scheduler] Gmail Watch gia hạn thất bại - kiểm tra token và Pub/Sub config")
                except Exception as e:
                    logger.error(f"❌ [Scheduler] Lỗi gia hạn Gmail Watch: {e}")

            scheduler.add_job(
                renew_gmail_watch,
                'cron', hour=6, minute=0,
                misfire_grace_time=900,
                id="gmail_watch_renewal"
            )
            logger.info("📧 Cronjob Gmail Watch Renewal đã đăng ký (chạy mỗi ngày 06:00)")

            scheduler.start()
            atexit.register(lambda: scheduler.shutdown())
            logger.info("✅ Các tác vụ nền (Scheduler) đã được lập lịch.")

    except Exception as e:
        logger.error(f"❌ Lỗi khởi động Scheduler: {e}", exc_info=True)
    
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
app.include_router(
    inventory.router_ui, 
    prefix="/inventory", 
    tags=["Inventory UI"]
)
app.include_router(
    inventory.router, 
    prefix="/api/inventory", 
    tags=["Inventory API"]
)

# 2. Các router KHÔNG có prefix (Root level)
app.include_router(users.router, tags=["Authentication"]) 
app.include_router(tasks.router, tags=["Tasks"])
app.include_router(choose_function.router, tags=["Core UI"])
app.include_router(utils.router, tags=["Utilities"])
app.include_router(export.router, tags=["Export"])

# OTA Dashboard API
app.include_router(ota_dashboard.router, tags=["OTA Dashboard"])

# HR Management (Admin only)
app.include_router(hr_management.router, tags=["HR Management"])

# PMS - Property Management System
app.include_router(pms_pages, tags=["PMS"])
app.include_router(pms_rooms, tags=["PMS"])
app.include_router(pms_checkin, tags=["PMS"])
app.include_router(pms_checkout, tags=["PMS"])
app.include_router(pms_stays, tags=["PMS"])
app.include_router(pms_admin, tags=["PMS Admin"])
app.include_router(pms_vn_address, tags=["PMS VN Address"])
app.include_router(pms_guest_activities, tags=["PMS Guest Activities"])
app.include_router(pms_cccd_scan, tags=["PMS CCCD Scan"])


# --- ROOT ENDPOINT ---
@app.get("/", include_in_schema=False)
def root(request: Request):
    """
    Điều hướng người dùng về trang chủ hoặc đăng nhập
    """
    if request.session.get("user"):
        return RedirectResponse(url="/choose-function", status_code=303)
    return RedirectResponse(url="/login", status_code=303)