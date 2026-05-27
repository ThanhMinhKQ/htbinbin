# app/api/pms/mrz_parser.py
"""
Passport Parser using Gatecheap Vision API (OpenAI-compatible).
Extracts structured passport information directly from a passport photo via AI vision.
Đồng bộ với cccd_image_parser.py — cùng pattern preprocess + multi-model fallback.

Keeps a small ICAO-MRZ text fallback (`parse_mrz_text`) for cases where caller
already has clean MRZ lines extracted (e.g. unit tests, third-party MRZ readers).
"""
from __future__ import annotations
import asyncio
import base64
import io
import logging
import re
import time
from datetime import datetime

import httpx
from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)

# Optional: keep python-mrz for the text-only TD1/TD2/TD3 utility.
HAS_MRZ = False
try:
    from mrz.checker.td3 import TD3CodeChecker
    from mrz.checker.td2 import TD2CodeChecker
    from mrz.checker.td1 import TD1CodeChecker
    HAS_MRZ = True
except ImportError:
    logger.warning("python-mrz is not installed. Fallback MRZ text parsing will be unavailable.")


_PROMPT_PASSPORT = (
    "Đây là ảnh trang thông tin Passport (hộ chiếu). "
    "Hãy trích xuất CHỈ các trường dữ liệu sau (mỗi trường một dòng, đúng format):\n"
    "Surname: ...\n"
    "Given names: ...\n"
    "Passport No: ...\n"
    "Nationality: ... (mã 3 ký tự, ví dụ VNM, USA, IDN, CHN)\n"
    "Date of birth: dd/mm/yyyy\n"
    "Sex: M hoặc F\n"
    "Date of expiry: dd/mm/yyyy\n"
    "Date of issue: dd/mm/yyyy\n"
    "MRZ line 1: ... (44 ký tự ở dòng MRZ thứ nhất, gồm A-Z, 0-9, '<')\n"
    "MRZ line 2: ... (44 ký tự ở dòng MRZ thứ hai)\n\n"
    "BỎ QUA tiêu đề 'PASSPORT', logo, decorative text. "
    "Chỉ trả về các trường dữ liệu theo đúng format trên, không giải thích thêm."
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def _empty_address() -> dict:
    return {
        "raw_address": "",
        "province": "",
        "district": "",
        "ward": "",
        "street": "",
    }


def _normalize_gender(value: str) -> str:
    value = (value or "").strip().upper()
    if value in ("M", "MALE"):
        return "Nam"
    if value in ("F", "FEMALE"):
        return "Nữ"
    return "Khác"


def _normalize_name(surname: str, given_name: str) -> str:
    raw = f"{surname or ''} {given_name or ''}".replace("<", " ").strip()
    while "  " in raw:
        raw = raw.replace("  ", " ")
    return raw.title()


def _preprocess_image(image_bytes: bytes) -> bytes:
    """Fix EXIF orientation, downscale to 1024px, JPEG q70 — same approach as CCCD parser."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if hasattr(img, "_getexif") and img._getexif():
            exif = dict(img._getexif().items())
            orientation = exif.get(274)
            if orientation == 3:
                img = img.rotate(180, expand=True)
            elif orientation == 6:
                img = img.rotate(270, expand=True)
            elif orientation == 8:
                img = img.rotate(90, expand=True)
        img.thumbnail((1024, 1024))
        out = io.BytesIO()
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(out, format="JPEG", quality=70)
        return out.getvalue()
    except Exception as e:
        logger.warning(f"Passport PIL preprocessing failed: {e}")
        return image_bytes


def _build_ocr_payload(image_bytes: bytes, prompt_text: str, model: str) -> tuple[str, dict, dict]:
    b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:image/jpeg;base64,{b64}"
    url = f"{settings.GATECHEAP_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.GATECHEAP_API_KEY}",
        "Content-Type": "application/json",
    }
    json_body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        "temperature": 0.0,
        "max_tokens": 8192,
        "stream": False,
    }
    return url, headers, json_body


_PASSPORT_LABEL_RE = re.compile(
    r"(?im)^\s*(surname|given\s*names?|passport\s*no|nationality|date\s*of\s*birth|sex|date\s*of\s*expiry|date\s*of\s*issue|mrz\s*line)\s*[:：]"
)
_MRZ_PATTERN_RE = re.compile(r"[A-Z0-9<]{28,}")


def _has_passport_signal(text: str) -> bool:
    """Output is usable if it contains at least one labeled passport field or an MRZ-like run."""
    if not text:
        return False
    if _PASSPORT_LABEL_RE.search(text):
        return True
    for line in text.splitlines():
        m = _MRZ_PATTERN_RE.search(line)
        if m and "<" in m.group(0):
            return True
    return False


async def _run_passport_ocr(image_bytes: bytes) -> str:
    """Call Gatecheap Vision API to extract passport fields. Async, non-blocking. Returns raw text or ''."""
    if not settings.GATECHEAP_API_KEY:
        logger.warning("GATECHEAP_API_KEY not set — passport OCR skipped.")
        return ""

    image_bytes = await asyncio.to_thread(_preprocess_image, image_bytes)

    models_to_try = [
        settings.GATECHEAP_MODEL,
        settings.GATECHEAP_FALLBACK_MODEL,
        settings.GATECHEAP_SECOND_FALLBACK_MODEL,
    ]
    models_to_try = [m for m in models_to_try if m]

    _MIN_OCR_CHARS = 30  # passport response should at least have a few fields
    last_error = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        for model in models_to_try:
            try:
                url, headers, json_body = _build_ocr_payload(image_bytes, _PROMPT_PASSPORT, model)
                response = await client.post(url, headers=headers, json=json_body)
                response.raise_for_status()
                try:
                    result = response.json()
                except Exception:
                    logger.warning(
                        f"Passport OCR model={model} returned non-JSON: {response.text[:200]!r}"
                    )
                    continue
                text = (result["choices"][0]["message"].get("content") or "").strip()
                finish_reason = result["choices"][0].get("finish_reason", "unknown")
                if text:
                    logger.info(
                        f"Passport OCR model={model} returned {len(text)} chars (finish={finish_reason}): {text[:200]!r}"
                    )
                    if len(text) < _MIN_OCR_CHARS:
                        logger.warning(
                            f"Passport OCR model={model} returned too few chars ({len(text)}), trying next model"
                        )
                        continue
                    if not _has_passport_signal(text):
                        logger.warning(
                            f"Passport OCR model={model} returned reasoning-only output, trying next model"
                        )
                        continue
                    return text
            except Exception as e:
                last_error = e
                logger.warning(f"Passport OCR failed with model={model}: {e}")

    if last_error:
        raise last_error
    return ""


# ──────────────────────────────────────────────────────────────────────
# Field extraction from AI response
# ──────────────────────────────────────────────────────────────────────
def _extract_field(text: str, *labels: str) -> str:
    """Extract first matching label's value from a multi-line OCR response."""
    for line in text.splitlines():
        for label in labels:
            m = re.match(rf"^\s*{re.escape(label)}\s*[:：]\s*(.+?)\s*$", line, re.IGNORECASE)
            if m:
                return m.group(1).strip()
    return ""


def _parse_passport_text(text: str) -> dict:
    """Parse Vision API response — try labeled fields first, fallback to raw MRZ extraction."""
    if not text or "NO_MRZ" in text.upper():
        return {
            "is_valid": False,
            "error": "Không thể đọc được vùng MRZ từ ảnh Passport. Vui lòng chụp rõ phần dưới cùng của trang thông tin hộ chiếu.",
        }

    # ── Strategy 1: Parse labeled fields (AI followed the prompt) ──
    surname = _extract_field(text, "Surname", "Họ")
    given = _extract_field(text, "Given names", "Given name", "Tên")
    passport_no = _extract_field(text, "Passport No", "Passport Number", "Số hộ chiếu")
    nationality = _extract_field(text, "Nationality", "Quốc tịch")
    dob = _extract_field(text, "Date of birth", "Ngày sinh", "DOB")
    sex = _extract_field(text, "Sex", "Gender", "Giới tính")
    expiry = _extract_field(text, "Date of expiry", "Expiry", "Ngày hết hạn")
    issue = _extract_field(text, "Date of issue", "Ngày cấp")

    # Clean passport number
    passport_no = re.sub(r"[^A-Z0-9]", "", passport_no.upper()).strip() if passport_no else ""
    nationality = nationality.upper().strip()[:3] if nationality else ""

    # Try to get MRZ lines from labeled fields
    mrz1 = _extract_field(text, "MRZ line 1", "MRZ1")
    mrz2 = _extract_field(text, "MRZ line 2", "MRZ2")

    # Also scan for raw MRZ lines anywhere in the text (backtick-stripped)
    mrz_lines = []
    for line in text.splitlines():
        cleaned = re.sub(r"^[`\"'\s]+|[`\"'\s]+$", "", line)
        if cleaned.startswith("```"):
            continue
        mrz_match = re.search(r"([A-Z0-9<]{28,})", cleaned)
        if mrz_match and "<" in mrz_match.group(1):
            mrz_lines.append(mrz_match.group(1))

    # Merge labeled MRZ into mrz_lines if present
    if mrz1 and re.match(r"^[A-Z0-9<]{28,}$", mrz1) and mrz1 not in mrz_lines:
        mrz_lines.insert(0, mrz1)
    if mrz2 and re.match(r"^[A-Z0-9<]{28,}$", mrz2) and mrz2 not in mrz_lines:
        mrz_lines.append(mrz2)

    # If labeled fields are sufficient, use them directly
    name = _normalize_name(surname, given)

    # Convert dd/mm/yyyy to ISO yyyy-mm-dd
    def _to_iso(val: str) -> str:
        if not val:
            return ""
        m = re.match(r"^(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})$", val.strip())
        if m:
            return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
        if re.match(r"^\d{4}-\d{2}-\d{2}$", val.strip()):
            return val.strip()
        return ""

    dob_iso = _to_iso(dob)
    expiry_iso = _to_iso(expiry)
    issue_iso = _to_iso(issue)

    if passport_no and name and len(name) > 2 and dob_iso:
        return {
            "is_valid": True,
            "card_type": "passport",
            "id_number": passport_no,
            "name": name,
            "dob": dob_iso,
            "gender": _normalize_gender(sex),
            "expiry_date": expiry_iso,
            "issue_date": issue_iso,
            "nationality": nationality,
            "address": _empty_address(),
            "conflicts": [],
            "warnings": [],
            "raw_cleaned": "\n".join(mrz_lines) if mrz_lines else text,
            "error": "",
        }

    # ── Strategy 2: Parse MRZ lines directly (AI gave raw MRZ or partial labels) ──
    if len(mrz_lines) >= 2:
        if HAS_MRZ:
            result = parse_mrz_text(mrz_lines)
            if result.get("is_valid"):
                return result

        # Manual TD3 parse (2 × 44 chars)
        if len(mrz_lines[0]) == 44 and len(mrz_lines[1]) == 44:
            return _parse_td3_manual(mrz_lines[0], mrz_lines[1])

    return {
        "is_valid": False,
        "error": "Không nhận diện được mã MRZ hợp lệ từ ảnh. Vui lòng chụp rõ nét phần dưới cùng của hộ chiếu.",
    }


def _parse_td3_manual(line1: str, line2: str) -> dict:
    """Manual TD3 MRZ parser (2×44 chars) — no python-mrz dependency needed."""
    # Line 1: P<ISSNAME<<GIVEN<<<<<<<<<<<<<<<<<<<<<<<<<
    # Line 2: DOCNUM<<<CNATYYMMDDCSYYMMDDCOPT<<<<<<<<CC
    try:
        # Line 1: doc type (pos 0), issuer (1-3), names (5+)
        names_part = line1[5:].split("<<", 1)
        surname = names_part[0].replace("<", " ").strip() if names_part else ""
        given_name = names_part[1].replace("<", " ").strip() if len(names_part) > 1 else ""

        # Line 2
        doc_number = line2[0:9].replace("<", "").strip()
        nationality = line2[10:13].replace("<", "").strip()
        dob_raw = line2[13:19]  # YYMMDD
        sex = line2[20]         # M/F/<
        expiry_raw = line2[21:27]  # YYMMDD

        dob = _parse_mrz_date(dob_raw, is_birth=True)
        expiry = _parse_mrz_date(expiry_raw, is_birth=False)

        name = _normalize_name(surname, given_name)
        is_valid = bool(doc_number and name and dob)

        return {
            "is_valid": is_valid,
            "card_type": "passport",
            "id_number": doc_number,
            "name": name,
            "dob": dob,
            "gender": _normalize_gender(sex),
            "expiry_date": expiry,
            "nationality": nationality,
            "address": _empty_address(),
            "conflicts": [],
            "warnings": [],
            "raw_cleaned": f"{line1}\n{line2}",
            "error": "" if is_valid else "Thiếu trường bắt buộc trong MRZ",
        }
    except Exception as e:
        logger.warning(f"Manual TD3 parse failed: {e}")
        return {
            "is_valid": False,
            "error": "Lỗi phân tích mã MRZ. Vui lòng chụp lại rõ hơn.",
        }


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────
async def parse_mrz_from_image(image_bytes: bytes, filename: str = "") -> dict:
    """
    Extract and parse Passport information from uploaded image bytes via Gatecheap Vision API.
    """
    if not image_bytes:
        return {
            "is_valid": False,
            "error": "Không nhận được ảnh Passport để nhận diện.",
        }

    if not settings.GATECHEAP_API_KEY:
        return {
            "is_valid": False,
            "error": "Hệ thống nhận diện ảnh chưa được cấu hình (GATECHEAP_API_KEY trống). Vui lòng nhập thông tin Passport thủ công.",
        }

    t0 = time.monotonic()
    try:
        ocr_text = await _run_passport_ocr(image_bytes)
    except Exception as exc:
        logger.error("Error calling Gatecheap Vision for passport: %s", exc)
        return {
            "is_valid": False,
            "error": "Lỗi nhận diện Passport. Vui lòng thử lại sau hoặc nhập thông tin thủ công.",
        }

    elapsed = round(time.monotonic() - t0, 2)
    logger.info("[Passport OCR] chars=%s elapsed=%.2fs", len(ocr_text), elapsed)

    return _parse_passport_text(ocr_text)


# ──────────────────────────────────────────────────────────────────────
# Legacy / fallback helpers (kept for tests + clean MRZ text input)
# ──────────────────────────────────────────────────────────────────────
def _parse_mrz_date(date_str: str, is_birth: bool = False) -> str:
    """Convert YYMMDD to YYYY-MM-DD."""
    if not date_str or len(date_str) != 6 or not date_str.isdigit():
        return ""
    yy = int(date_str[:2])
    mm = date_str[2:4]
    dd = date_str[4:]
    current_yy = datetime.now().year % 100
    if is_birth:
        year = 2000 + yy if yy <= current_yy else 1900 + yy
    else:
        year = 2000 + yy
    return f"{year}-{mm}-{dd}"


def parse_mrz_text(mrz_lines: list[str]) -> dict:
    """
    Parses clean MRZ text lines using the python `mrz` library (TD1/TD2/TD3).
    Used by callers that already have OCRed MRZ text.
    """
    if not HAS_MRZ:
        return {"is_valid": False, "error": "Thư viện python-mrz chưa được cài đặt trên server."}

    cleaned_lines = [line.strip().upper().replace(" ", "") for line in mrz_lines if line.strip()]

    for check_class in [TD3CodeChecker, TD2CodeChecker, TD1CodeChecker]:
        try:
            mrz_str = "\n".join(cleaned_lines)
            checker = check_class(mrz_str)
            if bool(checker):
                fields = checker.fields()
                dob = _parse_mrz_date(fields.birth_date, is_birth=True)
                expiry = _parse_mrz_date(fields.expiry_date, is_birth=False)
                return {
                    "is_valid": True,
                    "card_type": "passport",
                    "id_number": fields.document_number.replace("<", "").strip(),
                    "name": _normalize_name(fields.surname, fields.name),
                    "dob": dob,
                    "gender": _normalize_gender(fields.sex),
                    "expiry_date": expiry,
                    "nationality": fields.nationality.strip(),
                    "address": _empty_address(),
                    "conflicts": [],
                    "warnings": [],
                    "raw_cleaned": mrz_str,
                }
        except Exception as e:
            logger.debug(f"Failed parsing with {check_class.__name__}: {e}")

    return {"is_valid": False, "error": "Không thể định dạng hoặc khớp mã MRZ"}
