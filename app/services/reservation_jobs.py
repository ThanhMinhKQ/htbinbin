"""Background jobs for Reservation Hub inventory and booking hygiene."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from ..core.config import logger
from ..core.utils import VN_TZ
from ..db.models import Booking, Branch
from ..db.session import SessionLocal
from .booking_service import BookingService
from .room_inventory_service import InventoryService


def generate_reservation_inventory(days: int = 365) -> None:
    db = SessionLocal()
    try:
        today = datetime.now(VN_TZ).date()
        service = InventoryService(db)
        branches = db.query(Branch).all()
        touched = 0
        for branch in branches:
            result = service.generate_daily_inventory(branch.id, today, days, refresh_counts=False)
            touched += int(result.get("records") or 0)
        db.commit()
        logger.info("[ReservationHub] Generated inventory for %s branches, %s records", len(branches), touched)
    except Exception as exc:
        db.rollback()
        logger.error("[ReservationHub] Generate inventory failed: %s", exc, exc_info=True)
    finally:
        db.close()


def release_expired_inventory_holds() -> None:
    db = SessionLocal()
    try:
        released = InventoryService(db).release_expired_holds()
        db.commit()
        if released:
            logger.info("[ReservationHub] Released %s expired inventory holds", released)
    except Exception as exc:
        db.rollback()
        logger.error("[ReservationHub] Release expired holds failed: %s", exc, exc_info=True)
    finally:
        db.close()


def mark_reservation_no_shows() -> None:
    """No-show booking CONFIRMED chưa nhận phòng sau khi quá thời điểm trả phòng + 30 phút.

    - Ưu tiên dùng raw.check_out_at (ISO datetime) để bắt booking giờ chính xác.
    - Fallback: dùng Booking.check_out (date) + 12:00 cho booking đêm cũ.
    - Job chạy mỗi giờ nên bắt được mọi loại booking trong vòng tối đa ~90 phút sau giờ trả.
    """
    db = SessionLocal()
    grace = timedelta(minutes=30)
    try:
        now = datetime.now(VN_TZ)
        bookings = db.query(Booking).filter(
            Booking.reservation_status == "CONFIRMED",
            Booking.stay_id.is_(None),
        ).all()

        service = BookingService(db)
        count = 0
        for booking in bookings:
            checkout_dt = _resolve_checkout_datetime(booking)
            if checkout_dt is None:
                continue
            if now < checkout_dt + grace:
                continue
            service.cancel_reservation(
                booking.id,
                "Tự động no-show sau giờ trả phòng",
                None,
                no_show=True,
            )
            count += 1
        db.commit()
        if count:
            logger.info("[ReservationHub] Marked %s reservations as no-show", count)
    except Exception as exc:
        db.rollback()
        logger.error("[ReservationHub] Auto no-show failed: %s", exc, exc_info=True)
    finally:
        db.close()


def _resolve_checkout_datetime(booking: Booking) -> datetime | None:
    raw = booking.raw_data if isinstance(booking.raw_data, dict) else {}
    raw_checkout = raw.get("check_out_at")
    if raw_checkout:
        try:
            parsed = datetime.fromisoformat(str(raw_checkout))
            if parsed.tzinfo is None:
                parsed = VN_TZ.localize(parsed)
            return parsed.astimezone(VN_TZ)
        except (TypeError, ValueError):
            pass
    if booking.check_out:
        return VN_TZ.localize(datetime.combine(booking.check_out, time(12, 0)))
    return None
