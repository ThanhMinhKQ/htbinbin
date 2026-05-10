import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.models import Booking
from app.services.booking_service import BookingService
from app.services.ota_agent.mapper import HotelMapper


def main() -> None:
    load_dotenv(".env")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    session = Session(engine)
    mapper = HotelMapper(session)
    booking_service = BookingService(session)
    updated = []
    skipped = []

    bookings = (
        session.query(Booking)
        .filter(Booking.booking_type == "OTA", Booking.branch_id.is_(None))
        .all()
    )

    for booking in bookings:
        raw = dict(booking.raw_data or {})
        hotel_name = (
            raw.get("hotel_name")
            or raw.get("property_name")
            or raw.get("hotel")
            or ""
        )
        room_type = raw.get("room_type") or booking.room_type or ""
        branch_id = mapper.get_branch_id(hotel_name) or mapper.get_branch_id_from_room_type(room_type)

        if not branch_id:
            skipped.append((booking.id, booking.external_id, hotel_name, room_type))
            continue

        booking.branch_id = branch_id
        raw["mapped_branch_id"] = branch_id
        raw["mapped_branch_source"] = "ota_remap"
        booking.raw_data = raw
        booking_service.stage_ota_booking_for_review(booking, user_id=None)
        updated.append((booking.id, booking.external_id, hotel_name, branch_id))

    session.commit()
    print("updated", len(updated))
    for row in updated:
        print(row)
    print("skipped", len(skipped))
    for row in skipped:
        print(row)
    session.close()


if __name__ == "__main__":
    main()
