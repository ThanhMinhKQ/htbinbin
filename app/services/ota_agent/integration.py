from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models import Booking, BookingStatus, OTAParsingLog, OTAParsingStatus
from .extractor import OTAExtractor
from .rule_extractor import RuleBasedOTAExtractor, detect_cancel_action, detect_modify_action, is_confident_booking, looks_like_known_non_booking
from .mapper import HotelMapper
from app.core.config import logger
from app.core.utils import VN_TZ
from app.services.booking_service import BookingService
from datetime import date, datetime, timedelta
import traceback
import re
from typing import Optional

try:
    from .listener import OTAListener
except ModuleNotFoundError as exc:
    if exc.name != "imap_tools":
        raise
    OTAListener = None

class OTAAgent:
    def __init__(self):
        self.listener = OTAListener() if OTAListener else None
        self.extractor = OTAExtractor()
        self.rule_extractor = RuleBasedOTAExtractor()

    def run_once(self):
        """
        Main entry point: Fetch mails -> Process each -> DB
        """
        if not self.listener:
            logger.error("[OTA Agent] IMAP listener chưa khả dụng vì thiếu package imap_tools. Gmail API/PubSub vẫn dùng process_email bình thường.")
            return
        db = SessionLocal()
        try:
            mapper = HotelMapper(db)
            emails = self.listener.fetch_unseen_emails()
            
            for email in emails:
                try:
                    self.process_email(db, mapper, email)
                except Exception as e:
                    # Log error but continue processing other emails
                    logger.error(f"[OTA Agent] Error processing email {email.get('uid')}: {e}")
                    # Rollback this email's transaction
                    db.rollback()
                
        except Exception as e:
            logger.error(f"[OTA Agent] Critical error in run_once: {e}")
        finally:
            db.close()

    def process_email(self, db: Session, mapper: HotelMapper, email: dict, processed_at: Optional[datetime] = None):
        logger.info(f"[OTA Agent] Processing email: {email['subject']}")

        # 0a. Subject/body filter: bỏ qua email OTA admin/non-booking trước khi tạo log hoặc gọi Gemini.
        from app.services.ota_agent.gmail_service import gmail_service
        if not gmail_service.is_booking_subject(email.get('subject', '')) or looks_like_known_non_booking(email):
            logger.info(f"[OTA Agent] ⏭️ Bỏ qua email không phải booking — không gọi Gemini: {email.get('subject', '')[:120]}")
            return

        # 0b. Dedup: Kiểm tra message_id đã tồn tại chưa (tránh UniqueViolation)
        message_id = email.get('message_id')
        existing_log = None
        if message_id:
            existing_log = db.query(OTAParsingLog).filter(
                OTAParsingLog.email_message_id == message_id
            ).first()
            if existing_log:
                if existing_log.status == OTAParsingStatus.SUCCESS:
                    logger.info(
                        f"[OTA Agent] ⏭️ Bỏ qua email đã xử lý thành công "
                        f"(message_id={message_id}, booking_id={existing_log.booking_id})"
                    )
                    return
                else:
                    # Đã có log FAILED/pending → dùng lại log đó, không INSERT mới
                    logger.info(
                        f"[OTA Agent] ↺ Retry email (message_id={message_id}, "
                        f"status={existing_log.status}, retry={existing_log.retry_count})"
                    )

        # 0c. Cache theo booking id trong subject/body: chỉ bỏ qua duplicate NEW.
        # CANCEL/MODIFY phải được parse để cập nhật booking đã tồn tại.
        cached_external_id = self._guess_external_id(email)
        precheck_data = self.rule_extractor.extract(email)
        precheck_action = str((precheck_data or {}).get("action_type") or "NEW").upper()
        if precheck_action == "NEW":
            body_preview = email.get("text") or re.sub(r"<[^>]+>", " ", email.get("html") or "")
            if detect_cancel_action(email.get("subject", ""), body_preview):
                precheck_action = "CANCEL"
            elif detect_modify_action(email.get("subject", ""), body_preview):
                precheck_action = "MODIFY"
        if cached_external_id and precheck_action == "NEW" and self._already_processed_external_id(db, cached_external_id):
            logger.info(
                f"[OTA Agent] ⏭️ Bỏ qua booking đã có cache external_id={cached_external_id} — không gọi Gemini"
            )
            return

        # 1. Init Log
        if existing_log:
            log_entry = existing_log  # Reuse log cũ cho retry
        else:
            log_entry = OTAParsingLog(
                email_subject=email['subject'],
                email_sender=email['sender'],
                email_message_id=message_id,
                raw_content=email.get('html') or email.get('text', ''),
                received_at=processed_at or datetime.now(VN_TZ),
                retry_count=0
            )
            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)


        try:
            # 2. Extract Data: AI-first — luôn gọi GPT cho mọi email OTA
            if precheck_data and precheck_data.get("status") == "SKIPPED":
                logger.info(
                    f"[OTA Agent] ⏭️ Rule skip {precheck_data.get('booking_source')} — không phải booking, không gọi AI"
                )
                data = precheck_data
            else:
                data = self.extractor.extract_data(email['html'], email['sender'], email['subject'])
                if isinstance(data, dict):
                    data["parser_method"] = "ai"
            data = self._normalize_extracted_data(data)

            if data.get("status") == "FAILED" or "error" in data:
                raise ValueError(data.get("error", "AI Extraction returned failure"))

            # 3. Map Branch
            hotel_name = data.get('hotel_name')
            booking_source = data.get('booking_source')
            room_type = data.get('room_type') or ""

            branch_id = None
            # Website bookings: branch code is encoded in room_type, e.g. "(B2)"
            if booking_source == "Website":
                branch_id = mapper.get_branch_id_from_room_type(room_type)

            # Fallback to hotel_name-based mapping for all sources
            if not branch_id:
                branch_id = mapper.get_branch_id(hotel_name)

            data['branch_id'] = branch_id
            
            if not branch_id:
                logger.warning(f"[OTA Agent] Could not map hotel '{hotel_name}' to any branch.")
                # Vẫn lưu booking nhưng branch_id = Null

            # 4. Upsert Booking
            booking = self.upsert_booking(db, data)

            # 5. Success Log
            log_entry.status = OTAParsingStatus.SUCCESS
            log_entry.extracted_data = self._json_safe(data)
            log_entry.booking_id = booking.id if booking else None
            log_entry.error_message = None
            log_entry.error_traceback = None
            db.commit()
            if booking:
                logger.info(f"[OTA Agent] ✅ Đã xử lý booking {data.get('external_id')}")
            else:
                logger.info(f"[OTA Agent] ⏭️ Bỏ qua (không đủ thông tin hoặc không phải booking): {data.get('external_id', 'N/A')}")


        except Exception as e:
            # Enhanced error logging with full traceback
            error_traceback = traceback.format_exc()
            logger.error(f"[OTA Agent] Error processing email {email.get('uid')}: {e}")
            logger.error(f"[OTA Agent] Traceback: {error_traceback}")
            db.rollback()
            log_entry.status = OTAParsingStatus.FAILED
            log_entry.error_message = str(e)
            log_entry.error_traceback = error_traceback  # Save full traceback for debugging
            db.commit()

    def _guess_external_id(self, email: dict) -> Optional[str]:
        """Best-effort booking id guess used only for quota-saving dedupe before Gemini."""
        subject = email.get("subject") or ""
        html = email.get("html") or ""
        text = email.get("text") or ""
        body = text or re.sub(r"<[^>]+>", " ", html)
        haystack = re.sub(r"\s+", " ", f"{subject} {body[:2500]}")
        patterns = [
            r"(?:Mã đặt phòng|Ma dat phong|Booking ID|Booking Number|Booking No\.?|Reservation|Reservation no\.?|Confirmation number|Order ID|Đơn hàng|Don hang)\s*#?\s*[:：-]?\s*([A-Z0-9-]{5,})",
            r"Go2Joy[^\d]{0,40}(\d{6,})",
            r"#\s*(\d{4,})",
        ]
        for pattern in patterns:
            match = re.search(pattern, haystack, re.IGNORECASE)
            if match:
                value = match.group(1).strip().strip("#.,;:)")
                if value:
                    if pattern.endswith(r"#\s*(\d{4,})") and "binbinhotel" in (email.get("sender") or "").lower():
                        return f"WEB-{value}"
                    return value
        return None

    def _already_processed_external_id(self, db: Session, external_id: str) -> bool:
        if not external_id:
            return False
        if db.query(Booking.id).filter(Booking.external_id == external_id).first():
            return True
        return db.query(OTAParsingLog.id).filter(
            OTAParsingLog.status == OTAParsingStatus.SUCCESS,
            OTAParsingLog.extracted_data["external_id"].astext == external_id,
        ).first() is not None

    def upsert_booking(self, db: Session, data: dict) -> Booking:
        external_id = data.get('external_id')
        if not external_id:
            # Email không phải booking thật (admin/newsletter) → Gemini không parse được ID
            # Đây không phải lỗi → skip quietly, đánh dấu log SUCCESS để tránh retry
            logger.info(f"[OTA Agent] ⏭️ Bỏ qua email không có external_id (có thể là email admin/thông báo)")
            return None

        action_type = data.get('action_type', 'NEW').upper()
        
        # Check existing
        existing_booking = db.query(Booking).filter(
            Booking.booking_source == data.get('booking_source', 'Unknown'),
            Booking.external_id == external_id,
        ).first()

        if not existing_booking and int(data.get('num_rooms') or 1) > 1 and action_type != 'CANCEL':
            room_type_id = BookingService(db)._resolve_room_type_id(data.get('branch_id'), data.get('room_type'))
            if room_type_id:
                payload = self._booking_payload_from_data(data, room_type_id)
                bookings = BookingService(db).create_group_reservation(payload, user_id=None)
                return bookings[0] if bookings else None

        if not existing_booking:
            if action_type == 'CANCEL':
                # Booking chưa tồn tại mà nhận được CANCEL → bỏ qua
                # Không INSERT vì check_in/check_out sẽ null → DB constraint violation
                logger.warning(
                    f"[OTA Agent] ⏭️ Bỏ qua CANCEL cho booking chưa tồn tại: {external_id}"
                )
                return None

            else:
                # NEW or MODIFY (treat as NEW if not exists)
                # Bỏ qua nếu thiếu check_out (email không đủ thông tin, không phải lỗi thật)
                if not data.get('check_out') and action_type == 'NEW':
                    logger.warning(
                        f"[OTA Agent] ⏭️ Bỏ qua booking {external_id}: thiếu check_out "
                        f"(email có thể chỉ là thông báo, không phải xác nhận booking đầy đủ)"
                    )
                    return None
                new_booking = self._create_booking_obj(data)
                db.add(new_booking)
                db.flush()  # Get ID immediately
                return new_booking
        else:
            # Existing Found
            if action_type == 'CANCEL':
                existing_booking.status = BookingStatus.CANCELLED
                existing_booking.reservation_status = "CANCELLED"
                existing_booking.updated_at = datetime.now()
                logger.info(f"Cancelled booking {external_id}")
            else:
                # MODIFY or NEW (Duplicate NEW -> Update info)
                existing_booking.guest_name = self._safe_text(data.get('guest_name'), 255) or existing_booking.guest_name
                existing_booking.guest_phone = self._safe_text(data.get('guest_phone'), 50) or existing_booking.guest_phone
                existing_booking.checkin_code = self._safe_text(data.get('checkin_code'), 50) or existing_booking.checkin_code
                new_check_in = self._as_date(data.get('check_in'))
                new_check_out = self._as_date(data.get('check_out'))
                normalized_dates = self._normalize_booking_dates({**data, 'check_in': new_check_in, 'check_out': new_check_out})
                existing_booking.check_in = normalized_dates.get('check_in') or existing_booking.check_in
                existing_booking.check_out = normalized_dates.get('check_out') or existing_booking.check_out
                existing_booking.room_type = self._safe_text(data.get('room_type'), 255) or existing_booking.room_type
                existing_booking.num_guests = data.get('num_guests') or existing_booking.num_guests
                existing_booking.num_adults = data.get('num_adults') or existing_booking.num_adults
                existing_booking.num_children = data.get('num_children') if data.get('num_children') is not None else existing_booking.num_children
                existing_booking.total_price = data.get('total_price') or existing_booking.total_price
                existing_booking.is_prepaid = data.get('is_prepaid')
                existing_booking.payment_method = data.get('payment_method')
                # OTA tự động không dùng tiền đặt cọc; chỉ giữ total_price.
                existing_booking.deposit_amount = 0
                existing_booking.branch_id = data.get('branch_id') or existing_booking.branch_id
                existing_booking.raw_data = self._json_safe({**data, **normalized_dates})
                existing_booking.updated_at = datetime.now()
                # Status? If was cancelled, maybe reopen? Usually MODIFY implies Valid.
                existing_booking.status = BookingStatus.CONFIRMED
                existing_booking.booking_type = "OTA"
                existing_booking.reservation_status = "PENDING"
                existing_booking.confirmed_at = None
                logger.info(f"Updated booking {external_id}")
            return existing_booking

    def _booking_payload_from_data(self, data: dict, room_type_id: int) -> dict:
        data = self._normalize_booking_dates(data)
        return {
            "booking_type": "OTA",
            "booking_source": data.get('booking_source', 'Unknown'),
            "external_id": data.get('external_id'),
            "reservation_status": "PENDING",
            "branch_id": data.get('branch_id'),
            "room_type_id": room_type_id,
            "guest_name": self._safe_text(data.get('guest_name'), 255) or 'Khách OTA',
            "guest_phone": self._safe_text(data.get('guest_phone'), 50) or '',
            "check_in": str(data.get('check_in'))[:10],
            "check_out": str(data.get('check_out'))[:10],
            "num_guests": data.get('num_guests') or 1,
            "num_adults": data.get('num_adults') or data.get('num_guests') or 1,
            "num_children": data.get('num_children') or 0,
            "total_price": float(data.get('total_price') or 0),
            "currency": data.get('currency', 'VND'),
            "is_prepaid": bool(data.get('is_prepaid') or False),
            "payment_method": data.get('payment_method'),
            "deposit_amount": 0,
            "special_requests": data.get('notes'),
            "raw_data": self._json_safe(data),
            "room_items": [{
                "room_type_id": room_type_id,
                "quantity": int(data.get('num_rooms') or 1),
                "unit_total": 0,
                "reference_unit_total": 0,
                "room_type": data.get('room_type'),
            }],
        }

    def _create_booking_obj(self, data: dict) -> Booking:
        # Ensure guest_name is never None (database constraint)
        guest_name = self._safe_text(data.get('guest_name'), 255) or 'Unknown Guest'
        
        check_in = self._as_date(data.get('check_in'))
        check_out = self._as_date(data.get('check_out'))
        data = self._normalize_booking_dates({**data, 'check_in': check_in, 'check_out': check_out})
        check_in = data.get('check_in')
        check_out = data.get('check_out')

        return Booking(
            external_id=data.get('external_id'),
            booking_source=data.get('booking_source', 'Unknown'),
            guest_name=guest_name,
            guest_phone=self._safe_text(data.get('guest_phone'), 50),
            checkin_code=self._safe_text(data.get('checkin_code'), 50),
            check_in=check_in,
            check_out=check_out,
            room_type=self._safe_text(data.get('room_type'), 255),
            num_guests=data.get('num_guests', 1),
            num_adults=data.get('num_adults', 1),
            num_children=data.get('num_children', 0),
            total_price=data.get('total_price', 0),
            currency=data.get('currency', 'VND'),
            is_prepaid=data.get('is_prepaid', False),
            payment_method=data.get('payment_method'),
            # OTA tự động không dùng tiền đặt cọc; chỉ giữ total_price.
            deposit_amount=0,
            status=BookingStatus.CONFIRMED,
            branch_id=data.get('branch_id'),
            booking_type="OTA",
            reservation_status="PENDING",
            raw_data=self._json_safe(data)
        )

    def _normalize_extracted_data(self, data: dict) -> dict:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        check_in = self._as_date(normalized.get('check_in'))
        check_out = self._as_date(normalized.get('check_out'))
        if check_in:
            normalized['check_in'] = check_in
        if check_out:
            normalized['check_out'] = check_out
        normalized['guest_name'] = self._safe_text(normalized.get('guest_name'), 255) or 'Unknown Guest'
        normalized['room_type'] = self._safe_text(normalized.get('room_type'), 255)
        normalized['guest_phone'] = self._safe_text(normalized.get('guest_phone'), 50)
        normalized['checkin_code'] = self._safe_text(normalized.get('checkin_code'), 50)
        normalized['deposit_amount'] = 0
        return normalized

    def _normalize_booking_dates(self, data: dict) -> dict:
        normalized = dict(data)
        check_in = self._as_date(normalized.get('check_in'))
        check_out = self._as_date(normalized.get('check_out'))
        if check_in:
            normalized['check_in'] = check_in
        if check_out:
            normalized['check_out'] = check_out
        if check_in and check_out and check_out <= check_in:
            check_in_minutes = self._time_minutes(normalized.get('check_in_time') or normalized.get('estimated_arrival'))
            check_out_minutes = self._time_minutes(normalized.get('check_out_time') or normalized.get('estimated_departure'))
            crosses_midnight = (
                check_in == check_out
                and check_in_minutes is not None
                and check_out_minutes is not None
                and check_out_minutes <= check_in_minutes
            )
            if crosses_midnight:
                normalized['check_out'] = check_in + timedelta(days=1)
                normalized['ota_same_day_booking'] = False
                normalized['ota_cross_midnight_booking'] = True
                normalized.pop('ota_actual_check_out', None)
                return normalized
            normalized['ota_actual_check_out'] = check_out
            normalized['ota_same_day_booking'] = True
            normalized['check_out'] = check_in + timedelta(days=1)
        return normalized

    def _as_date(self, value):
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str) and value.strip():
            return date.fromisoformat(value[:10])
        return None

    def _time_minutes(self, value):
        if value is None:
            return None
        if isinstance(value, datetime) or (hasattr(value, "hour") and hasattr(value, "minute")):
            return int(value.hour) * 60 + int(value.minute)
        match = re.match(r"^\s*(\d{1,2}):(\d{2})", str(value))
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            return None
        return hour * 60 + minute

    def _safe_text(self, value, max_length: int):
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
        if not text:
            return None
        return text[:max_length]

    def _json_safe(self, value):
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: self._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        return value

# Singleton instance for Scheduler
ota_agent = OTAAgent()
