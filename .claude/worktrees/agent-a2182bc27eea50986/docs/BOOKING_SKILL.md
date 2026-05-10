---
name: pms-booking
description: "Quản lý đặt phòng PMS: reservation, room inventory, availability, OTA booking, walk-in, direct booking, hold room, overbooking, calendar, timeline, no-show, cancel. Dùng khi làm việc với đặt phòng, booking, reservation, inventory, availability, hold, block, calendar, timeline, arrivals, departures. Cập nhật: 2026-05-01"
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
    # Booking từ OTA luôn CONFIRMED
    for date in date_range(booking.check_in, booking.check_out):
        inventory = get_or_create_inventory(branch, room_type, date)
        inventory.reserved_rooms += 1
        inventory.available_rooms -= 1
        log_change("BOOKING_CONFIRM", +1, "reserved_rooms", booking.id)

# 2. Walk-in / Direct booking
def on_manual_booking_created(booking):
    # Tạo HOLD trước, confirm sau
    hold = create_hold(branch, room_type, dates, "WALK_IN", expire_minutes=15)
    # Khi confirm:
    release_hold(hold.id)
    for date in dates:
        inventory.reserved_rooms += 1
        inventory.available_rooms -= 1
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
| `/api/pms/inventory/calendar` | GET | Calendar data (30 ngày) |
| `/api/pms/inventory/timeline` | GET | Room timeline (Gantt data) |
| `/api/pms/inventory/generate` | POST | Generate inventory days |
| `/api/pms/inventory/blocks` | GET | List room blocks |
| `/api/pms/inventory/blocks` | POST | Create room block |
| `/api/pms/inventory/blocks/{id}` | PUT | Update/release block |

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
# 1. Tìm booking matching (guest_name + check_in + branch)
# 2. Gán stay_id vào booking
# 3. Update reservation_status = "CHECKED_IN"
# 4. Update inventory: reserved → sold
# 5. Log GuestActivity: BOOKING_CHECKIN
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
# 2. reservation_status = "CONFIRMED" (OTA luôn confirmed)
# 3. Inventory updated: reserved += 1
# 4. Dashboard tự refresh

# Khi OTA cancel:
# 1. reservation_status = "CANCELLED"
# 2. Inventory: reserved -= 1
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

5. **Overbooking**: available có thể < 0 nếu overbooking_limit > 0
   - Alert khi available < 0

6. **Multi-branch**: Inventory tính per branch, per room_type, per date

---

## Booking Sources & Icons

| Source | Icon | booking_type | Auto-confirm? |
|--------|------|-------------|---------------|
| Booking.com | 🔵 | OTA | ✅ Yes |
| Agoda | 🟠 | OTA | ✅ Yes |
| Traveloka | 🟢 | OTA | ✅ Yes |
| Go2Joy | 🟣 | OTA | ✅ Yes |
| Airbnb | 🔴 | OTA | ✅ Yes |
| Mytour | 🟡 | OTA | ✅ Yes |
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
- Auto-confirm + inventory update
- Cancel handling

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
