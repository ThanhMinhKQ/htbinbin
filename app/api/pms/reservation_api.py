"""Reservation Hub API for PMS booking management."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, joinedload, defer

from ...core.utils import VN_TZ
from ...db.models import Booking, Branch, Guest, HotelRoomType, OTAParsingLog, OTAParsingStatus, RoomBlock
from ...db.session import get_db
from ...services.booking_service import BookingService, is_ota_like_booking
from ...services.room_inventory_service import InventoryService
from ...services.ota_agent.mapper import HotelMapper
from ...services.ota_agent.ota_service import ota_dashboard_service
from .pms_helpers import _active_branch, _get_branch_by_code, _is_admin, _require_login


router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
logger = logging.getLogger(__name__)


class ReservationPayload(BaseModel):
    booking_type: str = "DIRECT"
    booking_source: Optional[str] = None
    external_id: Optional[str] = None
    reservation_status: Optional[str] = None
    branch_id: Optional[int] = None
    guest_id: Optional[int] = None
    room_type_id: Optional[int] = None
    guest_name: Optional[str] = None
    guest_phone: Optional[str] = None
    guest_email: Optional[str] = None
    guest_cccd: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    nationality: Optional[str] = None
    id_expire: Optional[str] = None
    address: Optional[str] = None
    check_in: str
    check_out: str
    estimated_arrival: Optional[str] = None
    num_guests: int = 1
    num_adults: Optional[int] = None
    num_children: int = 0
    total_price: float = 0
    currency: str = "VND"
    is_prepaid: bool = False
    deposit_amount: float = 0
    payment_method: Optional[str] = None
    special_requests: Optional[str] = None
    internal_notes: Optional[str] = None
    raw_data: Optional[dict[str, Any]] = None
    room_items: Optional[list[dict[str, Any]]] = None


class ReservationUpdatePayload(BaseModel):
    booking_type: Optional[str] = None
    booking_source: Optional[str] = None
    external_id: Optional[str] = None
    reservation_status: Optional[str] = None
    room_type_id: Optional[int] = None
    guest_name: Optional[str] = None
    guest_phone: Optional[str] = None
    guest_email: Optional[str] = None
    guest_cccd: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[str] = None
    nationality: Optional[str] = None
    id_expire: Optional[str] = None
    address: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    estimated_arrival: Optional[str] = None
    num_guests: Optional[int] = None
    num_adults: Optional[int] = None
    num_children: Optional[int] = None
    total_price: Optional[float] = None
    deposit_amount: Optional[float] = None
    payment_method: Optional[str] = None
    special_requests: Optional[str] = None
    internal_notes: Optional[str] = None
    raw_data: Optional[dict[str, Any]] = None


class CancelPayload(BaseModel):
    reason: Optional[str] = ""


class AssignRoomPayload(BaseModel):
    room_id: int


class ReservationStatusPayload(BaseModel):
    reservation_status: str


class ReservationConfirmPayload(BaseModel):
    room_type_id: Optional[int] = None


class ReservationTransferPayload(BaseModel):
    target_branch_id: int
    target_room_type_id: int
    reason: Optional[str] = ""


class RoomBlockPayload(BaseModel):
    room_id: int
    start_date: str
    end_date: str
    reason: Optional[str] = None


class RoomBlockUpdatePayload(BaseModel):
    status: Optional[str] = None
    reason: Optional[str] = None


class InventoryHoldPayload(BaseModel):
    room_type_id: int
    check_in: str
    check_out: str
    quantity: int = 1
    booking_id: Optional[int] = None
    hold_type: str = "MANUAL"
    expire_minutes: int = 15


def _payload_dict(payload: BaseModel) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_unset=True)
    return payload.dict(exclude_unset=True)



def _parse_date(value: Optional[str], field_name: str) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} không hợp lệ") from exc


def _target_branch_id(request: Request, db: Session, user: dict, branch_id: Optional[int]) -> int:
    is_admin = _is_admin(user)
    if branch_id:
        branch = db.query(Branch).filter(Branch.id == branch_id).first()
        if not branch:
            raise HTTPException(status_code=400, detail="Không tìm thấy chi nhánh")
        if is_admin:
            return int(branch.id)
        active = _get_branch_by_code(_active_branch(request), db)
        if not active or active.id != branch.id:
            raise HTTPException(status_code=403, detail="Không có quyền thao tác chi nhánh này")
        return int(branch.id)

    active = _get_branch_by_code(_active_branch(request), db)
    if active:
        return int(active.id)
    if is_admin:
        first_branch = db.query(Branch).order_by(Branch.id.asc()).first()
        if first_branch:
            return int(first_branch.id)
    raise HTTPException(status_code=400, detail="Cần chọn chi nhánh trước khi thao tác")


def _json_success(data=None, message: str = "OK") -> JSONResponse:
    payload = {"success": True, "message": message}
    if data is not None:
        payload["data"] = data
    return JSONResponse(payload)


def _iso_vn(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    try:
        if value.tzinfo:
            return value.astimezone(VN_TZ).isoformat()
        return VN_TZ.localize(value).isoformat()
    except Exception:
        return value.isoformat()


def _json_value(data: Any, key: str, default: Any = None) -> Any:
    if isinstance(data, dict):
        value = data.get(key)
        return default if value is None else value
    return default


def _log_parser_method(log: OTAParsingLog) -> str:
    data = log.extracted_data if isinstance(log.extracted_data, dict) else {}
    explicit = str(data.get("parser_method") or data.get("extraction_method") or data.get("parsed_by") or "").lower()
    if explicit:
        if any(token in explicit for token in ("rule", "parse", "template", "regex")):
            return "rule"
        if any(token in explicit for token in ("ai", "gemini", "llm", "gpt", "gatecheap")):
            return "ai"
    if log.booking and isinstance(log.booking.raw_data, dict):
        raw_method = str(
            log.booking.raw_data.get("parser_method")
            or log.booking.raw_data.get("extraction_method")
            or log.booking.raw_data.get("parsed_by")
            or ""
        ).lower()
        if any(token in raw_method for token in ("rule", "parse", "template", "regex")):
            return "rule"
        if any(token in raw_method for token in ("ai", "gemini", "llm", "gpt", "gatecheap")):
            return "ai"
    # Các log thành công sau quota-guard có booking/extracted_data nhưng chưa ghi marker cũ;
    # nếu không thấy dấu AI rõ ràng thì mặc định xem là parser rule để không phóng đại lượt Gemini.
    return "ai" if log.status == OTAParsingStatus.FAILED else "rule"


def _is_relevant_ota_log(log: OTAParsingLog) -> bool:
    data = log.extracted_data if isinstance(log.extracted_data, dict) else {}
    action_type = str(data.get("action_type") or "").upper()
    has_booking_signal = bool(log.booking_id or data.get("external_id") or data.get("booking_source"))
    is_booking_action = action_type in {"NEW", "MODIFY", "CANCEL", "CANCELLED", "UPDATE"}
    is_failed_review = log.status == OTAParsingStatus.FAILED and not data.get("non_booking") and data.get("status") != "SKIPPED"
    return has_booking_signal or is_booking_action or is_failed_review


def _booking_is_cancelled(booking: Optional[Booking]) -> bool:
    if not booking:
        return False
    for attr in ("reservation_status", "status"):
        value = getattr(booking, attr, None)
        if hasattr(value, "value"):
            value = value.value
        if str(value or "").upper() in {"CANCELLED", "NO_SHOW"}:
            return True
    return False


def _is_success_booking_log(log: OTAParsingLog) -> bool:
    if log.status != OTAParsingStatus.SUCCESS or not log.booking_id:
        return False
    data = log.extracted_data if isinstance(log.extracted_data, dict) else {}
    if data.get("status") == "SKIPPED" or data.get("non_booking"):
        return False
    action_type = _ota_log_action_type(log)
    return action_type == "NEW"


def _is_cancel_booking_log(log: OTAParsingLog) -> bool:
    if log.status != OTAParsingStatus.SUCCESS:
        return False
    data = log.extracted_data if isinstance(log.extracted_data, dict) else {}
    if data.get("status") == "SKIPPED" or data.get("non_booking"):
        return False
    return _ota_log_action_type(log) == "CANCEL"


def _is_modification_booking_log(log: OTAParsingLog) -> bool:
    if log.status != OTAParsingStatus.SUCCESS:
        return False
    data = log.extracted_data if isinstance(log.extracted_data, dict) else {}
    if data.get("status") == "SKIPPED" or data.get("non_booking"):
        return False
    return _ota_log_action_type(log) == "UPDATE"


def _ota_log_matches_branch(log: OTAParsingLog, target_branch: Optional[int]) -> bool:
    if not target_branch:
        return True
    booking = log.booking
    if booking and booking.branch_id:
        try:
            return int(booking.branch_id) == int(target_branch)
        except (TypeError, ValueError):
            return False
    data = log.extracted_data if isinstance(log.extracted_data, dict) else {}
    try:
        branch_id = data.get("branch_id")
        return bool(branch_id) and int(branch_id) == int(target_branch)
    except (TypeError, ValueError):
        return False


def _ota_log_action_type(log: OTAParsingLog) -> str:
    data = log.extracted_data if isinstance(log.extracted_data, dict) else {}
    raw = str(data.get("action_type") or "").upper()
    if raw in ("CANCEL", "CANCELLED"):
        return "CANCEL"
    if raw in ("MODIFY", "MODIFIED", "UPDATE", "UPDATED", "AMENDMENT", "AMEND"):
        return "UPDATE"
    if raw == "NEW":
        return "NEW"
    # Fallback: suy từ booking status
    if log.booking and getattr(log.booking.status, "value", log.booking.status) == "CANCELLED":
        return "CANCEL"
    return "NEW"


def _ota_log_branch_from_data(log: OTAParsingLog, data: dict[str, Any]) -> tuple[Optional[int], str]:
    session = log._sa_instance_state.session
    if not session:
        return data.get("branch_id"), ""
    mapper = HotelMapper(session)
    branch_id = data.get("branch_id")
    if not branch_id and data.get("booking_source") == "Website":
        branch_id = mapper.get_branch_id_from_room_type(str(data.get("room_type") or ""))
    if not branch_id:
        candidates = [
            data.get("hotel_name"),
            data.get("branch_name"),
            data.get("property_name"),
        ]
        raw_content = str(log.raw_content or "")
        candidates.extend(re.findall(r"(?:Khách\s*sạn|Khach\s*san|Hotel|Dear\s+Hotel|Quý\s+khách\s+sạn)\s*[:\-]?\s*([^\n\r<]{0,120}Bin\s*Bin[^\n\r<]{0,120})", raw_content, re.IGNORECASE))
        candidates.extend(re.findall(r"(Bin\s*Bin\s*(?:Hotel)?\s*\d+[^\n\r<]{0,120})", raw_content, re.IGNORECASE))
        candidates.extend(re.findall(r"(Khách\s*sạn\s*Bin\s*Bin\s*\d+[^\n\r<]{0,120})", raw_content, re.IGNORECASE))
        for candidate in candidates:
            branch_id = mapper.get_branch_id(str(candidate or ""))
            if branch_id:
                break
    branch = session.get(Branch, branch_id) if branch_id else None
    return branch_id, branch.name if branch else ""


def _serialize_ota_log(log: OTAParsingLog) -> dict[str, Any]:
    booking = log.booking
    data = log.extracted_data if isinstance(log.extracted_data, dict) else {}
    branch = booking.branch if booking and booking.branch else None
    branch_id = branch.id if branch else (booking.branch_id if booking else data.get("branch_id"))
    branch_name = branch.name if branch else ""
    if not branch_name and branch_id:
        mapped_branch = log._sa_instance_state.session.get(Branch, branch_id) if log._sa_instance_state.session else None
        branch_name = mapped_branch.name if mapped_branch else ""
    if not branch_name:
        branch_id, branch_name = _ota_log_branch_from_data(log, data)
    status_value = log.status.value if hasattr(log.status, "value") else str(log.status or "")
    action_type = _ota_log_action_type(log)
    return {
        "id": log.id,
        "received_at": _iso_vn(log.received_at),
        "email_subject": log.email_subject,
        "email_sender": log.email_sender,
        "status": status_value,
        "parser_method": _log_parser_method(log),
        "action_type": action_type,
        "branch_id": branch_id,
        "branch_name": branch_name or "Chưa xác định",
        "booking_id": log.booking_id,
        "booking_source": booking.booking_source if booking else _json_value(data, "booking_source", "OTA"),
        "external_id": booking.external_id if booking else _json_value(data, "external_id", ""),
        "guest_name": booking.guest_name if booking else _json_value(data, "guest_name", ""),
        "num_guests": booking.num_guests if booking else int(_json_value(data, "num_guests", 1) or 1),
        "booking_type": booking.booking_type if booking else "OTA",
        "room_type_name": booking.room_type if booking else _json_value(data, "room_type", ""),
        "check_in": booking.check_in.isoformat() if booking and booking.check_in else str(_json_value(data, "check_in", "") or ""),
        "check_out": booking.check_out.isoformat() if booking and booking.check_out else str(_json_value(data, "check_out", "") or ""),
        "check_in_time": str(data.get("check_in_time") or data.get("estimated_arrival") or ""),
        "check_out_time": str(data.get("check_out_time") or data.get("estimated_departure") or ""),
        "ota_same_day_booking": bool(data.get("ota_same_day_booking")),
        "ota_actual_check_out": str(data.get("ota_actual_check_out") or ""),
        "ota_cross_midnight_booking": bool(data.get("ota_cross_midnight_booking")),
        "error_message": log.error_message,
        "retry_count": log.retry_count or 0,
    }


@router.get("/api/pms/reservations/stats", tags=["PMS Reservations"])
def api_reservation_stats(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = _target_branch_id(request, db, user, branch_id)
    return JSONResponse(BookingService(db).stats(target_branch))


@router.get("/api/pms/reservations/today-arrivals", tags=["PMS Reservations"])
def api_today_arrivals(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = _target_branch_id(request, db, user, branch_id)
    today = datetime.now(VN_TZ).date()
    data = BookingService(db).list_reservations(
        branch_id=target_branch,
        check_in_from=today,
        check_in_to=today,
        status=None,
        page_size=100,
    )
    data["items"] = [i for i in data["items"] if i["reservation_status"] in {"PENDING", "CONFIRMED"}]
    data["total"] = len(data["items"])
    return JSONResponse(data)


@router.get("/api/pms/reservations/today-departures", tags=["PMS Reservations"])
def api_today_departures(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = _target_branch_id(request, db, user, branch_id)
    today = datetime.now(VN_TZ).date()
    data = BookingService(db).list_reservations(
        branch_id=target_branch,
        check_in_from=None,
        check_in_to=None,
        page_size=100,
    )
    data["items"] = [
        i for i in data["items"]
        if i["check_out"] == today.isoformat() and i["reservation_status"] in {"CONFIRMED", "CHECKED_IN"}
    ]
    data["total"] = len(data["items"])
    return JSONResponse(data)


@router.get("/api/pms/reservations/in-house", tags=["PMS Reservations"])
def api_in_house_reservations(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = _target_branch_id(request, db, user, branch_id)
    return JSONResponse(BookingService(db).list_reservations(branch_id=target_branch, status="CHECKED_IN", page_size=100))


@router.get("/api/pms/reservations", tags=["PMS Reservations"])
def api_list_reservations(
    request: Request,
    branch_id: Optional[int] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    check_in_from: Optional[str] = None,
    check_in_to: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = _target_branch_id(request, db, user, branch_id)
    service = BookingService(db)
    return JSONResponse(service.list_reservations(
        branch_id=target_branch,
        status=status,
        source=source,
        search=search,
        check_in_from=_parse_date(check_in_from, "Từ ngày"),
        check_in_to=_parse_date(check_in_to, "Đến ngày"),
        page=page,
        page_size=page_size,
    ))


@router.get("/api/pms/reservations/search", tags=["PMS Reservations"])
def api_search_reservations(
    request: Request,
    branch_id: Optional[int] = None,
    q: Optional[str] = None,
    status: Optional[str] = None,
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = _target_branch_id(request, db, user, branch_id)
    return JSONResponse(BookingService(db).list_reservations(
        branch_id=target_branch,
        status=status,
        search=q,
        page_size=page_size,
    ))


@router.post("/api/pms/reservations", tags=["PMS Reservations"])
def api_create_reservation(
    payload: ReservationPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    data = _payload_dict(payload)
    data["branch_id"] = _target_branch_id(request, db, user, data.get("branch_id"))
    data["guest_name"] = (data.get("guest_name") or "").strip() or "Khách lẻ"
    room_items = data.get("room_items") or []
    if room_items:
        try:
            bookings = BookingService(db).create_group_reservation(data, user.get("id"))
            db.commit()
            return _json_success(
                [BookingService(db).serialize(booking) for booking in bookings],
                f"Đã tạo {len(bookings)} phòng đặt",
            )
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    room_type_id = data.get("room_type_id")
    if not room_type_id:
        raise HTTPException(status_code=400, detail="Cần chọn loại phòng")
    room_type = db.query(HotelRoomType).filter(
        HotelRoomType.id == int(room_type_id),
        HotelRoomType.branch_id == data["branch_id"],
        HotelRoomType.is_active == True,
    ).first()
    if not room_type:
        raise HTTPException(status_code=400, detail="Loại phòng không thuộc chi nhánh đang chọn")
    try:
        booking = BookingService(db).create_reservation(data, user.get("id"))
        db.commit()
        return _json_success(BookingService(db).serialize(booking), "Đã tạo đặt phòng")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/pms/reservations/sync-ota", tags=["PMS Reservations"])
def api_sync_ota_reservations(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = _target_branch_id(request, db, user, branch_id)
    service = BookingService(db)
    bookings = db.query(Booking).filter(
        Booking.branch_id == target_branch,
        Booking.source_booking_id.is_(None),
    ).all()
    synced = 0
    for booking in bookings:
        if is_ota_like_booking(booking):
            service.stage_ota_booking_for_review(booking, user_id=user.get("id"))
            synced += 1
    db.commit()
    return _json_success({"synced": synced}, "Đã đồng bộ booking OTA vào Quản lý đặt phòng")


_OTA_STATUS_CACHE: dict[tuple, tuple[float, dict]] = {}
_OTA_STATUS_TTL = 20.0  # giây


@router.get("/api/pms/reservations/ota/status", tags=["PMS Reservations"])
def api_ota_status(
    request: Request,
    branch_id: Optional[int] = None,
    days: int = Query(7, ge=1, le=90),
    fresh: bool = Query(False),
    db: Session = Depends(get_db),
):
    user = _require_login(request)

    def offline_response(target_branch=None, branch_name="Tất cả chi nhánh"):
        return JSONResponse({
            "booking_stats": {},
            "branch_id": target_branch,
            "branch_name": branch_name,
            "ota_total": 0,
            "ota_confirmed": 0,
            "ota_cancelled": 0,
            "ota_updated": 0,
            "ota_pending": 0,
            "failed_emails": 0,
            "success_emails": 0,
            "cancelled_emails": 0,
            "agent_ai_count": 0,
            "agent_gemini_count": 0,
            "agent_rule_count": 0,
            "agent_skipped_count": 0,
            "agent_parse_count": 0,
            "agent_total_count": 0,
            "agent_window_days": days,
            "latest_email_at": None,
            "latest_email_status": None,
            "latest_success_log_id": None,
            "latest_success_booking": None,
            "latest_cancel_log_id": None,
            "latest_cancel_booking": None,
            "latest_modification_log_id": None,
            "latest_modification_booking": None,
            "database_offline": True,
            "message": "Không kết nối được cơ sở dữ liệu",
        }, status_code=200)

    try:
        target_branch = None if _is_admin(user) and not branch_id else _target_branch_id(request, db, user, branch_id)
    except OperationalError:
        db.rollback()
        return offline_response()

    # ── TTL cache 20s để tránh hammer DB khi FE poll ────────────────────
    # Endpoint này được poll từ base.html (120s) + dashboard (90s) cho MỌI user.
    # Dữ liệu mới chỉ tới qua email OTA (tối đa vài phút/lần) → cache ngắn an toàn.
    import time
    cache_key = (target_branch, days)
    now_ts = time.time()
    cached = _OTA_STATUS_CACHE.get(cache_key)
    if not fresh and cached and (now_ts - cached[0]) < _OTA_STATUS_TTL:
        return JSONResponse(cached[1])

    try:
        branch = db.query(Branch).filter(Branch.id == target_branch).first() if target_branch else None
        since = datetime.now(VN_TZ) - timedelta(days=days)
        # Bỏ service.stats(): polling không cần booking_stats (FE không dùng).
        # Bỏ ota_q: dead code (được build nhưng không execute/return).
        # Giảm limit 200 → 80: đủ để xác định top success/cancel/failed gần nhất.
        log_q = db.query(OTAParsingLog).outerjoin(OTAParsingLog.booking)
        if target_branch:
            log_q = log_q.filter(or_(
                Booking.branch_id == target_branch,
                OTAParsingLog.extracted_data["branch_id"].astext == str(target_branch),
            ))
        recent_logs = log_q.options(joinedload(OTAParsingLog.booking).joinedload(Booking.branch)).filter(
            OTAParsingLog.received_at >= since,
            OTAParsingLog.status.isnot(None),
        ).order_by(OTAParsingLog.received_at.desc()).limit(80).all()
    except OperationalError:
        db.rollback()
        return offline_response(target_branch)
    relevant_logs = [log for log in recent_logs if _is_relevant_ota_log(log) and _ota_log_matches_branch(log, target_branch)]
    latest_log = relevant_logs[0] if relevant_logs else None
    success_booking_logs = [log for log in relevant_logs if _is_success_booking_log(log)]
    cancel_booking_logs = [log for log in relevant_logs if _is_cancel_booking_log(log)]
    modification_booking_logs = [log for log in relevant_logs if _is_modification_booking_log(log)]
    ai_count = sum(1 for log in relevant_logs if _log_parser_method(log) == "ai")
    rule_count = sum(1 for log in relevant_logs if _log_parser_method(log) == "rule")
    skipped_count = sum(1 for log in relevant_logs if _log_parser_method(log) == "rule_skip" or (log.extracted_data or {}).get("status") == "SKIPPED")
    latest_relevant_log = success_booking_logs[0] if success_booking_logs else None
    latest_relevant_payload = _serialize_ota_log(latest_relevant_log) if latest_relevant_log else None
    latest_cancel_log = cancel_booking_logs[0] if cancel_booking_logs else None
    latest_cancel_payload = _serialize_ota_log(latest_cancel_log) if latest_cancel_log else None
    latest_modification_log = modification_booking_logs[0] if modification_booking_logs else None
    latest_modification_payload = None
    if latest_modification_log and latest_modification_log.booking:
        raw = latest_modification_log.booking.raw_data if isinstance(latest_modification_log.booking.raw_data, dict) else {}
        base = _serialize_ota_log(latest_modification_log)
        base['modification_summary'] = raw.get('modification_summary') or ''
        base['modification_at'] = raw.get('modification_at') or ''
        base['booking_db_id'] = latest_modification_log.booking.id
        latest_modification_payload = base
    payload = {
        "booking_stats": {},
        "branch_id": target_branch,
        "branch_name": branch.name if branch else "Tất cả chi nhánh",
        "ota_total": len(relevant_logs),
        "ota_confirmed": len(success_booking_logs),
        "ota_cancelled": len(cancel_booking_logs),
        "ota_updated": len(modification_booking_logs),
        "ota_pending": 0,
        "failed_emails": sum(1 for log in relevant_logs if log.status == OTAParsingStatus.FAILED),
        "success_emails": len(success_booking_logs),
        "cancelled_emails": len(cancel_booking_logs),
        "agent_ai_count": ai_count,
        "agent_gemini_count": ai_count,
        "agent_rule_count": rule_count,
        "agent_skipped_count": skipped_count,
        "agent_parse_count": rule_count,
        "agent_total_count": ai_count + rule_count + skipped_count,
        "agent_window_days": days,
        "latest_email_at": _iso_vn(latest_log.received_at) if latest_log else None,
        "latest_email_status": latest_log.status.value if latest_log and hasattr(latest_log.status, "value") else None,
        "latest_success_log_id": latest_relevant_log.id if latest_relevant_log else None,
        "latest_success_booking": latest_relevant_payload,
        "latest_cancel_log_id": latest_cancel_log.id if latest_cancel_log else None,
        "latest_cancel_booking": latest_cancel_payload,
        "latest_modification_log_id": latest_modification_log.id if latest_modification_log else None,
        "latest_modification_booking": latest_modification_payload,
    }
    if not fresh:
        _OTA_STATUS_CACHE[cache_key] = (now_ts, payload)
        # Don trim cache đơn giản để tránh leak
        if len(_OTA_STATUS_CACHE) > 64:
            oldest = min(_OTA_STATUS_CACHE.items(), key=lambda kv: kv[1][0])[0]
            _OTA_STATUS_CACHE.pop(oldest, None)
    return JSONResponse(payload)


@router.post("/api/pms/reservations/ota/mark-modification-read/{booking_id}", tags=["PMS Reservations"])
def api_mark_modification_read(
    booking_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Đánh dấu booking modification đã được đọc — xóa flag has_unread_modification."""
    _require_login(request)
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy booking.")
    raw = dict(booking.raw_data or {})
    raw["has_unread_modification"] = False
    raw["modification_read_at"] = datetime.now(VN_TZ).isoformat()
    booking.raw_data = raw
    db.commit()
    # Xóa cache để lần poll tiếp theo không trả về modification cũ
    _OTA_STATUS_CACHE.clear()
    return JSONResponse({"ok": True, "booking_id": booking_id})


@router.get("/api/pms/reservations/ota/logs", tags=["PMS Reservations"])
def api_ota_logs(
    request: Request,
    status: Optional[str] = None,
    booking_source: Optional[str] = None,
    parser_method: Optional[str] = None,
    action_type: Optional[str] = None,
    branch_id: Optional[int] = None,
    search: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = None if _is_admin(user) and not branch_id else _target_branch_id(request, db, user, branch_id)
    relevant_action = OTAParsingLog.extracted_data["action_type"].astext.in_(["NEW", "MODIFY", "CANCEL", "CANCELLED", "UPDATE"])
    failed_review = and_(
        OTAParsingLog.status == OTAParsingStatus.FAILED,
        or_(
            OTAParsingLog.extracted_data["non_booking"].astext.is_(None),
            OTAParsingLog.extracted_data["non_booking"].astext != "true",
        ),
        or_(
            OTAParsingLog.extracted_data["status"].astext.is_(None),
            OTAParsingLog.extracted_data["status"].astext != "SKIPPED",
        ),
    )
    q = db.query(OTAParsingLog).options(
        joinedload(OTAParsingLog.booking).joinedload(Booking.branch),
        defer(OTAParsingLog.raw_content),
        defer(OTAParsingLog.error_traceback),
    ).outerjoin(OTAParsingLog.booking).filter(or_(
        OTAParsingLog.booking_id.isnot(None),
        relevant_action,
        failed_review,
    )).order_by(OTAParsingLog.received_at.desc())

    if from_date:
        q = q.filter(OTAParsingLog.received_at >= _parse_date(from_date, "from_date"))
    elif not search:
        now_vn = datetime.now(VN_TZ)
        default_since = now_vn.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        q = q.filter(OTAParsingLog.received_at >= default_since)
    if to_date:
        q = q.filter(OTAParsingLog.received_at < _parse_date(to_date, "to_date") + timedelta(days=1))

    if target_branch:
        q = q.filter(or_(
            Booking.branch_id == target_branch,
            OTAParsingLog.extracted_data["branch_id"].astext == str(target_branch),
        ))
    if status:
        normalized = status.upper()
        if normalized == "SUCCESS":
            q = q.filter(OTAParsingLog.status == OTAParsingStatus.SUCCESS)
        elif normalized == "FAILED":
            q = q.filter(OTAParsingLog.status == OTAParsingStatus.FAILED)
    if booking_source:
        q = q.filter(or_(
            Booking.booking_source.ilike(booking_source),
            OTAParsingLog.extracted_data["booking_source"].astext.ilike(booking_source),
        ))
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(or_(
            OTAParsingLog.email_subject.ilike(like),
            OTAParsingLog.email_sender.ilike(like),
            Booking.external_id.ilike(like),
            Booking.guest_name.ilike(like),
            Booking.booking_source.ilike(like),
        ))

    raw_logs = q.all()
    logs = [log for log in raw_logs if _is_relevant_ota_log(log) and _ota_log_matches_branch(log, target_branch)]
    if parser_method and parser_method.lower() not in {"all", ""}:
        normalized_method = parser_method.lower()
        logs = [log for log in logs if _log_parser_method(log) == normalized_method]
    if action_type and action_type.upper() not in {"ALL", ""}:
        logs = [log for log in logs if _ota_log_action_type(log) == action_type.upper()]

    total = len(logs)
    total_pages = max(1, (total + limit - 1) // limit)
    page = min(page, total_pages)
    offset = (page - 1) * limit
    page_logs = logs[offset:offset + limit]

    # Aggregate counts từ toàn bộ logs (không phân trang) để dashboard khớp bảng
    counts = {"NEW": 0, "UPDATE": 0, "CANCEL": 0, "FAILED": 0}
    for log in logs:
        if log.status == OTAParsingStatus.FAILED:
            counts["FAILED"] += 1
        else:
            counts[_ota_log_action_type(log)] = counts.get(_ota_log_action_type(log), 0) + 1

    branch_obj = db.query(Branch).filter(Branch.id == target_branch).first() if target_branch else None
    branch_name_label = branch_obj.name if branch_obj else "Tất cả chi nhánh"

    return JSONResponse({
        "items": [_serialize_ota_log(log) for log in page_logs],
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "counts": counts,
        "branch_name": branch_name_label,
        "filters": {
            "status": status,
            "booking_source": booking_source,
            "parser_method": parser_method,
            "action_type": action_type,
            "branch_id": target_branch,
            "from_date": from_date,
            "to_date": to_date,
        },
    })


@router.post("/api/pms/reservations/ota/retry/{log_id}", tags=["PMS Reservations"])
def api_retry_ota_log(
    log_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    _require_login(request)
    log = db.query(OTAParsingLog).filter(OTAParsingLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Không tìm thấy log OTA")
    if log.status != OTAParsingStatus.FAILED:
        raise HTTPException(status_code=400, detail="Chỉ có thể retry email đã thất bại")
    if (log.retry_count or 0) >= 999:
        raise HTTPException(status_code=400, detail="Email này đã được đánh dấu Dead Letter Queue, không thể retry.")
    if (log.error_message or "").startswith("[RETRYING]"):
        return JSONResponse({
            "success": True,
            "status": "processing",
            "message": "Email OTA này đang được xử lý lại trong nền",
            "log_id": log_id,
        }, status_code=202)

    log.error_message = "[RETRYING] Đang xử lý lại trong nền..."
    log.last_retry_at = datetime.now(timezone.utc)
    db.commit()
    background_tasks.add_task(_run_retry_in_background, log_id)
    return JSONResponse({
        "success": True,
        "status": "processing",
        "message": "Đang xử lý lại email OTA trong nền",
        "log_id": log_id,
    }, status_code=202)


@router.get("/api/pms/reservations/ota/retry/{log_id}/status", tags=["PMS Reservations"])
def api_retry_status(
    log_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _require_login(request)
    log = db.query(OTAParsingLog).filter(OTAParsingLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Không tìm thấy log OTA")
    is_processing = (log.error_message or "").startswith("[RETRYING]")
    if is_processing and log.last_retry_at:
        started_at = log.last_retry_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - started_at > timedelta(minutes=10):
            log.error_message = "Retry email OTA quá thời gian xử lý"
            db.commit()
            is_processing = False
    return JSONResponse({
        "log_id": log_id,
        "status": "processing" if is_processing else (log.status.value if hasattr(log.status, "value") else str(log.status)),
        "error_message": log.error_message if not is_processing else None,
        "booking_id": log.booking_id,
        "retry_count": log.retry_count or 0,
    })


def _run_retry_in_background(log_id: int):
    from ...db.session import SessionLocal
    db = SessionLocal()
    try:
        result = ota_dashboard_service.retry_failed_email(db=db, log_id=log_id)
        if not result.get("success"):
            log = db.query(OTAParsingLog).filter(OTAParsingLog.id == log_id).first()
            if log and (log.error_message or "").startswith("[RETRYING]"):
                log.error_message = result.get("error") or "Không xử lý lại được email OTA"
                db.commit()
            logger.warning("[OTA Retry BG] log_id=%s failed: %s", log_id, result.get("error"))
        else:
            logger.info("[OTA Retry BG] log_id=%s succeeded, booking_id=%s", log_id, result.get("booking_id"))
    except Exception:
        logger.exception("[OTA Retry BG] log_id=%s exception", log_id)
        try:
            log = db.query(OTAParsingLog).filter(OTAParsingLog.id == log_id).first()
            if log and (log.error_message or "").startswith("[RETRYING]"):
                log.error_message = "Retry email OTA bị lỗi trong nền"
                db.commit()
        except Exception:
            logger.exception("[OTA Retry BG] log_id=%s failed to clear retry marker", log_id)
    finally:
        db.close()


@router.post("/api/pms/reservations/ota/scan-today", tags=["PMS Reservations"])
def api_scan_ota_today(
    request: Request,
    background_tasks: BackgroundTasks,
    scan_date: Optional[str] = Query(None),
):
    _require_login(request)
    from ...api.ota_dashboard import _running_manual_scans, _run_scan_emails_for_date

    if scan_date:
        try:
            target_day = datetime.strptime(scan_date, "%Y-%m-%d").date()
            target_date = VN_TZ.localize(datetime.combine(target_day, datetime.min.time()))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="scan_date phải đúng định dạng YYYY-MM-DD") from exc
    else:
        now = datetime.now(VN_TZ)
        target_date = now.replace(hour=0, minute=0, second=0, microsecond=0)

    scan_requested_at = datetime.now(VN_TZ)
    scan_key = target_date.date().isoformat()
    if scan_key in _running_manual_scans:
        return JSONResponse({
            "success": True,
            "status": "already_running",
            "message": "Đang quét email OTA trong nền; vui lòng chờ job hiện tại hoàn tất",
            "scan_date": scan_key,
        })
    _running_manual_scans.add(scan_key)
    background_tasks.add_task(_run_scan_emails_for_date, target_date, scan_requested_at=scan_requested_at, scan_key=scan_key)
    return _json_success(
        {"status": "started", "scan_date": scan_key, "scan_requested_at": scan_requested_at.isoformat()},
        "Đang quét email OTA trong nền; booking hợp lệ sẽ tự vào Quản lý đặt phòng",
    )


@router.get("/api/pms/reservations/{booking_id}", tags=["PMS Reservations"])
def api_get_reservation(
    booking_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    booking = db.query(Booking).options(
        joinedload(Booking.branch),
        joinedload(Booking.assigned_room),
        joinedload(Booking.guest).joinedload(Guest.membership),
    ).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy đặt phòng")
    _target_branch_id(request, db, user, booking.branch_id)
    return JSONResponse(BookingService(db).serialize(booking))


@router.get("/pms/reservations/{booking_id}/confirmation/print", tags=["PMS Reservations"])
def page_reservation_confirmation_print(
    booking_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    booking = db.query(Booking).options(
        joinedload(Booking.branch),
        joinedload(Booking.assigned_room),
        joinedload(Booking.guest).joinedload(Guest.membership),
    ).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy đặt phòng")
    _target_branch_id(request, db, user, booking.branch_id)
    serialized = BookingService(db).serialize(booking)
    extras = _build_print_extras(serialized)
    return templates.TemplateResponse(request, "pms/reservation_confirmation_print.html", {
        "request": request,
        "booking": serialized,
        "current_user": user,
        "current_time": datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M"),
        **extras,
    })


def _build_print_extras(booking: dict[str, Any]) -> dict[str, Any]:
    """Đảm bảo template print có đủ breakdown/services/time cho mọi loại booking,
    đặc biệt booking theo giờ vốn không luôn có pricing_preview chuẩn."""
    def as_float(value: Any) -> float:
        if isinstance(value, str):
            cleaned = re.sub(r"[^\d,.\-]", "", value.strip())
            if not cleaned:
                return 0.0
            if "." in cleaned and "," in cleaned:
                if cleaned.rfind(",") > cleaned.rfind("."):
                    cleaned = cleaned.replace(".", "").replace(",", ".")
                else:
                    cleaned = cleaned.replace(",", "")
            elif "." in cleaned:
                parts = cleaned.split(".")
                if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
                    cleaned = "".join(parts)
            elif "," in cleaned:
                parts = cleaned.split(",")
                if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
                    cleaned = "".join(parts)
                else:
                    cleaned = cleaned.replace(",", ".")
        try:
            return float(cleaned if isinstance(value, str) else (value or 0))
        except (TypeError, ValueError):
            return 0.0

    raw = booking.get("raw_data") or {}
    pricing = raw.get("pricing_preview") or {}
    pricing_breakdown = pricing.get("breakdown") if isinstance(pricing, dict) else None
    breakdown = [dict(item) for item in pricing_breakdown if isinstance(item, dict)] if isinstance(pricing_breakdown, list) else []
    services = raw.get("services") or []
    manual_override_value = raw.get("manual_total_override")
    manual_total_override = manual_override_value is True or str(manual_override_value).strip().lower() in {"1", "true", "yes", "on"}
    manual_total_price = as_float(raw.get("manual_total_price"))
    if manual_total_override and manual_total_price > 0:
        booking["total_price"] = manual_total_price

    check_in_at = str(raw.get("check_in_at") or "")
    check_out_at = str(raw.get("check_out_at") or "")
    check_in_time = (check_in_at[11:16] if "T" in check_in_at else "") or str(raw.get("check_in_time") or booking.get("estimated_arrival") or "14:00")[-5:]

    cross_midnight = bool(raw.get("ota_cross_midnight_booking"))
    same_day_flag = bool(raw.get("ota_same_day_booking"))
    pricing_mode = str(raw.get("pricing_mode") or pricing.get("pricing_mode") or "").upper()
    same_day_dates = bool(booking.get("check_in") and booking.get("check_out") and booking["check_in"] == booking["check_out"])
    special_req = str(booking.get("special_requests") or "").lower()
    hourly_in_notes = "giờ" in special_req or "hourly" in special_req or "hour" in special_req
    is_hourly = (
        pricing_mode in {"HOUR", "HOURLY", "FORCE_HOURLY"}
        or (same_day_flag and not cross_midnight)
        or same_day_dates
        or hourly_in_notes
    )

    # Với booking giờ, check_out_at thường là ngày hôm sau (DB lưu check_out+1).
    # Lấy giờ thực từ raw.check_out_time hoặc ota_actual_check_out nếu có.
    if is_hourly:
        actual_co_time = str(raw.get("check_out_time") or "")
        if not actual_co_time and raw.get("ota_actual_check_out"):
            # ota_actual_check_out dạng "HH:MM" hoặc "YYYY-MM-DDTHH:MM"
            aco = str(raw["ota_actual_check_out"])
            actual_co_time = aco[11:16] if "T" in aco else aco[:5]
        if not actual_co_time and "T" in check_out_at:
            # check_out_at có thể là ngày hôm sau nhưng giờ vẫn đúng
            actual_co_time = check_out_at[11:16]
        check_out_time = actual_co_time or "12:00"
        # Ngày checkout hiển thị là ngày check_in (cùng ngày)
        display_check_out_date = booking.get("check_in") or ""
    else:
        check_out_time = (check_out_at[11:16] if "T" in check_out_at else "") or str(raw.get("check_out_time") or "12:00")[-5:]
        display_check_out_date = booking.get("check_out") or ""

    ci_iso = check_in_at if "T" in check_in_at else f"{booking.get('check_in') or ''}T{check_in_time}"
    co_iso = f"{display_check_out_date}T{check_out_time}" if display_check_out_date else (check_out_at if "T" in check_out_at else f"{booking.get('check_out') or ''}T{check_out_time}")

    # Nếu là hourly và breakdown từ pricing_preview có start/end_iso sai ngày,
    # rebuild lại để đảm bảo hiển thị đúng.
    if is_hourly and breakdown:
        for item in breakdown:
            if item.get("start_iso") and "T" in str(item["start_iso"]):
                item["start_iso"] = ci_iso
            if item.get("end_iso") and "T" in str(item["end_iso"]):
                item["end_iso"] = co_iso

    if not breakdown and not services:
        total_price = float(booking.get("total_price") or 0)
        if is_hourly:
            hours = _stay_hours(ci_iso, co_iso) or 1
            breakdown = [{
                "type": "HOURLY_CHARGE",
                "description": f"Tiền phòng theo giờ ({hours} tiếng)",
                "amount": total_price,
                "hours": hours,
                "start_iso": ci_iso,
                "end_iso": co_iso,
                "slice_type": "core",
            }]
        else:
            nights = max(1, _date_diff(booking.get("check_in"), booking.get("check_out")))
            breakdown = [{
                "type": "ROOM_CHARGE",
                "description": f"Tiền phòng ({nights} đêm)",
                "amount": total_price,
                "days": nights,
                "start_iso": ci_iso,
                "end_iso": co_iso,
                "slice_type": "core",
            }]

    if manual_total_override:
        total_price = as_float(booking.get("total_price"))
        line_total = sum(as_float(item.get("amount")) for item in breakdown)
        for service in services if isinstance(services, list) else []:
            if not isinstance(service, dict):
                continue
            service_qty = as_float(service.get("qty") or service.get("quantity") or 1) or 1
            service_price = service.get("total")
            if service_price is None:
                service_price = service.get("amount")
            if service_price is None:
                service_price = as_float(service.get("price")) * service_qty
            line_total += as_float(service_price)
        if isinstance(pricing_breakdown, dict):
            legacy_early = raw.get("early_checkin_fee") or raw.get("early_fee") or pricing_breakdown.get("early_checkin_fee")
            legacy_late = raw.get("late_checkout_fee") or raw.get("late_fee") or pricing_breakdown.get("late_checkout_fee")
            line_total += as_float(legacy_early) + as_float(legacy_late)
        delta = round(total_price - line_total)
        if total_price > 0 and delta:
            breakdown.append({
                "type": "MANUAL_TOTAL_ADJUSTMENT",
                "description": "Chênh lệch xác nhận / Adjustment",
                "amount": delta,
                "manual_total_override": True,
                "reference_total": raw.get("manual_total_reference"),
                "confirmed_total": total_price,
            })

    return {
        "services": services,
        "breakdown": breakdown,
        "check_in_time": check_in_time,
        "check_out_time": check_out_time,
        "is_hourly_booking": is_hourly,
        "display_check_out_date": display_check_out_date,
    }


def _stay_hours(check_in_at: str, check_out_at: str) -> int:
    try:
        ci = datetime.fromisoformat(check_in_at)
        co = datetime.fromisoformat(check_out_at)
        delta = (co - ci).total_seconds() / 3600
        return max(1, int(round(delta)))
    except (TypeError, ValueError):
        return 0


def _date_diff(start: Optional[str], end: Optional[str]) -> int:
    try:
        a = date.fromisoformat(str(start)[:10])
        b = date.fromisoformat(str(end)[:10])
        return max(0, (b - a).days)
    except (TypeError, ValueError):
        return 0


@router.put("/api/pms/reservations/{booking_id}", tags=["PMS Reservations"])
def api_update_reservation(
    booking_id: int,
    payload: ReservationUpdatePayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy đặt phòng")
    _target_branch_id(request, db, user, booking.branch_id)
    if booking.reservation_status in {"CANCELLED", "NO_SHOW", "CHECKED_OUT"}:
        raise HTTPException(status_code=400, detail="Không thể sửa đặt phòng đã kết thúc")

    data = _payload_dict(payload)
    if data.get("room_type_id"):
        room_type = db.query(HotelRoomType).filter(
            HotelRoomType.id == int(data["room_type_id"]),
            HotelRoomType.branch_id == booking.branch_id,
            HotelRoomType.is_active == True,
        ).first()
        if not room_type:
            raise HTTPException(status_code=400, detail="Loại phòng không thuộc chi nhánh của đặt phòng")
    try:
        booking = BookingService(db).update_reservation(booking_id, data, user.get("id"))
        db.commit()
        return _json_success(BookingService(db).serialize(booking), "Đã cập nhật đặt phòng")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/pms/reservations/{booking_id}/confirm", tags=["PMS Reservations"])
def api_confirm_reservation(
    booking_id: int,
    request: Request,
    payload: Optional[ReservationConfirmPayload] = None,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy đặt phòng")
    _target_branch_id(request, db, user, booking.branch_id)
    try:
        booking = BookingService(db).confirm_reservation(booking_id, user.get("id"), payload.room_type_id if payload else None)
        db.commit()
        return _json_success(BookingService(db).serialize(booking), "Đã xác nhận đặt phòng")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/pms/reservations/{booking_id}/status", tags=["PMS Reservations"])
def api_set_reservation_status(
    booking_id: int,
    payload: ReservationStatusPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy đặt phòng")
    _target_branch_id(request, db, user, booking.branch_id)
    try:
        booking = BookingService(db).set_reservation_confirmation_status(
            booking_id,
            payload.reservation_status,
            user.get("id"),
        )
        db.commit()
        return _json_success(BookingService(db).serialize(booking), "Đã cập nhật trạng thái đặt phòng")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/pms/reservations/{booking_id}/transfer-branch", tags=["PMS Reservations"])
def api_transfer_reservation_branch(
    booking_id: int,
    payload: ReservationTransferPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy đặt phòng")
    _target_branch_id(request, db, user, booking.branch_id)
    target_branch = db.query(Branch).filter(Branch.id == int(payload.target_branch_id)).first()
    if not target_branch:
        raise HTTPException(status_code=400, detail="Không tìm thấy chi nhánh đích")
    target_room_type = db.query(HotelRoomType).filter(
        HotelRoomType.id == int(payload.target_room_type_id),
        HotelRoomType.branch_id == int(payload.target_branch_id),
        HotelRoomType.is_active == True,
    ).first()
    if not target_room_type:
        raise HTTPException(status_code=400, detail="Loại phòng không thuộc chi nhánh đích")
    try:
        booking = BookingService(db).transfer_branch(
            booking_id,
            int(payload.target_branch_id),
            int(payload.target_room_type_id),
            payload.reason or "",
            user.get("id"),
        )
        db.commit()
        return _json_success(BookingService(db).serialize(booking), "Đã chuyển chi nhánh đặt phòng")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/pms/reservations/{booking_id}/cancel", tags=["PMS Reservations"])
def api_cancel_reservation(
    booking_id: int,
    payload: CancelPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy đặt phòng")
    _target_branch_id(request, db, user, booking.branch_id)
    try:
        booking = BookingService(db).cancel_reservation(booking_id, payload.reason or "", user.get("id"), no_show=False)
        db.commit()
        return _json_success(BookingService(db).serialize(booking), "Đã hủy đặt phòng")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/pms/reservations/{booking_id}/no-show", tags=["PMS Reservations"])
def api_no_show_reservation(
    booking_id: int,
    payload: CancelPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy đặt phòng")
    _target_branch_id(request, db, user, booking.branch_id)
    try:
        booking = BookingService(db).cancel_reservation(booking_id, payload.reason or "No-show", user.get("id"), no_show=True)
        db.commit()
        return _json_success(BookingService(db).serialize(booking), "Đã ghi nhận no-show")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/pms/reservations/{booking_id}/restore", tags=["PMS Reservations"])
def api_restore_reservation(
    booking_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy đặt phòng")
    _target_branch_id(request, db, user, booking.branch_id)
    try:
        booking = BookingService(db).restore_reservation(booking_id, user.get("id"))
        db.commit()
        return _json_success(BookingService(db).serialize(booking), "Đã khôi phục đặt phòng")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/pms/reservations/{booking_id}/assignable-rooms", tags=["PMS Reservations"])
def api_assignable_rooms(
    booking_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy đặt phòng")
    _target_branch_id(request, db, user, booking.branch_id)
    return JSONResponse(BookingService(db).list_assignable_rooms(booking))


@router.post("/api/pms/reservations/{booking_id}/assign-room", tags=["PMS Reservations"])
def api_assign_room(
    booking_id: int,
    payload: AssignRoomPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy đặt phòng")
    _target_branch_id(request, db, user, booking.branch_id)
    try:
        booking = BookingService(db).assign_room(booking_id, payload.room_id, user.get("id"))
        db.commit()
        return _json_success(BookingService(db).serialize(booking), "Đã gán phòng")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/pms/reservations/{booking_id}/unassign-room", tags=["PMS Reservations"])
def api_unassign_room(
    booking_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy đặt phòng")
    _target_branch_id(request, db, user, booking.branch_id)
    try:
        booking = BookingService(db).unassign_room(booking_id, user.get("id"))
        db.commit()
        return _json_success(BookingService(db).serialize(booking), "Đã gỡ gán phòng")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/pms/reservations/{booking_id}/checkin", tags=["PMS Reservations"])
def api_checkin_reservation(
    booking_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Không tìm thấy đặt phòng")
    _target_branch_id(request, db, user, booking.branch_id)
    if booking.reservation_status != "CONFIRMED":
        raise HTTPException(status_code=400, detail="Chỉ đặt phòng đã xác nhận mới được nhận phòng")
    if not booking.assigned_room_id:
        raise HTTPException(status_code=400, detail="Cần gán phòng trước khi nhận phòng")
    today = datetime.now(VN_TZ).date()
    if booking.check_in and booking.check_in > today:
        raise HTTPException(status_code=400, detail="Chỉ được nhận phòng từ ngày nhận phòng")
    room = booking.assigned_room
    room_type = room.room_type_obj if room else None
    return _json_success({
        "booking_id": booking.id,
        "branch_id": booking.branch_id,
        "room_id": booking.assigned_room_id,
        "room_number": room.room_number if room else None,
        "room_type_id": room.room_type_id if room else None,
        "room_type_name": room_type.name if room_type else booking.room_type,
        "max_guests": room_type.max_guests if room_type else None,
        "price_per_night": float(room_type.price_per_night or 0) if room_type else 0,
        "price_per_hour": float(room_type.price_per_hour or 0) if room_type else 0,
        "price_next_hour": float(room_type.price_next_hour or 0) if room_type else 0,
        "min_hours": room_type.min_hours if room_type else 0,
        "reservation": BookingService(db).serialize(booking),
    }, "Mở luồng nhận phòng để hoàn tất hồ sơ khách và folio")


@router.get("/api/pms/inventory/availability", tags=["PMS Reservations"])
def api_inventory_availability(
    request: Request,
    branch_id: Optional[int] = None,
    check_in: str = Query(...),
    check_out: str = Query(...),
    room_type_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = _target_branch_id(request, db, user, branch_id)
    start = _parse_date(check_in, "Ngày nhận")
    end = _parse_date(check_out, "Ngày trả")
    if not start or not end or end <= start:
        raise HTTPException(status_code=400, detail="Khoảng ngày không hợp lệ")
    return JSONResponse(InventoryService(db).get_availability(target_branch, start, end, room_type_id))


@router.get("/api/pms/inventory/calendar", tags=["PMS Reservations"])
def api_inventory_calendar(
    request: Request,
    branch_id: Optional[int] = None,
    start_date: Optional[str] = None,
    days: int = Query(30, ge=1, le=120),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = _target_branch_id(request, db, user, branch_id)
    start = _parse_date(start_date, "Ngày bắt đầu") or datetime.now(VN_TZ).date()
    return JSONResponse({"calendar": InventoryService(db).get_calendar(target_branch, start, days)})


@router.post("/api/pms/inventory/generate", tags=["PMS Reservations"])
def api_generate_inventory(
    request: Request,
    branch_id: Optional[int] = None,
    start_date: Optional[str] = None,
    days: int = Query(45, ge=1, le=120),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = _target_branch_id(request, db, user, branch_id)
    start = _parse_date(start_date, "Ngày bắt đầu") or datetime.now(VN_TZ).date()
    result = InventoryService(db).generate_daily_inventory(target_branch, start, days)
    db.commit()
    return _json_success(result, "Đã đồng bộ lịch tồn phòng")


@router.get("/api/pms/inventory/blockable-rooms", tags=["PMS Reservations"])
def api_blockable_rooms(
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = _target_branch_id(request, db, user, branch_id)
    return JSONResponse({"rooms": InventoryService(db).list_blockable_rooms(target_branch)})


@router.get("/api/pms/inventory/blocks", tags=["PMS Reservations"])
def api_list_room_blocks(
    request: Request,
    branch_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = _target_branch_id(request, db, user, branch_id)
    service = InventoryService(db)
    return JSONResponse({
        "blocks": service.list_blocks(
            target_branch,
            _parse_date(start_date, "Từ ngày"),
            _parse_date(end_date, "Đến ngày"),
            status,
        )
    })


@router.post("/api/pms/inventory/blocks", tags=["PMS Reservations"])
def api_create_room_block(
    payload: RoomBlockPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    start = _parse_date(payload.start_date, "Ngày bắt đầu")
    end = _parse_date(payload.end_date, "Ngày kết thúc")
    if not start or not end:
        raise HTTPException(status_code=400, detail="Cần nhập khoảng ngày khóa phòng")
    try:
        service = InventoryService(db)
        block = service.create_block(payload.room_id, start, end, payload.reason, user.get("id"))
        db.commit()
        return _json_success(service.serialize_block(block), "Đã khóa phòng")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/pms/inventory/blocks/{block_id}/release", tags=["PMS Reservations"])
def api_release_room_block(
    block_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    service = InventoryService(db)
    try:
        existing = db.query(RoomBlock).filter(RoomBlock.id == block_id).first()
        if not existing:
            raise ValueError("Không tìm thấy lịch khóa phòng")
        _target_branch_id(request, db, user, existing.branch_id)
        block = service.release_block(block_id, user.get("id"))
        db.commit()
        return _json_success(service.serialize_block(block), "Đã mở khóa phòng")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/api/pms/inventory/blocks/{block_id}", tags=["PMS Reservations"])
def api_update_room_block(
    block_id: int,
    payload: RoomBlockUpdatePayload,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    block = db.query(RoomBlock).filter(RoomBlock.id == block_id).first()
    if not block:
        raise HTTPException(status_code=404, detail="Không tìm thấy lịch khóa phòng")
    _target_branch_id(request, db, user, block.branch_id)

    status = (payload.status or "").upper()
    try:
        service = InventoryService(db)
        if status in {"DONE", "RELEASED", "CANCELLED"}:
            block = service.release_block(block_id, user.get("id"))
            if status in {"DONE", "CANCELLED"}:
                block.status = status
        if payload.reason is not None:
            block.reason = payload.reason
        block.updated_at = datetime.now(VN_TZ)
        db.commit()
        return _json_success(service.serialize_block(block), "Đã cập nhật khóa phòng")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/pms/inventory/holds", tags=["PMS Reservations"])
def api_create_inventory_hold(
    payload: InventoryHoldPayload,
    request: Request,
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = _target_branch_id(request, db, user, branch_id)
    check_in = _parse_date(payload.check_in, "Ngày nhận")
    check_out = _parse_date(payload.check_out, "Ngày trả")
    if not check_in or not check_out:
        raise HTTPException(status_code=400, detail="Cần nhập khoảng ngày giữ phòng")
    try:
        holds = InventoryService(db).create_hold(
            branch_id=target_branch,
            room_type_id=payload.room_type_id,
            check_in=check_in,
            check_out=check_out,
            quantity=payload.quantity,
            booking_id=payload.booking_id,
            hold_type=payload.hold_type,
            expire_minutes=payload.expire_minutes,
        )
        db.commit()
        return _json_success({"holds": len(holds)}, "Đã giữ phòng tạm")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/pms/inventory/holds/release-expired", tags=["PMS Reservations"])
def api_release_expired_inventory_holds(
    request: Request,
    db: Session = Depends(get_db),
):
    _require_login(request)
    count = InventoryService(db).release_expired_holds()
    db.commit()
    return _json_success({"released": count}, "Đã giải phóng giữ phòng hết hạn")


@router.get("/api/pms/inventory/timeline", tags=["PMS Reservations"])
def api_inventory_timeline(
    request: Request,
    branch_id: Optional[int] = None,
    start_date: Optional[str] = None,
    days: int = Query(14, ge=1, le=60),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    target_branch = _target_branch_id(request, db, user, branch_id)
    start = _parse_date(start_date, "Ngày bắt đầu") or datetime.now(VN_TZ).date()
    return JSONResponse({"timeline": InventoryService(db).get_timeline(target_branch, start, days)})
