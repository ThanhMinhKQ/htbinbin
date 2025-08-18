# attendance_service.py - fixed column mapping & header sync for BP/TC only
from collections import defaultdict
from typing import List
from datetime import datetime
from pytz import timezone

# ================== CONFIG ==================
SERVICE_ACCOUNT_FILE = "config/credentials.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1R-5t90lNY22MUfkdv3YUHtKOzW7fjIIgjSYtCisDLqA"

# Header mặc định (cho tất cả sheet khác ngoài BP/TC)
BASE_HEADERS = [
    "Ngày", "Giờ", "Người điểm danh", "Mã NV", "Tên NV", "Chi nhánh chính",
    "Chi nhánh làm", "Tăng ca", "Số công", "Ghi chú"
]

# Header cho BP & TC (thêm 3 cột dịch vụ)
SERVICE_HEADERS = BASE_HEADERS + ["Dịch vụ", "Số phòng", "Số lượng đồ"]

# Cache sheet_id
_sheet_id_cache = {}

# ================== UTILS ==================
def _now_vn_str():
    tz = timezone("Asia/Ho_Chi_Minh")
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

def get_sheets_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)

def get_sheet_id_by_name(service, sheet_name: str) -> int:
    if sheet_name in _sheet_id_cache:
        return _sheet_id_cache[sheet_name]
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    for sheet in spreadsheet.get("sheets", []):
        props = sheet.get("properties", {})
        if props.get("title") == sheet_name:
            sid = props.get("sheetId")
            _sheet_id_cache[sheet_name] = sid
            return sid
    raise ValueError(f"Không tìm thấy sheet: {sheet_name}")

def _ensure_sheet_header(values_service, sheet_name: str):
    # Use correct range format for header row
    header_range = f"{sheet_name}!1:1"
    expected_headers = SERVICE_HEADERS if sheet_name.upper() in ("BP", "TC") else BASE_HEADERS
    try:
        result = values_service.get(spreadsheetId=SPREADSHEET_ID, range=header_range).execute()
        current_headers = result.get("values", [[]])[0]
        if current_headers != expected_headers:
            values_service.update(
                spreadsheetId=SPREADSHEET_ID,
                range=header_range,
                valueInputOption="USER_ENTERED",
                body={"values": [expected_headers]}
            ).execute()
    except Exception as e:
        print(f"[attendance_service] Lỗi đọc header {sheet_name}: {e}")
        values_service.update(
            spreadsheetId=SPREADSHEET_ID,
            range=header_range,
            valueInputOption="USER_ENTERED",
            body={"values": [expected_headers]}
        ).execute()

def create_sheet_if_not_exists(service, sheet_name: str, headers: list):
    """Tạo sheet mới nếu chưa tồn tại."""
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheet_titles = [s["properties"]["title"] for s in spreadsheet.get("sheets", [])]
    if sheet_name not in sheet_titles:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": sheet_name,
                                "gridProperties": {
                                    "rowCount": 1000,
                                    "columnCount": len(headers)
                                }
                            }
                        }
                    }
                ]
            }
        ).execute()
        # Ghi header cho sheet mới
        values_service = service.spreadsheets().values()
        header_range = f"{sheet_name}!1:1"
        values_service.update(
            spreadsheetId=SPREADSHEET_ID,
            range=header_range,
            valueInputOption="USER_ENTERED",
            body={"values": [headers]}
        ).execute()
        # Xóa cache sheet_id nếu có
        _sheet_id_cache.pop(sheet_name, None)

# ================== MAIN SAVE FUNCTIONS ==================
def push_single_checkin(data: dict) -> dict:
    return push_bulk_checkin([data])

def push_bulk_checkin(records: List[dict]) -> dict:
    import traceback
    if not records:
        print("[attendance_service] Không có bản ghi để ghi lên Google Sheets.")
        return {"status": "no_records", "inserted": 0}

    try:
        print(f"[attendance_service] Bắt đầu ghi {len(records)} bản ghi lên Google Sheets...")
        service = get_sheets_service()
        values_service = service.spreadsheets().values()

        grouped_by_sheet = defaultdict(list)
        for rec in records:
            sheet_name = rec.get("sheet") or "Default"
            grouped_by_sheet[sheet_name].append(rec)

        inserted_total = 0

        for sheet_name, recs in grouped_by_sheet.items():
            print(f"[attendance_service] Đang ghi sheet: {sheet_name}, số bản ghi: {len(recs)}")
            sheet_upper = sheet_name.strip().upper()
            is_service_sheet = sheet_upper in ("BP", "TC")
            headers = SERVICE_HEADERS if is_service_sheet else BASE_HEADERS

            # Tạo sheet nếu chưa có
            create_sheet_if_not_exists(service, sheet_name, headers)

            # Đảm bảo header đúng cho sheet
            _ensure_sheet_header(values_service, sheet_name)

            # Lấy dữ liệu hiện tại
            try:
                existing = values_service.get(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{sheet_name}!A1:Z"
                ).execute()
                existing_data = existing.get("values", [])
            except Exception as e:
                print(f"[attendance_service] Lỗi đọc sheet {sheet_name}: {e}")
                existing_data = []

            if not existing_data or existing_data[0] != headers:
                _ensure_sheet_header(values_service, sheet_name)
                sheet_rows = []
            else:
                sheet_rows = existing_data[1:]

            idx_code = headers.index("Mã NV")
            idx_date = headers.index("Ngày")
            idx_note = headers.index("Ghi chú")
            idx_nguoi_diem_danh = headers.index("Người điểm danh")
            if is_service_sheet:
                idx_dich_vu = headers.index("Dịch vụ")
                idx_so_phong = headers.index("Số phòng")
                idx_so_luong = headers.index("Số lượng đồ")

            # Map (code, date) → index
            code_date_map = {}
            for i, row in enumerate(sheet_rows):
                if len(row) > max(idx_code, idx_date):
                    code = str(row[idx_code]).strip()
                    date = str(row[idx_date]).strip()
                    code_date_map[(code, date)] = i

            appends = []

            for r in recs:
                dich_vu = r.get("dich_vu") or ""
                so_phong = r.get("so_phong") or ""
                so_luong = r.get("so_luong") or ""

                dt_raw = r.get("thoi_gian") or _now_vn_str()
                # Đảm bảo ngày và giờ là chuỗi, thêm dấu nháy đơn để ép kiểu chuỗi
                if " " in str(dt_raw):
                    ngay, gio = map(str, str(dt_raw).split(" ", 1))
                else:
                    ngay, gio = str(dt_raw), ""
                ngay = f"'{ngay}"
                gio = f"'{gio}"
                code = r.get("ma_nv")
                nguoi_diem_danh = r.get("nguoi_diem_danh", "")

                idx = code_date_map.get((code, ngay))
                if idx is not None:
                    # Cập nhật dòng cũ
                    row_data = sheet_rows[idx]
                    while len(row_data) < len(headers):
                        row_data.append("")
                    row_data[idx_date] = ngay
                    row_data[headers.index("Giờ")] = gio if "Giờ" in headers else ""
                    row_data[idx_nguoi_diem_danh] = nguoi_diem_danh
                    if is_service_sheet:
                        row_data[idx_dich_vu] = dich_vu
                        row_data[idx_so_phong] = so_phong
                        row_data[idx_so_luong] = so_luong
                    row_data[idx_note] = r.get("ghi_chu", "")
                    range_update = f"{sheet_name}!A{idx+2}:{chr(65+len(headers)-1)}{idx+2}"
                    values_service.update(
                        spreadsheetId=SPREADSHEET_ID,
                        range=range_update,
                        valueInputOption="USER_ENTERED",
                        body={"values": [row_data]}
                    ).execute()
                    inserted_total += 1
                else:
                    # Append mới
                    if is_service_sheet:
                        row_data = [
                            ngay, gio, nguoi_diem_danh, code, r.get("ten_nv"),
                            r.get("chi_nhanh_chinh"), r.get("chi_nhanh_lam"),
                            "x" if r.get("la_tang_ca") else "",
                            r.get("so_cong_nv"), r.get("ghi_chu", ""),
                            dich_vu, so_phong, so_luong
                        ]
                    else:
                        row_data = [
                            ngay, gio, nguoi_diem_danh, code, r.get("ten_nv"),
                            r.get("chi_nhanh_chinh"), r.get("chi_nhanh_lam"),
                            "x" if r.get("la_tang_ca") else "",
                            r.get("so_cong_nv"), r.get("ghi_chu", "")
                        ]
                    appends.append(row_data)

            if appends:
                print(f"[attendance_service] Đang append {len(appends)} dòng mới vào sheet {sheet_name}")
                values_service.append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{sheet_name}!A:A",
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": appends}
                ).execute()
                inserted_total += len(appends)

            # Auto resize
            try:
                sheet_id = get_sheet_id_by_name(service, sheet_name)
                service.spreadsheets().batchUpdate(
                    spreadsheetId=SPREADSHEET_ID,
                    body={
                        "requests": [{
                            "autoResizeDimensions": {
                                "dimensions": {
                                    "sheetId": sheet_id,
                                    "dimension": "COLUMNS",
                                    "startIndex": 0,
                                    "endIndex": len(headers)
                                }
                            }
                        }]
                    }
                ).execute()
            except Exception as e:
                print(f"[attendance_service] Lỗi auto resize: {e}")

        print(f"[attendance_service] Đã ghi xong. Tổng số dòng ghi: {inserted_total}")
        return {"status": "success", "inserted": inserted_total}

    except Exception as e:
        print(f"[attendance_service] Lỗi Google API: {e}")
        traceback.print_exc()
        raise  # raise để API trả lỗi về frontend
