# attendance_service.py - tách riêng DV sheet (không có cột Số công)
from collections import defaultdict
from typing import List
from datetime import datetime
from pytz import timezone

# ================== CONFIG ==================
#SERVICE_ACCOUNT_FILE = "config/credentials.json"
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

# Cache sheet_id
_sheet_id_cache = {}

# ================== UTILS ==================
def get_sheet_name(code: str) -> str:
    """
    Xác định sheet ghi điểm danh dựa trên mã nhân viên.
    - Mã có "TC" (Tăng ca) -> sheet "TC"
    - Mã có "BP" (Buồng phòng) không tăng ca -> sheet "DV"
    - Các bộ phận khác có sheet riêng theo vai trò.
    """
    code_upper = (code or "").upper()

    # Ưu tiên 1: Mã tăng ca ("TC") luôn vào sheet "TC"
    if "TC" in code_upper:
        return "TC"

    # Ưu tiên 2: Buồng phòng (không tăng ca) vào sheet "DV"
    if "BP" in code_upper:
        return "DV"

    # Lễ tân (không tăng ca)
    if "LT" in code_upper:
        return "LT"

    # Các vai trò khác
    if "BV" in code_upper:
        return "BV"
    if "QL" in code_upper:
        return "QL"
    if "KTV" in code_upper:
        return "KTV"

    return "Default" # Fallback cho các trường hợp khác

def _now_vn_str():
    tz = timezone("Asia/Ho_Chi_Minh")
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

def get_sheets_service():
    import os, json
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
    header_range = f"{sheet_name}!1:1"
    sheet_upper = sheet_name.upper()
    if sheet_upper == "DV":
        expected_headers = DV_HEADERS
    else:
        expected_headers = BASE_HEADERS

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
        values_service = service.spreadsheets().values()
        values_service.update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{sheet_name}!1:1",
            valueInputOption="USER_ENTERED",
            body={"values": [headers]}
        ).execute()
        _sheet_id_cache.pop(sheet_name, None)

# ================== MAIN SAVE FUNCTIONS ==================
def push_single_checkin(data: dict) -> dict:
    return push_bulk_checkin([data])

def push_bulk_checkin(records: List[dict]) -> dict:
    """
    Hybrid: Nếu trùng mã NV + ngày thì update, nếu chưa có thì append.
    Đọc sheet 1 lần duy nhất cho mỗi sheet -> nhanh hơn nhiều.
    """
    import traceback
    if not records:
        print("[attendance_service] Không có bản ghi để ghi lên Google Sheets.")
        return {"status": "no_records", "inserted": 0}

    try:
        print(f"[attendance_service] [HYBRID] Bắt đầu xử lý {len(records)} bản ghi...")
        service = get_sheets_service()
        values_service = service.spreadsheets().values()

        grouped_by_sheet = defaultdict(list)
        for rec in records:
            ma_nv = rec.get("ma_nv") or ""
            # Sử dụng hàm get_sheet_name để xác định sheet một cách nhất quán
            sheet_name = get_sheet_name(ma_nv)
            rec["sheet"] = sheet_name
            grouped_by_sheet[sheet_name].append(rec)

        inserted_total, updated_total = 0, 0

        for sheet_name, recs in grouped_by_sheet.items():
            sheet_upper = sheet_name.strip().upper()
            headers = DV_HEADERS if sheet_upper == "DV" else BASE_HEADERS

            create_sheet_if_not_exists(service, sheet_name, headers)
            _ensure_sheet_header(values_service, sheet_name)

            # Đọc sheet 1 lần duy nhất
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

            # Map để check trùng
            idx_code = headers.index("Mã NV")
            idx_date = headers.index("Ngày")
            code_date_map = {}
            for i, row in enumerate(sheet_rows):
                if len(row) > max(idx_code, idx_date):
                    code = str(row[idx_code]).strip()
                    date = str(row[idx_date]).strip()
                    code_date_map[(code, date)] = i

            # Gom các bản ghi cần update / append
            updates, appends = [], []

            for r in recs:
                dt_raw = r.get("thoi_gian") or _now_vn_str()
                if " " in str(dt_raw):
                    ngay, gio = map(str, str(dt_raw).split(" ", 1))
                else:
                    ngay, gio = str(dt_raw), ""
                ngay = f"'{ngay}"
                gio = f"'{gio}"

                code = r.get("ma_nv")
                nguoi_diem_danh = r.get("nguoi_diem_danh", "")
                ghi_chu = r.get("ghi_chu", "")

                if sheet_upper == "DV":
                    row_data = [
                        ngay, gio, nguoi_diem_danh, code, r.get("ten_nv"),
                        r.get("chi_nhanh_chinh"), r.get("chi_nhanh_lam"),
                        "x" if r.get("la_tang_ca") else "",
                        r.get("dich_vu") or "",
                        r.get("so_phong") or "",
                        r.get("so_luong") or "",
                        ghi_chu
                    ]
                else:
                    row_data = [
                        ngay, gio, nguoi_diem_danh, code, r.get("ten_nv"),
                        r.get("chi_nhanh_chinh"), r.get("chi_nhanh_lam"),
                        "x" if r.get("la_tang_ca") else "",
                        r.get("so_cong_nv") or "",
                        ghi_chu
                    ]

                idx = code_date_map.get((code, ngay))
                if idx is not None:
                    # record đã có -> update
                    updates.append((idx + 2, row_data))  # +2 vì header + base 1
                else:
                    appends.append(row_data)

            # Batch update 1 lần
            if updates:
                data = []
                for row_num, row_data in updates:
                    rng = f"{sheet_name}!A{row_num}:{chr(65+len(headers)-1)}{row_num}"
                    data.append({"range": rng, "values": [row_data]})
                values_service.batchUpdate(
                    spreadsheetId=SPREADSHEET_ID,
                    body={"valueInputOption": "USER_ENTERED", "data": data}
                ).execute()
                updated_total += len(updates)

            # Batch append 1 lần
            if appends:
                values_service.append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{sheet_name}!A:A",
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": appends}
                ).execute()
                inserted_total += len(appends)

        print(f"[attendance_service] [HYBRID] Đã xử lý xong. Update: {updated_total}, Append: {inserted_total}")
        return {"status": "success", "inserted": inserted_total, "updated": updated_total}

    except Exception as e:
        print(f"[attendance_service] Lỗi Google API (HYBRID): {e}")
        traceback.print_exc()
        return {"status": "error", "inserted": 0, "updated": 0, "error": str(e)}

def get_attendance_by_checker(checker_code: str) -> list:
    """
    Lấy tất cả các bản ghi điểm danh (bao gồm cả DV) được thực hiện bởi một người.
    """
    try:
        service = get_sheets_service()
        spreadsheet_meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheets = spreadsheet_meta.get('sheets', [])
        
        all_records = []
        
        # Lấy danh sách tên các sheet
        sheet_titles = [s['properties']['title'] for s in sheets]

        for sheet_name in sheet_titles:
            # Bỏ qua các sheet không liên quan nếu có
            if sheet_name.lower() in ['config', 'summary']:
                continue

            print(f"[get_attendance_by_checker] Đang đọc sheet: {sheet_name}")
            try:
                result = service.spreadsheets().values().get(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{sheet_name}!A:Z"
                ).execute()
                
                values = result.get('values', [])
                if not values:
                    continue

                headers = values[0]
                if "Người điểm danh" not in headers:
                    continue
                
                checker_col_idx = headers.index("Người điểm danh")

                for row in values[1:]:
                    if len(row) > checker_col_idx and row[checker_col_idx] == checker_code:
                        record = dict(zip(headers, row))
                        record['sheet_name'] = sheet_name # Thêm thông tin sheet
                        all_records.append(record)

            except Exception as e:
                print(f"[get_attendance_by_checker] Lỗi khi xử lý sheet '{sheet_name}': {e}")
                continue
        
        # Sắp xếp kết quả theo ngày giờ mới nhất lên đầu
        all_records.sort(key=lambda x: (x.get('Ngày', ''), x.get('Giờ', '')), reverse=True)
        return all_records

    except Exception as e:
        print(f"[get_attendance_by_checker] Lỗi nghiêm trọng: {e}")
        return []
