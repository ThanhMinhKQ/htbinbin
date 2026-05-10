---
name: pms-booking
description: "Quản lý đặt phòng PMS: reservation, room inventory, availability, OTA booking, walk-in, direct booking, hold room, overbooking, chuyển chi nhánh, calendar, timeline, no-show, cancel. Dùng khi làm việc với đặt phòng, booking, reservation, inventory, availability, hold, block, calendar, timeline, arrivals, departures. Cập nhật: 2026-05-07"
---

# PMS Booking - Reservation Management System

## Tài liệu tham khảo

- [PMS_SKILL.md](PMS_SKILL.md) - Kiến trúc PMS tổng quan, Pricing Engine, OTA Integration
- [CRM_SKILL.md](CRM_SKILL.md) - Guest CRM, Membership, Timeline
- [4_ROOM INVENTORY_MODULE_SPEC.md](4_ROOM%20INVENTORY_MODULE_SPEC.md) - Room Inventory spec gốc
- [5_PRICING ENGINE_MODULE_SPEC.md](5_PRICING%20ENGINE_MODULE_SPEC.md) - Pricing Engine spec
- [6_OTA_SYNC_MODULE_SPEC_2026.md](6_OTA_SYNC_MODULE_SPEC_2026.md) - OTA Sync spec

---

## Tổng quan Module

### Mục tiêu

Module Quản lý Đặt phòng là **trung tâm điều phối** (Reservation Hub) giữa tất cả các nguồn booking:
- OTA channels (Booking.com, Agoda, Traveloka, Go2Joy, Airbnb, Mytour)
- Walk-in (khách đến trực tiếp, lễ tân tạo)
- Website/Phone (khách đặt online hoặc gọi điện)
- Direct (nhân viên tạo thủ công)
- Điều phối chuyển booking giữa các chi nhánh khi khách đặt nhầm nơi
- Kiểm soát overbooking: cho phép tạo booking vượt tồn ở trạng thái chờ, chỉ xác nhận khi đủ tồn

### Kiến trúc 4 Layer

```
┌─────────────────────────────────────────────────────────────────┐
│                    BOOKING MANAGEMENT LAYERS                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Layer 1: PHYSICAL            → HotelRoom (phòng thật)         │
│  Layer 2: INVENTORY           → room_inventory_daily (tồn/ngày)│
│  Layer 3: RESERVATION         → Booking (đặt phòng unified)    │
│  Layer 4: OPERATION           → HotelStay (lưu trú thực tế)   │
│                                                                  │
│  Flow:  Booking → Inventory Hold → Confirm → Check-in → Stay  │
└─────────────────────────────────────────────────────────────────┘
```

### Luồng tổng quan

```
  OTA Email ──→ AI Parse ──→┐
  Walk-in ─────────────────→├──→ Booking (unified) ──→ Inventory Update
  Website ─────────────────→┤         │
  Phone ───────────────────→┘         ▼
                              Confirm → Assign Room → Check-in → HotelStay
                                                                    │
                                                              Check-out → CRM Hook
```

---

## Cấu trúc thư mục

```
app/
├── api/pms/
│   └── reservation_api.py          # Reservation API (30+ endpoints)
├── services/
│   ├── inventory_service.py        # Room inventory management
│   ├── booking_service.py          # Reservation Hub orchestration
│   └── ota_agent/                  # OTA email → booking (existing)
├── db/
│   └── models.py                   # +4 models mới, Booking mở rộng
├── templates/pms/
│   ├── reservation_dashboard.html  # Main reservation page
│   └── partials/reservation/
│       ├── stats_cards.html        # KPI cards row
│       ├── tab_all.html            # All bookings
│       ├── tab_today.html          # Today arrivals/departures
│       ├── tab_upcoming.html       # Future bookings
│       ├── tab_ota.html            # OTA bookings (embed)
│       ├── tab_calendar.html       # Availability calendar
│       ├── modal_create.html       # Create reservation
│       ├── modal_detail.html       # Booking detail
│       └── modal_assign.html       # Assign room
└── static/
    ├── js/pms/reservation_dashboard.js   # Alpine.js component
    └── css/reservation_dashboard.css     # Styles
```

---

## Database Models

### RoomInventoryDaily — Tồn phòng theo ngày (SOURCE OF TRUTH)

```python
RoomInventoryDaily:
    id: BIGINT (PK)
    branch_id: Integer (FK → branches)
    room_type_id: Integer (FK → hotel_room_types)
    date: DATE

    total_rooms: Integer              # Tổng phòng vật lý loại này
    available_rooms: Integer          # Còn bán được
    reserved_rooms: Integer           # Đã giữ (booking confirmed)
    sold_rooms: Integer               # Đã check-in (đang ở)
    out_of_order_rooms: Integer       # Hỏng / bảo trì
    overbooking_limit: Integer = 0    # Cho phép vượt bao nhiêu

    base_price: NUMERIC(15,2)        # Giá cơ sở ngày đó

    created_at: DateTime
    updated_at: DateTime

    # UNIQUE(branch_id, room_type_id, date)
    # INDEX(branch_id, date)

    # Logic tính:
    # available = total - reserved - sold - ooo + overbooking_limit
    # Nếu available <= 0 → STOP SELL
```

### RoomBlock — Khóa phòng (Maintenance/OOO)

```python
RoomBlock:
    id: BIGINT (PK)
    room_id: Integer (FK → hotel_rooms)
    branch_id: Integer (FK → branches)

    start_date: DATE
    end_date: DATE
    reason: TEXT                      # "Sửa điều hòa", "Sơn phòng"
    status: String(20)               # ACTIVE | DONE | CANCELLED

    created_by: BIGINT (FK → users)
    created_at: DateTime
    updated_at: DateTime
```

### RoomInventoryHold — Giữ phòng tạm

```python
RoomInventoryHold:
    id: BIGINT (PK)
    booking_id: BIGINT (FK → bookings, nullable)
    branch_id: Integer (FK → branches)
    room_type_id: Integer (FK → hotel_room_types)

    date: DATE                        # Ngày giữ
    quantity: Integer = 1
    hold_type: String(20)             # WALK_IN | OTA | WEBSITE | MANUAL
    expire_at: DateTime               # Hết hạn → tự release
    released: Boolean = False

    created_at: DateTime
```

### RoomInventoryLog — Audit trail

```python
RoomInventoryLog:
    id: BIGINT (PK)
    branch_id: Integer (FK → branches)
    room_type_id: Integer (FK → hotel_room_types)
    date: DATE

    change_type: String(30)           # BOOKING_CONFIRM | CHECKIN | CHECKOUT |
                                      # CANCEL | BLOCK | UNBLOCK | HOLD | RELEASE | MANUAL
    delta: Integer                    # +1 hoặc -1
    field_changed: String(20)         # reserved_rooms | sold_rooms | out_of_order_rooms
    ref_type: String(20)             # booking | stay | block | hold | manual
    ref_id: BIGINT
    note: TEXT

    created_by: BIGINT (FK → users, nullable)
    created_at: DateTime
```

### Booking (MỞ RỘNG) — Unified Reservation

```python
# Fields MỚI thêm vào Booking model hiện tại:
Booking (extended):
    # === EXISTING FIELDS (giữ nguyên) ===
    id, booking_source, external_id, guest_name, guest_phone, checkin_code,
    check_in, check_out, room_type, num_guests, num_adults, num_children,
    total_price, currency, is_prepaid, payment_method, deposit_amount,
    status, branch_id, source_booking_id, guest_id, raw_data,
    created_at, updated_at, created_by, updated_by, version

    # === NEW FIELDS ===
    booking_type: String(20)          # OTA | WALK_IN | WEBSITE | PHONE | DIRECT
                                      # Default: OTA (backward compatible)

    reservation_status: String(20)    # PENDING | CONFIRMED | CHECKED_IN |
                                      # CHECKED_OUT | CANCELLED | NO_SHOW
                                      # Tách biệt với BookingStatus cũ

    assigned_room_id: Integer         # FK → hotel_rooms (nullable)
                                      # Phòng cụ thể được gán

    stay_id: BIGINT                   # FK → hotel_stays (nullable)
                                      # Link khi đã check-in

    estimated_arrival: TIME           # Giờ dự kiến đến (14:00, 20:00...)
    special_requests: TEXT            # Yêu cầu đặc biệt (từ raw_data)
    internal_notes: TEXT              # Ghi chú nội bộ (chỉ staff thấy)

    confirmed_at: DateTime            # Thời điểm xác nhận
    cancelled_at: DateTime            # Thời điểm hủy
    cancel_reason: TEXT               # Lý do hủy
    no_show_at: DateTime              # Thời điểm đánh no-show

    # === CROSS-BRANCH TRANSFER / OVERBOOKING METADATA ===
    # Không nhất thiết cần thêm cột riêng nếu raw_data đã đủ linh hoạt.
    # Các key raw_data bắt buộc khi phát sinh nghiệp vụ:
    raw_data.branch_transfer_history: list[dict]
    raw_data.original_branch_id: int
    raw_data.original_branch_name: string
    raw_data.transfer_reason: string
    raw_data.overbooking_requested: bool
    raw_data.overbooking_reason: string
    raw_data.waiting_for_inventory: bool
    raw_data.inventory_reserved: bool
```

---

## Booking Lifecycle (State Machine)

```
                    ┌──────────────────────────────────────────────┐
                    │           BOOKING LIFECYCLE                    │
                    ├──────────────────────────────────────────────┤
                    │                                                │
  OTA/Walk-in ─────→  PENDING ──confirm──→ CONFIRMED                │
                    │     │                     │                    │
                    │     │cancel          assign_room              │
                    │     ▼                     │                    │
                    │  CANCELLED           ┌────▼────┐              │
                    │                      │ ASSIGNED │              │
                    │                      └────┬────┘              │
                    │                      checkin│                  │
                    │                           ▼                    │
                    │                      CHECKED_IN → (HotelStay) │
                    │                           │                    │
                    │                      checkout│                │
                    │                           ▼                    │
                    │  NO_SHOW ←─no_show─ CHECKED_OUT               │
                    │                                                │
                    └──────────────────────────────────────────────┘

  Status transitions cho phép:
    PENDING    → CONFIRMED, CANCELLED
    CONFIRMED  → CHECKED_IN, CANCELLED, NO_SHOW
    CHECKED_IN → CHECKED_OUT
    (CANCELLED, CHECKED_OUT, NO_SHOW = terminal states)

  Quy tắc tồn phòng:
    PENDING    = chưa reserve tồn chính thức, được dùng cho booking chờ xác nhận / overbooking
    CONFIRMED  = đã reserve tồn chính thức, bắt buộc phải đủ availability tại thời điểm xác nhận
    CHECKED_IN = đã chuyển sang lưu trú thật, có assigned_room_id và HotelStay
```

### Mapping với BookingStatus cũ

| BookingStatus (cũ) | reservation_status (mới) |
|---------------------|--------------------------|
| CONFIRMED           | CONFIRMED                |
| CANCELLED           | CANCELLED                |
| COMPLETED           | CHECKED_OUT              |
| NO_SHOW             | NO_SHOW                  |

---

## Inventory Service Logic

### Flow: Khi Booking được tạo

```python
# 1. OTA booking (từ email AI)
def on_ota_booking_created(booking):
    if has_availability(booking.branch_id, booking.room_type_id, booking.dates):
        # Booking OTA đủ tồn → xác nhận và giữ tồn ngay
        booking.reservation_status = "CONFIRMED"
        reserve_inventory(booking)
    else:
        # Booking OTA vượt tồn / khách đặt nhầm chi nhánh → chỉ tạo hồ sơ chờ xử lý
        booking.reservation_status = "PENDING"
        booking.raw_data["overbooking_requested"] = True
        booking.raw_data["waiting_for_inventory"] = True
        # Không reserve inventory khi chưa đủ tồn

# 2. Walk-in / Direct booking
def on_manual_booking_created(booking):
    if booking.reservation_status == "CONFIRMED":
        reserve_inventory(booking)
    else:
        # PENDING có thể dùng cho giữ chờ xác nhận hoặc overbooking
        # Không tăng reserved_rooms cho tới khi confirm
        create_optional_hold(branch, room_type, dates, expire_minutes=15)

# 3. Confirm booking
def confirm_booking(booking):
    if booking.reservation_status != "PENDING":
        raise ValueError("Chỉ xác nhận booking đang chờ")
    if not has_availability(booking.branch_id, booking.room_type_id, booking.dates):
        raise ValueError("Không thể xác nhận vì tồn phòng không đủ")
    reserve_inventory(booking)
    booking.reservation_status = "CONFIRMED"
    booking.raw_data["waiting_for_inventory"] = False
    booking.raw_data["inventory_reserved"] = True
```

### Flow: Check-in

```python
def on_checkin(stay_id, booking_id=None):
    # reserved → sold (nếu có booking)
    if booking_id:
        for date in remaining_dates:
            inventory.reserved_rooms -= 1
            inventory.sold_rooms += 1
            log_change("CHECKIN", -1, "reserved_rooms")
            log_change("CHECKIN", +1, "sold_rooms")
    else:
        # Walk-in không có booking → chỉ tăng sold
        inventory.sold_rooms += 1
        inventory.available_rooms -= 1
```

### Flow: Cancel

```python
def on_booking_cancelled(booking_id):
    if booking.reservation_status != "CONFIRMED":
        # PENDING chưa reserve tồn nên không release inventory
        return
    for date in booking_dates:
        inventory.reserved_rooms -= 1
        inventory.available_rooms += 1
        log_change("CANCEL", -1, "reserved_rooms")
```

### Flow: Room Block (Maintenance)

```python
def create_block(room_id, start, end, reason):
    block = RoomBlock(room_id, start, end, reason, status="ACTIVE")
    room = get_room(room_id)
    for date in date_range(start, end):
        inventory = get_inventory(branch, room.room_type_id, date)
        inventory.out_of_order_rooms += 1
        inventory.available_rooms -= 1
```

### Available Rooms Formula

```python
available_rooms = (
    total_rooms
    - reserved_rooms
    - sold_rooms
    - out_of_order_rooms
    + overbooking_limit
)

# Nếu available_rooms <= 0 → STOP SELL cho ngày đó
# Nếu available_rooms < 3 → Dynamic pricing: +20%
```

### Flow: Chuyển booking giữa chi nhánh

Dùng khi khách đặt nhầm chi nhánh, khách muốn đổi địa điểm, hoặc OTA map sai branch.

```python
def transfer_booking_branch(booking, target_branch_id, target_room_type_id, reason, user_id):
    if booking.reservation_status in {"CHECKED_IN", "CHECKED_OUT", "CANCELLED", "NO_SHOW"}:
        raise ValueError("Không được chuyển chi nhánh booking đã nhận phòng hoặc đã kết thúc")

    old_branch_id = booking.branch_id
    old_room_type_id = booking.raw_data.get("room_type_id")
    was_confirmed = booking.reservation_status == "CONFIRMED"

    # 1. Nếu booking cũ đã reserve tồn, release tồn ở chi nhánh cũ trước.
    if was_confirmed:
        release_inventory(booking, old_branch_id, old_room_type_id)

    # 2. Cập nhật chi nhánh / hạng phòng đích.
    booking.branch_id = target_branch_id
    booking.room_type = get_room_type_name(target_room_type_id)
    booking.raw_data["room_type_id"] = target_room_type_id
    booking.assigned_room_id = None

    # 3. Ghi lịch sử chuyển chi nhánh để audit và để chi nhánh cũ có thể xem bản ghi nếu cần.
    booking.raw_data.setdefault("branch_transfer_history", []).append({
        "from_branch_id": old_branch_id,
        "to_branch_id": target_branch_id,
        "from_room_type_id": old_room_type_id,
        "to_room_type_id": target_room_type_id,
        "reason": reason,
        "user_id": user_id,
        "transferred_at": now_iso(),
    })

    # 4. Nếu chi nhánh mới đủ tồn thì giữ lại trạng thái CONFIRMED và reserve tồn mới.
    #    Nếu không đủ tồn thì hạ về PENDING, đánh dấu chờ tồn.
    if has_availability(target_branch_id, target_room_type_id, booking.dates):
        reserve_inventory(booking, target_branch_id, target_room_type_id)
        booking.reservation_status = "CONFIRMED" if was_confirmed else booking.reservation_status
        booking.raw_data["waiting_for_inventory"] = False
        booking.raw_data["inventory_reserved"] = was_confirmed
    else:
        booking.reservation_status = "PENDING"
        booking.raw_data["overbooking_requested"] = True
        booking.raw_data["waiting_for_inventory"] = True
        booking.raw_data["inventory_reserved"] = False
```

Quy tắc nghiệp vụ:
- Chỉ chuyển booking ở trạng thái `PENDING` hoặc `CONFIRMED`.
- Nếu đã gán phòng cụ thể (`assigned_room_id`) thì phải bỏ gán phòng khi chuyển chi nhánh.
- Nếu booking đã `CONFIRMED`, phải release tồn chi nhánh cũ trước khi reserve chi nhánh mới.
- Nếu chi nhánh mới không đủ tồn, booking vẫn được chuyển nhưng bắt buộc về `PENDING`.
- Không cho check-in booking `PENDING`; bắt buộc xác nhận khi đủ tồn trước.

### Flow: Overbooking chờ xác nhận

Overbooking trong module này không có nghĩa là bán vượt tồn ngay. Hệ thống chỉ cho phép **tạo hồ sơ booking vượt tồn ở trạng thái `PENDING`**, để nhân viên xử lý sau.

```python
def create_overbooking_request(payload, user_id):
    if has_availability(payload.branch_id, payload.room_type_id, payload.dates):
        return create_reservation(payload | {"reservation_status": "CONFIRMED"}, user_id)

    if not payload.get("allow_waitlist"):
        raise ValueError("Tồn phòng không đủ")

    booking = create_reservation(payload | {"reservation_status": "PENDING"}, user_id)
    booking.raw_data["overbooking_requested"] = True
    booking.raw_data["overbooking_reason"] = payload.get("overbooking_reason")
    booking.raw_data["waiting_for_inventory"] = True
    booking.raw_data["inventory_reserved"] = False
    return booking
```

Quy tắc xác nhận:
- `PENDING + waiting_for_inventory=True` chỉ được chuyển sang `CONFIRMED` khi mọi ngày trong khoảng lưu trú có `available_rooms >= quantity`.
- Nút `Xác nhận` phải gọi availability check ở backend ngay tại thời điểm bấm, không tin dữ liệu calendar cũ trên frontend.
- Khi xác nhận thành công mới tăng `reserved_rooms`.
- Nếu vẫn thiếu tồn, API trả lỗi rõ: `Không thể xác nhận vì tồn phòng không đủ`.
- Booking chờ overbooking phải hiển thị badge `Chờ tồn` / `Overbook pending` trong Reservation Hub.
- Không được gán phòng, check-in, hoặc chuyển thành HotelStay khi booking còn `PENDING`.

---

## API Endpoints

### Reservation CRUD

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/pms/reservations` | GET | List bookings (filters, pagination, sorting) |
| `/api/pms/reservations` | POST | Create new reservation |
| `/api/pms/reservations/{id}` | GET | Get reservation detail |
| `/api/pms/reservations/{id}` | PUT | Update reservation |
| `/api/pms/reservations/{id}/confirm` | POST | PENDING → CONFIRMED |
| `/api/pms/reservations/{id}/mark-pending` | POST | CONFIRMED → PENDING, release tồn đã giữ |
| `/api/pms/reservations/{id}/transfer-branch` | POST | Chuyển booking sang chi nhánh/hạng phòng khác |
| `/api/pms/reservations/{id}/assign-room` | POST | Gán phòng cụ thể |
| `/api/pms/reservations/{id}/checkin` | POST | Convert to HotelStay |
| `/api/pms/reservations/{id}/cancel` | POST | Cancel with reason |
| `/api/pms/reservations/{id}/no-show` | POST | Mark no-show |

### Reservation Queries

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/pms/reservations/today-arrivals` | GET | Arrivals hôm nay |
| `/api/pms/reservations/today-departures` | GET | Departures hôm nay |
| `/api/pms/reservations/in-house` | GET | Đang lưu trú |
| `/api/pms/reservations/stats` | GET | Dashboard KPIs |
| `/api/pms/reservations/search` | GET | Tìm kiếm nâng cao |

### Room Inventory

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/pms/inventory/availability` | GET | Check availability (date range) |
| `/api/pms/inventory/availability/confirmable` | GET | Kiểm tra booking PENDING có đủ tồn để xác nhận không |
| `/api/pms/inventory/calendar` | GET | Calendar data (30 ngày) |
| `/api/pms/inventory/timeline` | GET | Room timeline (Gantt data) |
| `/api/pms/inventory/generate` | POST | Generate inventory days |
| `/api/pms/inventory/blocks` | GET | List room blocks |
| `/api/pms/inventory/blocks` | POST | Create room block |
| `/api/pms/inventory/blocks/{id}` | PUT | Update/release block |

### Payload: Tạo booking chờ xác nhận khi thiếu tồn

```json
{
  "booking_type": "DIRECT",
  "booking_source": "Direct",
  "branch_id": 2,
  "room_type_id": 5,
  "check_in": "2026-05-10",
  "check_out": "2026-05-11",
  "guest_name": "Nguyễn Văn A",
  "reservation_status": "PENDING",
  "allow_waitlist": true,
  "overbooking_reason": "Khách muốn giữ chỗ, đang chờ phòng trống"
}
```

Backend phải xử lý:
- Nếu đủ tồn và payload yêu cầu `CONFIRMED`: reserve inventory ngay.
- Nếu thiếu tồn và `allow_waitlist=true`: tạo booking `PENDING`, không reserve inventory.
- Nếu thiếu tồn và không có `allow_waitlist`: trả lỗi `400`.

### Payload: Chuyển booking sang chi nhánh khác

```json
{
  "target_branch_id": 7,
  "target_room_type_id": 18,
  "reason": "Khách đặt nhầm chi nhánh",
  "keep_confirmed_if_available": true
}
```

Backend phải xử lý:
- Validate booking chưa ở trạng thái terminal và chưa check-in.
- Validate `target_room_type_id` thuộc `target_branch_id`.
- Nếu booking cũ đã `CONFIRMED`, release tồn ở chi nhánh cũ.
- Nếu chi nhánh mới đủ tồn và `keep_confirmed_if_available=true`, reserve tồn mới và giữ `CONFIRMED`.
- Nếu chi nhánh mới thiếu tồn, chuyển booking về `PENDING`, set `waiting_for_inventory=true`.
- Ghi `branch_transfer_history` trong `raw_data` và `RoomInventoryLog` cho release/reserve.

---

## Frontend: Reservation Dashboard

### Page Layout

```
reservation_dashboard.html (Alpine.js x-data="reservationHub()")
├── stats_cards.html        # 5 KPI cards (sticky top)
├── tab_all.html            # Tất cả bookings (table + filters)
├── tab_today.html          # Arrivals + Departures hôm nay
├── tab_upcoming.html       # Bookings sắp tới (7 ngày)
├── tab_ota.html            # OTA bookings (embed OTA dashboard logic)
├── tab_calendar.html       # Availability calendar + Room timeline
├── modal_create.html       # Tạo reservation mới
├── modal_detail.html       # Chi tiết booking + quick actions
└── modal_assign.html       # Gán phòng cụ thể
```

### Alpine.js Component

```javascript
function reservationHub() {
  return {
    activeTab: 'today',
    loading: true,

    // Stats
    stats: { today: 0, arrivals: 0, departures: 0, inHouse: 0, noShow: 0 },

    // Tab data (lazy loaded)
    allBookings: [], allLoading: false,
    todayArrivals: [], todayDepartures: [],
    upcoming: [], upcomingLoading: false,
    otaBookings: [], otaLoading: false,

    // Calendar
    calendarData: [], calendarMonth: null,

    // Filters
    filters: { status: '', source: '', dateFrom: '', dateTo: '', search: '' },

    // Modals
    showCreateModal: false,
    showDetailModal: false,
    selectedBooking: null,

    async init() {
      await this.loadStats();
      await this.loadToday();
    },

    async loadStats() { /* GET /reservations/stats */ },
    async loadToday() { /* GET /today-arrivals + /today-departures */ },
    async loadAll() { /* GET /reservations?filters */ },
    async loadUpcoming() { /* GET /reservations?check_in_from=today */ },
    async loadOTA() { /* GET /api/ota/bookings */ },
    async loadCalendar(month) { /* GET /inventory/calendar */ },

    // Actions
    async confirmBooking(id) { /* POST /confirm */ },
    async markPending(id) { /* POST /mark-pending */ },
    async transferBranch(id, payload) { /* POST /transfer-branch */ },
    async checkConfirmable(id) { /* GET /inventory/availability/confirmable */ },
    async assignRoom(id, roomId) { /* POST /assign-room */ },
    async convertToCheckin(id) { /* POST /checkin */ },
    async cancelBooking(id, reason) { /* POST /cancel */ },
    async markNoShow(id) { /* POST /no-show */ },

    // Create
    async createReservation(data) { /* POST /reservations */ },

    // Helpers
    fmtMoney(v) { return Number(v).toLocaleString('vi-VN') + 'đ'; },
    fmtDate(d) { /* DD/MM/YYYY */ },
    sourceIcon(src) { /* 🏨 Booking.com, 🟠 Agoda, 🚶 Walk-in */ },
    statusBadge(s) { /* Color-coded badge */ },
  }
}
```

### UI: Chuyển chi nhánh booking

Chi tiết booking cần có action `Chuyển chi nhánh` cho booking `PENDING` hoặc `CONFIRMED`.

Modal chuyển chi nhánh gồm:
- Chi nhánh hiện tại, hạng phòng hiện tại, trạng thái giữ tồn hiện tại.
- Dropdown chi nhánh đích.
- Dropdown hạng phòng thuộc chi nhánh đích.
- Lịch/tóm tắt availability của chi nhánh đích trong khoảng check-in/check-out.
- Lý do chuyển, bắt buộc nhập.
- Checkbox `Giữ xác nhận nếu chi nhánh mới đủ tồn`.

Hành vi UI:
- Nếu chi nhánh mới đủ tồn: hiển thị trạng thái `Có thể chuyển và giữ CONFIRMED`.
- Nếu thiếu tồn: hiển thị cảnh báo `Sẽ chuyển sang Chờ xác nhận, chưa giữ tồn`.
- Sau khi chuyển thành công, refresh danh sách booking, stats, calendar và detail modal.
- Nếu booking cũ đã có `assigned_room_id`, UI phải báo phòng gán sẽ bị bỏ khi chuyển chi nhánh.

### UI: Overbooking chờ xác nhận

Khi tạo/sửa booking mà availability không đủ:
- Không cho tạo `CONFIRMED`.
- Hiển thị lựa chọn `Tạo chờ xác nhận`.
- Bắt buộc nhập lý do overbooking/chờ tồn.
- Booking được tạo với badge `Chờ tồn`.

Các action bị khóa khi booking `PENDING`:
- `Gán phòng`.
- `Nhận phòng`.
- `In xác nhận nhận phòng` nếu tài liệu thể hiện booking đã chắc chắn.

Action được phép:
- `Xác nhận` nếu backend báo đủ tồn.
- `Chuyển chi nhánh`.
- `Hủy`.
- `Sửa thông tin`.

### CSS Design System

```css
:root {
  --res-bg: #f8fafc;
  --res-surface: #ffffff;
  --res-text: #0f172a;
  --res-accent: #0ea5e9;        /* Sky blue — booking theme */
  --res-success: #10b981;
  --res-warning: #f59e0b;
  --res-danger: #ef4444;
  --res-info: #6366f1;
  --res-border: #e2e8f0;
  --res-radius: 12px;
}

html.dark {
  --res-bg: #0a0a0f;
  --res-surface: #15151d;
  --res-text: #e2e8f0;
  --res-border: #1e293b;
}
```

### Group Booking Deposit Allocation

Khi tạo đặt phòng nhóm, Step 3 (Thanh toán / tiền cọc) phải cho người dùng chọn cách ghi nhận tiền cọc:

| Cơ chế | Mục đích | Hành vi |
|--------|----------|---------|
| Chia cọc theo phòng | Khi khách muốn mỗi phòng có phần cọc riêng | Tổng tiền cọc được phân bổ xuống từng phòng trong nhóm, mặc định chia đều nhưng cho phép chỉnh từng dòng |
| Cọc vào một phòng | Khi một khách đại diện hoặc một phòng đứng tên thanh toán | Toàn bộ `deposit_amount` được ghi vào booking/phòng được chọn, các phòng còn lại cọc = 0 |

Yêu cầu UI ở Step 3:
- Hiển thị toggle/radio: `Chia cọc theo phòng` hoặc `Cọc tất cả vào một phòng`.
- Nếu chọn chia cọc: hiển thị danh sách phòng/room line với ô tiền cọc từng phòng; tổng các dòng phải bằng tổng tiền cọc nhóm.
- Nếu chọn cọc vào một phòng: hiển thị dropdown chọn phòng nhận cọc; hệ thống tự đặt toàn bộ cọc vào phòng đó.
- Luôn hiển thị tổng tiền cọc nhóm, tổng đã phân bổ, và cảnh báo nếu lệch.
- Khi check-in từng phòng trong nhóm, tiền cọc đi theo đúng room line/booking con đã được phân bổ.

---

## Background Jobs (APScheduler)

### 1. Generate Daily Inventory — Cron 01:00 AM

```python
def generate_daily_inventory():
    """Tạo sẵn inventory cho 365 ngày tới."""
    for branch in all_branches:
        for room_type in branch.room_types:
            total = count_active_rooms(branch, room_type)
            for date in next_365_days:
                get_or_create(branch, room_type, date, total_rooms=total)
```

### 2. Release Expired Holds — Interval 5 phút

```python
def release_expired_holds():
    """Trả lại phòng từ hold hết hạn."""
    expired = query(RoomInventoryHold).filter(
        expire_at < now(), released == False
    ).all()
    for hold in expired:
        hold.released = True
        # Không cần update inventory vì hold chưa thành reserved
```

### 3. Auto No-Show — Cron 18:00

```python
def auto_no_show():
    """Đánh no-show cho booking check-in hôm nay mà chưa đến."""
    bookings = query(Booking).filter(
        check_in == today(),
        reservation_status == "CONFIRMED",
        stay_id == None  # Chưa check-in
    ).all()
    for b in bookings:
        b.reservation_status = "NO_SHOW"
        b.no_show_at = now()
        inventory_service.on_booking_cancelled(b.id)  # Trả lại phòng
```

---

## Tích hợp với Modules hiện tại

### → PMS Check-in

```python
# Khi check-in từ booking:
# 1. Chỉ cho check-in booking reservation_status == "CONFIRMED"
# 2. Tìm booking matching (guest_name + check_in + branch)
# 3. Validate assigned_room_id thuộc booking.branch_id
# 4. Gán stay_id vào booking
# 5. Update reservation_status = "CHECKED_IN"
# 6. Update inventory: reserved → sold
# 7. Log GuestActivity: BOOKING_CHECKIN
```

### → PMS Check-out

```python
# Khi check-out:
# 1. Tìm booking có stay_id matching
# 2. Update reservation_status = "CHECKED_OUT"
# 3. Update inventory: sold -= 1
# 4. CRM hooks (on_checkout_complete) chạy bình thường
```

### → OTA Agent

```python
# Khi AI parse email tạo booking:
# 1. Booking được tạo với booking_type = "OTA"
# 2. Nếu đủ tồn: reservation_status = "CONFIRMED", Inventory reserved += 1
# 3. Nếu thiếu tồn / map nhầm chi nhánh: reservation_status = "PENDING", waiting_for_inventory = True
# 4. Dashboard tự refresh và hiển thị badge Chờ tồn

# Khi OTA cancel:
# 1. reservation_status = "CANCELLED"
# 2. Nếu booking đã reserve tồn thì Inventory reserved -= 1
```

### → CRM Guest

```python
# Khi tạo booking:
# 1. Tìm/tạo Guest từ guest_name + phone
# 2. Link booking.guest_id
# 3. Log GuestActivity: BOOKING_CREATED

# Khi cancel:
# Log GuestActivity: BOOKING_CANCELLED
```

### → Pricing Engine

```python
# Khi tạo/preview booking:
# 1. Gọi calculate_full_charge() preview giá
# 2. Kết hợp với inventory availability check
# 3. Dynamic pricing: if available < 3 → +20%
```

---

## Data Consistency Rules

1. **RoomInventoryDaily** = Source of truth cho availability
   - `available = total - reserved - sold - ooo + overbooking_limit`
   - Mọi thay đổi PHẢI ghi RoomInventoryLog

2. **Booking.reservation_status** là trạng thái chính
   - BookingStatus cũ (CONFIRMED/CANCELLED/COMPLETED/NO_SHOW) vẫn giữ cho backward compatible
   - reservation_status mới chi tiết hơn

3. **Hold chỉ tạm** — không ảnh hưởng reserved_rooms
   - Hold chỉ "đánh dấu" intent, chưa commit inventory
   - Khi confirm → release hold + tăng reserved

4. **Inventory log append-only** — không sửa, chỉ thêm

5. **Overbooking chờ xác nhận**
   - Không tạo `CONFIRMED` nếu availability thiếu.
   - Chỉ tạo `PENDING` với `raw_data.overbooking_requested=true`.
   - `PENDING` không tăng `reserved_rooms`, không gán phòng, không check-in.
   - Chỉ khi confirm thành công mới reserve tồn.

6. **Multi-branch**: Inventory tính per branch, per room_type, per date

7. **Chuyển chi nhánh phải cân bằng inventory**
   - Nếu booking cũ đã `CONFIRMED`: release tồn chi nhánh cũ trước.
   - Nếu chi nhánh mới đủ tồn: reserve tồn chi nhánh mới.
   - Nếu chi nhánh mới thiếu tồn: booking về `PENDING`, không reserve tồn.
   - Luôn ghi lịch sử chuyển trong `raw_data.branch_transfer_history`.

8. **Assigned room không được vượt branch**
   - `assigned_room_id.branch_id` phải bằng `booking.branch_id`.
   - Khi đổi `branch_id` hoặc `room_type_id`, phải clear `assigned_room_id`.

---

## Booking Sources & Icons

| Source | Icon | booking_type | Auto-confirm? |
|--------|------|-------------|---------------|
| Booking.com | 🔵 | OTA | ✅ Nếu đủ tồn |
| Agoda | 🟠 | OTA | ✅ Nếu đủ tồn |
| Traveloka | 🟢 | OTA | ✅ Nếu đủ tồn |
| Go2Joy | 🟣 | OTA | ✅ Nếu đủ tồn |
| Airbnb | 🔴 | OTA | ✅ Nếu đủ tồn |
| Mytour | 🟡 | OTA | ✅ Nếu đủ tồn |
| Website | 🌐 | WEBSITE | ❌ Need confirm |
| Walk-in | 🚶 | WALK_IN | ✅ Yes |
| Phone | 📞 | PHONE | ❌ Need confirm |
| Direct | 📋 | DIRECT | ❌ Need confirm |

---

## Common Tasks

### Tạo reservation thủ công

```python
from app.services.booking_service import BookingService

svc = BookingService(db)
booking = svc.create_reservation({
    "booking_type": "WALK_IN",
    "guest_name": "Nguyễn Văn A",
    "phone": "0901234567",
    "check_in": "2026-05-02",
    "check_out": "2026-05-04",
    "room_type_id": 1,
    "branch_id": 2,
    "num_guests": 2,
})
```

### Check availability

```python
from app.services.inventory_service import InventoryService

svc = InventoryService(db)
avail = svc.get_availability(
    branch_id=2,
    check_in=date(2026, 5, 2),
    check_out=date(2026, 5, 4),
    room_type_id=1  # optional
)
# Returns: [{"room_type": "Superior", "available": 3, "price": 500000}, ...]
```

### Tạo booking chờ tồn khi overbook

```python
from app.services.booking_service import BookingService

svc = BookingService(db)
booking = svc.create_reservation({
    "booking_type": "DIRECT",
    "booking_source": "Direct",
    "guest_name": "Nguyễn Văn B",
    "phone": "0909999999",
    "check_in": "2026-05-10",
    "check_out": "2026-05-11",
    "room_type_id": 1,
    "branch_id": 2,
    "num_guests": 2,
    "reservation_status": "PENDING",
    "allow_waitlist": True,
    "overbooking_reason": "Khách muốn giữ chỗ khi chi nhánh đang hết phòng",
})
# Kết quả: Booking PENDING, không reserve inventory.
```

### Chuyển booking sang chi nhánh khác

```python
from app.services.booking_service import BookingService

svc = BookingService(db)
booking = svc.transfer_branch(
    booking_id=123,
    target_branch_id=7,
    target_room_type_id=18,
    reason="Khách đặt nhầm chi nhánh",
    user_id=current_user.id,
)
# Nếu chi nhánh mới đủ tồn: giữ CONFIRMED và reserve tồn mới.
# Nếu chi nhánh mới thiếu tồn: chuyển PENDING, waiting_for_inventory=True.
```

### Generate inventory cho branch mới

```python
from app.services.inventory_service import InventoryService

svc = InventoryService(db)
svc.generate_daily_inventory(branch_id=2, start_date=date.today(), days=365)
```

### Block phòng bảo trì

```python
from app.services.inventory_service import InventoryService

svc = InventoryService(db)
svc.create_block(
    room_id=101,
    start_date=date(2026, 5, 5),
    end_date=date(2026, 5, 7),
    reason="Sửa điều hòa",
    user_id=current_user.id,
)
```

---

## Xu hướng 2026 được áp dụng

### 1. AI-Powered Operations
- OTA email parsing bằng Gemini 2.5 Flash (đã có)
- Smart room assignment (gợi ý phòng dựa trên guest preferences từ CRM)
- Predictive no-show (dựa trên history)

### 2. Real-time Dashboard
- WebSocket/SSE cho live updates khi có booking mới
- Auto-refresh stats mỗi 30 giây
- Push notification khi OTA booking đến

### 3. Revenue Management
- Dynamic pricing dựa trên inventory level
- Rate parity monitoring (OTA vs Direct)
- Occupancy-based pricing rules

### 4. Guest Experience
- Self-service check-in từ booking confirmation
- QR code check-in (existing `qr_checkin.py`)
- Pre-arrival preferences collection

### 5. Unified Dashboard
- Single pane of glass cho tất cả reservations
- Cross-channel visibility
- Real-time inventory across all OTAs

---

## Liên kết với các module khác

### PMS Checkin (pms_checkin.py)
- Convert booking → HotelStay
- Update inventory: reserved → sold
- Link booking.stay_id

### PMS Checkout (pms_checkout.py)
- Update booking.reservation_status = CHECKED_OUT
- Update inventory: sold -= 1
- Trigger CRM hooks

### OTA Agent (ota_agent/)
- Tạo booking từ email AI
- Auto-confirm khi đủ tồn; nếu thiếu tồn thì tạo `PENDING` chờ xác nhận
- Cancel handling release tồn chỉ khi booking đã reserve inventory

### CRM (guest_crm_service.py)
- Link booking → Guest
- Log GuestActivity
- Loyalty points (khi checkout)

### Pricing Engine (pricing_engine.py)
- Preview pricing cho booking
- Dynamic pricing based on availability
- Rate plan support (future)

### Room Setup (pms_rooms.py)
- Room assignment
- Room condition tracking
- Block/maintenance management
