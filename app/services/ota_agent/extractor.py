import httpx
from bs4 import BeautifulSoup  # type: ignore
from app.core.config import settings, logger  # type: ignore
import json
import re
import time
import threading

# ── Global Rate Limiter ───────────────────────────────────────────────────
_api_lock = threading.Lock()
_last_api_call_at: float = 0.0
_MIN_CALL_INTERVAL = 2.0
_global_backoff_until: float = 0.0


def _wait_for_api_slot():
    global _last_api_call_at
    with _api_lock:
        now = time.monotonic()
        if now < _global_backoff_until:
            extra = _global_backoff_until - now
            logger.info(f"[OTA Extractor] Global backoff: chờ thêm {extra:.1f}s...")
            time.sleep(extra)
        now = time.monotonic()
        elapsed = now - _last_api_call_at
        if elapsed < _MIN_CALL_INTERVAL:
            wait = _MIN_CALL_INTERVAL - elapsed
            time.sleep(wait)
        _last_api_call_at = time.monotonic()


def _apply_global_backoff(error_msg: str, default_seconds: int = 30):
    global _global_backoff_until
    match = re.search(r'retry.{0,20}?(\d+(?:\.\d+)?)\s*s', error_msg, re.IGNORECASE)
    seconds = float(match.group(1)) if match else default_seconds
    seconds = min(seconds + 5, 60)
    _global_backoff_until = time.monotonic() + seconds
    logger.warning(f"[OTA Extractor] 429 → global backoff {seconds:.0f}s")
# ──────────────────────────────────────────────────────────────────────────


class OTAExtractor:
    def __init__(self):
        self.api_key = settings.GATECHEAP_API_KEY
        self.model = settings.GATECHEAP_MODEL
        self.base_url = "https://gatecheap.io.vn/v1"
        if not self.api_key:
            logger.warning("[OTA Extractor] GATECHEAP_API_KEY is missing!")
        self.client = self.api_key is not None

    def clean_html(self, html_content: str) -> str:
        if not html_content:
            return ""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            for tag in soup(["script", "style", "img", "head", "meta", "link", "iframe", "svg", "button", "input"]):
                tag.decompose()
            for tag in soup.find_all(True):
                tag.attrs = {}
            cleaned_html = str(soup)
            cleaned_html = re.sub(r'\s+', ' ', cleaned_html).strip()
            return cleaned_html
        except Exception as e:
            logger.error(f"[OTA Extractor] Cleaning error: {e}")
            return html_content

    def extract_data(self, html_content: str, sender: str, subject: str) -> dict:
        if not self.client:
            return {"error": "Missing GATECHEAP_API_KEY", "status": "FAILED"}

        if "mytour" in sender.lower() and "xác nhận phòng trống" in subject.lower():
            logger.info(f"[OTA Extractor] Bỏ qua email kiểm tra phòng trống Mytour: {subject}")
            return {"action_type": "IGNORE", "status": "IGNORED"}

        cleaned_body = self.clean_html(html_content)
        cleaned_body = str(cleaned_body)[:50000]

        prompt = f"""You are an expert Hotel Booking Data Extractor for a Vietnamese hotel chain.
Analyze the following Booking Confirmation Email from sender "{sender}" with subject "{subject}".

Task: Extract booking details into a valid JSON object.

Required JSON Structure:
{{
    "action_type": "NEW" | "MODIFY" | "CANCEL",
    "booking_source": "Agoda" | "Expedia" | "Traveloka" | "Airbnb" | "Go2Joy" | "Trip.com" | "Mytour" | "Website" | "Other",
    "external_id": "string",
    "checkin_code": "string",
    "guest_name": "string",
    "guest_phone": "string",
    "hotel_name": "string",
    "check_in": "YYYY-MM-DD",
    "check_in_time": "HH:MM",
    "check_out": "YYYY-MM-DD",
    "check_out_time": "HH:MM",
    "room_type": "string",
    "num_rooms": integer,
    "num_guests": integer,
    "num_adults": integer,
    "num_children": integer,
    "total_price": number,
    "currency": "string",
    "is_prepaid": boolean,
    "payment_method": "string",
    "deposit_amount": 0,
    "notes": "string"
}}

Rules:
1. If information is missing or unclear, set value to null (or 0 for numeric fields).
2. Format all dates strictly as YYYY-MM-DD.
3. Format check_in_time and check_out_time as HH:MM (24h). For Go2Joy hourly bookings both dates are the same but there are specific check-in/check-out times. Extract them carefully.
4. Ensure numeric fields are numbers, NOT strings. Remove any commas or currency symbols from prices.
5. For total_price, apply these source-specific rules:
   - Go2Joy: use "Tiền phòng" (room price), NOT "Số tiền thanh toán" (final payment).
   - Agoda: use "Net rate (incl. taxes & fees)" / "Giá thực tế (bao gồm thuế & phí)", NOT "Reference sell rate".
   - Expedia: use "Amount to Charge Expedia Group", NOT "Total Booking Amount".
   - Airbnb: ALWAYS use "Bạn kiếm được" (host payout). NEVER use "Tổng (VND)" or "Phí phòng".
   - Mytour: use "Tổng tiền trả khách sạn" (total amount paid to hotel).
   - Other OTAs: use the main booking total shown in the confirmation.
6. Detect action_type from keywords: "New booking" / "Booking confirmed" / "Đơn hàng mới" → NEW | "Modified / Amendment" → MODIFY | "Cancelled / Cancellation" → CANCEL.
7. For booking_source, infer from sender email domain or email branding:
   - @agoda.com → "Agoda"
   - @go2joy.vn → "Go2Joy"
   - @trip.com / @ctrip.com → "Trip.com"
   - @traveloka.com → "Traveloka"
   - @airbnb.com → "Airbnb"
   - noreply@mytour.vn / @mytour.vn → "Mytour"
   - Email subject contains "[Khách sạn Bin Bin]" or sender is binbinhotel.ota@gmail.com → "Website"
8. For "Website" bookings: external_id is the order number after "#" in subject. Default "is_prepaid": false unless explicit proof of online payment.
9. For "Go2Joy" bookings: If "Tình trạng thanh toán" says "Chưa thanh toán" or "Thanh toán tại khách sạn", set "is_prepaid": false. Otherwise default to true.
10. IMPORTANT: Always set "deposit_amount": 0 for all OTA bookings.
11. checkin_code: A short PIN/access code for room check-in. Leave null if not present.
12. Return ONLY the JSON object. No markdown formatting, no explanation.

Email Content:
{cleaned_body}"""

        max_retries = 2
        retry_delays = [5, 15]

        for attempt in range(max_retries):
            try:
                _wait_for_api_slot()
                logger.info(f"[OTA Extractor] GPT request for: {subject} (Attempt {attempt + 1}/{max_retries})")

                response = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=60.0,
                )

                if response.status_code == 429:
                    _apply_global_backoff(response.text)
                    if attempt < max_retries - 1:
                        time.sleep(retry_delays[attempt])
                        continue
                    return {"error": "Rate limit exceeded after max retries", "status": "FAILED"}

                response.raise_for_status()
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                data = json.loads(content)
                data["status"] = "SUCCESS"
                return data

            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                error_msg = str(e)
                if "429" in error_msg:
                    _apply_global_backoff(error_msg)
                    if attempt < max_retries - 1:
                        time.sleep(retry_delays[attempt])
                        continue
                    return {"error": "Rate limit exceeded after max retries", "status": "FAILED"}
                logger.error(f"[OTA Extractor] API Error: {e}")
                return {"error": str(e), "status": "FAILED"}
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                logger.error(f"[OTA Extractor] Parse Error: {e}")
                return {"error": f"Response parse error: {e}", "status": "FAILED"}
            except Exception as e:
                logger.error(f"[OTA Extractor] Unexpected Error: {e}")
                return {"error": str(e), "status": "FAILED"}

        return {"error": "Max retries exceeded", "status": "FAILED"}
