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
                <p>Số khách 2</p>
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
        self.assertEqual(data["num_guests"], 2)
        self.assertEqual(data["num_adults"], 2)
        self.assertEqual(data["check_in_time"], "14:00")
        self.assertEqual(data["check_out_time"], "12:00")
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

    def test_go2joy_current_new_booking_template_extracts_stay_payment_and_total(self):
        email = {
            "sender": "booking@go2joy.vn",
            "subject": "Go2Joy - Đặt phòng mới - 4481840",
            "html": """
                logo Go2Joy
                Thân gửi Quý khách sạn Bin Bin Hotel 7 – Near Ton Duc Thang University,
                Khách sạn vừa nhận được 1 đặt phòng mới từ khách của Go2Joy.
                Chi tiết đặt phòng
                Tên khách
                Mẫn Võ
                Mã đặt phòng
                Loại phòng
                4481840
                Superior room
                Loại đặt phòng
                Thời gian nhận phòng ~ trả phòng
                Qua đêm
                23:00, 09/05/2026 ~ 12:00, 10/05/2026
                Tiền phòng
                550.000 VND
                Phụ thu
                50.000 VND
                Tiền sản phẩm
                0 VND
                Giảm giá/Khuyến mãi0 VND
                Số tiền thanh toán
                550.000 VND
                Tình trạng thanh toán
                Đã thanh toán (Ví ShopeePay)
                Cảm ơn sự hợp tác của Quý khách sạn.
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Go2Joy")
        self.assertEqual(data["external_id"], "4481840")
        self.assertEqual(data["guest_name"], "Mẫn Võ")
        self.assertEqual(data["hotel_name"], "Bin Bin Hotel 7 – Near Ton Duc Thang University")
        self.assertEqual(data["room_type"], "Superior room")
        self.assertEqual(str(data["check_in"]), "2026-05-09")
        self.assertEqual(data["check_in_time"], "23:00")
        self.assertEqual(str(data["check_out"]), "2026-05-10")
        self.assertEqual(data["check_out_time"], "12:00")
        self.assertEqual(data["total_price"], 550000)
        self.assertTrue(data["is_prepaid"])
        self.assertEqual(data["payment_method"], "Đã thanh toán (Ví ShopeePay)")
        self.assertTrue(is_confident_booking(data))

    def test_go2joy_hourly_html_template_extracts_same_day_times_and_payment(self):
        email = {
            "sender": "booking@go2joy.vn",
            "subject": "Go2Joy - Đặt phòng mới - 4480749",
            "html": """
                <p>Thân gửi Quý khách sạn Bin Bin Hotel 8 – Near Sunrise City D7,</p>
                <p>Tên khách</p><b>Joyer.996</b>
                <div>Mã đặt phòng</div><div>Loại phòng</div>
                <div>4480749</div><div>Superior Room</div>
                <div>Loại đặt phòng</div><div>Thời gian nhận phòng ~ trả phòng</div>
                <div>Giờ</div><div>15:00, 07/05/2026 ~ 17:00, 07/05/2026</div>
                <div>Tiền phòng</div><div>300.000 VND</div>
                <div>Phụ thu</div><div>0 VND</div>
                <div>Tiền sản phẩm</div><div>0 VND</div>
                <div>Giảm giá/Khuyến mãi</div><div>-50.000 VND</div>
                <div>Số tiền thanh toán</div><div>250.000 VND</div>
                <div>Tình trạng thanh toán</div><div>Đã thanh toán (Ví MoMo)</div>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["external_id"], "4480749")
        self.assertEqual(data["guest_name"], "Joyer.996")
        self.assertEqual(data["hotel_name"], "Bin Bin Hotel 8 – Near Sunrise City D7")
        self.assertEqual(data["room_type"], "Superior Room")
        self.assertEqual(str(data["check_in"]), "2026-05-07")
        self.assertEqual(data["check_in_time"], "15:00")
        self.assertEqual(str(data["check_out"]), "2026-05-07")
        self.assertEqual(data["check_out_time"], "17:00")
        self.assertEqual(data["total_price"], 300000)
        self.assertTrue(data["is_prepaid"])
        self.assertEqual(data["payment_method"], "Đã thanh toán (Ví MoMo)")
        self.assertTrue(is_confident_booking(data))

    def test_go2joy_hourly_4477671_keeps_checkout_same_day_and_paid_amount(self):
        email = {
            "sender": "booking@go2joy.vn",
            "subject": "Go2Joy - Đặt phòng mới - 4477671",
            "html": """
                <p>Thân gửi Quý khách sạn Bin Bin Hotel 17 – Near Gs Metro City,</p>
                <p>Khách sạn vừa nhận được 1 đặt phòng mới từ khách của Go2Joy.</p>
                <p>Tên khách</p><b>San</b>
                <div>Mã đặt phòng</div><div>Loại phòng</div>
                <div>4477671</div><div>Superior</div>
                <div>Loại đặt phòng</div><div>Thời gian nhận phòng ~ trả phòng</div>
                <div>Giờ</div><div>11:30, 05/05/2026 ~ 14:30, 05/05/2026</div>
                <div>Tiền phòng</div><div>300.000 VND</div>
                <div>Phụ thu</div><div>0 VND</div>
                <div>Tiền sản phẩm</div><div>0 VND</div>
                <div>Giảm giá/Khuyến mãi</div><div>0 VND</div>
                <div>Số tiền thanh toán</div><div>300.000 VND</div>
                <div>Tình trạng thanh toán</div><div>Đã thanh toán (Ví MoMo)</div>
                <p>English below</p>
                <p>Booking type</p><p>Check-in ~ checkout time</p>
                <p>Hourly</p><p>11:30, 05/05/2026 ~ 14:30, 05/05/2026</p>
                <p>Price</p><p>300,000 VND</p>
                <p>Payment amount</p><p>300,000 VND</p>
                <p>Payment status</p><p>Paid (MoMo Wallet)</p>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Go2Joy")
        self.assertEqual(data["external_id"], "4477671")
        self.assertEqual(data["guest_name"], "San")
        self.assertEqual(data["hotel_name"], "Bin Bin Hotel 17 – Near Gs Metro City")
        self.assertEqual(data["room_type"], "Superior")
        self.assertEqual(str(data["check_in"]), "2026-05-05")
        self.assertEqual(data["check_in_time"], "11:30")
        self.assertEqual(str(data["check_out"]), "2026-05-05")
        self.assertEqual(data["check_out_time"], "14:30")
        self.assertEqual(data["total_price"], 300000)
        self.assertTrue(data["is_prepaid"])
        self.assertEqual(data["payment_method"], "Đã thanh toán (Ví MoMo)")
        self.assertTrue(is_confident_booking(data))

    def test_go2joy_new_booking_notification_4478523_uses_rule_parser(self):
        email = {
            "sender": "info.mail@go2joy.vn",
            "subject": "Go2Joy - Thông báo có đặt phòng mới - 4478523",
            "html": """
                <p>Thân gửi Quý khách sạn Bin Bin Hotel 9 – Near Tam Anh Hospital,</p>
                <p>Khách sạn vừa nhận được 1 đặt phòng mới từ khách của Go2Joy.</p>
                <p>Tên khách</p><b>Joyer.996</b>
                <div>Mã đặt phòng</div><div>Loại phòng</div>
                <div>4478523</div><div>SUPERIOR ROOM</div>
                <div>Loại đặt phòng</div><div>Thời gian nhận phòng ~ trả phòng</div>
                <div>Giờ</div><div>15:00, 07/05/2026 ~ 17:00, 07/05/2026</div>
                <div>Tiền phòng</div><div>300.000 VND</div>
                <div>Phụ thu</div><div>0 VND</div>
                <div>Tiền sản phẩm</div><div>0 VND</div>
                <div>Giảm giá/Khuyến mãi</div><div>-50.000 VND</div>
                <div>Số tiền thanh toán</div><div>250.000 VND</div>
                <div>Tình trạng thanh toán</div><div>Đã thanh toán (Ví MoMo)</div>
                <p>English below</p>
                <p>Booking type</p><p>Check-in ~ checkout time</p>
                <p>Hourly</p><p>15:00, 07/05/2026 ~ 17:00, 07/05/2026</p>
                <p>Price</p><p>300,000 VND</p>
                <p>Payment amount</p><p>250,000 VND</p>
                <p>Payment status</p><p>Paid (MoMo Wallet)</p>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Go2Joy")
        self.assertEqual(data["external_id"], "4478523")
        self.assertEqual(data["guest_name"], "Joyer.996")
        self.assertEqual(data["hotel_name"], "Bin Bin Hotel 9 – Near Tam Anh Hospital")
        self.assertEqual(data["room_type"], "SUPERIOR ROOM")
        self.assertEqual(str(data["check_in"]), "2026-05-07")
        self.assertEqual(data["check_in_time"], "15:00")
        self.assertEqual(str(data["check_out"]), "2026-05-07")
        self.assertEqual(data["check_out_time"], "17:00")
        self.assertEqual(data["total_price"], 300000)
        self.assertTrue(data["is_prepaid"])
        self.assertEqual(data["payment_method"], "Đã thanh toán (Ví MoMo)")
        self.assertTrue(is_confident_booking(data))

    def test_go2joy_empty_guest_name_uses_short_fallback(self):
        email = {
            "sender": "info.mail@go2joy.vn",
            "subject": "Go2Joy - Thông báo có đặt phòng mới - 4492068",
            "html": """
                <p>Thân gửi Quý khách sạn Bin Bin Hotel 1 – Near Rmit University D7,</p>
                <p>Khách sạn vừa nhận được 1 đặt phòng mới từ khách của Go2Joy.</p>
                <p>Tên khách</p><b></b>
                <div>Mã đặt phòng</div><div>Loại phòng</div>
                <div>4492068</div><div>Superior room</div>
                <div>Loại đặt phòng</div><div>Thời gian nhận phòng ~ trả phòng</div>
                <div>Giờ</div><div>15:00, 10/05/2026 ~ 18:00, 10/05/2026</div>
                <div>Tiền phòng</div><div>300.000 VND</div>
                <div>Phụ thu</div><div>0 VND</div>
                <div>Tiền sản phẩm</div><div>0 VND</div>
                <div>Số tiền thanh toán</div><div>300.000 VND</div>
                <div>Tình trạng thanh toán</div><div>Đã thanh toán (Ví MoMo)</div>
                <p>English below</p>
                <p>Guest's name</p><b></b>
                <p>Booking Number</p><p>Room type</p>
                <p>4492068</p><p>Superior room</p>
                <p>Booking type</p><p>Check-in ~ checkout time</p>
                <p>Hourly</p><p>15:00, 10/05/2026 ~ 18:00, 10/05/2026</p>
                <p>Price</p><p>300,000 VND</p>
                <p>Payment amount</p><p>300,000 VND</p>
                <p>Payment status</p><p>Paid (MoMo Wallet)</p>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Go2Joy")
        self.assertEqual(data["external_id"], "4492068")
        self.assertEqual(data["guest_name"], "Go2Joy Guest")
        self.assertNotIn("Mã đặt phòng", data["guest_name"])
        self.assertNotIn("Booking Number", data["guest_name"])
        self.assertLessEqual(len(data["guest_name"]), 32)
        self.assertEqual(data["room_type"], "Superior room")
        self.assertEqual(str(data["check_in"]), "2026-05-10")
        self.assertEqual(data["check_in_time"], "15:00")
        self.assertEqual(str(data["check_out"]), "2026-05-10")
        self.assertEqual(data["check_out_time"], "18:00")
        self.assertEqual(data["total_price"], 300000)
        self.assertTrue(data["is_prepaid"])
        self.assertTrue(is_confident_booking(data))

    def test_go2joy_cancellation_template_extracts_cancel_action_and_stay(self):
        email = {
            "sender": "info.mail@go2joy.vn",
            "subject": "Go2Joy - Thông báo đặt phòng đã bị huỷ - 4478523",
            "html": """
                <p>Thân gửi Quý khách sạn Bin Bin Hotel 9 – Near Tam Anh Hospital,</p>
                <p>Tên khách</p><b>Joyer.996</b>
                <div>Mã đặt phòng</div><div>Loại phòng</div>
                <div>4478523</div><div>SUPERIOR ROOM</div>
                <div>Loại đặt phòng</div><div>Thời gian nhận phòng ~ trả phòng</div>
                <div>Giờ</div><div>15:00, 07/05/2026 ~ 17:00, 07/05/2026</div>
                <div>Nội dung thay đổi</div>
                <div>Tình trạng đặt phòng</div><div>Khách hủy phòng</div>
                <p>English below</p>
                <p>Booking status</p><p>Cancelled by user</p>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Go2Joy")
        self.assertEqual(data["action_type"], "CANCEL")
        self.assertEqual(data["external_id"], "4478523")
        self.assertEqual(data["guest_name"], "Joyer.996")
        self.assertEqual(data["hotel_name"], "Bin Bin Hotel 9 – Near Tam Anh Hospital")
        self.assertEqual(data["room_type"], "SUPERIOR ROOM")
        self.assertEqual(str(data["check_in"]), "2026-05-07")
        self.assertEqual(data["check_in_time"], "15:00")
        self.assertEqual(str(data["check_out"]), "2026-05-07")
        self.assertEqual(data["check_out_time"], "17:00")
        self.assertTrue(is_confident_booking(data))

    def test_website_woocommerce_template_extracts_branch_from_room_type_and_cash_payment(self):
        email = {
            "sender": "binbinhotel.ota@gmail.com",
            "subject": "Đơn hàng mới: #2075",
            "html": """
                <div>Đơn hàng mới: #2075<br>
                Bạn vừa nhận được đơn hàng từ Hùng. Đơn hàng như sau:<br>
                [ĐƠN HÀNG #2075] (03/05/2026)<br>
                Deluxe Room (B17) X 1 = 600.000<br>
                Start: 03/05/2026<br>
                - End: 04/05/2026<br>
                Tổng số phụ: 600.000<br>
                Phương thức thanh toán: Trả tiền mặt khi nhận phòng<br>
                Tổng cộng: 600.000<br>
                ĐỊA CHỈ THANH TOÁN<br>
                Hùng<br>
                Long Thành, Đồng Nai<br>
                0785710031<br>
                lamquochung114x@gmail.com<br>
                Chúc mừng bạn đã bán hàng thành công.</div>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Website")
        self.assertEqual(data["external_id"], "WEB-2075")
        self.assertEqual(data["guest_name"], "Hùng")
        self.assertEqual(data["guest_phone"], "0785710031")
        self.assertEqual(data["hotel_name"], "Bin Bin Hotel B17")
        self.assertEqual(data["room_type"], "Deluxe Room (B17)")
        self.assertEqual(data["num_rooms"], 1)
        self.assertEqual(str(data["check_in"]), "2026-05-03")
        self.assertEqual(str(data["check_out"]), "2026-05-04")
        self.assertEqual(data["total_price"], 600000)
        self.assertFalse(data["is_prepaid"])
        self.assertEqual(data["payment_method"], "Trả tiền mặt khi nhận phòng")
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

    def test_agoda_current_html_template_extracts_booking_details(self):
        email = {
            "sender": "noreply@agoda.com",
            "subject": "Agoda Booking confirmation 2008838993",
            "html": """
                <span><strong>Booking ID</strong></span><span>Mã số đặt phòng</span>
                <span>2008838993</span>
                <span>TRẢ TRƯỚC</span>
                <span>Booking confirmation</span><span>Xác nhận đặt phòng</span>
                <span><strong>Bin Bin Hotel 11 -  Near Island Diamond</strong></span>
                (Property ID <span>51752654</span>)
                <span><strong>Customer First Name </strong></span><span>Tên Khách Hàng </span>
                <span>Anh Thu</span>
                <span><strong>Customer Last Name </strong></span><span>Họ Khách Hàng </span>
                <span>Huynh</span>
                <span><strong>Country of Residence </strong></span><span>Quốc gia cư trú </span>
                <span>Vietnam</span>
                <span><strong>Check-in</strong></span><span>Nhận phòng</span>
                <span>8-May-2026 (8-05-2026)</span>
                <span><strong>Check-out</strong></span><span>Trả phòng</span>
                <span>9-May-2026 (9-05-2026)</span>
                <span><strong>Room Type </strong></span><span>Loại Phòng </span>
                <span><strong>No. of Rooms</strong></span><span>Số phòng</span>
                <span><strong>Occupancy</strong></span><span>Số người</span>
                <span><strong>No. of Extra Bed</strong></span><span>Số Giường Thêm :</span>
                <span>Superior Queen</span><span>2</span><span>2 Adults</span><span>0</span>
                <span id="m_7644237551432296439ltrSpecialRequestTitle_lblMain"><strong>Special Requests</strong></span>
                <span id="m_7644237551432296439ltrSpecialRequestTitle_lblSub">Yêu cầu đặc biệt</span>
                <span>(All special requests are subject to availability upon arrival.)</span>
                <span id="m_7644237551432296439lblSupplierNoteData">NonSmoke</span>
                <span><strong>Cancellation Policy</strong></span>
                <span>Chính sách hủy phòng</span>
                <span><strong>Reference sell rate (incl. taxes &amp; fees)</strong></span>
                <span>VND</span><span>812,500.00</span>
                <span><strong>Net rate (incl. taxes &amp; fees)</strong></span>
                <span>Giá thực tế (bao gồm thuế &amp; phí)</span>
                <span>VND 650,000.00</span>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Agoda")
        self.assertEqual(data["external_id"], "2008838993")
        self.assertEqual(data["hotel_name"], "Bin Bin Hotel 11 - Near Island Diamond")
        self.assertEqual(data["guest_name"], "Anh Thu Huynh")
        self.assertEqual(str(data["check_in"]), "2026-05-08")
        self.assertEqual(str(data["check_out"]), "2026-05-09")
        self.assertEqual(data["room_type"], "Superior Queen")
        self.assertEqual(data["num_rooms"], 2)
        self.assertEqual(data["num_guests"], 2)
        self.assertEqual(data["num_adults"], 2)
        self.assertEqual(data["total_price"], 650000)
        self.assertTrue(data["is_prepaid"])
        self.assertEqual(data["payment_method"], "Agoda prepaid/net rate")
        self.assertEqual(data["notes"], "NonSmoke")
        self.assertTrue(is_confident_booking(data))

    def test_agoda_cancellation_template_extracts_cancel_action(self):
        email = {
            "sender": "no-reply@agoda.com",
            "subject": "Agoda Booking ID 1713766698 - CANCELLED Bin Bin Hotel 2 - Near Him Lam D7 Hotel Country: Vietnam / Language_English",
            "html": """
                <p>Kính gửi Quý Khách Đặt Phòng,,</p>
                <p>Lệ Phí Hủy Đặt Phòng: VND 0</p>
                <strong>Details of Booking</strong>
                <p>Mã Số Đặt Phòng : 1713766698</p>
                <p>Tên Khách Hàng : Ma. Brida Lea</p>
                <p>Họ Khách Hàng : Diola</p>
                <p>Thành Phố : Ho Chi Minh City</p>
                <p>Quốc Gia : Vietnam</p>
                <p>Ngày Đến : May 26, 2026</p>
                <p>Ngày Đi : June 1, 2026</p>
                <p>Khách Sạn : Bin Bin Hotel 2 - Near Him Lam D7</p>
                <p>Loại Phòng : Deluxe Room with King Bed - Non-Smoking</p>
                <p>Số Phòng : 1</p>
                <p>Số Người Lớn : 2</p>
                <p>Số Trẻ Em : 0</p>
                <p>Ghi Chú : NonSmoke, LargeBed, QuietRoom, ArrivalTime:12 00 - 13 00, AdditionalNotes:Room with window and view if available</p>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Agoda")
        self.assertEqual(data["action_type"], "CANCEL")
        self.assertEqual(data["external_id"], "1713766698")
        self.assertEqual(data["hotel_name"], "Bin Bin Hotel 2 - Near Him Lam D7")
        self.assertEqual(data["guest_name"], "Ma. Brida Lea Diola")
        self.assertEqual(str(data["check_in"]), "2026-05-26")
        self.assertEqual(str(data["check_out"]), "2026-06-01")
        self.assertEqual(data["room_type"], "Deluxe Room with King Bed - Non-Smoking")
        self.assertEqual(data["num_rooms"], 1)
        self.assertEqual(data["num_adults"], 2)
        self.assertEqual(data["num_children"], 0)
        self.assertEqual(data["num_guests"], 2)
        self.assertEqual(data["notes"], "NonSmoke, LargeBed, QuietRoom, ArrivalTime:12 00 - 13 00, AdditionalNotes:Room with window and view if available")
        self.assertTrue(is_confident_booking(data))

    def test_traveloka_vietnamese_tera_template_extracts_shared_fields(self):
        email = {
            "sender": "noreply@traveloka.com",
            "subject": "Traveloka Đặt chỗ mới 20261118228037",
            "html": """
                <p>Đặt chỗ mới</p><span>Trả trước</span>
                <p>Bin Bin Hotel 5 - Near Lotte Mart D7 (20004650)</p>
                <p>Thành phố: District 7</p>
                <p>Mã đặt phòng</p><p>20261118228037</p>
                <p>Tên khách</p><p>ngo</p>
                <p>Họ khách</p><p>thi thanh tam</p>
                <p>Email khách</p><p>1354395680-191283f6263b4f56@<wbr>hotel.traveloka.com</p>
                <p>Check-in</p><p>May 16, 2026</p>
                <p>Check-out</p><p>May 17, 2026</p>
                <p>Giờ đặt chỗ (UTC + 0)</p><p>May 05, 2026 11:47:50</p>
                <p>Thông tin phòng</p><p>Thông tin khách</p><p>Thông tin giường phụ</p>
                <p>(1 × ) Deluxe - Super Saver RO</p>
                <p>2 Người lớn</p>
                <p>1 Trẻ em (2 - 11) y.o</p>
                <p>Yêu cầu đặc biệt</p><p>-</p>
                <p>Chính sách huỷ phòng (dựa vào thời gian check-in của khách sạn)</p>
                <p>Đặt và thanh toán bởi</p><p>Traveloka</p>
                <p>Tổng tiền bạn sẽ nhận được</p><p>VND 600000</p>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Traveloka")
        self.assertEqual(data["external_id"], "20261118228037")
        self.assertEqual(data["hotel_name"], "Bin Bin Hotel 5 - Near Lotte Mart D7 (20004650)")
        self.assertEqual(data["guest_name"], "ngo thi thanh tam")
        self.assertEqual(data["guest_email"], "1354395680-191283f6263b4f56@hotel.traveloka.com")
        self.assertEqual(str(data["check_in"]), "2026-05-16")
        self.assertEqual(str(data["check_out"]), "2026-05-17")
        self.assertEqual(data["room_type"], "Deluxe - Super Saver RO")
        self.assertEqual(data["num_rooms"], 1)
        self.assertEqual(data["num_adults"], 2)
        self.assertEqual(data["num_children"], 1)
        self.assertEqual(data["num_guests"], 3)
        self.assertEqual(data["total_price"], 600000)
        self.assertTrue(data["is_prepaid"])
        self.assertEqual(data["payment_method"], "Traveloka prepaid")
        self.assertIsNone(data["notes"])
        self.assertTrue(is_confident_booking(data))

    def test_traveloka_cancellation_template_extracts_cancel_action(self):
        email = {
            "sender": "noreply@traveloka.com",
            "subject": "Traveloka CANCELLATION 20261118195583",
            "html": """
                <p>CANCELLATION</p><span>Prepaid</span>
                <p>Bin Bin Hotel 11 - Near Island Diamond (20077320)</p>
                <p>City: Thu Duc City</p>
                <p>Itinerary ID</p><p>20261118195583</p>
                <p>Customer First Name</p><p>Nguyen</p>
                <p>Customer Last Name</p><p>Minh Khang</p>
                <p>Guest Email</p><p>1354128256-eac9bf37dbac0be0@<wbr>hotel.traveloka.com</p>
                <p>Check-in</p><p>May 08, 2026</p>
                <p>Check-out</p><p>May 09, 2026</p>
                <p>Room Information</p><p>Guest Information</p><p>Extra Bed Information</p>
                <p>(1 × ) Deluxe Room - Best Offer</p>
                <p>2 Adult(s)</p>
                <p>Special Request</p>
                <p>1. High Floor 2. Check-in Time (19:00)</p>
                <p>Cancellation policy (based on your hotel check-in time)</p>
                <p>Cancellation Detail</p>
                <p>Cancelled by system on traveloka.com</p>
                <p>Refunded Amount</p><p>VND 700000</p>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Traveloka")
        self.assertEqual(data["action_type"], "CANCEL")
        self.assertEqual(data["external_id"], "20261118195583")
        self.assertEqual(data["hotel_name"], "Bin Bin Hotel 11 - Near Island Diamond (20077320)")
        self.assertEqual(data["guest_name"], "Nguyen Minh Khang")
        self.assertEqual(data["guest_email"], "1354128256-eac9bf37dbac0be0@hotel.traveloka.com")
        self.assertEqual(str(data["check_in"]), "2026-05-08")
        self.assertEqual(str(data["check_out"]), "2026-05-09")
        self.assertEqual(data["room_type"], "Deluxe Room - Best Offer")
        self.assertEqual(data["num_rooms"], 1)
        self.assertEqual(data["num_adults"], 2)
        self.assertEqual(data["total_price"], 700000)
        self.assertTrue(data["is_prepaid"])
        self.assertTrue(is_confident_booking(data))

    def test_tripcom_cancellation_template_extracts_cancel_action(self):
        email = {
            "sender": "auto_reservation@trip.com",
            "subject": "Action required-Cancellation request accepted (booking no.#1128147761948280#)",
            "html": """
                <p>You have received a notification of a <span>canceled</span> booking</p>
                <p>The reservation below has been canceled. Make sure it is also canceled in your system.</p>
                <p>Reservation no. <span>1128147761948280</span></p>
                <p>Hotel</p><p>Bin Bin Hotel 7 - Near Ton Duc Thang University</p>
                <p>Guest Name</p><p>LU/XIAODONG</p>
                <p>Booking Amount</p><p>VND 1750000</p>
                <p>Room Type</p><p>Twin Room B2B room only | 1 room(s)</p>
                <p>Staying period</p><p>Sep 26, 2026 - Sep 28, 2026 | 2 night(s)</p>
                <p>Applicable cancellation fees</p><p>VND 0.00</p>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Trip.com")
        self.assertEqual(data["action_type"], "CANCEL")
        self.assertEqual(data["external_id"], "1128147761948280")
        self.assertEqual(data["hotel_name"], "Bin Bin Hotel 7 - Near Ton Duc Thang University")
        self.assertEqual(data["guest_name"], "LU/XIAODONG")
        self.assertEqual(data["room_type"], "Twin Room B2B room only")
        self.assertEqual(data["num_rooms"], 1)
        self.assertEqual(str(data["check_in"]), "2026-09-26")
        self.assertEqual(str(data["check_out"]), "2026-09-28")
        self.assertEqual(data["total_price"], 1750000)
        self.assertTrue(is_confident_booking(data))

    def test_expedia_vietnamese_template_extracts_shared_fields_and_net_amount(self):
        email = {
            "sender": "notify@expedia.com",
            "subject": "Expedia Booking 2453591445",
            "html": """
                <td>Đặt phòng mới</td>
                <td>Bin Bin Hotel 14 - Near Vstar School D7</td>
                <td>Ho Chi Minh City,VNM</td>
                <td>Khách đã THANH TOÁN TRƯỚC</td>
                <td><b>Mã đặt phòng: </b><a>2453591445</a></td>
                <td><b>Khách: </b>SHIHPENG  LIN</td>
                <td>Đặt vào: 05-05-2026 09:38 PST</td>
                <td colspan="3"><b>Email khách: </b>r5f81sfnpc@m.<wbr>expediapartnercentral.com</td>
                <td colspan="3">Mã loại phòng: Deluxe Suite</td>
                <td>Tên loại phòng: </td><td>Phòng Suite Deluxe - Standard</td>
                <td>Deluxe Suite - Standard</td>
                <td>Hướng dẫn thanh toán: Expedia thu khoản thanh toán từ khách: Khách sạn xuất hóa đơn cho Expedia.</td>
                <td>Nhận phòng</td><td>Trả phòng</td><td>Người lớn</td><td>Trẻ/Tuổi</td><td>Đêm phòng</td><td>Số xác nhận khách sạn</td>
                <td>12-05-2026</td><td>13-05-2026</td><td>1</td><td>0</td><td>1</td><td></td>
                <td><b>Yêu cầu đặc biệt</b></td>
                <td>1 Queen Bed, Non-Smoking</td>
                <td><b>Khách gửi yêu cầu cho khách sạn</b></td>
                <td>Quiet room preferred,No corner room,Smoke-free treatment required,Luggage storage</td>
                <td>Giá linh hoạt Expedia: Có</td>
                <td><b>Tổng khoản tiền đặt phòng: </b></td><td><b>915,067 VND</b></td>
                <td><b>Khoản tiền thu từ Expedia Group: </b></td><td><b>752,250 VND</b></td>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Expedia")
        self.assertEqual(data["external_id"], "2453591445")
        self.assertEqual(data["hotel_name"], "Bin Bin Hotel 14 - Near Vstar School D7")
        self.assertEqual(data["guest_name"], "SHIHPENG LIN")
        self.assertEqual(data["guest_email"], "r5f81sfnpc@m.expediapartnercentral.com")
        self.assertEqual(str(data["check_in"]), "2026-05-12")
        self.assertEqual(str(data["check_out"]), "2026-05-13")
        self.assertEqual(data["room_type"], "Phòng Suite Deluxe - Standard")
        self.assertEqual(data["num_rooms"], 1)
        self.assertEqual(data["num_adults"], 1)
        self.assertEqual(data["num_children"], 0)
        self.assertEqual(data["num_guests"], 1)
        self.assertEqual(data["total_price"], 752250)
        self.assertTrue(data["is_prepaid"])
        self.assertEqual(data["payment_method"], "Expedia prepaid/collect")
        self.assertEqual(data["notes"], "Quiet room preferred,No corner room,Smoke-free treatment required,Luggage storage")
        self.assertTrue(is_confident_booking(data))

    def test_expedia_english_template_extracts_shared_fields_and_net_amount(self):
        email = {
            "sender": "notify@expedia.com",
            "subject": "Expedia New Reservation 2453315582",
            "html": """
                <td>New Reservation</td>
                <td>BIN BIN HOTEL 11- NEAR ISLAND DIAMOND</td>
                <td>Ho Chi Minh City,VNM</td>
                <td>Guest has PRE-PAID</td>
                <td><b>Reservation ID: </b><a>2453315582</a></td>
                <td><b>Guest: </b>GANG  WANG</td>
                <td align="right">Booked on: May 5, 2026 1:53 AM PST</td>
                <td colspan="3"><b>Guest Email: </b>sl4htsuioh@m.<wbr>expediapartnercentral.com</td>
                <td colspan="3">Room Type Code: Standard Double Room</td>
                <td>Room Type Name: </td><td>Standard Double Room - Standard</td>
                <td>Pricing Model: Per Day Pricing</td>
                <td>Payment Instructions: Expedia collects payment from traveler: Hotel invoices Expedia.</td>
                <td>Check-In</td><td>Check-Out</td><td>Adults</td><td>Kids/Ages</td><td>Room Nights</td><td>Hotel Conf</td>
                <td>May 6, 2026</td><td>May 7, 2026</td><td>1</td><td>0</td><td>1</td><td></td>
                <td><b>Special Request</b></td>
                <td>1 Queen Bed, Non-Smoking</td>
                <td><b>Customer entered request to hotel</b></td>
                <td>&amp;lpar;WANG GANG&amp;rpar;</td>
                <td><b>!LAST-MINUTE BOOKING - NO GUEST NAME CHANGES ALLOWED - PLEASE CHECK ID!</b></td>
                <td>Expedia Flexible Rate: Yes</td>
                <td><b>Total Booking Amount: </b></td><td><b>790,738 VND</b></td>
                <td><b>Amount to Charge Expedia Group: </b></td><td><b>650,194 VND</b></td>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Expedia")
        self.assertEqual(data["external_id"], "2453315582")
        self.assertEqual(data["hotel_name"], "BIN BIN HOTEL 11- NEAR ISLAND DIAMOND")
        self.assertEqual(data["guest_name"], "GANG WANG")
        self.assertEqual(data["guest_email"], "sl4htsuioh@m.expediapartnercentral.com")
        self.assertEqual(str(data["check_in"]), "2026-05-06")
        self.assertEqual(str(data["check_out"]), "2026-05-07")
        self.assertEqual(data["room_type"], "Standard Double Room - Standard")
        self.assertEqual(data["num_rooms"], 1)
        self.assertEqual(data["num_adults"], 1)
        self.assertEqual(data["num_children"], 0)
        self.assertEqual(data["num_guests"], 1)
        self.assertEqual(data["total_price"], 650194)
        self.assertTrue(data["is_prepaid"])
        self.assertEqual(data["payment_method"], "Expedia prepaid/collect")
        self.assertEqual(data["notes"], "&lpar;WANG GANG&rpar;")
        self.assertTrue(is_confident_booking(data))

    def test_traveloka_standard_template_extracts_shared_fields(self):
        email = {
            "sender": "noreply@traveloka.com",
            "subject": "Traveloka New Booking 20261118186080",
            "html": """
                <p>New Booking</p>
                <span>Prepaid</span>
                <p>Bin Bin Hotel 1 - Near RMIT University D7 (10032919)</p>
                <p>City: District 7</p>
                <p>Itinerary ID</p><p>20261118186080</p>
                <p>Customer First Name</p><p>Minh</p>
                <p>Customer Last Name</p><p>Hang</p>
                <p>Guest Contact</p><p>+84387079640</p>
                <p>Guest Email</p><p>1354058610-1feb71981bc42e15@hotel.traveloka.com</p>
                <p>Check-in</p><p>May 09, 2026</p>
                <p>Check-out</p><p>May 10, 2026</p>
                <p>Booking time (UTC+0)</p><p>May 04, 2026 12:21:08</p>
                <p>Room Information</p><p>Guest Information</p><p>Extra Bed Information</p>
                <p>(1 × ) Superior Room - Best Offer</p>
                <p>2 Adult(s)</p>
                <p>1 Child (2 - 12) y.o</p>
                <p>Special Request</p><p>-</p>
                <p>Cancellation policy (based on your hotel check-in time)</p>
                <p>Total you will receive</p><p>VND 500000</p>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Traveloka")
        self.assertEqual(data["external_id"], "20261118186080")
        self.assertEqual(data["hotel_name"], "Bin Bin Hotel 1 - Near RMIT University D7 (10032919)")
        self.assertEqual(data["guest_name"], "Minh Hang")
        self.assertEqual(data["guest_phone"], "+84387079640")
        self.assertEqual(data["guest_email"], "1354058610-1feb71981bc42e15@hotel.traveloka.com")
        self.assertEqual(str(data["check_in"]), "2026-05-09")
        self.assertEqual(str(data["check_out"]), "2026-05-10")
        self.assertEqual(data["room_type"], "Superior Room - Best Offer")
        self.assertEqual(data["num_rooms"], 1)
        self.assertEqual(data["num_adults"], 2)
        self.assertEqual(data["num_children"], 1)
        self.assertEqual(data["num_guests"], 3)
        self.assertEqual(data["total_price"], 500000)
        self.assertTrue(data["is_prepaid"])
        self.assertEqual(data["payment_method"], "Traveloka prepaid")
        self.assertIsNone(data["notes"])
        self.assertTrue(is_confident_booking(data))

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

    def test_tripcom_confirmed_template_extracts_shared_fields(self):
        email = {
            "sender": "noreply@trip.com",
            "subject": "Trip.com Reservation Confirmed 1365639910698604",
            "html": """
                <p>Reservation <span>Confirmed</span></p>
                <p>You have accepted the guest's reservation.</p>
                <span>Reservation no.</span><span>1365639910698604</span>
                <span>Property confirmation no.</span><span>Ctrip</span>
                <p>Please update the reservation information in your property management system (PMS) as soon as possible.</p>
                <p>Bin Bin Hotel 10 - Mimosa Near Tan Son Nhat Airport</p>
                <div>Guest Name:</div><div>JAMATIA/HIMALAY,Nguyen/Dung Quoc</div>
                <span>Room Type:</span><span>Superior Room B2B RO | 1 room(s)</span>
                <span>Bed type:</span><span>1 Queen bed</span>
                <span>Staying period:</span><span>Mar 6, 2026 - Mar 9, 2026 | 3 night(s)</span>
                <span>Arrival time:</span><span>14:00, Mar 6 - 06:00, Mar 7</span>
                <span>Guests (estimated):</span><span>1 adult</span>
                <span>Payment information</span><span>Net rate｜Prepaid｜monthly settlement</span>
                <span>Room rate 1 room(s) × 3 night(s)</span>
                <span>This rate is for 2 adults</span>
                <span>Your payout</span><span>VND</span><span>1650000.00</span>
                <span>Additional Information</span>
                <span>Special requests</span><span>Other requests:</span><span>Away from elevator,Quiet room</span>
                <span>Cancellation Policy</span><span>After reservation is confirmed</span><span>Non-refundable</span>
                <span>Note</span><span>This is a prepaid reservation. The guest has already paid for the room.</span>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Trip.com")
        self.assertEqual(data["external_id"], "1365639910698604")
        self.assertEqual(data["hotel_name"], "Bin Bin Hotel 10 - Mimosa Near Tan Son Nhat Airport")
        self.assertEqual(data["guest_name"], "JAMATIA/HIMALAY,Nguyen/Dung Quoc")
        self.assertEqual(str(data["check_in"]), "2026-03-06")
        self.assertEqual(str(data["check_out"]), "2026-03-09")
        self.assertEqual(data["check_in_time"], "14:00")
        self.assertEqual(data["room_type"], "Superior Room B2B RO")
        self.assertEqual(data["num_rooms"], 1)
        self.assertEqual(data["num_adults"], 1)
        self.assertEqual(data["num_children"], 0)
        self.assertEqual(data["num_guests"], 1)
        self.assertEqual(data["total_price"], 1650000)
        self.assertTrue(data["is_prepaid"])
        self.assertEqual(data["payment_method"], "Trip.com net rate/prepaid")
        self.assertEqual(data["notes"], "Away from elevator,Quiet room")
        self.assertTrue(is_confident_booking(data))

    def test_mytour_success_template_extracts_shared_fields(self):
        email = {
            "sender": "hotelsupport@mytour.vn",
            "subject": "Mytour Đơn phòng thành công H5977542",
            "html": """
                <span>ĐƠN PHÒNG THÀNH CÔNG</span>
                <span>MYTOUR</span>
                <span>Kính chào <strong>BIN BIN Hotel 11 - Near Island Diamond</strong>,</span>
                <span>Quý đối tác có một đơn đặt phòng thành công đã được thanh toán trên hệ thống đặt phòng của VNTravel Partner Solution.</span>
                <span>truy cập hệ thống để xem chi tiết đơn hàng <strong>H5977542</strong>.</span>
                <span>H5977542</span><span>Mã đơn phòng</span>
                <span>01-04-2026</span><span>Check-in</span>
                <span>03-04-2026</span><span>Check-out</span>
                <span>*Vui lòng liên hệ lại Mytour nếu khách sạn có mã Check in riêng</span>
                <span>Thông tin khách hàng</span><span>Họ tên</span><span>LINGLING HUANG</span><span>SĐT</span>
                <span>Thông tin khách sạn</span><span>Tên KS</span><span>BIN BIN Hotel 11 - Near Island Diamond</span><span>Địa chỉ</span>
                <span>Deluxe Room</span><span>|</span><span>1</span><span>phòng</span>
                <span>Số khách tiêu chuẩn</span><span>1</span><span>người lớn</span>
                <span>Tổng số khách</span><span>1</span><span>người lớn</span><span>0</span><span>trẻ em</span>
                <span>Yêu cầu đặc biệt</span><span>• Yêu cầu khác: .null</span>
                <span>Chính sách hoàn hủy</span><span>Đơn phòng không hoàn hủy, không thay đổi</span>
                <span>Chi tiết giá phòng</span><span>01-04-2026</span><span>649.440</span>
                <span>02-04-2026</span><span>649.440</span>
                <span>Tổng</span><span>1.298.880</span><span>Phụ thu dịch vụ khác:</span>
                <span>Tổng tiền phòng</span><span>1.584.000</span>
                <span>Tổng tiền trả khách sạn</span><span>1.298.880</span>
                <span>Đặt và thanh toán bởi CÔNG TY CỔ PHẦN DU LỊCH VIỆT NAM VNTRAVEL</span>
            """,
        }

        data = self.extractor.extract(email)

        self.assertEqual(data["booking_source"], "Mytour")
        self.assertEqual(data["external_id"], "H5977542")
        self.assertEqual(data["hotel_name"], "BIN BIN Hotel 11 - Near Island Diamond")
        self.assertEqual(data["guest_name"], "LINGLING HUANG")
        self.assertEqual(str(data["check_in"]), "2026-04-01")
        self.assertEqual(str(data["check_out"]), "2026-04-03")
        self.assertEqual(data["room_type"], "Deluxe Room")
        self.assertEqual(data["num_rooms"], 1)
        self.assertEqual(data["num_adults"], 1)
        self.assertEqual(data["num_children"], 0)
        self.assertEqual(data["num_guests"], 1)
        self.assertEqual(data["total_price"], 1298880)
        self.assertTrue(data["is_prepaid"])
        self.assertEqual(data["payment_method"], "Mytour prepaid/VNTravel")
        self.assertIsNone(data["notes"])
        self.assertTrue(is_confident_booking(data))

    def test_unknown_or_incomplete_email_returns_none_so_gemini_can_fallback(self):
        email = {
            "sender": "partner@example.com",
            "subject": "Booking notification",
            "html": "There is a booking but no date and no price",
        }

        self.assertIsNone(self.extractor.extract(email))


if __name__ == "__main__":
    unittest.main()
