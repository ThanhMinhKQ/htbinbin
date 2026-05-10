I. 🎯 Mục tiêu hệ thống

Quản lý tồn phòng theo thời gian (date-based):

Không phải chỉ là phòng đang trống hay đang ở
Mà là:
Ngày nào còn bao nhiêu phòng?
Có bị overbooking không?
Có khóa bán không?
Có room out-of-order không?

👉 Đây là lớp nằm giữa:

HotelRoom
Booking (OTA)
HotelStay
II. 🚨 Vấn đề DB hiện tại của bạn

Hiện bạn đang có:

HotelRoom
HotelStay
Booking

❌ Nhưng thiếu hoàn toàn layer INVENTORY theo ngày

👉 Đây là lỗi rất lớn:

Không biết ngày mai còn bao nhiêu phòng
Không kiểm soát OTA
Không support dynamic pricing
III. 🧠 Kiến trúc chuẩn (3 layer)
1. Physical Layer
HotelRoom → phòng thật
2. Logical Inventory Layer
room_inventory_daily → tồn theo ngày
3. Reservation Layer
Booking
HotelStay
IV. 🧱 DATABASE DESIGN
1. 📅 room_inventory_daily
room_inventory_daily
👉 Vai trò:

Snapshot tồn phòng theo từng ngày

| Field              | Type     | Ý nghĩa           |
| ------------------ | -------- | ----------------- |
| id                 | BIGINT   | PK                |
| branch_id          | FK       | Chi nhánh         |
| room_type_id       | FK       | Loại phòng        |
| date               | DATE     | Ngày              |
| total_rooms        | INT      | Tổng số phòng     |
| available_rooms    | INT      | Phòng còn bán     |
| reserved_rooms     | INT      | Đã giữ            |
| sold_rooms         | INT      | Đã check-in       |
| out_of_order_rooms | INT      | Phòng hỏng        |
| overbooking_limit  | INT      | Cho phép overbook |
| created_at         | DATETIME |                   |

🔥 Unique constraint cực quan trọng
UNIQUE(branch_id, room_type_id, date)
👉 Logic tính
available_rooms =
    total_rooms
    - reserved_rooms
    - sold_rooms
    - out_of_order_rooms
2. 🚫 room_block (Out of Order / Maintenance)
room_blocks
Field	Type
id	BIGINT
room_id	FK
start_date	DATE
end_date	DATE
reason	TEXT
status	ACTIVE / DONE

👉 Khi block:
→ update out_of_order_rooms

3. 🔒 room_inventory_hold (giữ phòng tạm)
room_inventory_hold
Field	Type
id	BIGINT
booking_id	FK
room_type_id	FK
date	DATE
quantity	INT
expire_at	DATETIME

👉 dùng cho:

khách đặt nhưng chưa thanh toán
giữ phòng OTA
4. 🔗 room_inventory_log (audit)
room_inventory_log
Field	Type
id	BIGINT
date	DATE
room_type_id	FK
change_type	ENUM
delta	INT
ref_type	booking / stay / manual
ref_id	BIGINT
created_at	DATETIME
V. 🔄 FLOW NGHIỆP VỤ
1. 🛎️ Khi có Booking (OTA / trực tiếp)
Booking → HOLD → CONFIRM
Step 1: HOLD
insert vào room_inventory_hold
giảm available_rooms
Step 2: CONFIRM
move hold → reserved
update reserved_rooms
2. 🏨 Khi Check-in
reserved → sold
giảm reserved_rooms
tăng sold_rooms
3. 🚪 Khi Check-out
không trả lại inventory (đã consume)
4. ❌ Cancel
reserved → available
5. 🔧 Maintenance
available → out_of_order
VI. ⚡ JOB BACKGROUND (BẮT BUỘC)
1. 🕒 Cron: Generate inventory

Chạy mỗi ngày:

Generate next 365 days

👉 Tạo sẵn inventory

2. 🧹 Cron: Release HOLD
expire_at < now()

👉 trả lại phòng

3. 🔄 Sync OTA
push availability
pull booking
VII. 🔥 TÍNH NĂNG NÂNG CAO (2026)
1. Overbooking Control
overbooking_limit = 2

→ cho phép bán quá 2 phòng

2. Dynamic Pricing (gắn với inventory)
if available < 3:
    increase price +20%
3. Stop Sell
available_rooms = 0

→ khóa bán OTA

4. Channel Manager Ready
mapping:
room_type ↔ OTA room_type
realtime sync
VIII. 🧠 Mapping với DB của bạn
Bạn đã có:
HotelRoomType ✅
HotelRoom ✅
Booking ✅
HotelStay ✅
Bạn cần thêm:

👉 BẮT BUỘC:

room_inventory_daily
room_inventory_hold
room_blocks

👉 NÂNG CAO:

room_inventory_log
IX. 🚨 Sai lầm phổ biến (tránh ngay)

❌ Dùng HotelRoom để check availability
→ sai hoàn toàn

❌ Không lưu inventory theo ngày
→ không scale được OTA

❌ Không có HOLD
→ double booking ngay lập tức

❌ Không có audit log
→ không debug được

X. 🎯 Kết luận

Module này quyết định:

Bạn có làm OTA được không
Có scale multi-branch không
Có làm dynamic pricing không

👉 Nói thẳng:
Không có Room Inventory → không phải PMS, chỉ là phần mềm quản lý phòng đơn giản