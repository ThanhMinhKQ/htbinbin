# app/api/pms/identity_parser.py
"""
Identity Parser — Standalone CCCD/CMND/Căn Cước QR parsing engine.
Không phụ thuộc framework, tái sử dụng được ở bất kỳ đâu.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# ───────────────────────────── Paths ───────────────────────────────────────────

_DATA_DIR = Path(__file__).parent.parent.parent / "static" / "data"

# ───────────────────────────── Card type constants ─────────────────────────────

CCCD_CU        = "CCCD_CU"       # CCCD thường (pre-2024, 4 cấp địa chỉ)
CAN_CUOC_MOI  = "CAN_CUOC_MOI" # Căn cước công dân mới (2024+, 3 cấp)
CMND_TYPE     = "CMND"          # CMND 9 số (cũ)

# ───────────────────────────── Province aliases ──────────────────────────────────

_PROVINCE_ALIASES: dict[str, str] = {
    # canonical keys align with vn_new_wards.json
    "tp hcm": "TP HCM",
    "tp.hcm": "TP HCM",
    "tphcm": "TP HCM",
    "tp hồ chí minh": "TP HCM",
    "tp. hồ chí minh": "TP HCM",
    "ho chi minh": "TP HCM",
    "hồ chí minh": "TP HCM",
    "thành phố hồ chí minh": "TP HCM",
    "thanh pho ho chi minh": "TP HCM",
    "hcm": "TP HCM",
    "tp": "TP HCM",
    "tp hn": "Hà Nội",
    "tp.hn": "Hà Nội",
    "hanoi": "Hà Nội",
    "hn": "Hà Nội",
    "tp hà nội": "Hà Nội",
    "tp. hà nội": "Hà Nội",
    "thành phố hà nội": "Hà Nội",
    "ha noi": "Hà Nội",
    "tp đn": "Đà Nẵng",
    "tp.đn": "Đà Nẵng",
    "tp đà nẵng": "Đà Nẵng",
    "da nang": "Đà Nẵng",
    "đà nẵng": "Đà Nẵng",
    "thành phố đà nẵng": "Đà Nẵng",
    "can tho": "Cần Thơ",
    "cần thơ": "Cần Thơ",
    "cantho": "Cần Thơ",
    "tp cần thơ": "Cần Thơ",
    "tp hải phòng": "Hải Phòng",
    "hai phong": "Hải Phòng",
    "hải phòng": "Hải Phòng",
    "an giang": "An Giang",
    "bà rịa - vũng tàu": "Bà Rịa - Vũng Tàu",
    "bà rịa": "Bà Rịa - Vũng Tàu",
    "vũng tàu": "Bà Rịa - Vũng Tàu",
    "bình dương": "Bình Dương",
    "bình phước": "Bình Phước",
    "bình thuận": "Bình Thuận",
    "bình định": "Bình Định",
    "bạc liêu": "Bạc Liêu",
    "bắc giang": "Bắc Giang",
    "bắc kạn": "Bắc Kạn",
    "bắc ninh": "Bắc Ninh",
    "bến tre": "Bến Tre",
    "cao bằng": "Cao Bằng",
    "cà mau": "Cà Mau",
    "gia lai": "Gia Lai",
    "huế": "Huế",
    "hà giang": "Hà Giang",
    "hà nam": "Hà Nam",
    "hà nội": "Hà Nội",
    "hà tĩnh": "Hà Tĩnh",
    "hòa bình": "Hòa Bình",
    "hưng yên": "Hưng Yên",
    "hải dương": "Hải Dương",
    "hậu giang": "Hậu Giang",
    "khánh hòa": "Khánh Hòa",
    "kiên giang": "Kiên Giang",
    "kon tum": "Kon Tum",
    "lai châu": "Lai Châu",
    "long an": "Long An",
    "lào cai": "Lào Cai",
    "lâm đồng": "Lâm Đồng",
    "lạng sơn": "Lạng Sơn",
    "nam định": "Nam Định",
    "nghệ an": "Nghệ An",
    "ninh bình": "Ninh Bình",
    "ninh thuận": "Ninh Thuận",
    "phú thọ": "Phú Thọ",
    "phú yên": "Phú Yên",
    "quảng bình": "Quảng Bình",
    "quảng nam": "Quảng Nam",
    "quảng ngãi": "Quảng Ngãi",
    "quảng ninh": "Quảng Ninh",
    "quảng trị": "Quảng Trị",
    "sóc trăng": "Sóc Trăng",
    "sơn la": "Sơn La",
    "tây ninh": "Tây Ninh",
    "thanh hóa": "Thanh Hóa",
    "thái bình": "Thái Bình",
    "thái nguyên": "Thái Nguyên",
    "tiền giang": "Tiền Giang",
    "trà vinh": "Trà Vinh",
    "tuyên quang": "Tuyên Quang",
    "vĩnh long": "Vĩnh Long",
    "vĩnh phúc": "Vĩnh Phúc",
    "yên bái": "Yên Bái",
    "điện biên": "Điện Biên",
    "đắk lắk": "Đắk Lắk",
    "đắk nông": "Đắk Nông",
    "đồng nai": "Đồng Nai",
    "đồng tháp": "Đồng Tháp",
}

_EXTRA_PROVINCE_NAMES_FOR_SPLIT: frozenset[str] = frozenset({
    "TP. Hồ Chí Minh", "TP. Hà Nội", "TP. Đà Nẵng", "TP. Cần Thơ", "TP. Hải Phòng", "TT. Huế",
    "Bình Dương", "Bình Phước", "Bạc Liêu", "Bến Tre", "Đắk Nông", "Hậu Giang", "Kiên Giang",
    "Long An", "Ninh Thuận", "Bình Thuận", "Phú Yên", "Kon Tum", "Quảng Bình", "Quảng Nam",
    "Thừa Thiên Huế", "Trà Vinh", "Sóc Trăng", "Tiền Giang", "Vĩnh Phúc", "Bắc Giang", "Bắc Kạn",
    "Hà Giang", "Hà Nam", "Hải Dương", "Hòa Bình", "Nam Định", "Thái Bình", "Yên Bái",
})

# ───────────────────────────── Data caches ──────────────────────────────────────

_NEW_WARDS_CACHE: dict[str, list[str]] | None = None
_ALIAS_REVERSE_MAP: dict[str, str] | None = None
_PROVINCE_NAMES_SPLIT_CACHE: list[str] | None = None
_PROVINCE_ALIASES_COMPILED: bool = False
_PROVINCE_PATTERNS: list[tuple[re.Pattern, str]] = []
_PROVINCE_KEY_CACHE: dict[str, str] | None = None
_PROVINCE_WARD_SET_CACHE: dict[str, set[str]] | None = None

_PROVINCE_DISPLAY_NAMES: dict[str, str] = {
    "TP HCM": "Thành phố Hồ Chí Minh",
    "Hà Nội": "Hà Nội",
    "Đà Nẵng": "Đà Nẵng",
    "Cần Thơ": "Cần Thơ",
    "Hải Phòng": "Hải Phòng",
}

# Old address data (caches — load once)
_OLD_PROVINCES_CACHE: list[dict] | None = None
_OLD_DISTRICTS_CACHE: dict[str, list[dict]] | None = None


def _load_data(file_name: str) -> dict | list:
    """Load a JSON data file relative to the parser. Returns empty container on failure."""
    try:
        path = _DATA_DIR / file_name
        if path.is_file():
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    return {} if file_name.endswith(".json") else []


def _load_new_wards_cache() -> dict[str, list[str]]:
    """Load new wards data for ward existence check. Cached after first call."""
    global _NEW_WARDS_CACHE
    if _NEW_WARDS_CACHE is not None:
        return _NEW_WARDS_CACHE
    _NEW_WARDS_CACHE = _load_data("vn_new_wards.json")
    return _NEW_WARDS_CACHE or {}


def _load_old_address_cache() -> tuple[list[dict], dict[str, list[dict]]]:
    """
    Load old provinces + districts into RAM. Loaded once on first use.
    Returns: (provinces_list, districts_dict) where districts_dict maps province_code -> list[district]
    """
    global _OLD_PROVINCES_CACHE, _OLD_DISTRICTS_CACHE
    if _OLD_PROVINCES_CACHE is not None:
        return _OLD_PROVINCES_CACHE, _OLD_DISTRICTS_CACHE

    _OLD_PROVINCES_CACHE = _load_data("vn_old_provinces.json")
    raw_districts: dict = _load_data("vn_old_districts.json")

    # Rebuild: flatten into province_code → list[district]
    _OLD_DISTRICTS_CACHE = {}
    for prov in _OLD_PROVINCES_CACHE:
        code = str(prov.get("code", ""))
        _OLD_DISTRICTS_CACHE[code] = raw_districts.get(code, [])

    return _OLD_PROVINCES_CACHE, _OLD_DISTRICTS_CACHE


def _get_alias_reverse_map() -> dict[str, str]:
    """Build reverse map: normalized canonical value -> canonical province key in wards data."""
    global _ALIAS_REVERSE_MAP
    if _ALIAS_REVERSE_MAP is not None:
        return _ALIAS_REVERSE_MAP

    wards_data = _load_new_wards_cache()
    canon_by_norm = {
        _normalize_for_compare(k): k for k in wards_data.keys()
    }

    _ALIAS_REVERSE_MAP = {}
    for alias_key, alias_val in _PROVINCE_ALIASES.items():
        alias_norm = _normalize_for_compare(alias_key)
        val_norm = _normalize_for_compare(alias_val)
        canonical = canon_by_norm.get(val_norm, alias_val)
        _ALIAS_REVERSE_MAP[alias_norm] = canonical
        _ALIAS_REVERSE_MAP[val_norm] = canonical

    for key in wards_data.keys():
        key_norm = _normalize_for_compare(key)
        _ALIAS_REVERSE_MAP[key_norm] = key

    return _ALIAS_REVERSE_MAP


# ───────────────────────────── Normalization helpers ─────────────────────────────

def _normalize_for_compare(s: str) -> str:
    """Normalize string for comparison (remove diacritics, lowercase, strip dots/spaces)."""
    if not s:
        return ""
    normalized = unicodedata.normalize("NFD", s)
    return normalized.encode("ascii", "ignore").decode("utf-8").lower().replace(".", "").replace(" ", "").strip()


def normalize_qr_raw(raw: str) -> str:
    """Normalize scanner QR payload before field extraction."""
    if not raw:
        return ""
    s = unicodedata.normalize("NFKC", raw).replace("﻿", "")
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)
    s = s.replace("\r\n", "").replace("\r", "").replace("\n", "")
    s = re.sub(r"[｜¦]", "|", s)
    s = re.sub(r"\|{3,}", "||", s)
    return unicodedata.normalize("NFC", s).strip()


def split_qr_fields(raw: str) -> list[str]:
    return [p.strip() for p in normalize_qr_raw(raw).split("|")]


def _normalize_gender(value: str) -> str:
    norm = _normalize_for_compare(value)
    if norm in {"nam", "male", "m"}:
        return "Nam"
    if norm in {"nu", "n", "female", "f"}:
        return "Nữ"
    return ""


def _birth_gender_from_cccd(id_number: str) -> dict:
    if not re.fullmatch(r"\d{12}", id_number or ""):
        return {}
    code = int(id_number[3])
    year = int(id_number[4:6])
    century = 1900 + (code // 2) * 100
    return {
        "gender": "Nam" if code % 2 == 0 else "Nữ",
        "birth_year": century + year,
    }


def _is_address_like_field(value: str) -> bool:
    return bool(re.search(r"[,\d]|TP\.|Tỉnh|Thành phố|Quận|Huyện|Phường|Xã|Đường|Phố|Tổ|KP", value, re.IGNORECASE))


def _is_name_like_field(value: str) -> bool:
    if not value or _is_address_like_field(value):
        return False
    words = [w for w in re.split(r"\s+", value.strip()) if w]
    if len(words) < 2 or len(words) > 6:
        return False
    return all(re.fullmatch(r"[A-Za-zÀ-ỹĐđ'’-]+", w) for w in words)


def _address_mode_for_card(card_type: str, address_raw: str) -> str:
    if card_type == CMND_TYPE:
        return "old"
    if card_type == CAN_CUOC_MOI and not _hints_old_admin_levels(address_raw):
        return "new"
    return "old"


def _normalize_district_name(district_name: str) -> str:
    """Remove common district-level prefixes for comparison."""
    if not district_name:
        return district_name
    return re.sub(r"^(quận|huyện|thành phố|thị xã|thị trấn)\s*", "", district_name, flags=re.IGNORECASE).strip()


def _normalize_ward_number(ward_name: str) -> str:
    """Remove leading zeros from ward numbers: 'Phường 01' → 'Phường 1'."""
    if not ward_name:
        return ward_name
    return re.sub(
        r"(phường|xã|thị trấn)\s*0+(\d+)",
        lambda m: m.group(1) + " " + str(int(m.group(2))),
        ward_name,
        flags=re.IGNORECASE,
    )


def _compile_aliases() -> None:
    global _PROVINCE_ALIASES_COMPILED, _PROVINCE_PATTERNS
    if _PROVINCE_ALIASES_COMPILED:
        return
    keywords = [
        r"TP\.\s*H[oô]?\s*Ch[ií]\s*Minh",
        r"TP\.\s*H[àảãạ]\s*N[oộỏõạ]",
        r"T[ỉi]nh\s+\w+",
        r"Th[àảãạ]nh\s+ph[ốo]\s+\w+",
    ]
    for kw in keywords:
        _PROVINCE_PATTERNS.append((re.compile(kw, re.IGNORECASE), kw))
    _PROVINCE_ALIASES_COMPILED = True


# ───────────────────────────── Province lookup ───────────────────────────────────

def _normalize_ward_for_lookup(ward_name: str) -> str:
    if not ward_name:
        return ""
    ward_clean = _normalize_ward_number(ward_name)
    ward_clean = re.sub(r"^(phường|xã|thị trấn)\s*", "", ward_clean, flags=re.IGNORECASE).strip()
    return _normalize_for_compare(ward_clean)



def _resolve_province_data_key(province_name: str) -> str:
    global _PROVINCE_KEY_CACHE
    if not province_name:
        return ""
    if _PROVINCE_KEY_CACHE is None:
        _PROVINCE_KEY_CACHE = {}

    prov_norm = _normalize_for_compare(province_name)
    cached = _PROVINCE_KEY_CACHE.get(prov_norm)
    if cached is not None:
        return cached

    wards_data = _load_new_wards_cache()
    alias_map = _get_alias_reverse_map()

    direct = alias_map.get(prov_norm, "")
    if direct:
        _PROVINCE_KEY_CACHE[prov_norm] = direct
        return direct

    prov_stripped = prov_norm
    for pfx in ("thanhpho", "tp", "tinh"):
        if prov_stripped.startswith(pfx):
            prov_stripped = prov_stripped[len(pfx):]
    for key in wards_data.keys():
        key_norm = _normalize_for_compare(key)
        key_stripped = key_norm
        for pfx in ("thanhpho", "tp", "tinh"):
            if key_stripped.startswith(pfx):
                key_stripped = key_stripped[len(pfx):]
        if prov_stripped == key_stripped:
            _PROVINCE_KEY_CACHE[prov_norm] = key
            return key

    _PROVINCE_KEY_CACHE[prov_norm] = ""
    return ""



def _get_province_ward_set(province_name: str) -> set[str]:
    global _PROVINCE_WARD_SET_CACHE
    if _PROVINCE_WARD_SET_CACHE is None:
        _PROVINCE_WARD_SET_CACHE = {}

    province_key = _resolve_province_data_key(province_name)
    if not province_key:
        return set()

    cached = _PROVINCE_WARD_SET_CACHE.get(province_key)
    if cached is not None:
        return cached

    wards = _load_new_wards_cache().get(province_key, [])
    ward_set = {_normalize_ward_for_lookup(w) for w in wards if w}
    _PROVINCE_WARD_SET_CACHE[province_key] = ward_set
    return ward_set



def _is_ward_in_province(ward_name: str, province_name: str) -> bool:
    """
    Kiểm tra xem ward_name có tồn tại như Phường/Xã trong province không.
    Wards data keys: "TP HCM", "Hà Nội", "Đà Nẵng", etc.
    """
    if not ward_name or not province_name:
        return False
    ward_norm = _normalize_ward_for_lookup(ward_name)
    if not ward_norm:
        return False
    return ward_norm in _get_province_ward_set(province_name)


def _province_display_name(province_key_or_name: str) -> str:
    if not province_key_or_name:
        return ""
    canonical = _resolve_province_data_key(province_key_or_name) or province_key_or_name
    return _PROVINCE_DISPLAY_NAMES.get(canonical, canonical)


def _is_district_in_province(district_name: str, province_name: str) -> bool:
    """
    Kiểm tra xem district_name có tồn tại như Quận/Huyện/Thành phố trong province không.
    Uses in-memory cache — no disk I/O per call.
    """
    if not district_name or not province_name:
        return False

    provinces, districts_by_code = _load_old_address_cache()
    prov_norm = _normalize_for_compare(province_name)

    province_code: str | None = None
    for p in provinces:
        p_name_norm = _normalize_for_compare(p["name"])
        if p_name_norm == prov_norm or prov_norm in p_name_norm or p_name_norm in prov_norm:
            province_code = str(p["code"])
            break

    if not province_code:
        return False

    districts = districts_by_code.get(province_code, [])
    dist_norm = _normalize_for_compare(_normalize_district_name(district_name))

    for d in districts:
        d_name = d.get("name", "")
        d_stripped = re.sub(
            r"^(quận|huyện|thành phố|thị xã|thị trấn)\s*", "", d_name, flags=re.IGNORECASE
        ).strip()
        d_norm = _normalize_for_compare(d_stripped)
        if d_norm == dist_norm or dist_norm in d_norm or d_norm in dist_norm:
            return True
    return False


# ───────────────────────────── Date helpers ────────────────────────────────────

def fmt_dmy(raw: str) -> Optional[str]:
    """'ddMMyyyy' → 'dd/MM/yyyy'. None if invalid."""
    if not raw or len(raw) != 8 or not raw.isdigit():
        return None
    try:
        d, m, y = int(raw[:2]), int(raw[2:4]), int(raw[4:8])
        return date(y, m, d).strftime("%d/%m/%Y")
    except ValueError:
        return None


def _add_years_same_day(d: date, years: int) -> date:
    """Cộng năm, giữ ngày/tháng (xử lý 29/2)."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(month=2, day=28, year=d.year + years)


def calc_expiry(dob_fmt: str) -> str:
    """
    Tính ngày hết hạn CCCD (mốc đổi thẻ theo tuổi, cùng ngày/tháng sinh):
      < 25 tuổi  → hết hạn đủ 25 tuổi
      25–39      → đủ 40 tuổi
      40–59      → đủ 60 tuổi
      ≥ 60       → Không thời hạn
    dob_fmt: 'dd/MM/yyyy'
    """
    try:
        dob = datetime.strptime(dob_fmt, "%d/%m/%Y").date()
    except ValueError:
        return "Không xác định"

    today = date.today()
    age = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        age -= 1

    if age < 25:
        return _add_years_same_day(dob, 25).strftime("%d/%m/%Y")
    if age < 40:
        return _add_years_same_day(dob, 40).strftime("%d/%m/%Y")
    if age < 60:
        return _add_years_same_day(dob, 60).strftime("%d/%m/%Y")
    return "Không thời hạn"


def calc_age(dob_fmt: str) -> Optional[int]:
    """Tính tuổi từ 'dd/MM/yyyy'. None if invalid."""
    try:
        dob = datetime.strptime(dob_fmt, "%d/%m/%Y").date()
        today = date.today()
        age = today.year - dob.year
        if (today.month, today.day) < (dob.month, dob.day):
            age -= 1
        return age
    except ValueError:
        return None


def get_expiry_status(expiry: str) -> str:
    """Trả badge expiry: 'valid' | 'expiring' | 'expired' | 'permanent' | 'unknown'."""
    if not expiry or expiry in ("Không xác định",):
        return "unknown"
    if expiry == "Không thời hạn":
        return "permanent"
    try:
        diff = (datetime.strptime(expiry, "%d/%m/%Y").date() - date.today()).days
        if diff < 0:
            return "expired"
        if diff <= 180:
            return "expiring"
        return "valid"
    except ValueError:
        return "unknown"


# ─────────────────────────── Card type detection ────────────────────────────────

_KNOWN_DISTRICTS: frozenset[str] = frozenset({
    # TP.HCM
    "tân bình", "tân phú", "bình tân", "bình thạnh", "gò vấp", "phú nhuận",
    "thủ đức", "hóc môn", "củ chi", "cần giờ", "bình chánh",
    # Hà Nội
    "ba đình", "hoàn kiếm", "hai bà trưng", "đống đa", "tây hồ",
    "thanh xuân", "hà đông", "hoàng mai", "long biên", "cầu giấy",
    "nam từ liêm", "bắc từ liêm", "đông anh", "gia lâm",
    "ba vì", "chương mỹ", "đan phượng", "hoài đức", "mê linh",
    "phú xuyên", "quốc oai", "sóc sơn", "thạch thất", "thường tín",
    "ứng hòa", "thanh liệt", "thanh trì", "sơn tây", "phúc thọ",
    # Đà Nẵng
    "hải châu", "thanh khê", "sơn trà", "ngũ hành sơn", "liên chiểu",
    "cẩm lệ", "hoà vang",
    # Others
    "tân hưng", "bến lức", "nhà bè", "càng long",
    "vĩnh long", "bến tre", "trà vinh",
})


def _has_empty_part(address_raw: str) -> bool:
    """True nếu địa chỉ có phần trống sau khi split (VD: 'A, B, , C')."""
    if not address_raw:
        return False
    parts = [p.strip() for p in address_raw.strip().split(",")]
    return any(p == "" for p in parts)


def _hints_old_admin_levels(address_raw: str) -> bool:
    """
    True nếu địa chỉ có cấp Quận/Huyện/Thị xã/Thị trấn → CCCD_CU (4 cấp).
    Patterns:
      1. Prefix rõ ràng sau dấu phẩy (', Quận ', ', Huyện ')
      2. ≥ 3 dấu phẩy và phần áp chót không phải Phường/Xã mới trong tỉnh
      3. Tên quận/huyện phổ biến ở vị trí 3+ (sau detail + ward)
      4. 2 phần tử cuối giống nhau (district == province) nhưng không phải tỉnh/TP lặp
    """
    if not address_raw or not address_raw.strip():
        return False

    addr = address_raw.strip()
    raw_parts = [p.strip() for p in addr.split(",")]
    parts = [p for p in raw_parts if p]

    if len(parts) >= 3 and _is_ward_in_province(parts[-2], parts[-1]):
        return False

    if len(parts) >= 4:
        last_key = _resolve_province_data_key(parts[-1])
        second_last_key = _resolve_province_data_key(parts[-2])
        if last_key and second_last_key == last_key:
            return False

    # Pattern 1: prefix rõ ràng
    if re.search(r",\s*(quận|huyện|thị xã|thị trấn|tx\.)\s", addr, re.IGNORECASE):
        return True

    # Pattern 2: ≥ 3 dấu phẩy → 4 cấp
    if addr.count(",") >= 3:
        return True

    # Pattern 3: tên quận/huyện phổ biến ở vị trí 3+
    parts = [p.strip().lower() for p in raw_parts]
    for i, part in enumerate(parts):
        if re.match(r"^(số|tổ|kp|đường|phố)\s*\d", part):
            continue
        if re.match(r"^(phường|xã)\s*\d", part):
            continue
        for district in _KNOWN_DISTRICTS:
            if district in part and i >= 2:
                return True

    # Pattern 4: district == province
    if len(parts) >= 3:
        last = parts[-1]
        second_last = re.sub(r"^(tỉnh |thành phố |tp\.? )", "", parts[-2], flags=re.IGNORECASE).strip()
        if second_last == last or second_last.replace(" ", "") == last.replace(" ", ""):
            return True

    return False


def _district_equals_province(address_raw: str) -> bool:
    """True nếu 2 phần tử cuối trùng nhau (district == province)."""
    if not address_raw:
        return False
    parts = [p.strip() for p in address_raw.strip().split(",") if p.strip()]
    if len(parts) < 3:
        return False
    a = parts[-1].lower().replace(".", "").replace(" ", "")
    b = re.sub(r"^(tỉnh |thành phố |tp\.? )", "", parts[-2], flags=re.IGNORECASE).strip().lower().replace(".", "").replace(" ", "")
    return a == b


def _detect_can_cuoc_moi_special(address_raw: str) -> bool:
    """
    Phát hiện CCCD mới bị ghi 4 phần tử (cần parse 3 cấp).
    Trả True nếu district_candidate thực chất là ward.
    """
    if not address_raw:
        return False
    parts = [p.strip() for p in address_raw.strip().split(",") if p.strip()]
    if len(parts) < 4:
        return False

    parts_rev = list(reversed(parts))
    prov = parts_rev[0] if len(parts_rev) >= 1 else ""
    dcand = parts_rev[1] if len(parts_rev) >= 2 else ""
    wcand = parts_rev[2] if len(parts_rev) >= 3 else ""

    dc_lower = dcand.lower()

    # District == Province
    if dc_lower.replace("-", "") == prov.lower().replace("-", ""):
        return True

    # district_candidate bắt đầu "Phường "/"Xã " → bị xếp nhầm → CCCD cũ
    if dc_lower.startswith(("phường ", "xã ")):
        return False

    # district_candidate tồn tại như Phường/Xã trong tỉnh → CCCD mới
    is_ward = _is_ward_in_province(dcand, prov)
    is_district = _is_district_in_province(dcand, prov)

    if is_ward and not is_district:
        return True
    if is_ward and is_district:
        return False  # vừa ward vừa district → CCCD cũ

    # district_candidate bắt đầu "Thành phố" → TP cấp huyện → CCCD cũ
    if dc_lower.startswith("thành phố"):
        return False

    return False


def detect_card_type(
    parts: list[str],
    date_candidates: list[tuple[str, str]],
    address_raw: str = "",
    old_id: str = "",
    id_number: str = "",
) -> str:
    """
    Phát hiện loại thẻ / format QR.
    Ưu tiên tín hiệu mạnh: CMND-only, năm cấp >= 2024 và cấu trúc địa chỉ thực tế.
    """
    if old_id and not id_number:
        return CMND_TYPE

    if len(date_candidates) >= 2:
        issue_raw = date_candidates[-1][0]
        try:
            if int(issue_raw[4:8]) >= 2024:
                return CAN_CUOC_MOI
        except ValueError:
            pass

    if _detect_can_cuoc_moi_special(address_raw):
        return CAN_CUOC_MOI

    addr = address_raw.strip() if address_raw else ""
    if addr and _has_empty_part(addr):
        filtered = [p.strip() for p in addr.split(",") if p.strip()]
        if len(filtered) == 3:
            return CAN_CUOC_MOI

    if _hints_old_admin_levels(address_raw):
        return CCCD_CU

    if len(parts) > 1 and parts[1].strip() == "":
        return CAN_CUOC_MOI

    empty_count = sum(1 for p in parts if p.strip() == "")
    non_empty = [p for p in parts if p.strip()]
    if empty_count >= 2 or len(non_empty) > 7:
        return CAN_CUOC_MOI

    return CCCD_CU


# ─────────────────────────── Address parser ────────────────────────────────────

def normalize_address_str(s: str) -> str:
    """Bước 1: chuẩn hóa address string."""
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\bTP\.\s*", "TP. ", s)
    for old in ("Tỉnh ", "tỉnh "):
        s = s.replace(old, "")
    return s.strip()


def _province_names_longest_first() -> list[str]:
    global _PROVINCE_NAMES_SPLIT_CACHE
    if _PROVINCE_NAMES_SPLIT_CACHE is not None:
        return _PROVINCE_NAMES_SPLIT_CACHE
    names: set[str] = set(_EXTRA_PROVINCE_NAMES_FOR_SPLIT)
    names.update(_PROVINCE_ALIASES.values())
    jpath = _DATA_DIR / "vn_new_wards.json"
    if jpath.is_file():
        try:
            with open(jpath, encoding="utf-8") as fp:
                names.update(json.load(fp).keys())
        except (OSError, json.JSONDecodeError):
            pass
    _PROVINCE_NAMES_SPLIT_CACHE = sorted(names, key=lambda x: (-len(x), x))
    return _PROVINCE_NAMES_SPLIT_CACHE


def _norm_addr_token(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).lower()


def _split_segment_if_province_fused(seg: str) -> list[str]:
    seg = seg.strip()
    if not seg:
        return []
    for prov in _province_names_longest_first():
        if len(seg) <= len(prov):
            continue
        pat = re.compile("^" + re.escape(prov) + r"\s+(.+)$", re.IGNORECASE)
        m = pat.match(seg)
        if m:
            rest = m.group(1).strip()
            if rest:
                return [prov, rest]
    return [seg]


def _dedupe_trailing_ward_province_repeat(parts: list[str]) -> list[str]:
    out = list(parts)
    while len(out) >= 4:
        n = len(out)
        if (_norm_addr_token(out[n - 1]) == _norm_addr_token(out[n - 3])
                and _norm_addr_token(out[n - 2]) == _norm_addr_token(out[n - 4])):
            out = out[:-2]
        else:
            break
    return out


def repair_qr_address(raw_address: str) -> str:
    if not raw_address or not raw_address.strip():
        return (raw_address or "").strip()
    addr = normalize_address_str(raw_address)
    segs = [p.strip() for p in addr.split(",") if p.strip()]
    expanded: list[str] = []
    for seg in segs:
        expanded.extend(_split_segment_if_province_fused(seg))
    expanded = _dedupe_trailing_ward_province_repeat(expanded)
    return ", ".join(expanded)


# ─── parse_address_vn helpers ─────────────────────────────────────────────────

def _parse_can_cuoc_moi_special(
    parts_rev: list[str],
) -> tuple[str, str, str]:
    """
    Parse CCCD mới bị ghi 4 phần tử (VD: 'Hà Nội, Hà Nội' hoặc 'Tân Hưng' là Phường).
    Returns: (detail, ward, district='') — district luôn trống cho CCCD mới.
    """
    ward = parts_rev[2] if len(parts_rev) >= 3 else ""
    detail_parts = parts_rev[3:] if len(parts_rev) >= 4 else []
    detail_parts.reverse()
    detail = ", ".join(detail_parts)
    return detail, ward, ""


def _parse_can_cuoc_moi_standard(parts_rev: list[str]) -> tuple[str, str, str]:
    """Parse CAN_CUOC_MOI chuẩn (3 cấp: province, ward, detail)."""
    ward = parts_rev[1] if len(parts_rev) >= 2 else ""
    detail_parts = parts_rev[2:] if len(parts_rev) >= 3 else []
    detail_parts.reverse()
    detail = ", ".join(detail_parts)
    return detail, ward, ""


def _parse_address_flexible(
    parts_rev: list[str], province: str, card_type: str
) -> tuple[str, str, str]:
    if len(parts_rev) <= 1:
        return "", "", ""

    three_level_ward = parts_rev[1] if len(parts_rev) >= 2 else ""
    if card_type == CAN_CUOC_MOI and _is_ward_in_province(three_level_ward, province):
        detail_parts = parts_rev[2:] if len(parts_rev) >= 3 else []
        detail_parts.reverse()
        return ", ".join(detail_parts), three_level_ward, ""

    if len(parts_rev) >= 3:
        four_level_district = parts_rev[1]
        four_level_ward = parts_rev[2]
        if _is_ward_in_province(four_level_ward, province):
            detail_parts = parts_rev[3:] if len(parts_rev) >= 4 else []
            detail_parts.reverse()
            return ", ".join(detail_parts), four_level_ward, four_level_district

    if card_type == CAN_CUOC_MOI:
        return _parse_can_cuoc_moi_standard(parts_rev)
    return _parse_cccd_cu(parts_rev, province)


def _parse_cccd_cu(
    parts_rev: list[str], province: str
) -> tuple[str, str, str]:
    """
    Parse CCCD_CU (4 cấp). Tự động disambiguate ward vs district bằng prefix và lookup.
    Returns: (detail, ward, district).
    """
    district_cand = parts_rev[1] if len(parts_rev) >= 2 else ""
    ward_cand = parts_rev[2] if len(parts_rev) >= 3 else ""

    dc_lower = district_cand.lower()
    wc_lower = ward_cand.lower()

    # Prefix-based disambiguation
    dc_has_prefix = dc_lower.startswith(("thành phố", "quận ", "huyện ", "thị xã "))
    wc_has_prefix = wc_lower.startswith(("thành phố", "quận ", "huyện ", "thị xã "))
    ward_is_phuong_xa = wc_lower.startswith(("phường ", "xã "))

    swap_needed = False
    if dc_has_prefix:
        swap_needed = False
    elif ward_is_phuong_xa:
        swap_needed = True
    elif wc_has_prefix:
        swap_needed = True
    else:
        # Không có prefix → dùng lookup
        ward_is_real = _is_ward_in_province(ward_cand, province)
        district_is_real = _is_ward_in_province(district_cand, province)
        if district_is_real and not ward_is_real:
            swap_needed = True

    if swap_needed:
        district, ward = ward_cand, district_cand
    else:
        district, ward = district_cand, ward_cand

    detail_parts = parts_rev[3:] if len(parts_rev) >= 4 else []
    detail_parts.reverse()
    detail = ", ".join(detail_parts)
    return detail, ward, district


def parse_address_vn(raw_address: str, card_type: str) -> dict:
    """
    Parse địa chỉ VN từ chuỗi QR.

    Returns: { detail, ward, district, province, province_raw, city }
    """
    if not raw_address:
        return {"detail": "", "ward": "", "district": "", "province": "",
                "province_raw": "", "city": ""}

    addr = repair_qr_address(raw_address)
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    parts.reverse()

    province_raw = parts[0] if len(parts) >= 1 else ""
    province_key = _resolve_province_data_key(province_raw)
    province_canonical = province_key or _PROVINCE_ALIASES.get(_normalize_for_compare(province_raw), province_raw)
    province = _province_display_name(province_canonical)

    detail, ward, district = _parse_address_flexible(parts, province, card_type)

    if card_type == CAN_CUOC_MOI and district and not _is_district_in_province(district, province):
        district = ""

    return {
        "detail": detail, "ward": ward, "district": district,
        "province": province, "province_raw": province_raw, "city": province,
    }


# ─────────────────────────── Main QR parser ────────────────────────────────────

def parse_qr(raw: str) -> dict:
    """
    Parse chuỗi QR CCCD / Căn cước / CMND.

    Returns structured data dict:
      {
        card_type, id_number, old_id, name, dob, gender,
        address: { raw, detail, ward, district, province },
        issue_date, expiry_date, age, is_valid, expiry_status, error, raw_cleaned
      }
    """
    _compile_aliases()

    cleaned = normalize_qr_raw(raw)
    for prefix in ("CĂN CƯỚC CÔNG DÂN:", "CCCD:", "CMND:", "CAN CUOC:", "CANCUOC:"):
        if cleaned.upper().startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break

    parts = [p.strip() for p in cleaned.split("|")]

    id_number: str = ""
    old_id: str = ""
    name: str = ""
    gender: str = ""
    address_raw: str = ""
    date_candidates: list[tuple[str, str]] = []
    warnings: list[str] = []
    conflicts: list[str] = []

    for p in parts:
        if not p:
            continue

        if re.fullmatch(r"\d{12}", p) and not id_number:
            id_number = p
        elif re.fullmatch(r"\d{9}", p) and not old_id:
            old_id = p
        elif re.fullmatch(r"\d{8}", p):
            fmt = fmt_dmy(p)
            if fmt:
                date_candidates.append((p, fmt))
        elif normalized_gender := _normalize_gender(p):
            gender = normalized_gender
        elif not name and _is_name_like_field(p):
            name = p.strip().upper()
        elif len(p) > len(address_raw) and _is_address_like_field(p):
            address_raw = p

    id_evidence = _birth_gender_from_cccd(id_number)
    if id_evidence:
        if gender and id_evidence.get("gender") and gender != id_evidence["gender"]:
            conflicts.append("gender_mismatch")
        if date_candidates and id_evidence.get("birth_year"):
            try:
                if int(date_candidates[0][0][4:8]) != id_evidence["birth_year"]:
                    conflicts.append("birth_year_mismatch")
            except ValueError:
                pass
        if not gender:
            gender = id_evidence.get("gender", "")

    card_type = detect_card_type(parts, date_candidates, address_raw, old_id=old_id, id_number=id_number)
    address_mode = _address_mode_for_card(card_type, address_raw)

    dob_fmt = date_candidates[0][1] if date_candidates else ""
    issue_date = date_candidates[-1][1] if len(date_candidates) > 1 else ""

    addr = parse_address_vn(address_raw, CAN_CUOC_MOI if address_mode == "new" else CCCD_CU)

    expiry_date = calc_expiry(dob_fmt) if dob_fmt else "Không xác định"
    age = calc_age(dob_fmt) if dob_fmt else None
    expiry_status = get_expiry_status(expiry_date)

    if not address_raw:
        warnings.append("address_missing")

    if not id_number and not old_id:
        is_valid = False
        error = "Không tìm thấy số CCCD/CMND trong chuỗi QR"
    elif not name:
        is_valid = False
        error = "Không tìm thấy tên trong chuỗi QR"
    elif not dob_fmt:
        is_valid = False
        error = "Không tìm thấy ngày sinh trong chuỗi QR"
    elif conflicts:
        is_valid = False
        error = "Dữ liệu QR mâu thuẫn: " + ", ".join(conflicts)
    else:
        is_valid = True
        error = ""

    confidence = 0.0
    if id_number or old_id: confidence += 0.30
    if name:                confidence += 0.25
    if dob_fmt:             confidence += 0.15
    if gender:              confidence += 0.10
    if addr.get("province"): confidence += 0.10
    if addr.get("district") or addr.get("ward"): confidence += 0.05
    if issue_date:          confidence += 0.05
    confidence -= 0.25 * len(conflicts)
    confidence -= 0.05 * len(warnings)
    confidence = round(max(0.0, min(confidence, 1.0)), 2)

    return {
        "card_type":     card_type,
        "address_mode":  address_mode,
        "id_number":     id_number,
        "old_id":        old_id,
        "name":          name,
        "dob":           dob_fmt,
        "gender":        gender,
        "address": {
            "raw":      address_raw,
            "detail":   addr["detail"],
            "ward":     addr["ward"],
            "district": addr["district"],
            "province": addr["province"],
        },
        "issue_date":    issue_date,
        "expiry_date":   expiry_date,
        "age":           age,
        "is_valid":      is_valid,
        "expiry_status": expiry_status,
        "confidence":    confidence,
        "warnings":      warnings,
        "conflicts":     conflicts,
        "error":         error,
        "raw_cleaned":   cleaned,
    }


# ─────────────────────────── Convenience aliases ────────────────────────────────

parse_cccd_qr  = parse_qr
parse_identity = parse_qr
parse_qr_cccd = parse_qr
