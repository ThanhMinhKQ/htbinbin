from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
import os
from datetime import datetime, timedelta, time # Đảm bảo đã import time

from ..db.session import get_db
from ..db.models import User, ServiceRecord, Branch, Department, AttendanceRecord
from ..core.security import get_csrf_token
from ..core.utils import get_current_work_shift, VN_TZ
from ..core.config import logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import cast, Date, and_
from sqlalchemy.orm import joinedload

from fastapi.templating import Jinja2Templates

router = APIRouter()

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
templates = Jinja2Templates(directory=os.path.join(APP_ROOT, "templates"))

# --- Helper function ĐÃ ĐƯỢC CHỈNH SỬA ---
def get_work_date_range(work_date):
    """
    Tạo khoảng thời gian cho ca làm việc chuẩn khách sạn:
    Từ 07:00:00 sáng ngày work_date đến 07:00:00 sáng ngày hôm sau.
    Ví dụ: Ngày 01/01 -> Từ 07:00 01/01 đến 07:00 02/01.
    """
    # [FIX] Bắt đầu từ 07:00:00 thay vì 00:00:00
    start_dt = datetime.combine(work_date, time(7, 0, 0))
    
    # Kết thúc là 07:00:00 sáng hôm sau
    # Dùng toán tử < end_dt sẽ lấy đến 06:59:59.999
    end_dt = start_dt + timedelta(days=1)
    
    return start_dt, end_dt

@router.get("", response_class=HTMLResponse)
def attendance_service_ui(request: Request, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data:
        return RedirectResponse("/login", status_code=303)
    
    if user_data.get("role") in ["quanly", "ktv", "admin", "boss"]:
        return RedirectResponse("/choose-function", status_code=303)

    active_branch_code = request.session.get("active_branch")
    
    active_branch_obj = None
    if active_branch_code:
        active_branch_obj = db.query(Branch).filter(Branch.branch_code == active_branch_code).first()
    
    # === LẤY DANH SÁCH NHÂN VIÊN ===
    checker_id = user_data.get("id")
    
    # Hàm này trả về ngày làm việc logic (VD: 2h sáng ngày 2/1 vẫn trả về ngày 1/1)
    work_date, _ = get_current_work_shift()
    
    # [LOGIC MỚI] Lấy range từ 7h sáng nay đến 7h sáng mai
    start_dt, end_dt = get_work_date_range(work_date)

    buong_phong_dept = db.query(Department).filter(Department.role_code == 'buongphong').first()
    initial_employees = []

    if buong_phong_dept and active_branch_obj:
        # Query lọc theo khoảng thời gian chuẩn 7h-7h
        recent_records = db.query(
            AttendanceRecord.employee_code_snapshot,
            AttendanceRecord.employee_name_snapshot,
            AttendanceRecord.main_branch_snapshot
        ).join(User, AttendanceRecord.user_id == User.id
        ).filter(
            AttendanceRecord.checker_id == checker_id,
            User.department_id == buong_phong_dept.id,
            AttendanceRecord.attendance_datetime >= start_dt,     # >= 07:00 sáng
            AttendanceRecord.attendance_datetime < end_dt,        # < 07:00 sáng hôm sau
            AttendanceRecord.branch_id == active_branch_obj.id
        ).distinct().all()

        initial_employees = [
            {
                "code": rec.employee_code_snapshot, 
                "name": rec.employee_name_snapshot, 
                "branch": rec.main_branch_snapshot, 
                "so_phong": "", "so_luong": "", "dich_vu": "", "ghi_chu": ""
            }
            for rec in recent_records
        ]
    elif not active_branch_obj:
        logger.warning(f"Chưa xác định chi nhánh làm việc cho session user: {user_data.get('code')}")
    
    csrf_token = get_csrf_token(request)
    
    response = templates.TemplateResponse("service.html", {
        "request": request,
        "csrf_token": csrf_token,
        "user": user_data,
        "initial_employees": initial_employees,
    })
    
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@router.post("/checkin_bulk")
async def service_checkin_bulk(request: Request, db: Session = Depends(get_db)):
    session_user = request.session.get("user")
    if not session_user:
        raise HTTPException(status_code=403, detail="Không có quyền điểm danh.")

    checker = db.query(User).filter(User.employee_code == session_user["code"]).first()
    if not checker:
        raise HTTPException(status_code=403, detail="Không tìm thấy người dùng thực hiện điểm danh.")

    try:
        raw_data = await request.json()
        if not isinstance(raw_data, list) or not raw_data:
            return {"status": "success", "inserted": 0}

        branch_code_from_payload = raw_data[0].get("chi_nhanh_lam")
        branch_obj = db.query(Branch).filter(Branch.branch_code == branch_code_from_payload).first()
        if not branch_obj:
            raise HTTPException(status_code=400, detail=f"Chi nhánh làm việc không hợp lệ: {branch_code_from_payload}")
        branch_id_lam = branch_obj.id

        employee_codes = {rec.get("ma_nv") for rec in raw_data if rec.get("ma_nv")}
        employees_in_db = db.query(User).options(
            joinedload(User.main_branch), 
            joinedload(User.department)
        ).filter(User.employee_code.in_(employee_codes)).all()
        employee_map = {emp.employee_code: emp for emp in employees_in_db}

        new_service_records = []
        now_vn = datetime.now(VN_TZ)

        for rec in raw_data:
            ma_nv = rec.get("ma_nv")
            employee_snapshot = employee_map.get(ma_nv)

            if not employee_snapshot:
                logger.warning(f"Bỏ qua chấm dịch vụ cho mã NV không tồn tại: {ma_nv}")
                continue
            
            so_luong_str = str(rec.get("so_luong", ''))
            quantity_val = int(so_luong_str) if so_luong_str.isdigit() else None

            new_service_records.append(ServiceRecord(
                user_id=employee_snapshot.id,
                checker_id=checker.id,
                branch_id=branch_id_lam,
                is_overtime=bool(rec.get("la_tang_ca")),
                notes=rec.get("ghi_chu", ""),
                employee_code_snapshot=employee_snapshot.employee_code,
                employee_name_snapshot=employee_snapshot.name,
                role_snapshot=employee_snapshot.department.name if employee_snapshot.department else '',
                main_branch_snapshot=employee_snapshot.main_branch.branch_code if employee_snapshot.main_branch else '',
                service_datetime=now_vn,
                service_type=rec.get("dich_vu", "N/A"),
                room_number=rec.get("so_phong", ""),
                quantity=quantity_val
            ))

        if new_service_records:
            db.add_all(new_service_records)
            db.commit()

        return {"status": "success", "message": "Đã ghi nhận dịch vụ thành công."}

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Lỗi khi lưu dịch vụ: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi khi lưu kết quả vào cơ sở dữ liệu.")

@router.get("/api/get-checked-in-bp")
def get_checked_in_bp_today(request: Request, db: Session = Depends(get_db)):
    """
    API lấy danh sách Buồng phòng đã được CHÍNH user này check-in trong "NGÀY LÀM VIỆC" (7h-7h).
    """
    user_data = request.session.get("user")
    if not user_data or user_data.get("role") != 'letan':
        raise HTTPException(status_code=403, detail="Không có quyền truy cập.")

    checker_id = user_data.get("id")
    work_date, _ = get_current_work_shift()
    
    # [FIX LOGIC] Áp dụng range 7h-7h cho API
    start_dt, end_dt = get_work_date_range(work_date)

    buong_phong_dept = db.query(Department).filter(Department.role_code == 'buongphong').first()
    if not buong_phong_dept:
        return JSONResponse(content=[])

    active_branch_code = request.session.get("active_branch")
    active_branch_obj = None
    if active_branch_code:
        active_branch_obj = db.query(Branch).filter(Branch.branch_code == active_branch_code).first()

    query = db.query(
        AttendanceRecord.employee_code_snapshot,
        AttendanceRecord.employee_name_snapshot,
        AttendanceRecord.main_branch_snapshot
    ).join(User, AttendanceRecord.user_id == User.id
    ).filter(
        AttendanceRecord.checker_id == checker_id,
        User.department_id == buong_phong_dept.id,
        AttendanceRecord.attendance_datetime >= start_dt, # >= 07:00
        AttendanceRecord.attendance_datetime < end_dt     # < 07:00 hôm sau
    )

    if active_branch_obj:
        query = query.filter(AttendanceRecord.branch_id == active_branch_obj.id)

    recent_records = query.distinct().all()

    initial_employees = [
        {
            "code": rec.employee_code_snapshot, 
            "name": rec.employee_name_snapshot, 
            "branch": rec.main_branch_snapshot, 
            "so_phong": "", "so_luong": "", "dich_vu": "", "ghi_chu": ""
        }
        for rec in recent_records
    ]
    
    return JSONResponse(content=initial_employees)
