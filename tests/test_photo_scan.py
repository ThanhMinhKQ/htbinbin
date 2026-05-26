import unittest
from app.api.pms.mrz_parser import _parse_mrz_date, parse_mrz_text, parse_mrz_from_image

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
            "B9876543<1USA9005156F3012316<<<<<<<<<<<<<<02"
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

    def test_parse_mrz_from_image_mock_fallback(self):
        # Triggers mock fallback because 'mock' is in filename
        res = parse_mrz_from_image(b"", filename="mock_passport.png")
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["card_type"], "passport")
        self.assertEqual(res["id_number"], "B9876543")
        self.assertEqual(res["name"], "JOHN SMITH")

if __name__ == "__main__":
    unittest.main()
