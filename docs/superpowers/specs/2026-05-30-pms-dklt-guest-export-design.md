# PMS ĐKLT — Xuất theo khách + theo dõi đã xuất + lọc ngày đến

**Ngày:** 2026-05-30
**Phạm vi:** Tính năng xuất Đăng ký lưu trú (ĐKLT) trong PMS Dashboard
**Trạng thái:** Đã chốt hướng A1 + B1 + C, chờ review spec

---

## 1. Bối cảnh & vấn đề

Popup "Xuất Đăng ký lưu trú" hiện tại (`pms-dklt-modal` trong `app/templates/pms/dashboard.html`) cho phép nhân viên lễ tân chọn **phòng** đang lưu trú rồi xuất file ĐKLT (Excel cho khách VN, Excel/XML cho khách nước ngoài). Logic:

- Frontend: `PMS_DKLT` state trong `app/static/js/pms/pms_dashboard.js` — chọn ở **mức stay (phòng)**, gửi `stay_ids`.
- Backend: 3 endpoint trong `app/api/pms/pms_export.py`:
  - `GET /api/pms/dklt/preview` — đếm VN/foreign.
  - `GET /api/pms/dklt/rooms` — liệt kê stay đang ở (chỉ count, không có chi tiết khách).
  - `GET /api/pms/dklt/export` — build file theo `stay_ids` + `group` + `format`.

**Hạn chế hiện tại:**

1. Chỉ chọn được nguyên phòng — không tick được từng khách trong phòng.
2. Không biết khách nào **đã từng xuất ĐKLT** — dễ khai trùng hoặc bỏ sót.
3. Không lọc được theo **ngày đến** (hôm nay / hôm qua / khoảng ngày).

**Mục tiêu:** Cho phép xuất ở mức **khách**, đánh dấu & hiển thị trạng thái "đã xuất", và lọc theo ngày đến — nhưng vẫn cho phép xuất lại (cờ chỉ để cảnh báo, không khoá).

---

## 2. Quyết định đã chốt

| Phần | Hướng chốt | Lý do |
| --- | --- | --- |
| A — Lưu trạng thái đã xuất | **A1**: thêm 2 cột vào `hotel_guests` | Ít bề mặt thay đổi nhất, query thẳng, đủ cho nhu cầu "đã/chưa + lần gần nhất". Khớp pattern `created_by`/`updated_by` sẵn có. |
| B — Lấy dữ liệu khách | **B1**: mở rộng `/api/pms/dklt/rooms` trả thêm `guests[]` | Một nguồn dữ liệu, toggle view thuần client, tránh lệch nguồn. |
| C — Export theo guest | **C**: thêm `guest_ids` vào `/export` + tách POST đánh dấu | Đúng REST (GET không side-effect), tương thích ngược `stay_ids`. |

---

## 3. Thiết kế Database (A1)

### 3.1 Thêm cột vào `hotel_guests`

Model `HotelGuest` (`app/db/models.py:1530`) thêm 2 cột, đặt ngay sau `updated_by`:

```python
dklt_exported_at = Column(DateTime(timezone=True), nullable=True)
dklt_exported_by = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
```

- `dklt_exported_at`: thời điểm xuất ĐKLT **gần nhất** của khách này. NULL = chưa xuất.
- `dklt_exported_by`: user id người xuất gần nhất.
- Không backfill — toàn bộ khách hiện hữu = NULL = "chưa xuất".
- Re-export ghi đè timestamp (chấp nhận được — chỉ cần biết lần gần nhất).

Không thêm relationship cho `dklt_exported_by` (không cần load tên người xuất ở UI hiện tại; chỉ hiển thị ngày). Nếu sau này cần, bổ sung riêng.

### 3.2 Migration Alembic

- File mới trong `alembic/versions/`, ví dụ `add_dklt_exported_fields.py`.
- `down_revision = '4c3c30f314f2'` (head hiện tại — `add_guest_documents`). **Lưu ý sửa lỗi nhận định trước đó:** repo chỉ có **một** head, không phải 5 head song song. `alembic heads` xác nhận `4c3c30f314f2 (head)`. Không cần merge head.
- `upgrade()`: `op.add_column` 2 cột (nullable=True) + tạo FK `dklt_exported_by → users.id` (ondelete SET NULL).
- `downgrade()`: `op.drop_column` 2 cột (drop constraint FK trước nếu cần theo dialect).

---

## 4. Thiết kế API (B1 + C)

### 4.1 `GET /api/pms/dklt/rooms` — mở rộng payload (B1)

Giữ nguyên cấu trúc `stays[]` hiện có (`stay_id`, `room_number`, `check_in_at`, `check_out_at`, `vn_count`, `foreign_count`, `primary_guest`) để view-theo-phòng không phải đổi. **Thêm** vào mỗi stay mảng `guests[]`:

```json
{
  "guest_id": 123,
  "full_name": "Nguyễn Văn A",
  "is_foreign": false,
  "is_primary": true,
  "check_in_at": "2026-05-30T14:00:00+07:00",
  "dklt_exported_at": null
}
```

- `is_foreign`: từ helper `_is_foreign(guest)` sẵn có (`id_type ∈ FOREIGN_ID_TYPES`).
- `is_primary`: `guest.is_primary`.
- `check_in_at`: `guest.check_in_at` fallback `stay.check_in_at` (để lọc ngày đến hoạt động cả khi khách cùng phòng đến khác ngày).
- `dklt_exported_at`: ISO string hoặc null.

Implement: trong vòng lặp `by_stay` của `api_dklt_rooms`, gom thêm `guests` list song song với việc đếm `vn_count`/`foreign_count` (dùng cùng `rows` từ `_query_active_guests`). Sort `guests` trong mỗi stay theo `is_primary desc, full_name`.

### 4.2 `GET /api/pms/dklt/export` — thêm `guest_ids` (C)

Thêm query param `guest_ids: Optional[str]` (CSV). Logic lọc:

- Nếu có `guest_ids` → lọc `rows_raw` theo `r["guest"].id ∈ guest_ids` (ưu tiên hơn `stay_ids`).
- Nếu không có `guest_ids` → giữ nguyên logic `stay_ids` cũ (tương thích ngược).
- Phần còn lại (tách VN/foreign theo `group`, build file, `_stream_file`) **không đổi**.
- **Endpoint này KHÔNG ghi DB** — thuần tạo file (giữ GET sạch).

Validate `guest_ids` giống `stay_ids`: parse int, lỗi → HTTP 400 "guest_ids không hợp lệ.".

### 4.3 `POST /api/pms/dklt/mark-exported` — endpoint mới (C)

```
POST /api/pms/dklt/mark-exported
Body: { "guest_ids": [123, 456, ...] }
Response: { "updated": <int> }
```

- Resolve branch như các endpoint khác (qua `_resolve_branch`, đảm bảo guest thuộc branch người dùng có quyền — lọc theo branch khi update).
- Set `dklt_exported_at = datetime.now(VN_TZ)` và `dklt_exported_by = <user.id từ session>` cho các guest trong danh sách **thuộc branch đó**.
- `db.commit()`, trả `{ "updated": n }`.
- Body rỗng / không có `guest_ids` → HTTP 400.
- Áp dụng cho cả 2 nhóm VN & foreign (frontend gửi đúng tập đã xuất).

Lấy user id từ session theo cùng cơ chế các endpoint PMS khác đang dùng (kiểm tra tại bước implement — dùng đúng dependency/`request.session` hiện hành thay vì giả định).

---

## 5. Thiết kế Frontend (popup)

### 5.1 Mở rộng `PMS_DKLT` state

```js
const PMS_DKLT = {
    stays: [],              // giữ nguyên (kèm guests[] mới)
    guests: [],             // mảng phẳng dựng từ stays[].guests[] + {stay_id, room_number}
    selected: new Set(),    // GIỜ chứa guest_id (đổi từ stay_id)
    filter: '',
    scope: 'all',           // 'all' | 'vn' | 'foreign'
    viewMode: 'room',       // 'room' | 'guest'  (mới)
    dateFilter: 'all',      // 'all' | 'today' | 'yesterday' | 'custom'  (mới)
    dateFrom: null,         // ISO date khi custom
    dateTo: null,
    loaded: false,
};
```

`selected` chuyển từ tập `stay_id` → tập `guest_id`. Đây là **nguồn chân lý** cho việc chọn ở cả 2 view.

### 5.2 Quan hệ chọn phòng ↔ chọn khách

- Chọn ở **mức guest** là gốc.
- View-theo-phòng: checkbox phòng = trạng thái tổng hợp của các guest trong phòng:
  - tất cả guest trong phòng được chọn → phòng `checked`.
  - một phần → `indeterminate`.
  - không có → unchecked.
  - tick/untick phòng = tick/untick tất cả guest **đang hiển thị** (sau filter) trong phòng đó.
- Chuyển view giữ nguyên `selected` (không reset).

### 5.3 Auto-tick khi mở popup

- Guest **chưa xuất** (`dklt_exported_at == null`) → auto-tick (giữ hành vi hiện tại "chọn tất cả").
- Guest **đã xuất** → **không** auto-tick (tránh khai trùng), nhưng vẫn cho tick lại thủ công.

### 5.4 Lọc theo ngày đến

- Quick filter: **Tất cả / Hôm nay / Hôm qua / Khoảng ngày** (2 ô `<input type="date">` khi chọn "Khoảng ngày").
- Lọc trên `check_in_at` của guest (so theo ngày VN, bỏ giờ).
- Kết hợp được với scope quốc tịch (`all/vn/foreign`) và ô tìm tên/phòng sẵn có.

### 5.5 Cờ "đã xuất"

- Guest có `dklt_exported_at` → badge **"Đã xuất · dd/mm"** (tông xanh xám).
- Hiển thị ở cả 2 view (mức guest).

### 5.6 Submit & đánh dấu

- `pmsDkltSubmit`: gom `guest_ids` từ `selected` (thay cho `stay_ids`).
- `pmsDownloadDkltFile`: gửi `guest_ids` thay `stay_ids` trên URL `/export`. Giữ tách VN/foreign + Excel/XML như cũ (vòng lặp `groups`).
- Sau khi **tất cả** file tải thành công → gọi `POST /api/pms/dklt/mark-exported` với chính tập `guest_id` vừa xuất.
- Cập nhật badge tại chỗ: set `dklt_exported_at` cho các guest trong `PMS_DKLT.guests`/`stays` rồi re-render (không cần mở lại popup). Toast thành công như cũ.
- Nếu mark-exported lỗi nhưng file đã tải: toast cảnh báo nhẹ "Đã xuất file nhưng chưa đánh dấu được trạng thái" — không chặn flow tải.

### 5.7 Hàm frontend đổi/thêm

Đổi: `pmsOpenDkltModal`, `pmsDkltVisibleStays` (tách thành filter theo guest), `pmsDkltRender`, `pmsDkltUpdateFooter`, `pmsDkltSyncSelectAll`, `pmsDkltToggleStay` → `pmsDkltToggleGuest`, `pmsDkltToggleAll`, `pmsDkltSubmit`, `pmsDownloadDkltFile`.
Thêm: `pmsDkltSetViewMode`, `pmsDkltSetDateFilter`, `pmsDkltBuildGuests` (dựng mảng phẳng), `pmsDkltMarkExported` (gọi POST), helper lọc ngày.

### 5.8 Markup (`dashboard.html`)

Trong `pms-dklt-modal`:
- Thêm toggle view **Theo phòng / Theo khách** (cạnh hàng scope, dùng pattern `pms-dklt-scope-btn`).
- Thêm hàng lọc ngày (quick buttons + 2 ô date ẩn/hiện).
- `pms-dklt-room-list` render được cả 2 layout: view phòng (guest thụt vào trong mỗi phòng) và view khách (danh sách phẳng).

### 5.9 CSS

Trong block style của `dashboard.html` (bám `--pms-*`, hỗ trợ `html.dark`):
- Hàng guest thụt lề trong view phòng.
- Badge "đã xuất".
- Nút toggle view (tái dùng `.pms-dklt-scope-btn`).
- Ô lọc ngày.

---

## 6. Phạm vi KHÔNG đụng tới

- `/api/pms/dklt/preview` — giữ nguyên (chỉ đếm tổng, không cần guest detail).
- Logic build file Excel/XML (`_build_vn_xlsx`, `_build_foreign_xml`, `_build_foreign_xlsx`, `_foreign_row`) — không đổi.
- `_query_active_guests`, `_is_foreign`, `_resolve_branch` — dùng lại, không sửa.
- Reservation/inventory state, auth boundaries — không liên quan.

---

## 7. Rủi ro & kiểm thử

**Rủi ro:**
- Migration trên bảng `hotel_guests` (bảng lớn, nhiều index). `add_column` nullable không backfill → an toàn, không lock lâu trên Postgres.
- Đổi ngữ nghĩa `PMS_DKLT.selected` từ stay_id → guest_id: phải rà hết các hàm tham chiếu để tránh sót.

**Kiểm thử (theo `.claude/rules/verification.md`):**
- Backend: chạy app, gọi `/api/pms/dklt/rooms` xác nhận có `guests[]`; gọi `/export?guest_ids=...` xác nhận file đúng tập khách; gọi `POST /mark-exported` xác nhận DB cập nhật.
- Frontend (browser): mở popup, toggle 2 view, tick mức khách & mức phòng (indeterminate), lọc ngày, xuất → kiểm tra badge "đã xuất" hiện sau khi xuất, dark mode.
- `gitnexus_impact` trên `api_dklt_export`, `api_dklt_rooms` trước khi sửa; `gitnexus_detect_changes()` trước commit.
- Migration: review upgrade/downgrade; thử `alembic upgrade head` trên DB dev.

---

## 8. Thứ tự triển khai (gợi ý cho plan)

1. DB: model + migration.
2. API: mở rộng `/rooms`, thêm `guest_ids` vào `/export`, thêm `POST /mark-exported`.
3. Frontend JS: state + render 2 view + lọc ngày + submit/mark.
4. Markup + CSS.
5. Verify (browser + API) → detect_changes → (chờ user duyệt commit).
