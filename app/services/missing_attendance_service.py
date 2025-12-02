import sys
import os
from datetime import datetime, time, timedelta, date
from typing import Optional, List
from sqlalchemy import and_, or_, cast, Date
from sqlalchemy.orm import Session, joinedload
import pytz

# --- Setup đường dẫn để import được từ thư mục cha (nếu chạy script độc lập) ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.db.session import SessionLocal
from app.db.models import User, AttendanceRecord, Department, Branch
from app.core.config import logger

# Định nghĩa múi giờ chuẩn VN như file cũ
VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

def run_daily_absence_check(target_date: Optional[date] = None):
    """
    Hàm entry point để Scheduler gọi hoặc chạy thủ công.
    """
    # Nếu không truyền ngày, mặc định lấy ngày hôm qua (theo giờ VN)
    if target_date is None:
        now_vn = datetime.now(VN_TZ)
        target_date = now_vn.date() - timedelta(days=1)
        log_prefix = "TỰ ĐỘNG"
    else:
        log_prefix = "THỦ CÔNG"

    logger.info(f"--- Bắt đầu chạy cập nhật vắng mặt {log_prefix} cho ngày {target_date.strftime('%d/%m/%Y')} ---")
    update_missing_attendance_to_db(target_date=target_date)
    logger.info(f"--- Hoàn tất cập nhật vắng mặt cho ngày {target_date.strftime('%d/%m/%Y')} ---")

def update_missing_attendance_to_db(target_date: date):
    """
    Logic cốt lõi: So sánh danh sách nhân viên active và danh sách đã chấm công
    để tìm người vắng mặt.
    """
    workday_str = target_date.strftime('%d/%m/%Y')
    
    with SessionLocal() as db:
        try:
            # =========================================================================
            # BƯỚC 1: Dọn dẹp dữ liệu cũ (Giống file cũ)
            # =========================================================================
            # Xóa các bản ghi do hệ thống tự tạo (checker_id là NULL) của ngày này
            # để tránh trùng lặp nếu lỡ chạy script 2 lần.
            deleted_count = db.query(AttendanceRecord).filter(
                cast(AttendanceRecord.attendance_datetime, Date) == target_date,
                AttendanceRecord.checker_id == None, # Dấu hiệu nhận biết bản ghi tự động
                AttendanceRecord.work_units == 0 
            ).delete(synchronize_session=False)
            
            if deleted_count > 0:
                logger.info(f"[CLEANUP] Đã xóa {deleted_count} bản ghi vắng mặt cũ ngày {workday_str}.")

            # =========================================================================
            # BƯỚC 2: Xác định khung giờ làm việc (Logic Ca Đêm từ file cũ)
            # =========================================================================
            # Một ngày làm việc tính từ 07:00 sáng hôm đó đến 07:00 sáng hôm sau
            start_datetime = datetime.combine(target_date, time(7, 0, 0))
            end_datetime = start_datetime + timedelta(days=1) # Tức là 7:00 sáng hôm sau

            # =========================================================================
            # BƯỚC 3: Lấy danh sách ID nhân viên ĐÃ ĐIỂM DANH
            # =========================================================================
            # Chỉ cần họ có 1 bản ghi bất kỳ (công > 0) trong khung giờ trên là coi như có đi làm
            checked_in_users = db.query(AttendanceRecord.user_id).filter(
                AttendanceRecord.attendance_datetime >= start_datetime,
                AttendanceRecord.attendance_datetime < end_datetime,
                AttendanceRecord.work_units > 0
            ).all()
            
            # Chuyển thành Set để tra cứu cho nhanh
            checked_in_ids = {u.user_id for u in checked_in_users}
            logger.info(f"[CHECK] Ngày {workday_str}: Có {len(checked_in_ids)} nhân viên đã đi làm.")

            # =========================================================================
            # BƯỚC 4: Lấy danh sách nhân viên CẦN KIỂM TRA (Logic lọc role từ file cũ)
            # =========================================================================
            # Lấy tất cả user đang active, kèm thông tin phòng ban
            all_employees = db.query(User).options(
                joinedload(User.department),
                joinedload(User.main_branch)
            ).filter(
                User.is_active == True
            ).all()

            new_absence_records = []
            
            for emp in all_employees:
                # --- A. Lọc Logic (Giống file cũ) ---
                
                # 1. Bỏ qua nếu không có phòng ban
                if not emp.department:
                    continue
                    
                role_code = (emp.department.role_code or "").lower()
                emp_code = (emp.employee_code or "").upper()
                
                # 2. Loại trừ Boss và Admin
                if role_code in ['boss', 'admin']:
                    continue
                
                # 3. Loại trừ bộ phận Dịch Vụ (DV) nếu mã nhân viên chứa "DV" 
                # (Logic file cũ: if "DV" in code_upper -> return "DV" -> continue)
                if "DV" in emp_code:
                    continue

                # --- B. Kiểm tra vắng mặt ---
                if emp.id not in checked_in_ids:
                    
                    # QUAN TRỌNG: Xử lý vấn đề "Chi nhánh làm"
                    # Chúng ta vẫn PHẢI lưu branch_id vào DB để không lỗi Foreign Key/Join.
                    # Nhưng ở api/results.py (bạn đã sửa), nó sẽ tự động ẩn đi khi hiển thị.
                    
                    main_branch_id = emp.main_branch_id
                    main_branch_name = emp.main_branch.branch_code if emp.main_branch else ''

                    # Nếu user không có chi nhánh chính (lỗi dữ liệu), gán tạm chi nhánh đầu tiên để không lỗi code
                    if not main_branch_id:
                        first_branch = db.query(Branch).first()
                        if first_branch:
                            main_branch_id = first_branch.id
                            main_branch_name = first_branch.branch_code

                    record = AttendanceRecord(
                        user_id=emp.id,
                        checker_id=None,    # NULL = Hệ thống tự động
                        branch_id=main_branch_id, # Bắt buộc có để query report chạy được
                        
                        # Snapshot thông tin tại thời điểm ghi nhận
                        employee_code_snapshot=emp.employee_code,
                        employee_name_snapshot=emp.name,
                        role_snapshot=emp.department.name,
                        main_branch_snapshot=main_branch_name,
                        
                        # Thời gian: Ghi nhận vào 23:59 của ngày đó
                        attendance_datetime=datetime.combine(target_date, time(23, 59, 0)),
                        work_units=0.0,     # 0 công
                        is_overtime=False,
                        notes=f"Hệ thống: Nghỉ không phép ngày {workday_str}"
                    )
                    new_absence_records.append(record)

            # =========================================================================
            # BƯỚC 5: Lưu vào DB
            # =========================================================================
            if new_absence_records:
                db.add_all(new_absence_records)
                db.commit()
                logger.info(f"[UPDATE] Ngày {workday_str}: Đã ghi nhận {len(new_absence_records)} nhân viên vắng mặt.")
            else:
                logger.info(f"[UPDATE] Ngày {workday_str}: Không có nhân viên vắng mặt (hoặc tất cả đã chấm công).")

        except Exception as e:
            db.rollback()
            logger.error(f"[ERROR] Lỗi khi cập nhật vắng mặt ngày {workday_str}: {str(e)}", exc_info=True)
            # Không raise lỗi crash app, chỉ log lại để admin biết

if __name__ == "__main__":
    # Script chạy thử nghiệm
    run_daily_absence_check()
