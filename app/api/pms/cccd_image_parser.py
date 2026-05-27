# app/api/pms/cccd_image_parser.py
"""
CCCD/CMND Image Parser using Gatecheap Vision API (OpenAI-compatible).
Extracts structured guest information from front and back photos of CCCD.
"""
from __future__ import annotations
import base64
import logging
import re
import io
import time
from datetime import datetime, date
from PIL import Image
import httpx

from .identity_parser import (
    parse_address_vn,
    detect_card_type,
    calc_expiry,
    calc_age,
    get_expiry_status,
    _normalize_gender,
    _birth_gender_from_cccd,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

_PROMPT_FRONT = (
    "Đây là ảnh MẶT TRƯỚC CCCD/Căn cước công dân Việt Nam. "
    "Hãy trích xuất CHỈ các trường dữ liệu sau (bằng tiếng Việt, giữ nguyên dấu), mỗi trường một dòng:\n"
    "Số / No.: ...\n"
    "Họ và tên / Full name: ...\n"
    "Ngày sinh / Date of birth: dd/mm/yyyy\n"
    "Giới tính / Sex: Nam hoặc Nữ\n"
    "Quốc tịch / Nationality: ...\n"
    "Quê quán / Place of origin: ...\n"
    "Nơi thường trú / Place of residence: ...\n"
    "Có giá trị đến / Date of expiry: dd/mm/yyyy\n\n"
    "BỎ QUA hoàn toàn các dòng tiêu đề như 'CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM', "
    "'Độc lập - Tự do - Hạnh phúc', 'CĂN CƯỚC CÔNG DÂN', 'Socialist Republic'. "
    "Chỉ trả về các trường dữ liệu, không giải thích thêm."
)

_PROMPT_BACK = (
    "Đây là ảnh MẶT SAU CCCD/Căn cước công dân Việt Nam. "
    "Hãy trích xuất CHỈ các trường dữ liệu sau (bằng tiếng Việt, giữ nguyên dấu), mỗi trường một dòng:\n"
    "Nơi thường trú / Place of residence: ... (địa chỉ đầy đủ)\n"
    "Ngày cấp: ngày ... tháng ... năm ...\n"
    "Đặc điểm nhận dạng: ...\n\n"
    "BỎ QUA các dòng tiêu đề, logo, chức danh. "
    "Chỉ trả về các trường dữ liệu, không giải thích thêm."
)


_NO_IMAGE_PATTERNS = re.compile(
    r"(không\s*(thấy|nhận|có|nhìn\s*thấy)(\s+\S+){0,3}\s*ảnh|"
    r"chưa\s*(thấy|nhận|đính\s*kèm|gửi)(\s+\S+){0,3}\s*ảnh|"
    r"(chưa|không)\s*(\S+\s+){0,3}đính\s*kèm\s*ảnh|"
    r"gửi\s*(lại|kèm)?\s*(\S+\s+){0,3}ảnh|"
    r"no\s*image|don'?t\s*see\s*(an|any)\s*image|i\s*can'?t\s*see\s*(an|any)\s*image)",
    re.IGNORECASE,
)


def _is_no_image_response(text: str) -> bool:
    """Detect when model hallucinates that no image was attached."""
    return bool(text) and bool(_NO_IMAGE_PATTERNS.search(text))


def parse_cccd_image(front_bytes: bytes, back_bytes: bytes | None = None) -> dict:
    """
    OCR front and back CCCD images using Gatecheap Vision API and parse structured guest information.
    Sends front first, then back sequentially to avoid proxy issues with concurrent/multi-image requests.
    """
    t0 = time.monotonic()
    front_text = ""
    back_text = ""

    if front_bytes:
        try:
            front_text = _run_gatecheap_ocr(front_bytes, _PROMPT_FRONT)
        except Exception as e:
            logger.error(f"Error running Gatecheap OCR on front image: {e}")
            front_text = ""

    if back_bytes:
        try:
            back_text = _run_gatecheap_ocr(back_bytes, _PROMPT_BACK)
        except Exception as e:
            logger.error(f"Error running Gatecheap OCR on back image: {e}")
            back_text = ""

    # If OCR returned empty, return error instead of mock data
    if not front_text:
        return {
            "is_valid": False,
            "error": "Không thể đọc được nội dung từ ảnh CCCD. Vui lòng chụp lại rõ hơn hoặc dùng quét mã QR.",
            "card_type": "",
            "confidence": 0.0,
        }

    elapsed = round(time.monotonic() - t0, 2)
    logger.info(
        "[CCCD OCR] front_chars=%s back_chars=%s back_uploaded=%s elapsed=%.2fs",
        len(front_text),
        len(back_text),
        bool(back_bytes),
        elapsed,
    )

    return _parse_cccd_text(front_text, back_text)


def _preprocess_image(image_bytes: bytes) -> bytes:
    """Preprocess image: fix EXIF orientation, resize to 1024px, compress JPEG quality 70."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if hasattr(img, '_getexif') and img._getexif():
            exif = dict(img._getexif().items())
            orientation = exif.get(274)
            if orientation == 3:
                img = img.rotate(180, expand=True)
            elif orientation == 6:
                img = img.rotate(270, expand=True)
            elif orientation == 8:
                img = img.rotate(90, expand=True)

        # Always resize to max 1024px — drastically reduces base64 payload
        # CCCD text is large print, 1024px is more than enough for OCR accuracy
        img.thumbnail((768, 768))

        out_buf = io.BytesIO()
        img.save(out_buf, format='JPEG', quality=60)
        return out_buf.getvalue()
    except Exception as e:
        logger.warning(f"PIL Image preprocessing failed: {e}")
        return image_bytes


def _build_ocr_payload(image_bytes: bytes, prompt_text: str, model: str) -> tuple[str, dict, dict]:
    """Build URL, headers, and JSON payload for Gatecheap OCR call."""
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
        "max_tokens": 2048,
        "stream": False,
    }
    return url, headers, json_body


def _run_gatecheap_ocr(image_bytes: bytes, prompt_text: str = "") -> str:
    """Run OCR via Gatecheap Vision API (OpenAI-compatible, base64 image). Synchronous version."""
    if not settings.GATECHEAP_API_KEY:
        logger.warning("GATECHEAP_API_KEY not set — skipping OCR.")
        return ""

    image_bytes = _preprocess_image(image_bytes)
    logger.info(f"[CCCD OCR] preprocessed image size: {len(image_bytes)} bytes")

    models_to_try = [
        settings.GATECHEAP_MODEL,
        settings.GATECHEAP_FALLBACK_MODEL,
        settings.GATECHEAP_SECOND_FALLBACK_MODEL,
    ]
    models_to_try = [m for m in models_to_try if m]

    if not prompt_text:
        prompt_text = _PROMPT_FRONT

    # Minimum chars for a valid CCCD OCR result (ID + name + DOB at minimum)
    _MIN_OCR_CHARS = 50

    last_error = None
    for model in models_to_try:
        try:
            url, headers, json_body = _build_ocr_payload(image_bytes, prompt_text, model)
            response = httpx.post(url, headers=headers, json=json_body, timeout=20.0)
            response.raise_for_status()
            raw_body = response.text
            try:
                result = response.json()
            except Exception:
                logger.warning(f"Gatecheap OCR model={model} returned non-JSON (status {response.status_code}): {raw_body[:200]!r}")
                continue
            text = result["choices"][0]["message"]["content"]
            finish_reason = result["choices"][0].get("finish_reason", "unknown")
            if text and text.strip():
                text = text.strip()
                logger.info(f"Gatecheap OCR model={model} returned {len(text)} chars (finish={finish_reason}): {text[:200]!r}")
                if _is_no_image_response(text):
                    logger.warning(f"Gatecheap OCR model={model} hallucinated no-image response, trying next model")
                    continue
                if len(text) >= _MIN_OCR_CHARS:
                    return text
                logger.warning(f"Gatecheap OCR model={model} returned too few chars ({len(text)}), trying next model")
                continue
        except Exception as e:
            last_error = e
            logger.warning(f"Gatecheap OCR failed with model={model}: {e}")
            continue

    if last_error:
        raise last_error
    return ""


def _extract_residence_from_lines(text_lines: list[str], *, allow_unlabeled: bool = False) -> str:
    residence_lines = []
    residence_started = False

    for line in text_lines:
        if re.search(r"(nơi\s*thường\s*trú|place\s*of\s*residence|nơi\s*thường\s*trù|nơi\s*thương\s*trú)", line, re.IGNORECASE):
            residence_started = True
            colon_part = re.split(r"\s*[:\-]\s*", line, maxsplit=1)
            if len(colon_part) > 1 and len(colon_part[1].strip()) > 3:
                residence_lines.append(colon_part[1].strip())
            continue
        if residence_started:
            if re.search(r"(có\s*giá\s*trị|ngày\s*hết\s*hạn|expiry|đặc\s*điểm|ngày\s*cấp|ngày\s*\d|cục\s*trưởng)", line, re.IGNORECASE):
                break
            residence_lines.append(line)

    if not residence_lines and allow_unlabeled:
        for line in text_lines:
            if re.search(r"(ngày\s*\d|tháng|năm|đặc\s*điểm|cục\s*trưởng|expiry|hết\s*hạn)", line, re.IGNORECASE):
                continue
            if line.count(",") >= 1 and re.search(r"(phường|xã|thị\s*trấn|quận|huyện|thành\s*phố|tỉnh|tp\.?\s*)", line, re.IGNORECASE):
                residence_lines.append(line)
                break

    address = ", ".join(residence_lines).strip()
    address = re.sub(r"^(nơi\s*thường\s*trú|place\s*of\s*residence)\s*[/A-Za-z\s]*[:\-\s]*", "", address, flags=re.IGNORECASE).strip()
    address = re.sub(r"^[,\-\s:]+", "", address)
    return re.sub(r"[,\-\s:]+$", "", address)


def _parse_cccd_text(front_text: str, back_text: str = "") -> dict:
    """
    Parses front & back OCR text using regex and heuristics.
    Matches standard fields from Vietnamese CCCD layouts (old / new).
    """
    # Clean OCR text: remove multiple newlines/spaces, keep line endings
    lines = [line.strip() for line in front_text.split("\n") if line.strip()]
    # Filter out header/title lines that AI sometimes includes
    _junk_patterns = [
        "socialist republic", "cộng hòa xã hội", "độc lập", "tự do", "hạnh phúc",
        "căn cước công dân", "citizen identity", "chứng minh nhân dân",
    ]
    lines = [l for l in lines if not any(p in l.lower() for p in _junk_patterns)]
    full_text_single_line = " ".join(lines)

    id_number = ""
    name = ""
    dob_fmt = ""
    gender = ""
    nationality = "Việt Nam" # Default
    address_raw = ""
    back_address_raw = ""
    place_of_origin = ""

    # 1. Số định danh / ID number (12 digits or 9 digits for CMND)
    id_match = re.search(r"\b(\d{12})\b", full_text_single_line)
    if id_match:
        id_number = id_match.group(1)
    else:
        # Fallback to 9 digits CMND
        id_match_old = re.search(r"\b(\d{9})\b", full_text_single_line)
        if id_match_old:
            id_number = id_match_old.group(1)

    # 2. Dob / Ngày sinh
    # Looking for dd/mm/yyyy or dd - mm - yyyy or similar
    dob_match = re.search(r"(ngày\s*sinh|date\s*of\s*birth|sinh\s*ngày).*?(\d{2})[/\-\s\.](\d{2})[/\-\s\.](\d{4})", full_text_single_line, re.IGNORECASE)
    if dob_match:
        dob_fmt = f"{dob_match.group(2)}/{dob_match.group(3)}/{dob_match.group(4)}"
    else:
        # Fallback to first date format in text
        dob_match_fallback = re.search(r"\b(\d{2})[/\-\s\.](\d{2})[/\-\s\.](\d{4})\b", full_text_single_line)
        if dob_match_fallback:
            dob_fmt = f"{dob_match_fallback.group(1)}/{dob_match_fallback.group(2)}/{dob_match_fallback.group(3)}"

    # 3. Giới tính / Gender
    # Look for Giới tính: Nam/Nữ or Nam / Nữ
    gender_match = re.search(r"giới\s*tính\s*[:\-\s]*\s*(Nam|Nữ|Nữ\s*\/|Nam\s*\/)", full_text_single_line, re.IGNORECASE)
    if gender_match:
        gender = _normalize_gender(gender_match.group(1).replace("/", "").strip())
    else:
        # Heuristic search for "Nam" or "Nữ" standing alone in lines
        for line in lines:
            norm_l = line.lower().strip()
            if norm_l == "nam":
                gender = "Nam"
                break
            elif norm_l == "nữ" or norm_l == "nu":
                gender = "Nữ"
                break

    # 4. Quốc tịch / Nationality
    nat_match = re.search(r"(quốc\s*tịch|nationality)[/A-Za-z\s:]*:\s*([A-Za-zÀ-ỹĐđ\s]+)", full_text_single_line, re.IGNORECASE)
    if nat_match:
        nationality = nat_match.group(2).strip()
        # Clean potential tail junk from next labels
        nationality = re.split(r"(quê|nơi|ngày|hạn|số|có giá)", nationality, flags=re.IGNORECASE)[0].strip()

    # 5. Name / Họ và tên
    # Name is typically in UPPERCASE, on its own line, following "Họ và tên" or "Full name"
    # Or just detected via all-caps line following ID line
    name_heuristics = []
    for i, line in enumerate(lines):
        if re.search(r"(họ\s*và\s*tên|họ\s*tên|full\s*name|họ\s*về\s*tên)", line, re.IGNORECASE):
            # The name is either on the same line after colon, or on the next line
            colon_split = re.split(r"\s*[:\-]\s*", line, maxsplit=1)
            if len(colon_split) > 1 and len(colon_split[1].strip()) >= 5 and colon_split[1].isupper():
                name_heuristics.append(colon_split[1].strip())
            if i + 1 < len(lines):
                next_line = lines[i+1].strip()
                if next_line.isupper() and len(next_line) >= 5 and not any(kw in next_line.lower() for kw in ["số", "cccd", "id"]):
                    name_heuristics.append(next_line)
                elif i + 2 < len(lines): # Try one more line if next is just small label
                    next_next_line = lines[i+2].strip()
                    if next_next_line.isupper() and len(next_next_line) >= 5 and not any(kw in next_next_line.lower() for kw in ["số", "cccd", "id"]):
                        name_heuristics.append(next_next_line)
        # Regex search for all caps words of name length
        if line.isupper() and 2 <= len(line.split()) <= 5 and not any(kw in line.lower() for kw in ["cộng hòa", "độc lập", "tự do", "căn cước", "cục trưởng"]):
            name_heuristics.append(line)

    # Use first valid name heuristic
    for n in name_heuristics:
        # Clean non-alphabetical
        n_clean = re.sub(r"[^A-ZÀ-ỸĐđ\s]", "", n).strip()
        if len(n_clean.split()) >= 2:
            name = n_clean
            break

    # 6. Quê quán / Place of origin
    # Looks for "Quê quán" or "Place of origin"
    origin_lines = []
    origin_started = False
    for i, line in enumerate(lines):
        if re.search(r"(quê\s*quán|place\s*of\s*origin|quê\s*quấn)", line, re.IGNORECASE):
            origin_started = True
            # Extract content after colon if present
            colon_part = re.split(r"\s*[:\-]\s*", line, maxsplit=1)
            if len(colon_part) > 1 and len(colon_part[1].strip()) > 3:
                origin_lines.append(colon_part[1].strip())
            continue
        if origin_started:
            if re.search(r"(nơi\s*thường\s*trú|nơi\s*cư\s*trú|place\s*of\s*residence|ngày|có\s*giá\s*trị)", line, re.IGNORECASE):
                break
            origin_lines.append(line)
    if origin_lines:
        place_of_origin = ", ".join(origin_lines).strip()

    # 7. Nơi thường trú / Place of residence
    address_raw = _extract_residence_from_lines(lines)

    # Clean address and origin from label junk
    for junk in ["Quê quán", "Quê quán:", "Quê quán / Place of origin", "Nơi thường trú", "Nơi thường trú:", "Nơi thường trú / Place of residence"]:
        if address_raw.startswith(junk):
            address_raw = address_raw[len(junk):].strip()
        if place_of_origin.startswith(junk):
            place_of_origin = place_of_origin[len(junk):].strip()

    # Clean tail junk
    address_raw = re.split(r"(có giá|expiry|giá trị)", address_raw, flags=re.IGNORECASE)[0].strip()
    place_of_origin = re.split(r"(nơi thường|thường trú)", place_of_origin, flags=re.IGNORECASE)[0].strip()

    # Remove extra spaces/dangling commas
    address_raw = re.sub(r"^[,\-\s:]+", "", address_raw)
    address_raw = re.sub(r"[,\-\s:]+$", "", address_raw)
    place_of_origin = re.sub(r"^[,\-\s:]+", "", place_of_origin)
    place_of_origin = re.sub(r"[,\-\s:]+$", "", place_of_origin)

    # 8. Expiry date / Có giá trị đến
    expiry_date = ""
    expiry_match = re.search(r"(có\s*giá\s*trị\s*đến|đến|ngày\s*hết\s*hạn|expiry\s*date).*?(\d{2})[/\-\s\.](\d{2})[/\-\s\.](\d{4})", full_text_single_line, re.IGNORECASE)
    if expiry_match:
        expiry_date = f"{expiry_match.group(2)}/{expiry_match.group(3)}/{expiry_match.group(4)}"

    # 9. Issue date + address from back text (Căn cước mới có Nơi thường trú ở mặt sau)
    issue_date = ""
    if back_text:
        back_lines = [line.strip() for line in back_text.split("\n") if line.strip()]
        # Filter junk from back text too
        back_lines = [l for l in back_lines if not any(p in l.lower() for p in _junk_patterns)]
        back_single = " ".join(back_lines)

        # Issue date: "ngày ... tháng ... năm ..."
        issue_match = re.search(r"ngày\s*(\d{1,2})\s*tháng\s*(\d{1,2})\s*năm\s*(\d{4})", back_single, re.IGNORECASE)
        if issue_match:
            d = int(issue_match.group(1))
            m = int(issue_match.group(2))
            y = int(issue_match.group(3))
            issue_date = f"{d:02d}/{m:02d}/{y}"

        back_address_raw = _extract_residence_from_lines(back_lines, allow_unlabeled=True)

    # Heuristic validations & fill-ins
    id_evidence = _birth_gender_from_cccd(id_number)
    if id_evidence:
        if not gender:
            gender = id_evidence.get("gender", "")
        if not dob_fmt and id_evidence.get("birth_year"):
            # If DOB is missing, construct birth year fallback
            dob_fmt = f"01/01/{id_evidence['birth_year']}"

    # Build date candidates for card type detection
    date_candidates = []
    if dob_fmt:
        date_candidates.append((dob_fmt.replace("/", ""), dob_fmt))
    if issue_date:
        date_candidates.append((issue_date.replace("/", ""), issue_date))

    card_type = detect_card_type([], date_candidates, back_address_raw or address_raw, id_number=id_number)
    if back_address_raw and (card_type == "CAN_CUOC_MOI" or not address_raw):
        address_raw = back_address_raw
    addr = parse_address_vn(address_raw, card_type)

    if not expiry_date:
        expiry_date = calc_expiry(dob_fmt) if dob_fmt else "Không xác định"

    age = calc_age(dob_fmt) if dob_fmt else None
    expiry_status = get_expiry_status(expiry_date)

    is_valid = bool(id_number and name and dob_fmt)
    error = "" if is_valid else "Không thể trích xuất các trường thông tin bắt buộc (Số CCCD, Họ tên, Ngày sinh) từ ảnh."

    # Compute confidence
    confidence = 0.0
    if id_number: confidence += 0.35
    if name:      confidence += 0.35
    if dob_fmt:   confidence += 0.15
    if gender:    confidence += 0.05
    if address_raw: confidence += 0.10
    confidence = round(max(0.0, min(confidence, 1.0)), 2)

    return {
        "card_type": card_type,
        "address_mode": "new" if card_type == "CAN_CUOC_MOI" else "old",
        "id_number": id_number,
        "old_id": "",
        "name": name.title() if name else "",
        "dob": dob_fmt,
        "gender": gender,
        "nationality": nationality,
        "place_of_origin": place_of_origin,
        "address": {
            "raw": address_raw,
            "detail": addr.get("detail", ""),
            "ward": addr.get("ward", ""),
            "district": addr.get("district", ""),
            "province": addr.get("province", ""),
        },
        "issue_date": issue_date,
        "expiry_date": expiry_date,
        "age": age,
        "is_valid": is_valid,
        "expiry_status": expiry_status,
        "confidence": confidence,
        "warnings": [],
        "conflicts": [],
        "error": error,
        "raw_cleaned": front_text # Store OCR text here
    }
