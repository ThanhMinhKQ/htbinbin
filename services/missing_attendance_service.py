# missing_attendance_service.py - chuẩn cập nhật điểm danh
import os
import json
from datetime import datetime
from collections import defaultdict
from pytz import timezone
from employees import employees

SERVICE_ACCOUNT_FILE = "config/credentials.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1R-5t90lNY22MUfkdv3YUHtKOzW7fjIIgjSYtCisDLqA"

# Header mặc định (cho tất cả sheet điểm danh)
BASE_HEADERS = [
    "Ngày", "Giờ", "Người điểm danh", "Mã NV", "Tên NV", "Chi nhánh chính",
    "Chi nhánh làm", "Tăng ca", "Số công", "Ghi chú"
]

# Header cho DV (không có Số công, thêm 3 cột dịch vụ)
DV_HEADERS = [
    "Ngày", "Giờ", "Người điểm danh", "Mã NV", "Tên NV", "Chi nhánh chính",
    "Chi nhánh làm", "Tăng ca",
    "Dịch vụ", "Số phòng", "Số lượng đồ", "Ghi chú"
]

def get_sheet_name(code: str) -> str:
    """
    Xác định sheet dựa trên mã nhân viên
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

    return "Default"

def _now_vn_str():
    tz = timezone("Asia/Ho_Chi_Minh")
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

def build_absence_row(sheet_name: str, emp: dict, base_time: str) -> dict:
    """
    Tạo dictionary cho bản vắng mặt, đúng header
    """
    if " " in base_time:
        ngay, gio = base_time.split(" ", 1)
    else:
        ngay, gio = base_time, ""

    row = {
        "Ngày": f"'{ngay}",
        "Giờ": f"'{gio}",
        "Mã NV": emp.get("code", ""),
        "Tên NV": emp.get("name", ""),
        "Chi nhánh chính": emp.get("branch", ""),
        "Ghi chú": "Hệ thống tự động ghi nhận: Không điểm danh",
        "Người điểm danh": "Hệ thống",
        "Chi nhánh làm": emp.get("branch", ""),
        "Tăng ca": "",
    }

    if sheet_name.upper() == "DV":
        row.update({
            "Dịch vụ": "Nghỉ",
            "Số phòng": "0",
            "Số lượng đồ": "0",
        })
    else:
        row["Số công"] = "0"
    return row

def update_missing_attendance(employees):
    """
    Append các bản ghi vắng mặt cho tất cả sheet ngoại trừ DV
    """
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=SCOPES
        )
    else:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )

    service = build("sheets", "v4", credentials=creds).spreadsheets()
    values_service = service.values()
    now_vn_str = _now_vn_str()
    processing_date = now_vn_str.split(" ")[0]

    grouped_employees = defaultdict(list)
    for emp in employees:
        sheet_name = get_sheet_name(emp.get("code", ""))
        if sheet_name.upper() != "DV":   # DV không ghi điểm danh
            grouped_employees[sheet_name].append(emp)

    for sheet_name, employees_in_sheet in grouped_employees.items():
        expected_headers = BASE_HEADERS
        try:
            result = values_service.get(
                spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!A:Z"
            ).execute()
            existing_data = result.get("values", [])
        except Exception as e:
            print(f"[missing_attendance] Không đọc được sheet '{sheet_name}': {e}")
            continue

        # đảm bảo header
        if not existing_data or existing_data[0] != expected_headers:
            try:
                values_service.update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{sheet_name}!A1",
                    valueInputOption="USER_ENTERED",
                    body={"values": [expected_headers]},
                ).execute()
                sheet_rows = []
            except Exception as e:
                print(f"[missing_attendance] Cập nhật header thất bại '{sheet_name}': {e}")
                continue
        else:
            sheet_rows = existing_data[1:]

        try:
            idx_code = expected_headers.index("Mã NV")
            idx_date = expected_headers.index("Ngày")
        except ValueError:
            print(f"[missing_attendance] Header quan trọng thiếu ở sheet '{sheet_name}'. Bỏ qua.")
            continue

        checked_in_codes = set()
        for row in sheet_rows:
            if len(row) <= max(idx_date, idx_code):
                continue
            row_date = str(row[idx_date]).strip().replace("'", "")
            if row_date == processing_date:
                code = str(row[idx_code]).strip()
                if code:
                    checked_in_codes.add(code)

        new_rows_to_append = []
        for emp in employees_in_sheet:
            if emp.get("code") not in checked_in_codes:
                absence_data = build_absence_row(sheet_name, emp, now_vn_str)
                row_values = [absence_data.get(h, "") for h in expected_headers]
                new_rows_to_append.append(row_values)

        if not new_rows_to_append:
            continue

        try:
            values_service.append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{sheet_name}!A:A",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": new_rows_to_append},
            ).execute()
            print(f"[missing_attendance] Đã thêm {len(new_rows_to_append)} bản ghi vắng mặt vào sheet '{sheet_name}'.")
        except Exception as e:
            print(f"[missing_attendance] Append thất bại sheet '{sheet_name}': {e}")
            continue

if __name__ == "__main__":
    print("[TEST] Bắt đầu cập nhật nhân viên vắng mặt...")
    update_missing_attendance(employees)
    print("[TEST] Hoàn tất!")
