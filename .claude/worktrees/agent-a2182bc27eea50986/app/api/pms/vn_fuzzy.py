# app/api/pms/vn_fuzzy.py
"""
Vietnamese Address Fuzzy Matcher — Stage 3 Enhancement.
Dùng rapidfuzz để fuzzy-match tên tỉnh/huyện/xã,
tự động sửa alias thông dụng → tên chuẩn.
"""
from __future__ import annotations

import os
import re
from typing import Optional

# ─── RapidFuzz import (optional — graceful fallback nếu chưa có) ─────────────────

try:
    from rapidfuzz import fuzz, process
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False

# ─── Province canonical name map ─────────────────────────────────────────────────

PROVINCE_CANONICAL: dict[str, str] = {
    # TP.HCM variants → canonical
    "tp hcm":          "TP. Hồ Chí Minh",
    "tp.hcm":          "TP. Hồ Chí Minh",
    "tphcm":           "TP. Hồ Chí Minh",
    "ho chi minh":      "TP. Hồ Chí Minh",
    "hcm":             "TP. Hồ Chí Minh",
    "tp ho chi minh":   "TP. Hồ Chí Minh",
    "thanh pho ho chi minh": "TP. Hồ Chí Minh",
    "hochiminh":        "TP. Hồ Chí Minh",
    "ho chi minh city": "TP. Hồ Chí Minh",
    # Hà Nội
    "tp hn":           "TP. Hà Nội",
    "tp.hn":           "TP. Hà Nội",
    "hanoi":           "TP. Hà Nội",
    "hn":              "TP. Hà Nội",
    "tp ha noi":       "TP. Hà Nội",
    "tp hà nội":      "TP. Hà Nội",
    "thanh pho ha noi": "TP. Hà Nội",
    "hanoicity":       "TP. Hà Nội",
    # Đà Nẵng
    "tp đn":           "TP. Đà Nẵng",
    "tp.đn":           "TP. Đà Nẵng",
    "da nang":         "TP. Đà Nẵng",
    "đà nẵng":        "TP. Đà Nẵng",
    "danang":          "TP. Đà Nẵng",
    # Cần Thơ
    "can tho":          "TP. Cần Thơ",
    "cần thơ":         "TP. Cần Thơ",
    "cantho":           "TP. Cần Thơ",
    # Hải Phòng
    "hai phong":        "TP. Hải Phòng",
    "hải phòng":       "TP. Hải Phòng",
    "haiphong":         "TP. Hải Phòng",
    # Huế
    "thua thien hue":   "TT. Huế",
    "thừa thiên huế":  "TT. Huế",
    "hue":              "TT. Huế",
    "huế":              "TT. Huế",
    # Bình Dương
    "binh duong":       "Bình Dương",
    "bình dương":       "Bình Dương",
    # Đồng Nai
    "dong nai":         "Đồng Nai",
    "đồng nai":         "Đồng Nai",
    # Vũng Tàu
    "ba ria vung tau":  "Bà Rịa - Vũng Tàu",
    "bà rịa vũng tàu": "Bà Rịa - Vũng Tàu",
    "vung tau":         "Bà Rịa - Vũng Tàu",
    "vũng tàu":        "Bà Rịa - Vũng Tàu",
    # Hưng Yên
    "hung yen":         "Hưng Yên",
    "hưng yên":        "Hưng Yên",
    # Hải Dương
    "hai duong":        "Hải Dương",
    "hải dương":       "Hải Dương",
    # Nam Định
    "nam dinh":         "Nam Định",
    "nam định":         "Nam Định",
    # Thái Bình
    "thai binh":       "Thái Bình",
    "thái bình":       "Thái Bình",
    # Nghệ An
    "nghe an":          "Nghệ An",
    "nghệ an":         "Nghệ An",
    # Hà Tĩnh
    "ha tinh":          "Hà Tĩnh",
    "hà tĩnh":         "Hà Tĩnh",
    # Quảng Ninh
    "quang ninh":       "Quảng Ninh",
    "quảng ninh":       "Quảng Ninh",
    # Thanh Hóa
    "thanh hoa":        "Thanh Hóa",
    "thanh hóa":        "Thanh Hóa",
    # Ninh Bình
    "ninh binh":        "Ninh Bình",
    "ninh bình":        "Ninh Bình",
    # Hòa Bình
    "hoa binh":         "Hòa Bình",
    "hòa bình":        "Hòa Bình",
    # Sơn La
    "son la":           "Sơn La",
    "sơn la":           "Sơn La",
    # Lào Cai
    "lao cai":          "Lào Cai",
    "lào cai":          "Lào Cai",
    # Yên Bái
    "yen bai":          "Yên Bái",
    "yên bái":          "Yên Bái",
    # Tuyên Quang
    "tuyen quang":      "Tuyên Quang",
    "tuyên quang":      "Tuyên Quang",
    # Lạng Sơn
    "lang son":         "Lạng Sơn",
    "lạng sơn":         "Lạng Sơn",
    # Cao Bằng
    "cao bang":         "Cao Bằng",
    "cao bằng":         "Cao Bằng",
    # Bắc Kạn
    "bac kan":          "Bắc Kạn",
    "bắc kạn":          "Bắc Kạn",
    # Tỉnh Bắc Giang
    "bac giang":        "Bắc Giang",
    "bắc giang":        "Bắc Giang",
    # Phú Thọ
    "phu tho":          "Phú Thọ",
    "phú thọ":          "Phú Thọ",
    # Vĩnh Phúc
    "vinh phuc":        "Vĩnh Phúc",
    "vĩnh phúc":        "Vĩnh Phúc",
    # Bắc Ninh
    "bac ninh":         "Bắc Ninh",
    "bắc ninh":         "Bắc Ninh",
    # Hưng Yên (duplicate check)
    "hungyen":          "Hưng Yên",
}

# ─── Normalize input key ────────────────────────────────────────────────────────

def _norm_key(s: str) -> str:
    """Chuẩn hóa string thành key để lookup."""
    return s.lower().strip().replace(".", "").replace("  ", " ").replace(" ", "")


def _strip_prefix(s: str) -> str:
    """Xóa prefix thông dụng: Tỉnh, TP., Thành phố, Quận, Huyện..."""
    s = s.strip()
    for p in ["tỉnh ", "thành phố ", "tp ", "tp.", "quận ", "huyện ",
              "thị xã ", "thị trấn ", "phường ", "xã "]:
        ls = s.lower()
        if ls.startswith(p):
            return s[len(p):].strip()
    return s


# ─── Canonicalize province name ───────────────────────────────────────────────

def canonicalize_province(raw: str) -> tuple[str, str]:
    """
    Chuẩn hóa tên tỉnh/Thành phố.
    Trả về (canonical_name, confidence_level)
      confidence: 'exact' | 'alias' | 'fuzzy' | 'none'
    """
    if not raw:
        return "", "none"

    # 1. Lookup bảng alias
    key = _norm_key(raw)
    if key in PROVINCE_CANONICAL:
        return PROVINCE_CANONICAL[key], "alias"

    # 2. Fuzzy match bằng rapidfuzz (nếu có)
    if _HAS_RAPIDFUZZ:
        canonicals = list(PROVINCE_CANONICAL.values())
        # unique
        seen = set()
        uniq = []
        for c in canonicals:
            if c not in seen:
                seen.add(c)
                uniq.append(c)

        result = process.extractOne(
            _strip_prefix(raw),
            uniq,
            scorer=fuzz.ratio
        )
        if result and result[1] >= 80:
            return result[0], "fuzzy"

    # 3. Strip prefix thuần
    stripped = _strip_prefix(raw)
    if stripped:
        key2 = _norm_key(stripped)
        if key2 in PROVINCE_CANONICAL:
            return PROVINCE_CANONICAL[key2], "alias"

    return raw, "none"


# ─── Demo / test ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        "TP HCM", "HCM", "tp.hcm", "ho chi minh",
        "TP HN", "Ha Noi", "tp ha noi",
        "Da Nang", "Đà Nẵng", "TP ĐN",
        "Binh Duong", "Hải Phòng",
        "TP. Hồ Chí Minh", "Tỉnh Bình Dương",
    ]
    for t in tests:
        canon, conf = canonicalize_province(t)
        print(f"  {t!r:25s} → {canon!r:25s} [{conf}]")
