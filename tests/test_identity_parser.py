import unittest

from app.api.pms.cccd_scan_api import _calc_confidence, preprocess_raw
from app.api.pms.identity_parser import CAN_CUOC_MOI, CCCD_CU, CMND_TYPE, parse_qr


class IdentityParserQrTest(unittest.TestCase):
    def test_parses_old_cccd_with_old_id_and_old_address_mode(self):
        result = parse_qr(
            "079098000001|024123456|NGUYỄN VĂN A|01011998|Nam|"
            "Số 1 Đường ABC, Phường 1, Quận 1, TP. Hồ Chí Minh|01012022"
        )

        self.assertTrue(result["is_valid"], result.get("error"))
        self.assertEqual(result["card_type"], CCCD_CU)
        self.assertEqual(result["address_mode"], "old")
        self.assertEqual(result["id_number"], "079098000001")
        self.assertEqual(result["old_id"], "024123456")
        self.assertEqual(result["dob"], "01/01/1998")
        self.assertEqual(result["gender"], "Nam")
        self.assertEqual(result["address"]["district"], "Quận 1")
        self.assertGreaterEqual(result["confidence"], 0.9)
        self.assertEqual(result["conflicts"], [])

    def test_parses_new_can_cuoc_with_2024_issue_and_new_address_mode(self):
        result = parse_qr(
            "079324000001||NGUYỄN THỊ B|02012024|Nữ|"
            "Số 2 Đường DEF, Phường Bến Nghé, TP. Hồ Chí Minh|01012024"
        )

        self.assertTrue(result["is_valid"], result.get("error"))
        self.assertEqual(result["card_type"], CAN_CUOC_MOI)
        self.assertEqual(result["address_mode"], "new")
        self.assertEqual(result["dob"], "02/01/2024")
        self.assertEqual(result["gender"], "Nữ")
        self.assertEqual(result["address"]["district"], "")
        self.assertEqual(result["address"]["ward"], "Phường Bến Nghé")

    def test_sample_old_cccd_with_new_admin_address_uses_new_address_mode(self):
        result = parse_qr(
            "074201005464|281342079|Nguyễn Hoàng Thanh Minh|09032001|Nam|"
            "Tổ 13, Ấp Hòa Cường, Minh Thạnh, TP. Hồ Chí Minh|19032026||||"
        )

        self.assertTrue(result["is_valid"], result.get("error"))
        self.assertEqual(result["old_id"], "281342079")
        self.assertEqual(result["address_mode"], "new")
        self.assertEqual(result["address"]["province"], "Thành phố Hồ Chí Minh")
        self.assertEqual(result["address"]["district"], "")
        self.assertEqual(result["address"]["ward"], "Minh Thạnh")
        self.assertEqual(result["address"]["detail"], "Tổ 13, Ấp Hòa Cường")

    def test_hanoi_duplicated_province_address_uses_new_address_mode(self):
        result = parse_qr(
            "001083009657|013000725|Vũ Ngọc Quang|12081983|Nam|"
            "Tập Thể 116, Thanh Liệt, Hà Nội, Hà Nội|06082024||||"
        )

        self.assertTrue(result["is_valid"], result.get("error"))
        self.assertEqual(result["address_mode"], "new")
        self.assertEqual(result["address"]["province"], "Hà Nội")
        self.assertEqual(result["address"]["district"], "")
        self.assertEqual(result["address"]["ward"], "Thanh Liệt")
        self.assertEqual(result["address"]["detail"], "Tập Thể 116")

    def test_old_cccd_preserves_town_ward_when_district_name_repeats(self):
        result = parse_qr(
            "017096006320|113671520|Lê Tuấn Anh|09121996|Nam|"
            "Khu 2, Thị trấn Cao Phong, Cao Phong, Hòa Bình|29092022"
        )

        self.assertTrue(result["is_valid"], result.get("error"))
        self.assertEqual(result["address_mode"], "old")
        self.assertEqual(result["address"]["province"], "Hòa Bình")
        self.assertEqual(result["address"]["district"], "Cao Phong")
        self.assertEqual(result["address"]["ward"], "Thị trấn Cao Phong")
        self.assertEqual(result["address"]["detail"], "Khu 2")

    def test_classifies_nine_digit_only_identity_as_cmnd_old_address_mode(self):
        result = parse_qr(
            "024123456|TRẦN VĂN C|03011980|nam|"
            "Số 3, Phường 2, Quận 3, TP. Hồ Chí Minh|01012010"
        )

        self.assertTrue(result["is_valid"], result.get("error"))
        self.assertEqual(result["card_type"], CMND_TYPE)
        self.assertEqual(result["address_mode"], "old")
        self.assertEqual(result["old_id"], "024123456")
        self.assertEqual(result["gender"], "Nam")
        self.assertEqual(result["address"]["district"], "Quận 3")

    def test_rejects_gender_conflict_between_id_code_and_explicit_field(self):
        result = parse_qr(
            "079398000001|NGUYỄN VĂN D|01011998|Nam|"
            "Số 4, Phường 1, Quận 1, TP. Hồ Chí Minh|01012024"
        )

        self.assertFalse(result["is_valid"])
        self.assertIn("gender_mismatch", result["conflicts"])
        self.assertLess(result["confidence"], 0.8)

    def test_accepts_unaccented_name_and_decomposed_vietnamese_after_normalization(self):
        raw = (
            "﻿０７９０９８０００００２|||NGUYEN VAN E|01011998|NAM|"
            "So 5, Phường 1, Quận 1, TP. Hồ Chí Minh|01012022\x00\r\n"
        )
        result = parse_qr(preprocess_raw(raw))

        self.assertTrue(result["is_valid"], result.get("error"))
        self.assertEqual(result["id_number"], "079098000002")
        self.assertEqual(result["name"], "NGUYEN VAN E")
        self.assertEqual(result["gender"], "Nam")
        self.assertEqual(result["raw_cleaned"].count("||"), 1)

    def test_confidence_drops_for_missing_optional_address(self):
        result = parse_qr("079098000003|NGUYEN VAN F|01011998|Nam|01012022")

        self.assertTrue(result["is_valid"], result.get("error"))
        self.assertLess(result["confidence"], 0.9)
        self.assertIn("address_missing", result["warnings"])


class CccdScanApiPreprocessTest(unittest.TestCase):
    def test_preprocess_normalizes_full_width_digits_unicode_and_pipes(self):
        raw = "﻿０７９０９８０００００１|||NGUYỄN VĂN A\r\n"

        self.assertEqual(preprocess_raw(raw), "079098000001||NGUYỄN VĂN A")

    def test_calc_confidence_penalizes_conflicts(self):
        result = {
            "is_valid": False,
            "id_number": "079398000001",
            "name": "NGUYỄN VĂN D",
            "dob": "01/01/1998",
            "gender": "Nam",
            "address": {"province": "TP HCM", "district": "Quận 1", "ward": "Phường 1"},
            "issue_date": "01/01/2024",
            "conflicts": ["gender_mismatch"],
        }

        self.assertLess(_calc_confidence(result), 0.8)


if __name__ == "__main__":
    unittest.main()
