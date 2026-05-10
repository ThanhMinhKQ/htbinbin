import unittest
from datetime import date

from app.services.ota_agent.integration import OTAAgent


class OTAAgentBookingDateTests(unittest.TestCase):
    def setUp(self):
        self.agent = OTAAgent()

    def test_same_day_hourly_booking_stores_valid_checkout_and_raw_actual_checkout(self):
        data = self.agent._normalize_extracted_data({
            "external_id": "4478142",
            "booking_source": "Go2Joy",
            "guest_name": "Joyer.779",
            "room_type": "Superior room",
            "check_in": date(2026, 5, 5),
            "check_out": date(2026, 5, 5),
            "check_in_time": "11:30",
            "check_out_time": "14:30",
            "total_price": 300000,
            "is_prepaid": True,
            "payment_method": "Đã thanh toán (Ví MoMo)",
        })

        booking = self.agent._create_booking_obj(data)

        self.assertEqual(str(booking.check_in), "2026-05-05")
        self.assertEqual(str(booking.check_out), "2026-05-06")
        self.assertEqual(booking.raw_data["ota_actual_check_out"], "2026-05-05")
        self.assertTrue(booking.raw_data["ota_same_day_booking"])
        self.assertEqual(booking.raw_data["check_out_time"], "14:30")

    def test_same_date_ota_booking_crossing_midnight_is_overnight_not_hourly(self):
        data = self.agent._normalize_extracted_data({
            "external_id": "4478143",
            "booking_source": "Go2Joy",
            "guest_name": "Joyer.880",
            "room_type": "Superior room",
            "check_in": date(2026, 5, 5),
            "check_out": date(2026, 5, 5),
            "check_in_time": "22:00",
            "check_out_time": "08:00",
            "total_price": 650000,
            "is_prepaid": True,
            "payment_method": "Đã thanh toán",
        })

        booking = self.agent._create_booking_obj(data)

        self.assertEqual(str(booking.check_in), "2026-05-05")
        self.assertEqual(str(booking.check_out), "2026-05-06")
        self.assertFalse(booking.raw_data["ota_same_day_booking"])
        self.assertTrue(booking.raw_data["ota_cross_midnight_booking"])
        self.assertNotIn("ota_actual_check_out", booking.raw_data)


if __name__ == "__main__":
    unittest.main()
