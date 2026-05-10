import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.api.ota_dashboard import _build_ota_change_token, _has_ota_changes_since
from app.api.pms.reservation_api import _is_cancel_booking_log, _is_success_booking_log
from app.db.models import BookingStatus, OTAParsingStatus


class OTARealtimeRefreshTests(unittest.TestCase):
    def test_change_token_includes_count_and_latest_update_timestamp(self):
        vn = timezone(timedelta(hours=7))
        bookings = [
            SimpleNamespace(created_at=datetime(2026, 5, 2, 9, 0, tzinfo=vn), updated_at=None),
            SimpleNamespace(created_at=datetime(2026, 5, 2, 9, 5, tzinfo=vn), updated_at=datetime(2026, 5, 2, 9, 7, tzinfo=vn)),
        ]

        token = _build_ota_change_token(bookings)

        self.assertEqual(token["total_bookings"], 2)
        self.assertEqual(token["latest_changed_at"], "2026-05-02T09:07:00+07:00")

    def test_change_detection_catches_new_booking_without_page_reload(self):
        before = {
            "total_bookings": 2,
            "cancelled_count": 0,
            "latest_changed_at": "2026-05-02T09:07:00+07:00",
        }
        after = {
            "total_bookings": 3,
            "cancelled_count": 0,
            "latest_changed_at": "2026-05-02T09:08:00+07:00",
        }

        self.assertTrue(_has_ota_changes_since(before, after))

    def test_change_detection_catches_update_even_when_count_is_same(self):
        before = {
            "total_bookings": 3,
            "cancelled_count": 0,
            "latest_changed_at": "2026-05-02T09:08:00+07:00",
        }
        after = {
            "total_bookings": 3,
            "cancelled_count": 1,
            "latest_changed_at": "2026-05-02T09:10:00+07:00",
        }

        self.assertTrue(_has_ota_changes_since(before, after))

    def test_change_detection_returns_false_when_token_is_same(self):
        before = {
            "total_bookings": 3,
            "cancelled_count": 1,
            "latest_changed_at": "2026-05-02T09:10:00+07:00",
        }

        self.assertFalse(_has_ota_changes_since(before, dict(before)))

    def test_status_endpoint_treats_cancelled_booking_log_without_action_type_as_cancel(self):
        log = SimpleNamespace(
            status=OTAParsingStatus.SUCCESS,
            booking_id=7,
            extracted_data={"external_id": "OTA-7", "booking_source": "Go2Joy"},
            booking=SimpleNamespace(status=BookingStatus.CANCELLED, reservation_status="CANCELLED"),
        )

        self.assertTrue(_is_cancel_booking_log(log))
        self.assertFalse(_is_success_booking_log(log))


if __name__ == "__main__":
    unittest.main()
