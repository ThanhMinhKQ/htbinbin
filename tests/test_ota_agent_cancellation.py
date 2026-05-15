import unittest
from datetime import date

from app.db.models import Booking, BookingStatus
from app.services.ota_agent.integration import OTAAgent


class _Query:
    def __init__(self, items):
        self._items = list(items)
        self.filters = []

    def filter(self, *conditions):
        self.filters.extend(conditions)
        return self

    def first(self):
        return self._items[0] if self._items else None

    def all(self):
        return list(self._items)


class _Session:
    def __init__(self, bookings):
        self.bookings = bookings

    def query(self, model):
        if model is Booking:
            return _Query(self.bookings)
        return _Query([])

    def add(self, obj):
        self.bookings.append(obj)

    def flush(self):
        pass


class OTAAgentCancellationTests(unittest.TestCase):
    def setUp(self):
        self.agent = OTAAgent()

    def test_cancelled_action_updates_existing_go2joy_booking(self):
        booking = Booking(
            external_id="4505305",
            booking_source="Go2Joy",
            guest_name="Go2Joy Guest",
            check_in=date(2026, 5, 15),
            check_out=date(2026, 5, 16),
            status=BookingStatus.CONFIRMED,
            reservation_status="PENDING",
            booking_type="OTA",
        )
        db = _Session([booking])

        result = self.agent.upsert_booking(db, {
            "external_id": "4505305",
            "booking_source": "Go2Joy",
            "action_type": "CANCELLED",
        })

        self.assertIs(result, booking)
        self.assertEqual(booking.status, BookingStatus.CANCELLED)
        self.assertEqual(booking.reservation_status, "CANCELLED")


if __name__ == "__main__":
    unittest.main()
