import unittest
from unittest.mock import patch, AsyncMock
from app.api.pms.mrz_parser import (
    _parse_mrz_date,
    parse_mrz_text,
    parse_mrz_from_image,
)
import app.api.pms.mrz_parser as mrz_parser


class PhotoScanTestCase(unittest.TestCase):
    def test_parse_mrz_date_birth(self):
        # YY <= current_yy (e.g. 26 is <= 26 assume 2000s)
        self.assertEqual(_parse_mrz_date("260515", is_birth=True), "2026-05-15")
        # YY > current_yy (e.g. 90 is > 26 assume 1900s)
        self.assertEqual(_parse_mrz_date("900515", is_birth=True), "1990-05-15")
        # Empty/invalid
        self.assertEqual(_parse_mrz_date("", is_birth=True), "")
        self.assertEqual(_parse_mrz_date("abcd12", is_birth=True), "")

    def test_parse_mrz_date_expiry(self):
        # Expiry: assume 2000s
        self.assertEqual(_parse_mrz_date("301231", is_birth=False), "2030-12-31")

    def test_parse_mrz_text_td3_valid(self):
        # Valid TD3 (Passport) MRZ
        # Line 1: P<USASTEPHENS<<MARIA<<<<<<<<<<<<<<<<<<<<<<<<
        # Line 2: B9876543<1USA9005156F3012316<<<<<<<<<<<<<<02
        mrz_lines = [
            "P<USASTEPHENS<<MARIA<<<<<<<<<<<<<<<<<<<<<<<<",
            "B9876543<1USA9005156F3012316<<<<<<<<<<<<<<02",
        ]
        res = parse_mrz_text(mrz_lines)
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["card_type"], "passport")
        self.assertEqual(res["id_number"], "B9876543")
        self.assertEqual(res["name"], "Stephens Maria")
        self.assertEqual(res["dob"], "1990-05-15")
        self.assertEqual(res["gender"], "Nữ")
        self.assertEqual(res["expiry_date"], "2030-12-31")
        self.assertEqual(res["nationality"], "USA")

    def test_parse_mrz_text_invalid(self):
        res = parse_mrz_text(["INVALID MRZ LINE 1", "INVALID MRZ LINE 2"])
        self.assertFalse(res["is_valid"])
        self.assertIn("error", res)


class PhotoScanAsyncTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_parse_passport_uses_vision_labeled_fields(self):
        vision_text = (
            "Surname: Stephens\nGiven names: Maria\nPassport No: B9876543\n"
            "Nationality: USA\nDate of birth: 15/05/1990\nSex: F\n"
            "Date of expiry: 31/12/2030\nDate of issue: 01/01/2020\n"
        )
        with patch.object(mrz_parser.settings, "GATECHEAP_API_KEY", "test-key"), \
             patch.object(mrz_parser, "_run_passport_ocr", new=AsyncMock(return_value=vision_text)) as mock_vision:
            result = await parse_mrz_from_image(b"fake-image-bytes", "passport.jpg")
            self.assertTrue(result["is_valid"])
            self.assertEqual(result["card_type"], "passport")
            self.assertEqual(result["id_number"], "B9876543")
            self.assertEqual(result["name"], "Stephens Maria")
            self.assertEqual(result["dob"], "1990-05-15")
            self.assertEqual(result["gender"], "Nữ")
            self.assertEqual(result["expiry_date"], "2030-12-31")
            self.assertEqual(result["nationality"], "USA")
            mock_vision.assert_called_once()

    async def test_parse_passport_returns_error_when_vision_returns_empty(self):
        with patch.object(mrz_parser.settings, "GATECHEAP_API_KEY", "test-key"), \
             patch.object(mrz_parser, "_run_passport_ocr", new=AsyncMock(return_value="")):
            result = await parse_mrz_from_image(b"fake-image-bytes", "passport.jpg")
            self.assertFalse(result["is_valid"])
            self.assertIn("MRZ", result["error"])

    async def test_parse_mrz_from_image_without_api_key_does_not_return_mock(self):
        # When GATECHEAP_API_KEY is missing, passport parser must NOT inject mock data.
        with patch.object(mrz_parser.settings, "GATECHEAP_API_KEY", ""):
            result = await parse_mrz_from_image(b"not-an-image", "real_passport.jpg")
            self.assertFalse(result["is_valid"])
            self.assertNotIn("JOHN SMITH", str(result))
            self.assertIn("chưa được cấu hình", result["error"])


if __name__ == "__main__":
    unittest.main()
