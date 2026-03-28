# app/api/pms/cccd_scan_api.py
"""
CCCD / Căn Cước QR Scan API
Pattern-based parsing + card-type detection + address normalization.
"""
from __future__ import annotations

import re
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from .pms_helpers import _require_login
from .identity_parser import parse_qr, CAN_CUOC_MOI, CCCD_CU, CMND_TYPE, parse_address_vn
from .vn_fuzzy import canonicalize_province

router = APIRouter()

# ───────────────────────────── Card type constants ─────────────────────────────

CCCD_CU        = "CCCD_CU"        # CCCD thường (pre-2024, 7 fields, có CMND cũ)
CAN_CUOC_MOI  = "CAN_CUOC_MOI"  # Căn cước công dân mới (2024+, || field 2)
CMND_TYPE     = "CMND"           # CMND 9 số (không phải CCCD)

# ───────────────────────────── Helpers ─────────────────────────────────────────

def _fmt_dmy(raw: str) -> Optional[str]:
    """'ddMMyyyy' → 'dd/MM/yyyy'. None if invalid."""
    if not raw or len(raw) != 8 or not raw.isdigit():
        return None
    try:
        d, m, y = int(raw[:2]), int(raw[2:4]), int(raw[4:8])
        return date(y, m, d).strftime("%d/%m/%Y")
    except Exception:
        return None


def _calc_expiry(dob_fmt: str) -> str:
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


def _calc_age(dob_fmt: str) -> Optional[int]:
    try:
        dob  = datetime.strptime(dob_fmt, "%d/%m/%Y").date()
        today = date.today()
        age = today.year - dob.year
        if (today.month, today.day) < (dob.month, dob.day):
            age -= 1
        return age
    except Exception:
        return None


def _get_expiry_status(expiry: str) -> str:
    if not expiry or expiry in ("Không xác định",):
        return "unknown"
    if expiry == "Không thời hạn":
        return "permanent"
    try:
        diff = (datetime.strptime(expiry, "%d/%m/%Y").date() - date.today()).days
        if diff < 0:   return "expired"
        if diff <= 180: return "expiring"
        return "valid"
    except Exception:
        return "unknown"


# ─────────────────────────── Card type detection ───────────────────────────────

def _detect_card_type(parts: list[str], date_candidates: list[tuple[str, str]]) -> str:
    """
    3-rule combo detection:
      Rule 1 – Field 2 bị rỗng  → CAN_CUOC_MOI
      Rule 2 – > 7 fields (thừa ||)  → CAN_CUOC_MOI
      Rule 3 – Ngày cấp ≥ 2024     → CAN_CUOC_MOI
      Fallback                        → CCCD_CU
    """
    # Rule 1: field[1] empty
    if len(parts) > 1 and parts[1].strip() == "":
        return CAN_CUOC_MOI

    # Rule 2: too many empty fields / > 7 total fields
    empty_count = sum(1 for p in parts if p.strip() == "")
    non_empty   = [p for p in parts if p.strip()]
    if empty_count >= 2 or len(non_empty) > 7:
        return CAN_CUOC_MOI

    # Rule 3: issue date year >= 2024
    if date_candidates and len(date_candidates) >= 2:
        issue_raw = date_candidates[-1][0]   # last = issue_date
        try:
            year = int(issue_raw[4:8])
            if year >= 2024:
                return CAN_CUOC_MOI
        except Exception:
            pass

    return CCCD_CU


# ─────────────────────────── Address parser ────────────────────────────────────
# parse_address_vn: identity_parser (repair QR dính tỉnh–xã, bỏ lặp đuôi, 3/4 cấp).

# ─────────────────────────── Main QR parser ───────────────────────────────────

def parse_cccd_qr(raw: str) -> dict:
    """
    Parse chuỗi QR CCCD / Căn cước / CMND quét được.

    Returns:
      {
        "card_type":      "CCCD_CU" | "CAN_CUOC_MOI" | "CMND",
        "id_number":      "...",       # CCCD 12 số
        "old_id":         "...",       # CMND 9 số (CCCD_CU only)
        "name":           "...",
        "dob":            "dd/MM/yyyy",
        "gender":         "Nam" | "Nữ",
        "address": {
          "raw":          "...",
          "detail":       "...",
          "ward":         "...",
          "district":     "...",
          "province":     "...",
        },
        "issue_date":     "dd/MM/yyyy" | "",
        "expiry_date":    "dd/MM/yyyy" | "Không thời hạn",
        "age":            int | None,
        "is_valid":       bool,
        "expiry_status":  "valid" | "expiring" | "expired" | "permanent" | "unknown",
        "error":          "",
        "raw_cleaned":    "...",
      }
    """
    # ── 1. Strip prefixes ────────────────────────────────────────────────────
    cleaned = raw.strip()
    for prefix in ("CĂN CƯỚC CÔNG DÂN:", "CCCD:", "CMND:", "CAN CUOC:", "CANCUOC:"):
        if cleaned.upper().startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break

    # ── 2. Split by pipe ─────────────────────────────────────────────────────
    raw_parts = cleaned.split("|")
    parts     = [p.strip() for p in raw_parts]

    # ── 3. Pattern-based field extraction ───────────────────────────────────
    id_number: str        = ""
    old_id: str           = ""
    name: str             = ""
    gender: str           = ""
    address_raw: str      = ""
    date_candidates: list[tuple[str, str]] = []

    for p in parts:
        if not p:
            continue

        # 12-digit ID (CCCD)
        if re.fullmatch(r"\d{12}", p) and not id_number:
            id_number = p

        # 9-digit old CMND
        elif re.fullmatch(r"\d{9}", p) and not old_id:
            old_id = p

        # 8-digit date ddMMyyyy
        elif re.fullmatch(r"\d{8}", p):
            fmt = _fmt_dmy(p)
            if fmt:
                date_candidates.append((p, fmt))

        # Gender
        elif p in ("Nam", "Nữ"):
            gender = p

        # Name: chữ tiếng Việt, không phải số thuần
        elif not name and re.search(r"[\u00C0-\u1EF9]", p):
            name = p.strip().upper()

        # Address: chuỗi dài nhất, có dấu phẩy hoặc số nhà
        elif (
            len(p) > len(address_raw)
            and (
                "," in p
                or re.search(r"\d", p)
                or re.search(r"TP\.|Tỉnh|Thành phố|Quận|Huyện|Phường|Xã|Đường|Phố|Tổ|KP", p)
            )
        ):
            address_raw = p

    # ── 4. Detect card type ─────────────────────────────────────────────────
    card_type = _detect_card_type(parts, date_candidates)

    # ── 5. Assign dates ─────────────────────────────────────────────────────
    dob_fmt    = date_candidates[0][1] if date_candidates else ""
    issue_date = date_candidates[-1][1] if len(date_candidates) > 1 else ""

    # ── 6. Parse address ─────────────────────────────────────────────────────
    addr = parse_address_vn(address_raw, card_type)

    # ── 7. Expiry + age ──────────────────────────────────────────────────────
    expiry_date = _calc_expiry(dob_fmt) if dob_fmt else "Không xác định"
    age         = _calc_age(dob_fmt)    if dob_fmt else None
    expiry_status = _get_expiry_status(expiry_date)

    # ── 8. Validation ───────────────────────────────────────────────────────
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


# ─────────────────────────── API endpoint ──────────────────────────────────────

@router.post("/api/pms/scan/cccd", tags=["PMS"])
async def api_scan_cccd(
    request: Request,
    raw: str = Query(..., description="Chuỗi QR quét được"),
):
    """Parse chuỗi QR CCCD / Căn cước / CMND, trả về structured data."""
    _require_login(request)

    if not raw or len(raw.strip()) < 5:
        return JSONResponse(status_code=400, content={"detail": "Chuỗi QR rỗng hoặc quá ngắn"})

    result = parse_qr(raw)   # from identity_parser (supports fuzzy province)
    return JSONResponse({
        "success":       result["is_valid"],
        "data":          result,
        "card_type":     result["card_type"],
        "expiry_status": result["expiry_status"],
    })
