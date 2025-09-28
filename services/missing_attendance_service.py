# missing_attendance_service.py - chuẩn cập nhật điểm danh
import sys
from datetime import datetime, time, timedelta, date
from pathlib import Path
from typing import Optional
from pytz import timezone
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

# Thêm thư mục gốc của dự án vào sys.path để import các module khác
sys.path.append(str(Path(__file__).resolve().parents[1]))

from database import SessionLocal
from models import AttendanceRecord
from employees import employees

def get_sheet_name(code: str) -> str:
    """
    Xác định sheet (bộ phận) dựa trên mã nhân viên.
    Hàm này vẫn hữu ích để loại trừ một số bộ phận nhất định.
    """
    code_upper = (code or "").upper()

    # --- Bộ phận buồng phòng ---
    if "BP" in code_upper:
        return "BP"
    # --- Lễ tân ---
    if "LTTC" in code_upper:
        return "TC"
    if "LT" in code_upper:
        return "LT"
    # --- Bảo vệ ---
    if "BV" in code_upper:
        return "BV"
    # --- Quản lý ---
    if "QL" in code_upper:
        return "QL"
    # --- Kỹ thuật viên ---
    if "KTV" in code_upper:
        return "KTV"
    
    # --- Dịch vụ ---
    # Mặc dù không ghi điểm danh vắng mặt cho DV, vẫn định danh để loại trừ
    if "DV" in code_upper:
        return "DV"
        
    return "Default"

def update_missing_attendance_to_db(employees_list: list, target_date: Optional[date] = None):
    """
    Kiểm tra và cập nhật các bản ghi vắng mặt cho một ngày cụ thể.
    Nếu target_date không được cung cấp, sẽ mặc định là ngày hôm trước.
    """
    vn_tz = timezone("Asia/Ho_Chi_Minh")
    
    # Xác định ngày làm việc cần kiểm tra
    if target_date is None:
        workday_to_check = datetime.now(vn_tz).date() - timedelta(days=1)
    else:
        workday_to_check = target_date
    
    workday_str = workday_to_check.strftime('%d/%m/%Y')
    
    with SessionLocal() as db:
        try:
            # 1. Xóa các bản ghi vắng mặt "Hệ thống" cũ cho ngày này để tránh trùng lặp
            # Điều này rất quan trọng khi chạy lại tác vụ thủ công.
            db.query(AttendanceRecord).filter(
                AttendanceRecord.ngay_diem_danh == workday_to_check,
                AttendanceRecord.nguoi_diem_danh == "Hệ thống"
            ).delete(synchronize_session=False)
            db.commit()
            print(f"[DB_CLEANUP] Đã xóa các bản ghi vắng mặt cũ cho ngày {workday_str}.")
    
            # 2. Lấy danh sách các mã nhân viên đã điểm danh trong "ngày làm việc"
            checked_in_records = db.query(AttendanceRecord.ma_nv).filter(
                or_(
                    # Ca ngày: từ 07:00 đến 23:59 của workday_to_check
                    and_(
                        AttendanceRecord.ngay_diem_danh == workday_to_check,
                        AttendanceRecord.gio_diem_danh >= time(7, 0, 0)
                    ),
                    # Ca đêm: từ 00:00 đến 06:59 của ngày hôm sau
                    and_(
                        AttendanceRecord.ngay_diem_danh == workday_to_check + timedelta(days=1),
                        AttendanceRecord.gio_diem_danh < time(7, 0, 0)
                    )
                )
            ).all()
            checked_in_codes = {record.ma_nv for record in checked_in_records}
            
            print(f"[DB_CHECK] Ngày làm việc {workday_str}: Tìm thấy {len(checked_in_codes)} nhân viên đã điểm danh.")
    
            # 3. Lọc ra những nhân viên chưa điểm danh
            new_absence_records = []
            for emp in employees_list:
                emp_code = emp.get("code")
                if not emp_code:
                    continue
    
                # Bỏ qua các vai trò không cần điểm danh (Boss, Admin) và bộ phận đặc thù (DV)
                emp_role = emp.get("role", "").lower()
                department = get_sheet_name(emp_code)
                if department.upper() == "DV" or emp_role in ["boss", "admin"]:
                    continue
    
                if emp_code not in checked_in_codes:
                    # 4. Tạo bản ghi vắng mặt cho nhân viên
                    absence_record = AttendanceRecord(
                        ngay_diem_danh=workday_to_check, # Ghi nhận vắng mặt cho ngày làm việc được chỉ định
                        gio_diem_danh=time(23, 59, 0),  # Ghi nhận vào cuối ngày hôm trước
                        nguoi_diem_danh="Hệ thống",
                        ma_nv=emp.get("code", ""),
                        ten_nv=emp.get("name", ""),
                        chi_nhanh_chinh=emp.get("branch", ""),
                        chi_nhanh_lam=None,  # Nhân viên vắng mặt nên không có chi nhánh làm việc
                        la_tang_ca=False,
                        so_cong_nv=0.0,
                        ghi_chu=f"Hệ thống: Nghỉ cả ngày {workday_str}"
                    )
                    new_absence_records.append(absence_record)
    
            if not new_absence_records:
                print(f"[DB_UPDATE] Ngày {workday_str}: Không có nhân viên nào vắng mặt cần cập nhật.")
                return
    
            # 5. Thêm tất cả các bản ghi vắng mặt vào database
            db.add_all(new_absence_records)
            db.commit()
            print(f"[DB_UPDATE] Ngày {workday_str}: Đã thêm {len(new_absence_records)} bản ghi vắng mặt vào database.")
    
        except Exception as e:
            print(f"[DB_ERROR] Lỗi khi cập nhật điểm danh vắng mặt: {e}")
            db.rollback()
            raise # Ném lại lỗi để tác vụ nền (scheduler) có thể ghi nhận

if __name__ == "__main__":
    print("[Missing] Bắt đầu cập nhật nhân viên vắng mặt cho ngày hôm trước...")
    update_missing_attendance_to_db(employees)
    print("[Missing] Hoàn tất!")
