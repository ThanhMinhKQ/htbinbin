from imap_tools import MailBox, AND
from app.core.config import settings, logger
from typing import List, Dict, Any

class OTAListener:
    def __init__(self):
        self.server = settings.IMAP_SERVER
        self.user = settings.IMAP_USER
        self.password = settings.IMAP_PASSWORD
        self.ota_senders = [s.strip() for s in settings.OTA_SENDERS.split(',') if s.strip()]

    def verify_connection(self) -> bool:
        """Kiểm tra kết nối IMAP"""
        if not self.user or not self.password:
            logger.warning("[OTA Listener] Missing IMAP credentials.")
            return False
        try:
            with MailBox(self.server).login(self.user, self.password, initial_folder='INBOX'):
                return True
        except Exception as e:
            logger.error(f"[OTA Listener] Connection failed: {e}")
            return False

    def fetch_unseen_emails(self, limit=20) -> List[Dict[str, Any]]:
        """
        Lấy email chưa đọc từ các OTA sender.
        Tự động đánh dấu là đã đọc (SEEN) sau khi fetch (mặc định của imap_tools).
        """
        if not self.verify_connection():
            return []

        results = []
        try:
            with MailBox(self.server).login(self.user, self.password, initial_folder='INBOX') as mailbox:
                # Tìm tất cả email chưa đọc
                # Lưu ý: Tìm tất cả UNSEEN rồi lọc theo sender bằng Python để tránh lỗi cú pháp IMAP phức tạp
                # (Trừ khi inbox quá lớn, nhưng inbox đặt phòng thường được xử lý liên tục)
                
                # Để tối ưu, nếu inbox lớn, ta có thể loop qua từng sender để query IMAP (nhưng sẽ chậm nếu nhiều sender)
                # Query: AND(seen=False) -> Python filter
                
                logger.info("[OTA Listener] Checking for unseen emails...")
                
                for msg in mailbox.fetch(AND(seen=False), limit=limit, reverse=True): # Lấy mới nhất trước
                    
                    sender_email = msg.from_
                    
                    # Logic kiểm tra sender: Check DOMAIN thay vì exact match
                    # Ví dụ: guest.booking.com, noreply@booking.com đều match với "booking.com"
                    is_ota = any(
                        s.strip().replace('noreply@', '').replace('reservations@', '').replace('no-reply@', '') in sender_email.lower()
                        for s in self.ota_senders
                    )
                    
                    if is_ota:
                        logger.info(f"[OTA Listener] Found OTA email from: {sender_email} | Subject: {msg.subject}")
                        results.append({
                            "uid": msg.uid,
                            "subject": msg.subject,
                            "sender": sender_email,
                            "date": msg.date,
                            "html": msg.html,
                            "text": msg.text,
                            "message_id": msg.uid # Dùng UID làm định danh tạm
                        })
                    else:
                        # Nếu không phải OTA, có thể giữ nguyên trạng thái UNSEEN?
                        # imap_tools.fetch mặc định đánh dấu SEEN tất cả msg trả về.
                        # Nếu muốn giữ UNSEEN cho mail rác -> cần dùng mark_seen=False
                        # Tuy nhiên để đơn giản cho MVP, ta cứ đánh dấu là đã đọc để tránh query lại.
                        pass
                        
        except Exception as e:
            logger.error(f"[OTA Listener] Fetch error: {e}")

        logger.info(f"[OTA Listener] Fetched {len(results)} relevant emails.")
        return results
