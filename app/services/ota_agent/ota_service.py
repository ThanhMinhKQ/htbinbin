"""
OTA Dashboard Service Layer
Business logic for OTA Dashboard operations
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from app.db.models import OTAParsingLog, Booking, OTAParsingStatus, BookingStatus
from app.services.ota_agent.extractor import OTAExtractor
from app.services.ota_agent.mapper import HotelMapper
from app.services.ota_agent.rule_extractor import RuleBasedOTAExtractor, is_confident_booking
from app.services.booking_service import BookingService
from app.core.config import logger
from datetime import date, datetime, timedelta, timezone
from typing import List, Dict, Optional
import re
import traceback
import json


class OTADashboardService:
    """Service layer for OTA Dashboard operations"""

    def __init__(self):
        self.extractor = OTAExtractor()
        self.rule_extractor = RuleBasedOTAExtractor()

    def _json_safe(self, value):
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: self._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        return value

    def _fallback_external_id(self, extracted: Dict, log: OTAParsingLog) -> str:
        booking_source = str(extracted.get("booking_source") or "OTA").upper().replace(" ", "")
        subject = log.email_subject or ""
        if booking_source == "WEBSITE":
            order_match = re.search(r"#\s*([A-Za-z0-9_-]+)", subject)
            if order_match:
                return f"WEB-{order_match.group(1)}"
        return f"{booking_source}-{log.id}"
    
    def get_failed_emails(
        self, 
        db: Session, 
        limit: int = 50, 
        offset: int = 0,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> Dict:
        """Get list of failed emails with filters"""
        
        query = db.query(OTAParsingLog).filter(
            OTAParsingLog.status == OTAParsingStatus.FAILED
        )
        
        # Apply date filters
        if date_from:
            query = query.filter(OTAParsingLog.received_at >= date_from)
        if date_to:
            query = query.filter(OTAParsingLog.received_at <= date_to)
        
        # Get total count
        total = query.count()
        
        # Get paginated results
        logs = query.order_by(OTAParsingLog.received_at.desc()).limit(limit).offset(offset).all()
        
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": logs
        }
    
    def get_email_detail(self, db: Session, log_id: int) -> Optional[Dict]:
        """Get detailed information about a specific email log"""
        
        log = db.query(OTAParsingLog).filter(OTAParsingLog.id == log_id).first()
        
        if not log:
            return None
        
        return {
            "id": log.id,
            "email_subject": log.email_subject,
            "email_sender": log.email_sender,
            "email_message_id": log.email_message_id,
            "received_at": log.received_at,
            "status": log.status.value if hasattr(log.status, 'value') else str(log.status),
            "error_message": log.error_message,
            "error_traceback": log.error_traceback,
            "raw_content": log.raw_content,
            "extracted_data": log.extracted_data,
            "retry_count": log.retry_count,
            "last_retry_at": log.last_retry_at,
            "booking_id": log.booking_id,
            "booking": {
                "id": log.booking.id,
                "external_id": log.booking.external_id,
                "guest_name": log.booking.guest_name,
                "status": log.booking.status.value if hasattr(log.booking.status, 'value') else str(log.booking.status)
            } if log.booking else None
        }
    
    def retry_failed_email(self, db: Session, log_id: int) -> Dict:
        """Retry processing a failed email"""
        
        log = db.query(OTAParsingLog).filter(OTAParsingLog.id == log_id).first()
        
        if not log:
            return {"success": False, "error": "Log not found"}
        
        if log.status != OTAParsingStatus.FAILED:
            return {"success": False, "error": "Only failed emails can be retried"}
        if (log.error_message or "").startswith("[RETRYING]"):
            log.error_message = None
            db.commit()

        # Check retry limit
        if (log.retry_count or 0) >= 999:
            return {"success": False, "error": "Email này đã được đánh dấu Dead Letter Queue, không thể retry."}

        try:
            logger.info(f"[OTA Dashboard] Retrying email log ID: {log_id}")

            email = {
                "subject": log.email_subject or "",
                "sender": log.email_sender or "",
                "html": log.raw_content or "",
                "text": log.raw_content or "",
                "date": log.received_at,
                "message_id": log.email_message_id,
            }
            from app.services.ota_agent.integration import OTAAgent
            agent = OTAAgent()
            extracted = agent._extract_ai_data(email)
            extracted = agent._normalize_extracted_data(extracted)
            agent._validate_extracted_booking(extracted)
            extracted = self._json_safe(extracted)

            if extracted.get("action_type") == "SKIP" or extracted.get("status") == "SKIPPED":
                log.status = OTAParsingStatus.SUCCESS
                log.extracted_data = extracted
                log.error_message = None
                log.error_traceback = None
                log.retry_count += 1
                log.last_retry_at = datetime.now(timezone.utc)
                log.booking_id = None
                db.commit()
                return {
                    "success": True,
                    "message": "Email skipped as non-booking",
                    "booking_id": None,
                    "booking_external_id": None,
                    "retry_count": log.retry_count
                }

            if extracted.get("status") == "FAILED":
                # Retry failed
                log.retry_count += 1
                log.last_retry_at = datetime.now(timezone.utc)
                log.error_message = extracted.get("error", "Unknown error during retry")
                log.error_traceback = traceback.format_exc()
                db.commit()
                
                return {
                    "success": False,
                    "error": extracted.get("error"),
                    "retry_count": log.retry_count
                }
            
            # Extraction successful
            log.extracted_data = extracted
            external_id = str(extracted.get("external_id") or "").strip()
            if not external_id:
                external_id = self._fallback_external_id(extracted, log)
                extracted["external_id"] = external_id

            # Try to map hotel and create booking
            mapper = HotelMapper(db)
            hotel_name = extracted.get("hotel_name", "")
            booking_source = extracted.get("booking_source")
            room_type = extracted.get("room_type") or ""

            branch_id = None
            # Website bookings: branch code is encoded in room_type, e.g. "(B2)"
            if booking_source == "Website":
                branch_id = mapper.get_branch_id_from_room_type(room_type)

            # Fallback to hotel_name-based mapping for all sources
            if not branch_id:
                branch_id = mapper.get_branch_id(hotel_name)

            extracted['branch_id'] = branch_id
            booking = agent.upsert_booking(db, extracted)
            if booking and not (booking.raw_data or {}).get("group_total"):
                BookingService(db).stage_ota_booking_for_review(booking, user_id=None)
            
            # Update log
            log.status = OTAParsingStatus.SUCCESS
            log.error_message = None
            log.error_traceback = None
            log.retry_count += 1
            log.last_retry_at = datetime.now(timezone.utc)
            log.booking_id = booking.id if booking else None

            db.commit()

            return {
                "success": True,
                "message": "Email processed successfully",
                "booking_id": booking.id if booking else None,
                "booking_external_id": booking.external_id if booking else None,
                "retry_count": log.retry_count
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"[OTA Dashboard] Retry error: {e}")
            
            # Update retry count
            log.retry_count += 1
            log.last_retry_at = datetime.now(timezone.utc)
            log.error_message = str(e)
            log.error_traceback = traceback.format_exc()
            db.commit()
            
            return {
                "success": False,
                "error": str(e),
                "retry_count": log.retry_count
            }
    
    def get_timeline_stats(self, db: Session, period: str = "daily", days: int = 30) -> Dict:
        """Get success rate and booking statistics over time"""
        
        from sqlalchemy import Integer, case
        
        now = datetime.now(timezone.utc)
        start_date = now - timedelta(days=days)
        
        if period == "daily":
            # Group by day
            date_trunc = func.date_trunc('day', OTAParsingLog.received_at)
        elif period == "weekly":
            # Group by week
            date_trunc = func.date_trunc('week', OTAParsingLog.received_at)
        else:  # monthly
            # Group by month
            date_trunc = func.date_trunc('month', OTAParsingLog.received_at)
        
        # Get log statistics - use CASE for conditional counting
        log_stats = db.query(
            date_trunc.label('period'),
            func.count(OTAParsingLog.id).label('total'),
            func.sum(
                case((OTAParsingLog.status == OTAParsingStatus.SUCCESS, 1), else_=0)
            ).label('success'),
            func.sum(
                case((OTAParsingLog.status == OTAParsingStatus.FAILED, 1), else_=0)
            ).label('failed')
        ).filter(
            OTAParsingLog.received_at >= start_date
        ).group_by('period').order_by('period').all()
        
        # Get booking statistics
        booking_date_trunc = func.date_trunc('day' if period == 'daily' else 'week' if period == 'weekly' else 'month', Booking.created_at)
        booking_stats = db.query(
            booking_date_trunc.label('period'),
            func.count(Booking.id).label('count'),
            Booking.booking_source
        ).filter(
            Booking.created_at >= start_date
        ).group_by('period', Booking.booking_source).order_by('period').all()
        
        # Format results
        timeline = []
        for stat in log_stats:
            success_rate = (stat.success / stat.total * 100) if stat.total > 0 else 0
            timeline.append({
                "period": stat.period.isoformat() if stat.period else None,
                "total_logs": stat.total,
                "success_count": stat.success or 0,
                "failed_count": stat.failed or 0,
                "success_rate": round(success_rate, 2)
            })
        
        # Format booking stats by OTA
        booking_timeline = {}
        for stat in booking_stats:
            period_str = stat.period.isoformat() if stat.period else "unknown"
            if period_str not in booking_timeline:
                booking_timeline[period_str] = {}
            booking_timeline[period_str][stat.booking_source] = stat.count
        
        return {
            "period": period,
            "days": days,
            "timeline": timeline,
            "booking_timeline": booking_timeline
        }
    
    def get_health_status(self, db: Session) -> Dict:
        """Get health status of OTA Agent"""
        
        # Get last successful sync
        last_success = db.query(OTAParsingLog).filter(
            OTAParsingLog.status == OTAParsingStatus.SUCCESS
        ).order_by(OTAParsingLog.received_at.desc()).first()
        
        # Get recent failures (last 24h)
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        recent_failures = db.query(OTAParsingLog).filter(
            and_(
                OTAParsingLog.status == OTAParsingStatus.FAILED,
                OTAParsingLog.received_at >= yesterday
            )
        ).count()
        
        # Get total logs today
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        logs_today = db.query(OTAParsingLog).filter(
            OTAParsingLog.received_at >= today_start
        ).count()
        
        # Check if system is healthy
        is_healthy = True
        warnings = []
        
        if last_success:
            time_since_last = datetime.now(timezone.utc) - last_success.received_at
            if time_since_last > timedelta(hours=2):
                is_healthy = False
                warnings.append(f"No successful sync in {time_since_last.seconds // 3600} hours")
        else:
            is_healthy = False
            warnings.append("No successful syncs found")
        
        if recent_failures > 5:
            warnings.append(f"{recent_failures} failures in last 24 hours")
        
        # Check Gmail token health
        from app.services.ota_agent.gmail_service import gmail_service
        token_health = gmail_service.check_token_health()
        if not token_health["valid"]:
            is_healthy = False
            if token_health.get("revoked"):
                warnings.append("Gmail token bị revoke — cần re-authenticate tại /api/ota/oauth/start")
            elif token_health.get("error"):
                warnings.append(f"Gmail token lỗi: {token_health['error']}")
        elif token_health.get("days_until_expiry") is not None and token_health["days_until_expiry"] <= 7:
            warnings.append(f"Gmail token sắp hết hạn trong {token_health['days_until_expiry']} ngày — re-auth sớm tại /api/ota/oauth/start")

        return {
            "is_healthy": is_healthy,
            "last_success_at": last_success.received_at if last_success else None,
            "logs_today": logs_today,
            "recent_failures_24h": recent_failures,
            "warnings": warnings,
            "ai_api_configured": bool(self.extractor.client),
            "gmail_token": token_health,
        }
    
    def mark_as_dead_letter(self, db: Session, log_id: int) -> bool:
        """Mark an email as dead letter (manual intervention required)"""
        
        log = db.query(OTAParsingLog).filter(OTAParsingLog.id == log_id).first()
        
        if not log:
            return False
        
        # Add a special marker in error_message
        log.error_message = f"[DEAD LETTER QUEUE] {log.error_message or 'Manual review required'}"
        log.retry_count = 999  # Special marker for DLQ
        db.commit()
        
        logger.warning(f"[OTA Dashboard] Email {log_id} moved to Dead Letter Queue")
        return True
    
    def get_enhanced_metrics(self, db: Session) -> Dict:
        """Get enhanced metrics for dashboard"""
        
        try:
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Emails processed today
            emails_today = db.query(OTAParsingLog).filter(
                OTAParsingLog.received_at >= today_start
            ).count()
            
            # Dead Letter Queue count
            dlq_count = db.query(OTAParsingLog).filter(
                OTAParsingLog.retry_count >= 999
            ).count()
            
            # Average processing time (estimate based on retry timing)
            avg_processing_time = 0  # Placeholder - would need actual timing data
            
            # Active alerts - calculate directly to avoid calling get_health_status
            active_alerts = 0
            try:
                # Check for recent failures
                yesterday = datetime.now(timezone.utc) - timedelta(days=1)
                recent_failures = db.query(OTAParsingLog).filter(
                    and_(
                        OTAParsingLog.status == OTAParsingStatus.FAILED,
                        OTAParsingLog.received_at >= yesterday
                    )
                ).count()
                
                if recent_failures > 5:
                    active_alerts += 1
                
                # Check for stale syncs
                last_success = db.query(OTAParsingLog).filter(
                    OTAParsingLog.status == OTAParsingStatus.SUCCESS
                ).order_by(OTAParsingLog.received_at.desc()).first()
                
                if last_success:
                    time_since_last = datetime.now(timezone.utc) - last_success.received_at
                    if time_since_last > timedelta(hours=2):
                        active_alerts += 1
                else:
                    active_alerts += 1
            except Exception as e:
                logger.error(f"Error calculating active alerts: {e}")
                active_alerts = 0
            
            return {
                "emails_today": emails_today,
                "dlq_count": dlq_count,
                "avg_processing_time": avg_processing_time,
                "active_alerts": active_alerts
            }
        except Exception as e:
            logger.error(f"Error in get_enhanced_metrics: {e}")
            return {
                "emails_today": 0,
                "dlq_count": 0,
                "avg_processing_time": 0,
                "active_alerts": 0
            }
    
    def get_error_categories(self, db: Session) -> Dict:
        """Get categorized error statistics"""
        
        failed_logs = db.query(OTAParsingLog).filter(
            OTAParsingLog.status == OTAParsingStatus.FAILED
        ).all()
        
        categories = {
            "AI Extraction Failed": 0,
            "Hotel Mapping Failed": 0,
            "Database Error": 0,
            "Validation Error": 0,
            "Unknown Error": 0
        }
        
        for log in failed_logs:
            error_msg = (log.error_message or "").lower()
            
            if "extraction" in error_msg or "ai" in error_msg or "gemini" in error_msg or "gpt" in error_msg:
                categories["AI Extraction Failed"] += 1
            elif "hotel" in error_msg or "branch" in error_msg or "map" in error_msg:
                categories["Hotel Mapping Failed"] += 1
            elif "database" in error_msg or "sql" in error_msg or "integrity" in error_msg:
                categories["Database Error"] += 1
            elif "validation" in error_msg or "missing" in error_msg or "invalid" in error_msg:
                categories["Validation Error"] += 1
            else:
                categories["Unknown Error"] += 1
        
        return categories
    
    def bulk_retry_emails(self, db: Session, log_ids: List[int]) -> Dict:
        """Retry multiple failed emails at once"""
        
        results = {
            "total": len(log_ids),
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "details": []
        }
        
        for log_id in log_ids:
            try:
                result = self.retry_failed_email(db, log_id)
                
                if result.get("success"):
                    results["success"] += 1
                    results["details"].append({
                        "log_id": log_id,
                        "status": "success",
                        "booking_id": result.get("booking_id")
                    })
                else:
                    if "Maximum retry" in result.get("error", ""):
                        results["skipped"] += 1
                        results["details"].append({
                            "log_id": log_id,
                            "status": "skipped",
                            "reason": "Max retries reached"
                        })
                    else:
                        results["failed"] += 1
                        results["details"].append({
                            "log_id": log_id,
                            "status": "failed",
                            "error": result.get("error")
                        })
            except Exception as e:
                results["failed"] += 1
                results["details"].append({
                    "log_id": log_id,
                    "status": "failed",
                    "error": str(e)
                })
        
        return results


# Singleton instance
ota_dashboard_service = OTADashboardService()
