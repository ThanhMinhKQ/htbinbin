"""
PMS Pricing Service — Facade Layer

Chuyển toàn bộ logic tính giá sang PricingEngine (time-slicing).
Giữ nguyên tất cả exports để backward-compatible với caller hiện tại.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from ..db.models import HotelRoomType
from .pricing_engine import PricingEngine

# ─── Cached engines per room_type id ─────────────────────────────────────────

_engine_cache: dict[int, PricingEngine] = {}


def _get_engine(room_type: Optional[HotelRoomType]) -> Optional[PricingEngine]:
    if room_type is None:
        return None
    key = id(room_type)
    if key not in _engine_cache:
        _engine_cache[key] = PricingEngine(room_type)
    return _engine_cache[key]


# ─── Backward-compatible exports ───────────────────────────────────────────────

MODE_TO_STAY_TYPE = {
    "AUTO": "AUTO",
    "NIGHT": "NIGHT",
    "HOURLY": "HOURLY",
    "DAY_USE": "DAY_USE",
    "WEEKLY": "WEEKLY",
}


def calculate_full_charge(
    stay_type: str,
    room_type: Optional[HotelRoomType],
    check_in: datetime,
    check_out: datetime,
) -> tuple[Decimal, list[dict]]:
    """
    Tính tiền phòng với Time-Slicing Engine.
    Giữ nguyên signature và return format như cũ.

    Returns:
        (total_amount, breakdown)
        breakdown items giờ có thêm trường 'slice_type'.
    """
    engine = _get_engine(room_type)
    if engine is None:
        return money(0), []

    mode_map = {
        "AUTO": "AUTO",
        "FORCE_HOURLY": "FORCE_HOURLY",
        "FORCE_DAILY": "FORCE_DAILY",
        "FORCE_OVERNIGHT": "FORCE_OVERNIGHT",
        "NIGHT": "AUTO",
        "HOUR": "FORCE_HOURLY",
        "DAY_USE": "FORCE_DAILY",
        "WEEKLY": "FORCE_DAILY",
    }
    mode = mode_map.get((stay_type or "AUTO").upper(), "AUTO")
    return engine.evaluate(check_in, check_out, mode)


def calculate_room_price(
    stay_type: str,
    room_type: Optional[HotelRoomType],
    check_in: datetime,
    check_out: datetime,
    apply_promo: bool = True,
) -> Decimal:
    """
    Legacy wrapper — giữ nguyên signature cho chỗ gọi hiện tại.
    """
    total, _breakdown = calculate_full_charge(stay_type, room_type, check_in, check_out)
    return total


def detect_pricing_mode_from_breakdown(breakdown: list) -> Optional[str]:
    """
    Trích xuất pricing_mode từ breakdown.

    Dùng tại checkout để ghi nhận pricing_mode_final.
    Nếu có ROOM_CHARGE → NIGHT, nếu có HOURLY_CHARGE → HOURLY.
    """
    if not breakdown:
        return None
    for item in breakdown:
        m = item.get("mode")
        if m == "OVERNIGHT":
            return "FORCE_OVERNIGHT"
        elif m == "DAILY":
            return "FORCE_DAILY"  # Ensure it detects FORCE modes now
        elif m == "HOURLY":
            return "FORCE_HOURLY"

    # Fallback legacy detection
    for item in breakdown:
        t = item.get("type")
        if t == "ROOM_CHARGE":
            return "FORCE_DAILY"
        elif t == "HOURLY_CHARGE":
            return "FORCE_HOURLY"
    return None


def money(value) -> Decimal:
    """Normalize monetary value to Decimal(2)."""
    if value is None or value == "":
        return Decimal("0")
    elif isinstance(value, Decimal):
        return value
    return Decimal(str(value).strip()).quantize(Decimal("0.01"))


# ─── Preview helper (dùng trong API preview endpoint) ─────────────────────────

def get_engine_config(room_type: HotelRoomType) -> dict:
    """Trả về config của engine cho API preview."""
    engine = _get_engine(room_type)
    if engine is None:
        return {}
    return {
        "std_checkin_time": engine.std_in.strftime("%H:%M"),
        "std_checkout_time": engine.std_out.strftime("%H:%M"),
        "early_fee_per_hour": float(engine.early_fee),
        "late_fee_per_hour": float(engine.late_fee),
        "grace_minutes": engine.grace,
        "price_per_night": float(engine.ppn),
        "price_per_hour": float(engine.pph),
        "price_next_hour": float(engine.pnh),
        "min_hours": engine.min_h,
    }
