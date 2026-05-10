---
name: pms-crm
description: "Quản lý CRM khách hàng PMS: hồ sơ guest, membership tiers (BASIC→VIP), loyalty points, lịch sử lưu trú, thống kê, timeline activities, địa chỉ địa lý, dịch vụ, thanh toán. Dùng khi làm việc với CRM, guest, khách hàng, thành viên, membership, tier, điểm thưởng, VIP, Silver, Gold, Platinum, checkout, checkin, Blacklist, Debt. Cập nhật: 2026-05-01"
---

# PMS CRM - Guest Relationship Management System

## Tổng quan dự án

### Bin Bin Hotel Management System (PMS)

**Tech Stack:**
- Backend: FastAPI (Python 3.14+)
- Database: PostgreSQL (Supabase) via SQLAlchemy
- Frontend: Jinja2 Templates + Alpine.js
- Session: Starlette SessionMiddleware
- Scheduler: APScheduler

### Cấu trúc thư mục chính

```
app/
├── main.py                          # FastAPI entry point, router registration
├── api/pms/
│   ├── guest_crm_api.py              # CRM API (30+ endpoints)
│   ├── guest_activity.py            # Timeline/activity logging helpers
│   ├── pms_checkin.py               # Check-in flow
│   ├── pms_checkout.py              # Check-out flow (atomic)
│   ├── pms_pages.py                 # Page routes (HTML)
│   ├── folio_api.py                 # Billing/folio management
│   ├── pms_stays.py                 # Hotel stays management
│   └── pms_helpers.py               # Shared helpers (_require_login, _active_branch)
├── services/
│   ├── guest_crm_service.py          # CRM core logic (tier, points, membership)
│   ├── guest_crm_integration.py      # Checkout hooks (on_checkout_complete)
│   ├── checkout_service.py           # Checkout atomic operations
│   ├── folio_service.py             # Folio financial operations
│   └── pricing_engine.py            # Time-Slicing pricing engine
├── db/
│   ├── models.py                    # All SQLAlchemy models (Guest, Folio, etc.)
│   └── session.py                   # DB session management
├── static/js/pms/
│   ├── crm_guest_detail.js          # Alpine.js guest detail component
│   ├── pms_checkin.js              # Check-in UI
│   ├── pms_checkout.js             # Check-out UI
│   ├── pms_common.js               # Shared utilities
│   └── ag_search.js                # Guest search
├── static/css/
│   └── crm_guest_detail.css         # CRM guest detail styles
└── templates/pms/
    ├── crm_guest_detail.html        # Guest detail page
    ├── crm_dashboard.html          # CRM dashboard
    └── partials/crm_guest_detail/  # Tab components
        ├── header_tabs.html
        ├── sidebar.html
        ├── skeleton.html
        ├── tab_overview.html
        ├── tab_stays.html
        ├── tab_services.html
        ├── tab_payments.html
        └── tab_coguests.html
```

---

## Database Models (CRM Core)

### Guest - Master Customer Record

```python
Guest:
    id: BIGINT (PK)
    full_name: String(255)                    # Họ tên đầy đủ
    normalized_name: String(255)               # Tên không dấu, lowercase (search)
    phone: String(20)                        # SĐT (indexed)
    email: String(255)                        # Email (indexed)
    cccd: String(20)                         # CCCD/CMND/Passport (indexed, unique)
    date_of_birth: Date                      # Ngày sinh
    gender: String(10)                       # Nam/Nữ/Khác
    nationality: String(100)                  # Quốc tịch
    id_expire: Date                          # Ngày hết hạn CCCD
    default_address: Text                     # Địa chỉ mặc định
    first_seen_at: DateTime                  # Lần đầu tiên ghé thăm
    last_seen_at: DateTime                   # Lần cuối ghé thăm
    total_stays: Integer                     # Tổng số lần lưu trú
    total_spent: NUMERIC(15,2)               # Tổng chi tiêu
    is_blacklisted: Boolean                  # Cờ blacklist
    tags: JSONB                              # ['VIP', 'OTA', 'SILVER', 'GOLD', 'BLACKLIST']
    deleted_at: DateTime                    # Soft delete
    created_at: DateTime
    updated_at: DateTime

    # Relationships
    identities: GuestIdentity[]               # Định danh (phone/email/cccd)
    profile: GuestProfile (1:1)              # Dữ liệu tổng hợp
    preferences: GuestPreference[]            # Sở thích
    interactions: GuestInteraction[]         # Tương tác
    activities: GuestActivity[]              # Timeline
    membership: GuestMembership (1:1)       # Thành viên
    stay_summaries: GuestStaySummary[]      # Lịch sử lưu trú
    service_usages: GuestServiceUsage[]      # Dịch vụ đã dùng
    payment_summaries: GuestPaymentSummary[] # Thanh toán
    loyalty_transactions: GuestLoyaltyTransaction[]  # Điểm thưởng
    stay_mappings: GuestStayMapping[]        # Khách cùng ở
    hotel_guests: HotelGuest[]              # Liên kết stay
    bookings: Booking[]                      # Đặt phòng OTA
```

### GuestIdentity - Định danh khách (Chống trùng lặp)

```python
GuestIdentity:
    id: BIGINT (PK)
    guest_id: BIGINT (FK → Guest)
    identity_type: String(50)               # phone / email / cccd
    identity_value: String(255)             # Giá trị gốc
    normalized_value: String(255)            # Giá trị chuẩn hóa (lowercase, +84→0)
    is_primary: Boolean                     # Định danh chính
    created_at: DateTime

    # Unique constraint: (identity_type, normalized_value)
```

### GuestProfile - Dữ liệu tổng hợp

```python
GuestProfile:
    guest_id: BIGINT (PK, FK → Guest)
    avg_stay_duration: Float               # Số đêm TB
    favorite_room_type: String(100)        # Loại phòng hay ở nhất
    last_room_number: String(20)            # Phòng gần nhất
    preferred_payment: String(50)           # Thanh toán ưa thích
    risk_score: Float                       # Điểm rủi ro
    lifetime_value: NUMERIC(15,2)            # Giá trị trọn đời
    last_review_score: Float                 # Điểm review gần nhất
    updated_at: DateTime
```

### GuestPreference - Sở thích khách

```python
GuestPreference:
    id: BIGINT (PK)
    guest_id: BIGINT (FK → Guest)
    preference_type: String(50)             # smoking / bed / floor / pillow / breakfast
    preference_value: String(255)            # non-smoking / king-bed / high-floor
    source: String(20)                      # manual / AI / booking
    confidence_score: Float                  # 0-1
    updated_at: DateTime

    # Unique constraint: (guest_id, preference_type)
```

### GuestMembership - Bậc thành viên

```python
GuestMembership:
    id: BIGINT (PK)
    guest_id: BIGINT (FK → Guest, unique)
    tier: Enum                              # BASIC|SILVER|GOLD|PLATINUM|VIP
    tier_updated_at: DateTime               # Thời điểm lên tier gần nhất

    # Thống kê tích lũy
    total_stays: Integer
    total_nights: Integer
    total_spent: NUMERIC(15,2)
    total_deposit: NUMERIC(15,2)
    total_debt: NUMERIC(15,2)               # Tổng nợ chưa trả
    total_refund: NUMERIC(15,2)

    # Loyalty Points
    loyalty_points: Integer                  # Tổng điểm đã tích
    points_redeemed: Integer                # Điểm đã đổi
    points_balance: Integer                 # Số dư = loyalty_points - points_redeemed

    # Preferences
    favorite_branch_id: Integer (FK → Branch)
    favorite_room_type: String(100)
    preferred_payment_method: String(50)

    # Notes
    membership_note: Text

    updated_at: DateTime
    created_at: DateTime
```

### GuestStaySummary - Tổng hợp lưu trú (Source of Truth)

```python
GuestStaySummary:
    id: BIGINT (PK)
    guest_id: BIGINT (FK → Guest)
    stay_id: BIGINT (FK → HotelStay)
    branch_id: Integer (FK → Branch)

    # Room info
    room_number: String(20)
    room_type_name: String(100)
    floor: Integer

    # Dates
    check_in_at: DateTime
    check_out_at: DateTime
    nights: Integer                          # Số đêm ở

    # Pricing
    total_charge: NUMERIC(15,2)
    discount: NUMERIC(15,2)
    deposit: NUMERIC(15,2)
    deposit_type: String(50)
    deposit_paid: NUMERIC(15,2)
    final_amount: NUMERIC(15,2)             # Thực trả cuối cùng
    debt_amount: NUMERIC(15,2)              # Nợ

    # Stay type
    stay_type: String(20)                    # NIGHT / HOUR / DAY_USE / AUTO
    pricing_mode: String(20)                 # HOURLY / NIGHT / DAY_USE

    # Guest count
    guest_count: Integer                    # Số khách trong phòng

    # Status
    status: String(20)                       # ACTIVE / CHECKED_OUT / CANCELLED
    checkout_summary: String(50)              # normal / debt / refund
    debt_status: String(20)                  # none / pending / partial / settled

    # Payment methods
    payment_methods: JSONB                   # ["CASH", "CARD"]

    # Vehicle & Source
    vehicle: String(100)
    source: String(50)                       # pms / ota / walkin

    created_at: DateTime
    updated_at: DateTime

    # Unique constraint: (guest_id, stay_id)
```

### GuestActivity - Timeline hoạt động

```python
GuestActivity:
    id: BIGINT (PK)
    guest_id: BIGINT (FK → Guest)
    activity_type: String(50)               # CHECK_IN, CHECK_OUT, PAYMENT_RECEIVED...
    activity_group: String(50)               # stay, booking, payment, service, experience, system
    title: String(255)                       # Tiêu đề hiển thị
    description: Text                        # Mô tả chi tiết
    stay_id: BIGINT (FK → HotelStay, nullable)
    booking_id: BIGINT (FK → Booking, nullable)
    branch_id: Integer (FK → Branch, nullable)
    amount: NUMERIC(15,2)                    # Số tiền (nếu liên quan)
    currency: String(10)                      # VND
    actor_type: String(20)                   # system / user / guest
    actor_id: BIGINT (FK → User, nullable)   # user_id nếu có
    source: String(50)                       # pms / ota / api / ai / pos / wms
    extra_data: JSONB                         # Dữ liệu mở rộng
    created_at: DateTime                     # Indexed

    # Index: (guest_id, created_at)
```

### GuestServiceUsage - Theo dõi dịch vụ

```python
GuestServiceUsage:
    id: BIGINT (PK)
    guest_id: BIGINT (FK → Guest)
    stay_id: BIGINT (FK → HotelStay)
    branch_id: Integer (FK → Branch)

    # Service info
    service_category: String(50)             # MINIBAR / LAUNDRY / RESTAURANT / SPA / SERVICE / OTHER
    service_name: String(255)
    product_id: Integer (FK → Product, nullable)

    # Usage details
    quantity: NUMERIC(10,2)
    unit_price: NUMERIC(15,2)
    total_amount: NUMERIC(15,2)
    currency: String(10) = "VND"

    # Room & time
    room_number: String(20)
    used_at: DateTime

    # Reference
    folio_transaction_id: BIGINT (FK → FolioTransaction, nullable)
    stock_movement_id: BIGINT (FK → StockMovement, nullable)
    created_by: BIGINT (FK → User, nullable)

    created_at: DateTime
```

### GuestPaymentSummary - Tổng hợp thanh toán

```python
GuestPaymentSummary:
    id: BIGINT (PK)
    guest_id: BIGINT (FK → Guest)
    stay_id: BIGINT (FK → HotelStay)
    folio_id: BIGINT (FK → Folio, nullable)
    payment_id: BIGINT (FK → Payment, nullable)
    branch_id: Integer (FK → Branch)

    # Payment info
    amount: NUMERIC(15,2)
    payment_type: String(50)                 # DEPOSIT / PAYMENT / DEBT_PAYMENT / REFUND
    payment_method: String(50)               # CASH / CARD / BANK_TRANSFER / OTA / COMPANY
    transaction_code: String(100)

    # Room & Time
    room_number: String(20)
    paid_at: DateTime

    # Status
    is_voided: Boolean
    void_reason: Text
    notes: Text

    created_at: DateTime
```

### GuestLoyaltyTransaction - Lịch sử điểm thưởng

```python
GuestLoyaltyTransaction:
    id: BIGINT (PK)
    guest_id: BIGINT (FK → Guest)
    stay_id: BIGINT (FK → HotelStay, nullable)

    transaction_type: String(50)              # EARN / REDEEM / ADJUSTMENT
    points: Integer                          # Dương cho EARN, âm cho REDEEM
    reason: Text

    created_by: BIGINT (FK → User, nullable)
    created_at: DateTime
```

### GuestStayMapping - Bảng trung gian khách cùng ở

```python
GuestStayMapping:
    id: BIGINT (PK)
    guest_id: BIGINT (FK → Guest)
    stay_id: BIGINT (FK → HotelStay)
    branch_id: Integer (FK → Branch)

    room_number: String(20)
    check_in_at: DateTime
    check_out_at: DateTime
    is_primary: Boolean                      # Khách chính trong lần ở này

    created_at: DateTime

    # Unique constraint: (guest_id, stay_id)
```

---

## Membership Tiers

### Tier Thresholds & Benefits

| Tier     | Points   | Multiplier | Discount | Benefits |
|----------|----------|------------|----------|----------|
| **BASIC** | 0        | 1.0x       | 0%       | - |
| **SILVER** | 5,000   | 1.5x       | 5%       | early_checkin |
| **GOLD**  | 15,000  | 2.0x       | 10%      | early_checkin, late_checkout, priority |
| **PLATINUM** | 40,000 | 3.0x      | 15%      | + free_upgrade |
| **VIP**   | 100,000 | 5.0x       | 20%      | + dedicated_manager |

### Points Formula

```python
# 1. final_amount = total_charge - discount
# 2. Chia đều khi nhiều khách
split_amount = final_amount / guest_count

# 3. Tính base points
base_points = floor(split_amount / 1000)  # 1 điểm / 1000đ

# 4. Áp dụng tier multiplier
earned_points = floor(base_points * tier_multiplier)
```

### Tier Journey Visualization

Frontend hiển thị tier journey với:
- 5 bậc: BASIC → SILVER → GOLD → PLATINUM → VIP
- Progress bar cho bậc hiện tại
- Next tier info với số điểm còn thiếu
- Icon và gradient theo tier

---

## Luồng Checkout (CRM Integration)

```
User clicks "Checkout"
        │
        ▼
pms_checkout.py → execute_checkout (atomic)
        │
        ▼
guest_crm_integration.py → on_checkout_complete(db, stay_id, folio_id, user_id)
        │
        ├── Tạo GuestStayMapping (tất cả khách trong stay)
        ├── Tạo GuestStaySummary
        ├── Tạo GuestServiceUsage (từ FolioTransaction MINIBAR/SERVICE)
        ├── Tạo GuestPaymentSummary (từ Payment)
        ├── Cập nhật membership (tier & points)
        └── Log GuestActivity (CHECK_OUT)
```

### Chi tiết on_checkout_complete

```python
def on_checkout_complete(db, stay_id, folio_id, user_id):
    # 1. Tạo GuestStayMapping cho tất cả guests
    for guest_id in guest_ids:
        GuestStayMapping(guest_id, stay_id, ...)
    
    # 2. Với mỗi guest:
    # 2a. create_stay_summary() - Tổng hợp lưu trú
    # 2b. _create_service_usages() - Từ FolioTransaction
    # 2c. _create_payment_summaries() - Từ Payment
    # 2d. _update_membership_on_checkout() - Cập nhật tier/points
    
    return results
```

---

## API Endpoints

### Guest Search & Profile

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/pms/crm/guests/search` | GET | Tìm khách (tên, CCCD, SĐT, email) |
| `/api/pms/crm/guests/{id}` | GET | Chi tiết khách đầy đủ |
| `/api/pms/crm/guests/{id}/profile` | GET | Profile tóm tắt + tier journey |
| `/api/pms/crm/guests/{id}/co-guests` | GET | Khách cùng ở |

### Stays & History

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/pms/crm/guests/{id}/stays` | GET | Lịch sử lưu trú (phân trang) |
| `/api/pms/crm/guests/{id}/stays/{stay_id}/detail` | GET | Chi tiết 1 lần lưu trú |
| `/api/pms/crm/guests/{id}/services` | GET | Lịch sử dịch vụ |
| `/api/pms/crm/guests/{id}/payments` | GET | Lịch sử thanh toán |
| `/api/pms/crm/guests/{id}/timeline` | GET | Timeline đầy đủ |

### Membership & Analytics

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/pms/crm/guests/{id}/membership` | GET | Thông tin thành viên |
| `/api/pms/memberships/tiers` | GET | Danh sách tiers & benefits |
| `/api/pms/crm/guests/tier/{tier}` | GET | Tìm khách theo tier |
| `/api/pms/crm/stats` | GET | Thống kê CRM dashboard |
| `/api/pms/crm/stats/overview` | GET | Thống kê tổng quan |
| `/api/pms/crm/admin/rebuild-memberships` | POST | Rebuild toàn bộ tier |

### Blacklist Management

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/pms/crm/guests/{id}/blacklist` | PATCH | Đánh dấu/gỡ blacklist |

---

## Activity Types (Timeline)

### STAY Group
- `CHECK_IN`, `CHECK_OUT`, `ROOM_CHANGE`, `EXTEND_STAY`
- `EARLY_CHECKIN`, `LATE_CHECKOUT`, `GUEST_ADDED`, `GUEST_EDITED`

### BOOKING Group
- `BOOKING_CREATED`, `BOOKING_MODIFIED`, `BOOKING_CANCELLED`, `NO_SHOW`

### PAYMENT Group
- `PAYMENT_RECEIVED`, `PAYMENT_REFUND`, `DEPOSIT_ADDED`, `DEPOSIT_USED`

### SERVICE Group
- `SERVICE_USED`, `MINIBAR_USED`, `LAUNDRY_USED`, `RESTAURANT_USED`, `SPA_USED`

### EXPERIENCE Group
- `COMPLAINT`, `FEEDBACK`, `REVIEW`, `LOST_ITEM`

### SYSTEM Group
- `PROFILE_UPDATED`, `BLACKLISTED`, `TIER_UPGRADED`, `TIER_DOWNGRADED`, `POINTS_EARNED`

---

## Frontend Architecture

### Guest Detail Page (crm_guest_detail.html)

```html
<div x-data="guestDetail()" data-guest-id="{{ guest_id }}">
  {% include 'pms/partials/crm_guest_detail/header_tabs.html' %}
  {% include 'pms/partials/crm_guest_detail/skeleton.html' %}
  
  <template x-if="!loading && guest">
    <div class="gd-body">
      {% include 'pms/partials/crm_guest_detail/sidebar.html' %}
      <div class="gd-content">
        {% include 'pms/partials/crm_guest_detail/tab_overview.html' %}
        {% include 'pms/partials/crm_guest_detail/tab_stays.html' %}
        {% include 'pms/partials/crm_guest_detail/tab_services.html' %}
        {% include 'pms/partials/crm_guest_detail/tab_payments.html' %}
        {% include 'pms/partials/crm_guest_detail/tab_coguests.html' %}
      </div>
    </div>
  </template>
</div>
```

### Alpine.js Component (crm_guest_detail.js)

```javascript
function guestDetail() {
  return {
    guestId, loading: true, activeTab: 'overview',
    guest: null, membership: null, next_tier: null, profile: null,
    
    // Lazy loaded tab data
    stays: [], staysLoading: false,
    services: [], serviceStats: null,
    payments: [], paymentStats: null,
    timeline: [], timelineLoading: false,
    coGuests: [], coGuestsLoading: false,
    
    async init() {
      await this.loadProfile();
      this.loadStays();
    },
    
    async loadProfile() { /* GET /profile */ },
    async loadStays() { /* GET /stays */ },
    async loadServices() { /* GET /services */ },
    async loadPayments() { /* GET /payments */ },
    async loadTimeline() { /* GET /timeline */ },
    async loadCoGuests() { /* GET /co-guests */ },
    async toggleBlacklist() { /* PATCH /blacklist */ },
    
    // Formatters
    fmtMoney(v) { return Number(v).toLocaleString('vi-VN') + 'đ'; },
    fmtDate(iso) { /* DD/MM/YYYY */ },
    tierGradient(tier) { /* CSS gradient */ },
  }
}
```

### Tab Overview Layout

1. **Tier Journey Progress** - Full width, hiển thị 5 bậc với progress bar
2. **Benefits + Preferences** - 2 columns
3. **Recent Stays Preview** - Full width, 3 stays gần nhất

---

## Common Tasks

### Rebuild all memberships
```python
from app.services.guest_crm_service import recalculate_all_memberships
result = recalculate_all_memberships(db)
```

### Batch create stay summaries (migration)
```python
from app.services.guest_crm_service import batch_create_stay_summaries
result = batch_create_stay_summaries(db, batch_size=100)
```

### Log custom activity
```python
from app.api.pms.guest_activity import log_activity, ActivityType, ActivityGroup

log_activity(
    db=db,
    guest_id=guest_id,
    activity_type=ActivityType.PAYMENT_RECEIVED,
    activity_group=ActivityGroup.PAYMENT,
    title="Thanh toán 500.000đ",
    amount=500000,
    stay_id=stay_id,
)
```

### Manual points adjustment
```python
from app.db.models import GuestLoyaltyTransaction

db.add(GuestLoyaltyTransaction(
    guest_id=guest_id,
    transaction_type="ADJUSTMENT",
    points=-500,
    reason="Đổi voucher 500đ",
    stay_id=stay_id,
))
```

### Trigger checkout CRM hook
```python
from app.services.guest_crm_integration import on_checkout_complete

result = on_checkout_complete(
    db=db,
    stay_id=stay_id,
    folio_id=folio_id,
    user_id=user_id,
)
```

---

## Data Consistency Rules

1. **GuestStaySummary** = Source of truth cho stats
2. **Points chia đều** khi nhiều khách: `split_amount = final_amount / guest_count`
3. **total_spent GIỮ NGUYÊN** full amount (không chia)
4. **GuestIdentity** dùng chống trùng lặp định danh
5. **Blacklist**: Set `is_blacklisted=True`, không xóa record
6. **Soft delete**: Query thêm `WHERE deleted_at IS NULL`
7. **GuestActivity** là append-only
8. **Debt tracking**: `debt_amount > 0` và `debt_status IN ('pending', 'partial')`

---

## Pricing Engine (Tính tiền phòng)

### Key Files
```
app/services/pricing_engine.py    # Core pricing engine (Time-Slicing)
app/services/pricing_service.py   # Facade layer (backward-compatible)
app/api/pms/pms_checkout.py       # Sử dụng pricing engine
app/api/pms/pms_checkin.py        # Preview pricing
```

### Pricing Modes

| Mode | Mô tả | Use case |
|------|--------|---------|
| **AUTO** | So sánh HOURLY vs DAILY, chọn rẻ hơn | Mặc định |
| **FORCE_HOURLY** | Tính giá thuê giờ thuần túy | Thuê theo giờ |
| **FORCE_DAILY** | Tính giá theo ngày | Lưu trú qua đêm |
| **FORCE_OVERNIGHT** | Tính giá qua đêm cứng (00:00-05:59) | Đặt phòng đêm |

### Luồng Smart Routing (Smart Check-in)

```
Check-in Time Range          Xử lý
─────────────────────────────────────────────────────
00:00 - 05:59              → FORCE_OVERNIGHT (Qua đêm cứng)
06:00 - 13:59              → Kiểm tra day_threshold
                            ├─ stay_hours >= threshold → FORCE_DAILY
                            └─ stay_hours < threshold → AUTO
14:00 - 23:59              → AUTO (so sánh HOURLY vs DAILY)
```

### Points Calculation với Pricing

```python
# Từ checkout flow (guest_crm_integration.py)

# 1. Lấy final_amount từ pricing engine
final_amount = folio.total_charge - folio.total_discount

# 2. Chia đều cho số khách
split_amount = final_amount / guest_count

# 3. Tính points
base_points = floor(split_amount / 1000)
earned_points = floor(base_points * tier_multiplier)
```

---

## Cập nhật gần đây (2026-05-01)

### Files đã modified:
- `app/api/pms/guest_crm_api.py` - CRM API endpoints (30+ endpoints)
- `app/services/guest_crm_service.py` - Membership & tier logic
- `app/services/guest_crm_integration.py` - Checkout hooks
- `app/api/pms/guest_activity.py` - Activity logging helpers
- `app/static/js/pms/crm_guest_detail.js` - Alpine.js component
- `app/static/css/crm_guest_detail.css` - Styles mới
- `app/templates/pms/crm_guest_detail.html` - Guest detail page
- `app/templates/pms/partials/crm_guest_detail/*.html` - Tab components

### Tính năng mới:
- Guest Detail Page với Alpine.js
- Tier Journey visualization (5 bậc)
- Lazy loading cho tab data
- Skeleton loading
- Responsive design
- Dark mode support
- Blacklist management
- Debt tracking
- Co-guests (khách cùng ở)
- Address fields (địa bàn mới/cũ sau 1/7/2025)
- Vehicle tracking (biển số xe)

### Địa chỉ địa lý mới (HotelGuest)
- `city`, `district`, `ward` - Địa bàn mới (sau chuyển đổi)
- `old_city`, `old_district`, `old_ward` - Địa bàn cũ
- `address_type` - "new" | "old"

---

## Liên kết với các module khác

### PMS Checkin
- Tạo HotelStay mới
- Tạo HotelGuest với địa chỉ địa lý
- Gọi `log_checkin()` tạo GuestActivity

### PMS Checkout
- Atomic checkout transaction
- Gọi `on_checkout_complete()` cho CRM hooks
- Tạo GuestStaySummary, GuestServiceUsage, GuestPaymentSummary
- Cập nhật membership tier & points

### Folio/Billing
- Folio ↔ HotelStay tách biệt
- FolioTransaction cho từng dòng tiền
- Payment cho thanh toán thực tế
- PaymentAllocation cho split bill

### OTA Booking Agent
- Booking tạo từ email AI parse
- Liên kết Booking → Guest
- Liên kết Booking → HotelStay (khi checkin)

### WMS (Inventory)
- Product: Sản phẩm (minibar, laundry)
- StockMovement: Lịch sử xuất/nhập kho
- GuestServiceUsage → StockMovement (minibar usage)
