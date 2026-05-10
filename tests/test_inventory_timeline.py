import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.core.utils import VN_TZ
from app.db.models import HotelStayStatus, StayType
from app.services.inventory_service import InventoryService


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
            guests=[SimpleNamespace(full_name="Nguyen Van A", is_primary=True)],
        )

        db = DbStub([[room], [], [stay], []])

        timeline = InventoryService(db).get_timeline(branch_id=1, start_date=start_date, days=14)

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
            guests=[SimpleNamespace(full_name="Nguyen Van A", is_primary=True)],
        )

        db = DbStub([[room], [], [stay], []])

        timeline = InventoryService(db).get_timeline(branch_id=1, start_date=start_date, days=14)

        self.assertEqual(timeline[0]["events"][0]["end_date"], end_date.isoformat())
        self.assertFalse(timeline[0]["events"][0]["is_hourly"])


if __name__ == "__main__":
    unittest.main()
