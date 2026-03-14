from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models import Booking, BookingStatus, OTAParsingLog, OTAParsingStatus
from .listener import OTAListener
from .extractor import OTAExtractor
from .mapper import HotelMapper
from app.core.config import logger
from datetime import datetime
import traceback

class OTAAgent:
    def __init__(self):
        self.listener = OTAListener()
        self.extractor = OTAExtractor()

    def run_once(self):
        """
        Main entry point: Fetch mails -> Process each -> DB
        """
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

    def process_email(self, db: Session, mapper: HotelMapper, email: dict):
        logger.info(f"[OTA Agent] Processing email: {email['subject']}")

        # 0a. Subject filter: bỏ qua email không phải booking (report, newsletter...)
        from app.services.ota_agent.gmail_service import gmail_service
        if not gmail_service.is_booking_subject(email.get('subject', '')):
            return  # Bỏ qua - không tạo log, không gọi AI

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

        # 1. Init Log
        if existing_log:
            log_entry = existing_log  # Reuse log cũ cho retry
        else:
            log_entry = OTAParsingLog(
                email_subject=email['subject'],
                email_sender=email['sender'],
                email_message_id=message_id,
                raw_content=email.get('html') or email.get('text', ''),
                received_at=datetime.now(),
                retry_count=0
            )
            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)


        try:
            # 2. Extract Data (AI)
            data = self.extractor.extract_data(email['html'], email['sender'], email['subject'])
            
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
            log_entry.extracted_data = data
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
            
            log_entry.status = OTAParsingStatus.FAILED
            log_entry.error_message = str(e)
            log_entry.error_traceback = error_traceback  # Save full traceback for debugging
            db.commit()

    def upsert_booking(self, db: Session, data: dict) -> Booking:
        external_id = data.get('external_id')
        if not external_id:
            # Email không phải booking thật (admin/newsletter) → Gemini không parse được ID
            # Đây không phải lỗi → skip quietly, đánh dấu log SUCCESS để tránh retry
            logger.info(f"[OTA Agent] ⏭️ Bỏ qua email không có external_id (có thể là email admin/thông báo)")
            return None

        action_type = data.get('action_type', 'NEW').upper()
        
        # Check existing
        existing_booking = db.query(Booking).filter(Booking.external_id == external_id).first()

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
                existing_booking.updated_at = datetime.now()
                logger.info(f"Cancelled booking {external_id}")
            else:
                # MODIFY or NEW (Duplicate NEW -> Update info)
                existing_booking.guest_name = data.get('guest_name') or existing_booking.guest_name
                existing_booking.guest_phone = data.get('guest_phone') or existing_booking.guest_phone
                existing_booking.checkin_code = data.get('checkin_code') or existing_booking.checkin_code
                existing_booking.check_in = data.get('check_in') or existing_booking.check_in
                existing_booking.check_out = data.get('check_out') or existing_booking.check_out
                existing_booking.room_type = data.get('room_type') or existing_booking.room_type
                existing_booking.num_guests = data.get('num_guests') or existing_booking.num_guests
                existing_booking.num_adults = data.get('num_adults') or existing_booking.num_adults
                existing_booking.num_children = data.get('num_children') if data.get('num_children') is not None else existing_booking.num_children
                existing_booking.total_price = data.get('total_price') or existing_booking.total_price
                existing_booking.is_prepaid = data.get('is_prepaid')
                existing_booking.payment_method = data.get('payment_method')
                existing_booking.deposit_amount = data.get('deposit_amount')
                existing_booking.branch_id = data.get('branch_id') or existing_booking.branch_id
                existing_booking.raw_data = data
                existing_booking.updated_at = datetime.now()
                # Status? If was cancelled, maybe reopen? Usually MODIFY implies Valid.
                existing_booking.status = BookingStatus.CONFIRMED
                logger.info(f"Updated booking {external_id}")
            return existing_booking

    def _create_booking_obj(self, data: dict) -> Booking:
        # Ensure guest_name is never None (database constraint)
        guest_name = data.get('guest_name') or 'Unknown Guest'
        
        return Booking(
            external_id=data.get('external_id'),
            booking_source=data.get('booking_source', 'Unknown'),
            guest_name=guest_name,
            guest_phone=data.get('guest_phone'),
            checkin_code=data.get('checkin_code'),
            check_in=data.get('check_in'),
            check_out=data.get('check_out'),
            room_type=data.get('room_type'),
            num_guests=data.get('num_guests', 1),
            num_adults=data.get('num_adults', 1),
            num_children=data.get('num_children', 0),
            total_price=data.get('total_price', 0),
            currency=data.get('currency', 'VND'),
            is_prepaid=data.get('is_prepaid', False),
            payment_method=data.get('payment_method'),
            deposit_amount=data.get('deposit_amount', 0),
            status=BookingStatus.CONFIRMED,
            branch_id=data.get('branch_id'),
            raw_data=data
        )

# Singleton instance for Scheduler
ota_agent = OTAAgent()
