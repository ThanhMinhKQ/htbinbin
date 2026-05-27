import unittest
from unittest.mock import patch, MagicMock
from app.api.pms.cccd_image_parser import _parse_cccd_text, parse_cccd_image

class CccdImageParserTestCase(unittest.TestCase):
    def test_parse_cccd_text_front_only_can_cuoc_moi(self):
        # Sample OCR text returned by Google Vision on a modern CCCD (Căn cước công dân gắn chip)
        front_text = """
CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Độc lập - Tự do - Hạnh phúc
CĂN CƯỚC CÔNG DÂN
Citizen Identity Card
Số / No.: 038096012345
Họ và tên / Full name:
LÊ HẢI ĐĂNG
Ngày sinh / Date of birth: 15/08/1996
Giới tính / Sex: Nam
Quốc tịch / Nationality: Việt Nam
Quê quán / Place of origin: Hải Hậu, Nam Định
Nơi thường trú / Place of residence:
123 Đường Lê Lợi, Phường Bến Nghé, Thành phố Hồ Chí Minh
Có giá trị đến / Date of expiry: 15/08/2036
        """
        res = _parse_cccd_text(front_text)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["card_type"], "CAN_CUOC_MOI")
        self.assertEqual(res["id_number"], "038096012345")
        self.assertEqual(res["name"], "Lê Hải Đăng")
        self.assertEqual(res["dob"], "15/08/1996")
        self.assertEqual(res["gender"], "Nam")
        self.assertEqual(res["nationality"], "Việt Nam")
        self.assertEqual(res["place_of_origin"], "Hải Hậu, Nam Định")
        self.assertEqual(res["address"]["province"], "Thành phố Hồ Chí Minh")
        self.assertEqual(res["address"]["district"], "") # Căn cước mới không lưu district
        self.assertEqual(res["address"]["ward"], "Phường Bến Nghé")
        self.assertEqual(res["address"]["detail"], "123 Đường Lê Lợi")
        self.assertEqual(res["expiry_date"], "15/08/2036")

    def test_parse_cccd_text_front_only_cccd_cu(self):
        # Sample OCR text for older CCCD format (pre-2024, 4 levels)
        front_text = """
CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Độc lập - Tự do - Hạnh phúc
CĂN CƯỚC CÔNG DÂN
Số / No.: 030096055555
Họ và tên: LÊ HẢI ĐĂNG
Ngày sinh: 15/08/1996
Giới tính: Nam
Quốc tịch: Việt Nam
Quê quán: Xã Hải Anh, Huyện Hải Hậu, Tỉnh Nam Định
Nơi thường trú: Tổ 4, Thị trấn Thịnh Long, Huyện Hải Hậu, Tỉnh Nam Định
Có giá trị đến: 15/08/2036
        """
        res = _parse_cccd_text(front_text)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["card_type"], "CCCD_CU")
        self.assertEqual(res["id_number"], "030096055555")
        self.assertEqual(res["name"], "Lê Hải Đăng")
        self.assertEqual(res["dob"], "15/08/1996")
        self.assertEqual(res["gender"], "Nam")
        self.assertEqual(res["nationality"], "Việt Nam")
        self.assertEqual(res["place_of_origin"], "Xã Hải Anh, Huyện Hải Hậu, Tỉnh Nam Định")
        self.assertEqual(res["address"]["province"], "Nam Định")
        self.assertEqual(res["address"]["district"], "Huyện Hải Hậu")
        self.assertEqual(res["address"]["ward"], "Thị trấn Thịnh Long")
        self.assertEqual(res["address"]["detail"], "Tổ 4")
        self.assertEqual(res["expiry_date"], "15/08/2036")

    def test_parse_cccd_text_with_back_side(self):
        front_text = """
Số / No.: 038096012345
Họ và tên: LÊ HẢI ĐĂNG
Ngày sinh: 15/08/1996
Giới tính: Nam
Quốc tịch: Việt Nam
Nơi thường trú: Phường Bến Nghé, Quận 1, TP HCM
        """
        # Back side OCR containing issue date
        back_text = """
CỤC TRƯỞNG CỤC CẢNH SÁT QUẢN LÝ HÀNH CHÍNH
VỀ TRẬT TỰ XÃ HỘI
Hà Nội, ngày 20 tháng 04 năm 2024
ĐẶC ĐIỂM NHẬN DẠNG
Nốt ruồi cách 1cm dưới sau cánh mũi trái
        """
        res = _parse_cccd_text(front_text, back_text)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["id_number"], "038096012345")
        self.assertEqual(res["issue_date"], "20/04/2024")
        self.assertEqual(res["expiry_date"], "15/08/2036") # calculated from DOB/age rule if not in front_text

    def test_parse_cccd_text_missing_essential_fields(self):
        # Missing name and DOB
        front_text = "Số / No.: 038096012345\nChỉ có số không có tên"
        res = _parse_cccd_text(front_text)
        self.assertFalse(res["is_valid"])
        self.assertEqual(res["id_number"], "038096012345")
        self.assertIn("Không thể trích xuất các trường thông tin bắt buộc", res["error"])

    @patch("app.api.pms.cccd_image_parser.settings")
    def test_parse_cccd_image_no_mock_fallback(self, mock_settings):
        mock_settings.GATECHEAP_API_KEY = None
        import asyncio
        res = asyncio.run(parse_cccd_image(b"dummy_front_bytes", b"dummy_back_bytes"))
        self.assertFalse(res["is_valid"])
        self.assertIn("Không thể đọc được nội dung", res["error"])

    def test_parse_cccd_text_can_cuoc_moi_address_on_back(self):
        """Căn cước mới: Nơi thường trú ở mặt sau, mặt trước không có."""
        front_text = """
Số / No.: 038024012345
Họ và tên / Full name:
NGUYỄN VĂN AN
Ngày sinh / Date of birth: 10/05/2000
Giới tính / Sex: Nam
Quốc tịch / Nationality: Việt Nam
Quê quán / Place of origin: Hải Hậu, Nam Định
Có giá trị đến / Date of expiry: 10/05/2050
        """
        back_text = """
Nơi thường trú / Place of residence:
123 Đường Nguyễn Huệ, Phường Bến Nghé, Thành phố Hồ Chí Minh
Đặc điểm nhận dạng: Sẹo ở cằm
Ngày 15 tháng 03 năm 2024
CỤC TRƯỞNG CỤC CẢNH SÁT
        """
        res = _parse_cccd_text(front_text, back_text)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["id_number"], "038024012345")
        self.assertEqual(res["name"], "Nguyễn Văn An")
        # Address parsed from back
        self.assertIn("Nguyễn Huệ", res["address"]["raw"])
        self.assertEqual(res["address"]["province"], "Thành phố Hồ Chí Minh")
        self.assertEqual(res["address"]["ward"], "Phường Bến Nghé")
        self.assertEqual(res["issue_date"], "15/03/2024")

    def test_parse_cccd_text_can_cuoc_moi_back_overrides_front_origin_like_address(self):
        front_text = """
Số / No.: 038024012345
Họ và tên / Full name:
NGUYỄN VĂN AN
Ngày sinh / Date of birth: 10/05/2000
Giới tính / Sex: Nam
Quốc tịch / Nationality: Việt Nam
Quê quán / Place of origin: Hải Hậu, Nam Định
Nơi thường trú / Place of residence: Hải Hậu, Nam Định
Có giá trị đến / Date of expiry: 10/05/2050
        """
        back_text = """
Nơi thường trú / Place of residence:
123 Đường Nguyễn Huệ, Phường Bến Nghé, Thành phố Hồ Chí Minh
Đặc điểm nhận dạng: Sẹo ở cằm
Ngày 15 tháng 03 năm 2024
        """
        res = _parse_cccd_text(front_text, back_text)
        self.assertTrue(res["is_valid"])
        self.assertIn("Nguyễn Huệ", res["address"]["raw"])
        self.assertEqual(res["address"]["province"], "Thành phố Hồ Chí Minh")
        self.assertEqual(res["address"]["ward"], "Phường Bến Nghé")

    def test_parse_cccd_text_can_cuoc_moi_back_address_without_label(self):
        front_text = """
Số / No.: 038024012345
Họ và tên / Full name:
NGUYỄN VĂN AN
Ngày sinh / Date of birth: 10/05/2000
Giới tính / Sex: Nam
Quốc tịch / Nationality: Việt Nam
Quê quán / Place of origin: Hải Hậu, Nam Định
Có giá trị đến / Date of expiry: 10/05/2050
        """
        back_text = """
123 Đường Nguyễn Huệ, Phường Bến Nghé, Thành phố Hồ Chí Minh
Đặc điểm nhận dạng: Sẹo ở cằm
Ngày 15 tháng 03 năm 2024
        """
        res = _parse_cccd_text(front_text, back_text)
        self.assertTrue(res["is_valid"])
        self.assertIn("Nguyễn Huệ", res["address"]["raw"])
        self.assertEqual(res["address"]["province"], "Thành phố Hồ Chí Minh")
        self.assertEqual(res["address"]["ward"], "Phường Bến Nghé")

if __name__ == "__main__":
    unittest.main()
