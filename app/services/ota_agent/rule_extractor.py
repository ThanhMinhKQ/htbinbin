from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional

from bs4 import BeautifulSoup  # type: ignore


SOURCE_MARKERS = {
    "Go2Joy": ("go2joy", "g2j"),
    "Website": ("binbinhotel.ota@gmail.com", "khách sạn bin bin", "khach san bin bin"),
    "Agoda": ("agoda",),
    "Traveloka": ("traveloka",),
    "Trip.com": ("trip.com", "ctrip"),
    "Airbnb": ("airbnb",),
    "Mytour": ("mytour",),
    "Expedia": ("expedia",),
}

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
    "tháng 1": 1, "thang 1": 1,
    "tháng 2": 2, "thang 2": 2,
    "tháng 3": 3, "thang 3": 3,
    "tháng 4": 4, "thang 4": 4,
    "tháng 5": 5, "thang 5": 5,
    "tháng 6": 6, "thang 6": 6,
    "tháng 7": 7, "thang 7": 7,
    "tháng 8": 8, "thang 8": 8,
    "tháng 9": 9, "thang 9": 9,
    "tháng 10": 10, "thang 10": 10,
    "tháng 11": 11, "thang 11": 11,
    "tháng 12": 12, "thang 12": 12,
}


def strip_accents(value: str) -> str:
    text = unicodedata.normalize("NFD", value or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D")


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_key(value: Any) -> str:
    return strip_accents(normalize_space(value)).lower()


def html_to_text(html: str) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "img", "head", "meta", "link", "iframe", "svg", "button", "input"]):
            tag.decompose()
        return normalize_space(soup.get_text(" "))
    except Exception:
        return normalize_space(re.sub(r"<[^>]+>", " ", html))


def parse_amount(value: Any) -> int:
    text = str(value or "")
    text = text.replace("\xa0", " ")
    digits = re.sub(r"\D", "", text)
    return int(digits or 0)


def parse_amount_decimal(value: Any) -> int:
    """Parse amounts like 600,000.00 without turning decimals into extra VND zeros."""
    text = str(value or "").replace("\xa0", " ").strip()
    if not text:
        return 0
    m = re.search(r"\d[\d.,]*", text)
    if not m:
        return 0
    token = m.group(0)
    if re.search(r"[.,]\d{2}$", token) and token.count(".") + token.count(",") >= 1:
        token = token[:-3]
    return parse_amount(token)


def parse_date_value(value: Any) -> Optional[date]:
    text = normalize_space(value)
    if not text:
        return None
    text = re.sub(r"(?i)(mon|tue|wed|thu|fri|sat|sun)(day)?[,]?", " ", text)
    text = normalize_space(text)
    paren = re.search(r"\((\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\)", text)
    if paren:
        text = paren.group(1)
    text = re.sub(r"(?i)(\d{1,2})-([A-Za-z]{3,9})-(\d{4})", r"\1 \2 \3", text)
    ymd = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if ymd:
        return date(int(ymd.group(1)), int(ymd.group(2)), int(ymd.group(3)))
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
    if m:
        month = MONTHS.get(m.group(2).lower())
        if month:
            return date(int(m.group(3)), month, int(m.group(1)))
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", text)
    if m:
        month = MONTHS.get(m.group(1).lower())
        if month:
            return date(int(m.group(3)), month, int(m.group(2)))
    m = re.search(r"(\d{1,2})\s*(?:tháng|thang)\s*(\d{1,2})\s*,?\s*(\d{4})", normalize_key(text))
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def first_match(text: str, patterns: list[str], flags: int = re.IGNORECASE) -> Optional[str]:
    for pattern in patterns:
        m = re.search(pattern, text, flags)
        if m:
            return normalize_space(m.group(1))
    return None


def value_between_labels(text: str, label: str, next_labels: list[str]) -> Optional[str]:
    labels = "|".join(re.escape(item) for item in next_labels)
    pattern = rf"(?:^|\s){re.escape(label)}\s+(.+?)(?=\s+(?:{labels})(?:\s|$)|$)"
    return first_match(text, [pattern])


def clean_field(value: Optional[str], max_length: int = 255) -> Optional[str]:
    if not value:
        return None
    value = normalize_space(value).strip(" :-–—|\t\n\r")
    value = re.split(r"\s{2,}", value)[0].strip()
    if not value:
        return None
    return value[:max_length]


KNOWN_NON_BOOKING_KEYWORDS = (
    "rate plan", "rateplan", "settings", "setting", "setup", "inventory",
    "promotion", "promotions", "promo", "campaign", "newsletter", "digest",
    "report", "analytics", "performance", "insight", "summary",
    "invoice", "receipt", "statement", "payment received",
    "support", "password", "security alert", "login", "verify", "otp", "token", "one time password", "verification code",
    "bao cao", "hieu suat", "thong ke", "phan tich", "khuyen mai",
    "hoa don", "xac minh", "mat khau", "bao mat",
)

BOOKING_INTENT_KEYWORDS = (
    "booking", "reservation", "confirmation", "confirmed", "new booking",
    "cancel", "cancelled", "cancellation", "amendment", "modified",
    "dat phong", "dat cho", "xac nhan", "huy", "nhan phong", "tra phong",
    "don hang", "go2joy", "g2j",
)


def looks_like_known_non_booking(email: dict) -> bool:
    """Return True for known OTA/admin emails that should never spend Gemini quota."""
    subject_key = normalize_key(email.get("subject", ""))
    body_key = normalize_key((email.get("text") or html_to_text(email.get("html") or ""))[:2000])
    haystack = f"{subject_key} {body_key}"
    if not haystack.strip():
        return False
    has_non_booking = any(keyword in haystack for keyword in KNOWN_NON_BOOKING_KEYWORDS)
    if not has_non_booking:
        return False
    if re.search(r"\bnot\s+a\s+(?:booking|reservation|confirmation)\b", haystack):
        return True
    has_booking_intent = any(keyword in haystack for keyword in BOOKING_INTENT_KEYWORDS)
    has_booking_id = bool(re.search(r"\b(?:booking|reservation|confirmation|ma dat phong|ma so dat phong)\b.{0,40}\b[A-Z0-9-]{5,}\b", haystack, re.IGNORECASE))
    return not (has_booking_intent and has_booking_id)


def skip_result(source: str, email: dict, reason: str = "non_booking_email") -> dict:
    return {
        "status": "SKIPPED",
        "reason": reason,
        "booking_source": source,
        "external_id": None,
        "action_type": "SKIP",
        "deposit_amount": 0,
        "extraction_method": "rule_skip",
        "rule_confidence": 100,
        "raw_email_date": email.get("date"),
    }


def detect_source(email: dict) -> Optional[str]:
    haystack = normalize_key(" ".join([email.get("sender", ""), email.get("subject", ""), email.get("html", "")[:1000], email.get("text", "")[:1000]]))
    for source, markers in SOURCE_MARKERS.items():
        if any(normalize_key(marker) in haystack for marker in markers):
            return source
    return None


def detect_cancel_action(subject: str = "", text: str = "", source: str = "") -> bool:
    haystack = normalize_key(f"{source} {subject} {text[:2500]}")
    cancel_patterns = (
        r"\b(?:cancel|canceled|cancelled|cancellation)\b",
        r"\b(?:booking|reservation|itinerary|order)\b.{0,80}\b(?:canceled|cancelled)\b",
        r"\b(?:canceled|cancelled)\b.{0,80}\b(?:booking|reservation|itinerary|order)\b",
        r"\b(?:huy dat phong|huy phong|khach huy|khach huy phong|don bi huy|don phong bi huy|huy don phong|dat phong da bi huy|da bi huy)\b",
        r"\b(?:booking status|tinh trang dat phong)\b.{0,80}\b(?:cancelled|canceled|cancelled by user|khach huy phong|huy phong)\b",
        r"\b(?:cancelled by|cancelled by user|booking cancelled|reservation cancelled)\b",
    )
    return any(re.search(pattern, haystack, re.IGNORECASE) for pattern in cancel_patterns)


def detect_modify_action(subject: str = "", text: str = "") -> bool:
    haystack = normalize_key(f"{subject} {text[:1200]}")
    return any(k in haystack for k in ("modify", "modified", "amend", "amended", "update", "updated", "change", "changed", "thay doi", "cap nhat", "sua doi"))


def action_from_subject(subject: str) -> str:
    if detect_cancel_action(subject):
        return "CANCEL"
    if detect_modify_action(subject):
        return "MODIFY"
    return "NEW"


def extract_external_id_by_source(source: str, subject: str, text: str) -> Optional[str]:
    haystack = normalize_space(f"{subject} {text[:3000]}")
    patterns_by_source = {
        "Go2Joy": [
            r"(?:Mã đặt phòng|Ma dat phong|Booking Number)\s+(?:Loại phòng|Room type)?\s*#?\s*(\d{5,})",
            r"(?:Go2Joy|G2J|đặt phòng|dat phong)[^\d]{0,60}(\d{5,})",
        ],
        "Website": [
            r"#\s*(\d{3,})",
            r"(?:Đơn hàng|Don hang|Order)\s*(?:mới|moi)?\s*#?\s*(\d{3,})",
        ],
        "Agoda": [
            r"Booking ID\s+(?:Mã số đặt phòng\s+)?([A-Z0-9-]{5,})",
            r"Mã Số Đặt Phòng\s*:??\s*([A-Z0-9-]{5,})",
        ],
        "Traveloka": [
            r"Itinerary ID\s+(\d{8,})",
            r"Mã đặt phòng\s+(\d{8,})",
        ],
        "Trip.com": [
            r"Reservation[：:]\s*([A-Z0-9-]{5,})",
            r"booking no\.\s*#?([A-Z0-9-]{5,})#?",
            r"Reservation no\.\s*([A-Z0-9-]{5,})",
            r"orderid=(\d{8,})",
        ],
        "Mytour": [
            r"Mã đơn phòng\s*(H\d+)",
            r"chi tiết đơn hàng\s+(H\d+)",
            r"booking/\d+/detail/\d+\s+truy cập hệ thống.+?(H\d+)",
        ],
        "Expedia": [
            r"Mã đặt phòng\s*:??\s*(\d{6,})",
            r"Reservation ID\s*:??\s*(\d{6,})",
            r"reservationId(?:s)?=(\d{6,})",
        ],
    }
    patterns = patterns_by_source.get(source, []) + [
        r"(?:Booking ID|Booking number|Confirmation number|Reservation ID|Itinerary number|Mã đặt phòng|Ma dat phong|Mã đơn|Ma don|Order ID)\s*:??\s*#?\s*([A-Z0-9-]{5,})",
        r"(?:booking|reservation|confirmation)[^A-Z0-9]{0,30}([A-Z0-9-]{6,})",
    ]
    value = clean_field(first_match(haystack, patterns), 50)
    if source == "Website" and value and not value.upper().startswith("WEB-"):
        return f"WEB-{value}"
    return value


def base_result(source: str, email: dict) -> dict:
    return {
        "action_type": action_from_subject(email.get("subject", "")),
        "booking_source": source,
        "external_id": None,
        "checkin_code": None,
        "guest_name": None,
        "guest_phone": None,
        "hotel_name": None,
        "check_in": None,
        "check_in_time": None,
        "check_out": None,
        "check_out_time": None,
        "room_type": None,
        "num_rooms": 1,
        "num_guests": 1,
        "num_adults": 1,
        "num_children": 0,
        "total_price": 0,
        "currency": "VND",
        "is_prepaid": False,
        "payment_method": None,
        "deposit_amount": 0,
        "notes": None,
        "status": "SUCCESS",
        "extraction_method": "rule",
        "rule_confidence": 0,
        "raw_email_date": email.get("date"),
    }


def is_confident_booking(data: Optional[dict]) -> bool:
    if not isinstance(data, dict) or data.get("status") != "SUCCESS":
        return False
    if str(data.get("action_type", "NEW")).upper() == "CANCEL":
        return bool(data.get("external_id") and data.get("booking_source"))
    required = ["booking_source", "external_id", "guest_name", "check_in", "check_out", "room_type"]
    if any(not data.get(k) for k in required):
        return False
    check_in = parse_date_value(data.get("check_in")) or data.get("check_in")
    check_out = parse_date_value(data.get("check_out")) or data.get("check_out")
    if isinstance(check_in, date) and isinstance(check_out, date) and check_out <= check_in:
        # Cho booking theo giờ: hệ thống integration sẽ normalize thành +1 ngày,
        # nhưng parser chỉ tự tin nếu có giờ check-in/out rõ ràng.
        if not (data.get("check_in_time") and data.get("check_out_time")):
            return False
    if data.get("total_price") is None or int(data.get("total_price") or 0) < 0:
        return False
    if int(data.get("deposit_amount") or 0) != 0:
        return False
    return int(data.get("rule_confidence") or 0) >= 70


class RuleBasedOTAExtractor:
    def extract(self, email: dict) -> Optional[dict]:
        source = detect_source(email)
        if not source:
            return None
        if looks_like_known_non_booking(email):
            return skip_result(source, email)
        parser: Optional[Callable[[dict], Optional[dict]]] = getattr(self, f"extract_{source.lower().replace('.', '').replace(' ', '_')}", None)
        if not parser:
            return None
        data = parser(email)
        if not data:
            return skip_result(source, email) if looks_like_known_non_booking(email) else None
        if data.get("status") == "SKIPPED":
            return data
        data["deposit_amount"] = 0
        return data if is_confident_booking(data) else None

    def _text(self, email: dict) -> str:
        return normalize_space(email.get("text") or html_to_text(email.get("html") or ""))

    def extract_go2joy(self, email: dict) -> Optional[dict]:
        text = self._text(email)
        completed_notice = normalize_key(f"{email.get('subject', '')} {text[:2000]}")
        if any(
            phrase in completed_notice
            for phrase in (
                "thong bao dat phong da hoan tat",
                "dat phong da hoan tat",
                "reservation has been completed",
                "booking has been completed",
            )
        ) and not detect_cancel_action(email.get("subject", ""), text, "Go2Joy"):
            return skip_result("Go2Joy", email, reason="go2joy_completed_notification")

        data = base_result("Go2Joy", email)
        if detect_cancel_action(email.get("subject", ""), text, "Go2Joy"):
            data["action_type"] = "CANCEL"
        labels = [
            "Thời gian nhận phòng ~ trả phòng", "Check-in ~ checkout time",
            "Tình trạng đặt phòng", "Booking status",
            "Tình trạng thanh toán", "Payment status", "Tiền phòng", "Price",
            "Phụ thu", "Extra fee", "Số tiền thanh toán", "Payment amount",
            "Tiền sản phẩm", "Product amount", "Giảm giá/Khuyến mãi", "Discount/ Promotion",
            "Loại đặt phòng", "Booking type", "Nội dung thay đổi", "English below", "Cảm ơn", "Thank you",
        ]
        booking_id = first_match(text, [
            r"(?:Mã đặt phòng|Booking Number)\s+(?:Loại phòng|Room type)\s+(\d{5,})",
            r"(?:Mã đặt phòng|Booking Number|đặt phòng mới -)\s*#?\s*(\d{5,})",
        ])
        booking_id = extract_external_id_by_source("Go2Joy", email.get("subject", ""), text)
        stay_text = value_between_labels(text, "Thời gian nhận phòng ~ trả phòng", labels) or value_between_labels(text, "Check-in ~ checkout time", labels) or ""
        stay_source = stay_text if re.search(r"\d{1,2}:\d{2}.*\d{1,2}/\d{1,2}/\d{4}", stay_text) else text
        stay = re.search(r"(\d{1,2}:\d{2}),\s*(\d{1,2}/\d{1,2}/\d{4})\s*~\s*(\d{1,2}:\d{2}),\s*(\d{1,2}/\d{1,2}/\d{4})", stay_source)
        payment = value_between_labels(text, "Tình trạng thanh toán", labels) or value_between_labels(text, "Payment status", labels)
        room_price = parse_amount(value_between_labels(text, "Tiền phòng", labels) or value_between_labels(text, "Price", labels) or first_match(text, [r"(?:Tiền phòng|Price)\s+([\d.,]+)\s*(?:VND|VNĐ|đ|₫)?"]))
        payment_amount = parse_amount(value_between_labels(text, "Số tiền thanh toán", labels) or value_between_labels(text, "Payment amount", labels) or first_match(text, [r"(?:Số tiền thanh toán|Payment amount)\s+([\d.,]+)\s*(?:VND|VNĐ|đ|₫)?"]))
        guest_count = int(first_match(text, [r"(?:Số khách|No\. of Guests|Guests?|Occupancy|Số người)\s*:?\s*(\d+)"]) or 1)

        def clean_go2joy_guest(value: Optional[str]) -> Optional[str]:
            guest = clean_field(value)
            if not guest:
                return None
            key = normalize_key(guest)
            body_markers = (
                "ma dat phong", "booking number", "loai phong", "room type",
                "loai dat phong", "booking type", "thoi gian nhan phong",
                "check-in", "tien phong", "price", "tinh trang thanh toan",
                "payment status", "english below",
            )
            if len(guest) > 80 or any(marker in key for marker in body_markers):
                return None
            return guest

        guest_name = (
            clean_go2joy_guest(value_between_labels(text, "Tên khách", ["Mã đặt phòng", "Booking Number"]))
            or clean_go2joy_guest(value_between_labels(text, "Guest's name", ["Booking Number", "Mã đặt phòng"]))
        )
        data.update({
            "external_id": booking_id,
            "hotel_name": clean_field(first_match(text, [r"(?:Quý khách sạn|Dear Hotel)\s+(.+?)(?:,| You have| Khách sạn vừa nhận|$)"])),
            "guest_name": guest_name or "Go2Joy Guest",
            "room_type": clean_field(first_match(text, [r"(?:Mã đặt phòng|Booking Number)\s+(?:Loại phòng|Room type)\s+\d+\s+(.+?)\s+(?:Loại đặt phòng|Booking type)"])),
            "num_rooms": int(first_match(text, [r"(?:Số phòng|No\. of Rooms|Room\(s\)|Rooms?)\s*:?\s*([0-9]+)"]) or 1),
            "num_guests": guest_count,
            "num_adults": guest_count,
            "check_in": parse_date_value(stay.group(2)) if stay else None,
            "check_in_time": stay.group(1) if stay else None,
            "check_out": parse_date_value(stay.group(4)) if stay else None,
            "check_out_time": stay.group(3) if stay else None,
            "total_price": room_price or payment_amount,
            "is_prepaid": bool(payment and any(k in normalize_key(payment) for k in ("da thanh toan", "paid"))),
            "payment_method": payment,
            "rule_confidence": 96,
        })
        return data

    def extract_website(self, email: dict) -> Optional[dict]:
        text = self._text(email)
        subject = email.get("subject", "")
        data = base_result("Website", email)
        order_no = first_match(subject + " " + text[:300], [r"#\s*(\d{3,})", r"(?:Đơn hàng|Don hang|Order)\s*(?:mới|moi)?\s*#?\s*(\d{3,})"])
        product_line = first_match(text, [r"\]\s*\([^)]*\)\s+(.+?\([^)]*\))\s+X\s+(\d+)", r"(?:^|\s)([^\n]+?\([A-Z]\d+\))\s+X\s+\d+\s*="])
        room_qty = first_match(text, [r"\]\s*\([^)]*\)\s+.+?\([^)]*\)\s+X\s+(\d+)", r"(?:^|\s)[^\n]+?\([A-Z]\d+\)\s+X\s+(\d+)\s*="])
        guest_count = int(first_match(text, [r"(?:Số khách|No\. of Guests|Guests?|Số người)\s*:?\s*(\d+)"]) or 1)
        stay = re.search(r"(\d{1,2}:\d{2}),\s*([\d/\-.]{8,10})\s*~\s*(\d{1,2}:\d{2}),\s*([\d/\-.]{8,10})", text)
        room_type = clean_field(product_line) or clean_field(first_match(text, [r"(?:Loại phòng|Room type|Room)\s*:?\s*(.+?)(?:Ngày nhận|Check-in|Ngày trả|Check-out|$)"]))
        branch_code = first_match(room_type or "", [r"\(([A-Z]\d+)\)"])
        guest_block = first_match(text, [r"ĐỊA CHỈ THANH TOÁN\s+(.+?)(?:Chúc mừng|Khách sạn Bin Bin|$)"])
        guest_name = first_match(text, [r"Bạn vừa nhận được đơn hàng từ\s+(.+?)\.\s+Đơn hàng", r"Khách hàng\s*:?\s*(.+?)(?:Số điện thoại|Phone|Khách sạn|$)"])
        if not guest_name and guest_block:
            guest_name = first_match(guest_block, [r"^\s*(.+?)(?:\s+\+?0\d{8,10}|\s+[\w.+-]+@[\w.-]+|$)"])
        phone = first_match(guest_block or text, [r"(?:Số điện thoại|Phone)\s*:?\s*(\+?0\d{8,10})", r"(\+?0\d{8,10})"])
        pay_text = first_match(text, [r"(?:Phương thức thanh toán|Payment method)\s*:?\s*(.+?)(?:Tổng cộng|Total|$)", r"(?:Thanh toán|Payment)\s*:?\s*(.+?)(?:Tổng cộng|Total|$)"])
        pay_key = normalize_key(pay_text or "")
        data.update({
            "external_id": f"WEB-{order_no}" if order_no and not str(order_no).upper().startswith("WEB-") else order_no,
            "guest_name": clean_field(guest_name),
            "guest_phone": clean_field(phone, 50),
            "hotel_name": f"Bin Bin Hotel {branch_code}" if branch_code else clean_field(first_match(text, [r"(?:Khách sạn|Hotel|Property)\s*:?\s*(.+?)(?:Loại phòng|Room|Ngày nhận|Check-in|$)"])),
            "room_type": room_type,
            "num_rooms": int(room_qty or 1),
            "num_guests": guest_count,
            "num_adults": guest_count,
            "check_in": parse_date_value(stay.group(2)) if stay else parse_date_value(first_match(text, [r"(?:Start|Ngày nhận phòng|Check-in|Nhận phòng)\s*:?\s*([\d/\-.]{8,10}|\d{1,2}\s+\w+\s+\d{4})"])),
            "check_in_time": stay.group(1) if stay else None,
            "check_out": parse_date_value(stay.group(4)) if stay else parse_date_value(first_match(text, [r"(?:End|Ngày trả phòng|Check-out|Trả phòng)\s*:?\s*([\d/\-.]{8,10}|\d{1,2}\s+\w+\s+\d{4})"])),
            "check_out_time": stay.group(3) if stay else None,
            "total_price": parse_amount(first_match(text, [r"(?:Tổng cộng|Tổng tiền|Total)\s*:?\s*([\d.,]+)\s*(?:VND|VNĐ|đ|₫)?"])),
            "is_prepaid": bool(pay_text and any(k in pay_key for k in ("da thanh toan", "paid online", "paid")) and "chua" not in pay_key and "tra tien mat" not in pay_key),
            "payment_method": pay_text,
            "rule_confidence": 94,
        })
        return data

    def extract_agoda(self, email: dict) -> Optional[dict]:
        text = self._text(email)
        data = base_result("Agoda", email)
        if detect_cancel_action(email.get("subject", ""), text, "Agoda"):
            data["action_type"] = "CANCEL"
        subject_id = first_match(email.get("subject", ""), [r"Booking ID\s+([A-Z0-9-]{5,})"])
        booking_id = subject_id or extract_external_id_by_source("Agoda", email.get("subject", ""), text)
        first = clean_field(first_match(text, [r"Customer First Name\s+Tên Khách Hàng\s+(.+?)\s+Customer Last Name", r"Tên Khách Hàng\s*:??\s*(.+?)\s+Họ Khách Hàng"]))
        last = clean_field(first_match(text, [r"Customer Last Name\s+Họ Khách Hàng\s+(.+?)\s+Country of Residence", r"Họ Khách Hàng\s*:??\s*(.+?)\s+Thành Phố"]))
        guest = normalize_space(" ".join(x for x in (first, last) if x)) or None
        prepaid = any(k in normalize_key(text) for k in ("tra truoc", "prepaid", "pre-paid"))
        special_request = clean_field(first_match(text, [
            r"Special Requests\s+Yêu cầu đặc biệt\s*\([^)]*\)\s*(.+?)\s+Cancellation Policy",
            r"Special Requests\s+Yêu cầu đặc biệt\s*(.+?)\s+Cancellation Policy",
            r"Special Requests\s*(.+?)\s+Cancellation Policy",
        ]), 1000)
        if special_request and normalize_key(special_request).startswith("all special requests"):
            special_request = clean_field(first_match(special_request, [r"\)\s*(.+)$"]), 1000)
        room_match = re.search(r"Room Type\s+Loại Phòng\s+No\. of Rooms\s+Số phòng\s+Occupancy\s+Số người\s+No\. of Extra Bed\s+Số Giường Thêm\s*:?\s*(.+?)\s+(\d+)\s+(\d+)\s+Adult", text, re.IGNORECASE)
        room_type = clean_field(room_match.group(1) if room_match else first_match(text, [r"Room Type\s+Loại Phòng.+?:\s*(.+?)\s+Tên chính sách giá", r"Loại Phòng\s*:??\s*(.+?)\s+(?:Free WiFi|Số Phòng)"]))
        num_rooms = int(room_match.group(2) if room_match else first_match(text, [r"(?:No\. of Rooms|Số phòng|Số Phòng|Rooms?)\s*:?\s*(\d+)"]) or 1)
        num_adults = int(room_match.group(3) if room_match else first_match(text, [r"(?:Occupancy|Số người|Số Người Lớn)\s*:?\s*(\d+)", r"(\d+)\s+Adults?"]) or 1)
        num_children = int(first_match(text, [r"Số Trẻ Em\s*:??\s*(\d+)"]) or 0)
        data.update({
            "external_id": booking_id,
            "hotel_name": clean_field(first_match(text, [r"Booking confirmation\s+Xác nhận đặt phòng\s+(.+?)\s+\(Property ID", r"(.+?)\s+\(Property ID\s+\d+\)", r"Khách Sạn\s*:??\s*(.+?)\s+Loại Phòng"])),
            "guest_name": clean_field(guest),
            "check_in": parse_date_value(first_match(text, [r"Check-in\s+Nhận phòng\s+([^\(]+)", r"Ngày Đến\s*:??\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})"])),
            "check_out": parse_date_value(first_match(text, [r"Check-out\s+Trả phòng\s+([^\(]+)", r"Ngày Đi\s*:??\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})"])),
            "room_type": room_type,
            "num_rooms": num_rooms,
            "num_guests": num_adults + num_children,
            "num_adults": num_adults,
            "num_children": num_children,
            "total_price": parse_amount_decimal(first_match(text, [r"Net rate \(incl\. taxes & fees\)\s+Giá thực tế \(bao gồm thuế & phí\)\s+(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)", r"Net rate.*?(?:VND|VNĐ|đ|₫)\s*([\d.,]+)"])),
            "is_prepaid": prepaid or True,
            "payment_method": "Agoda prepaid/net rate" if prepaid else "Agoda net rate",
            "notes": special_request or clean_field(first_match(text, [r"Ghi Chú\s*:??\s*(.+?)(?:\s+Bộ Phận Hỗ Trợ|\s+Đặt phòng thông minh|$)"]), 1000),
            "rule_confidence": 94,
        })
        return data

    def extract_traveloka(self, email: dict) -> Optional[dict]:
        text = self._text(email)
        data = base_result("Traveloka", email)
        if detect_cancel_action(email.get("subject", ""), text, "Traveloka"):
            data["action_type"] = "CANCEL"
        first = clean_field(first_match(text, [r"Customer First Name\s+(.+?)\s+Customer Last Name", r"Tên khách\s+(.+?)\s+Họ khách"]))
        last = clean_field(first_match(text, [r"Customer Last Name\s+(.+?)\s+Guest Contact", r"Customer Last Name\s+(.+?)\s+Guest Email", r"Họ khách\s+(.+?)\s+Email khách"]))
        guest = normalize_space(" ".join(x for x in (first, last) if x)) or None
        room_match = re.search(r"\(\s*(\d+)\s*[×xX]\s*\)\s*(.+?)\s+(\d+)\s+Adult\(s\)(?:\s+(\d+)\s+Child)?", text, re.IGNORECASE)
        if not room_match:
            room_match = re.search(r"\(\s*(\d+)\s*[×xX]\s*\)\s*(.+?)\s+(\d+)\s+Người lớn(?:\s+(\d+)\s+Trẻ em)?", text, re.IGNORECASE)
        special_request = clean_field(first_match(text, [r"Special Request\s+(.+?)\s+Cancellation policy", r"Yêu cầu đặc biệt\s+(.+?)\s+Chính sách huỷ phòng", r"Yêu cầu đặc biệt\s+(.+?)\s+Chính sách hủy phòng"]), 1000)
        traveloka_email = first_match(text, [
            r"Guest Email\s+([\w.+-]+@\s*(?:<wbr>\s*)?[\w.-]+(?:\s+[\w.-]+)?)\s+Check-in",
            r"Email khách\s+([\w.+-]+@\s*(?:<wbr>\s*)?[\w.-]+(?:\s+[\w.-]+)?)\s+Check-in",
            r"Email khách\s+([\w.+-]+)\s+hotel\.traveloka\.com\s+Check-in",
        ])
        if traveloka_email:
            traveloka_email = normalize_space(traveloka_email).replace(" ", "")
            if "@" not in traveloka_email and traveloka_email.endswith("-"):
                traveloka_email = None
            elif "@" not in traveloka_email:
                traveloka_email = f"{traveloka_email}@hotel.traveloka.com"
        if special_request in ("-", "—"):
            special_request = None
        prepaid = any(k in normalize_key(text) for k in ("prepaid", "tra truoc", "dat va thanh toan boi"))
        data.update({
            "external_id": extract_external_id_by_source("Traveloka", email.get("subject", ""), text),
            "hotel_name": clean_field(first_match(text, [r"New Booking\s+(?:Prepaid\s+)?(.+?)\s+City:", r"CANCELLATION\s+(?:Prepaid\s+)?(.+?)\s+City:", r"Đặt chỗ mới\s+(?:Trả trước\s+)?(.+?)\s+Thành phố:", r"(.+?\(\d+\))\s+City:", r"(.+?\(\d+\))\s+Thành phố:"])),
            "guest_name": clean_field(guest),
            "guest_phone": clean_field(first_match(text, [r"Guest Contact\s+(\+?\d[\d .-]{7,})", r"Liên hệ khách\s+(\+?\d[\d .-]{7,})"]), 50),
            "guest_email": clean_field(traveloka_email, 255),
            "check_in": parse_date_value(first_match(text, [r"Check-in\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})"])),
            "check_out": parse_date_value(first_match(text, [r"Check-out\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})"])),
            "room_type": clean_field(room_match.group(2) if room_match else first_match(text, [r"Room Information\s+(.+?)\s+Guest Information", r"Thông tin phòng\s+(.+?)\s+Thông tin khách"])),
            "num_rooms": int(room_match.group(1) if room_match else first_match(text, [r"\(\s*(\d+)\s*[×xX]\s*\)"]) or 1),
            "num_adults": int(room_match.group(3) if room_match else first_match(text, [r"(\d+)\s+Adult\(s\)", r"(\d+)\s+Người lớn"]) or 1),
            "num_children": int((room_match.group(4) if room_match and room_match.group(4) else None) or first_match(text, [r"(\d+)\s+Child", r"(\d+)\s+Trẻ em"]) or 0),
            "total_price": parse_amount_decimal(first_match(text, [r"Total you will receive\s+(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)", r"Tổng tiền bạn sẽ nhận được\s+(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)", r"Refunded Amount\s+(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)", r"Total Amount\s+(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)", r"Subtotal Rates\s+(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)"])),
            "is_prepaid": prepaid,
            "payment_method": "Traveloka prepaid" if prepaid else None,
            "notes": special_request,
            "rule_confidence": 94,
        })
        data["num_guests"] = int(data.get("num_adults") or 0) + int(data.get("num_children") or 0)
        return data

    def extract_tripcom(self, email: dict) -> Optional[dict]:
        subject = email.get("subject", "")
        text = self._text(email)
        # Bỏ qua email support/cài đặt giá/rate plan, không phải reservation.
        if not re.search(r"booking|reservation", subject, re.IGNORECASE):
            return skip_result("Trip.com", email) if looks_like_known_non_booking(email) else None
        data = base_result("Trip.com", email)
        if detect_cancel_action(subject, text, "Trip.com"):
            data["action_type"] = "CANCEL"
        if "Reservation：" in text or "Total amount：" in text:
            data.update({
                "external_id": extract_external_id_by_source("Trip.com", subject, text),
                "guest_name": clean_field(first_match(text, [r"Guest name[：:]\s*(.+?)\s+Occupancy[：:]"])),
                "hotel_name": clean_field(first_match(text, [r"^\s*(.+?)\s+Dear Partner", r"for\s+(.+?)\s+Dear Partner"])),
                "check_in": parse_date_value(first_match(text, [r"Check-in date[：:]\s*([\d/\-.]{8,10})"])),
                "check_out": parse_date_value(first_match(text, [r"Check-out date[：:]\s*([\d/\-.]{8,10})"])),
                "room_type": clean_field(first_match(text, [r"Room type[：:]\s*(.+?)\s+Room\(s\)[：:]"])),
                "total_price": parse_amount_decimal(first_match(text, [r"Total amount[：:]\s*(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)"])),
                "is_prepaid": "prepay" in normalize_key(text) or "prepaid" in normalize_key(text),
                "payment_method": "Trip.com prepaid" if "prepay" in normalize_key(text) or "prepaid" in normalize_key(text) else None,
                "rule_confidence": 92,
            })
            return data
        room_count = int(first_match(text, [r"Room Type:?\s*.+?\|\s*(\d+)\s+room", r"Room rate\s+(\d+)\s+room\(s\)"]) or 1)
        adults = int(first_match(text, [r"Guests \(estimated\):\s*(\d+)\s+adult", r"This rate is for\s+(\d+)\s+adults?"]) or 1)
        children = int(first_match(text, [r"Guests \(estimated\):\s*\d+\s+adults?\s+(\d+)\s+child"]) or 0)
        special_request = clean_field(first_match(text, [r"Special requests\s+Other requests:\s+(.+?)\s+Cancellation Policy", r"Other requests:\s+(.+?)\s+Cancellation Policy"]), 1000)
        room_type = clean_field(first_match(text, [r"Room Type:?\s*(.+?)\s+\|\s+\d+\s+room"]))
        data.update({
            "external_id": extract_external_id_by_source("Trip.com", subject, text),
            "hotel_name": clean_field(first_match(text, [r"Please update the reservation information in your property management system \(PMS\) as soon as possible\.\s+(.+?)\s+Guest Name:?", r"Confirmed by\s+Ctrip\s+Reply method\s+email\s+.+?\s+(.+?)\s+Guest Name:", r"(?:^|\s)Hotel\s+(.+?)\s+Guest Name"])),
            "guest_name": clean_field(first_match(text, [r"Guest Name:?\s*(.+?)\s+(?:Booking Amount|Room Type:)"])),
            "room_type": room_type,
            "num_rooms": room_count,
            "num_adults": adults,
            "num_children": children,
            "check_in": parse_date_value(first_match(text, [r"Staying period:?\s*(.+?)\s+-\s+.+?\s+\|"])),
            "check_out": parse_date_value(first_match(text, [r"Staying period:?\s+.+?\s+-\s+(.+?)\s+\|"])),
            "check_in_time": clean_field(first_match(text, [r"Arrival time:?\s*(\d{1,2}:\d{2})"]), 5),
            "total_price": parse_amount_decimal(first_match(text, [r"Booking Amount\s+(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)", r"Your payout\s+(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)", r"Final room rate \(incl\. taxes and fees\)\s*([\d.,]+)"])),
            "is_prepaid": "prepaid" in normalize_key(text),
            "payment_method": "Trip.com net rate/prepaid" if "prepaid" in normalize_key(text) else None,
            "notes": special_request,
            "rule_confidence": 94,
        })
        data["num_guests"] = int(data.get("num_adults") or 0) + int(data.get("num_children") or 0)
        return data

    def extract_airbnb(self, email: dict) -> Optional[dict]:
        return self._extract_generic(
            email, "Airbnb",
            price_patterns=[r"(?:Bạn kiếm được|Ban kiem duoc|You earn|Host payout)\s*:?\s*(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)"],
            confidence=84,
        )

    def extract_mytour(self, email: dict) -> Optional[dict]:
        text = self._text(email)
        data = base_result("Mytour", email)
        if detect_cancel_action(email.get("subject", ""), text, "Mytour"):
            data["action_type"] = "CANCEL"
        special_request = clean_field(first_match(text, [r"Yêu cầu đặc biệt\s+•\s*(.+?)\s+Chính sách hoàn hủy", r"Yêu cầu khác:\s*(.+?)\s+Chính sách hoàn hủy"]), 1000)
        if special_request and normalize_key(special_request) in ("yeu cau khac: .null", ".null", "null"):
            special_request = None
        num_adults = int(first_match(text, [r"Tổng số khách\s+(\d+)\s+người lớn", r"Số khách tiêu chuẩn\s+(\d+)\s+người lớn"]) or 1)
        num_children = int(first_match(text, [r"Tổng số khách\s+\d+\s+người lớn\s+(\d+)\s+trẻ em"]) or 0)
        data.update({
            "external_id": extract_external_id_by_source("Mytour", email.get("subject", ""), text),
            "hotel_name": clean_field(first_match(text, [r"Kính chào\s+(.+?),", r"Tên KS\s+(.+?)\s+Địa chỉ"])),
            "guest_name": clean_field(first_match(text, [r"Họ tên\s+(.+?)\s+SĐT"])),
            "guest_phone": clean_field(first_match(text, [r"SĐT\s+(\+?\d[\d .-]{7,})"]), 50),
            "check_in": parse_date_value(first_match(text, [r"(\d{2}-\d{2}-\d{4})\s+Check-in"])),
            "check_out": parse_date_value(first_match(text, [r"Check-in\s+(\d{2}-\d{2}-\d{4})\s+Check-out"])),
            "room_type": clean_field(first_match(text, [r"Địa chỉ\s+(.+?)\s+\|\s+\d+\s+phòng", r"(Deluxe Room|Superior Room|Standard Room|Suite Room|Family Room|.+?Room)\s+\|\s+\d+\s+phòng"])),
            "num_rooms": int(first_match(text, [r"\|\s+(\d+)\s+phòng"]) or 1),
            "num_adults": num_adults,
            "num_children": num_children,
            "total_price": parse_amount(first_match(text, [r"Tổng tiền trả khách sạn\s+([\d.]+)", r"Tổng\s+([\d.]+)\s+Phụ thu dịch vụ khác"])),
            "is_prepaid": any(k in normalize_key(text) for k in ("da duoc thanh toan", "dat va thanh toan boi", "thanh toan boi")),
            "payment_method": "Mytour prepaid/VNTravel" if any(k in normalize_key(text) for k in ("da duoc thanh toan", "dat va thanh toan boi", "thanh toan boi")) else None,
            "notes": special_request,
            "rule_confidence": 94,
        })
        data["num_guests"] = int(data.get("num_adults") or 0) + int(data.get("num_children") or 0)
        return data

    def extract_expedia(self, email: dict) -> Optional[dict]:
        text = self._text(email)
        data = base_result("Expedia", email)
        if detect_cancel_action(email.get("subject", ""), text, "Expedia"):
            data["action_type"] = "CANCEL"
        prepaid = any(k in normalize_key(text) for k in ("thanh toan truoc", "prepaid", "pre-paid", "expedia thu khoan thanh toan", "expedia collects payment"))
        stay_match = re.search(
            r"Nhận phòng\s+Trả phòng\s+Người lớn\s+Trẻ/Tuổi\s+Đêm phòng\s+Số xác nhận khách sạn\s+([\d/\-.]{8,10})\s+([\d/\-.]{8,10})\s+(\d+)\s+(\d+)\s+(\d+)",
            text,
            re.IGNORECASE,
        )
        if not stay_match:
            stay_match = re.search(
                r"Check-In\s+Check-Out\s+Adults\s+Kids/Ages\s+Room Nights\s+Hotel Conf\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})\s+(\d+)\s+(\d+)\s+(\d+)",
                text,
                re.IGNORECASE,
            )
        special_request = clean_field(first_match(text, [
            r"Khách gửi yêu cầu cho khách sạn\s+(.+?)\s+Giá linh hoạt Expedia",
            r"Yêu cầu đặc biệt\s+(.+?)\s+Giá linh hoạt Expedia",
            r"Customer entered request to hotel\s+(.+?)\s+!LAST-MINUTE BOOKING",
            r"Customer entered request to hotel\s+(.+?)\s+Expedia Flexible Rate",
            r"Special Request\s+(.+?)\s+Customer entered request to hotel",
        ]), 1000)
        data.update({
            "external_id": extract_external_id_by_source("Expedia", email.get("subject", ""), text),
            "guest_name": clean_field(first_match(text, [r"Khách\s*:??\s*([^:]+?)\s+Đặt vào", r"Khách\s*:??\s*([A-ZÀ-Ỹ][^:]+?)\s+Đặt vào", r"Guest\s*:??\s*([^:]+?)\s+Booked", r"Guest\s*:??\s*([^:]+?)\s+Guest Email", r"Guest\s*:??\s*([^:]+?)\s+Room Type"])),
            "guest_email": normalize_space(clean_field(first_match(text, [r"Email khách\s*:??\s*([\w.+-]+@\s*(?:<wbr>\s*)?[\w.-]+(?:\s+[\w.-]+)?)", r"Guest Email\s*:??\s*([\w.+-]+@\s*(?:<wbr>\s*)?[\w.-]+(?:\s+[\w.-]+)?)"]), 255)).replace(" ", ""),
            "hotel_name": clean_field(first_match(text, [r"Đặt phòng mới\s+(.+?)\s+Ho Chi Minh City", r"New Reservation\s+(.+?)\s+Ho Chi Minh City", r"EAN logo\s+(.+?)\s+Ho Chi Minh City"])),
            "room_type": clean_field(first_match(text, [r"Tên loại phòng\s*:??\s*(.+?)\s+Deluxe Suite", r"Room Type Name\s*:??\s*(.+?)\s+Pricing Model", r"Mã loại phòng\s*:??\s*(.+?)\s+Tên loại phòng", r"Room Type Code\s*:??\s*(.+?)\s+Room Type Name"])),
            "num_rooms": 1,
            "num_adults": int(stay_match.group(3) if stay_match else first_match(text, [r"Người lớn\s+Trẻ/Tuổi\s+Đêm phòng\s+[^\d]*(\d+)"]) or 1),
            "num_children": int(stay_match.group(4) if stay_match else first_match(text, [r"Trẻ/Tuổi\s+Đêm phòng\s+[^\d]*\d+\s+(\d+)"]) or 0),
            "check_in": parse_date_value(stay_match.group(1) if stay_match else first_match(text, [r"Nhận phòng\s+Trả phòng.+?\s+([\d/\-.]{8,10})", r"Check-In\s+Check-Out.+?\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})"])),
            "check_out": parse_date_value(stay_match.group(2) if stay_match else first_match(text, [r"Nhận phòng\s+Trả phòng.+?\s+[\d/\-.]{8,10}\s+([\d/\-.]{8,10})", r"Check-In\s+Check-Out.+?\s+[A-Za-z]+\s+\d{1,2},?\s+\d{4}\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})"])),
            "total_price": parse_amount_decimal(first_match(text, [r"Khoản tiền thu từ Expedia Group\s*:??\s*([\d.,]+)\s*VND", r"Amount to Charge Expedia Group\s*:??\s*([\d.,]+)\s*VND", r"Tổng khoản tiền đặt phòng\s*:??\s*([\d.,]+)\s*VND", r"Total Booking Amount\s*:??\s*([\d.,]+)\s*VND"])),
            "is_prepaid": prepaid,
            "payment_method": "Expedia prepaid/collect" if prepaid else None,
            "notes": special_request,
            "rule_confidence": 94,
        })
        data["num_guests"] = int(data.get("num_adults") or 0) + int(data.get("num_children") or 0)
        return data

    def _extract_generic(
        self,
        email: dict,
        source: str,
        external_patterns: Optional[list[str]] = None,
        price_patterns: Optional[list[str]] = None,
        confidence: int = 80,
    ) -> Optional[dict]:
        text = self._text(email)
        subject = email.get("subject", "")
        data = base_result(source, email)
        if detect_cancel_action(subject, text, source):
            data["action_type"] = "CANCEL"
        external_patterns = external_patterns or [
            r"(?:Booking ID|Booking number|Confirmation number|Reservation ID|Itinerary number|Mã đặt phòng|Mã đơn|Order ID)\s*:?\s*#?\s*([A-Z0-9-]{5,})",
            r"(?:booking|reservation|confirmation)[^A-Z0-9]{0,20}([A-Z0-9-]{6,})",
        ]
        price_patterns = price_patterns or [
            r"(?:Total amount|Total price|Total booking amount|Tổng cộng|Tổng tiền|Grand total)\s*:?\s*(?:VND|VNĐ|đ|₫|USD)?\s*([\d.,]+)",
            r"(?:Net amount|Net rate|Amount due|Payable amount)\s*:?\s*(?:VND|VNĐ|đ|₫|USD)?\s*([\d.,]+)",
        ]
        stay = re.search(r"(\d{1,2}:\d{2}),\s*([\d/\-.]{8,10})\s*~\s*(\d{1,2}:\d{2}),\s*([\d/\-.]{8,10})", text)
        guest_count = int(first_match(text, [r"(?:Số khách|No\. of Guests|Guests?|Occupancy|Số người)\s*:?\s*(\d+)"]) or 1)
        data.update({
            "external_id": extract_external_id_by_source(source, subject, text) or clean_field(first_match(subject + " " + text[:1000], external_patterns), 50),
            "guest_name": clean_field(first_match(text, [r"(?:Guest name|Guest|Customer name|Primary guest|Tên khách|Khách hàng)\s*:?\s*(.+?)(?:Booking|Confirmation|Property|Hotel|Room|Check-in|Số điện thoại|Phone|$)"])),
            "guest_phone": clean_field(first_match(text, [r"(?:Phone|Mobile|Số điện thoại|Điện thoại)\s*:?\s*(\+?\d[\d .-]{7,})"]), 50),
            "hotel_name": clean_field(first_match(text, [r"(?:Property|Hotel|Accommodation|Khách sạn|Tên khách sạn)\s*:?\s*(.+?)(?:Room|Guest|Check-in|Check in|Địa chỉ|Address|$)"])),
            "room_type": clean_field(first_match(text, [r"(?:Room type|Room|Loại phòng)\s*:?\s*(.+?)(?:Check-in|Check in|Check-out|Guest|Số khách|Guests|Số phòng|No\. of Rooms|Rooms?|$)"])),
            "num_rooms": int(first_match(text, [r"(?:Số phòng|No\. of Rooms|Room\(s\)|Rooms?)\s*:?\s*(\d+)"]) or 1),
            "num_guests": guest_count,
            "num_adults": guest_count,
            "check_in": parse_date_value(stay.group(2)) if stay else parse_date_value(first_match(text, [r"(?:Check-in|Check in|Ngày nhận phòng|Nhận phòng)\s*:?\s*([\d/\-.]{8,10}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})"])),
            "check_in_time": stay.group(1) if stay else None,
            "check_out": parse_date_value(stay.group(4)) if stay else parse_date_value(first_match(text, [r"(?:Check-out|Check out|Ngày trả phòng|Trả phòng)\s*:?\s*([\d/\-.]{8,10}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})"])),
            "check_out_time": stay.group(3) if stay else None,
            "total_price": parse_amount(first_match(text, price_patterns)),
            "is_prepaid": any(k in normalize_key(text) for k in ("prepaid", "paid online", "da thanh toan", "already paid")) and "chua thanh toan" not in normalize_key(text),
            "rule_confidence": confidence,
        })
        if not data.get("check_out") and data.get("check_in"):
            data["check_out"] = data["check_in"] + timedelta(days=1)
        return data
