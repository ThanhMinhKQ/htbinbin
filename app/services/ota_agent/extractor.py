from google import genai
from bs4 import BeautifulSoup
from app.core.config import settings, logger
import json
import re
import time

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
        
        cleaned_body = self.clean_html(html_content)
        
        # Limit length to avoid unexpected huge emails, though Flash handles 1M.
        # 50k chars is usually enough for an email.
        cleaned_body = cleaned_body[:50000]

        prompt = f"""
        You are an expert Hotel Booking Data Extractor for a Vietnamese hotel chain.
        Analyze the following Booking Confirmation Email from sender "{sender}" with subject "{subject}".
        
        Task: Extract booking details into a valid JSON object.
        
        Required JSON Structure:
        {{
            "action_type": "NEW" | "MODIFY" | "CANCEL",
            "booking_source": "Booking.com" | "Agoda" | "Expedia" | "Traveloka" | "Airbnb" | "Go2Joy" | "Trip.com" | "Website" | "Other",
            "external_id": "string",      // Booking ID / Confirmation Number from OTA (e.g. "4266983", "BDC-1234567", "#1987")
            "checkin_code": "string",     // PIN code or access code for room check-in (if available, else null). NOT the booking ID.
            "guest_name": "string",       // Full name of the primary guest
            "guest_phone": "string",      // Guest phone number (if available, else null)
            "hotel_name": "string",       // Hotel/property name as stated in the email
            "check_in": "YYYY-MM-DD",     // Check-in date
            "check_out": "YYYY-MM-DD",    // Check-out date
            "room_type": "string",        // Room type/name (e.g. "Superior Room", "Deluxe Double")
            "num_guests": integer,        // Total number of guests (adults + children)
            "num_adults": integer,        // Number of adults only
            "num_children": integer,      // Number of children (0 if not mentioned)
            "total_price": number,        // Total amount as raw number without currency symbol or commas
            "currency": "string",         // VND, USD, EUR...
            "is_prepaid": boolean,        // true = paid online already; false = pay at hotel
            "payment_method": "string",   // e.g. "Visa ending 1234", "Cash", "Bank Transfer", null if unknown
            "deposit_amount": number,     // Amount already paid/deposited (0 if not mentioned)
            "notes": "string"             // Special requests or important notes (null if none)
        }}
        
        Rules:
        1. If information is missing or unclear, set value to null (or 0 for numeric fields).
        2. Format all dates strictly as YYYY-MM-DD.
        3. Ensure numeric fields are numbers, NOT strings. Remove any commas or currency symbols from prices.
        4. Detect action_type from keywords: "New booking" / "Booking confirmed" / "Đơn hàng mới" → NEW | "Modified / Amendment" → MODIFY | "Cancelled / Cancellation" → CANCEL.
        5. For booking_source, infer from sender email domain or email branding:
           - @booking.com / guest.booking.com → "Booking.com"
           - @agoda.com → "Agoda"
           - @go2joy.vn → "Go2Joy"
           - @trip.com / @ctrip.com → "Trip.com"
           - @traveloka.com → "Traveloka"
           - @airbnb.com → "Airbnb"
           - Email subject contains "[Khách sạn Bin Bin]" or sender is binbinhotel.ota@gmail.com → "Website"
        6. For "Website" bookings: external_id is the order number after "#" in subject (e.g. subject "[Khách sạn Bin Bin] Đơn hàng mới #1987" → external_id = "WEB-1987").
        7. checkin_code: A short numeric/alphanumeric PIN to access the room or building. May appear as "PIN", "Access code", "Check-in code", "Mã check-in". Leave null if not present.
        8. Return ONLY the JSON object. No markdown formatting, no explanation.
        
        Email Content:
        {cleaned_body}
        """

        
        max_retries = 4
        # Exponential back-off: 5s, 15s, 30s, 60s
        retry_delays = [5, 15, 30, 60]
        
        for attempt in range(max_retries):
            try:
                logger.info(f"[OTA Extractor] Sending request to Gemini for: {subject} (Attempt {attempt + 1}/{max_retries})")
                
                response = self.client.models.generate_content(
                    model='gemini-2.0-flash',  # 1500 RPD free tier, hỗ trợ v1beta
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
                error_msg = str(e).lower()
                if "429" in error_msg or "quota" in error_msg or "rate limit" in error_msg or "resource_exhausted" in error_msg:
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

