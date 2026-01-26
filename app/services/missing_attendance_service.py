import sys
import os
from datetime import datetime, time, timedelta, date
from typing import Optional, List
from sqlalchemy import and_, or_, cast, Date
from sqlalchemy.orm import Session, joinedload
import pytz

# --- Setup đường dẫn ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.db.session import SessionLocal
from app.db.models import User, AttendanceRecord, Department, Branch
from app.core.config import logger

# [QUAN TRỌNG] Định nghĩa múi giờ
VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

def run_daily_absence_check(target_date: Optional[date] = None):
    # Nếu không truyền ngày, lấy ngày hôm qua
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
    workday_str = target_date.strftime('%d/%m/%Y')
    
    with SessionLocal() as db:
        try:
            # 1. Xóa bản ghi vắng mặt cũ (Hệ thống tạo) của ngày này để tránh trùng
            # Lưu ý: Khi xóa, ta phải tìm các bản ghi thuộc về "target_date" (ngày làm việc)
            # Dù bản ghi đó ghi giờ là 06:59 sáng hôm sau, ta vẫn cần logic để identify nó thuộc ngày nào.
            # Cách an toàn nhất là xóa theo khoảng thời gian của ca làm việc đó.
            
            start_clean = VN_TZ.localize(datetime.combine(target_date, time(7, 0, 0)))
            end_clean = start_clean + timedelta(days=1) # 7h sáng hôm sau

            db.query(AttendanceRecord).filter(
                AttendanceRecord.attendance_datetime >= start_clean,
                AttendanceRecord.attendance_datetime <= end_clean,
                AttendanceRecord.checker_id == None, 
                AttendanceRecord.work_units == 0 
            ).delete(synchronize_session=False)
            
            # =========================================================================
            # [FIX QUAN TRỌNG] XỬ LÝ TIMEZONE CHO KHUNG GIỜ CHECK-IN
            # =========================================================================
            start_naive = datetime.combine(target_date, time(7, 0, 0))
            end_naive = start_naive + timedelta(days=1) # 7:00 sáng hôm sau

            # Gán múi giờ VN vào để so sánh chính xác với Database
            start_datetime = VN_TZ.localize(start_naive)
            end_datetime = VN_TZ.localize(end_naive)

            # 2. Lấy danh sách ID đã điểm danh (Công > 0)
            checked_in_ids = {
                r.user_id for r in db.query(AttendanceRecord.user_id).filter(
                    AttendanceRecord.attendance_datetime >= start_datetime,
                    AttendanceRecord.attendance_datetime < end_datetime,
                    AttendanceRecord.work_units > 0
                ).distinct().all()
            }
            
            logger.info(f"[CHECK] Ngày {workday_str}: Tìm thấy {len(checked_in_ids)} nhân viên đã đi làm (từ 7h sáng đến 7h sáng hôm sau).")

            # 3. Lấy danh sách nhân viên cần kiểm tra
            all_employees = db.query(User).options(
                joinedload(User.department),
                joinedload(User.main_branch)
            ).filter(User.is_active == True).all()

            new_absence_records = []
            
            # [FIX LOGIC] Thời gian ghi nhận vắng: 06:59:00 của ngày HÔM SAU
            record_time_naive = datetime.combine(target_date + timedelta(days=1), time(6, 59, 0))
            record_datetime = VN_TZ.localize(record_time_naive)
            
            for emp in all_employees:
                # --- LỌC NHÂN VIÊN ---
                if not emp.department: continue
                
                role_code = (emp.department.role_code or "").lower()
                emp_code = (emp.employee_code or "").upper()
                
                # Bỏ qua Boss/Admin/Dịch vụ
                if role_code in ['boss', 'admin']: continue
                if "DV" in emp_code: continue

                # --- KIỂM TRA VẮNG MẶT ---
                if emp.id not in checked_in_ids:
                    
                    # Xử lý Chi nhánh
                    main_branch_id = emp.main_branch_id
                    main_branch_name = emp.main_branch.branch_code if emp.main_branch else ''
                    if not main_branch_id:
                        first_branch = db.query(Branch).first()
                        if first_branch:
                            main_branch_id = first_branch.id
                            main_branch_name = first_branch.branch_code

                    # Lấy tên chức vụ tiếng Việt
                    snapshot_role = emp.department.name if emp.department else "Nhân viên"

                    record = AttendanceRecord(
                        user_id=emp.id,
                        checker_id=None,
                        branch_id=main_branch_id,
                        
                        employee_code_snapshot=emp.employee_code,
                        employee_name_snapshot=emp.name,
                        role_snapshot=snapshot_role,
                        main_branch_snapshot=main_branch_name,
                        
                        # [ĐÃ SỬA] Ghi nhận vào 06:59 ngày hôm sau
                        attendance_datetime=record_datetime,
                        
                        work_units=0.0,
                        is_overtime=False,
                        notes=f"Hệ thống: Nghỉ không phép ngày {workday_str}"
                    )
                    new_absence_records.append(record)
    
            if new_absence_records:
                db.add_all(new_absence_records)
                db.commit()
                logger.info(f"[UPDATE] Ngày {workday_str}: Đã ghi nhận {len(new_absence_records)} nhân viên vắng (vào lúc {record_datetime.strftime('%d/%m %H:%M')}).")
            else:
                logger.info(f"[UPDATE] Ngày {workday_str}: Không ai vắng mặt.")
    
        except Exception as e:
            logger.error(f"[ERROR] Update vắng mặt thất bại: {e}", exc_info=True)
            db.rollback()

if __name__ == "__main__":
    run_daily_absence_check()