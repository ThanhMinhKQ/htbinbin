from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
import os
from datetime import datetime, time

from ..db.session import get_db
from ..db.models import User, ServiceRecord, Branch, AttendanceRecord
from ..core.security import get_csrf_token
from ..core.utils import VN_TZ # Import múi giờ VN
from ..core.config import logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import cast, Date, desc, or_, func
from sqlalchemy.orm import joinedload

from fastapi.templating import Jinja2Templates

router = APIRouter()

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
templates = Jinja2Templates(directory=os.path.join(APP_ROOT, "templates"))

def _get_active_buong_phong_query(db: Session, branch_code: str):
    """
    Hàm helper: Lấy danh sách Buồng phòng đã điểm danh HÔM NAY.
    Dựa trực tiếp vào dữ liệu snapshot trong AttendanceRecord để đảm bảo chính xác.
    """
    # 1. Xác định "Hôm nay" theo giờ Việt Nam
    today = datetime.now(VN_TZ).date()
    
    # 2. Truy vấn trực tiếp bảng AttendanceRecord
    # Logic: 
    # - Ngày điểm danh là hôm nay.
    # - Chi nhánh làm việc khớp với chi nhánh hiện tại.
    # - Vai trò là Buồng phòng (check nhiều trường hợp tên gọi).
    
    query = db.query(
        AttendanceRecord.employee_code_snapshot,
        AttendanceRecord.employee_name_snapshot,
        AttendanceRecord.main_branch_snapshot,
        Branch.branch_code.label("checked_at_branch")
    ).join(Branch, AttendanceRecord.branch_id == Branch.id  # Join để lấy mã chi nhánh làm việc
    ).filter(
        # Lọc theo ngày hôm nay (cast sang Date để bỏ qua giờ phút)
        cast(AttendanceRecord.attendance_datetime, Date) == today,
        
        # Lọc đúng chi nhánh đang chọn
        Branch.branch_code == branch_code,
        
        # Lọc vai trò: Kiểm tra linh hoạt nhiều kiểu viết tắt
        or_(
            func.lower(AttendanceRecord.role_snapshot) == 'buongphong',
            func.lower(AttendanceRecord.role_snapshot) == 'buồng phòng',
            func.lower(AttendanceRecord.role_snapshot) == 'bp',
            # [QUAN TRỌNG] Fallback: Nếu role sai, kiểm tra mã nhân viên bắt đầu bằng 'bp.'
            AttendanceRecord.employee_code_snapshot.ilike('bp.%')
        )
    ).distinct()
    
    return query

@router.get("", response_class=HTMLResponse)
def attendance_service_ui(request: Request, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data:
        return RedirectResponse("/login", status_code=303)
    
    if user_data.get("role") in ["quanly", "ktv", "admin", "boss"]:
        return RedirectResponse("/choose-function", status_code=303)

    # Lấy chi nhánh đang hoạt động
    current_branch_code = request.session.get("active_branch") or user_data.get("main_branch")

    initial_employees = []
    try:
        if current_branch_code:
            # Gọi hàm query đã sửa
            recent_records = _get_active_buong_phong_query(db, current_branch_code).all()
            
            initial_employees = [
                {
                    "code": rec.employee_code_snapshot, 
                    "name": rec.employee_name_snapshot, 
                    "branch": rec.checked_at_branch if rec.checked_at_branch else rec.main_branch_snapshot, 
                    "so_phong": "", 
                    "so_luong": "", 
                    "dich_vu": "", 
                    "ghi_chu": ""
                }
                for rec in recent_records
            ]
    except Exception as e:
        logger.error(f"Lỗi khi lấy danh sách buồng phòng: {e}")
    
    csrf_token = get_csrf_token(request)
    
    response = templates.TemplateResponse("service.html", {
        "request": request,
        "csrf_token": csrf_token,
        "user": user_data,
        "initial_employees": initial_employees,
    })
    
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@router.get("/api/get-checked-in-bp")
def get_checked_in_bp_today(request: Request, db: Session = Depends(get_db)):
    """API làm mới danh sách nhân viên"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Không có quyền truy cập.")

    current_branch_code = request.session.get("active_branch") or user_data.get("main_branch")

    try:
        records = _get_active_buong_phong_query(db, current_branch_code).all()
        
        result = [
            {
                "code": r.employee_code_snapshot, 
                "name": r.employee_name_snapshot, 
                "branch": r.checked_at_branch,
                "so_phong": "", "so_luong": "", "dich_vu": "", "ghi_chu": ""
            }
            for r in records
        ]
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"API Error: {e}")
        return JSONResponse(content=[])

@router.post("/checkin_bulk")
async def service_checkin_bulk(request: Request, db: Session = Depends(get_db)):
    session_user = request.session.get("user")
    if not session_user:
        raise HTTPException(status_code=403, detail="Chưa đăng nhập.")

    checker = db.query(User).filter(User.employee_code == session_user["code"]).first()
    if not checker:
        raise HTTPException(status_code=403, detail="User lỗi.")

    try:
        raw_data = await request.json()
        if not raw_data:
            return {"status": "success", "inserted": 0}

        # Xử lý chi nhánh từ payload hoặc lấy của user
        first_item = raw_data[0] if isinstance(raw_data, list) else {}
        branch_code_in = first_item.get("chi_nhanh_lam")
        
        branch_obj = None
        if branch_code_in:
            branch_obj = db.query(Branch).filter(Branch.branch_code == branch_code_in).first()
        
        target_branch_id = branch_obj.id if branch_obj else checker.main_branch_id

        # Lấy danh sách mã nhân viên để query 1 lần
        codes = [rec.get("ma_nv") for rec in raw_data if rec.get("ma_nv")]
        users_map = {}
        if codes:
            users = db.query(User).options(joinedload(User.main_branch), joinedload(User.department))\
                      .filter(User.employee_code.in_(codes)).all()
            users_map = {u.employee_code: u for u in users}

        new_records = []
        now_vn = datetime.now(VN_TZ)

        for rec in raw_data:
            ma_nv = rec.get("ma_nv")
            user_snap = users_map.get(ma_nv)
            if not user_snap: continue

            # Validate số lượng
            try:
                qty = int(rec.get("so_luong"))
            except (ValueError, TypeError):
                qty = None

            # Chỉ lưu nếu có dịch vụ hoặc số phòng
            if not rec.get("dich_vu") and not rec.get("so_phong"):
                continue

            new_records.append(ServiceRecord(
                user_id=user_snap.id,
                checker_id=checker.id,
                branch_id=target_branch_id,
                is_overtime=bool(rec.get("la_tang_ca")),
                notes=rec.get("ghi_chu", ""),
                employee_code_snapshot=user_snap.employee_code,
                employee_name_snapshot=user_snap.name,
                role_snapshot=user_snap.department.name if user_snap.department else '',
                main_branch_snapshot=user_snap.main_branch.branch_code if user_snap.main_branch else '',
                service_datetime=now_vn,
                service_type=rec.get("dich_vu", ""),
                room_number=rec.get("so_phong", ""),
                quantity=qty
            ))

        if new_records:
            db.add_all(new_records)
            db.commit()

        return {"status": "success", "message": "Lưu thành công."}

    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi save service: {e}")
        raise HTTPException(status_code=500, detail="Lỗi server.")
