# app/api/pms/cccd_scan_api.py
"""
CCCD / Căn Cước QR Scan API
Scanner preprocessing + API endpoint.
All parsing logic lives in identity_parser.py (single source of truth).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from .pms_helpers import _require_login
from .identity_parser import parse_qr, CAN_CUOC_MOI, CCCD_CU, CMND_TYPE, parse_address_vn

router = APIRouter()

# ───────────────────────────── Raw data preprocessing ──────────────────────────

def preprocess_raw(raw: str) -> str:
    """Clean raw QR data from scanner before parsing.

    Handles common RAR-DTA RD23 scanner artifacts:
      - NULL bytes & control characters
      - Unicode normalization (NFC)
      - Triple+ pipes → double pipe (preserve || for CAN_CUOC_MOI)
      - Trailing/leading whitespace, stray carriage returns
    """
    if not raw:
        return ""
    s = raw
    # 1. Remove NULL bytes and non-printable control chars
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)
    # 2. Flatten line-endings
    s = s.replace("\r\n", "").replace("\r", "").replace("\n", "")
    # 3. Unicode NFC normalization (fixes composed vs decomposed Vietnamese)
    s = unicodedata.normalize("NFC", s)
    # 4. Fix triple+ pipes → double (CAN_CUOC_MOI uses ||, don't collapse those)
    s = re.sub(r"\|{3,}", "||", s)
    # 5. Trim
    return s.strip()


def _calc_confidence(result: dict) -> float:
    """Score 0.0–1.0 indicating how confident we are in the parse result."""
    if not result.get("is_valid"):
        return 0.0
    score = 0.0
    if result.get("id_number"):   score += 0.30
    if result.get("name"):        score += 0.25
    if result.get("dob"):         score += 0.15
    if result.get("gender"):      score += 0.10
    addr = result.get("address", {})
    if addr.get("province"):      score += 0.10
    if addr.get("district") or addr.get("ward"): score += 0.05
    if result.get("issue_date"):  score += 0.05
    return round(min(score, 1.0), 2)


# ─────────────────────────── API endpoint ──────────────────────────────────────

@router.get("/api/pms/scan/cccd", tags=["PMS"])
def api_scan_cccd(
    request: Request,
    raw: str = Query(..., description="Chuỗi QR quét được"),
):
    """Parse chuỗi QR CCCD / Căn cước / CMND, trả về structured data."""
    _require_login(request)

    if not raw or len(raw.strip()) < 5:
        return JSONResponse(status_code=400, content={"detail": "Chuỗi QR rỗng hoặc quá ngắn"})

    # Preprocess: clean scanner artifacts before parsing
    cleaned = preprocess_raw(raw)

    result = parse_qr(cleaned)   # from identity_parser (single source of truth)
    confidence = _calc_confidence(result)

    return JSONResponse({
        "success":       result["is_valid"],
        "data":          result,
        "card_type":     result["card_type"],
        "expiry_status": result["expiry_status"],
        "confidence":    confidence,
    })