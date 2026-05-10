# Reservation Hub / Booking Management Flow

Cập nhật: 2026-05-04

Tài liệu này mô tả toàn bộ luồng quản lý đặt phòng trong PMS: tạo đặt phòng thủ công, OTA tự động từ email, đặt nhiều phòng theo cụm, xác nhận tồn phòng, gán phòng, nhận phòng, giá OTA, tiền cọc và các điểm code chính cần đọc khi bảo trì.

## 1. Mục tiêu module

Reservation Hub là trung tâm quản lý tất cả đặt phòng trước khi chuyển thành lưu trú thực tế.

Nguồn đặt phòng hiện có:

- `DIRECT`: lễ tân tạo trực tiếp.
- `OTA`: Agoda, Go2Joy, Traveloka, Expedia, Booking, Trip.com, Mytour, Airbnb, website khách sạn qua email OTA.
- `SALES`: booking từ sales.
- `ZALO`: booking từ Zalo.
- `PHONE`: booking từ số điện thoại.
- `WALK_IN`: khách đến trực tiếp và nhận phòng ngay.

Triết lý chính:

- `Booking` là đặt phòng / giữ chỗ / hồ sơ trước lưu trú.
- `HotelStay` là lượt lưu trú thật sau khi nhận phòng.
- Với đặt nhiều phòng, hệ thống vẫn giữ mô hình `1 Booking row = 1 phòng vận hành` để còn gán phòng, nhận phòng, folio và checkout riêng từng phòng.
- Với OTA nhiều phòng, mã OTA gốc là mã nhóm; các booking con có `external_id` riêng để không trùng DB nhưng vẫn giữ mã OTA gốc trong `raw_data.booking_reference_code` / `raw_data.ota_group_code`.

## 2. Các file quan trọng

### Backend

| File | Vai trò |
|---|---|
| `app/api/pms/reservation_api.py` | API Reservation Hub: list, create, update, confirm, cancel, assign room, check-in preparation, OTA logs. |
| `app/services/booking_service.py` | Service chính xử lý tạo/sửa booking, group booking, inventory reserve/release, serialize booking. |
| `app/api/pms/pms_checkin.py` | API nhận phòng: tạo `HotelStay`, khách lưu trú, deposit, OTA pricing lock. |
| `app/services/inventory_service.py` | Reserve/release tồn phòng theo ngày. |
| `app/services/ota_agent/integration.py` | Luồng OTA email tự động: parse email, map branch, upsert/create booking. |
| `app/services/ota_agent/rule_extractor.py` | Parser rule-based cho Agoda/Go2Joy/Website/Trip/Traveloka... |
| `app/services/ota_agent/gmail_service.py` | Gmail API + Pub/Sub watch + history fetch. |
| `app/services/ota_agent/ota_service.py` | Dashboard retry/scan OTA email lỗi. |

### Frontend

| File | Vai trò |
|---|---|
| `app/static/js/pms/reservation_hub/form.js` | Wizard tạo/sửa booking, room cart, pricing preview, OTA pricing/cọc. |
| `app/static/js/pms/reservation_hub/reservations.js` | Danh sách booking, action table, display booking/group/OTA. |
| `app/templates/pms/partials/reservation_hub/create_modal.html` | Modal tạo/sửa booking 3 bước. |
| `app/static/js/pms/pms_dashboard.js` | Dashboard phòng, arrivals, mở modal nhận phòng từ booking. |
| `app/static/js/pms/pms_checkin.js` | Modal nhận phòng, guest form, deposit method, OTA pricing lock. |
| `app/templates/pms/checkin.html` | HTML modal nhận phòng. |
| `app/static/js/pms/rd_modal.js` | Room detail/checkout/folio display. |
| `app/static/js/pms/pms_checkin.js` | Submit nhận phòng sang `/api/pms/checkin`. |

## 3. Model dữ liệu chính

### 3.1 Booking

`Booking` là record đặt phòng. Các field quan trọng:

| Field | Ý nghĩa |
|---|---|
| `booking_type` | Loại nguồn logic: `DIRECT`, `OTA`, `SALES`, `ZALO`, `PHONE`, `WALK_IN`. |
| `booking_source` | Kênh cụ thể: `Agoda`, `Go2Joy`, `Traveloka`, `Direct`, `Sales`... |
| `external_id` | Mã booking duy nhất theo source. OTA nhóm sẽ có suffix như `ABC-01`, `ABC-02`. |
| `reservation_status` | Trạng thái reservation mới: `PENDING`, `CONFIRMED`, `CHECKED_IN`, `CHECKED_OUT`, `CANCELLED`, `NO_SHOW`. |
| `status` | Legacy status enum: map từ `reservation_status`. |
| `guest_name`, `guest_phone`, `guest_id` | Thông tin khách chính / link CRM. |
| `check_in`, `check_out`, `estimated_arrival` | Ngày nhận/trả và giờ dự kiến. |
| `room_type`, `raw_data.room_type_id` | Hạng phòng đã đặt. |
| `assigned_room_id` | Phòng thật sau khi gán. |
| `total_price` | Tổng tiền tính cho booking row này. Với OTA group là phần tiền được chia cho phòng con. |
| `deposit_amount` | Tiền cọc của booking. Với OTA phải là `0`. |
| `payment_method` | Phương thức cọc nếu có. |
| `raw_data` | Metadata mở rộng: group, OTA, address, pricing, deposit_meta. |
| `source_booking_id` | Link booking con về booking đầu nhóm. |

### 3.2 HotelStay

`HotelStay` là lượt lưu trú thực tế sau khi nhận phòng.

| Field | Ý nghĩa |
|---|---|
| `room_id` | Phòng thật đang ở. |
| `check_in_at`, `check_out_at` | Thời điểm nhận/trả dự kiến hoặc thực tế. |
| `deposit` | Tiền khách trả trước ở thời điểm nhận phòng. Với OTA phải là `0` nếu không nhập cọc. |
| `deposit_type`, `deposit_meta` | Phương thức và metadata thanh toán. |
| `pricing_mode_initial` | Mode tính giá lúc nhận phòng: `HOURLY`, `NIGHT`, `OTA_MANUAL`... |
| `total_price` | Tổng tiền lock ban đầu. Với OTA dùng actual OTA total của booking. |
| `status` | `ACTIVE`, `CHECKED_OUT`, ... |

### 3.3 Inventory

Tồn phòng được quản lý theo ngày/hạng phòng bởi `InventoryService`.

Các hành động chính:

- Confirm booking: reserve tồn phòng.
- Cancel/no-show: release tồn phòng.
- Check-in: chuyển booking sang lưu trú, room trở thành occupied.
- Room block/OOO: giảm khả dụng.

## 4. Trạng thái đặt phòng

### 4.1 Reservation status mới

```text
PENDING      → booking mới, chưa giữ tồn phòng chắc chắn
CONFIRMED    → đã xác nhận, đã reserve tồn phòng
CHECKED_IN   → đã nhận phòng, có HotelStay
CHECKED_OUT  → đã checkout
CANCELLED    → đã hủy
NO_SHOW      → khách không đến
```

### 4.2 Legacy status mapping

Code mapping nằm trong `app/services/booking_service.py`:

```python
legacy_to_reservation_status(status)
reservation_to_legacy_status(status)
```

Mapping hiện tại:

```text
BookingStatus.CONFIRMED  → CONFIRMED/PENDING tùy reservation_status
BookingStatus.CANCELLED  → CANCELLED
BookingStatus.COMPLETED  → CHECKED_OUT
BookingStatus.NO_SHOW    → NO_SHOW
```

Lưu ý: `status` legacy không đủ phân biệt `PENDING` và `CONFIRMED`, vì vậy phải ưu tiên `reservation_status` khi xử lý nghiệp vụ.

## 5. Luồng tạo booking thủ công

Frontend chính: `app/static/js/pms/reservation_hub/form.js`

Modal tạo booking có 3 bước:

```text
Step 1: Chọn phòng
Step 2: Thông tin khách
Step 3: Thanh toán đặt cọc
```

### 5.1 Step 1: Chọn phòng

Người dùng chọn:

- Ngày/giờ nhận phòng.
- Ngày/giờ trả phòng dự kiến.
- Số khách, default hiện tại là `2`.
- Nguồn đặt: `DIRECT`, `OTA`, `SALES`, `ZALO`, `PHONE`.
- Nếu `OTA`: bắt buộc chọn kênh OTA và nhập mã tham chiếu.
- Hạng phòng và số lượng phòng.

Room cart được serialize thành:

```json
"room_items": [
  {
    "room_type_id": 1,
    "quantity": 2,
    "unit_total": 0,
    "reference_unit_total": 450000,
    "room_type": "Superior Double"
  }
]
```

Với booking thường:

- `unit_total` là giá billable.
- `reference_unit_total` cũng là giá tham chiếu.

Với OTA:

- `unit_total = 0` để tránh lấy giá PMS làm giá billable.
- `reference_unit_total` giữ giá PMS chỉ để đối soát.
- `total_price` của payload là tổng tiền thực thu OTA.

### 5.2 Step 2: Thông tin khách

Booking thường yêu cầu thông tin khách chính.

Booking OTA được relax:

- Không bắt buộc nhập đủ họ tên/số giấy tờ/giới tính/ngày sinh/số điện thoại ở bước tạo booking.
- Vì OTA auto/manual có thể chỉ có tên khách hoặc thiếu giấy tờ.
- Khi nhận phòng mới cần hoàn thiện hồ sơ khách lưu trú.

CSS class liên quan:

```text
bk-ota-guest-relaxed
```

### 5.3 Step 3: Thanh toán đặt cọc

Booking thường:

- Có thể nhập cọc.
- Chọn phương thức: `Chi nhánh`, `Chuyển khoản`, `Quẹt thẻ`, `Công ty`, `OTA`.
- Metadata cọc lưu ở `raw_data.deposit_meta`.

Booking OTA:

- Không nhập tiền cọc trước.
- `deposit_amount` phải là `0`.
- `payment_method`/`deposit_type` dùng `OTA` chỉ để đối soát.
- `deposit_meta.ota_channel` lấy từ `bk-form-ota-channel`.
- `deposit_meta.ref_code` lấy từ mã tham chiếu OTA.

Invariant cần giữ:

```text
Nếu booking_type == OTA:
  deposit_amount = 0
  raw_data.deposit_type = OTA
  raw_data.deposit_meta.ota_channel = booking_source/kênh OTA
  raw_data.deposit_meta.ref_code = mã OTA gốc
```

## 6. Backend tạo booking

API chính:

```http
POST /api/pms/reservations
PUT  /api/pms/reservations/{booking_id}
```

File:

```text
app/api/pms/reservation_api.py
```

Service:

```text
app/services/booking_service.py
```

### 6.1 Tạo một booking

Method:

```python
BookingService.create_reservation(payload, user_id)
```

Nhiệm vụ:

1. Parse `check_in`, `check_out`.
2. Resolve `room_type`.
3. Map `booking_type` / `booking_source`.
4. Find/create CRM guest nếu phù hợp.
5. Tạo `Booking`.
6. Nếu `reservation_status == CONFIRMED`: reserve inventory.
7. Log guest activity.
8. Post deposit vào shift nếu có cọc.

Lưu ý OTA:

- OTA tự động không nên sync CRM guest nếu chưa có guest info đầy đủ.
- OTA auto nên tạo `PENDING`, chưa reserve tồn phòng.
- OTA không được tự post deposit.

### 6.2 Tạo booking theo cụm / nhiều phòng

Method:

```python
BookingService.create_group_reservation(payload, user_id)
```

Đầu vào chính:

```json
{
  "booking_type": "OTA",
  "booking_source": "Go2Joy",
  "external_id": "987654322",
  "total_price": 900000,
  "room_items": [
    {
      "room_type_id": 1,
      "quantity": 2,
      "unit_total": 0,
      "reference_unit_total": 450000,
      "room_type": "Superior Double"
    }
  ]
}
```

Với OTA nhiều phòng:

- `payload.total_price` là tổng tiền thực thu của một mã OTA.
- PMS reference chỉ để đối soát.
- Hệ thống tạo nhiều `Booking` row, mỗi row là một phòng vận hành.
- Mã gốc giữ ở raw metadata.
- `external_id` con có suffix:

```text
987654322-01
987654322-02
```

Raw metadata group:

```json
{
  "group_code": "987654322",
  "group_index": 1,
  "group_total": 2,
  "group_summary": "Superior Double x2",
  "ota_group_code": "987654322",
  "booking_reference_code": "987654322",
  "ota_price_mode": "manual_channel_total",
  "ota_group_total": 900000,
  "ota_group_child_total": 450000,
  "ota_group_reference_total": 900000,
  "ota_group_reference_child_total": 450000,
  "ota_actual_total": 450000,
  "pms_reference_total": 450000,
  "ota_price_delta": 0
}
```

### 6.3 Cách chia tiền OTA nhiều phòng

Quy tắc:

1. Nếu nhiều phòng cùng loại và không có reference khác nhau: chia đều OTA total.
2. Nếu nhiều room type khác nhau và có PMS reference: chia theo tỷ trọng PMS reference.
3. Booking cuối hấp thụ phần làm tròn để tổng child luôn đúng bằng OTA actual total.

Ví dụ:

```text
OTA total: 900.000
Số phòng: 2
Kết quả:
  child 1: 450.000
  child 2: 450.000
```

Ví dụ mixed room:

```text
OTA total: 1.200.000
PMS reference:
  Superior: 400.000
  Deluxe:   800.000
Kết quả:
  Superior child: 400.000
  Deluxe child:   800.000
```

Nếu OTA actual khác PMS reference:

```text
OTA total: 1.000.000
PMS reference total: 1.200.000
Tỷ trọng vẫn theo PMS reference nếu mixed room.
```

## 7. Luồng OTA tự động từ Gmail/PubSub

### 7.1 Tổng quan

```text
Gmail Watch
  → Pub/Sub Push
  → /api/ota/webhook/gmail?token=...
  → gmail_service.fetch_new_emails_from_history(historyId)
  → ota_agent.process_email(...)
  → Rule parser hoặc Gemini
  → HotelMapper map branch
  → BookingService tạo booking PENDING
```

File chính:

```text
app/services/ota_agent/gmail_service.py
app/api/ota_dashboard.py
app/services/ota_agent/integration.py
app/services/ota_agent/rule_extractor.py
```

### 7.2 Gmail Watch

`gmail_service.watch_inbox()` đăng ký Gmail API watch vào Pub/Sub topic:

```text
settings.GOOGLE_PUBSUB_TOPIC
```

Watch trả về `historyId` baseline. Baseline này phải lưu vào DB bằng key:

```text
gmail_last_history_id
```

Nếu mất baseline hoặc server restart mà không có DB value, webhook đầu tiên có thể chỉ initialize historyId và không process email cũ.

### 7.3 Webhook Pub/Sub

Endpoint:

```http
POST /api/ota/webhook/gmail?token=<PUBSUB_VERIFICATION_TOKEN>
```

Log cần thấy:

```text
[Webhook] Gmail push received
[Gmail Push] ...
[Gmail Service] Email OTA mới
[OTA Agent] Processing email
```

### 7.4 Filter email OTA

`gmail_service` lọc:

- Sender thuộc `settings.OTA_SENDERS`.
- Subject không thuộc `SKIP_KEYWORDS` như report/newsletter/marketing/admin.
- Subject booking hoặc uncertain thì cho qua AI/rule parser.

### 7.5 Rule parser

`RuleBasedOTAExtractor` cố parse trước để giảm Gemini quota.

Các trường cần có để tự tin tạo booking:

```json
{
  "booking_source": "Go2Joy",
  "external_id": "987654322",
  "guest_name": "Nguyễn Văn C",
  "hotel_name": "BIN BIN 1",
  "room_type": "Superior Double",
  "num_rooms": 2,
  "check_in": "2026-05-26",
  "check_out": "2026-05-27",
  "total_price": 900000,
  "deposit_amount": 0
}
```

Với Go2Joy, parser cần đọc được:

```text
Số phòng 2
Tiền phòng 900.000 VND
Tình trạng thanh toán Đã thanh toán
```

### 7.6 Upsert OTA booking

Method:

```python
OTAAgent.upsert_booking(db, data)
```

Logic chính:

1. Nếu không có `external_id`: skip quietly.
2. Nếu đã có booking cùng `booking_source + external_id`: update existing.
3. Nếu `num_rooms > 1`: resolve room type rồi gọi `BookingService.create_group_reservation()`.
4. Nếu không resolve được room type hoặc chỉ 1 phòng: tạo một booking.
5. Booking OTA auto nên là `PENDING` và không reserve tồn phòng.

Điểm dễ lỗi:

- Nếu mã OTA đã từng tạo trước khi có logic group, lần test lại cùng mã sẽ chỉ update booking cũ một phòng.
- Cần test mã OTA hoàn toàn mới.
- Nếu `room_type` từ email không khớp PMS room type, `_resolve_room_type_id()` có thể fail và flow rơi về single booking.

## 8. Xác nhận booking và inventory

### 8.1 PENDING

`PENDING` nghĩa là booking đã được tạo nhưng chưa giữ tồn phòng chắc chắn.

Thường dùng cho:

- OTA auto mới parse từ email.
- Booking cần lễ tân kiểm tra tồn/phòng trước khi xác nhận.

### 8.2 CONFIRMED

Khi confirm booking:

```http
POST /api/pms/reservations/{booking_id}/confirm
```

Backend:

```python
BookingService.confirm_reservation(...)
```

Hệ thống:

1. Kiểm tra trạng thái hiện tại.
2. Reserve inventory cho hạng phòng/ngày ở.
3. Đổi `reservation_status = CONFIRMED`.
4. Set legacy `status` tương ứng.
5. Ghi activity.

### 8.3 Assign room

```http
POST /api/pms/reservations/{booking_id}/assign-room
```

Điều kiện:

- Booking chưa terminal.
- Room cùng branch.
- Room đúng room type nếu booking có `raw_data.room_type_id`.
- Không assign phòng đang occupied/conflict.

Assign room chỉ gán phòng vật lý, chưa tạo stay.

## 9. Nhận phòng từ booking

### 9.1 Mở modal nhận phòng

Từ dashboard/arrivals:

```text
pmsDashboardOpenAssignedBooking()
pmsDashboardCheckinBooking()
```

Frontend gọi:

```http
POST /api/pms/reservations/{booking_id}/checkin
```

Backend trả:

```json
{
  "booking_id": 123,
  "room_id": 10,
  "room_number": "101",
  "room_type_id": 1,
  "room_type_name": "Superior Double",
  "reservation": { ...BookingService.serialize(booking) }
}
```

Sau đó frontend build context:

```js
pmsReservationToCiContext(data, reservation)
pmsCiOpenReservationModal(context)
```

### 9.2 Modal nhận phòng

File:

```text
app/static/js/pms/pms_checkin.js
app/templates/pms/checkin.html
```

Modal nhận phòng dùng để:

- Hoàn thiện khách lưu trú.
- Kiểm tra CCCD đang active/trùng.
- Nhập dịch vụ/phụ thu nếu có.
- Chọn/lock pricing.
- Gửi form sang `/api/pms/checkin`.

### 9.3 Submit nhận phòng

Endpoint:

```http
POST /api/pms/checkin
```

Backend tạo:

- `HotelStay`
- `HotelGuest` / guest master sync
- folio hoặc payment/deposit transaction nếu có
- update booking sang `CHECKED_IN`

## 10. Quy tắc OTA khi nhận phòng

Đặc thù khách sạn: OTA không nhập tiền cọc trước trong PMS.

Invariant bắt buộc:

```text
Nếu booking_type == OTA:
  ci-deposit = 0
  deposit_type = OTA
  deposit_meta.ota_channel = booking_source hoặc raw_data.ota_channel
  deposit_meta.ref_code = raw_data.booking_reference_code hoặc raw_data.ota_group_code hoặc external_id
  stay.total_price = booking.total_price
  stay.pricing_mode_initial = OTA_MANUAL nếu có ota_actual_total
```

Modal nhận phòng OTA phải:

- Tự chọn card `OTA`.
- Tự điền `Kênh OTA`.
- Tự điền `Mã tham chiếu`.
- Khóa input cọc.
- Khóa card phương thức thanh toán để lễ tân không đổi nhầm.
- Không append tiền cọc vào folio.

Backend `/api/pms/checkin` cũng có guard:

```python
if booking.booking_type == "OTA" and not ota_actual_total:
    ota_actual_total = float(booking.total_price or 0)
if booking.booking_type == "OTA" and not ota_channel:
    ota_channel = booking.booking_source or raw_data.ota_channel
```

Cần lưu ý: UI lock chỉ là trải nghiệm; backend vẫn nên ép `deposit = 0` cho OTA để tránh sai lệch nếu frontend lỗi.

## 11. Giá OTA và giá PMS

### 11.1 Nguyên tắc

Với OTA:

- `total_price` là tiền thực thu từ kênh OTA.
- Giá PMS/PricingEngine chỉ là reference để đối soát.
- Không hiểu chênh lệch PMS vs OTA là khách phải thu thêm hoặc hoàn lại.

### 11.2 Metadata OTA pricing

Raw data thường có:

```json
{
  "ota_price_mode": "manual_channel_total",
  "ota_actual_total": 450000,
  "pms_reference_total": 500000,
  "ota_price_delta": -50000,
  "ota_channel": "Go2Joy",
  "booking_reference_code": "987654322"
}
```

Với OTA group:

```json
{
  "ota_group_total": 900000,
  "ota_group_child_total": 450000,
  "ota_group_reference_total": 1000000,
  "ota_group_reference_child_total": 500000
}
```

### 11.3 Check-in OTA pricing lock

Khi nhận phòng OTA:

- `HotelStay.total_price = ota_actual_total`.
- `HotelStay.pricing_mode_initial = OTA_MANUAL`.
- Room detail/checkout phải ưu tiên giá OTA đã lock thay vì tự tính PricingEngine.

## 12. Tiền cọc

### 12.1 Booking thường

Booking thường có thể nhập cọc tại Step 3.

Dữ liệu:

```json
{
  "deposit_amount": 100000,
  "payment_method": "Chuyển khoản",
  "raw_data": {
    "deposit_type": "Chuyển khoản",
    "deposit_meta": {
      "ref_code": "BANK123"
    }
  }
}
```

Khi có cọc:

- `BookingService._post_booking_deposit_once()` có thể post vào shift.
- Khi nhận phòng, nếu cọc đã ghi nhận từ booking, không nhập lại khoản này vào folio.

### 12.2 Booking OTA

Booking OTA không nhập cọc.

Bắt buộc:

```json
{
  "deposit_amount": 0,
  "payment_method": "OTA",
  "raw_data": {
    "deposit_type": "OTA",
    "deposit_meta": {
      "ota_channel": "Go2Joy",
      "ref_code": "987654322"
    },
    "ota_auto_no_deposit": true
  }
}
```

Nếu thấy OTA có `deposit_amount > 0`, đây là dữ liệu sai cần normalize về `0`.

## 13. Sửa booking

API:

```http
PUT /api/pms/reservations/{booking_id}
```

Service:

```python
BookingService.update_reservation(booking_id, payload, user_id)
```

Các rule chính:

- Không sửa booking terminal: `CANCELLED`, `NO_SHOW`, `CHECKED_OUT`.
- Nếu đã `CHECKED_IN`, chỉ nên sửa thông tin khách/ghi chú, không sửa core room/date/status.
- Nếu đổi room type/date/status, cần release/reserve inventory tương ứng.
- Nếu OTA: giữ `booking_reference_code`, `ota_channel`, `ota_price_mode`.

## 14. Hủy / No-show / Restore

API:

```http
POST /api/pms/reservations/{booking_id}/cancel
POST /api/pms/reservations/{booking_id}/no-show
POST /api/pms/reservations/{booking_id}/restore
```

Logic:

- Cancel/no-show release inventory nếu đã reserve.
- Set terminal status.
- Log activity.
- Restore đưa booking về trạng thái có thể xử lý lại nếu hợp lệ.

## 15. OTA logs và retry

Reservation Hub có OTA logs:

```http
GET  /api/pms/reservations/ota/logs
POST /api/pms/reservations/ota/retry/{log_id}
POST /api/pms/reservations/ota/scan-today
```

Log model:

```text
OTAParsingLog
```

Các field quan trọng:

- `email_subject`
- `email_sender`
- `email_message_id`
- `raw_content`
- `extracted_data`
- `status`: `SUCCESS`, `FAILED`, ...
- `booking_id`
- `error_message`
- `error_traceback`

Retry dùng `ota_service.py` và cũng phải áp dụng grouped OTA nếu `num_rooms > 1`.

## 16. Test mail OTA nhiều phòng

Ví dụ Go2Joy 2 phòng:

```text
Subject: Go2Joy - Đặt phòng mới - 987654322

Quý khách sạn BIN BIN 1, Khách sạn có đặt phòng mới
Tên khách Nguyễn Văn C Mã đặt phòng 987654322
Mã đặt phòng Loại phòng 987654322 Superior Double Loại đặt phòng Qua đêm
Số phòng 2
14:00, 26/05/2026 ~ 12:00, 27/05/2026
Tiền phòng 900.000 VND
Tình trạng thanh toán Đã thanh toán
```

Kỳ vọng:

```text
Booking 1:
  external_id = 987654322-01
  total_price = 450000
  reservation_status = PENDING
  raw_data.booking_reference_code = 987654322

Booking 2:
  external_id = 987654322-02
  total_price = 450000
  reservation_status = PENDING
  source_booking_id = booking_1.id
  raw_data.booking_reference_code = 987654322
```

Nếu chỉ tạo một booking:

1. Kiểm tra mã OTA đã tồn tại từ trước chưa.
2. Kiểm tra `OTAParsingLog.extracted_data.num_rooms` có phải `2` không.
3. Kiểm tra `room_type` có resolve được sang `HotelRoomType` không.
4. Kiểm tra branch mapping từ `hotel_name`.
5. Kiểm tra code path có rơi vào fallback single booking không.

## 17. Các endpoint Reservation Hub thường dùng

| Endpoint | Mục đích |
|---|---|
| `GET /api/pms/reservations` | List booking. |
| `GET /api/pms/reservations/{booking_id}` | Detail booking. |
| `POST /api/pms/reservations` | Create booking. |
| `PUT /api/pms/reservations/{booking_id}` | Update booking. |
| `POST /api/pms/reservations/{booking_id}/confirm` | Confirm và reserve tồn. |
| `POST /api/pms/reservations/{booking_id}/cancel` | Hủy booking. |
| `POST /api/pms/reservations/{booking_id}/no-show` | No-show. |
| `POST /api/pms/reservations/{booking_id}/restore` | Restore booking. |
| `POST /api/pms/reservations/{booking_id}/assign-room` | Gán phòng. |
| `POST /api/pms/reservations/{booking_id}/checkin` | Chuẩn bị context nhận phòng. |
| `POST /api/pms/checkin` | Nhận phòng thật, tạo HotelStay. |
| `GET /api/pms/reservations/today-arrivals` | Booking đến hôm nay. |
| `GET /api/pms/reservations/today-departures` | Booking trả hôm nay. |
| `GET /api/pms/reservations/in-house` | Booking đang ở. |
| `GET /api/pms/inventory/availability` | Tồn phòng theo ngày/hạng. |
| `GET /api/pms/reservations/ota/logs` | OTA parsing logs. |
| `POST /api/pms/reservations/ota/retry/{log_id}` | Retry OTA parse. |

## 18. Các invariant cần nhớ khi sửa code

### 18.1 Booking lifecycle

```text
Không tạo HotelStay khi booking chỉ mới PENDING/CONFIRMED.
Chỉ tạo HotelStay khi nhận phòng qua /api/pms/checkin.
```

### 18.2 Inventory

```text
PENDING không reserve tồn.
CONFIRMED reserve tồn.
CANCELLED/NO_SHOW release tồn.
CHECKED_IN không được sửa core date/room type tùy tiện.
```

### 18.3 OTA pricing

```text
OTA total_price là giá thực thu.
PMS reference chỉ để đối soát.
Không tự thu/hoàn chênh lệch OTA vs PMS.
```

### 18.4 OTA deposit

```text
OTA deposit_amount luôn là 0.
Không post cọc OTA vào shift.
Không nhập lại cọc OTA lúc check-in.
```

### 18.5 OTA group

```text
Một mã OTA nhiều phòng vẫn tạo nhiều Booking rows.
Mã OTA gốc nằm trong raw_data.booking_reference_code / raw_data.ota_group_code.
Child external_id phải unique: CODE-01, CODE-02...
Tổng child total_price phải bằng OTA group total.
```

### 18.6 Guest CRM

```text
Booking thường có thể sync/create Guest từ form.
OTA auto không nên tạo CRM guest nếu thiếu giấy tờ/thông tin đầy đủ.
Khi nhận phòng mới hoàn thiện hồ sơ HotelGuest/Guest.
```

## 19. Debug checklist

### 19.1 Booking không hiện ở arrivals

Kiểm tra:

- `reservation_status` có `PENDING` hoặc `CONFIRMED` không.
- `check_in` có phải hôm nay không.
- Frontend có truyền `branch_id` vào `/today-arrivals` không.
- Session active branch có đúng không.

### 19.2 Confirm booking lỗi tồn phòng

Kiểm tra:

- `raw_data.room_type_id` đúng không.
- `branch_id` đúng không.
- Inventory daily có record chưa.
- Room block/OOO có làm hết phòng không.

### 19.3 OTA email không tạo booking

Kiểm tra log:

```text
[Webhook] Gmail push received
[Gmail Push]
[Gmail Service] Email OTA mới
[OTA Agent] Processing email
```

Kiểm tra cấu hình:

- `OTA_ENABLED=true`
- `OTA_SENDERS` có sender chưa.
- Gmail Watch đã đăng ký lại chưa.
- Pub/Sub push endpoint có token đúng chưa.
- `gmail_last_history_id` có baseline chưa.

### 19.4 OTA nhiều phòng chỉ tạo một booking

Kiểm tra:

- Mã OTA test có bị trùng booking cũ không.
- `extracted_data.num_rooms` có > 1 không.
- `room_type` có map được sang PMS room type không.
- `branch_id` có map được không.
- `create_group_reservation()` có được gọi không.

### 19.5 OTA nhận phòng không tự điền kênh/mã

Kiểm tra response `/api/pms/reservations/{id}/checkin`:

```json
{
  "reservation": {
    "booking_type": "OTA",
    "booking_source": "Go2Joy",
    "external_id": "987654322-01",
    "raw_data": {
      "booking_reference_code": "987654322",
      "ota_channel": "Go2Joy"
    }
  }
}
```

Nếu `raw_data` thiếu, frontend không thể lấy mã OTA gốc.

### 19.6 OTA vẫn cho nhập cọc

Kiểm tra cả frontend và backend:

Frontend:

- `isOtaBookingForm()` trả `true`.
- `applyOtaDepositLock()` đã chạy.
- `bk-form-deposit.disabled == true`.
- payment card non-OTA bị disabled.

Backend:

- Khi payload `booking_type == OTA`, nên ép `deposit_amount = 0` trước khi tạo/update.
- Khi `/api/pms/checkin` có `booking.booking_type == OTA`, nên ép `deposit = 0` dù frontend gửi gì.

## 20. Các test nên chạy sau khi sửa Reservation Hub

Syntax:

```bash
node --check app/static/js/pms/reservation_hub/form.js
node --check app/static/js/pms/reservation_hub/reservations.js
node --check app/static/js/pms/pms_dashboard.js
node --check app/static/js/pms/pms_checkin.js
python3 -m py_compile app/services/booking_service.py
python3 -m py_compile app/api/pms/reservation_api.py
python3 -m py_compile app/api/pms/pms_checkin.py
python3 -m py_compile app/services/ota_agent/integration.py
python3 -m py_compile app/services/ota_agent/rule_extractor.py
```

Unit test hiện có:

```bash
python3 -m unittest tests/test_ota_rule_extractor.py
```

Manual test quan trọng:

1. Tạo booking direct một phòng, có cọc.
2. Confirm booking, kiểm tra inventory giảm.
3. Assign room, nhận phòng, kiểm tra HotelStay tạo đúng.
4. Tạo booking OTA một phòng, tổng OTA khác PMS reference.
5. Tạo booking OTA hai phòng cùng loại, kiểm tra child total sum đúng OTA total.
6. Nhận phòng OTA, kiểm tra cọc = 0, method OTA, kênh/mã tự điền.
7. Cancel/no-show booking confirmed, kiểm tra inventory release.

## 21. Nguyên tắc khi mở rộng module

- Đừng dùng `status` legacy làm nguồn sự thật duy nhất; ưu tiên `reservation_status`.
- Đừng dùng giá PMS để tính tiền thật của OTA.
- Đừng nhập/post tiền cọc OTA.
- Đừng gộp nhiều phòng vào một Booking row nếu phòng cần vận hành riêng.
- Đừng tự confirm OTA auto nếu chưa kiểm tra tồn.
- Khi thêm kênh OTA mới, cập nhật cả parser, dropdown, sender filter và mapping branch/room type.
- Khi sửa group booking, phải đảm bảo tổng tiền con bằng tổng tiền cha/mã OTA gốc.
- Khi sửa check-in, phải kiểm tra cả luồng walk-in nhanh và check-in từ booking.

## 22. Sơ đồ luồng tổng hợp

```text
Manual Reservation
  UI Step 1/2/3
    → POST /api/pms/reservations
      → BookingService.create_reservation/create_group_reservation
        → Booking PENDING/CONFIRMED
        → nếu CONFIRMED: InventoryService.reserve_booking

OTA Email
  Gmail Watch/PubSub
    → ota_agent.process_email
      → rule parser/Gemini
      → mapper branch
      → upsert_booking
        → num_rooms > 1: create_group_reservation
        → Booking PENDING, deposit 0, no inventory reserve

Confirm
  POST /api/pms/reservations/{id}/confirm
    → reserve inventory
    → reservation_status CONFIRMED

Assign Room
  POST /api/pms/reservations/{id}/assign-room
    → assigned_room_id set

Check-in
  POST /api/pms/reservations/{id}/checkin
    → return reservation context
    → pmsCiOpenReservationModal
    → POST /api/pms/checkin
      → create HotelStay
      → create/update HotelGuest/Guest
      → OTA: lock total_price and no deposit
      → Booking CHECKED_IN

Checkout
  Room detail / folio / checkout service
    → settle folio
    → room available/dirty
    → Booking CHECKED_OUT
```
