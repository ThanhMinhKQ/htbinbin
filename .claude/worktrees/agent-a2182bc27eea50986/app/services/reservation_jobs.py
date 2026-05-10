"""Background jobs for Reservation Hub inventory and booking hygiene."""
from __future__ import annotations

from datetime import datetime

from ..core.config import logger
from ..core.utils import VN_TZ
from ..db.models import Booking, Branch
from ..db.session import SessionLocal
from .booking_service import BookingService
from .inventory_service import InventoryService


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
    db = SessionLocal()
    try:
        today = datetime.now(VN_TZ).date()
        bookings = db.query(Booking).filter(
            Booking.reservation_status == "CONFIRMED",
            Booking.check_in < today,
            Booking.stay_id.is_(None),
        ).all()
        service = BookingService(db)
        count = 0
        for booking in bookings:
            service.cancel_reservation(booking.id, "Tự động no-show sau ngày nhận phòng", None, no_show=True)
            count += 1
        db.commit()
        if count:
            logger.info("[ReservationHub] Marked %s reservations as no-show", count)
    except Exception as exc:
        db.rollback()
        logger.error("[ReservationHub] Auto no-show failed: %s", exc, exc_info=True)
    finally:
        db.close()
