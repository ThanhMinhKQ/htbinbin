# missing_attendance_service.py (lazy google api usage; efficient append)
import os
from datetime import datetime
from collections import defaultdict
from pytz import timezone

SERVICE_ACCOUNT_FILE = "config/credentials.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1R-5t90lNY22MUfkdv3YUHtKOzW7fjIIgjSYtCisDLqA"

HEADERS = {
    "LT": ["Ngày", "Giờ", "Mã NV", "Tên NV", "Chi nhánh chính", "Trạng thái", "Chi nhánh làm", "Tăng ca", "Số công", "Ghi chú"],
    "BP": ["Ngày", "Giờ", "Mã NV", "Tên NV", "Chi nhánh chính", "Trạng thái", "Chức năng", "Chi nhánh làm", "Tăng ca", "Số công", "Số phòng", "Số lượng đồ", "Ghi chú"],
    "BV": ["Ngày", "Giờ", "Mã NV", "Tên NV", "Chi nhánh chính", "Trạng thái", "Chi nhánh làm", "Tăng ca", "Số công", "Ghi chú"],
    "QL": ["Ngày", "Giờ", "Mã NV", "Tên NV", "Trạng thái", "Số công", "Ghi chú"],
    "TC": ["Ngày", "Giờ", "Mã NV", "Tên NV", "Chi nhánh chính", "Trạng thái", "Chức năng", "Chi nhánh làm", "Tăng ca", "Số công", "Số phòng", "Số lượng đồ", "Ghi chú"],
    "KTV": ["Ngày", "Giờ", "Mã NV", "Tên NV", "Trạng thái", "Số công", "Ghi chú"],
}

def get_sheet_name(code):
    if "BPTC" in code or "LTTC" in code:
        return "TC"
    if "BP" in code:
        return "BP"
    if "LT" in code:
        return "LT"
    if "BV" in code:
        return "BV"
    if "QL" in code:
        return "QL"
    if code == "KTV":
        return "KTV"
    return "Khac"

def format_vn_datetime(dt=None):
    tz = timezone("Asia/Ho_Chi_Minh")
    if dt is None:
        dt = datetime.now(tz)
    else:
        dt = dt.astimezone(tz)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def build_absence_row(sheet_name, emp, base_time):
    if " " in base_time:
        ngay, gio = base_time.split(" ", 1)
    else:
        ngay, gio = base_time, ""
    ngay = str(ngay)
    gio = str(gio)
    row = {
        "Ngày": ngay,
        "Giờ": gio,
        "Mã NV": emp["code"],
        "Tên NV": emp["name"],
        "Chi nhánh chính": emp["branch"],
        "Trạng thái": "❌ Nghỉ",
        "Ghi chú": "Không điểm danh",
    }
    if sheet_name in ["LT", "BV"]:
        row["Chi nhánh làm"] = "Không xác định"
        row["Tăng ca"] = "Null"
        row["Số công"] = "0"
    if sheet_name == "BP":
        row["Chức năng"] = "Chưa chọn"
        row["Chi nhánh làm"] = "Không xác định"
        row["Tăng ca"] = "Null"
        row["Số công"] = "0"
        row["Số phòng"] = "Chưa có"
        row["Số lượng đồ"] = "Chưa nhập"
    if sheet_name == "TC":
        if "LTTC" in emp["code"]:
            row["Chi nhánh làm"] = "Không xác định"
            row["Tăng ca"] = "Null"
            row["Số công"] = "0"
            row["Chức năng"] = ""
            row["Số phòng"] = ""
            row["Số lượng đồ"] = ""
        elif "BPTC" in emp["code"]:
            row["Chức năng"] = "Chưa chọn"
            row["Chi nhánh làm"] = "Không xác định"
            row["Tăng ca"] = "Null"
            row["Số công"] = "0"
            row["Số phòng"] = "Chưa có"
            row["Số lượng đồ"] = "Chưa nhập"
    if sheet_name == "QL":
        row["Số công"] = "0"
    if sheet_name == "KTV":
        row["Số công"] = "0"
    return row

def update_missing_attendance(employees):
    """
    employees: list of dicts with keys: code, name, branch, ...
    This function lazy-imports Google API libs and appends absent rows only when needed.
    """
    # lazy imports to avoid startup cost
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build("sheets", "v4", credentials=creds).spreadsheets()
    values_service = service.values()
    now_vn = format_vn_datetime()
    processing_date = now_vn[:10]

    for sheet_name, header_row in HEADERS.items():
        employees_in_dept = [emp for emp in employees if get_sheet_name(emp["code"]) == sheet_name]
        if not employees_in_dept:
            continue
        try:
            existing = values_service.get(spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!A1:Z").execute()
            existing_data = existing.get("values", [])
        except Exception as e:
            # If sheet missing or inaccessible, skip
            # print useful debug in prod
            # (don't crash whole process)
            print(f"[missing_attendance] cannot access sheet {sheet_name}: {e}")
            continue

        # ensure header
        if not existing_data or existing_data[0] != header_row:
            try:
                values_service.update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{sheet_name}!A1",
                    valueInputOption="RAW",
                    body={"values": [header_row]}
                ).execute()
                existing_rows = []
            except Exception as e:
                # can't update header, skip this sheet
                print(f"[missing_attendance] header update failed for {sheet_name}: {e}")
                continue
        else:
            existing_rows = existing_data[1:]

        # build code->rows map for today's rows
        idx_code = header_row.index("Mã NV")
        idx_date = 0
        idx_chuc_nang = header_row.index("Chức năng") if "Chức năng" in header_row else -1

        code_to_rows_today = {}
        for row in existing_rows:
            if len(row) <= max(idx_date, idx_code):
                continue
            row_date = str(row[idx_date]).strip().replace("'", "")[:10]
            code = str(row[idx_code]).strip()
            if row_date != processing_date or not code:
                continue
            code_to_rows_today.setdefault(code, []).append(row)

        new_rows = []
        for emp in employees_in_dept:
            code = emp["code"]
            rows_today = code_to_rows_today.get(code, [])
            should_write = False
            if sheet_name == "BP":
                if not rows_today:
                    should_write = True
                else:
                    has_diem_danh = any((row[idx_chuc_nang] if idx_chuc_nang >= 0 and len(row) > idx_chuc_nang else "") == "Điểm danh" for row in rows_today)
                    if not has_diem_danh:
                        should_write = True
            else:
                if not rows_today:
                    should_write = True

            if should_write:
                absence_row = build_absence_row(sheet_name, emp, now_vn)
                row_data = [absence_row.get(h, "") for h in header_row]
                new_rows.append(row_data)

        if not new_rows:
            continue

        # append new rows
        try:
            values_service.append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{sheet_name}!A:A",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": new_rows}
            ).execute()
        except Exception as e:
            print(f"[missing_attendance] append failed for {sheet_name}: {e}")
            continue
