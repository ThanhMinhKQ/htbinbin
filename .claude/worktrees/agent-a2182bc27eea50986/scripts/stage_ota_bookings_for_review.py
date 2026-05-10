#!/usr/bin/env python3
"""Move automatically-created OTA bookings into Reservation Hub review state."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    load_dotenv(ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is missing")

    from app.db.models import Booking
    from app.services.booking_service import BookingService, is_ota_like_booking

    engine = create_engine(database_url, pool_pre_ping=True)
    with Session(engine) as session:
        service = BookingService(session)
        staged = []
        bookings = session.query(Booking).filter(Booking.source_booking_id.is_(None)).all()
        for booking in bookings:
            if not is_ota_like_booking(booking):
                continue
            service.stage_ota_booking_for_review(booking, user_id=None)
            staged.append((booking.id, booking.external_id, booking.booking_source, booking.reservation_status))
        session.commit()

    print(f"Staged OTA bookings: {len(staged)}")
    for row in staged:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
