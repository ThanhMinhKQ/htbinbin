🧠 I. TRIẾT LÝ THIẾT KẾ (QUAN TRỌNG)

Loyalty không phải chỉ là:

“Ở 10 lần tặng 1 lần”

Mà là:

👉 Behavior-driven system
👉 Tự động hoá giữ chân khách
👉 Cá nhân hoá theo giá trị khách

🏗 II. KIẾN TRÚC TỔNG THỂ LOYALTY
Guest
 ├── LoyaltyAccount (1-1)
 ├── LoyaltyTier (N-1)
 ├── LoyaltyPointLedger (1-N)
 ├── LoyaltyReward (redeem)
 ├── LoyaltyCampaign (automation)
🧩 III. DATABASE DESIGN (FULL CHUẨN 2026)
1. loyalty_accounts
class LoyaltyAccount(Base):
    __tablename__ = "loyalty_accounts"

    id = Column(BIGINT, primary_key=True)
    guest_id = Column(BIGINT, ForeignKey("guests.id", ondelete="CASCADE"), unique=True, index=True)

    tier_id = Column(Integer, ForeignKey("loyalty_tiers.id"), index=True)

    total_points = Column(Integer, default=0)
    lifetime_points = Column(Integer, default=0)

    total_spent = Column(NUMERIC(15,2), default=0)
    total_stays = Column(Integer, default=0)

    last_activity_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    guest = relationship("Guest")
    tier = relationship("LoyaltyTier")
2. loyalty_tiers (phân hạng khách)
class LoyaltyTier(Base):
    __tablename__ = "loyalty_tiers"

    id = Column(Integer, primary_key=True)
    name = Column(String(50))  # Silver, Gold, Platinum

    min_points = Column(Integer, default=0)
    min_spent = Column(NUMERIC(15,2), default=0)

    benefits = Column(JSONB)  # {"late_checkout": true, "discount": 10}

    priority = Column(Integer)  # dùng để sort

    created_at = Column(DateTime(timezone=True), server_default=func.now())
3. loyalty_point_ledger (cực kỳ quan trọng)

👉 Đây là ledger chuẩn tài chính (audit được)

class LoyaltyPointLedger(Base):
    __tablename__ = "loyalty_point_ledger"

    id = Column(BIGINT, primary_key=True)

    account_id = Column(BIGINT, ForeignKey("loyalty_accounts.id", ondelete="CASCADE"), index=True)

    change_type = Column(String(50))  
    # EARN / REDEEM / EXPIRE / ADJUST

    points = Column(Integer)  # +100 hoặc -50

    balance_after = Column(Integer)

    ref_type = Column(String(50))  # stay / booking / campaign
    ref_id = Column(BIGINT)

    description = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("LoyaltyAccount")

👉 Đây là thứ giúp bạn:

debug sai điểm
audit nhân viên gian lận
tracking hành vi khách
4. loyalty_rewards (đổi thưởng)
class LoyaltyReward(Base):
    __tablename__ = "loyalty_rewards"

    id = Column(BIGINT, primary_key=True)

    name = Column(String(255))
    points_required = Column(Integer)

    reward_type = Column(String(50))  
    # DISCOUNT / FREE_NIGHT / SERVICE

    value = Column(NUMERIC(15,2))

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
5. loyalty_redemptions
class LoyaltyRedemption(Base):
    __tablename__ = "loyalty_redemptions"

    id = Column(BIGINT, primary_key=True)

    account_id = Column(BIGINT, ForeignKey("loyalty_accounts.id"))
    reward_id = Column(BIGINT, ForeignKey("loyalty_rewards.id"))

    points_used = Column(Integer)

    stay_id = Column(BIGINT, nullable=True)

    status = Column(String(50))  # USED / CANCELLED

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("LoyaltyAccount")
    reward = relationship("LoyaltyReward")
6. loyalty_campaigns (automation – cực mạnh)
class LoyaltyCampaign(Base):
    __tablename__ = "loyalty_campaigns"

    id = Column(BIGINT, primary_key=True)

    name = Column(String(255))

    trigger_type = Column(String(50))  
    # AFTER_STAY / BIRTHDAY / INACTIVE_30_DAYS

    rule = Column(JSONB)
    # {"min_stay": 3} hoặc {"inactive_days": 30}

    reward_points = Column(Integer)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
⚙️ IV. BUSINESS LOGIC (CÁI QUAN TRỌNG NHẤT)
1. Earn points

Ví dụ:

100,000 VND = 1 point
points = total_spent / 100000

Trigger:

check-out
booking completed
2. Auto upgrade tier
if total_spent > 50 triệu:
    upgrade GOLD

👉 chạy:

sau mỗi stay
hoặc cron job nightly
3. Expire points
points expire after 12 months

→ tạo job:

cron: daily
4. Campaign automation

Ví dụ:

30 ngày chưa quay lại → tặng 50 điểm
sinh nhật → tặng voucher
📊 V. TÍCH HỢP VỚI HỆ THỐNG HIỆN TẠI
Kết nối với:
1. HotelStay
checkout → earn points
no-show → không cộng
2. Folio
lấy total_spent chuẩn
tránh fake dữ liệu
3. Booking
OTA → có thể hạn chế điểm
direct → bonus
4. Guest Activity

👉 cực quan trọng:

GUEST_ACTIVITY:
type = LOYALTY_EARN
type = LOYALTY_REDEEM
🧠 VI. UI/UX (2026)
Dashboard khách

Hiển thị:

Tier: Gold
Points: 1,250
Progress bar lên tier tiếp theo
Nhân viên lễ tân
thấy ngay:
🔥 VIP GOLD
👉 hay quay lại
👉 nên upgrade phòng
Automation
gửi Zalo / SMS:
"Anh đã có 500 điểm, đổi được 1 đêm miễn phí"
🚀 VII. NHỮNG THỨ PMS CŨ KHÔNG CÓ (NHƯNG 2026 PHẢI CÓ)

👉 Bạn nên làm thêm:

1. Dynamic loyalty (AI nhẹ)
khách hay đi cuối tuần → tặng điểm cuối tuần
khách hay book giờ → ưu đãi giờ
2. Hidden VIP tier
không public
chỉ internal biết
3. Fraud detection
nhân viên tự cộng điểm
booking fake
4. Multi-branch loyalty
điểm dùng toàn hệ thống
📌 KẾT LUẬN

Nếu bạn build đúng hệ này:

👉 Bạn đang có:

CRM chuẩn
Retention engine
Marketing automation nền tảng