from google import genai  # type: ignore
from bs4 import BeautifulSoup  # type: ignore
from app.core.config import settings, logger  # type: ignore
import json
import re
import time
import threading
import re as _re

# ── Global Gemini Rate Limiter ─────────────────────────────────────────────
# gemini-2.5-flash free tier: 10 RPM
# Giữ ở mức ~6 RPM (1 call / 10s) để có buffer an toàn
_gemini_lock = threading.Lock()
_last_gemini_call_at: float = 0.0
_MIN_CALL_INTERVAL = 10.0       # giây tối thiểu giữa 2 lần gọi Gemini
_global_backoff_until: float = 0.0  # khi nhận 429, nghỉ thêm N giây

def _wait_for_gemini_slot():
    """Chờ đến khi đủ thời gian giữa 2 lần gọi Gemini (global rate limiter)."""
    global _last_gemini_call_at
    with _gemini_lock:
        now = time.monotonic()
        # Nếu đang trong global backoff (sau 429) → chờ thêm
        if now < _global_backoff_until:
            extra = _global_backoff_until - now
            logger.info(f"[Gemini RateLimiter] Global backoff: chờ thêm {extra:.1f}s...")
            time.sleep(extra)
        # Giữ khoảng cách tối thiểu giữa 2 call
        now = time.monotonic()
        elapsed = now - _last_gemini_call_at
        if elapsed < _MIN_CALL_INTERVAL:
            wait = _MIN_CALL_INTERVAL - elapsed
            logger.info(f"[Gemini RateLimiter] Rate limit: chờ {wait:.1f}s...")
            time.sleep(wait)
        _last_gemini_call_at = time.monotonic()

def _apply_global_backoff(error_msg: str, default_seconds: int = 60):
    """Đọc retryDelay từ error message 429 và áp dụng global backoff."""
    global _global_backoff_until
    # Tìm số giây trong message: "Please retry in 28.97s"
    match = _re.search(r'retry in (\d+(?:\.\d+)?)', error_msg, _re.IGNORECASE)
    seconds = float(match.group(1)) if match else default_seconds
    seconds = min(seconds + 5, 60)   # +5s buffer, max 60s (tránh giữ thread quá lâu)
    _global_backoff_until = time.monotonic() + seconds
    logger.warning(f"[Gemini RateLimiter] 429 nhận được → global backoff {seconds:.0f}s")
# ──────────────────────────────────────────────────────────────────────────



class OTAExtractor:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            logger.warning("[OTA Extractor] GEMINI_API_KEY is missing!")
            self.client = None


    def clean_html(self, html_content: str) -> str:
        """
        Làm sạch HTML để giảm token và loại bỏ nhiễu.
        Giữ lại cấu trúc bảng và văn bản, loại bỏ scripts, styles, images.
        """
        if not html_content: return ""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 1. Loại bỏ các tab không cần thiết
            for tag in soup(["script", "style", "img", "head", "meta", "link", "iframe", "svg", "button", "input"]):
                tag.decompose()
                
            # 2. Xóa tất cả attributes (class, id, style...) để tiết kiệm token
            # Chỉ giữ lại colspan/rowspan cho table nếu cần, nhưng thường AI đọc text flow là đủ.
            for tag in soup.find_all(True):
                tag.attrs = {} 
                
            # 3. Lấy HTML string đã clean (giữ lại các thẻ div, p, table...)
            # Thay vì get_text() (mất cấu trúc), ta dùng str(soup) nhưng đã stripped attributes.
            # Tuy nhiên, để gọn nhất, có thể chỉ lấy text nếu format email đơn giản. 
            # Với OTA, table layout quan trọng -> Giữ tag.
            
            # Xóa khoảng trắng thừa
            cleaned_html = str(soup)
            cleaned_html = re.sub(r'\s+', ' ', cleaned_html).strip()
            
            return cleaned_html
        except Exception as e:
            logger.error(f"[OTA Extractor] Cleaning error: {e}")
            return html_content # Fallback

    def extract_data(self, html_content: str, sender: str, subject: str) -> dict:
        """
        Gửi clean HTML cho Gemini để trích xuất JSON.
        """
        if not self.client: 
            return {"error": "Missing API Key", "status": "FAILED"}

        # --- Bỏ qua các email kiểm tra phòng trống của Mytour ---
        if "mytour" in sender.lower() and "xác nhận phòng trống" in subject.lower():
            logger.info(f"[OTA Extractor] Bỏ qua email kiểm tra phòng trống Mytour: {subject}")
            return {"action_type": "IGNORE", "status": "IGNORED"}
        
        cleaned_body = self.clean_html(html_content)
        
        # Limit length to avoid unexpected huge emails, though Flash handles 1M.
        # 50k chars is usually enough for an email.
        cleaned_body = str(cleaned_body)[:50000]  # type: ignore

        prompt = f"""
        You are an expert Hotel Booking Data Extractor for a Vietnamese hotel chain.
        Analyze the following Booking Confirmation Email from sender "{sender}" with subject "{subject}".
        
        Task: Extract booking details into a valid JSON object.
        
        Required JSON Structure:
        {{
            "action_type": "NEW" | "MODIFY" | "CANCEL",
            "booking_source": "Agoda" | "Expedia" | "Traveloka" | "Airbnb" | "Go2Joy" | "Trip.com" | "Mytour" | "Website" | "Other",
            "external_id": "string",      // Booking ID / Confirmation Number from OTA (e.g. "4266983", "BDC-1234567", "#1987")
            "checkin_code": "string",     // PIN code or access code for room check-in (if available, else null). NOT the booking ID.
            "guest_name": "string",       // Full name of the primary guest
            "guest_phone": "string",      // Guest phone number (if available, else null)
            "hotel_name": "string",       // Hotel/property name as stated in the email
            "check_in": "YYYY-MM-DD",     // Check-in date
            "check_in_time": "HH:MM",       // Check-in time in 24h format (e.g. "14:00"), null if not mentioned
            "check_out": "YYYY-MM-DD",    // Check-out date
            "check_out_time": "HH:MM",      // Check-out time in 24h format (e.g. "18:00"), null if not mentioned
            "room_type": "string",        // Room type/name (e.g. "Superior Room", "Deluxe Double")
            "num_rooms": integer,         // Number of rooms booked (default 1 if not mentioned)
            "num_guests": integer,        // Total number of guests (adults + children)
            "num_adults": integer,        // Number of adults only
            "num_children": integer,      // Number of children (0 if not mentioned)
            "total_price": number,        // Total amount as raw number without currency symbol or commas. For Go2Joy, carefully look for "Tiền phòng", "Tổng cộng" or "Tổng tiền thanh toán".
            "currency": "string",         // VND, USD, EUR...
            "is_prepaid": boolean,        // true = paid online already; false = pay at hotel
            "payment_method": "string",   // e.g. "Visa ending 1234", "Cash", "Bank Transfer", null if unknown
            "deposit_amount": number,     // Amount already paid/deposited (0 if not mentioned)
            "notes": "string"             // Special requests or important notes (null if none)
        }}
        
        Rules:
        1. If information is missing or unclear, set value to null (or 0 for numeric fields).
        2. Format all dates strictly as YYYY-MM-DD.
        3. Format check_in_time and check_out_time as HH:MM (24h). For Go2Joy hourly bookings both dates are the same but there are specific check-in/check-out times. Extract them carefully.
        4. Ensure numeric fields are numbers, NOT strings. Remove any commas or currency symbols from prices.
        5. For total_price, apply these source-specific rules:
           - Go2Joy: use "Tiền phòng" (room price), NOT "Số tiền thanh toán" (final payment). E.g. "Tiền phòng: 600.000" and "Số tiền thanh toán: 560.000" → total_price = 600000.
           - Agoda: use "Net rate (incl. taxes & fees)" / "Giá thực tế (bao gồm thuế & phí)", NOT "Reference sell rate" / "Giá bán tham khảo". E.g. Net rate = 550,000 and Reference sell rate = 687,500 → total_price = 550000.
           - Expedia: use "Amount to Charge Expedia Group", NOT "Total Booking Amount". E.g. Amount to Charge = 603,789 and Total Booking Amount = 726,158 → total_price = 603789.
           - Airbnb: EXTREMELY IMPORTANT: ALWAYS use the value labeled "Bạn kiếm được" (host payout) located at the bottom of the "Khoản chi trả cho chủ nhà" section. NEVER use "Tổng (VND)" and NEVER use "Phí phòng". Example: "Bạn kiếm được đ2.088.729" → total_price = 2088729.
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
        8. For "Website" bookings: external_id is the order number after "#" in subject (e.g. subject "[Khách sạn Bin Bin] Đơn hàng mới #1987" → external_id = "WEB-1987"). Website bookings are almost always unpaid ("Chưa thanh toán"), so you MUST default "is_prepaid": false for Website bookings unless there is explicit textual proof that they have already paid online.
        9. checkin_code: A short numeric/alphanumeric PIN to access the room or building. May appear as "PIN", "Access code", "Check-in code", "Mã check-in". Leave null if not present.
        10. Return ONLY the JSON object. No markdown formatting, no explanation.
        
        Email Content:
        {cleaned_body}
        """

        
        max_retries = 2
        # Back-off ngắn: fail nhanh để tránh giữ DB connection và thread pool
        retry_delays = [10, 30]
        
        for attempt in range(max_retries):
            try:
                # Chờ slot khả dụng (global rate limiter - tránh RPM limit)
                _wait_for_gemini_slot()
                logger.info(f"[OTA Extractor] Sending request to Gemini for: {subject} (Attempt {attempt + 1}/{max_retries})")
                
                response = self.client.models.generate_content(
                    model='gemini-2.5-flash',  # gemini-2.5-flash với API key mới
                    contents=prompt,
                    config={
                        'response_mime_type': 'application/json'
                    }
                )

                
                if response.text:
                    data = json.loads(response.text)
                    data["status"] = "SUCCESS"
                    return data
                else:
                    return {"error": "Empty response from AI", "status": "FAILED"}
                    
            except Exception as e:
                error_msg = str(e)
                error_lower = error_msg.lower()
                if "429" in error_lower or "quota" in error_lower or "rate limit" in error_lower or "resource_exhausted" in error_lower:
                    # Áp dụng global backoff cho mọi thread (đọc retryDelay từ error message)
                    _apply_global_backoff(error_msg)
                    if attempt < max_retries - 1:
                        sleep_time = retry_delays[attempt]
                        logger.warning(
                            f"[OTA Extractor] Rate limit (429) — chờ {sleep_time}s trước khi retry "
                            f"(lần {attempt + 1}/{max_retries})..."
                        )
                        time.sleep(sleep_time)
                        continue
                    else:
                        logger.error(f"[OTA Extractor] Vẫn bị 429 sau {max_retries} lần thử. Bỏ qua email này.")
                        return {"error": "Rate limit exceeded after max retries", "status": "FAILED"}

                        
                logger.error(f"[OTA Extractor] Gemini Processing Error: {e}")
                return {"error": str(e), "status": "FAILED"}

        return {"error": "Max retries exceeded", "status": "FAILED"}

