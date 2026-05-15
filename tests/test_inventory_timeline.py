import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.core.utils import VN_TZ
from app.db.models import HotelStayStatus, StayType
from app.services.room_inventory_service import InventoryService


class QueryStub:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def options(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows


class DbStub:
    def __init__(self, query_rows):
        self.query_rows = list(query_rows)

    def query(self, *args, **kwargs):
        return QueryStub(self.query_rows.pop(0))


# get_timeline issues 5 queries in order:
#   1. rooms
#   2. bookings
#   3. active_stays
#   4. guest_rows (stay_ids non-empty → issued; empty stay_ids → skipped)
#   5. blocks
# When stay_ids is empty the guest query is skipped, so only 4 rows needed.
# Our stubs always have a stay so we need 5 rows.

class InventoryTimelineTest(unittest.TestCase):
    def test_hourly_active_stay_without_checkout_only_spans_checkin_day(self):
        start_date = date(2026, 5, 6)
        room = SimpleNamespace(
            id=101,
            room_number="101",
            room_type_obj=SimpleNamespace(name="Deluxe"),
        )
        stay = SimpleNamespace(
            id=501,
            room_id=101,
            check_in_at=VN_TZ.localize(datetime(2026, 5, 6, 10, 0)),
            check_out_at=None,
            stay_type=StayType.HOUR,
            pricing_mode_initial="HOURLY",
        )
        # guest_rows trả về tuples (stay_id, full_name, is_primary)
        guest_row = (501, "Nguyen Van A", True)

        # rows: rooms, bookings, active_stays, guest_rows, blocks
        db = DbStub([[room], [], [stay], [guest_row], []])

        timeline = InventoryService(db).get_timeline(branch_id=1, start_date=start_date, days=14)

        self.assertEqual(len(timeline), 1)
        self.assertEqual(len(timeline[0]["events"]), 1)
        self.assertEqual(timeline[0]["events"][0]["start_date"], "2026-05-06")
        self.assertEqual(timeline[0]["events"][0]["end_date"], "2026-05-06")
        self.assertTrue(timeline[0]["events"][0]["is_hourly"])

    def test_overnight_active_stay_without_checkout_keeps_open_timeline_span(self):
        start_date = date(2026, 5, 6)
        end_date = start_date + timedelta(days=14)
        room = SimpleNamespace(
            id=101,
            room_number="101",
            room_type_obj=SimpleNamespace(name="Deluxe"),
        )
        stay = SimpleNamespace(
            id=501,
            room_id=101,
            check_in_at=VN_TZ.localize(datetime(2026, 5, 6, 10, 0)),
            check_out_at=None,
            stay_type=StayType.NIGHT,
            pricing_mode_initial="NIGHT",
        )
        # guest_rows trả về tuples (stay_id, full_name, is_primary)
        guest_row = (501, "Nguyen Van A", True)

        # rows: rooms, bookings, active_stays, guest_rows, blocks
        db = DbStub([[room], [], [stay], [guest_row], []])

        timeline = InventoryService(db).get_timeline(branch_id=1, start_date=start_date, days=14)

        self.assertEqual(len(timeline), 1)
        self.assertEqual(len(timeline[0]["events"]), 1)
        self.assertEqual(timeline[0]["events"][0]["end_date"], end_date.isoformat())
        self.assertFalse(timeline[0]["events"][0]["is_hourly"])

    def test_stay_checkout_at_noon_frees_room_same_day(self):
        """Khách trả phòng lúc 12:00 ngày 16 → phòng trống ngày 16, không bị tính sold."""
        from app.services.room_inventory_service import _stay_occupies_date
        check_in = VN_TZ.localize(datetime(2026, 5, 15, 14, 0))
        check_out = VN_TZ.localize(datetime(2026, 5, 16, 12, 0))

        self.assertTrue(_stay_occupies_date(check_in, check_out, date(2026, 5, 15)))
        self.assertFalse(_stay_occupies_date(check_in, check_out, date(2026, 5, 16)))

    def test_stay_checkout_after_noon_still_occupies_day(self):
        """Khách trả phòng lúc 13:00 ngày 16 (trễ) → phòng vẫn bận ngày 16."""
        from app.services.room_inventory_service import _stay_occupies_date
        check_in = VN_TZ.localize(datetime(2026, 5, 15, 14, 0))
        check_out = VN_TZ.localize(datetime(2026, 5, 16, 13, 0))

        self.assertTrue(_stay_occupies_date(check_in, check_out, date(2026, 5, 15)))
        self.assertTrue(_stay_occupies_date(check_in, check_out, date(2026, 5, 16)))

    def test_new_booking_same_day_after_checkout_is_available(self):
        """Khách A trả 12:00 ngày 16, khách B check-in 14:00 ngày 16 → không conflict."""
        from app.services.room_inventory_service import _stay_occupies_date
        # Stay của khách A: check-out đúng 12:00 ngày 16
        check_in_a = VN_TZ.localize(datetime(2026, 5, 15, 14, 0))
        check_out_a = VN_TZ.localize(datetime(2026, 5, 16, 12, 0))

        # Ngày 16 phải trống để nhận khách B
        self.assertFalse(_stay_occupies_date(check_in_a, check_out_a, date(2026, 5, 16)))


if __name__ == "__main__":
    unittest.main()
