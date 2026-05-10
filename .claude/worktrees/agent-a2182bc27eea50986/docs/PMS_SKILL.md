---
name: pms-crm
description: "Quản lý PMS + CRM khách hàng: hồ sơ guest, membership tiers (BASIC→VIP), loyalty points, lịch sử lưu trú, pricing engine, OTA integration (Booking.com, Agoda...). Dùng khi làm việc với CRM, guest, khách hàng, thành viên, membership, tier, điểm thưởng, checkout, checkin, pricing, OTA. Cập nhật: 2026-04-30"
---

# PMS CRM - Guest Relationship Management System

## Tài liệu tham khảo

- [CRM.md](CRM.md) - Tổng quan CRM, Quick Reference
- [CRM_references.md](CRM_references.md) - Chi tiết Database Models, Logic, Activity Types

## Tổng quan dự án

### Bin Bin Hotel Management System (PMS)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           FULL STACK ARCHITECTURE                        │
├─────────────────────────────────────────────────────────────────────────┤
│  FRONTEND (Browser)                                                     │
│  ├── Jinja2 Templates (.html)                                           │
│  ├── Alpine.js (Reactive UI)                                           │
│  ├── Vanilla JS + CSS                                                  │
│  └── Skeleton Loading (custom)                                         │
├─────────────────────────────────────────────────────────────────────────┤
│  BACKEND (FastAPI)                                                     │
│  ├── API Layer (app/api/pms/)                                          │
│  ├── Service Layer (app/services/)                                      │
│  └── Core Utilities (app/core/)                                        │
├─────────────────────────────────────────────────────────────────────────┤
│  DATABASE (PostgreSQL via SQLAlchemy)                                   │
│  ├── ORM Models (app/db/models.py)                                     │
│  └── Migrations (alembic/)                                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI (Python 3.14+) |
| Database | PostgreSQL (Supabase) |
| ORM | SQLAlchemy |
| Migrations | Alembic |
| Frontend | Jinja2 + Alpine.js |
| Session | Starlette SessionMiddleware |
| Scheduler | APScheduler |
| Auth | Custom (password hashed) |
| Timezone | Asia/Ho_Chi_Minh (VN_TZ) |

---

## Cấu trúc thư mục chính

```
app/
├── main.py                 # FastAPI entry point, router registration
├── api/                    # API endpoints
│   ├── pms/              # PMS module
│   │   ├── guest_crm_api.py       # CRM API (20+ endpoints)
│   │   ├── guest_activity.py       # Timeline/activity logging
│   │   ├── pms_checkin.py         # Check-in flow
│   │   ├── pms_checkout.py        # Check-out flow
│   │   ├── pms_stays.py           # Hotel stays management
│   │   ├── folio_api.py            # Billing/folio
│   │   ├── inventory_integration.py # WMS integration
│   │   └── pms_pages.py            # Page routes (HTML)
│   └── ... (users, attendance, tasks, etc.)
├── services/              # Business logic layer
│   ├── guest_crm_service.py        # CRM core logic
│   ├── guest_crm_integration.py   # Checkout hooks
│   ├── checkout_service.py         # Checkout orchestration
│   └── pricing_service.py          # Pricing engine
├── db/
│   ├── models.py                  # All SQLAlchemy models (~1700 lines)
│   ├── session.py                 # DB session management
│   └── utils.py                   # DB utilities
├── core/
│   ├── config.py                  # Settings (Pydantic)
│   ├── utils.py                   # Utilities (VN_TZ, etc.)
│   ├── jinja2_patch.py            # Jinja2 compatibility fix
│   └── templates.py               # Template rendering
├── templates/              # Jinja2 HTML templates
│   └── pms/
│       ├── crm_dashboard.html     # CRM main dashboard
│       ├── crm_guest_detail.html   # Guest detail page
│       └── partials/
│           └── crm_guest_detail/
│               ├── header_tabs.html
│               ├── sidebar.html
│               ├── tab_overview.html
│               ├── tab_stays.html
│               ├── tab_services.html
│               ├── tab_payments.html
│               ├── tab_coguests.html
│               ├── tab_timeline.html
│               └── skeleton.html
└── static/
    ├── js/pms/
    │   └── crm_guest_detail.js    # Alpine.js component
    └── css/
        ├── crm_guest_detail.css   # Guest detail styles
        └── skeleton.css           # Skeleton loading
```

---

## Kiến trúc CRM Layer

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         CRM ARCHITECTURE FLOW                             │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────────────────┐   │
│  │   Frontend  │───▶│  API Layer   │───▶│   Service Layer          │   │
│  │  (Alpine.js)│    │guest_crm_api │    │  guest_crm_service      │   │
│  └─────────────┘    └──────────────┘    │  guest_crm_integration  │   │
│                                          └────────────┬──────────────┘   │
│                                                       │                  │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────▼──────────────┐   │
│  │  Timeline   │◀───│  Activity    │◀───│   Database Models         │   │
│  │  Events     │    │  Logging     │    │   Guest, Membership,      │   │
│  └─────────────┘    └──────────────┘    │   StaySummary, etc.      │   │
│                                          └───────────────────────────┘   │
│                                                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

### Key Files

```
app/api/pms/guest_crm_api.py         # 20+ API endpoints
app/services/guest_crm_service.py   # Membership, points, tier logic
app/services/guest_crm_integration.py # Checkout hooks
app/api/pms/guest_activity.py       # Activity logging helpers
app/db/models.py                    # Guest, GuestMembership, GuestStaySummary, etc.
app/templates/pms/crm_guest_detail.html # Guest detail page
app/static/js/pms/crm_guest_detail.js  # Alpine.js component
app/static/css/crm_guest_detail.css    # Styles
```

---

## Database Models

### Guest (Master Customer Record)

```python
Guest:
    id: BIGINT (PK)
    full_name: String(255)              # Họ tên đầy đủ
    normalized_name: String(255)         # Tên không dấu, lowercase (search)
    phone: String(20)                   # SĐT (indexed)
    email: String(255)                  # Email (indexed)
    cccd: String(20)                   # CCCD/CMND/Passport (indexed, unique)
    date_of_birth: Date                # Ngày sinh
    gender: String(10)                  # Nam/Nữ/Khác
    nationality: String(100)           # Quốc tịch
    id_expire: Date                    # Ngày hết hạn CCCD
    default_address: Text              # Địa chỉ mặc định
    
    first_seen_at: DateTime             # Lần đầu tiên ghé thăm
    last_seen_at: DateTime             # Lần cuối ghé thăm
    total_stays: Integer               # Tổng số lần lưu trú
    total_spent: NUMERIC(15,2)        # Tổng chi tiêu
    
    is_blacklisted: Boolean            # Cờ blacklist
    tags: JSONB                       # ['VIP', 'OTA', 'CORP', 'SILVER', 'GOLD', ...]
    deleted_at: DateTime              # Soft delete
```

### GuestMembership (Membership Tier)

```python
GuestMembership:
    id: BIGINT (PK)
    guest_id: BIGINT (FK, unique)     # Liên kết 1-1 với Guest
    
    tier: Enum                         # BASIC|SILVER|GOLD|PLATINUM|VIP
    tier_updated_at: DateTime          # Thời điểm lên tier gần nhất
    
    # Stats tích lũy (từ GuestStaySummary)
    total_stays: Integer               # Tổng số lần lưu trú
    total_nights: Integer             # Tổng số đêm ở
    total_spent: NUMERIC(15,2)       # Tổng chi tiêu
    total_deposit: NUMERIC(15,2)     # Tổng đặt cọc
    total_debt: NUMERIC(15,2)        # Tổng nợ
    total_refund: NUMERIC(15,2)       # Tổng hoàn tiền
    
    # Loyalty Points
    loyalty_points: Integer            # Tổng điểm đã tích
    points_redeemed: Integer          # Điểm đã đổi
    points_balance: Integer            # Số dư điểm = loyalty_points - points_redeemed
    
    # Preferences
    favorite_branch_id: Integer        # Chi nhánh yêu thích
    favorite_room_type: String(100)   # Loại phòng yêu thích
    preferred_payment_method: String(50) # PT thanh toán ưa thích
```

### GuestStaySummary (Stay History - Source of Truth)

```python
GuestStaySummary:
    id: BIGINT (PK)
    guest_id: BIGINT (FK)             # Guest đã lưu trú
    stay_id: BIGINT (FK)             # HotelStay record
    branch_id: Integer (FK)           # Chi nhánh
    
    # Room info
    room_number: String(20)           # Số phòng
    room_type_name: String(100)       # Loại phòng
    floor: Integer                    # Tầng
    
    # Dates
    check_in_at: DateTime            # Giờ nhận phòng
    check_out_at: DateTime           # Giờ trả phòng
    nights: Integer                   # Số đêm ở
    
    # Pricing
    total_charge: NUMERIC(15,2)      # Tổng phí
    discount: NUMERIC(15,2)          # Giảm giá
    deposit: NUMERIC(15,2)           # Tiền cọc gốc
    deposit_type: String(50)          # Loại cọc (cash, card, ...)
    deposit_paid: NUMERIC(15,2)      # Tiền cọc đã sử dụng
    final_amount: NUMERIC(15,2)       # Thực trả = total_charge - discount
    debt_amount: NUMERIC(15,2)       # Số tiền còn nợ
    
    # Stay metadata
    stay_type: String(20)            # NIGHT|HOUR|DAY_USE|AUTO
    pricing_mode: String(20)         # HOURLY|NIGHT|DAY_USE
    guest_count: Integer              # Số khách trong phòng
    status: String(20)               # ACTIVE|CHECKED_OUT|CANCELLED
    checkout_summary: String(20)      # normal|debt|void
    payment_methods: JSONB           # ['cash', 'card']
    vehicle: String(255)             # Biển số xe
    source: String(20)               # pms|ota|walkin
    debt_status: String(20)          # none|pending|partial|settled
```

### GuestServiceUsage (Service Usage History)

```python
GuestServiceUsage:
    id: BIGINT (PK)
    guest_id: BIGINT (FK)
    stay_id: BIGINT (FK)
    branch_id: Integer (FK)
    
    service_category: String(50)      # MINIBAR|LAUNDRY|RESTAURANT|SPA|SERVICE|OTHER
    service_name: String(255)         # Tên dịch vụ cụ thể
    product_id: Integer               # Product ID (nếu từ inventory)
    
    quantity: DECIMAL                 # Số lượng
    unit_price: DECIMAL               # Đơn giá
    total_amount: DECIMAL             # Tổng tiền
    
    room_number: String(20)           # Phòng sử dụng
    used_at: DateTime                 # Thời điểm sử dụng
    
    folio_transaction_id: BIGINT      # FolioTransaction gốc
    stock_movement_id: BIGINT         # Stock movement (inventory)
    created_by: BIGINT               # User tạo
```

### GuestPaymentSummary (Payment History)

```python
GuestPaymentSummary:
    id: BIGINT (PK)
    guest_id: BIGINT (FK)
    stay_id: BIGINT (FK)
    folio_id: BIGINT (FK)
    payment_id: BIGINT (nullable)   # Payment record gốc
    branch_id: Integer (FK)
    
    amount: DECIMAL                   # Số tiền
    payment_type: String(20)         # DEPOSIT|PAYMENT|REFUND
    payment_method: String(50)       # CASH|CARD|BANK_TRANSFER|OTA|COMPANY
    
    transaction_code: String(50)     # Mã giao dịch
    room_number: String(20)          # Phòng thanh toán
    paid_at: DateTime                # Thời điểm thanh toán
    
    is_voided: Boolean               # Đã hủy
    void_reason: String(255)        # Lý do hủy
```

### GuestActivity (Timeline - All Guest Actions)

```python
GuestActivity:
    id: BIGINT (PK)
    guest_id: BIGINT (FK)
    
    activity_type: String(50)         # CHECK_IN, PAYMENT_RECEIVED, TIER_UPGRADED, ...
    activity_group: String(20)        # stay|booking|payment|service|experience|system
    title: String(255)               # Tiêu đề ngắn
    description: Text                 # Mô tả chi tiết
    
    stay_id: BIGINT (nullable)        # HotelStay liên quan
    booking_id: BIGINT (nullable)     # Booking liên quan
    branch_id: Integer (nullable)     # Chi nhánh
    
    amount: DECIMAL                   # Số tiền (nếu có)
    currency: String(10)             # VND, USD, ...
    
    actor_type: String(20)           # system|user|guest
    actor_id: BIGINT (nullable)      # User ID nếu actor_type=user
    
    source: String(20)               # pms|ota|api|ai|pos|wms
    
    extra_data: JSONB               # Dữ liệu bổ sung
    created_at: DateTime            # Thời điểm tạo
```

### GuestStayMapping (Co-guest Relationships)

```python
GuestStayMapping:
    id: BIGINT (PK)
    guest_id: BIGINT (FK)
    stay_id: BIGINT (FK)
    branch_id: Integer (FK)
    
    room_number: String(20)
    check_in_at: DateTime
    check_out_at: DateTime
    is_primary: Boolean              # Khách chính trong phòng
```

### GuestLoyaltyTransaction (Points Ledger)

```python
GuestLoyaltyTransaction:
    id: BIGINT (PK)
    guest_id: BIGINT (FK)
    stay_id: BIGINT (nullable)
    
    transaction_type: String(20)      # EARN|REDEEM|ADJUSTMENT|EXPIRED
    points: Integer                  # Số điểm (+/-)
    balance_after: Integer            # Số dư sau giao dịch
    
    reason: String(255)              # Lý do
    created_by: BIGINT              # User thực hiện
    created_at: DateTime
```

---

## Membership Tiers

### Tier Thresholds & Benefits

| Tier | Points Threshold | Points Multiplier | Discount | Benefits |
|------|-----------------|-------------------|----------|----------|
| **BASIC** | 0 | 1.0x | 0% | - |
| **SILVER** | 5,000 | 1.5x | 5% | early_checkin |
| **GOLD** | 15,000 | 2.0x | 10% | early_checkin, late_checkout, priority |
| **PLATINUM** | 40,000 | 3.0x | 15% | + free_upgrade |
| **VIP** | 100,000 | 5.0x | 20% | + dedicated_manager |

### Tier Benefits Detail

```python
BASIC:
    points_multiplier: 1.0
    early_checkin: False
    late_checkout: False
    discount_percent: 0
    priority_service: False
    free_upgrade: False
    dedicated_manager: False

SILVER:
    points_multiplier: 1.5
    early_checkin: True
    discount_percent: 5
    ...

GOLD:
    points_multiplier: 2.0
    early_checkin: True
    late_checkout: True
    discount_percent: 10
    priority_service: True
    ...

PLATINUM:
    points_multiplier: 3.0
    discount_percent: 15
    free_upgrade: True
    ...

VIP:
    points_multiplier: 5.0
    discount_percent: 20
    dedicated_manager: True
```

### Points Calculation Formula

```python
# 1. Tính final_amount (sau giảm giá)
final_amount = folio.total_charge - folio.total_discount

# 2. Chia đều cho số khách trong phòng
split_amount = final_amount / guest_count

# 3. Tính base points
base_points = floor(split_amount / 1000)  # 1 điểm / 1000đ

# 4. Áp dụng tier multiplier
tier_multiplier = {
    BASIC: 1.0,
    SILVER: 1.5,
    GOLD: 2.0,
    PLATINUM: 3.0,
    VIP: 5.0,
}
earned_points = floor(base_points * tier_multiplier)

# 5. Cộng vào loyalty_points
membership.loyalty_points += earned_points
membership.points_balance = loyalty_points - points_redeemed

# 6. Recalculate tier dựa trên points_balance
new_tier = calculate_tier(points_balance)
```

---

## Luồng Checkout (CRM Integration)

```
┌────────────────────────────────────────────────────────────────────────┐
│                        CHECKOUT → CRM FLOW                              │
├────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   User clicks "Checkout"                                                 │
│          │                                                              │
│          ▼                                                              │
│   ┌─────────────────┐                                                  │
│   │ pms_checkout.py │                                                  │
│   │ execute_checkout│                                                  │
│   └────────┬────────┘                                                  │
│            │                                                            │
│            ▼                                                            │
│   ┌─────────────────────────────────────┐                              │
│   │ guest_crm_integration.py            │                              │
│   │ on_checkout_complete(db, ...)       │                              │
│   └────────────┬────────────────────────┘                              │
│                │                                                        │
│      ┌─────────┼─────────┬──────────┬──────────┐                       │
│      ▼         ▼         ▼          ▼          ▼                       │
│   ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────┐              │
│   │Mapping │ │Summary │ │Services│ │Payments│ │Membership│              │
│   │        │ │        │ │        │ │        │ │ Update   │              │
│   └────────┘ └────────┘ └────────┘ └────────┘ └──────────┘              │
│                                                                         │
└────────────────────────────────────────────────────────────────────────┘
```

### Hook: on_checkout_complete()

```python
# Khi checkout thành công → gọi hook:
on_checkout_complete(db, stay_id, folio_id, user_id)

# Hook này tự động:
# 1. Tạo GuestStayMapping (quan hệ khách cùng ở)
# 2. Tạo GuestStaySummary (tổng hợp lưu trú)
# 3. Tạo GuestServiceUsage (từ FolioTransaction)
# 4. Tạo GuestPaymentSummary (từ Payment)
# 5. Cập nhật membership tier & points
# 6. Log GuestActivity (timeline)
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
| `/api/pms/crm/guests/{id}/stays` | GET | Lịch sử lưu trú |
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

### Checkout Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/pms/checkout/{stay_id}/info` | GET | Preview checkout |
| `/api/pms/checkout/{stay_id}/preview` | GET | Detailed preview với folio merge |
| `/api/pms/checkout/{stay_id}` | POST | Atomic checkout |
| `/api/pms/checkout/{stay_id}/recheckin` | POST | Reopen checked-out stay |

### Folio/Billing Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/pms/folio/{folio_id}` | GET | Get folio details |
| `/api/pms/folio/{folio_id}/transactions` | GET | Get transactions |
| `/api/pms/folio/{folio_id}/payment` | POST | Add payment |
| `/api/pms/folio/{folio_id}/charge` | POST | Add charge |
| `/api/pms/folio/fix-cache` | POST | Recalculate cache |

---

## Activity Types (Timeline)

### Activity Groups

```python
STAY = "stay"         # Checkin, checkout, đổi phòng
BOOKING = "booking"    # Đặt phòng
PAYMENT = "payment"    # Thanh toán, cọc
SERVICE = "service"    # Dịch vụ
EXPERIENCE = "experience"  # Khiếu nại, feedback
SYSTEM = "system"      # Profile update, blacklist
```

### Activity Types by Group

**STAY:**
- `CHECK_IN`, `CHECK_OUT`, `ROOM_CHANGE`
- `EXTEND_STAY`, `EARLY_CHECKIN`, `LATE_CHECKOUT`
- `GUEST_ADDED`, `GUEST_EDITED`

**BOOKING:**
- `BOOKING_CREATED`, `BOOKING_MODIFIED`
- `BOOKING_CANCELLED`, `NO_SHOW`

**PAYMENT:**
- `PAYMENT_RECEIVED`, `PAYMENT_REFUND`
- `DEPOSIT_ADDED`, `DEPOSIT_USED`

**SERVICE:**
- `SERVICE_USED`, `MINIBAR_USED`, `LAUNDRY_USED`
- `RESTAURANT_USED`, `SPA_USED`, `ROOM_SERVICE_USED`

**EXPERIENCE:**
- `COMPLAINT`, `FEEDBACK`, `REVIEW`
- `LOST_ITEM`

**SYSTEM:**
- `PROFILE_UPDATED`, `MERGED`, `BLACKLISTED`
- `TIER_UPGRADED`, `TIER_DOWNGRADED`
- `POINTS_EARNED`, `POINTS_REDEEMED`

---

## Frontend: Guest Detail Page

### Page Structure

```
crm_guest_detail.html
├── header_tabs.html       # Sticky header với tabs
├── sidebar.html           # Profile card, membership, stats
├── tab_overview.html      # Tier journey, benefits, preferences
├── tab_stays.html         # Stay history list
├── tab_services.html      # Service usage history
├── tab_payments.html      # Payment history
├── tab_coguests.html      # Co-guests list
├── tab_timeline.html      # Activity timeline
└── skeleton.html          # Loading skeleton
```

### Alpine.js Component (crm_guest_detail.js)

```javascript
function guestDetail() {
  return {
    guestId,           // From URL/Guest ID
    loading: true,
    activeTab: 'overview',

    // Profile data
    guest: null,
    membership: null,
    next_tier: null,
    profile: null,

    // Tab data (lazy loaded)
    stays: [], staysLoading: false,
    services: [], serviceStats: null,
    payments: [], paymentStats: null,
    timeline: [], timelineLoading: false,
    coGuests: [], coGuestsLoading: false,

    // Tier journey
    tierJourney: [],

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
    
    // Helpers
    fmtMoney(v) { /* Format VND */ },
    fmtDate(iso) { /* Format date */ },
    tierGradient(tier) { /* CSS gradient */ },
    // ... more helpers
  }
}
```

### CSS Variables (crm_guest_detail.css)

```css
:root {
  --crm-bg: #f8fafc;
  --crm-surface: #ffffff;
  --crm-text: #0f172a;
  --crm-accent: #6366f1;
  --crm-success: #10b981;
  --crm-warning: #f59e0b;
  --crm-danger: #ef4444;
  --crm-border: #e2e8f0;
  --crm-radius: 16px;
}

html.dark {
  --crm-bg: #0a0a0f;
  --crm-surface: #15151d;
  /* ... dark mode variables */
}
```

---

## Common Tasks

### Rebuild all memberships

```python
from app.services.guest_crm_service import recalculate_all_memberships

result = recalculate_all_memberships(db)
# Returns: {"memberships_updated": 123}
```

### Batch create stay summaries (migration)

```python
from app.services.guest_crm_service import batch_create_stay_summaries

result = batch_create_stay_summaries(db, batch_size=100)
# Returns: {"total_created": 456, "stays_processed": 789}
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
    transaction_type="ADJUSTMENT",  # EARN, REDEEM, ADJUSTMENT
    points=-500,  # Âm cho REDEEM
    reason="Đổi voucher 500đ",
    stay_id=stay_id,
))
```

### Trigger checkout CRM hook manually

```python
from app.services.guest_crm_integration import on_checkout_complete

result = on_checkout_complete(
    db=db,
    stay_id=stay_id,
    folio_id=folio_id,
    user_id=user_id,
)
# Returns: {"stay_mappings_created": 2, "stay_summaries_created": 2, ...}
```

---

## Data Consistency Rules

1. **GuestStaySummary** = Source of truth cho stats
   - `total_stays`, `total_nights`, `total_spent` được tính từ đây
   - Không update trực tiếp, chỉ tạo mới khi checkout

2. **Points chia đều** khi nhiều khách trong 1 stay
   - `split_amount = final_amount / guest_count`
   - `total_spent` GIỮ NGUYÊN không chia

3. **GuestIdentity** dùng chống trùng lặp
   - 1 guest có thể có nhiều SĐT/email
   - Dùng để merge duplicate guests

4. **Blacklist**: Set `is_blacklisted=True`, không xóa

5. **Soft delete**: Query luôn thêm `WHERE deleted_at IS NULL`

6. **GuestActivity** là append-only
   - Không sửa, chỉ thêm mới
   - Dùng cho timeline và audit trail

---

## Database Connection Management

```python
# app/db/session.py

# Main engine (cho HTTP requests) - có pool
engine = create_engine(
    str(settings.DATABASE_URL),
    pool_size=8,
    max_overflow=7,
    pool_timeout=30,
    pool_recycle=1800,
)

# Task engine (cho background tasks) - NullPool
_task_engine = create_engine(
    str(settings.DATABASE_URL),
    poolclass=NullPool,  # Mỗi query tạo/huỷ connection riêng
)

# Dependency
def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

---

## Session & Auth

```python
# SessionMiddleware trong app/main.py
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

# Middleware: ensure_active_branch_in_session
# Tự động set active_branch cho user khi login
# - Admin/Manager → "HỆ THỐNG"
# - Normal user → last_active_branch hoặc "Chưa phân bổ"
```

---

## Pricing Engine (Tính tiền phòng)

### Tổng quan kiến trúc

```
┌────────────────────────────────────────────────────────────────────────┐
│                     PRICING ENGINE ARCHITECTURE                          │
├────────────────────────────────────────────────────────────────────────┤
│  calculate_full_charge(check_in, check_out, mode)                       │
│           │                                                            │
│           ▼                                                            │
│  ┌─────────────────────────────────────────────────────┐               │
│  │           PricingEngine.evaluate()                  │               │
│  │  1. _normalize()     — Grace Period thông minh   │               │
│  │  2. _slice_timeline — Chia timeline thành slices │               │
│  │  3. _simulate_HOURLY — Tính giá theo giờ       │               │
│  │  4. _simulate_DAILY  — Tính giá theo ngày       │               │
│  │  5. _simulate_OVERNIGHT — Tính giá qua đêm      │               │
│  │  6. BAR Simulator    — So sánh & chọn tối ưu    │               │
│  └─────────────────────────────────────────────────────┘               │
└────────────────────────────────────────────────────────────────────────┘
```

### Key Files

```
app/services/pricing_engine.py   # Core pricing engine (Time-Slicing)
app/services/pricing_service.py  # Facade layer (backward-compatible)
app/api/pms/pms_checkout.py     # Sử dụng pricing engine
app/api/pms/pms_checkin.py     # Preview pricing
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

### Time-Slicing Engine

Hệ thống chia timeline thành các **TimeSlice** dựa trên `standard_checkin_time` và `standard_checkout_time`:

```
Ví dụ: CI 10:00 T2, CO 15:00 T3, std_in=14:00, std_out=12:00

Timeline:
10:00 ──────┬──────────────────────────┬───────────── 15:00
             │                          │
     ┌────────┴────────┐      ┌─────────┴────────┐
     │ Slice: early    │      │ Slice: core     │
     │ 10:00 → 14:00  │      │ 14:00 → 12:00   │
     │ (4 tiếng)       │      │ (22 tiếng)      │
     │ Phí sớm         │      │ 1 đêm           │
     └─────────────────┘      └─────────┬────────┘
                                       │
                              ┌────────┴────────┐
                              │ Slice: late     │
                              │ 12:00 → 15:00  │
                              │ (3 tiếng)       │
                              │ Phí muộn        │
                              └─────────────────┘
```

### Slice Types

| Slice Type | Mô tả | Pricing |
|-------------|--------|---------|
| **early** | Trước std_in (VD: <14:00) | early_fee/giờ |
| **core** | Từ std_in → std_out (hotel day) | ppn (1 đêm) hoặc pph |
| **late** | Sau std_out (VD: >12:00 ngày hôm sau) | late_fee/giờ hoặc +1 ngày |
| **overflow** | Vùng chờ giữa 2 hotel days (12:00-14:00) | Miễn phí |

### Pricing Config (HotelRoomType)

```python
# Standard times
standard_checkin_time: time = 14:00    # Giờ nhận phòng chuẩn
standard_checkout_time: time = 12:00   # Giờ trả phòng chuẩn

# Fees
early_checkin_fee_per_hour: Decimal     # Phí nhận phòng sớm/giờ
late_checkout_fee_per_hour: Decimal     # Phí trả phòng muộn/giờ
grace_minutes: int = 10               # Thời gian miễn phí (grace period)

# Per-hour pricing
price_per_hour: Decimal               # Giá giờ đầu tiên
price_next_hour: Decimal              # Giá giờ tiếp theo
min_hours: int = 1                   # Số giờ tối thiểu

# Per-night pricing
price_per_night: Decimal              # Giá 1 đêm

# Thresholds
day_threshold_hours: int = 8          # Ngưỡng chuyển sang giá ngày

# Night Promo
promo_start_time: time               # Giờ bắt đầu khuyến mãi đêm
promo_end_time: time                # Giờ kết thúc
promo_discount_percent: Decimal        # % giảm giá đêm
```

### BAR Simulation (Best Available Rate)

```python
# AUTO mode: So sánh 2 kịch bản
hourly_total = _simulate_HOURLY(slices)
daily_total = _simulate_DAILY(slices)

# Chọn kịch bản rẻ hơn
result = hourly_total if hourly_total <= daily_total else daily_total
```

### Grace Period Logic

```python
def _normalize(check_in, check_out):
    """
    Grace Period thông minh:
    - Checkout trong ±grace quanh std_out (12:00) → bẻ về 12:00
    - Checkin trong ±grace quanh std_in (14:00) → bẻ về 14:00

    VD: Grace = 10 phút, CI 13:52 → bẻ thành 14:00 (miễn phí early)
    VD: CO 12:08 → bẻ thành 12:00 (miễn phí late)
    """
```

### Breakdown Structure

```python
# Return format
(total_amount, breakdown)

# Breakdown item
{
    "type": "ROOM_CHARGE" | "HOURLY_CHARGE" | "EARLY_CHECKIN_FEE" | "LATE_CHECKOUT_FEE",
    "description": "Tiền phòng (1 đêm)",
    "amount": Decimal("500000"),
    "slice_type": "core" | "early" | "late",
    "mode": "DAILY" | "HOURLY" | "OVERNIGHT",
    "hours": 4,  # nếu có
    "days": 1,   # nếu có
    "start_iso": "2026-04-30T14:00:00+07:00",
    "end_iso": "2026-05-01T12:00:00+07:00",
}
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

### Common Code Snippets

#### Preview pricing khi check-in
```python
from app.services.pricing_service import calculate_full_charge, get_engine_config

# Get room type
room_type = db.query(HotelRoomType).filter(...).first()

# Preview
total, breakdown = calculate_full_charge(
    stay_type="AUTO",
    room_type=room_type,
    check_in=check_in_dt,
    check_out=check_out_dt,
)

# Config cho UI
config = get_engine_config(room_type)
# Returns: {"std_checkin_time": "14:00", "std_checkout_time": "12:00", ...}
```

#### Force hourly pricing
```python
total, breakdown = calculate_full_charge(
    stay_type="FORCE_HOURLY",
    room_type=room_type,
    check_in=check_in_dt,
    check_out=check_out_dt,
)
```

### Special Scenarios

#### 1. Overnight Early (14:00-23:59 check-in)
```
Overnight_Candidate = Overnight_Rate + extra_hours * early_fee
Anti-loss: Nếu >= Day_Rate → ép về DAILY
```

#### 2. Night Audit Overnight (00:00-05:59)
```
Tự động ép Overnight Rate
Checkout entitlement: 12:00 cùng ngày
```

#### 3. Day Rollover (Late checkout >= 8 giờ)
```
Nếu late_hours >= day_threshold → +1 ngày thay vì tính late_fee
```

---

## OTA Integration (Booking.com, Agoda, Traveloka, Go2Joy, Airbnb, Mytour, Website)

### Tổng quan kiến trúc

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      OTA INTEGRATION ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────┐     ┌───────────────────┐     ┌─────────────────┐ │
│  │  Gmail Inbox     │────▶│  Gmail API        │────▶│  OTA Agent      │ │
│  │  (OTA Emails)    │     │  + Pub/Sub Push   │     │  (Email Parser) │ │
│  └──────────────────┘     └───────────────────┘     └────────┬────────┘ │
│                                                               │          │
│                                                               ▼          │
│  ┌──────────────────┐     ┌───────────────────┐     ┌─────────────────┐ │
│  │  Gemini 2.5      │◀────│  OTA Extractor    │◀────│  Raw Email     │ │
│  │  (AI Parser)     │     │  (AI Extraction)  │     │  HTML Content  │ │
│  └──────────────────┘     └─────────┬─────────┘     └─────────────────┘ │
│                                    │                                   │
│                                    ▼                                   │
│  ┌──────────────────┐     ┌───────────────────┐     ┌─────────────────┐ │
│  │  Hotel Mapper    │◀────│  OTA Integration  │────▶│  Booking DB     │ │
│  │  (Branch Match)  │     │  (Upsert Logic)   │     │  (bookings)     │ │
│  └──────────────────┘     └───────────────────┘     └─────────────────┘ │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Files

```
app/services/ota_agent/
├── gmail_service.py       # Gmail API + Pub/Sub Push Notification
├── extractor.py           # Gemini AI email parser (Gemini 2.5 Flash)
├── mapper.py             # Hotel/Branch name fuzzy matching
├── integration.py         # OTAAgent: email → booking pipeline
├── listener.py            # Legacy IMAP listener (deprecated)
└── ota_service.py         # OTA Dashboard service layer

app/api/ota_dashboard.py   # OTA Dashboard API endpoints
app/db/models.py           # Booking, OTAParsingLog models
app/templates/ota_dashboard.html # OTA Dashboard UI
```

### Supported OTA Channels

| OTA | Email Domain | Special Notes |
|-----|--------------|---------------|
| **Booking.com** | @booking.com | Standard format |
| **Agoda** | @agoda.com | Net rate vs Reference rate distinction |
| **Traveloka** | @traveloka.com | Vietnamese format |
| **Go2Joy** | @go2joy.vn | Hourly bookings, use "Tiền phòng" not "Tổng tiền" |
| **Airbnb** | @airbnb.com | Use "Bạn kiếm được" (host payout) not total |
| **Mytour** | @mytour.vn | Use "Tổng tiền trả khách sạn" |
| **Trip.com** | @trip.com, @ctrip.com | International format |
| **Website** | binbinhotel.ota@gmail.com | Direct booking from hotel website |

### Luồng xử lý email

```
1. Gmail Push Notification (Pub/Sub)
   └── Webhook: POST /api/ota/webhook/gmail
   └── Background task: _process_gmail_push()

2. Email Fetch
   └── gmail_service.fetch_new_emails_from_history()
   └── Filter by OTA sender domains (settings.OTA_SENDERS)

3. Subject Filtering (trước khi gọi AI)
   ├── Skip: báo cáo, newsletter, marketing
   ├── Process: booking keywords (xác nhận, đặt phòng, confirmation)
   └── Unknown: vẫn xử lý (để AI quyết định)

4. AI Extraction (Gemini 2.5 Flash)
   └── extractor.extract_data(html, sender, subject)
   └── Rate limiter: 1 call / 10 giây (free tier 10 RPM)
   └── Retry: 2 lần với backoff 10s → 30s

5. Branch Mapping (HotelMapper)
   ├── Ưu tiên 1: Hardcoded aliases (HOTEL_ALIASES)
   ├── Ưu tiên 2: Exact match với Branch.name
   └── Ưu tiên 3: Fuzzy match (thefuzz, score >= 50)
   └── Website bookings: parse branch code từ room_type "(B2)"

6. Booking Upsert
   ├── NEW: Tạo booking mới nếu chưa tồn tại (external_id unique)
   ├── MODIFY: Cập nhật thông tin booking đã có
   └── CANCEL: Cập nhật status = CANCELLED
```

### Database Models (OTA Layer)

```python
# Booking - Đặt phòng từ OTA
Booking:
    id: BIGINT (PK)
    booking_source: String(50)      # Booking.com, Agoda, Go2Joy, Website...
    external_id: String(50)          # Mã đặt phòng OTA (unique với source)
    
    guest_name: String(255)          # Tên khách
    guest_phone: String(50)         # SĐT khách
    checkin_code: String(50)       # Mã PIN check-in
    
    check_in: Date                  # Ngày nhận phòng
    check_out: Date                 # Ngày trả phòng
    room_type: String(255)          # Loại phòng (từ email OTA)
    
    num_guests: Integer = 1
    num_adults: Integer = 1
    num_children: Integer = 0
    
    total_price: NUMERIC(15,2)     # Tổng tiền
    currency: String(10) = 'VND'
    is_prepaid: Boolean            # Đã thanh toán online chưa
    payment_method: String(100)    # Visa, Cash...
    deposit_amount: NUMERIC(15,2)  # Tiền đặt cọc đã trả
    
    status: BookingStatus          # CONFIRMED | CANCELLED | COMPLETED | NO_SHOW
    branch_id: Integer (FK)        # Chi nhánh (mapped từ hotel name)
    
    raw_data: JSONB                # Full AI extracted data
    created_at: DateTime
    updated_at: DateTime

# OTAParsingLog - Log xử lý email
OTAParsingLog:
    id: BIGINT (PK)
    received_at: DateTime          # Thời điểm nhận email
    
    email_subject: String(500)
    email_sender: String(255)
    email_message_id: String(255)  # Gmail message ID (unique, dedup)
    
    status: OTAParsingStatus        # SUCCESS | FAILED
    error_message: Text            # Lỗi nếu có
    error_traceback: Text           # Full stack trace
    
    raw_content: Text              # Email HTML gốc
    extracted_data: JSONB          # AI extracted data
    
    retry_count: Integer = 0       # Số lần retry
    last_retry_at: DateTime
    booking_id: BIGINT (FK)        # Booking đã tạo (nếu có)
```

### Gemini AI Extraction (extractor.py)

```python
# Prompt cho Gemini 2.5 Flash trích xuất booking data:
OTAExtractor:
    - Input: Clean HTML email content
    - Output: JSON với cấu trúc chuẩn
    - Special rules per OTA:
      
      Agoda:
        - Dùng "Net rate (incl. taxes & fees)" KHÔNG phải "Reference sell rate"
      
      Go2Joy:
        - Dùng "Tiền phòng" KHÔNG phải "Số tiền thanh toán"
        - Default is_prepaid = True nếu không nói rõ
      
      Airbnb:
        - LUÔN dùng "Bạn kiếm được" (host payout) KHÔNG phải "Tổng"
      
      Mytour:
        - Dùng "Tổng tiền trả khách sạn"
      
      Website:
        - External ID format: "WEB-{order_number}"
        - Default is_prepaid = False
```

### Branch Mapping (mapper.py)

```python
# Alias cứng cho các chi nhánh có tên thương hiệu khác tên hệ thống:
HOTEL_ALIASES = {
    "bin bin mimosa": "Bin Bin Hotel 10",
    "mimosa": "Bin Bin Hotel 10",
    "bin bin hotel 10 - mimosa near tan son nhat airport": "Bin Bin Hotel 10",
    "bin bin hotel 8 - near sunrise city district 7": "Bin Bin Hotel 8",
}

# Website bookings: branch code encoded trong room_type
# Ví dụ: "Superior Room (B2)" → branch_code "B2" → Bin Bin Hotel 2
def get_branch_id_from_room_type(room_type):
    match = re.search(r"\((B\d+)\)", room_type, re.IGNORECASE)
    # → branch_id from branch_code_map
```

### OTA Dashboard Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/ota/dashboard` | GET | OTA Dashboard UI |
| `/api/ota/stats` | GET | Booking statistics |
| `/api/ota/bookings` | GET | List bookings với filters |
| `/api/ota/bookings/{id}` | PUT | Update booking (admin/letan) |
| `/api/ota/bookings/{id}` | DELETE | Delete booking (admin only) |
| `/api/ota/logs` | GET | Parsing logs |
| `/api/ota/distribution` | GET | Bookings by OTA channel |
| `/api/ota/failed-emails` | GET | Failed email list |
| `/api/ota/retry/{log_id}` | POST | Retry failed email |
| `/api/ota/health` | GET | OTA agent health status |
| `/api/ota/timeline-stats` | GET | Success rate over time |
| `/api/ota/webhook/gmail` | POST | Gmail Pub/Sub webhook |
| `/api/ota/gmail/watch` | POST | Register Gmail watch |
| `/api/ota/gmail/status` | GET | Gmail push status |
| `/api/ota/scan-today` | POST | Manual email scan |

### Gmail Push Notification Setup

```bash
# 1. Google Cloud Console:
#    - Enable Gmail API
#    - Create Pub/Sub Topic
#    - Set permissions: gmail-api-push@system.gserviceaccount.com as Publisher

# 2. OAuth Setup:
python scripts/gmail_auth.py

# 3. Register Watch:
POST /api/ota/gmail/watch

# 4. Environment Variables:
GMAIL_TOKEN_JSON= {...}           # OAuth token (JSON)
GOOGLE_PUBSUB_TOPIC=projects/xxx  # Pub/Sub topic
GMAIL_WATCH_EMAIL=binbinhotel.ota@gmail.com
OTA_SENDERS=agoda.com,go2joy.vn,booking.com,traveloka.com,airbnb.com,mytour.vn
GEMINI_API_KEY=xxx                 # Gemini API key
```

### Rate Limiting & Retry

```python
# Gemini Rate Limiter (Global)
_MIN_CALL_INTERVAL = 10.0  # 1 call / 10s (10 RPM free tier)

# Retry on 429 (Rate Limit):
# - Attempt 1: wait 10s
# - Attempt 2: wait 30s
# - After 429: global backoff 60s

# Retry on failure:
# - retry_count tracking in OTAParsingLog
# - Manual retry via /api/ota/retry/{log_id}
# - Bulk retry via /api/ota/bulk-retry
```

### Activity Types (OTA)

```python
# Khi booking được tạo/cập nhật từ OTA:
GuestActivity:
    activity_type: "BOOKING_CREATED" | "BOOKING_MODIFIED" | "BOOKING_CANCELLED"
    activity_group: "booking"
    source: "ota"
    booking_id: <id>
    branch_id: <branch_id>
```

### Common Tasks

```python
# 1. Retry failed email manually
from app.services.ota_agent.integration import ota_agent
from app.services.ota_agent.mapper import HotelMapper
from app.db.session import SessionLocal

db = SessionLocal()
mapper = HotelMapper(db)
log = db.query(OTAParsingLog).filter(OTAParsingLog.id == log_id).first()

# Re-process với email data
ota_agent.process_email(db, mapper, {
    'subject': log.email_subject,
    'sender': log.email_sender,
    'html': log.raw_content,
    'message_id': log.email_message_id,
})

# 2. Check OTA health
GET /api/ota/health
# Returns: {last_success, recent_failures, emails_today, success_rate}

# 3. Manual scan emails for a date
POST /api/ota/scan-today?scan_date=2026-04-30

# 4. Update Gmail watch
POST /api/ota/gmail/watch

# 5. Export logs
GET /api/ota/export/logs?format=csv
GET /api/ota/export/failed-emails?format=json
```

### OTA Booking Source Tags (CRM)

```python
# Khi khách check-in từ OTA:
# → Gắn tag 'OTA' vào Guest.tags
# → booking_source được lưu trong GuestStaySummary.source

GuestStaySummary:
    source: String(20)   # pms|ota|walkin
```

### Limitations & Future Enhancements

```python
# Hiện tại (Email Parsing):
✅ Email → AI → Booking (near real-time)
✅ Support nhiều OTA channels
✅ Fuzzy branch matching
✅ Rate limiting & retry

# Cần nâng cấp (Real API):
❌ Direct API integration với Booking.com, Agoda
❌ Push availability/pricing
❌ Webhook endpoints cho OTA callbacks
❌ OTA sync log (ota_sync_log table)
❌ OTA channel configuration (ota_channels table)
```

---

## Cập nhật gần đây (2026-04-30)

### Files đã modified:
- `app/api/pms/guest_crm_api.py` - CRM API endpoints
- `app/services/guest_crm_integration.py` - Checkout hooks
- `app/static/css/crm_guest_detail.css` - Styles mới
- `app/static/js/pms/crm_guest_detail.js` - Alpine.js component
- `app/templates/pms/crm_guest_detail.html` - Guest detail page
- `app/templates/pms/partials/crm_guest_detail/*.html` - Tab components
- `docs/PMS_SKILL.md` - Thêm phần OTA Integration

### Tính năng mới:
- Guest Detail Page với Alpine.js (thay vì vanilla JS cũ)
- Tier Journey visualization
- Lazy loading cho tab data
- Skeleton loading
- Responsive design
- Dark mode support
- **OTA Integration** (Booking.com, Agoda, Traveloka, Go2Joy, Airbnb, Mytour, Website)
