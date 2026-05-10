import unittest

from app.services.ota_agent.rule_extractor import RuleBasedOTAExtractor, is_confident_booking


class RuleBasedOTAExtractorTests(unittest.TestCase):
    def setUp(self):
        self.extractor = RuleBasedOTAExtractor()

    def test_go2joy_confirmation_extracts_without_ai_and_no_deposit(self):
        email = {
            "sender": "booking@go2joy.vn",
            "subject": "Go2Joy - Đặt phòng mới - 123456789",
            "html": """
                <p>Quý khách sạn BIN BIN 1, Khách sạn có đặt phòng mới</p>
                <p>Tên khách Nguyễn Văn A Mã đặt phòng 123456789</p>
                <p>Mã đặt phòng Loại phòng 123456789 Deluxe Double Loại đặt phòng Qua đêm</p>
                <p>14:00, 20/05/2026 ~ 12:00, 21/05/2026</p>
                <p>Tiền phòng 600.000 VND</p>
                <p>Tình trạng thanh toán Đã thanh toán</p>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["booking_source"], "Go2Joy")
        self.assertEqual(data["external_id"], "123456789")
        self.assertEqual(data["guest_name"], "Nguyễn Văn A")
        self.assertEqual(data["hotel_name"], "BIN BIN 1")
        self.assertEqual(str(data["check_in"]), "2026-05-20")
        self.assertEqual(str(data["check_out"]), "2026-05-21")
        self.assertEqual(data["total_price"], 600000)
        self.assertEqual(data["deposit_amount"], 0)
        self.assertTrue(is_confident_booking(data))

    def test_go2joy_confirmation_extracts_two_rooms(self):
        email = {
            "sender": "booking@go2joy.vn",
            "subject": "Go2Joy - Đặt phòng mới - 987654321",
            "html": """
                <p>Quý khách sạn BIN BIN 1, Khách sạn có đặt phòng mới</p>
                <p>Tên khách Nguyễn Văn C Mã đặt phòng 987654321</p>
                <p>Mã đặt phòng Loại phòng 987654321 Superior Double Loại đặt phòng Qua đêm</p>
                <p>Số phòng 2</p>
                <p>14:00, 26/05/2026 ~ 12:00, 27/05/2026</p>
                <p>Tiền phòng 900.000 VND</p>
                <p>Tình trạng thanh toán Đã thanh toán</p>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Go2Joy")
        self.assertEqual(data["external_id"], "987654321")
        self.assertEqual(data["room_type"], "Superior Double")
        self.assertEqual(data["num_rooms"], 2)
        self.assertEqual(data["total_price"], 900000)
        self.assertTrue(is_confident_booking(data))


        email = {
            "sender": "binbinhotel.ota@gmail.com",
            "subject": "[Khách sạn Bin Bin] Đơn hàng mới #1987",
            "html": """
                <h1>Đơn hàng mới #1987</h1>
                <p>Khách hàng: Trần Thị B</p>
                <p>Số điện thoại: 0909123456</p>
                <p>Khách sạn: Bin Bin Hotel 2</p>
                <p>Loại phòng: Deluxe (B2)</p>
                <p>Ngày nhận phòng: 22/05/2026</p>
                <p>Ngày trả phòng: 23/05/2026</p>
                <p>Tổng cộng: 750.000 VND</p>
                <p>Thanh toán: Chưa thanh toán</p>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["booking_source"], "Website")
        self.assertEqual(data["external_id"], "WEB-1987")
        self.assertEqual(data["guest_name"], "Trần Thị B")
        self.assertEqual(data["guest_phone"], "0909123456")
        self.assertEqual(data["room_type"], "Deluxe (B2)")
        self.assertEqual(data["total_price"], 750000)
        self.assertFalse(data["is_prepaid"])
        self.assertEqual(data["deposit_amount"], 0)
        self.assertTrue(is_confident_booking(data))

    def test_agoda_uses_net_rate_not_reference_sell_rate(self):
        email = {
            "sender": "noreply@agoda.com",
            "subject": "Agoda New Booking 4266983",
            "html": """
                <p>Booking ID Mã số đặt phòng 4266983</p>
                <p>Booking confirmation Xác nhận đặt phòng Bin Bin Hotel 3 (Property ID 123)</p>
                <p>Customer First Name Tên Khách Hàng Alice Customer Last Name Họ Khách Hàng Nguyen Country of Residence Vietnam</p>
                <p>Check-in Nhận phòng 24-May-2026 (24-05-2026)</p>
                <p>Check-out Trả phòng 25-May-2026 (25-05-2026)</p>
                <p>Room Type Loại Phòng No. of Rooms Số phòng Occupancy Số người No. of Extra Bed Số Giường Thêm : Superior Double Room 1 2 Adults 0</p>
                <p>Reference sell rate: VND 687,500</p>
                <p>Net rate (incl. taxes & fees) Giá thực tế (bao gồm thuế & phí) VND 550,000.00</p>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Agoda")
        self.assertEqual(data["external_id"], "4266983")
        self.assertEqual(data["total_price"], 550000)
        self.assertEqual(data["deposit_amount"], 0)
        self.assertTrue(is_confident_booking(data))

    def test_known_ota_admin_email_returns_skip_without_gemini(self):
        email = {
            "sender": "notification@trip.com",
            "subject": "Trip.com rate plan settings reminder",
            "html": """
                <p>Dear Partner, please update your room rate plan settings.</p>
                <p>This is not a reservation confirmation and does not contain a booking ID.</p>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["status"], "SKIPPED")
        self.assertEqual(data["reason"], "non_booking_email")
        self.assertFalse(is_confident_booking(data))

    def test_unknown_or_incomplete_email_returns_none_so_gemini_can_fallback(self):
        email = {
            "sender": "partner@example.com",
            "subject": "Booking notification",
            "html": "There is a booking but no date and no price",
        }

        self.assertIsNone(self.extractor.extract(email))


if __name__ == "__main__":
    unittest.main()
