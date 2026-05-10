"""
PMS Pricing Engine — Time-Slicing + Rule-Based + BAR Simulation

Thay thế procedural 3-phase (Early/Core/Late) bằng:
  1. Timeline Normalization  — Grace Period thông minh
  2. Time Slice Engine      — Cắt trục thời gian theo mốc giờ chuẩn
  3. Rule Evaluator         — Áp dụng luật cho từng slice
  4. BAR Simulator          — So sánh HOURLY vs DAILY, chọn tối ưu
  5. Breakdown Yield        — Trả về breakdown chi tiết

Backward-compatible: pricing_service.py giữ nguyên signature,
bên trong gọi sang PricingEngine.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time, date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from ..db.models import HotelRoomType
from ..core.utils import VN_TZ

_MONEY_QUANT = Decimal("0.01")


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class TimeSlice:
    """Một khoảng thời gian liên tục, không đè lên nhau."""
    start: datetime
    end: datetime
    slice_type: str  # 'early' | 'core' | 'late' | 'night' | 'overflow'
    belongs_to_day: date    # Hotel day mà slice này thuộc về
    duration_minutes: float
    description: str = ""

    @property
    def duration_hours(self) -> float:
        return self.duration_minutes / 60.0


@dataclass
class ScenarioResult:
    """Kết quả tính giá của một kịch bản (HOURLY hoặc DAILY)."""
    mode: str              # 'HOURLY' | 'DAILY'
    total: Decimal
    breakdown: list[dict] = field(default_factory=list)

    def __lt__(self, other: ScenarioResult) -> bool:
        return self.total < other.total


# ─── Money Helpers ─────────────────────────────────────────────────────────────

def _money(value) -> Decimal:
    if value is None or value == "":
        raw = Decimal("0")
    elif isinstance(value, Decimal):
        raw = value
    else:
        raw = Decimal(str(value).strip())
    return raw.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)


def _ceil_hours(minutes: float, grace: int) -> int:
    if minutes <= grace:
        return 0
    return math.ceil((minutes - grace) / 60.0)


# ─── Night Promo ───────────────────────────────────────────────────────────────

def _night_promo_applies(room_type: HotelRoomType, check_in: datetime) -> bool:
    if not (room_type.promo_start_time and room_type.promo_end_time):
        return False

    ci_time = check_in.time()
    start = room_type.promo_start_time
    end = room_type.promo_end_time

    if start <= end:
        return start <= ci_time <= end
    return ci_time >= start or ci_time <= end


def _get_night_promo_amount(room_type: HotelRoomType, price: Decimal) -> Decimal:
    try:
        fixed_amount = _money(getattr(room_type, "promo_discount_amount", 0) or 0)
    except Exception:
        fixed_amount = Decimal("0.00")
    if fixed_amount > 0:
        return min(fixed_amount, price)

    # Backward compatibility for room types created before fixed discount amount.
    try:
        legacy_pct = Decimal(str(getattr(room_type, "promo_discount_percent", 0) or 0))
    except Exception:
        legacy_pct = Decimal("0")
    if legacy_pct > 0:
        return min(_money(price * legacy_pct / Decimal("100")), price)
    return Decimal("0.00")


def _apply_night_promo(price: Decimal, room_type: HotelRoomType, check_in: datetime) -> Decimal:
    if not _night_promo_applies(room_type, check_in):
        return price

    discount_amount = _get_night_promo_amount(room_type, price)
    if discount_amount <= 0:
        return price
    return _money(price - discount_amount)


# ─── PricingEngine ─────────────────────────────────────────────────────────────

class PricingEngine:
    """
    Time-Slicing + Rule-Based Pricing Engine.

    Luồng xử lý:
      evaluate(check_in, check_out, mode)
        1. _normalize()         — Grace Period normalization
        2. _slice_timeline()    — Chia thành các TimeSlice
        3. _build_rules()        — Load rules từ room_type config
        4. _simulate_HOURLY()    — Tính kịch bản HOURLY
        5. _simulate_DAILY()     — Tính kịch bản DAILY
        6. Chọn BAR scenario     — Trả về kịch bản rẻ hơn (mode='AUTO')
    """

    def __init__(self, room_type: HotelRoomType):
        self.rt = room_type

        # ── Pricing config ─────────────────────────────────────────────────────
        self.std_in: time = room_type.standard_checkin_time or time(14, 0)
        self.std_out: time = room_type.standard_checkout_time or time(12, 0)
        self.early_fee = _money(room_type.early_checkin_fee_per_hour or 0)
        self.late_fee = _money(room_type.late_checkout_fee_per_hour or 0)
        self.grace = getattr(room_type, 'grace_minutes', None) or 10

        # Per-hour
        self.pph = _money(room_type.price_per_hour or 0)
        self.pnh = _money(room_type.price_next_hour or 0)
        self.min_h = room_type.min_hours or 1

        # Per-night
        self.ppn = _money(room_type.price_per_night or 0)

        # Day threshold — giới hạn giờ trước khi ép chuyển thành Giá Ngày
        self.day_threshold = getattr(room_type, 'day_threshold_hours', None) or 8

        # Free early buffer: checkin từ 12:00→std_in → miễn phí early fee (CHỈ cho DAY)
        self.early_free_start: time = time(12, 0)

        # Overnight Rate — Giá ưu đãi qua đêm. New config uses a fixed VND amount.
        # Legacy percent is kept only as fallback for existing records.
        promo_amount = _get_night_promo_amount(room_type, self.ppn)
        self.overnight_rate = _money(self.ppn - promo_amount) if promo_amount > 0 else self.ppn

    # ── Bước 1: Timeline Normalization ─────────────────────────────────────────

    def _normalize(
        self, check_in: datetime, check_out: datetime
    ) -> tuple[datetime, datetime]:
        """
        Grace Period thông minh — bẻ timestamps về mốc chuẩn nếu gần.
        Giúp các Rule bên dưới cực kỳ sạch sẽ, không cần xử lý ngoại lệ.
        """
        ci = check_in.astimezone(VN_TZ) if check_in.tzinfo else VN_TZ.localize(check_in)
        co = check_out.astimezone(VN_TZ) if check_out.tzinfo else VN_TZ.localize(check_out)

        grace_d = timedelta(minutes=self.grace)

        # std_checkout_dt = check_out date + std_out
        std_out_dt = VN_TZ.localize(datetime.combine(co.date(), self.std_out))
        # Chỉ bẻ về std_out khi checkout nằm trong ±grace quanh mốc chuẩn
        if std_out_dt - grace_d <= co <= std_out_dt + grace_d:
            co = std_out_dt

        # std_checkin_dt = check_in date + std_in
        std_in_dt = VN_TZ.localize(datetime.combine(ci.date(), self.std_in))
        grace_d = timedelta(minutes=self.grace)
        # Chỉ bẻ về std_in khi check-in nằm trong ±grace quanh mốc chuẩn.
        # Tránh kéo mọi giờ sau 14:00 (vd 15:14 giờ) về 14:00 — làm sai phòng giờ và mismatch UI.
        if std_in_dt - grace_d <= ci <= std_in_dt + grace_d:
            ci = std_in_dt

        return ci, co

    # ── Bước 2: Time Slice Engine ─────────────────────────────────────────────

    def _slice_timeline(
        self, check_in: datetime, check_out: datetime
    ) -> list[TimeSlice]:
        """
        Cắt trục thời gian [check_in, check_out) thành các TimeSlice
        dựa trên standard_checkin_time và standard_checkout_time.

        Ví dụ: CI 10:00 T2, CO 15:00 T3, std_in=14:00, std_out=12:00
          Slice 1: 10:00 T2 → 14:00 T2  (type='early',  belongs_to=T2)
          Slice 2: 14:00 T2 → 12:00 T3  (type='core',   belongs_to=T2 hotel day)
          Slice 3: 12:00 T3 → 15:00 T3  (type='late',   belongs_to=T3)

        Ví dụ cross-day phức tạp: CI 22:00 T1, CO 08:00 T3
          Slice 1: 22:00 T1 → 14:00 T1  (early, T1)
          Slice 2: 14:00 T1 → 12:00 T2  (core,  T1 hotel day)
          Slice 3: 12:00 T2 → 14:00 T2  (overflow, giữa 2 hotel days)
          Slice 4: 14:00 T2 → 12:00 T3  (core,  T2 hotel day)
          Slice 5: 12:00 T3 → 08:00 T3  (late,  T3)
        """
        ci = check_in.astimezone(VN_TZ) if check_in.tzinfo else VN_TZ.localize(check_in)
        co = check_out.astimezone(VN_TZ) if check_out.tzinfo else VN_TZ.localize(check_out)

        if co <= ci:
            return []

        slices: list[TimeSlice] = []
        current = ci

        while current < co:
            current_date = current.date()
            current_time = current.time()

            # std_checkin_dt of current date
            std_in_dt = VN_TZ.localize(datetime.combine(current_date, self.std_in))
            # std_checkout_dt = NEXT day of current date
            std_out_dt = VN_TZ.localize(datetime.combine(current_date + timedelta(days=1), self.std_out))
            same_day_std_out_dt = VN_TZ.localize(datetime.combine(current_date, self.std_out))

            if current_date == co.date() and current_date > ci.date() and current >= same_day_std_out_dt:
                slice_end = co
                slices.append(TimeSlice(
                    start=current,
                    end=slice_end,
                    slice_type='late',
                    belongs_to_day=current_date,
                    duration_minutes=(slice_end - current).total_seconds() / 60.0,
                    description=f"Phí trả phòng muộn ({self.late_fee}/giờ)",
                ))
                current = slice_end
                continue

            # Mốc end của hotel day này = std_out_dt
            hotel_day_end = std_out_dt

            # Xác định loại slice dựa trên vị trí current trong hotel day
            # Xác định loại slice dựa trên vị trí current trong hotel day
            if current_time < self.std_in:
                # ── Trước std_in (vd < 14:00) ─────────────────
                prev_date = current_date - timedelta(days=1)
                prev_std_out = VN_TZ.localize(datetime.combine(prev_date + timedelta(days=1), self.std_out))
                
                # NẾU là ngày khách check-in HOẶC trước mốc std_out của ngày hôm qua => Đích thị là NHẬN PHÒNG SỚM
                if current_date == ci.date() or current < prev_std_out:
                    slice_end = min(co, std_in_dt)
                    slices.append(TimeSlice(
                        start=current,
                        end=slice_end,
                        slice_type='early',
                        belongs_to_day=current_date,
                        duration_minutes=(slice_end - current).total_seconds() / 60.0,
                        description=f"Phí nhận phòng sớm ({self.early_fee}/giờ)",
                    ))
                    current = slice_end
                    continue
                else:
                    # KHÁCH ĐÃ Ở TỪ TRƯỚC (Qua đêm) VÀ ĐANG VƯỢT MỐC TRẢ PHÒNG (12:00)
                    if co <= std_in_dt:
                        # Khách trả phòng trong khoảng gap 12:00 - 14:00
                        slices.append(TimeSlice(
                            start=current,
                            end=co,
                            slice_type='late',
                            belongs_to_day=current_date,
                            duration_minutes=(co - current).total_seconds() / 60.0,
                            description=f"Phí trả phòng muộn ({self.late_fee}/giờ)",
                        ))
                        current = co
                        continue
                    else:
                        # Khách tiếp tục ở qua mốc 14:00 (sang đêm tiếp theo) -> Đây là 2 tiếng tràn nhịp không tính phí
                        slice_end = min(co, std_in_dt)
                        slices.append(TimeSlice(
                            start=current,
                            end=slice_end,
                            slice_type='overflow',
                            belongs_to_day=current_date,
                            duration_minutes=(slice_end - current).total_seconds() / 60.0,
                            description="Vùng chờ giữa 2 ngày",
                        ))
                        current = slice_end
                        continue

            elif std_in_dt <= current < hotel_day_end:
                # ── CORE: Từ std_in ngày hiện tại → std_out *ngày hôm sau* (một hotel day)
                # Không dùng current_time < std_out vì std_out (vd 12:00) là sáng ngày sau;
                # nếu so sánh chỉ .time() thì 15:14 cùng ngày bị nhầm thành "sau std_out" → LATE.
                slice_end = min(co, hotel_day_end)
                slices.append(TimeSlice(
                    start=current,
                    end=slice_end,
                    slice_type='core',
                    belongs_to_day=current_date,
                    duration_minutes=(slice_end - current).total_seconds() / 60.0,
                    description="Tiền phòng core",
                ))
                current = hotel_day_end
                continue

            else:
                # Sau hotel_day_end của ngày bắt đầu tại current_date (legacy: current_time vs std_out)
                # ── LATE hoặc OVERFLOW ──────────────────────────────────────────
                # Nếu checkout ngay trong ngày (không qua ngày hôm sau):
                if co <= hotel_day_end:
                    # Checkout trong ngày hiện tại, sau std_out
                    slices.append(TimeSlice(
                        start=current,
                        end=co,
                        slice_type='late',
                        belongs_to_day=current_date,
                        duration_minutes=(co - current).total_seconds() / 60.0,
                        description=f"Phí trả phòng muộn ({self.late_fee}/giờ)",
                    ))
                    current = co
                    continue
                else:
                    # Trả phòng qua ngày → late cho đến hết hotel day hiện tại
                    slices.append(TimeSlice(
                        start=current,
                        end=hotel_day_end,
                        slice_type='late',
                        belongs_to_day=current_date,
                        duration_minutes=(hotel_day_end - current).total_seconds() / 60.0,
                        description=f"Phí trả phòng muộn ({self.late_fee}/giờ)",
                    ))
                    current = hotel_day_end
                    continue

        return slices

    # ── Bước 3: Simulate HOURLY scenario ───────────────────────────────────────

    def _simulate_HOURLY(
        self, slices: list[TimeSlice]
    ) -> ScenarioResult:
        """
        Tính giá theo kiểu giờ cho tất cả slices.
        Mỗi slice tính riêng: early/late dùng early_fee/late_fee,
        core dùng pph + pnh, overflow = 0.

        Spec v3 — Early Fee Buffer:
          Check-in 12:00–13:59 → miễn phí early fee.
          Check-in trước 12:00 → tính phí từ checkin đến 14:00.

        Spec v3 — Day Rollover:
          Nếu late_hours >= day_threshold → cộng ppn thay vì tính late fee.
        """
        total = Decimal("0")
        breakdown: list[dict] = []

        for sl in slices:
            if sl.slice_type == 'early':
                # HOURLY mode: Không áp dụng Early Fee Buffer (Rule 2 chỉ cho DAY)
                # Tính phí sớm bình thường
                hrs = _ceil_hours(sl.duration_minutes, self.grace)
                if hrs > 0:
                    amt = self.early_fee * Decimal(str(hrs))
                    total += amt
                    breakdown.append({
                        "type": "EARLY_CHECKIN_FEE",
                        "description": f"Nhận phòng sớm ({hrs}h)",
                        "hours": hrs,
                        "amount": amt,
                        "slice_type": "early",
                        "start_iso": sl.start.isoformat(),
                        "end_iso": sl.end.isoformat(),
                    })

            elif sl.slice_type == 'core':
                # Core hours: KHÔNG áp dụng grace.
                hrs = math.ceil(sl.duration_minutes / 60.0)
                hrs = max(self.min_h, hrs)
                
                base_amt = self.pph * Decimal(str(self.min_h))
                total += _money(base_amt)
                breakdown.append({
                    "type": "HOURLY_CHARGE",
                    "description": f"Tiền phòng theo giờ ({self.min_h}h đầu)",
                    "hours": self.min_h,
                    "mode": "HOURLY",
                    "amount": _money(base_amt),
                    "slice_type": "core",
                    "start_iso": sl.start.isoformat(),
                    "end_iso": sl.end.isoformat(),
                })

                extra_hrs = hrs - self.min_h
                if extra_hrs > 0:
                    extra_amt = self.pnh * Decimal(str(extra_hrs))
                    total += _money(extra_amt)
                    breakdown.append({
                        "type": "HOURLY_CHARGE",
                        "description": f"Tiền phòng giờ tiếp theo ({extra_hrs}h)",
                        "hours": extra_hrs,
                        "mode": "HOURLY",
                        "amount": _money(extra_amt),
                        "slice_type": "core",
                        "start_iso": sl.start.isoformat(),
                        "end_iso": sl.end.isoformat(),
                    })

            elif sl.slice_type == 'late':
                hrs = _ceil_hours(sl.duration_minutes, self.grace)
                if hrs > 0:
                    # ─── DAY ROLLOVER TRIGGER (Spec v3, Section 5) ──────────────
                    # Nếu trả phòng muộn >= day_threshold giờ → cộng 1 ngày mới
                    if hrs >= self.day_threshold:
                        amt = self.ppn
                        total += amt
                        breakdown.append({
                            "type": "ROOM_CHARGE",
                            "description": f"Trả phòng muộn → Tính thêm 1 ngày",
                            "hours": hrs,
                            "amount": amt,
                            "slice_type": "late",
                            "day_rollover": True,
                            "start_iso": sl.start.isoformat(),
                            "end_iso": sl.end.isoformat(),
                        })
                    else:
                        amt = self.late_fee * Decimal(str(hrs))
                        total += amt
                        breakdown.append({
                            "type": "LATE_CHECKOUT_FEE",
                            "description": f"Trả phòng muộn ({hrs}h)",
                            "hours": hrs,
                            "amount": amt,
                            "slice_type": "late",
                            "start_iso": sl.start.isoformat(),
                            "end_iso": sl.end.isoformat(),
                        })

            # overflow: không tính tiền

        return ScenarioResult(mode="HOURLY", total=_money(total), breakdown=breakdown)

    # ── Bước 3b: Pure Hourly (không dùng slice) ─────────────────────────────────

    def _simulate_PURE_HOURLY(
        self, check_in: datetime, check_out: datetime
    ) -> ScenarioResult:
        """
        Tính giá thuê giờ thuần túy: bỏ qua hotel-day slice logic hoàn toàn.
        Dùng cho FORCE_HOURLY (→ thuê giờ) nhậm tránh lỗi:
        - Check-in giữa 12:00–14:00 bị phân loại là 'late' của ngày hôm trước

        Logic:
          total_minutes = checkOut - checkIn
          hrs = max(min_h, ceil((total_minutes - grace) / 60))  si total > grace
               = min_h                                           si total <= grace
          cost = pph * 1 + pnh * (hrs - 1)
        """
        ci = check_in.astimezone(VN_TZ) if check_in.tzinfo else VN_TZ.localize(check_in)
        co = check_out.astimezone(VN_TZ) if check_out.tzinfo else VN_TZ.localize(check_out)

        total_minutes = (co - ci).total_seconds() / 60.0
        hrs = _ceil_hours(total_minutes, self.grace)
        hrs = max(self.min_h, hrs)

        base_amt = self.pph * Decimal(str(self.min_h))
        amt_total = _money(base_amt)
        breakdown = [{
            "type": "HOURLY_CHARGE",
            "description": f"Tiền phòng theo giờ ({self.min_h}h đầu)",
            "hours": self.min_h,
            "mode": "HOURLY",
            "amount": _money(base_amt),
            "slice_type": "core",
            "start_iso": ci.isoformat(),
            "end_iso": co.isoformat(),
        }]

        extra_hrs = hrs - self.min_h
        if extra_hrs > 0:
            extra_amt = self.pnh * Decimal(str(extra_hrs))
            amt_total += _money(extra_amt)
            breakdown.append({
                "type": "HOURLY_CHARGE",
                "description": f"Tiền phòng giờ tiếp theo ({extra_hrs}h)",
                "hours": extra_hrs,
                "mode": "HOURLY",
                "amount": _money(extra_amt),
                "slice_type": "core",
                "start_iso": ci.isoformat(),
                "end_iso": co.isoformat(),
            })

        return ScenarioResult(mode="HOURLY", total=amt_total, breakdown=breakdown)

    # ── Bước 4: Simulate DAILY scenario ────────────────────────────────────────

    def _simulate_DAILY(
        self, slices: list[TimeSlice]
    ) -> ScenarioResult:
        """
        Tính giá theo kiểu ngày: mỗi core slice = 1 đêm.
        Early/late tính phí riêng. Overflow = 0.
        Áp dụng night promo cho core slices.

        Spec v3 — Early Fee Buffer + Day Rollover (same rules as HOURLY).
        """
        total = Decimal("0")
        breakdown: list[dict] = []

        for sl in slices:
            if sl.slice_type == 'early':
                # ─── EARLY FEE BUFFER (Spec v3, Rule 2) ────────────────────────
                ci_time = sl.start.time()
                if ci_time >= self.early_free_start:
                    # Free buffer 12:00–14:00 → skip fee
                    breakdown.append({
                        "type": "EARLY_CHECKIN_FEE",
                        "description": "Nhận phòng sớm (miễn phí 12:00–14:00)",
                        "hours": 0,
                        "amount": Decimal("0"),
                        "slice_type": "early",
                        "free_buffer": True,
                        "start_iso": sl.start.isoformat(),
                        "end_iso": sl.end.isoformat(),
                    })
                else:
                    hrs = _ceil_hours(sl.duration_minutes, self.grace)
                    if hrs > 0:
                        amt = self.early_fee * Decimal(str(hrs))
                        total += amt
                        breakdown.append({
                            "type": "EARLY_CHECKIN_FEE",
                            "description": f"Nhận phòng sớm ({hrs}h)",
                            "hours": hrs,
                            "amount": amt,
                            "slice_type": "early",
                            "start_iso": sl.start.isoformat(),
                            "end_iso": sl.end.isoformat(),
                        })

            elif sl.slice_type == 'core':
                # Mỗi core slice = 1 đêm
                days = math.ceil(sl.duration_minutes / (24 * 60))
                days = max(1, days)
                amt = self.ppn * Decimal(str(days))
                # Áp dụng promo nếu đủ điều kiện
                amt = _apply_night_promo(amt, self.rt, sl.start)
                total += amt
                breakdown.append({
                    "type": "ROOM_CHARGE",
                    "description": f"Tiền phòng ({days} đêm)",
                    "days": days,
                    "mode": "DAILY",
                    "amount": amt,
                    "slice_type": "core",
                    "night_promo_applied": amt < self.ppn * Decimal(str(days)),
                    "start_iso": sl.start.isoformat(),
                    "end_iso": sl.end.isoformat(),
                })

            elif sl.slice_type == 'late':
                hrs = _ceil_hours(sl.duration_minutes, self.grace)
                if hrs > 0:
                    # ─── DAY ROLLOVER TRIGGER (Spec v3, Section 5) ──────────────
                    if hrs >= self.day_threshold:
                        amt = self.ppn
                        total += amt
                        breakdown.append({
                            "type": "ROOM_CHARGE",
                            "description": f"Trả phòng muộn → Tính thêm 1 ngày",
                            "hours": hrs,
                            "amount": amt,
                            "slice_type": "late",
                            "day_rollover": True,
                            "start_iso": sl.start.isoformat(),
                            "end_iso": sl.end.isoformat(),
                        })
                    else:
                        amt = self.late_fee * Decimal(str(hrs))
                        total += amt
                        breakdown.append({
                            "type": "LATE_CHECKOUT_FEE",
                            "description": f"Trả phòng muộn ({hrs}h)",
                            "hours": hrs,
                            "amount": amt,
                            "slice_type": "late",
                            "start_iso": sl.start.isoformat(),
                            "end_iso": sl.end.isoformat(),
                        })

            # overflow: không tính
            
        has_core = any(sl.slice_type == 'core' for sl in slices)
        if not has_core:
            # Nếu khách check-in và lọt hoàn toàn trong khung Early hoặc Late mà chưa chạm Core
            # nhưng lại đang chạy giá Ngày (DAILY) -> Bắt buộc thanh toán tối thiểu 1 đêm tiền phòng
            total += self.ppn
            breakdown.append({
                "type": "ROOM_CHARGE",
                "description": "Tiền phòng tối thiểu (chưa chạm khung giờ Core)",
                "days": 1,
                "mode": "DAILY",
                "amount": self.ppn,
                "slice_type": "core",
            })

        return ScenarioResult(mode="DAILY", total=_money(total), breakdown=breakdown)

    def _apply_extra_days_and_late_checkout(
        self, co: datetime, std_out_dt: datetime, total: Decimal, breakdown: list
    ) -> tuple[Decimal, list]:
        """
        Tính số tiền lưu trú thêm cho các chế độ ưu đãi Qua Đêm khi khách ở vắt qua ngày hôm sau nữa.
        Tách phần dư thành các đêm bổ sung (extra_nights) và trả phòng muộn (late_minutes).
        """
        if co <= std_out_dt:
            return total, breakdown
            
        total_extra_minutes = (co - std_out_dt).total_seconds() / 60.0
        extra_nights = int(total_extra_minutes // (24 * 60))
        late_minutes = total_extra_minutes % (24 * 60)
        
        std_out_dt_after_nights = std_out_dt + timedelta(days=extra_nights)
        
        if extra_nights > 0:
            amt = self.ppn * Decimal(str(extra_nights))
            total += amt
            breakdown.append({
                "type": "ROOM_CHARGE",
                "description": f"Tiền phòng ({extra_nights} đêm)",
                "days": extra_nights,
                "mode": "DAILY",
                "amount": amt,
                "slice_type": "core",
                "start_iso": std_out_dt.isoformat(),
                "end_iso": std_out_dt_after_nights.isoformat(),
            })
            
        hrs = _ceil_hours(late_minutes, self.grace)
        if hrs > 0:
            if hrs >= self.day_threshold:
                amt = self.ppn
                total += amt
                breakdown.append({
                    "type": "ROOM_CHARGE",
                    "description": f"Trả phòng muộn → Tính thêm 1 ngày",
                    "hours": hrs,
                    "amount": amt,
                    "slice_type": "late",
                    "day_rollover": True,
                    "start_iso": std_out_dt_after_nights.isoformat(),
                    "end_iso": co.isoformat(),
                })
            else:
                amt = self.late_fee * Decimal(str(hrs))
                total += amt
                breakdown.append({
                    "type": "LATE_CHECKOUT_FEE",
                    "description": f"Trả phòng muộn ({hrs}h)",
                    "hours": hrs,
                    "amount": amt,
                    "slice_type": "late",
                    "start_iso": std_out_dt_after_nights.isoformat(),
                    "end_iso": co.isoformat(),
                })
                
        return total, breakdown

    # ── Bước 5b: Simulate OVERNIGHT sớm (pre-midnight) ──────────────────────

    def _simulate_OVERNIGHT_EARLY(
        self, check_in: datetime, check_out: datetime
    ) -> ScenarioResult:
        """
        Spec Luồng 3.2: Khách vào tối (14:00–23:59) muốn tính Qua đêm.

        Overnight_Candidate = Overnight_Rate + (00:00 - Checkin_Time) * Surcharge_Rate
        Anti-loss: Nếu Overnight_Candidate >= Day_Rate (ppn) → ép DAY.

        Ví dụ (Suite: Giá ngày 750k, Qua đêm 600k):
          Vào 23:00 → 600k + (1h x 50k) = 650k < 750k → OK được áp dụng
          Vào 21:00 → 600k + (3h x 50k) = 750k >= 750k → Ép về Giá Ngày
        """
        ci = check_in.astimezone(VN_TZ) if check_in.tzinfo else VN_TZ.localize(check_in)

        # Tính số giờ từ checkin đến 00:00 ngày hôm sau
        midnight_next = VN_TZ.localize(datetime.combine(
            ci.date() + timedelta(days=1), time(0, 0)
        ))
        pre_midnight_minutes = (midnight_next - ci).total_seconds() / 60.0
        extra_hours = _ceil_hours(pre_midnight_minutes, self.grace)

        # Công thức spec: Overnight_Candidate = Overnight_Rate + extra * Surcharge_Rate
        extra_surcharge = self.early_fee * Decimal(str(extra_hours))
        overnight_candidate = self.overnight_rate + extra_surcharge

        # Anti-loss guard: so với Day_Rate (ppn), KHÔNG phải overnight_rate
        if overnight_candidate >= self.ppn:
            # Ép về Giá Ngày
            slices = self._slice_timeline(ci, check_out) if check_out > ci else []
            if slices:
                return self._simulate_DAILY(slices)
            return ScenarioResult(mode="DAILY", total=self.ppn, breakdown=[{
                "type": "ROOM_CHARGE",
                "description": "Tiền phòng (1 đêm) — ép từ Overnight",
                "days": 1,
                "mode": "DAILY",
                "amount": self.ppn,
                "slice_type": "core",
            }])

        # Overnight_candidate rẻ hơn Day_Rate → chấp nhận
        breakdown = []
        total_for_overnight_base = overnight_candidate
        
        std_out_dt = ci.replace(hour=self.std_out.hour, minute=self.std_out.minute, second=0, microsecond=0) + timedelta(days=1)
        end_core = min(check_out, std_out_dt)
        
        breakdown.append({
            "type": "ROOM_CHARGE",
            "description": "Tiền phòng ưu đãi qua đêm",
            "days": 1,
            "mode": "OVERNIGHT",
            "amount": self.overnight_rate,
            "slice_type": "core",
            "start_iso": ci.isoformat(),
            "end_iso": end_core.isoformat(),
        })
        if extra_hours > 0:
            breakdown.append({
                "type": "EARLY_CHECKIN_FEE",
                "description": f"Phụ thu vào sớm qua đêm ({extra_hours}h)",
                "hours": extra_hours,
                "amount": extra_surcharge,
                "slice_type": "early",
                "start_iso": ci.isoformat(),
                "end_iso": ci.isoformat(),
            })

        # Xử lý nếu lưu trú nhiều ngày
        total_for_overnight_base, breakdown = self._apply_extra_days_and_late_checkout(
            check_out, std_out_dt, total_for_overnight_base, breakdown
        )

        return ScenarioResult(
            mode="OVERNIGHT", total=_money(total_for_overnight_base), breakdown=breakdown
        )

    # ── Bước 5c: Simulate NIGHT AUDIT OVERNIGHT (Luồng 3.1) ─────────────────

    def _simulate_NIGHT_AUDIT_OVERNIGHT(
        self, ci: datetime, co: datetime
    ) -> ScenarioResult:
        """
        Spec v3 Luồng 3.1: Đi qua đêm cứng (00:00-05:59).
        Tuyệt đối cấm bán giờ, tự động ép Overnight Rate.
        Checkout entitlement: 12:00 cùng ngày, nếu lố bị tính Late Fee (hoặc Rollover).
        """
        std_out_dt = ci.replace(hour=self.std_out.hour, minute=self.std_out.minute, second=0, microsecond=0)
        
        breakdown = []
        total = self.overnight_rate
        
        end_core = min(co, std_out_dt)
        breakdown.append({
            "type": "ROOM_CHARGE",
            "description": "Tiền phòng ưu đãi qua đêm",
            "days": 1,
            "mode": "OVERNIGHT",
            "amount": self.overnight_rate,
            "slice_type": "core",
            "start_iso": ci.isoformat(),
            "end_iso": end_core.isoformat(),
        })
        
        # Xử lý nếu lưu trú kéo dài sang các ngày tiếp theo
        total, breakdown = self._apply_extra_days_and_late_checkout(
            co, std_out_dt, total, breakdown
        )

        return ScenarioResult(mode="OVERNIGHT", total=_money(total), breakdown=breakdown)

    # ── Bước 6: Evaluate ───────────────────────────────────────────────────────

    def evaluate(
        self, check_in: datetime, check_out: datetime, mode: str = "AUTO"
    ) -> tuple[Decimal, list[dict]]:
        """
        Main entry point (Smart Check-in Routing).
        """
        ci_norm, co_norm = self._normalize(check_in, check_out)
        mode_upper = mode.upper()
        ci_time = ci_norm.time()

        if co_norm <= ci_norm:
            return Decimal("0"), []

        is_forced_daily_by_rule = False

        # --- SMART ROUTING (Spec v3) ---
        if time(0, 0) <= ci_time <= time(5, 59):
            # Luồng 3.1: Khung Qua Đêm Cứng
            mode_upper = "FORCE_OVERNIGHT"
            
        elif time(6, 0) <= ci_time <= time(13, 59):
            # Luồng 4: Khung Sáng (06:00 - 13:59) - Chống lách luật Thuê Giờ
            if mode_upper in ["AUTO", "FORCE_HOURLY"]:
                total_minutes = (co_norm - ci_norm).total_seconds() / 60.0
                stay_hours = _ceil_hours(total_minutes, self.grace)
                
                # NẾU chạm Day Threshold (ngưỡng chuyển ngày)
                if stay_hours >= self.day_threshold:
                    mode_upper = "FORCE_DAILY"
                    is_forced_daily_by_rule = True

        # --- EXECUTE SCENARIO ---
        if mode_upper == "FORCE_HOURLY":
            result = self._simulate_PURE_HOURLY(ci_norm, co_norm)

        elif mode_upper == "FORCE_OVERNIGHT":
            if time(0, 0) <= ci_time <= time(5, 59):
                # Luồng 3.1: 00:00–05:59 -> Tính cứng 1 đêm (có hỗ trợ late checkout vào ngày hôm sau)
                result = self._simulate_NIGHT_AUDIT_OVERNIGHT(ci_norm, co_norm)
            else:
                # Luồng 3.2: 14:00–23:59 -> Trượt giá Overnight có chống lỗ
                result = self._simulate_OVERNIGHT_EARLY(ci_norm, co_norm)

        elif mode_upper == "FORCE_DAILY":
            slices = self._slice_timeline(ci_norm, co_norm)
            result = self._simulate_DAILY(slices)
            
            if is_forced_daily_by_rule:
                # Gắn nhãn để UI giải thích lý do hóa đơn đội lên cao
                modified = False
                for b in result.breakdown:
                    if b["type"] == "ROOM_CHARGE":
                        b["description"] += " (Ép giá Ngày chặn lách luật Thuê Giờ)"
                        modified = True
                        break
                if not modified and result.breakdown:
                    result.breakdown[0]["description"] += " (Ép giá Ngày)"

        else:
            slices = self._slice_timeline(ci_norm, co_norm)
            total_minutes = (co_norm - ci_norm).total_seconds() / 60.0
            stay_hours = _ceil_hours(total_minutes, self.grace)

            # AUTO chỉ được chọn giá giờ cho ca ở ngắn trong cùng ngày.
            # Booking qua ngày hoặc vượt ngưỡng ngày phải tính theo giá ngày để tránh
            # trường hợp giá giờ rẻ hơn làm sai đơn đặt phòng qua đêm.
            if co_norm.date() > ci_norm.date() or stay_hours >= self.day_threshold:
                result = self._simulate_DAILY(slices)
            else:
                hourly_res = self._simulate_PURE_HOURLY(ci_norm, co_norm)
                daily_res = self._simulate_DAILY(slices)
                result = hourly_res if hourly_res.total <= daily_res.total else daily_res

        return result.total, result.breakdown
