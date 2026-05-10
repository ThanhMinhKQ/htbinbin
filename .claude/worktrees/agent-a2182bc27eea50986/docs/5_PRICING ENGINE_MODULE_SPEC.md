I. 🎯 Mục tiêu

Hệ thống pricing phải trả lời được:

Giá hôm nay là bao nhiêu?
OTA và walk-in có giá khác nhau không?
Có giá theo ngày lễ, cuối tuần không?
Còn ít phòng → có tăng giá không?
Khách ở lâu → có giảm không?

👉 Tóm lại:

PRICE = f(date, room_type, demand, channel, rule)
II. 🚨 Vấn đề DB hiện tại của bạn

Bạn đang có:

HotelRoomType.price_per_night

❌ Đây là giá cứng (static price)
→ không dùng được cho OTA / dynamic pricing

III. 🧠 Kiến trúc chuẩn 2026
3 layer pricing:
Base Rate → Rate Plan → Dynamic Adjustment
IV. 🧱 DATABASE DESIGN
1. 🧾 rate_plans (GÓI GIÁ)
rate_plans

| Field               | Type     | Ý nghĩa                             |
| ------------------- | -------- | ----------------------------------- |
| id                  | BIGINT   | PK                                  |
| name                | VARCHAR  | "Standard", "Non-refundable", "OTA" |
| code                | VARCHAR  | STD / OTA / NR                      |
| is_active           | BOOL     |                                     |
| cancellation_policy | TEXT     |                                     |
| is_refundable       | BOOL     |                                     |
| meal_included       | BOOL     |                                     |
| created_at          | DATETIME |                                     |

👉 Ví dụ:

Standard
OTA Booking.com
Non-refundable (rẻ hơn 10%)
2. 💵 room_rates_daily (GIÁ THEO NGÀY)
room_rates_daily

| Field        | Type     |
| ------------ | -------- |
| id           | BIGINT   |
| branch_id    | FK       |
| room_type_id | FK       |
| rate_plan_id | FK       |
| date         | DATE     |
| base_price   | NUMERIC  |
| final_price  | NUMERIC  |
| min_stay     | INT      |
| max_stay     | INT      |
| closed       | BOOL     |
| created_at   | DATETIME |

👉 UNIQUE:

(branch_id, room_type_id, rate_plan_id, date)

👉 Đây là bảng quan trọng nhất của pricing

3. ⚙️ pricing_rules (RULE ENGINE)
pricing_rules

| Field          | Type    |
| -------------- | ------- |
| id             | BIGINT  |
| name           | VARCHAR |
| rule_type      | ENUM    |
| condition_json | JSONB   |
| action_json    | JSONB   |
| priority       | INT     |
| is_active      | BOOL    |

👉 rule_type:
OCCUPANCY
DATE_RANGE
DAY_OF_WEEK
LENGTH_OF_STAY
CHANNEL
👉 Ví dụ:
{
  "condition": {
    "available_rooms": "< 3"
  },
  "action": {
    "increase_percent": 20
  }
}
4. 🔗 channel_rate_mapping
channel_rate_mapping

| Field            | Type    |                 |
| ---------------- | ------- | --------------- |
| id               | BIGINT  |                 |
| channel          | VARCHAR | booking / agoda |
| room_type_id     | FK      |                 |
| rate_plan_id     | FK      |                 |
| external_rate_id | VARCHAR |                 |

👉 mapping với OTA

V. 🔄 FLOW PRICING
1. 🧮 Khi query giá
get_price(date, room_type, channel)
Step 1:
Load room_rates_daily
Step 2:

Apply rules:

pricing_rules
Step 3:

Check inventory:

if available < threshold → tăng giá
Step 4:

Return final_price

2. 📅 Batch generate giá

Cron job mỗi ngày:

Generate next 365 days
Logic:
base_price = HotelRoomType.price_per_night

if weekend:
    +20%

if holiday:
    +50%
3. 📉 Length of stay pricing
Stay 3 nights → giảm 10%
4. 🌐 OTA pricing
OTA price = base_price + commission

👉 Ví dụ:

Walk-in: 500k
OTA: 600k
VI. 🔥 Dynamic Pricing (CỰC QUAN TRỌNG)
Ví dụ thực tế:
Available	Action
>10	giảm 10%
5–10	giữ
<5	tăng 20%

👉 Code logic:

if available_rooms < 3:
    price *= 1.2
VII. 🧠 Mapping với Inventory

👉 Pricing phụ thuộc:

room_inventory_daily.available_rooms

👉 Đây là lý do:

Pricing luôn phải gọi inventory
Không được tách rời
VIII. 🔐 Stop Sell / Close Rate
closed = true

→ không bán

IX. 🚀 Advanced Features (2026)
1. AI Pricing (optional)
dự đoán demand
auto adjust giá
2. Competitor Pricing
scrape OTA
so sánh giá
3. Yield Management
tối đa hóa revenue
X. 🚨 Sai lầm phổ biến

❌ Chỉ dùng 1 giá duy nhất
❌ Không lưu giá theo ngày
❌ Không có rate plan
❌ Pricing không liên kết inventory

XI. 🎯 Kết luận

👉 Nếu Room Inventory là “trái tim”
👉 Thì Pricing Engine là “bộ não kiếm tiền”