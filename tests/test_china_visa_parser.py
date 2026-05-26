import unittest
from app.api.pms.china_visa_parser import parse_china_visa


class ChinaVisaParserTestCase(unittest.TestCase):
    def test_china_visa_parser_does_not_return_mock_valid_data(self):
        result = parse_china_visa(b"fake-image-bytes", "visa.jpg")

        self.assertFalse(result["is_valid"])
        self.assertEqual(result["card_type"], "visa")
        self.assertIn("chưa hỗ trợ", result["error"])
        self.assertNotIn("ZHANG WEI", str(result))
        self.assertNotIn("V1234567", str(result))


if __name__ == "__main__":
    unittest.main()
