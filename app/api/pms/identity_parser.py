# app/api/pms/identity_parser.py
"""
Identity Parser — Standalone CCCD/CMND/Căn Cước QR parsing engine.
Không phụ thuộc framework, tái sử dụng được ở bất kỳ đâu.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# ───────────────────────────── Card type constants ─────────────────────────────

CCCD_CU        = "CCCD_CU"       # CCCD thường (pre-2024, 4 cấp địa chỉ)
CAN_CUOC_MOI  = "CAN_CUOC_MOI" # Căn cước công dân mới (2024+, 3 cấp)
CMND_TYPE     = "CMND"          # CMND 9 số (cũ)

# ───────────────────────────── Province aliases ──────────────────────────────────

_PROVINCE_ALIASES: dict[str, str] = {
    # TP.HCM variants
    "tp hcm":          "TP. Hồ Chí Minh",
    "tp.hcm":          "TP. Hồ Chí Minh",
    "tphcm":           "TP. Hồ Chí Minh",
    "ho chi minh":      "TP. Hồ Chí Minh",
    "hcm":             "TP. Hồ Chí Minh",
    "tp. hồ chí minh": "TP. Hồ Chí Minh",
    # TP.HN variants
    "tp hn":           "TP. Hà Nội",
    "tp.hn":           "TP. Hà Nội",
    "hanoi":           "TP. Hà Nội",
    "hn":              "TP. Hà Nội",
    "tp. hà nội":      "TP. Hà Nội",
    # Đà Nẵng
    "tp đn":           "TP. Đà Nẵng",
    "tp.đn":           "TP. Đà Nẵng",
    "da nang":         "TP. Đà Nẵng",
    "đà nẵng":         "TP. Đà Nẵng",
    # Cần Thơ
    "can tho":         "TP. Cần Thơ",
    "cần thơ":         "TP. Cần Thơ",
    "cantho":          "TP. Cần Thơ",
    # Hải Phòng
    "hai phong":       "TP. Hải Phòng",
    "hải phòng":       "TP. Hải Phòng",
    # Other major TPs
    "tp cần thơ":      "TP. Cần Thơ",
    "tp đà nẵng":      "TP. Đà Nẵng",
    "tp hải phòng":    "TP. Hải Phòng",
    "tp hà nội":       "TP. Hà Nội",
}

_EXTRA_PROVINCE_NAMES_FOR_SPLIT: frozenset[str] = frozenset({
    "TP. Hồ Chí Minh", "TP. Hà Nội", "TP. Đà Nẵng", "TP. Cần Thơ", "TP. Hải Phòng", "TT. Huế",
    "Bình Dương", "Bình Phước", "Bạc Liêu", "Bến Tre", "Đắk Nông", "Hậu Giang", "Kiên Giang",
    "Long An", "Ninh Thuận", "Bình Thuận", "Phú Yên", "Kon Tum", "Quảng Bình", "Quảng Nam",
    "Thừa Thiên Huế", "Trà Vinh", "Sóc Trăng", "Tiền Giang", "Vĩnh Phúc", "Bắc Giang", "Bắc Kạn",
    "Hà Giang", "Hà Nam", "Hải Dương", "Hòa Bình", "Nam Định", "Thái Bình", "Yên Bái",
})

_PROVINCE_NAMES_SPLIT_CACHE: list[str] | None = None

_PROVINCE_ALIASES_COMPILED: bool = False
_PROVINCE_PATTERNS: list[tuple[re.Pattern, str]] = []


def _compile_aliases():
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


# ───────────────────────────── Date helpers ────────────────────────────────────

def fmt_dmy(raw: str) -> Optional[str]:
    """'ddMMyyyy' → 'dd/MM/yyyy'. None if invalid."""
    if not raw or len(raw) != 8 or not raw.isdigit():
        return None
    try:
        d, m, y = int(raw[:2]), int(raw[2:4]), int(raw[4:8])
        return date(y, m, d).strftime("%d/%m/%Y")
    except Exception:
        return None


def calc_expiry(dob_fmt: str) -> str:
    """
    Tính ngày hết hạn CCCD:
      < 25 tuổi  → hết hạn lúc 25
      25–39      → hết hạn lúc 40
      40–59      → hết hạn lúc 60
      ≥ 60       → Không thời hạn
    dob_fmt: 'dd/MM/yyyy'
    """
    try:
        dob = datetime.strptime(dob_fmt, "%d/%m/%Y").date()
    except Exception:
        return "Không xác định"

    year = dob.year
    now  = date.today()
    ages = [year + 25, year + 40, year + 60]

    for i, threshold in enumerate([25, 40, 60]):
        if now.year < threshold:
            return dob.replace(year=ages[i]).strftime("%d/%m/%Y")
    return "Không thời hạn"


def calc_age(dob_fmt: str) -> Optional[int]:
    try:
        dob   = datetime.strptime(dob_fmt, "%d/%m/%Y").date()
        today = date.today()
        age = today.year - dob.year
        if (today.month, today.day) < (dob.month, dob.day):
            age -= 1
        return age
    except Exception:
        return None


def get_expiry_status(expiry: str) -> str:
    if not expiry or expiry in ("Không xác định",):
        return "unknown"
    if expiry == "Không thời hạn":
        return "permanent"
    try:
        diff = (datetime.strptime(expiry, "%d/%m/%Y").date() - date.today()).days
        if diff < 0:     return "expired"
        if diff <= 180:  return "expiring"
        return "valid"
    except Exception:
        return "unknown"


# ─────────────────────────── Card type detection ────────────────────────────────

def detect_card_type(parts: list[str], date_candidates: list[tuple[str, str]]) -> str:
    """
    3-rule combo detection:
      Rule 1 – Field 2 bị rỗng  → CAN_CUOC_MOI
      Rule 2 – > 7 fields        → CAN_CUOC_MOI
      Rule 3 – Ngày cấp ≥ 2024 → CAN_CUOC_MOI
      Fallback                   → CCCD_CU
    """
    if len(parts) > 1 and parts[1].strip() == "":
        return CAN_CUOC_MOI

    empty_count = sum(1 for p in parts if p.strip() == "")
    non_empty   = [p for p in parts if p.strip()]
    if empty_count >= 2 or len(non_empty) > 7:
        return CAN_CUOC_MOI

    if date_candidates and len(date_candidates) >= 2:
        issue_raw = date_candidates[-1][0]
        try:
            year = int(issue_raw[4:8])
            if year >= 2024:
                return CAN_CUOC_MOI
        except Exception:
            pass

    return CCCD_CU


# ─────────────────────────── Address parser ────────────────────────────────────

def normalize_address_str(s: str) -> str:
    """Bước 1: chuẩn hóa address string."""
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\bTP\.\s*", "TP. ", s)
    for old, new in [
        ("Tỉnh ", ""), ("tỉnh ", ""),
        ("Thành phố ", ""), ("thành phố ", ""),
    ]:
        s = s.replace(old, new)
    return s.strip()


def _province_names_longest_first() -> list[str]:
    global _PROVINCE_NAMES_SPLIT_CACHE
    if _PROVINCE_NAMES_SPLIT_CACHE is not None:
        return _PROVINCE_NAMES_SPLIT_CACHE
    names: set[str] = set(_EXTRA_PROVINCE_NAMES_FOR_SPLIT)
    names.update(_PROVINCE_ALIASES.values())
    jpath = Path(__file__).resolve().parents[2] / "static" / "data" / "vn_new_wards.json"
    if jpath.is_file():
        with open(jpath, encoding="utf-8") as fp:
            names.update(json.load(fp).keys())
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
        if _norm_addr_token(out[n - 1]) == _norm_addr_token(out[n - 3]) and _norm_addr_token(
            out[n - 2]
        ) == _norm_addr_token(out[n - 4]):
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


def parse_address_vn(raw_address: str, card_type: str) -> dict:
    """
    Bước 2 + 3: Chuẩn hóa → sửa lỗi QR (tỉnh dính xã, lặp đuôi) → reverse-split → map theo card_type.

    CCCD_CU (4 cấp cũ):   [detail, phường/xã, quận/huyện, tỉnh/TP]
    CAN_CUOC_MOI (3 cấp): [detail, phường/xã, tỉnh/TP]
      → phường/xã = parts[1], quận/huyện = rỗng, tỉnh/TP = parts[0]

    Returns: { detail, ward, district, province, province_raw, city }
    """
    if not raw_address:
        return {"detail": "", "ward": "", "district": "", "province": "",
                "province_raw": "", "city": ""}

    addr = repair_qr_address(raw_address)

    raw_parts = [p.strip() for p in addr.split(",")]
    parts = [p for p in raw_parts if p]
    parts.reverse()

    province_raw = parts[0] if len(parts) >= 1 else ""
    province = province_raw

    prov_key = province_raw.lower().replace(".", "").replace(" ", "")
    if prov_key in _PROVINCE_ALIASES:
        province = _PROVINCE_ALIASES[prov_key]

    district: str = ""
    ward: str = ""
    detail: str = ""

    if card_type == CAN_CUOC_MOI:
        ward = parts[1] if len(parts) >= 2 else ""
        detail_parts = parts[2:]
        detail_parts.reverse()
        detail = ", ".join(detail_parts) if detail_parts else ""
    else:
        district = parts[1] if len(parts) >= 2 else ""
        ward = parts[2] if len(parts) >= 3 else ""
        detail_parts = parts[3:]
        detail_parts.reverse()
        detail = ", ".join(detail_parts) if detail_parts else ""

    return {
        "detail":       detail,
        "ward":         ward,
        "district":     district,
        "province":     province,
        "province_raw": province_raw,
        "city":         province,
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

    cleaned = raw.strip()
    for prefix in ("CĂN CƯỚC CÔNG DÂN:", "CCCD:", "CMND:", "CAN CUOC:", "CANCUOC:"):
        if cleaned.upper().startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break

    raw_parts = cleaned.split("|")
    parts     = [p.strip() for p in raw_parts]

    id_number: str        = ""
    old_id: str           = ""
    name: str             = ""
    gender: str           = ""
    address_raw: str      = ""
    date_candidates: list[tuple[str, str]] = []

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

        elif p in ("Nam", "Nữ"):
            gender = p

        elif not name and re.search(r"[\u00C0-\u1EF9]", p):
            name = p.strip().upper()

        elif (
            len(p) > len(address_raw)
            and (
                "," in p
                or re.search(r"\d", p)
                or re.search(r"TP\.|Tỉnh|Thành phố|Quận|Huyện|Phường|Xã|Đường|Phố|Tổ|KP", p)
            )
        ):
            address_raw = p

    card_type = detect_card_type(parts, date_candidates)

    dob_fmt    = date_candidates[0][1] if date_candidates else ""
    issue_date = date_candidates[-1][1] if len(date_candidates) > 1 else ""

    addr = parse_address_vn(address_raw, card_type)

    expiry_date   = calc_expiry(dob_fmt) if dob_fmt else "Không xác định"
    age           = calc_age(dob_fmt)    if dob_fmt else None
    expiry_status = get_expiry_status(expiry_date)

    if not id_number and not old_id:
        is_valid = False
        error    = "Không tìm thấy số CCCD/CMND trong chuỗi QR"
    elif not name:
        is_valid = False
        error    = "Không tìm thấy tên trong chuỗi QR"
    elif not dob_fmt:
        is_valid = False
        error    = "Không tìm thấy ngày sinh trong chuỗi QR"
    else:
        is_valid = True
        error    = ""

    return {
        "card_type":     card_type,
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
        "error":         error,
        "raw_cleaned":   cleaned,
    }


# ─────────────────────────── Convenience aliases ────────────────────────────────

parse_cccd_qr    = parse_qr
parse_identity   = parse_qr
parse_qr_cccd    = parse_qr
