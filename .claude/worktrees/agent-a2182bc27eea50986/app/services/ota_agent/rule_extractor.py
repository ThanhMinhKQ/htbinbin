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
    "support", "password", "security alert", "login", "verify",
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


def action_from_subject(subject: str) -> str:
    low = normalize_key(subject)
    if any(k in low for k in ("cancel", "huy", "huỷ", "hủy", "cancelled", "cancellation")):
        return "CANCEL"
    if any(k in low for k in ("modify", "modified", "amend", "update", "thay doi", "cap nhat")):
        return "MODIFY"
    return "NEW"


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
        data = base_result("Go2Joy", email)
        booking_id = first_match(text, [r"(?:Mã đặt phòng|Booking Number|đặt phòng mới -)\s*#?\s*(\d{5,})"])
        if not booking_id:
            booking_id = first_match(email.get("subject", ""), [r"(\d{6,})"])
        stay = re.search(r"(\d{1,2}:\d{2}),\s*(\d{1,2}/\d{1,2}/\d{4})\s*~\s*(\d{1,2}:\d{2}),\s*(\d{1,2}/\d{1,2}/\d{4})", text)
        payment = first_match(text, [r"(?:Tình trạng thanh toán|Payment status)\s+(.+?)(?:Cảm ơn|Thank you|$)"])
        data.update({
            "external_id": booking_id,
            "hotel_name": clean_field(first_match(text, [r"(?:Quý khách sạn|Dear Hotel)\s+([^,]+?)(?:,| You have| Khách sạn|$)"])),
            "guest_name": clean_field(first_match(text, [r"(?:Tên khách|Guest's name)\s+(.+?)\s+(?:Mã đặt phòng|Booking Number)"])) or "Go2Joy Guest",
            "room_type": clean_field(first_match(text, [r"(?:Mã đặt phòng|Booking Number)\s+(?:Loại phòng|Room type)\s+\d+\s+(.+?)\s+(?:Loại đặt phòng|Booking type)", r"(?:Loại phòng|Room type)\s+(.+?)\s+(?:Loại đặt phòng|Booking type)"])),
            "num_rooms": int(first_match(text, [r"(?:Số phòng|No\. of Rooms|Room\(s\)|Rooms?)\s*:?[\s]*([0-9]+)"]) or 1),
            "check_in": parse_date_value(stay.group(2)) if stay else None,
            "check_in_time": stay.group(1) if stay else None,
            "check_out": parse_date_value(stay.group(4)) if stay else None,
            "check_out_time": stay.group(3) if stay else None,
            "total_price": parse_amount(first_match(text, [r"(?:Tiền phòng|Price)\s+([\d.,]+)\s*VND"])),
            "is_prepaid": True if not payment else any(k in normalize_key(payment) for k in ("da thanh toan", "paid")),
            "payment_method": payment,
            "rule_confidence": 95,
        })
        return data

    def extract_website(self, email: dict) -> Optional[dict]:
        text = self._text(email)
        subject = email.get("subject", "")
        data = base_result("Website", email)
        order_no = first_match(subject + " " + text[:300], [r"#\s*(\d{3,})", r"(?:Đơn hàng|Don hang|Order)\s*(?:mới|moi)?\s*#?\s*(\d{3,})"])
        pay_text = first_match(text, [r"(?:Thanh toán|Payment|Trạng thái thanh toán)\s*:?\s*(.+?)(?:Khách sạn|Loại phòng|Ghi chú|$)"])
        data.update({
            "external_id": f"WEB-{order_no}" if order_no and not str(order_no).upper().startswith("WEB-") else order_no,
            "guest_name": clean_field(first_match(text, [r"(?:Khách hàng|Tên khách|Họ tên|Customer|Guest name)\s*:?\s*(.+?)(?:Số điện thoại|Điện thoại|Phone|Email|Khách sạn|$)"])),
            "guest_phone": clean_field(first_match(text, [r"(?:Số điện thoại|Điện thoại|Phone)\s*:?\s*(\+?\d[\d .-]{7,})"]), 50),
            "hotel_name": clean_field(first_match(text, [r"(?:Khách sạn|Hotel|Property)\s*:?\s*(.+?)(?:Loại phòng|Room|Ngày nhận|Check-in|$)"])),
            "room_type": clean_field(first_match(text, [r"(?:Loại phòng|Room type|Room)\s*:?\s*(.+?)(?:Ngày nhận|Check-in|Ngày trả|Check-out|$)"])),
            "check_in": parse_date_value(first_match(text, [r"(?:Ngày nhận phòng|Check-in|Nhận phòng)\s*:?\s*([\d/\-.]{8,10}|\d{1,2}\s+\w+\s+\d{4})"])),
            "check_out": parse_date_value(first_match(text, [r"(?:Ngày trả phòng|Check-out|Trả phòng)\s*:?\s*([\d/\-.]{8,10}|\d{1,2}\s+\w+\s+\d{4})"])),
            "total_price": parse_amount(first_match(text, [r"(?:Tổng cộng|Tổng tiền|Total)\s*:?\s*([\d.,]+)\s*(?:VND|VNĐ|đ|₫)?"])),
            "is_prepaid": bool(pay_text and any(k in normalize_key(pay_text) for k in ("da thanh toan", "paid online", "paid")) and "chua" not in normalize_key(pay_text)),
            "payment_method": pay_text,
            "rule_confidence": 92,
        })
        return data

    def extract_agoda(self, email: dict) -> Optional[dict]:
        text = self._text(email)
        data = base_result("Agoda", email)
        subject_id = first_match(email.get("subject", ""), [r"Booking ID\s+([A-Z0-9-]{5,})"])
        booking_id = subject_id or first_match(text, [r"Booking ID\s+(?:Mã số đặt phòng\s+)?([A-Z0-9-]{5,})"])
        first = clean_field(first_match(text, [r"Customer First Name\s+Tên Khách Hàng\s+(.+?)\s+Customer Last Name"]))
        last = clean_field(first_match(text, [r"Customer Last Name\s+Họ Khách Hàng\s+(.+?)\s+Country of Residence"]))
        guest = normalize_space(" ".join(x for x in (first, last) if x)) or None
        data.update({
            "external_id": booking_id,
            "hotel_name": clean_field(first_match(text, [r"Booking confirmation\s+Xác nhận đặt phòng\s+(.+?)\s+\(Property ID"])),
            "guest_name": clean_field(guest),
            "check_in": parse_date_value(first_match(text, [r"Check-in\s+Nhận phòng\s+([^\(]+)"])),
            "check_out": parse_date_value(first_match(text, [r"Check-out\s+Trả phòng\s+([^\(]+)"])),
            "room_type": clean_field(first_match(text, [r"Room Type\s+Loại Phòng\s+No\. of Rooms\s+Số phòng\s+Occupancy\s+Số người\s+No\. of Extra Bed\s+Số Giường Thêm\s*:\s*(.+?)\s+\d+\s+\d+\s+Adult", r"Room Type\s+Loại Phòng.+?:\s*(.+?)\s+Tên chính sách giá"])),
            "num_rooms": int(first_match(text, [r"Room Type\s+Loại Phòng\s+No\. of Rooms\s+Số phòng\s+Occupancy\s+Số người\s+No\. of Extra Bed\s+Số Giường Thêm\s*:\s*.+?\s+(\d+)\s+\d+\s+Adult", r"(?:No\. of Rooms|Số phòng|Rooms?)\s*:?[\s]*(\d+)"]) or 1),
            "total_price": parse_amount_decimal(first_match(text, [r"Net rate \(incl\. taxes & fees\)\s+Giá thực tế \(bao gồm thuế & phí\)\s+(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)", r"Net rate.*?(?:VND|VNĐ|đ|₫)\s*([\d.,]+)"])),
            "is_prepaid": True,
            "payment_method": "Agoda prepaid/net rate",
            "rule_confidence": 94,
        })
        return data

    def extract_traveloka(self, email: dict) -> Optional[dict]:
        return self._extract_generic(email, "Traveloka", confidence=82)

    def extract_tripcom(self, email: dict) -> Optional[dict]:
        subject = email.get("subject", "")
        text = self._text(email)
        # Bỏ qua email support/cài đặt giá/rate plan, không phải reservation.
        if not re.search(r"booking|reservation", subject, re.IGNORECASE):
            return skip_result("Trip.com", email) if looks_like_known_non_booking(email) else None
        data = base_result("Trip.com", email)
        if "Reservation：" in text or "Total amount：" in text:
            data.update({
                "external_id": clean_field(first_match(text, [r"Reservation[：:]\s*([A-Z0-9-]{5,})"]), 50),
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
        data.update({
            "external_id": clean_field(first_match(subject + " " + text[:500], [r"booking no\.\s*#?([A-Z0-9-]{5,})#?", r"Reservation no\.\s*([A-Z0-9-]{5,})"]), 50),
            "hotel_name": clean_field(first_match(text, [r"Property confirmation no\.\s*/\s*(.+?)\s+Guest Name:"])),
            "guest_name": clean_field(first_match(text, [r"Guest Name:\s*(.+?)\s+Room Type:"])),
            "room_type": clean_field(first_match(text, [r"Room Type:\s*(.+?)\s+\|\s+\d+\s+room"])),
            "check_in": parse_date_value(first_match(text, [r"Staying period:\s*(.+?)\s+-\s+.+?\s+\|"])),
            "check_out": parse_date_value(first_match(text, [r"Staying period:\s+.+?\s+-\s+(.+?)\s+\|"])),
            "total_price": parse_amount_decimal(first_match(text, [r"Your payout\s+(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)", r"Final room rate \(incl\. taxes and fees\)\s*([\d.,]+)"])),
            "is_prepaid": "prepaid" in normalize_key(text),
            "payment_method": "Trip.com net rate/prepaid" if "prepaid" in normalize_key(text) else None,
            "rule_confidence": 90,
        })
        return data

    def extract_airbnb(self, email: dict) -> Optional[dict]:
        return self._extract_generic(
            email, "Airbnb",
            price_patterns=[r"(?:Bạn kiếm được|Ban kiem duoc|You earn|Host payout)\s*:?\s*(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)"],
            confidence=84,
        )

    def extract_mytour(self, email: dict) -> Optional[dict]:
        return self._extract_generic(
            email, "Mytour",
            price_patterns=[r"(?:Tổng tiền trả khách sạn|Tong tien tra khach san|Total paid to hotel)\s*:?\s*(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)", r"(?:Tổng cộng|Tổng tiền)\s*:?\s*([\d.,]+)"],
            confidence=84,
        )

    def extract_expedia(self, email: dict) -> Optional[dict]:
        return self._extract_generic(
            email, "Expedia",
            price_patterns=[r"(?:Amount to Charge Expedia Group)\s*:?\s*(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)", r"(?:Net amount|Amount due)\s*:?\s*(?:VND|VNĐ|đ|₫)?\s*([\d.,]+)"],
            confidence=84,
        )

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
        external_patterns = external_patterns or [
            r"(?:Booking ID|Booking number|Confirmation number|Reservation ID|Itinerary number|Mã đặt phòng|Mã đơn|Order ID)\s*:?\s*#?\s*([A-Z0-9-]{5,})",
            r"(?:booking|reservation|confirmation)[^A-Z0-9]{0,20}([A-Z0-9-]{6,})",
        ]
        price_patterns = price_patterns or [
            r"(?:Total amount|Total price|Total booking amount|Tổng cộng|Tổng tiền|Grand total)\s*:?\s*(?:VND|VNĐ|đ|₫|USD)?\s*([\d.,]+)",
            r"(?:Net amount|Net rate|Amount due|Payable amount)\s*:?\s*(?:VND|VNĐ|đ|₫|USD)?\s*([\d.,]+)",
        ]
        data.update({
            "external_id": clean_field(first_match(subject + " " + text[:1000], external_patterns), 50),
            "guest_name": clean_field(first_match(text, [r"(?:Guest name|Guest|Customer name|Primary guest|Tên khách|Khách hàng)\s*:?\s*(.+?)(?:Booking|Confirmation|Property|Hotel|Room|Check-in|Số điện thoại|Phone|$)"])),
            "guest_phone": clean_field(first_match(text, [r"(?:Phone|Mobile|Số điện thoại|Điện thoại)\s*:?\s*(\+?\d[\d .-]{7,})"]), 50),
            "hotel_name": clean_field(first_match(text, [r"(?:Property|Hotel|Accommodation|Khách sạn|Tên khách sạn)\s*:?\s*(.+?)(?:Room|Guest|Check-in|Check in|Địa chỉ|Address|$)"])),
            "room_type": clean_field(first_match(text, [r"(?:Room type|Room|Loại phòng)\s*:?\s*(.+?)(?:Check-in|Check in|Check-out|Guest|Số khách|Guests|Số phòng|No\. of Rooms|Rooms?|$)"])),
            "num_rooms": int(first_match(text, [r"(?:Số phòng|No\. of Rooms|Room\(s\)|Rooms?)\s*:?\s*(\d+)"]) or 1),
            "check_in": parse_date_value(first_match(text, [r"(?:Check-in|Check in|Ngày nhận phòng|Nhận phòng)\s*:?\s*([\d/\-.]{8,10}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})"])),
            "check_out": parse_date_value(first_match(text, [r"(?:Check-out|Check out|Ngày trả phòng|Trả phòng)\s*:?\s*([\d/\-.]{8,10}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})"])),
            "total_price": parse_amount(first_match(text, price_patterns)),
            "is_prepaid": any(k in normalize_key(text) for k in ("prepaid", "paid online", "da thanh toan", "already paid")) and "chua thanh toan" not in normalize_key(text),
            "rule_confidence": confidence,
        })
        if not data.get("check_out") and data.get("check_in"):
            data["check_out"] = data["check_in"] + timedelta(days=1)
        return data
