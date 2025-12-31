from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
import os
from collections import defaultdict, OrderedDict
from typing import Optional
import calendar
import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from datetime import datetime, date, timedelta

from ..db.session import get_db
from ..db.models import User, AttendanceRecord, ServiceRecord, Branch, Department
from ..core.utils import VN_TZ
from ..core.config import ROLE_MAP
from sqlalchemy import cast, Date
from sqlalchemy.orm import joinedload
from sqlalchemy import func, distinct

from fastapi.templating import Jinja2Templates

router = APIRouter()

# Xác định đường dẫn tuyệt đối đến thư mục gốc của project 'app'
APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Tạo đường dẫn tuyệt đối đến thư mục templates
templates = Jinja2Templates(directory=os.path.join(APP_ROOT, "templates"))


@router.get("/calendar-view", response_class=HTMLResponse)
def view_attendance_calendar(
    request: Request,
    db: Session = Depends(get_db),
    chi_nhanh: Optional[str] = None, # Đây là branch_code
    month: Optional[int] = None,
    year: Optional[int] = None,
):
    user_data = request.session.get("user")
    if not user_data or user_data.get("role") not in ["admin", "boss", "quanly", "letan", "ktv"]:
        return RedirectResponse("/choose-function", status_code=303)

    # Lấy danh sách chi nhánh và phòng ban từ DB để hiển thị trong bộ lọc
    # Sửa lỗi: Loại bỏ Admin và Boss khỏi danh sách chi nhánh
    all_branches_obj = db.query(Branch).filter(Branch.branch_code.notin_(['Admin', 'Boss'])).all()

    # Logic sắp xếp chi nhánh tùy chỉnh
    b_branches = []
    other_branches = []
    for b in all_branches_obj:
        if b.branch_code.startswith('B') and b.branch_code[1:].isdigit():
            b_branches.append(b.branch_code)
        else:
            other_branches.append(b.branch_code)

    b_branches.sort(key=lambda x: int(x[1:]))
    other_branches.sort()
    display_branches = b_branches + other_branches

    # Xử lý giá trị chi_nhanh mặc định. Nếu chi_nhanh là chuỗi rỗng từ form, nó sẽ trở thành None.
    # Nếu không có chi nhánh nào được chọn (kể cả lần đầu vào trang), thì xử lý mặc định.
    if chi_nhanh is None:
        user_role = user_data.get("role")
        if user_role in ["ktv", "quanly"]:
            chi_nhanh = user_data.get("branch", "B1")
        elif user_role == "letan":
            # [CŨ] active_branch = get_active_branch(request, db, user_data)
            # [CŨ] chi_nhanh = active_branch or user_data.get("branch", "B1")
            
            # [MỚI] Lấy thẳng từ Session (nhờ Middleware ở main.py)
            chi_nhanh = request.session.get("active_branch") or user_data.get("branch", "B1")
            
        elif user_role in ["admin", "boss"]:
            # Để trống để mặc định là "Tất cả chi nhánh" (hoặc B1 tùy bạn)
            chi_nhanh = "B1"

    now = datetime.now(VN_TZ)
    current_month = month if month else now.month
    current_year = year if year else now.year

    start_date_of_month = date(current_year, current_month, 1)
    end_date_of_month = date(current_year, current_month, calendar.monthrange(current_year, current_month)[1])
    
    _, num_days = calendar.monthrange(current_year, current_month)
    
    employee_data = defaultdict(lambda: {
        "name": "", "role": "", "role_key": "", "main_branch": "",
        "worked_away_from_main_branch": False,
        "daily_work": defaultdict(lambda: {"work_units": 0, "is_overtime": False, "work_branch": "", "services": []})
    })

    if chi_nhanh:
        # =================================================================================
        # LOGIC CẢI TIẾN: HYBRID USER FETCHING (Lấy nhân viên từ Lịch sử + Hiện tại)
        # =================================================================================
        
        target_emp_codes = set()
        
        # Các bộ lọc định nghĩa sẵn
        role_map_filter = {"KTV": "ktv", "Quản lý": "quanly"}
        code_prefix_filter = {"LTTC": "LTTC", "BPTC": "BPTC"}

        # --- GIAI ĐOẠN 1: TÌM NHÂN VIÊN DỰA TRÊN LỊCH SỬ CHẤM CÔNG (SNAPSHOT) ---
        # Mục đích: Đảm bảo nhân viên cũ/đã chuyển đi vẫn hiện đúng trong quá khứ
        
        att_history_q = db.query(AttendanceRecord).options(joinedload(AttendanceRecord.branch))
        svc_history_q = db.query(ServiceRecord).options(joinedload(ServiceRecord.branch))
        
        # Áp dụng bộ lọc cho Query Lịch sử
        if chi_nhanh in role_map_filter:
            # Lọc theo role snapshot trong quá khứ
            # Lưu ý: Cần đảm bảo logic map role khớp với cách lưu snapshot
            # Ở đây ta dùng ilike để tìm tương đối vì snapshot lưu text tiếng Việt
            role_keyword = "kỹ thuật" if chi_nhanh == "KTV" else "quản lý"
            att_history_q = att_history_q.filter(AttendanceRecord.role_snapshot.ilike(f"%{role_keyword}%"))
            svc_history_q = svc_history_q.filter(ServiceRecord.role_snapshot.ilike(f"%{role_keyword}%"))
            
        elif chi_nhanh in code_prefix_filter:
            prefix = code_prefix_filter[chi_nhanh]
            att_history_q = att_history_q.filter(AttendanceRecord.employee_code_snapshot.startswith(prefix))
            svc_history_q = svc_history_q.filter(ServiceRecord.employee_code_snapshot.startswith(prefix))
            
        elif chi_nhanh == 'DI DONG':
            # Với DI DONG, ta cần logic đặc thù: Lấy tất cả, sau này lọc sau
            pass 
            
        else:
            # Lọc theo Chi nhánh (B1, B2...) dựa trên branch_id của bản ghi chấm công
            branch_to_filter_obj = next((b for b in all_branches_obj if b.branch_code == chi_nhanh), None)
            if branch_to_filter_obj:
                att_history_q = att_history_q.filter(AttendanceRecord.branch_id == branch_to_filter_obj.id)
                svc_history_q = svc_history_q.filter(ServiceRecord.branch_id == branch_to_filter_obj.id)

        # Lọc theo thời gian (Tháng đang xem)
        att_records = att_history_q.filter(cast(AttendanceRecord.attendance_datetime, Date).between(start_date_of_month, end_date_of_month)).all()
        svc_records = svc_history_q.filter(cast(ServiceRecord.service_datetime, Date).between(start_date_of_month, end_date_of_month)).all()

        all_records = att_records + svc_records

        # --- GIAI ĐOẠN 2: XÂY DỰNG DANH SÁCH NHÂN VIÊN TỪ LỊCH SỬ ---
        for rec in all_records:
            emp_code = rec.employee_code_snapshot
            if not emp_code: continue
            
            target_emp_codes.add(emp_code) # Lưu lại để lát nữa query User hiện tại loại trừ ra

            # Chỉ khởi tạo dữ liệu nếu chưa có
            if emp_code not in employee_data:
                # ƯU TIÊN SỐ 1: Sử dụng thông tin Snapshot (Phản ánh đúng chức vụ/nơi làm lúc đó)
                employee_data[emp_code]["name"] = rec.employee_name_snapshot
                employee_data[emp_code]["main_branch"] = rec.main_branch_snapshot
                
                # Logic chuẩn hóa Role Key (Tái sử dụng code của bạn)
                raw_role = str(rec.role_snapshot).lower() if rec.role_snapshot else ""
                normalized_key = "khac"
                if "lễ tân" in raw_role or "letan" in raw_role or "lttc" in raw_role: normalized_key = "letan"
                elif "buồng" in raw_role or "buongphong" in raw_role or "bptc" in raw_role: normalized_key = "buongphong"
                elif "bảo vệ" in raw_role or "baove" in raw_role or "an ninh" in raw_role: normalized_key = "baove"
                elif "kỹ thuật" in raw_role or "ktv" in raw_role: normalized_key = "ktv"
                elif "quản lý" in raw_role or "quanly" in raw_role: normalized_key = "quanly"
                elif "admin" in raw_role: normalized_key = "admin"
                elif "giám đốc" in raw_role or "boss" in raw_role: normalized_key = "boss"
                
                employee_data[emp_code]["role_key"] = normalized_key
                employee_data[emp_code]["role"] = ROLE_MAP.get(rec.role_snapshot, rec.role_snapshot)

        # --- GIAI ĐOẠN 3: BỔ SUNG NHÂN VIÊN HIỆN TẠI (CHƯA CÓ CÔNG) ---
        # Mục đích: Hiển thị nhân viên mới hoặc nhân viên nghỉ làm cả tháng nhưng vẫn thuộc biên chế
        if chi_nhanh != 'DI DONG': # DI DONG thường dựa vào phát sinh thực tế
            current_user_query = db.query(User).options(joinedload(User.department), joinedload(User.main_branch))
            
            if chi_nhanh in role_map_filter:
                current_user_query = current_user_query.join(User.department).filter(Department.role_code == role_map_filter[chi_nhanh])
            elif chi_nhanh in code_prefix_filter:
                current_user_query = current_user_query.filter(User.employee_code.startswith(code_prefix_filter[chi_nhanh]))
            else:
                 # Lọc theo chi nhánh chính hiện tại
                current_user_query = current_user_query.join(User.main_branch).filter(Branch.branch_code == chi_nhanh)
            
            # Loại bỏ những người đã được thêm từ lịch sử (target_emp_codes) để tránh ghi đè dữ liệu snapshot
            if target_emp_codes:
                current_user_query = current_user_query.filter(User.employee_code.notin_(target_emp_codes))
            
            current_employees = current_user_query.all()
            
            for emp in current_employees:
                emp_code = emp.employee_code
                if emp_code not in employee_data:
                    employee_data[emp_code]["name"] = emp.name
                    employee_data[emp_code]["main_branch"] = emp.main_branch.branch_code if emp.main_branch else ''
                    role_code = emp.department.role_code if emp.department else 'khac'
                    employee_data[emp_code]["role_key"] = role_code
                    employee_data[emp_code]["role"] = ROLE_MAP.get(role_code, role_code)

        # --- GIAI ĐOẠN 4: MAPPING DỮ LIỆU CÔNG VÀO VIEW (GIỮ NGUYÊN LOGIC CŨ) ---
        for rec in all_records:
            is_att = isinstance(rec, AttendanceRecord)
            dt = rec.attendance_datetime if is_att else rec.service_datetime
            
            dt_local = dt.astimezone(VN_TZ)
            work_date = dt_local.date() - timedelta(days=1) if dt_local.hour < 7 else dt_local.date()

            if work_date.month != current_month or work_date.year != current_year:
                continue

            day_of_month = work_date.day
            emp_code = rec.employee_code_snapshot
            
            # (Phần xử lý nếu emp_code chưa có trong employee_data đã được bao phủ ở Giai đoạn 2, 
            # nhưng giữ lại check này cho an toàn trường hợp DI DONG hoặc ngoại lệ)
            if emp_code not in employee_data:
                 # Fallback logic cũ của bạn...
                 pass 

            # Kiểm tra làm khác chi nhánh (Logic này giờ so sánh Snapshot với nơi làm thực tế -> Chính xác hơn)
            main_branch_of_employee = employee_data[emp_code].get("main_branch")
            if rec.branch and main_branch_of_employee and rec.branch.branch_code != main_branch_of_employee:
                employee_data[emp_code]["worked_away_from_main_branch"] = True

            daily_work_entry = employee_data[emp_code]["daily_work"][day_of_month]
            
            if is_att:
                daily_work_entry["work_units"] += rec.work_units or 0
                if rec.branch:
                    current_stored = daily_work_entry["work_branch"]
                    new_branch = rec.branch.branch_code
                    if not current_stored:
                        daily_work_entry["work_branch"] = new_branch
                    elif new_branch not in current_stored: 
                        daily_work_entry["work_branch"] = f"{current_stored}, {new_branch}"
                
                if rec.is_overtime:
                    daily_work_entry["is_overtime"] = True
            else: 
                service_summary = daily_work_entry.setdefault("service_summary", defaultdict(int))
                service_summary[rec.service_type] += rec.quantity or 0

        # Chuyển đổi service_summary thành list string để dễ render
        for emp_code in employee_data:
            for day_data in employee_data[emp_code]["daily_work"].values():
                if "service_summary" in day_data:
                    summary = day_data.pop("service_summary")
                    day_data["services"] = [f"{k}: {v}" for k, v in summary.items()]

        # === BƯỚC 4: TỐI ƯU HÓA - LẤY DỮ LIỆU THỐNG KÊ MỘT LẦN ===
        # 1. Xác định danh sách nhân viên chính của view này để lấy dữ liệu
        main_employee_codes = [
            emp_code for emp_code, emp_details in employee_data.items()
            if (
                emp_details.get("main_branch") == chi_nhanh
                or (chi_nhanh == "KTV" and emp_details.get("role_key") == "ktv")
                or (chi_nhanh == "Quản lý" and emp_details.get("role_key") == "quanly")
                or (chi_nhanh == "LTTC" and emp_details.get("role_key") == "lttc")
                or (chi_nhanh == "BPTC" and emp_details.get("role_key") == "bptc")
            )
        ]

        all_atts_for_stats = defaultdict(list)
        all_services_for_stats = defaultdict(list)

        if main_employee_codes:
            # 2. Lấy tất cả bản ghi điểm danh và dịch vụ cho các nhân viên đó trong khoảng thời gian liên quan
            start_query_date = date(current_year, current_month, 1)
            end_query_date = date(current_year, current_month, num_days) + timedelta(days=1)

            all_atts_raw_bulk = db.query(AttendanceRecord).options(joinedload(AttendanceRecord.branch)).filter(
                AttendanceRecord.employee_code_snapshot.in_(main_employee_codes),
                cast(AttendanceRecord.attendance_datetime, Date).between(start_query_date, end_query_date)
            ).all()

            all_services_bulk = db.query(ServiceRecord).options(joinedload(ServiceRecord.branch)).filter(
                ServiceRecord.employee_code_snapshot.in_(main_employee_codes),
                cast(ServiceRecord.service_datetime, Date).between(start_date_of_month, end_date_of_month)
            ).all()

            # 3. Nhóm các bản ghi theo mã nhân viên để tra cứu nhanh
            for att in all_atts_raw_bulk:
                all_atts_for_stats[att.employee_code_snapshot].append(att)
            for svc in all_services_bulk:
                all_services_for_stats[svc.employee_code_snapshot].append(svc)

        # === BƯỚC 4: TÍNH TOÁN THỐNG KÊ CHO DASHBOARD (ĐÃ BỊ THIẾU) ===
        for emp_code, emp_details in employee_data.items():
            # Chỉ tính cho nhân viên có chi nhánh chính là chi nhánh đang xem
            is_main_employee_of_view = (
                emp_details.get("main_branch") == chi_nhanh
                or (chi_nhanh == "KTV" and emp_details.get("role_key") == "ktv")
                or (chi_nhanh == "Quản lý" and emp_details.get("role_key") == "quanly")
                or (chi_nhanh == "LTTC" and emp_details.get("role_key") == "lttc")
                or (chi_nhanh == "BPTC" and emp_details.get("role_key") == "bptc")
            )

            if is_main_employee_of_view:
                # --- TÍNH TOÁN DASHBOARD ---
                # 1. Lấy dữ liệu đã được truy vấn sẵn, không query lại DB
                all_atts_raw = all_atts_for_stats.get(emp_code, [])

                # Helper để xác định ngày làm việc (ca đêm < 7h sáng tính cho ngày hôm trước)
                def get_work_day(att_datetime):
                    # Chuyển đổi thời gian DB (UTC) về giờ Việt Nam (GMT+7)
                    dt_local = att_datetime.astimezone(VN_TZ)
                    # Áp dụng logic trên giờ Việt Nam
                    return dt_local.date() - timedelta(days=1) if dt_local.hour < 7 else dt_local.date()
                # Gắn "work_day" vào mỗi bản ghi và lọc lại theo tháng đang xem
                all_atts = [
                    {
                        "work_day": get_work_day(att.attendance_datetime),
                        **att.__dict__
                    }
                    for att in all_atts_raw
                ]
                all_atts = [
                    att for att in all_atts 
                    if att["work_day"].month == current_month and att["work_day"].year == current_year
                ]

                # 2. Xử lý dữ liệu điểm danh dựa trên "work_day"
                tong_so_cong = 0.0
                work_days_set = set()
                overtime_work_days_set = set()
                daily_work_units = defaultdict(float)

                for att in all_atts:
                    work_day = att['work_day']
                    so_cong = att.get('work_units') or 0
                    tong_so_cong += so_cong
                    if so_cong > 0:
                        work_days_set.add(work_day)
                    daily_work_units[work_day] += so_cong
                    if att.get('is_overtime'):
                        overtime_work_days_set.add(work_day)

                # Xác định ngày tăng ca dựa trên tổng công > 1
                for day, total_units in daily_work_units.items():
                    if total_units > 1:
                        overtime_work_days_set.add(day)

                # Lấy chi tiết tăng ca
                overtime_details = []
                main_branch = emp_details.get("main_branch")

                # Xác định những ngày làm việc có chấm công ở chi nhánh khác (với số công > 0)
                other_branch_work_days = {
                    # Sửa lỗi: Tính work_day trực tiếp từ att.attendance_datetime
                    get_work_day(att.attendance_datetime)
                    for att in all_atts_raw
                    if main_branch and att.branch and att.branch.branch_code != main_branch and (att.work_units or 0) > 0
                }

                # Set để đảm bảo mỗi ngày chỉ xử lý 1 lần cho trường hợp >1 công
                processed_main_branch_overtime_days = set()

                # Lặp qua tất cả các bản ghi để xây dựng chi tiết
                for att in all_atts:
                    work_day = att.get('work_day')

                    # Bỏ qua nếu không phải là ngày tăng ca
                    if work_day not in overtime_work_days_set:
                        continue

                    # Ưu tiên 1: Tăng ca do đi chi nhánh khác
                    # Sửa lỗi: att.get('branch') không tồn tại, phải dùng att['branch_id']
                    if work_day in other_branch_work_days:
                        # Chỉ thêm các bản ghi ở chi nhánh khác (có công)
                        if main_branch and att.get('_sa_instance_state').object.branch.branch_code != main_branch and (att.get('work_units') or 0) > 0:
                            # Sửa lỗi: Chuyển đổi sang múi giờ Việt Nam trước khi định dạng
                            local_time = att['attendance_datetime'].astimezone(VN_TZ)
                            overtime_details.append({ 
                                "date": local_time.strftime('%d/%m/%Y'), "time": local_time.strftime('%H:%M'), 
                                "branch": att.get('_sa_instance_state').object.branch.branch_code, "work_units": att.get('work_units') })
                    # Trường hợp 2: Tăng ca do làm >1 công (và chỉ làm tại chi nhánh chính)
                    elif daily_work_units.get(work_day, 0) > 1:
                        if work_day not in processed_main_branch_overtime_days:
                            # Chỉ hiển thị 1 dòng tóm tắt cho ngày này
                            overtime_details.append({ "date": work_day.strftime('%d/%m/%Y'), "time": "Nhiều ca", "branch": main_branch, "work_units": f"{daily_work_units.get(work_day, 0):.1f}" })
                            processed_main_branch_overtime_days.add(work_day)

                # 3. Lấy dữ liệu dịch vụ đã được truy vấn sẵn
                all_services = all_services_for_stats.get(emp_code, [])

                # 4. Tổng hợp kết quả
                so_ngay_lam = len(work_days_set)
                so_ngay_tang_ca = len(overtime_work_days_set)

                # --- LOGIC MỚI CHO SỐ NGÀY NGHỈ ---
                is_current_month_view = (current_year == now.year and current_month == now.month)
                
                if is_current_month_view:
                    # Đối với tháng hiện tại, số ngày nghỉ được tính từ đầu tháng đến ngày hôm nay.
                    days_passed = now.day
                    # Lọc ra những ngày đã làm việc tính đến hôm nay.
                    worked_days_so_far = {d for d in work_days_set if d <= now.date()}
                    so_ngay_nghi = days_passed - len(worked_days_so_far)
                else:
                    # Đối với các tháng trong quá khứ, tính như cũ.
                    so_ngay_nghi = num_days - so_ngay_lam
                so_ngay_nghi = max(0, so_ngay_nghi)
                laundry_details = []
                ironing_details = []
                tong_dich_vu_giat = 0
                tong_dich_vu_ui = 0

                for svc in all_services:
                    try:
                        quantity = int(svc.quantity)
                    except (ValueError, TypeError):
                        quantity = 0
                    
                    # Sửa lỗi: Chuyển đổi sang múi giờ Việt Nam trước khi định dạng
                    local_time = svc.service_datetime.astimezone(VN_TZ)
                    detail = {
                        "date": local_time.strftime('%d/%m/%Y'), 
                        "time": local_time.strftime('%H:%M'),
                        "branch": svc.branch.branch_code if svc.branch else '', "room": svc.room_number, "quantity": svc.quantity
                    }

                    if svc.service_type == 'Giặt':
                        tong_dich_vu_giat += quantity
                        laundry_details.append(detail)
                    elif svc.service_type == 'Ủi':
                        tong_dich_vu_ui += quantity
                        ironing_details.append(detail)

                emp_details["dashboard_stats"] = {
                    "so_ngay_lam": so_ngay_lam,
                    "so_ngay_nghi": so_ngay_nghi,
                    "so_ngay_tang_ca": so_ngay_tang_ca,
                    "tong_so_cong": tong_so_cong,
                    "tong_dich_vu_giat": tong_dich_vu_giat,
                    "tong_dich_vu_ui": tong_dich_vu_ui,
                    "overtime_details": sorted(overtime_details, key=lambda x: datetime.strptime(x['date'], '%d/%m/%Y')),
                    "laundry_details": sorted(laundry_details, key=lambda x: datetime.strptime(x['date'], '%d/%m/%Y')),
                    "ironing_details": sorted(ironing_details, key=lambda x: datetime.strptime(x['date'], '%d/%m/%Y')),
                }

    # === SẮP XẾP DANH SÁCH NHÂN VIÊN ===
    # Priority khớp với ID trong database: letan(1) -> buongphong(2) -> baove(3)...
    role_priority = {
        "letan": 1, 
        "buongphong": 2, 
        "baove": 3, 
        "ktv": 4, 
        "quanly": 5,
        "admin": 6,
        "boss": 7
    }
    
    def get_sort_key(item):
        emp_code, emp_info = item
        
        # Tiêu chí 1: Chức vụ (Role)
        # Sử dụng role_key đã chuẩn hóa để gom nhóm
        role_score = role_priority.get(emp_info.get("role_key", "khac"), 99)
        
        # Tiêu chí 2: Phân loại Chủ nhà (Local) vs Khách (Visitor)
        # Mặc định là 0 (ưu tiên cao nhất)
        visitor_score = 0
        
        # Logic: Nếu đang xem lịch của một Chi nhánh cụ thể (VD: B1, B2...)
        # Nhân viên có 'main_branch' khác chi nhánh đang xem sẽ bị coi là 'khách' (score = 1) -> Xếp dưới
        current_view_branch = chi_nhanh # Biến chi_nhanh từ tham số hàm
        emp_main_branch = emp_info.get("main_branch")
        
        # Chỉ so sánh nếu cả 2 giá trị đều tồn tại
        if current_view_branch and emp_main_branch:
             # Nếu chi nhánh chính KHÁC chi nhánh hiện tại -> Đẩy xuống dưới
             if emp_main_branch != current_view_branch:
                 visitor_score = 1
        
        # Tiêu chí 3: Tên nhân viên (A-Z)
        name_score = emp_info.get("name", "")
        
        return (role_score, visitor_score, name_score)

    # Thực hiện sắp xếp
    sorted_employee_list = sorted(
        employee_data.items(),
        key=get_sort_key
    )
    
    sorted_employee_data = OrderedDict(sorted_employee_list)

    return templates.TemplateResponse("calendar_view.html", {
        "request": request,
        "user": user_data,
        "branches": display_branches,
        "selected_branch": chi_nhanh,
        "selected_month": current_month,
        "selected_year": current_year,
        "num_days": num_days,
        "employee_data": sorted_employee_data,
        "employee_data_for_js": sorted_employee_data, # Sửa lỗi: Cung cấp dữ liệu cho dashboard
        "current_day": now.day if now.month == current_month and now.year == current_year else None,
    })
