"""
OTA Dashboard API Endpoints
"""

import asyncio
from fastapi import APIRouter, Depends, Query, Request, HTTPException, BackgroundTasks  # type: ignore
from fastapi.responses import HTMLResponse  # type: ignore
from fastapi.templating import Jinja2Templates  # type: ignore
from sqlalchemy.orm import Session  # type: ignore
from sqlalchemy import func, case, or_, and_  # type: ignore
from app.db.session import get_db  # type: ignore
from app.db.models import Booking, OTAParsingLog, OTAParsingStatus, BookingStatus, Branch  # type: ignore
from app.services.ota_agent.ota_service import ota_dashboard_service  # type: ignore
from app.services.ota_agent.gmail_service import gmail_service  # type: ignore
from app.schemas.ota_schemas import (  # type: ignore
    OTAStats, BookingResponse, BookingUpdateRequest, LogResponse, OTADistribution,  # type: ignore
    FailedEmailResponse, EmailDetailResponse, TimelineStats, HealthStatus  # type: ignore
)  # type: ignore
from typing import List, Optional, Any, Dict
from datetime import datetime, timedelta, date
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

@router.get("/branches")
def list_branches(db: Session = Depends(get_db)):
    """Danh sách chi nhánh tham gia OTA: chỉ Bin Bin Hotel 1, 2, ... (loại Quản lí, v.v.), sắp xếp đúng thứ tự."""
    import re
    branches = (
        db.query(Branch)
        .filter(Branch.name.ilike("Bin Bin Hotel%"))
        .all()
    )
    out = [{"id": b.id, "name": b.name, "branch_code": (b.branch_code or b.name)} for b in branches]

    def sort_key(item):
        name = item.get("name") or ""
        m = re.search(r"(\d+)\s*$", name.strip())
        return (0, int(m.group(1))) if m else (1, name)

    out.sort(key=sort_key)
    return out


@router.get("/stats", response_model=OTAStats)
def get_ota_stats(
    branch_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get booking statistics, optionally filtered by branch"""
    from sqlalchemy import func  # type: ignore

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

    # Doanh thu ước tính (tổng total_price của CONFIRMED + COMPLETED + NO_SHOW đã thanh toán)
    revenue_row = booking_q.filter(
        or_(
            Booking.status == BookingStatus.CONFIRMED,
            Booking.status == BookingStatus.COMPLETED,
            and_(Booking.status == BookingStatus.NO_SHOW, Booking.is_prepaid == True)
        )
    ).with_entities(func.coalesce(func.sum(Booking.total_price), 0)).scalar()
    total_revenue = float(revenue_row or 0)

    # Thống kê theo thời gian
    from datetime import timezone
    vn_tz = timezone(timedelta(hours=7))
    now = datetime.now(vn_tz)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_date = now.date()  # Ngày hôm nay dạng date object
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    # Đơn trong ngày: đếm theo ngày CHECK-IN (đơn sẽ nhận phòng hôm nay)
    bookings_today = booking_q.filter(Booking.check_in == today_date).count()
    bookings_this_week = booking_q.filter(Booking.created_at >= week_start).count()
    bookings_this_month = booking_q.filter(Booking.created_at >= month_start).count()

    # Lấy thông tin đơn bị huỷ gần nhất
    latest_cancelled = booking_q.filter(Booking.status == BookingStatus.CANCELLED).order_by(Booking.updated_at.desc()).first()
    latest_cancelled_id = latest_cancelled.external_id if latest_cancelled else None

    return OTAStats(
        total_bookings=total_bookings,
        confirmed_count=confirmed_count,
        cancelled_count=cancelled_count,
        bookings_today=bookings_today,
        bookings_this_week=bookings_this_week,
        bookings_this_month=bookings_this_month,
        total_revenue=total_revenue,
        latest_cancelled_id=latest_cancelled_id,
    )


def _extract_special_requests(raw_data: dict) -> Optional[str]:
    """Trích yêu cầu đặc biệt của khách từ raw_data JSON (Gemini đã parse)."""
    if not raw_data or not isinstance(raw_data, dict):
        return None
    # Thử các key phổ biến từ các OTA khác nhau
    for key in ('special_requests', 'special_request', 'guest_requests',
                'guest_notes', 'notes', 'remarks', 'requests'):
        val = raw_data.get(key)
        if val and str(val).strip() and str(val).strip().lower() not in ('none', 'null', '-', 'n/a', ''):
            return str(val).strip()
    return None


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
    ).order_by(func.coalesce(Booking.updated_at, Booking.created_at).desc())
    
    # Apply filters
    if ota:
        query = query.filter(Booking.booking_source == ota)
    
    if branch_id:
        query = query.filter(Booking.branch_id == branch_id)

    if branch_name:
        # Chỉ hiển thị booking có branch_id thuộc chi nhánh này (gồm cả bản sao chỉ đọc để lại khi chuyển)
        branch_ids = [
            b.id for b in db.query(Branch).filter(
                or_(Branch.name.ilike(branch_name), Branch.branch_code.ilike(branch_name))
            ).all()
            if b.id
        ]
        if branch_ids:
            query = query.filter(Booking.branch_id.in_(branch_ids))
        else:
            query = query.filter(Booking.branch_id == -1)  # no match

    results = query.limit(limit).offset(offset).all()

    def _is_readonly_copy(booking):
        return getattr(booking, "source_booking_id", None) is not None

    return [
        BookingResponse(
            id=booking.id,
            external_id=booking.external_id,
            booking_source=booking.booking_source,
            guest_name=booking.guest_name,
            guest_phone=booking.guest_phone,
            checkin_code=booking.checkin_code,
            check_in=str(booking.check_in) if booking.check_in else None,
            check_in_time=(booking.raw_data or {}).get('check_in_time') or None,
            check_out=str(booking.check_out) if booking.check_out else None,
            check_out_time=(booking.raw_data or {}).get('check_out_time') or None,
            room_type=booking.room_type,
            num_rooms=int((booking.raw_data or {}).get('num_rooms') or 1),
            num_guests=booking.num_guests,
            num_adults=booking.num_adults,
            num_children=booking.num_children,
            total_price=float(booking.total_price),
            currency=booking.currency,
            branch_name=current_branch_name,
            original_branch_name=(booking.raw_data or {}).get("original_branch_name") or None,
            is_readonly_copy=_is_readonly_copy(booking),
            status=booking.status.value if hasattr(booking.status, 'value') else str(booking.status),
            special_requests=_extract_special_requests(booking.raw_data),
            created_at=booking.created_at,
            updated_at=getattr(booking, "updated_at", None),
            is_prepaid=booking.is_prepaid
        )
        for booking, current_branch_name in results
    ]


@router.put("/bookings/{booking_id}", response_model=BookingResponse)
def update_booking(
    booking_id: int,
    payload: BookingUpdateRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """Admin-only: Cập nhật thông tin booking bị AI trích xuất sai/thiếu."""
    user = request.session.get("user", {})
    user_role = (user.get("role") or "").lower()
    ADMIN_ROLES = {"admin", "quanly", "manager", "boss"}
    is_admin = user_role in ADMIN_ROLES
    is_letan = user_role == "letan"

    # Chỉ admin và lễ tân mới được chỉnh sửa (với phạm vi khác nhau)
    if not is_admin and not is_letan:
        raise HTTPException(status_code=403, detail="Bạn không có quyền chỉnh sửa phiếu đặt phòng này.")

    from datetime import datetime, date

    # Lấy booking
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy phiếu đặt phòng #{booking_id}.")
    if getattr(booking, "source_booking_id", None) is not None:
        raise HTTPException(status_code=403, detail="Đây là bản sao chỉ xem (đã chuyển chi nhánh). Không thể chỉnh sửa.")

    # Lưu lại trạng thái cũ để so sánh và ghi chú
    from datetime import datetime, date
    old_status = booking.status
    old_check_in = booking.check_in
    old_check_out = booking.check_out
    old_branch_id = booking.branch_id
    old_room_type = booking.room_type
    old_num_rooms = (booking.raw_data or {}).get("num_rooms")
    old_created_at = booking.created_at

    # Cập nhật các trường trong DB
    if is_admin:
        # Admin: được phép chỉnh toàn bộ (giống logic cũ)
        if payload.guest_name is not None:
            booking.guest_name = payload.guest_name
        if payload.guest_phone is not None:
            booking.guest_phone = payload.guest_phone
        if payload.room_type is not None:
            booking.room_type = payload.room_type
        if payload.num_guests is not None:
            booking.num_guests = payload.num_guests
        if payload.num_adults is not None:
            booking.num_adults = payload.num_adults
        if payload.num_children is not None:
            booking.num_children = payload.num_children
        if payload.total_price is not None:
            booking.total_price = payload.total_price
        if payload.currency is not None:
            booking.currency = payload.currency
        if payload.checkin_code is not None:
            booking.checkin_code = payload.checkin_code
        if payload.check_in is not None:
            booking.check_in = date.fromisoformat(payload.check_in)
        if payload.check_out is not None:
            booking.check_out = date.fromisoformat(payload.check_out)
        if payload.status is not None:
            try:
                new_status = BookingStatus[payload.status.upper()]

                # Admin: vẫn kiểm soát NO_SHOW theo NGÀY (không cần đến đúng giờ)
                if new_status == BookingStatus.NO_SHOW:
                    co_date = payload.check_out if payload.check_out is not None else booking.check_out
                    if co_date:
                        if isinstance(co_date, str):
                            co_date_obj = date.fromisoformat(co_date)
                        else:
                            co_date_obj = co_date
                        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
                        today = _dt.now(_tz(_td(hours=7))).date()
                        if today < co_date_obj:
                            raise HTTPException(
                                status_code=400,
                                detail="Chỉ có thể đổi thành No-show khi đã đến/qua ngày check-out của đơn phòng này."
                            )

                elif new_status == BookingStatus.COMPLETED:
                    ci_date = payload.check_in if payload.check_in is not None else booking.check_in
                    if ci_date:
                        if isinstance(ci_date, str):
                            ci_date_obj = date.fromisoformat(ci_date)
                        else:
                            ci_date_obj = ci_date
                        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
                        today = _dt.now(_tz(_td(hours=7))).date()
                        if today < ci_date_obj:
                            raise HTTPException(
                                status_code=400,
                                detail="Chỉ có thể chuyển sang Hoàn thành khi đã đến/qua ngày check-in của đơn phòng này."
                            )

                booking.status = new_status
            except KeyError:
                raise HTTPException(status_code=400, detail=f"Trạng thái không hợp lệ: {payload.status}")
        if payload.is_prepaid is not None:
            booking.is_prepaid = payload.is_prepaid
    else:
        # Lễ tân: chỉ được chỉnh ngày/giờ, yêu cầu, chi nhánh, thanh toán (một chiều) và trạng thái cho phép
        if payload.check_in is not None:
            booking.check_in = date.fromisoformat(payload.check_in)
        if payload.check_out is not None:
            booking.check_out = date.fromisoformat(payload.check_out)

        # Trạng thái: chỉ cho phép chuyển sang COMPLETED (Hoàn thành) hoặc NO_SHOW với điều kiện theo NGÀY
        if payload.status is not None:
            try:
                new_status = BookingStatus[payload.status.upper()]
            except KeyError:
                raise HTTPException(status_code=400, detail=f"Trạng thái không hợp lệ: {payload.status}")

            from datetime import datetime as _dt
            today = _dt.now().date()

            if new_status == BookingStatus.NO_SHOW:
                # Điều kiện: chỉ mở khi đến/qua NGÀY check-out (00:00)
                co_date = payload.check_out if payload.check_out is not None else booking.check_out
                if co_date:
                    if isinstance(co_date, str):
                        co_date_obj = date.fromisoformat(co_date)
                    else:
                        co_date_obj = co_date
                    if today < co_date_obj:
                        raise HTTPException(
                            status_code=400,
                            detail="Chỉ có thể đánh No-show khi đã đến/qua ngày check-out của đơn phòng này."
                        )
                booking.status = new_status

            elif new_status == BookingStatus.COMPLETED:
                # Điều kiện: chỉ mở khi đến/qua NGÀY check-in (00:00)
                ci_date = payload.check_in if payload.check_in is not None else booking.check_in
                if ci_date:
                    if isinstance(ci_date, str):
                        ci_date_obj = date.fromisoformat(ci_date)
                    else:
                        ci_date_obj = ci_date
                    if today < ci_date_obj:
                        raise HTTPException(
                            status_code=400,
                            detail="Chỉ có thể chuyển sang Hoàn thành khi đã đến/qua ngày check-in của đơn phòng này."
                        )
                booking.status = new_status
            else:
                # Các trạng thái khác lễ tân không được phép đổi trực tiếp
                raise HTTPException(status_code=403, detail="Lễ tân chỉ được phép đánh No-show hoặc Hoàn thành.")

        # Thanh toán: chỉ cho phép chuyển từ chưa thanh toán sang đã thanh toán, không cho đảo chiều
        if payload.is_prepaid is not None:
            current = booking.is_prepaid
            # Nếu đang chưa thanh toán (False hoặc None) → cho phép set True
            if (current is False or current is None) and payload.is_prepaid is True:
                booking.is_prepaid = True
            # Không cho phép giảm từ True về False
            elif current is True and payload.is_prepaid is False:
                raise HTTPException(
                    status_code=400,
                    detail="Không thể chuyển từ đã thanh toán sang chưa thanh toán."
                )
            # Các trường hợp còn lại: giữ nguyên, bỏ qua thay đổi

    # Xử lý branch_name: chuyển chi nhánh → tạo bản sao chỉ đọc tại chi nhánh cũ, bản gốc chuyển sang chi nhánh mới
    old_branch_name = None
    if old_branch_id:
        old_branch = db.query(Branch).filter(Branch.id == old_branch_id).first()
        old_branch_name = old_branch.name if old_branch else None
    new_branch_name_for_note = None
    if payload.branch_name is not None:
        if payload.branch_name.strip() == "":
            booking.branch_id = None
        else:
            new_branch = db.query(Branch).filter(Branch.name == payload.branch_name).first()
            if not new_branch:
                raise HTTPException(status_code=400, detail=f"Không tìm thấy chi nhánh: {payload.branch_name}")
            new_branch_id = new_branch.id
            if old_branch_id and int(new_branch_id) != int(old_branch_id):
                # Chuyển chi nhánh thật sự: tạo bản sao chỉ đọc tại chi nhánh cũ
                copy_external_id = f"{booking.external_id} Copy"
                copy_raw = dict(booking.raw_data or {})
                transfer_note = (
                    f"Đã chuyển sang {new_branch.name} vào {datetime.now().strftime('%d/%m/%Y %H:%M')}"
                )
                existing_req = (copy_raw.get("special_requests") or copy_raw.get("special_request") or "").strip()
                copy_raw["special_requests"] = (
                    f"{existing_req}\n{transfer_note}".strip() if existing_req else transfer_note
                )
                copy_booking = Booking(
                    booking_source=booking.booking_source,
                    external_id=copy_external_id,
                    guest_name=booking.guest_name,
                    guest_phone=booking.guest_phone,
                    checkin_code=booking.checkin_code,
                    check_in=booking.check_in,
                    check_out=booking.check_out,
                    room_type=booking.room_type,
                    num_guests=booking.num_guests,
                    num_adults=booking.num_adults,
                    num_children=booking.num_children,
                    total_price=booking.total_price,
                    currency=booking.currency or "VND",
                    is_prepaid=booking.is_prepaid,
                    payment_method=booking.payment_method,
                    deposit_amount=booking.deposit_amount or 0,
                    status=booking.status,
                    branch_id=old_branch_id,
                    source_booking_id=booking.id,
                    raw_data=copy_raw,
                )
                db.add(copy_booking)
                db.flush()
            raw = dict(booking.raw_data or {})
            if old_branch_id and 'original_branch_name' not in raw:
                raw['original_branch_name'] = old_branch_name
            booking.raw_data = raw
            booking.branch_id = new_branch.id
            new_branch_name_for_note = new_branch.name

    # Cập nhật raw_data cho các trường lưu trong JSON
    raw = dict(booking.raw_data or {})
    if payload.check_in_time is not None:
        raw['check_in_time'] = payload.check_in_time
    if payload.check_out_time is not None:
        raw['check_out_time'] = payload.check_out_time
    if payload.num_rooms is not None:
        raw['num_rooms'] = payload.num_rooms

    # Cập nhật yêu cầu: khi form gửi lên (kể cả rỗng) thì ghi đè, tránh xoá trắng không lưu
    _sent = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else (payload.dict(exclude_unset=True) if hasattr(payload, "dict") else {})
    if "special_requests" in _sent:
        req_val = (payload.special_requests or "").strip() or None
        # Xoá các key fallback cũ để đảm bảo yêu cầu trống thực sự được cập nhật
        for k in ('special_request', 'guest_requests', 'guest_notes', 'notes', 'remarks', 'requests'):
            raw.pop(k, None)
        raw["special_requests"] = req_val  # type: ignore

    booking.raw_data = raw
    booking.updated_at = datetime.now()

    db.commit()
    db.refresh(booking)

    # Lấy branch_name
    branch = db.query(Branch).filter(Branch.id == booking.branch_id).first()
    branch_name = branch.name if branch else None

    raw = booking.raw_data or {}
    return BookingResponse(
        id=booking.id,
        external_id=booking.external_id,
        booking_source=booking.booking_source,
        guest_name=booking.guest_name,
        guest_phone=booking.guest_phone,
        checkin_code=booking.checkin_code,
        check_in=str(booking.check_in) if booking.check_in else None,
        check_in_time=raw.get('check_in_time') or None,
        check_out=str(booking.check_out) if booking.check_out else None,
        check_out_time=raw.get('check_out_time') or None,
        room_type=booking.room_type,
        num_rooms=int(raw.get('num_rooms') or 1),
        num_guests=booking.num_guests,
        num_adults=booking.num_adults,
        num_children=booking.num_children,
        total_price=float(booking.total_price),
        currency=booking.currency,
        branch_name=branch_name,
        original_branch_name=raw.get('original_branch_name') or None,
        is_readonly_copy=getattr(booking, "source_booking_id", None) is not None,
        status=booking.status.value if hasattr(booking.status, 'value') else str(booking.status),
        special_requests=_extract_special_requests(booking.raw_data),
        created_at=booking.created_at,
        updated_at=getattr(booking, "updated_at", None),
        is_prepaid=booking.is_prepaid
    )


@router.delete("/bookings/{booking_id}")
def delete_booking(
    booking_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Xoá phiếu đặt phòng (chỉ admin)."""
    user = request.session.get("user", {})
    role = (user.get("role") or "").lower()
    if role not in ("admin", "quanly", "manager", "boss"):
        raise HTTPException(status_code=403, detail="Chỉ admin mới được xoá phiếu đặt phòng.")
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiếu đặt phòng.")
    # Admin được phép xoá cả bản sao
    db.delete(booking)
    db.commit()
    return {"ok": True, "id": booking_id}


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
    from fastapi.responses import StreamingResponse  # type: ignore
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
    from fastapi.responses import StreamingResponse  # type: ignore
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
    from app.core.config import settings, logger  # type: ignore

    # ── Kiểm tra OTA_ENABLED flag ────────────────────────────────────────────
    # Để tạm dừng OTA: set OTA_ENABLED=false trên Render → restart service
    # Để bật lại:      set OTA_ENABLED=true  trên Render → restart service
    if not settings.OTA_ENABLED:
        logger.info("[Webhook] ⏸️ OTA_ENABLED=false → bỏ qua webhook (đang tạm dừng)")
        return {"status": "paused", "reason": "OTA_ENABLED is false"}
    # ─────────────────────────────────────────────────────────────────────────

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
        from app.core.config import logger  # type: ignore
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
    from app.core.config import logger  # type: ignore
    from app.services.ota_agent.integration import ota_agent  # type: ignore
    from app.db.session import TaskSessionLocal  # NullPool: không cạnh tranh pool HTTP  # type: ignore
    from app.services.ota_agent.mapper import HotelMapper  # type: ignore

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
        emails_list: list = emails if isinstance(emails, list) else list(emails or [])
        for email in emails_list:
            db = TaskSessionLocal()
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
        from app.core.config import logger  # type: ignore
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
    from app.core.config import logger  # type: ignore
    from datetime import datetime, timezone, timedelta

    # Parse ngày cần quét
    if scan_date:
        try:
            target_date = datetime.strptime(scan_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="scan_date phải đúng định dạng YYYY-MM-DD")
    else:
        from datetime import timezone, timedelta
        vn_tz = timezone(timedelta(hours=7))
        target_date = datetime.now(vn_tz).replace(hour=0, minute=0, second=0, microsecond=0)

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
    from app.core.config import logger  # type: ignore
    from app.services.ota_agent.integration import ota_agent  # type: ignore
    from app.db.session import TaskSessionLocal  # NullPool: không cạnh tranh pool HTTP  # type: ignore
    from app.services.ota_agent.mapper import HotelMapper  # type: ignore
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
            db = TaskSessionLocal()
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
    from app.core.config import settings  # type: ignore

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
    from app.core.config import settings  # type: ignore

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
        from google_auth_oauthlib.flow import Flow  # type: ignore

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
        from app.core.config import logger  # type: ignore
        logger.error(f"[OAuth Callback] Lỗi: {e}")
        return HTMLResponse(f"<h1>❌ Lỗi</h1><p>{str(e)}</p>", status_code=500)
