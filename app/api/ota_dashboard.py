"""
OTA Dashboard API Endpoints
"""

import asyncio
from fastapi import APIRouter, Depends, Query, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, case, or_
from app.db.session import get_db
from app.db.models import Booking, OTAParsingLog, OTAParsingStatus, BookingStatus, Branch
from app.services.ota_agent.ota_service import ota_dashboard_service
from app.services.ota_agent.gmail_service import gmail_service
from app.schemas.ota_schemas import (
    OTAStats, BookingResponse, LogResponse, OTADistribution,
    FailedEmailResponse, EmailDetailResponse, TimelineStats, HealthStatus
)
from typing import List, Optional, Any, Dict
from datetime import datetime, timedelta
import os
import base64
import json

router = APIRouter(prefix="/api/ota", tags=["OTA Dashboard"])

# Templates
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"))


# ============================================================================
# Schemas được import từ app/schemas/ota_schemas.py
# OTAStats, BookingResponse, LogResponse, OTADistribution,
# FailedEmailResponse, EmailDetailResponse, TimelineStats, HealthStatus
# ============================================================================


# ============================================================================
# UI Routes
# ============================================================================

@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def ota_dashboard_ui(request: Request):
    """Serve OTA Dashboard UI - tích hợp vào base.html"""
    user = request.session.get("user", {})
    # Lấy chi nhánh hiện tại từ session
    current_branch = request.session.get("active_branch") or user.get("last_active_branch") or ""
    user_role = (user.get("role") or "").lower()
    return templates.TemplateResponse("ota_dashboard.html", {
        "request": request,
        "user": user,
        "active_page": "ota-dashboard",
        "current_branch": current_branch,   # chi nhánh đang chọn
        "user_role": user_role,             # role để JS biết có filter không
    })


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/stats", response_model=OTAStats)
def get_ota_stats(
    branch_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get booking statistics, optionally filtered by branch"""
    from sqlalchemy import func

    # Base query — join Branch nếu cần filter
    booking_q = db.query(Booking)
    if branch_name:
        booking_q = booking_q.join(Branch, Booking.branch_id == Branch.id).filter(
            or_(Branch.name.ilike(branch_name), Branch.branch_code.ilike(branch_name))
        )

    # Tổng đặt phòng
    total_bookings = booking_q.count()

    # Đặt phòng đang xác nhận
    confirmed_count = booking_q.filter(Booking.status == BookingStatus.CONFIRMED).count()

    # Đã huỷ
    cancelled_count = booking_q.filter(Booking.status == BookingStatus.CANCELLED).count()

    # Doanh thu ước tính (tổng total_price của các booking CONFIRMED)
    revenue_row = booking_q.filter(
        Booking.status == BookingStatus.CONFIRMED
    ).with_entities(func.coalesce(func.sum(Booking.total_price), 0)).scalar()
    total_revenue = float(revenue_row or 0)

    # Thống kê theo thời gian
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    bookings_today = booking_q.filter(Booking.created_at >= today_start).count()
    bookings_this_week = booking_q.filter(Booking.created_at >= week_start).count()
    bookings_this_month = booking_q.filter(Booking.created_at >= month_start).count()

    return OTAStats(
        total_bookings=total_bookings,
        confirmed_count=confirmed_count,
        cancelled_count=cancelled_count,
        bookings_today=bookings_today,
        bookings_this_week=bookings_this_week,
        bookings_this_month=bookings_this_month,
        total_revenue=total_revenue,
    )


@router.get("/bookings", response_model=List[BookingResponse])
def get_bookings(
    limit: int = Query(200, le=500),
    offset: int = Query(0, ge=0),
    ota: Optional[str] = None,
    branch_id: Optional[int] = None,
    branch_name: Optional[str] = None,   # filter theo tên chi nhánh (dùng cho letan)
    db: Session = Depends(get_db)
):
    """Get list of bookings with filters"""
    
    query = db.query(Booking, Branch.name.label('branch_name')).outerjoin(
        Branch, Booking.branch_id == Branch.id
    ).order_by(Booking.created_at.desc())
    
    # Apply filters
    if ota:
        query = query.filter(Booking.booking_source == ota)
    
    if branch_id:
        query = query.filter(Booking.branch_id == branch_id)

    if branch_name:
        # Match cả tên đầy đủ (admin dropdown) lẫn branch code (lễ tân lưu trong session)
        # VD: "Bin Bin Hotel 10" hoặc "B10" đều khớp được
        query = query.filter(
            or_(
                Branch.name.ilike(branch_name),
                Branch.branch_code.ilike(branch_name)
            )
        )
    
    results = query.limit(limit).offset(offset).all()
    
    return [
        BookingResponse(
            id=booking.id,
            external_id=booking.external_id,
            booking_source=booking.booking_source,
            guest_name=booking.guest_name,
            guest_phone=booking.guest_phone,
            checkin_code=booking.checkin_code,
            check_in=str(booking.check_in) if booking.check_in else None,
            check_out=str(booking.check_out) if booking.check_out else None,
            room_type=booking.room_type,
            num_guests=booking.num_guests,
            num_adults=booking.num_adults,
            num_children=booking.num_children,
            total_price=float(booking.total_price),
            currency=booking.currency,
            branch_name=branch_name,
            status=booking.status.value if hasattr(booking.status, 'value') else str(booking.status),
            created_at=booking.created_at
        )
        for booking, branch_name in results
    ]


@router.get("/logs", response_model=List[LogResponse])
def get_parsing_logs(
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get parsing logs with optional status filter"""
    
    query = db.query(OTAParsingLog).order_by(OTAParsingLog.received_at.desc())
    
    if status:
        if status.upper() == "SUCCESS":
            query = query.filter(OTAParsingLog.status == OTAParsingStatus.SUCCESS)
        elif status.upper() == "FAILED":
            query = query.filter(OTAParsingLog.status == OTAParsingStatus.FAILED)
    
    logs = query.limit(limit).offset(offset).all()
    
    return [
        LogResponse(
            id=log.id,
            email_subject=log.email_subject,
            email_sender=log.email_sender,
            status=log.status.value if hasattr(log.status, 'value') else str(log.status),
            error_message=log.error_message,
            received_at=log.received_at
        )
        for log in logs
    ]


@router.get("/distribution", response_model=List[OTADistribution])
def get_ota_distribution(db: Session = Depends(get_db)):
    """Get booking distribution by OTA"""
    
    total = db.query(Booking).count()
    
    if total == 0:
        return []
    
    results = db.query(
        Booking.booking_source,
        func.count(Booking.id).label('count')
    ).group_by(Booking.booking_source).all()
    
    return [
        OTADistribution(
            ota_name=source,
            count=count,
            percentage=round(count / total * 100, 2)
        )
        for source, count in results
    ]


@router.get("/failed-emails")
def get_failed_emails(
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get list of failed emails with pagination and filters"""
    
    # Parse dates if provided
    date_from_dt = datetime.fromisoformat(date_from) if date_from else None
    date_to_dt = datetime.fromisoformat(date_to) if date_to else None
    
    result = ota_dashboard_service.get_failed_emails(
        db=db,
        limit=limit,
        offset=offset,
        date_from=date_from_dt,
        date_to=date_to_dt
    )
    
    # Format response
    items = [
        FailedEmailResponse(
            id=log.id,
            email_subject=log.email_subject,
            email_sender=log.email_sender,
            error_message=log.error_message,
            error_traceback=log.error_traceback,
            received_at=log.received_at,
            retry_count=log.retry_count or 0,
            last_retry_at=log.last_retry_at
        )
        for log in result["items"]
    ]
    
    return {
        "total": result["total"],
        "limit": result["limit"],
        "offset": result["offset"],
        "items": items
    }


@router.get("/email-detail/{log_id}")
def get_email_detail(log_id: int, db: Session = Depends(get_db)):
    """Get detailed information about a specific email log"""
    
    detail = ota_dashboard_service.get_email_detail(db=db, log_id=log_id)
    
    if not detail:
        raise HTTPException(status_code=404, detail="Email log not found")
    
    return detail


@router.post("/retry/{log_id}")
def retry_failed_email(log_id: int, db: Session = Depends(get_db)):
    """Retry processing a failed email"""
    
    result = ota_dashboard_service.retry_failed_email(db=db, log_id=log_id)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    
    return result


@router.get("/stats/timeline", response_model=TimelineStats)
def get_timeline_stats(
    period: str = Query("daily", regex="^(daily|weekly|monthly)$"),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """Get success rate and booking statistics over time"""
    
    return ota_dashboard_service.get_timeline_stats(db=db, period=period, days=days)


@router.get("/health", response_model=HealthStatus)
def get_health_status(db: Session = Depends(get_db)):
    """Get health status of OTA Agent"""
    
    return ota_dashboard_service.get_health_status(db=db)


@router.post("/mark-dead-letter/{log_id}")
def mark_as_dead_letter(log_id: int, db: Session = Depends(get_db)):
    """Mark an email as dead letter (requires manual intervention)"""
    
    success = ota_dashboard_service.mark_as_dead_letter(db=db, log_id=log_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Email log not found")
    
    return {"message": "Email marked as dead letter", "log_id": log_id}


@router.get("/metrics/enhanced")
def get_enhanced_metrics(db: Session = Depends(get_db)):
    """Get enhanced metrics for dashboard"""
    
    return ota_dashboard_service.get_enhanced_metrics(db=db)


@router.get("/analytics/error-categories")
def get_error_categories(db: Session = Depends(get_db)):
    """Get categorized error statistics"""
    
    categories = ota_dashboard_service.get_error_categories(db=db)
    
    return [
        {"category": category, "count": count}
        for category, count in categories.items()
    ]


@router.post("/bulk-retry")
def bulk_retry_emails(log_ids: List[int], db: Session = Depends(get_db)):
    """Retry multiple failed emails at once"""
    
    if not log_ids:
        raise HTTPException(status_code=400, detail="No log IDs provided")
    
    if len(log_ids) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 emails can be retried at once")
    
    result = ota_dashboard_service.bulk_retry_emails(db=db, log_ids=log_ids)
    
    return result


@router.get("/export/logs")
def export_logs(
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    format: str = Query("csv", regex="^(csv|json)$"),
    db: Session = Depends(get_db)
):
    """Export logs to CSV or JSON"""
    from fastapi.responses import StreamingResponse
    import csv
    import io
    
    query = db.query(OTAParsingLog).order_by(OTAParsingLog.received_at.desc())
    
    # Apply filters
    if status:
        if status.upper() == "SUCCESS":
            query = query.filter(OTAParsingLog.status == OTAParsingStatus.SUCCESS)
        elif status.upper() == "FAILED":
            query = query.filter(OTAParsingLog.status == OTAParsingStatus.FAILED)
    
    if date_from:
        query = query.filter(OTAParsingLog.received_at >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(OTAParsingLog.received_at <= datetime.fromisoformat(date_to))
    
    logs = query.limit(1000).all()  # Limit to 1000 records
    
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'ID', 'Subject', 'Sender', 'Status', 'Error Message',
            'Received At', 'Retry Count', 'Booking ID'
        ])
        
        # Write data
        for log in logs:
            writer.writerow([
                log.id,
                log.email_subject,
                log.email_sender,
                log.status.value if hasattr(log.status, 'value') else str(log.status),
                log.error_message or '',
                log.received_at.isoformat() if log.received_at else '',
                log.retry_count or 0,
                log.booking_id or ''
            ])
        
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=ota_logs.csv"}
        )
    else:  # JSON
        import json
        
        data = [
            {
                "id": log.id,
                "email_subject": log.email_subject,
                "email_sender": log.email_sender,
                "status": log.status.value if hasattr(log.status, 'value') else str(log.status),
                "error_message": log.error_message,
                "received_at": log.received_at.isoformat() if log.received_at else None,
                "retry_count": log.retry_count or 0,
                "booking_id": log.booking_id
            }
            for log in logs
        ]
        
        return StreamingResponse(
            iter([json.dumps(data, indent=2)]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=ota_logs.json"}
        )


@router.get("/export/failed-emails")
def export_failed_emails(
    format: str = Query("csv", regex="^(csv|json)$"),
    db: Session = Depends(get_db)
):
    """Export failed emails to CSV or JSON"""
    from fastapi.responses import StreamingResponse
    import csv
    import io
    
    logs = db.query(OTAParsingLog).filter(
        OTAParsingLog.status == OTAParsingStatus.FAILED
    ).order_by(OTAParsingLog.received_at.desc()).limit(1000).all()
    
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'ID', 'Subject', 'Sender', 'Error Message', 'Error Traceback',
            'Received At', 'Retry Count', 'Last Retry At'
        ])
        
        # Write data
        for log in logs:
            writer.writerow([
                log.id,
                log.email_subject,
                log.email_sender,
                log.error_message or '',
                log.error_traceback or '',
                log.received_at.isoformat() if log.received_at else '',
                log.retry_count or 0,
                log.last_retry_at.isoformat() if log.last_retry_at else ''
            ])
        
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=failed_emails.csv"}
        )
    else:  # JSON
        import json
        
        data = [
            {
                "id": log.id,
                "email_subject": log.email_subject,
                "email_sender": log.email_sender,
                "error_message": log.error_message,
                "error_traceback": log.error_traceback,
                "received_at": log.received_at.isoformat() if log.received_at else None,
                "retry_count": log.retry_count or 0,
                "last_retry_at": log.last_retry_at.isoformat() if log.last_retry_at else None
            }
            for log in logs
        ]
        
        return StreamingResponse(
            iter([json.dumps(data, indent=2)]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=failed_emails.json"}
        )


# ===========================================================================
# GMAIL PUSH NOTIFICATION ENDPOINTS
# ===========================================================================

@router.post("/webhook/gmail", include_in_schema=False)
async def gmail_pubsub_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    token: Optional[str] = None,
):
    """
    Endpoint hứng trigger từ Google Cloud Pub/Sub.
    Được gọi ngay khi Gmail inbox có email mới.
    LUÔN trả về 200 OK để Google không retry.
    """
    from app.core.config import settings, logger

    # Validate token (bảo vệ endpoint)
    if token and token != settings.PUBSUB_VERIFICATION_TOKEN:
        return {"status": "ignored", "reason": "invalid_token"}

    try:
        body = await request.json()
        message = body.get("message", {})
        data_base64 = message.get("data", "")

        if not data_base64:
            return {"status": "ignored", "reason": "no_data"}

        # Decode payload từ Pub/Sub (base64 → JSON)
        decoded_str = base64.b64decode(data_base64 + "==").decode("utf-8", errors="replace")
        event_data = json.loads(decoded_str)

        email_address = event_data.get("emailAddress", "")
        history_id = str(event_data.get("historyId", ""))

        if not history_id:
            return {"status": "ignored", "reason": "no_history_id"}

        logger.info(
            f"[Webhook] 📨 Gmail push received | "
            f"email={email_address} | historyId={history_id}"
        )

        # Đẩy xử lý vào Background Task (trả 200 ngay lập tức cho Google)
        background_tasks.add_task(_process_gmail_push, history_id=history_id)

        return {"status": "success", "historyId": history_id}

    except json.JSONDecodeError:
        return {"status": "error", "reason": "invalid_json"}
    except Exception as e:
        from app.core.config import logger
        logger.error(f"[Webhook] Lỗi xử lý Pub/Sub message: {e}")
        # KHÔNG raise exception - luôn trả 200 để Google không retry
        return {"status": "error", "message": str(e)}


async def _process_gmail_push(history_id: str):
    """
    Background task: Lấy email mới từ Gmail API và đưa vào pipeline xử lý.
    Tái sử dụng hoàn toàn OTAAgent.process_email() đã có sẵn.

    FIX: Mỗi email được cấp 1 DB session riêng để tránh giữ connection
    trong suốt thời gian time.sleep() của Gemini rate limiter.
    """
    from app.core.config import logger
    from app.services.ota_agent.integration import ota_agent
    from app.db.session import SessionLocal
    from app.services.ota_agent.mapper import HotelMapper

    logger.info(f"[Gmail Push] ⏳ Bắt đầu xử lý historyId={history_id}")

    try:
        # fetch_new_emails_from_history gọi Gmail API (blocking I/O) → chạy trong thread
        emails = await asyncio.to_thread(gmail_service.fetch_new_emails_from_history, history_id)

        if not emails:
            logger.info(f"[Gmail Push] Không có email OTA mới từ historyId={history_id}")
            return

        logger.info(f"[Gmail Push] Xử lý {len(emails)} email OTA mới...")

        # FIX: Mỗi email = 1 session riêng → trả connection về pool ngay sau khi xong
        # (không giữ connection trong time.sleep của Gemini retry)
        processed = 0
        for email in emails:
            db = SessionLocal()
            try:
                mapper = HotelMapper(db)
                # process_email chứa time.sleep → chạy trong thread để không block event loop
                await asyncio.to_thread(ota_agent.process_email, db, mapper, email)
                processed += 1
            except Exception as e:
                logger.error(f"[Gmail Push] Lỗi xử lý email {email.get('uid')}: {e}")
                db.rollback()
            finally:
                db.close()  # Trả về pool NGAY sau mỗi email, không chờ email khác

        logger.info(f"[Gmail Push] ✅ Xử lý xong {processed}/{len(emails)} email")

    except Exception as e:
        from app.core.config import logger
        logger.error(f"[Gmail Push] Lỗi ngầm: {e}")
        import traceback
        logger.error(traceback.format_exc())


@router.post("/scan-today")
async def manual_scan_today(
    background_tasks: BackgroundTasks,
    scan_date: Optional[str] = Query(None, description="Ngày quét (YYYY-MM-DD). Mặc định: hôm nay")
):
    """
    Quét thủ công các email OTA trong ngày chỉ định (mặc định: hôm nay).
    Dùng khi webhook bị miss hoặc muốn kiểm tra lại.
    """
    from app.core.config import logger
    from datetime import datetime, timezone, timedelta

    # Parse ngày cần quét
    if scan_date:
        try:
            target_date = datetime.strptime(scan_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="scan_date phải đúng định dạng YYYY-MM-DD")
    else:
        target_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    date_str = target_date.strftime("%d/%m/%Y")
    logger.info(f"[Manual Scan] 🔍 Bắt đầu quét email ngày {date_str}...")
    background_tasks.add_task(_scan_emails_for_date, target_date)
    return {"status": "started", "message": f"Đang quét email ngày {date_str} trong nền...", "scan_date": scan_date or "today"}


async def _scan_emails_for_date(target_date):
    """
    Background task: Quét các email OTA trong một ngày cụ thể từ Gmail API.
    target_date: datetime UTC (giờ 00:00:00 của ngày cần quét)
    """
    import asyncio
    from app.core.config import logger
    from app.services.ota_agent.integration import ota_agent
    from app.db.session import SessionLocal
    from app.services.ota_agent.mapper import HotelMapper
    from datetime import timedelta

    date_str = target_date.strftime("%d/%m/%Y")
    logger.info(f"[Manual Scan] Đang tìm email OTA ngày {date_str}...")
    try:
        service = gmail_service.build_service()
        if not service:
            logger.error("[Manual Scan] ❌ Không thể kết nối Gmail API")
            return

        ota_senders = gmail_service.ota_senders
        if not ota_senders:
            logger.warning("[Manual Scan] Không có OTA sender nào được cấu hình")
            return

        sender_query = " OR ".join([f"from:{s}" for s in ota_senders])

        # Gmail after/before dùng Unix timestamp: tìm email trong đúng ngày đó
        after_ts = int(target_date.timestamp())
        before_ts = int((target_date + timedelta(days=1)).timestamp())

        query = f"({sender_query}) after:{after_ts} before:{before_ts}"
        logger.info(f"[Manual Scan] Gmail query: {query}")

        result = service.users().messages().list(
            userId='me', q=query, maxResults=20  # Giới hạn 20 mail/lần quét
        ).execute()

        messages = result.get('messages', [])
        logger.info(f"[Manual Scan] Tìm thấy {len(messages)} email ngày {date_str} (trước lọc OTA)")

        if not messages:
            logger.info(f"[Manual Scan] ✅ Không có email OTA nào ngày {date_str}")
            return

        emails = []
        for msg_meta in messages:
            msg_id = msg_meta.get('id')
            if not msg_id:
                continue
            email = gmail_service.get_message(msg_id)
            if email and gmail_service.is_ota_sender(email['sender']):
                emails.append(email)
                logger.info(f"[Manual Scan] ✉️ OTA email: {email['sender']} | {email['subject']}")
            else:
                if email:
                    logger.debug(f"[Manual Scan] Bỏ qua (không phải OTA): {email.get('sender', '?')}")

        logger.info(f"[Manual Scan] {len(emails)} email OTA cần xử lý (sau khi lọc)")

        if not emails:
            logger.info(f"[Manual Scan] ✅ Không có email OTA nào đợc lọc ngày {date_str}")
            return

        # FIX: Mỗi email = 1 session riêng → trả connection về pool ngay sau khi xong
        processed = 0
        failed = 0
        for i, email in enumerate(emails):
            db = SessionLocal()
            try:
                mapper = HotelMapper(db)
                await asyncio.to_thread(ota_agent.process_email, db, mapper, email)
                processed += 1
            except Exception as e:
                logger.error(f"[Manual Scan] Lỗi xử lý email {email.get('uid')}: {e}")
                db.rollback()
                failed += 1
            finally:
                db.close()  # Trả về pool NGAY sau mỗi email

            # Giữ khoảng cách giữa email (Gemini RPM limit) - không cần nếu đã có _wait_for_gemini_slot()
            if i < len(emails) - 1:
                await asyncio.sleep(6)

        logger.info(
            f"[Manual Scan] ✅ Hoàn thành ngày {date_str}: "
            f"đã xử lý={processed}, thất bại={failed} / tổng {len(emails)} email OTA"
        )

    except Exception as e:
        logger.error(f"[Manual Scan] ❌ Lỗi: {e}")
        import traceback
        logger.error(traceback.format_exc())


@router.post("/gmail/watch")
def trigger_gmail_watch():
    """
    Admin: Đăng ký hoặc gia hạn Gmail Inbox Watch với Pub/Sub.
    Gọi endpoint này sau khi setup Google Cloud.
    Watch tự động gia hạn mỗi ngày lúc 06:00 qua cronjob.
    """
    from app.core.config import settings

    result = gmail_service.watch_inbox()

    if not result:
        raise HTTPException(
            status_code=503,
            detail=(
                "Không thể đăng ký Gmail Watch. Kiểm tra: "
                "1) gmail_token.json tồn tại (chạy scripts/gmail_auth.py), "
                "2) GOOGLE_PUBSUB_TOPIC đã cấu hình trong .env, "
                "3) gmail-api-push@system.gserviceaccount.com có quyền Pub/Sub Publisher"
            )
        )

    return {
        "status": "success",
        "message": "✅ Gmail Watch đã đăng ký thành công! Hệ thống sẽ nhận email real-time.",
        "history_id": result.get("historyId"),
        "expiration_ms": result.get("expiration"),
        "expiration_note": "Watch hết hạn sau 7 ngày. Cronjob sẽ tự động gia hạn mỗi ngày lúc 06:00.",
        "pubsub_topic": settings.GOOGLE_PUBSUB_TOPIC,
        "watching_email": settings.GMAIL_WATCH_EMAIL,
    }


@router.get("/gmail/status")
def get_gmail_push_status():
    """
    Kiểm tra trạng thái Gmail Push Notification setup.
    """
    status = gmail_service.get_watch_status()
    current_history_id = None

    if status.get("credentials_valid"):
        current_history_id = gmail_service.get_current_history_id()

    return {
        **status,
        "current_history_id": current_history_id,
        "webhook_url": "/api/ota/webhook/gmail",
        "setup_guide": {
            "step1": "Tạo Google Cloud Project + bật Gmail API",
            "step2": "Tạo Pub/Sub Topic + cấp quyền gmail-api-push@system.gserviceaccount.com làm Publisher",
            "step3": "Tạo Pub/Sub Subscription (Push) → URL: https://domain/api/ota/webhook/gmail?token=PUBSUB_VERIFICATION_TOKEN",
            "step4": "Chạy: python scripts/gmail_auth.py  (cần browser)",
            "step5": "Gọi: POST /api/ota/gmail/watch  để kích hoạt",
        }
    }


@router.get("/oauth/callback", include_in_schema=False)
async def gmail_oauth_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None
):
    """
    OAuth2 callback URL (tuỳ chọn - dùng khi setup qua web browser).
    Cách đơn giản hơn: chạy scripts/gmail_auth.py trực tiếp.
    """
    from app.core.config import settings

    if error:
        return HTMLResponse(
            f"<h1>❌ OAuth Error</h1><p>{error}</p>",
            status_code=400
        )

    if not code:
        return HTMLResponse("<h1>No authorization code received</h1>", status_code=400)

    if not settings.GMAIL_CLIENT_ID or not settings.GMAIL_CLIENT_SECRET:
        return HTMLResponse(
            "<h1>❌ Lỗi cấu hình</h1>"
            "<p>GMAIL_CLIENT_ID và GMAIL_CLIENT_SECRET chưa được cấu hình trong .env</p>",
            status_code=500
        )

    try:
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.GMAIL_CLIENT_ID,
                    "client_secret": settings.GMAIL_CLIENT_SECRET,
                    "redirect_uris": [settings.GMAIL_REDIRECT_URI],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=[
                'https://www.googleapis.com/auth/gmail.readonly',
                'https://www.googleapis.com/auth/gmail.modify',
            ],
        )
        flow.redirect_uri = settings.GMAIL_REDIRECT_URI
        flow.fetch_token(code=code)

        creds = flow.credentials
        gmail_service.save_token_from_json(json.loads(creds.to_json()))

        return HTMLResponse("""
        <html>
        <body style="font-family:sans-serif; max-width:600px; margin:50px auto; text-align:center;">
            <h1>✅ Gmail OAuth2 thành công!</h1>
            <p>Token đã được lưu. Bạn có thể đóng tab này.</p>
            <p>Bước tiếp theo: Gọi <code>POST /api/ota/gmail/watch</code> để kích hoạt theo dõi email.</p>
            <a href="/api/ota/gmail/status" style="display:inline-block;margin-top:20px;padding:10px 20px;
               background:#1a73e8;color:#fff;border-radius:6px;text-decoration:none;">
               Xem trạng thái Gmail
            </a>
        </body>
        </html>
        """)

    except Exception as e:
        from app.core.config import logger
        logger.error(f"[OAuth Callback] Lỗi: {e}")
        return HTMLResponse(f"<h1>❌ Lỗi</h1><p>{str(e)}</p>", status_code=500)
