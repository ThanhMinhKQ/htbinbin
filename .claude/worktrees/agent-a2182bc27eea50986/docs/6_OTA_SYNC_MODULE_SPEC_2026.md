I. 🎯 Mục tiêu

Hệ thống phải làm được 3 việc real-time hoặc near real-time:

1. PUSH availability (tồn phòng)
2. PUSH pricing (giá)
3. PULL booking (đơn đặt phòng)
II. 🧠 Kiến trúc chuẩn (Channel Manager Layer)
PMS Core
   ↓
OTA Sync Service (Middleware)
   ↓
Booking.com / Agoda / Traveloka

👉 Không bao giờ connect trực tiếp DB → OTA
→ luôn qua sync service

III. 🚨 Vấn đề DB hiện tại của bạn

Bạn có:

Booking ✅
OTAParsingLog (email parsing) ⚠️ (cũ)

👉 Nhưng:

❌ Không có API sync
❌ Không có mapping OTA
❌ Không có webhook
❌ Không có push availability

👉 Nghĩa là:
Hiện tại bạn đang “fake OTA” bằng email parsing

→ phải nâng cấp lên real API

IV. 🧱 DATABASE DESIGN (OTA LAYER)
1. 🔗 ota_channels
ota_channels
Field	Type
id	BIGINT
name	VARCHAR
is_active	BOOL
api_key	TEXT
api_secret	TEXT
created_at	DATETIME
2. 🔗 ota_room_mapping
ota_room_mapping
Field	Type
id	BIGINT
channel_id	FK
room_type_id	FK
external_room_id	VARCHAR

👉 Mapping:

HotelRoomType ↔ Booking.com Room ID
3. 💰 ota_rate_mapping
ota_rate_mapping
Field	Type
id	BIGINT
channel_id	FK
rate_plan_id	FK
external_rate_id	VARCHAR
4. 📦 ota_sync_log (CỰC QUAN TRỌNG)
ota_sync_log
Field	Type
id	BIGINT
channel	VARCHAR
action	VARCHAR
request_payload	JSONB
response_payload	JSONB
status	SUCCESS / FAILED
error_message	TEXT
created_at	DATETIME

👉 Đây là bảng cứu mạng khi debug

5. 🔄 ota_booking_raw
ota_booking_raw
Field	Type
id	BIGINT
channel	VARCHAR
external_id	VARCHAR
raw_json	JSONB
parsed	BOOL
created_at	DATETIME

👉 lưu raw trước khi parse → tránh mất dữ liệu

V. 🔄 FLOW OTA SYNC
1. 📤 PUSH AVAILABILITY
Trigger:
Booking mới
Cancel
Check-in
Maintenance
Flow:
Update room_inventory_daily
    ↓
Build payload
    ↓
Call OTA API
Payload ví dụ:
{
  "room_id": "123",
  "date": "2026-04-01",
  "available": 5
}
2. 💵 PUSH PRICE
Trigger:
Cron (mỗi 5–15 phút)
Khi pricing change
Flow:
room_rates_daily
    ↓
Apply mapping
    ↓
Push OTA
3. 📥 PULL BOOKING
2 cách:
Cách 1: Webhook (BEST)

OTA → call API của bạn

POST /api/ota/webhook/booking
Cách 2: Polling
Cron mỗi 1 phút
→ fetch booking mới
Flow xử lý booking:
RAW → VALIDATE → CREATE Booking → UPDATE inventory
4. 🔄 IDENTITY RULE (QUAN TRỌNG)

👉 Tránh duplicate:

external_id phải UNIQUE
VI. 🧠 BOOKING MAPPING

OTA → Booking:

OTA Field	PMS Field
guest_name	guest_name
checkin	check_in
checkout	check_out
room_type	mapped
total_price	total_price
VII. ⚡ REALTIME STRATEGY
1. Queue system (BẮT BUỘC)
Kafka / Redis Queue / Celery

👉 Không gọi OTA trực tiếp từ request

2. Retry logic
FAILED → retry 3 lần
3. Idempotency
same request → không tạo duplicate
VIII. 🔥 ADVANCED (2026)
1. Rate parity control
OTA không được rẻ hơn web
2. Channel restriction
Weekend → chỉ bán OTA
3. Smart fallback
OTA lỗi → retry background
IX. 🚨 Sai lầm chết người

❌ Không có mapping
→ sai room ngay

❌ Không có log
→ không debug được

❌ Không có queue
→ hệ thống lag chết

❌ Không có idempotency
→ duplicate booking

X. 🎯 Mapping với hệ thống của bạn
Bạn đã có:
Booking ✅
room_inventory_daily (vừa design) ✅
room_rates_daily ✅
Bạn cần thêm:

👉 OTA layer:

ota_channels
ota_room_mapping
ota_rate_mapping
ota_sync_log
ota_booking_raw
XI. 🧠 Kiến trúc tổng thể (chuẩn luôn)
Frontend
   ↓
PMS API (FastAPI)
   ↓
Service Layer
   ↓
Queue (Celery/Redis)
   ↓
OTA Sync Worker
   ↓
OTA APIs
XII. 🎯 Kết luận

👉 OTA Sync là thứ biến bạn thành:

❌ Phần mềm nội bộ
→
✅ Hệ thống kinh doanh phòng thật