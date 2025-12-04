from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
import os
from datetime import datetime, timedelta  # <--- [FIX] Thêm timedelta

from ..db.session import get_db
from ..db.models import User, ServiceRecord, Branch, AttendanceRecord
from ..core.security import get_csrf_token
from ..core.utils import VN_TZ 
from ..core.config import logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import cast, Date, desc, or_, func

from fastapi.templating import Jinja2Templates

router = APIRouter()

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
templates = Jinja2Templates(directory=os.path.join(APP_ROOT, "templates"))

# --- Hàm hỗ trợ xác định chi nhánh ---
def _resolve_current_branch(db: Session, request: Request, user_id: int):
    """
    Hàm hỗ trợ xác định chi nhánh hiện tại của user.
    Ưu tiên: Session đang chọn -> Chi nhánh chính của user.
    """
    # 1. Kiểm tra nếu user đã chọn chi nhánh (lưu trong session)
    active_branch_code = request.session.get("active_branch")
    if active_branch_code:
        branch = db.query(Branch).filter(Branch.branch_code == active_branch_code).first()
        if branch:
            return branch

    # 2. Nếu không, lấy chi nhánh chính của nhân viên
    if user_id:
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.main_branch:
            return user.main_branch
    
    return None

# --- [FIXED] Hàm Query tối ưu theo Ca 7h-7h & Lọc theo User ---
def _get_active_buong_phong_query(db: Session, branch_obj: Branch, current_user_id: int):
    """
    Lấy danh sách BP:
    1. Đúng chi nhánh.
    2. Trong ca làm việc (7h sáng -> 7h sáng hôm sau).
    3. [MỚI] Chỉ lấy nhân viên do chính `current_user_id` điểm danh.
    """
    if not branch_obj:
        return []

    # 1. Xử lý Logic Ca làm việc (7:00 AM - 7:00 AM next day)
    now_vn = datetime.now(VN_TZ)
    
    # Nếu hiện tại chưa tới 7h sáng (ví dụ 2h sáng), thì vẫn thuộc ca của ngày hôm qua
    if now_vn.hour < 7:
        start_of_shift = (now_vn - timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
    else:
        # Nếu đã qua 7h sáng, thì là ca của ngày hôm nay
        start_of_shift = now_vn.replace(hour=7, minute=0, second=0, microsecond=0)
    
    end_of_shift = start_of_shift + timedelta(days=1)

    # 2. Tối ưu Data Transfer (Chỉ lấy cột cần thiết)
    query = db.query(
        AttendanceRecord.employee_code_snapshot,
        AttendanceRecord.employee_name_snapshot,
        AttendanceRecord.main_branch_snapshot
    ).filter(
        # A. Lọc theo khung giờ ca làm việc
        AttendanceRecord.attendance_datetime >= start_of_shift,
        AttendanceRecord.attendance_datetime < end_of_shift,
        
        # B. Đúng chi nhánh
        AttendanceRecord.branch_id == branch_obj.id, 
        
        # C. [MỚI] Chỉ lấy nhân viên do chính User này điểm danh (tránh lộn ca)
        # Giả định model AttendanceRecord có trường `checker_id`. 
        # Nếu tên trường khác (vd: created_by_id), bạn hãy sửa lại tên ở dòng dưới.
        AttendanceRecord.checker_id == current_user_id,

        # D. Lọc Role Buồng phòng/Tạp vụ
        or_(
            AttendanceRecord.employee_code_snapshot.ilike("bp%"),       
            AttendanceRecord.role_snapshot.ilike("%buồng phòng%"),     
            AttendanceRecord.role_snapshot.ilike("%buong phong%"),
            func.lower(AttendanceRecord.role_snapshot) == "buongphong"
        )
    ).distinct()

    return query.all()

@router.get("", response_class=HTMLResponse)
def attendance_service_ui(request: Request, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data:
        return RedirectResponse("/login", status_code=303)
    
    # Logic phân quyền
    if user_data.get("role") in ["quanly", "ktv", "admin", "boss"]:
        return RedirectResponse("/choose-function", status_code=303)

    user_id = user_data.get("id")
    target_branch = _resolve_current_branch(db, request, user_id)
    
    initial_employees = []
    current_branch_display = ""

    if target_branch:
        current_branch_display = target_branch.branch_code
        try:
            # [FIX] Truyền thêm user_id vào hàm query
            recent_records = _get_active_buong_phong_query(db, target_branch, user_id)
            
            initial_employees = [
                {
                    "code": rec.employee_code_snapshot, 
                    "name": rec.employee_name_snapshot, 
                    "branch": rec.main_branch_snapshot, 
                    "checked_at": target_branch.branch_code,
                    "so_phong": "", "so_luong": "", "dich_vu": "", "ghi_chu": ""
                }
                for rec in recent_records
            ]
        except Exception as e:
            logger.error(f"Lỗi service UI: {e}", exc_info=True)
    else:
        print("[DEBUG] Vẫn không xác định được chi nhánh nào.")

    csrf_token = get_csrf_token(request)
    
    response = templates.TemplateResponse("service.html", {
        "request": request,
        "csrf_token": csrf_token,
        "user": user_data,
        "initial_employees": initial_employees,
        "detected_branch": current_branch_display 
    })
    
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@router.get("/api/get-checked-in-bp")
def get_checked_in_bp_today(request: Request, db: Session = Depends(get_db)):
    """API làm mới danh sách (Nút Tải lại)"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Cấm truy cập.")

    user_id = user_data.get("id")
    target_branch = _resolve_current_branch(db, request, user_id)

    if not target_branch:
        return JSONResponse(content=[])

    try:
        # [FIX] Truyền thêm user_id vào hàm query
        records = _get_active_buong_phong_query(db, target_branch, user_id)
        result = [
            {
                "code": r.employee_code_snapshot, 
                "name": r.employee_name_snapshot, 
                "branch": r.main_branch_snapshot,
                "so_phong": "", "so_luong": "", "dich_vu": "", "ghi_chu": ""
            }
            for r in records
        ]
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"API Error: {e}", exc_info=True)
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

        # Xác định chi nhánh ghi nhận dịch vụ
        target_branch_id = checker.main_branch_id 
        
        first_item = raw_data[0] if isinstance(raw_data, list) else {}
        branch_code_in = first_item.get("chi_nhanh_lam")
        
        if branch_code_in:
            b_obj = db.query(Branch).filter(Branch.branch_code == branch_code_in).first()
            if b_obj:
                target_branch_id = b_obj.id

        # Query User tối ưu
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

            # Validate số lượng an toàn
            qty = None
            try:
                if rec.get("so_luong"):
                    qty = int(rec.get("so_luong"))
            except: pass

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
        logger.error(f"Lỗi save service: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi server.")
