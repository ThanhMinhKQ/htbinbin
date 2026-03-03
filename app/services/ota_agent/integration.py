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

        # 0. Dedup: Kiểm tra message_id đã xử lý SUCCESS chưa (tránh gọi AI thừa khi quét lại)
        message_id = email.get('message_id')
        if message_id:
            existing_log = db.query(OTAParsingLog).filter(
                OTAParsingLog.email_message_id == message_id,
                OTAParsingLog.status == OTAParsingStatus.SUCCESS
            ).first()
            if existing_log:
                logger.info(
                    f"[OTA Agent] ⏭️ Bỏ qua email đã xử lý (message_id={message_id}, "
                    f"booking_id={existing_log.booking_id})"
                )
                return

        # 1. Init Log with enhanced fields
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
            branch_id = mapper.get_branch_id(hotel_name)
            data['branch_id'] = branch_id
            
            if not branch_id:
                logger.warning(f"[OTA Agent] Could not map hotel '{hotel_name}' to any branch.")
                # Vẫn lưu booking nhưng branch_id = Null

            # 4. Upsert Booking
            booking = self.upsert_booking(db, data)

            # 5. Success Log with extracted data and booking link
            log_entry.status = OTAParsingStatus.SUCCESS
            log_entry.extracted_data = data  # Save AI extracted data
            log_entry.booking_id = booking.id if booking else None  # Link to booking
            log_entry.error_message = None  # Clear any previous errors
            log_entry.error_traceback = None
            db.commit()
            logger.info(f"[OTA Agent] Successfully processed booking {data.get('external_id')}")

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
            raise ValueError("Missing external_id from Extractor")

        action_type = data.get('action_type', 'NEW').upper()
        
        # Check existing
        existing_booking = db.query(Booking).filter(Booking.external_id == external_id).first()

        if not existing_booking:
            if action_type == 'CANCEL':
                # Trường hợp đặc biệt: Nhận mail hủy trước khi nhận mail đặt (hiếm gặp)
                # Hoặc mail rác. Vẫn tạo nhưng set status cancel
                logger.warning(f"Received CANCEL for non-existent booking {external_id}")
                new_booking = self._create_booking_obj(data)
                new_booking.status = BookingStatus.CANCELLED
                db.add(new_booking)
                db.flush()  # Get ID immediately
                return new_booking
            else:
                # NEW or MODIFY (treat as NEW if not exists)
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
