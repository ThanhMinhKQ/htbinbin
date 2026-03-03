"""
Gmail Service - Thay thế IMAP polling bằng Gmail API + Pub/Sub Watch
"""

import os
import json
import base64
from pathlib import Path
from typing import List, Dict, Any, Optional
from email import message_from_bytes

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings, logger

# Scopes cần thiết: đọc mail + metadata
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',  # Cần để đánh dấu đã đọc nếu muốn
]

# Đường dẫn lưu token (root project)
TOKEN_PATH = Path(__file__).parent.parent.parent.parent / "gmail_token.json"
CLIENT_SECRETS_PATH = Path(__file__).parent.parent.parent.parent / "client_secrets.json"


class GmailService:
    """
    Wrapper Gmail API dùng OAuth2.
    Thay thế OTAListener (IMAP) bằng event-driven push notification.
    """

    def __init__(self):
        self._service = None
        self.ota_senders = [
            s.strip().lower()
            for s in (settings.OTA_SENDERS or "").split(',')
            if s.strip()
        ]

    def get_credentials(self) -> Optional[Credentials]:
        """Đọc credentials từ token file hoặc env var, tự động refresh nếu hết hạn."""
        creds = None

        if TOKEN_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            except Exception as e:
                logger.error(f"[Gmail Service] Lỗi đọc token file: {e}")
        
        # Fallback: đọc từ env var GMAIL_TOKEN_JSON (dùng khi deploy trên Render/cloud)
        if not creds:
            token_json_str = os.environ.get("GMAIL_TOKEN_JSON", "")
            if token_json_str:
                try:
                    token_data = json.loads(token_json_str)
                    creds = Credentials.from_authorized_user_info(token_data, SCOPES)
                    logger.info("[Gmail Service] Đọc token từ env var GMAIL_TOKEN_JSON")
                except Exception as e:
                    logger.error(f"[Gmail Service] Lỗi đọc token từ env var: {e}")
                    return None

        if not creds:
            logger.warning(
                "[Gmail Service] Token không tìm thấy. "
                "Hãy set env var GMAIL_TOKEN_JSON hoặc chạy scripts/gmail_auth.py"
            )
            return None

        # Refresh nếu hết hạn
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_token(creds)
                logger.info("[Gmail Service] Token đã được làm mới tự động")
            except Exception as e:
                logger.error(f"[Gmail Service] Không thể refresh token: {e}")
                return None

        if not creds.valid:
            logger.warning("[Gmail Service] Token không hợp lệ")
            return None

        return creds

    def _save_token(self, creds: Credentials):
        """Lưu token vào file."""
        try:
            with open(TOKEN_PATH, 'w') as f:
                f.write(creds.to_json())
        except Exception as e:
            logger.error(f"[Gmail Service] Lỗi lưu token: {e}")

    def save_token_from_json(self, token_data: dict):
        """Lưu token từ dict (dùng trong OAuth callback)."""
        try:
            with open(TOKEN_PATH, 'w') as f:
                json.dump(token_data, f)
            logger.info(f"[Gmail Service] Token saved to {TOKEN_PATH}")
        except Exception as e:
            logger.error(f"[Gmail Service] Không thể lưu token: {e}")

    def build_service(self):
        """Khởi tạo Gmail API client."""
        creds = self.get_credentials()
        if not creds:
            return None
        try:
            service = build('gmail', 'v1', credentials=creds)
            return service
        except Exception as e:
            logger.error(f"[Gmail Service] Không thể khởi tạo Gmail API: {e}")
            return None

    def watch_inbox(self) -> Optional[Dict]:
        """
        Đăng ký Gmail watch với Pub/Sub topic.
        Hết hạn sau 7 ngày -> cần gia hạn định kỳ.
        Returns: {'historyId': '...', 'expiration': '...'}
        """
        topic = settings.GOOGLE_PUBSUB_TOPIC
        if not topic:
            logger.error("[Gmail Service] GOOGLE_PUBSUB_TOPIC chưa được cấu hình trong .env")
            return None

        service = self.build_service()
        if not service:
            return None

        try:
            result = service.users().watch(
                userId='me',
                body={
                    'topicName': topic,
                    'labelIds': ['INBOX'],
                    'labelFilterAction': 'include',
                }
            ).execute()

            logger.info(
                f"[Gmail Service] ✅ Watch đã đăng ký thành công! "
                f"historyId={result.get('historyId')}, "
                f"Hết hạn: {result.get('expiration')}"
            )
            return result

        except HttpError as e:
            logger.error(f"[Gmail Service] Lỗi đăng ký watch: {e}")
            return None

    def stop_watch(self) -> bool:
        """Huỷ Gmail watch hiện tại."""
        service = self.build_service()
        if not service:
            return False
        try:
            service.users().stop(userId='me').execute()
            logger.info("[Gmail Service] Đã huỷ watch")
            return True
        except HttpError as e:
            logger.error(f"[Gmail Service] Lỗi huỷ watch: {e}")
            return False

    def get_history(self, start_history_id: str) -> List[Dict]:
        """
        Lấy danh sách thay đổi từ Gmail History API.
        Returns: Danh sách message mới (chỉ messageId).
        """
        service = self.build_service()
        if not service:
            return []

        try:
            history_response = service.users().history().list(
                userId='me',
                startHistoryId=start_history_id,
                historyTypes=['messageAdded'],
                labelId='INBOX',
            ).execute()

            messages = []
            changes = history_response.get('history', [])

            for change in changes:
                for msg_added in change.get('messagesAdded', []):
                    msg = msg_added.get('message', {})
                    if msg.get('id'):
                        messages.append(msg)

            logger.info(f"[Gmail Service] Tìm thấy {len(messages)} message mới từ historyId={start_history_id}")
            return messages

        except HttpError as e:
            # 404 = historyId quá cũ (không còn trong history)
            if e.resp.status == 404:
                logger.warning(
                    f"[Gmail Service] historyId={start_history_id} quá cũ, "
                    "thực hiện full resync ..."
                )
                return self._full_resync()
            logger.error(f"[Gmail Service] Lỗi get_history: {e}")
            return []

    def _full_resync(self) -> List[Dict]:
        """
        Resync: Lấy email chưa đọc mới nhất khi historyId quá cũ.
        """
        service = self.build_service()
        if not service:
            return []
        try:
            result = service.users().messages().list(
                userId='me',
                q=f'is:unread from:({" OR ".join(self.ota_senders)})',
                maxResults=20
            ).execute()
            return result.get('messages', [])
        except Exception as e:
            logger.error(f"[Gmail Service] Lỗi full resync: {e}")
            return []

    def get_message(self, message_id: str) -> Optional[Dict]:
        """
        Lấy toàn bộ nội dung 1 email theo messageId.
        Returns: dict với keys: subject, sender, html, text, message_id, uid
        """
        service = self.build_service()
        if not service:
            return None

        try:
            msg = service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()

            headers = {h['name'].lower(): h['value'] for h in msg.get('payload', {}).get('headers', [])}

            subject = headers.get('subject', '')
            sender = headers.get('from', '')

            html_content = ''
            text_content = ''
            self._extract_parts(msg.get('payload', {}), html_content, text_content)

            # Parse parts properly
            html_content, text_content = self._parse_payload(msg.get('payload', {}))

            return {
                'uid': message_id,
                'message_id': message_id,
                'subject': subject,
                'sender': sender,
                'html': html_content,
                'text': text_content,
                'date': headers.get('date'),
            }

        except HttpError as e:
            logger.error(f"[Gmail Service] Lỗi lấy message {message_id}: {e}")
            return None

    def _parse_payload(self, payload: dict) -> tuple:
        """Đệ quy parse MIME parts để lấy HTML và Text content."""
        html = ''
        text = ''
        mime_type = payload.get('mimeType', '')

        if mime_type == 'text/html':
            data = payload.get('body', {}).get('data', '')
            if data:
                html = base64.urlsafe_b64decode(data + '==').decode('utf-8', errors='replace')

        elif mime_type == 'text/plain':
            data = payload.get('body', {}).get('data', '')
            if data:
                text = base64.urlsafe_b64decode(data + '==').decode('utf-8', errors='replace')

        elif mime_type.startswith('multipart/'):
            for part in payload.get('parts', []):
                sub_html, sub_text = self._parse_payload(part)
                html = html or sub_html
                text = text or sub_text

        return html, text

    def _extract_parts(self, payload: dict, html: str, text: str):
        """Helper không dùng - thay bằng _parse_payload."""
        pass

    # ── Booking subject filter ────────────────────────────────────────────────

    # Từ khoá subject BẮT BUỘC phải có ít nhất 1 (ngôn ngữ: VN/EN)
    BOOKING_KEYWORDS = [
        # English
        'booking', 'reservation', 'confirmed', 'confirmation',
        'new booking', 'booking confirmation',
        'cancelled', 'cancellation', 'amendment', 'modified',
        'check-in', 'check in', 'checkout', 'check out',
        'guest', 'accommodation', 'order',
        # Vietnamese
        'đặt phòng', 'xác nhận', 'hủy phòng', 'hủy đặt',
        'nhận phòng', 'trả phòng', 'đặt chỗ',
        'đơn hàng', 'đơn hàng mới',  # Website khách sạn
        'bin bin',                          # [Khách sạn Bin Bin] ...
        # Go2Joy specific
        'đặt chỗ thành công', 'booking thành công',
    ]

    # Từ khoá subject → BỎ QUA ngay (không gọi AI)
    SKIP_KEYWORDS = [
        # Reports / Analytics
        'báo cáo', 'hiệu suất', 'thống kê', 'phân tích',
        'report', 'performance', 'analytics', 'weekly', 'monthly',
        'insights', 'summary', 'digest',
        # Marketing / Newsletter
        'newsletter', 'promotion', 'khuyến mãi', 'ưu đãi',
        'offer', 'deal', 'discount', 'sale', 'marketing',
        'unsubscribe', 'hủy đăng ký',
        # System / Admin
        'payment received', 'invoice', 'receipt', 'statement',
        'hóa đơn', 'thanh toán thành công',
        'verify', 'xác minh', 'password', 'mật khẩu',
        'login', 'security alert',
    ]

    def is_booking_subject(self, subject: str) -> bool:
        """
        Kiểm tra subject email có khả năng là booking confirmation không.
        - Nếu chứa SKIP_KEYWORDS → False (bỏ qua ngay, không gọi AI)
        - Nếu chứa BOOKING_KEYWORDS → True (xử lý)
        - Nếu không match gì → True (uncertain, để AI quyết định)
        """
        if not subject:
            return True  # Không có subject → để AI phán

        subject_lower = subject.lower()

        # 1. Bỏ qua ngay nếu là report/newsletter/marketing
        for skip_kw in self.SKIP_KEYWORDS:
            if skip_kw in subject_lower:
                logger.info(f"[Gmail Filter] ⏭️ Bỏ qua (subject không phải booking): '{subject[:80]}'")
                return False

        # 2. Ưu tiên nếu có từ khoá booking rõ ràng
        for book_kw in self.BOOKING_KEYWORDS:
            if book_kw in subject_lower:
                return True

        # 3. Không chắc → vẫn cho qua (để AI phán)
        logger.debug(f"[Gmail Filter] ⚠️ Subject không rõ ràng, vẫn xử lý: '{subject[:80]}'")
        return True

    def is_ota_sender(self, sender_email: str) -> bool:
        """Kiểm tra email có phải từ OTA không."""
        sender_lower = sender_email.lower()
        return any(ota_domain in sender_lower for ota_domain in self.ota_senders)

    def fetch_new_emails_from_history(self, history_id: str) -> List[Dict]:
        """
        Entry point chính khi nhận webhook.
        1. Lấy danh sách message mới từ historyId
        2. Lọc chỉ email từ OTA
        3. Lấy đầy đủ nội dung
        Returns: List email dict (cùng format với OTAListener)
        """
        messages = self.get_history(history_id)
        if not messages:
            return []

        results = []
        for msg_meta in messages:
            message_id = msg_meta.get('id')
            if not message_id:
                continue

            email = self.get_message(message_id)
            if not email:
                continue

            # Lọc theo OTA sender
            if self.is_ota_sender(email['sender']):
                logger.info(
                    f"[Gmail Service] ✉️ Email OTA mới: "
                    f"from={email['sender']} | subject={email['subject']}"
                )
                results.append(email)
            else:
                logger.debug(f"[Gmail Service] Bỏ qua email từ: {email['sender']}")

        logger.info(f"[Gmail Service] Tổng email OTA cần xử lý: {len(results)}")
        return results

    def get_current_history_id(self) -> Optional[str]:
        """Lấy historyId hiện tại của mailbox (dùng sau khi watch)."""
        service = self.build_service()
        if not service:
            return None
        try:
            profile = service.users().getProfile(userId='me').execute()
            return str(profile.get('historyId', ''))
        except Exception as e:
            logger.error(f"[Gmail Service] Lỗi lấy historyId: {e}")
            return None

    def is_configured(self) -> bool:
        """Kiểm tra Gmail service đã sẵn sàng chưa."""
        has_token = TOKEN_PATH.exists() or bool(os.environ.get("GMAIL_TOKEN_JSON", ""))
        return has_token and settings.GOOGLE_PUBSUB_TOPIC is not None

    def get_watch_status(self) -> Dict:
        """Trả về trạng thái hiện tại của Gmail service."""
        token_exists = TOKEN_PATH.exists()
        creds_valid = False

        if token_exists:
            creds = self.get_credentials()
            creds_valid = creds is not None and creds.valid

        return {
            "token_file_exists": token_exists,
            "credentials_valid": creds_valid,
            "pubsub_topic": settings.GOOGLE_PUBSUB_TOPIC,
            "watch_email": settings.GMAIL_WATCH_EMAIL,
            "ota_senders": self.ota_senders,
            "token_path": str(TOKEN_PATH),
        }


# Singleton instance
gmail_service = GmailService()
