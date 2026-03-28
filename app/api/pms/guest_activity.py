# app/api/pms/guest_activity.py
"""
Guest Activity Service - Timeline logging for all guest actions
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from ...db.models import GuestActivity, Guest, HotelStay, HotelGuest, Booking
from ...core.utils import VN_TZ


# Activity Types
class ActivityType:
    # STAY
    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"
    ROOM_CHANGE = "ROOM_CHANGE"
    EXTEND_STAY = "EXTEND_STAY"
    EARLY_CHECKIN = "EARLY_CHECKIN"
    LATE_CHECKOUT = "LATE_CHECKOUT"
    GUEST_ADDED = "GUEST_ADDED"
    # BOOKING
    BOOKING_CREATED = "BOOKING_CREATED"
    BOOKING_MODIFIED = "BOOKING_MODIFIED"
    BOOKING_CANCELLED = "BOOKING_CANCELLED"
    NO_SHOW = "NO_SHOW"
    # PAYMENT
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    PAYMENT_REFUND = "PAYMENT_REFUND"
    DEPOSIT_ADDED = "DEPOSIT_ADDED"
    DEPOSIT_USED = "DEPOSIT_USED"
    # SERVICE
    SERVICE_USED = "SERVICE_USED"
    MINIBAR_USED = "MINIBAR_USED"
    # EXPERIENCE
    COMPLAINT = "COMPLAINT"
    FEEDBACK = "FEEDBACK"
    REVIEW = "REVIEW"
    LOST_ITEM = "LOST_ITEM"
    # SYSTEM
    PROFILE_UPDATED = "PROFILE_UPDATED"
    MERGED = "MERGED"
    BLACKLISTED = "BLACKLISTED"


# Activity Groups
class ActivityGroup:
    STAY = "stay"
    BOOKING = "booking"
    PAYMENT = "payment"
    SERVICE = "service"
    EXPERIENCE = "experience"
    SYSTEM = "system"


# Actor Types
class ActorType:
    SYSTEM = "system"
    USER = "user"
    GUEST = "guest"


# Sources
class Source:
    PMS = "pms"
    OTA = "ota"
    API = "api"
    AI = "ai"
    POS = "pos"
    WMS = "wms"


def _now_vn() -> datetime:
    return datetime.now(VN_TZ)


def _get_guest_id_from_stay(db: Session, stay: HotelStay) -> Optional[int]:
    """Lấy guest_id từ primary guest của stay"""
    primary = db.query(HotelGuest).filter(
        HotelGuest.stay_id == stay.id,
        HotelGuest.is_primary == True
    ).first()
    return primary.guest_id if primary and primary.guest_id else None


def _get_guest_id_from_hotel_guest(hotel_guest: HotelGuest) -> Optional[int]:
    """Lấy guest_id từ hotel_guest"""
    return hotel_guest.guest_id if hasattr(hotel_guest, 'guest_id') and hotel_guest.guest_id else None


def _get_room_number(stay: HotelStay) -> Optional[str]:
    """Lấy số phòng từ stay"""
    if stay.room:
        return stay.room.room_number
    return None


def log_activity(
    db: Session,
    guest_id: int,
    activity_type: str,
    activity_group: str = ActivityGroup.STAY,
    title: str = "",
    description: str = "",
    stay_id: Optional[int] = None,
    booking_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    amount: Optional[float] = None,
    currency: str = "VND",
    actor_type: str = ActorType.SYSTEM,
    actor_id: Optional[int] = None,
    source: str = Source.PMS,
    extra_data: Optional[Dict[str, Any]] = None,
    created_at: Optional[datetime] = None,
) -> GuestActivity:
    """
    Tạo mới 1 activity record
    """
    activity = GuestActivity(
        guest_id=guest_id,
        activity_type=activity_type,
        activity_group=activity_group,
        title=title,
        description=description,
        stay_id=stay_id,
        booking_id=booking_id,
        branch_id=branch_id,
        amount=amount,
        currency=currency,
        actor_type=actor_type,
        actor_id=actor_id,
        source=source,
        extra_data=extra_data or {},
        created_at=created_at or _now_vn(),
    )
    db.add(activity)
    db.flush()
    return activity


def log_checkin(
    db: Session,
    stay: HotelStay,
    hotel_guest: HotelGuest,
    actor_id: Optional[int] = None,
    guest_count: int = 1,
    extra_guest_names: Optional[list] = None,
) -> GuestActivity:
    """Log check-in event"""
    guest_id = _get_guest_id_from_hotel_guest(hotel_guest)
    if not guest_id:
        return None

    room_number = _get_room_number(stay)
    stay_type = stay.stay_type or "night"

    return log_activity(
        db=db,
        guest_id=guest_id,
        activity_type=ActivityType.CHECK_IN,
        activity_group=ActivityGroup.STAY,
        title=f"Nhận phòng {room_number or ''}",
        description=f"Nhận phòng {stay_type}" + (f" - Phòng {room_number}" if room_number else ""),
        stay_id=stay.id,
        branch_id=stay.branch_id,
        actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
        actor_id=actor_id,
        extra_data={
            "room_number": room_number,
            "stay_type": stay_type,
            "check_in_at": stay.check_in_at.isoformat() if stay.check_in_at else None,
            "check_out_at": stay.check_out_at.isoformat() if stay.check_out_at else None,
            "total_price": float(stay.total_price) if stay.total_price else 0,
            "deposit": float(stay.deposit) if stay.deposit else 0,
            # Guest profile
            "guest_name": hotel_guest.full_name,
            "cccd": hotel_guest.cccd,
            "id_type": hotel_guest.id_type,
            "nationality": hotel_guest.nationality,
            "phone": hotel_guest.phone,
            # Address (địa bàn mới)
            "city": hotel_guest.city,
            "district": hotel_guest.district,
            "ward": hotel_guest.ward,
            # Extra guests
            "guest_count": guest_count,
            "extra_guest_names": extra_guest_names or [],
        }
    )


def log_checkout(
    db: Session,
    stay: HotelStay,
    hotel_guest: HotelGuest,
    final_price: float,
    discount: float = 0,
    extra_charge: float = 0,
    deposit: float = 0,
    actor_id: Optional[int] = None,
    guest_count: int = 1,
) -> GuestActivity:
    """Log check-out event"""
    guest_id = _get_guest_id_from_hotel_guest(hotel_guest)
    if not guest_id:
        return None

    room_number = _get_room_number(stay)
    total_due = final_price - discount + extra_charge

    # Update guest stats
    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if guest:
        guest.total_stays = (guest.total_stays or 0) + 1
        guest.total_spent = (guest.total_spent or 0) + total_due
        guest.last_seen_at = _now_vn()

    return log_activity(
        db=db,
        guest_id=guest_id,
        activity_type=ActivityType.CHECK_OUT,
        activity_group=ActivityGroup.STAY,
        title=f"Trả phòng {room_number or ''}",
        description=f"Trả phòng" + (f" - Phòng {room_number}" if room_number else ""),
        stay_id=stay.id,
        branch_id=stay.branch_id,
        amount=total_due,
        currency="VND",
        actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
        actor_id=actor_id,
        extra_data={
            "room_number": room_number,
            "final_price": float(final_price),
            "discount": float(discount),
            "extra_charge": float(extra_charge),
            "deposit": float(deposit),
            "amount_due": float(total_due),
            "check_in_at": stay.check_in_at.isoformat() if stay.check_in_at else None,
            "check_out_at": _now_vn().isoformat(),
            # Guest profile
            "guest_name": hotel_guest.full_name,
            "cccd": hotel_guest.cccd,
            "id_type": hotel_guest.id_type,
            "nationality": hotel_guest.nationality,
            "guest_count": guest_count,
        }
    )


def log_room_change(
    db: Session,
    stay: HotelStay,
    hotel_guest: HotelGuest,
    from_room: str,
    to_room: str,
    reason: str = "",
    actor_id: Optional[int] = None,
) -> GuestActivity:
    """Log room change event"""
    guest_id = _get_guest_id_from_hotel_guest(hotel_guest)
    if not guest_id:
        return None

    return log_activity(
        db=db,
        guest_id=guest_id,
        activity_type=ActivityType.ROOM_CHANGE,
        activity_group=ActivityGroup.STAY,
        title=f"Chuyển phòng {from_room} → {to_room}",
        description=f"Chuyển phòng: {from_room} → {to_room}" + (f" - Lý do: {reason}" if reason else ""),
        stay_id=stay.id,
        branch_id=stay.branch_id,
        actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
        actor_id=actor_id,
        extra_data={
            "from_room": from_room,
            "to_room": to_room,
            "reason": reason,
            # Guest info
            "guest_name": hotel_guest.full_name,
            "cccd": hotel_guest.cccd,
            "nationality": hotel_guest.nationality,
        }
    )


def log_guest_added_to_stay(
    db: Session,
    stay: HotelStay,
    new_hotel_guest: HotelGuest,
    actor_id: Optional[int] = None,
) -> Optional[GuestActivity]:
    guest_id = _get_guest_id_from_hotel_guest(new_hotel_guest)
    if not guest_id:
        guest_id = _get_guest_id_from_stay(db, stay)
    if not guest_id:
        return None
    room_number = _get_room_number(stay)
    return log_activity(
        db=db,
        guest_id=guest_id,
        activity_type=ActivityType.GUEST_ADDED,
        activity_group=ActivityGroup.STAY,
        title=f"Thêm khách đi cùng: {new_hotel_guest.full_name}",
        description=f"Đã thêm khách vào lưu trú" + (f" — phòng {room_number}" if room_number else ""),
        stay_id=stay.id,
        branch_id=stay.branch_id,
        actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
        actor_id=actor_id,
        extra_data={
            "room_number": room_number,
            "added_name": new_hotel_guest.full_name,
            "cccd": new_hotel_guest.cccd,
            "nationality": new_hotel_guest.nationality,
            "hotel_guest_id": new_hotel_guest.id,
        },
    )


def log_payment(
    db: Session,
    stay: HotelStay,
    hotel_guest: HotelGuest,
    amount: float,
    payment_method: str = "cash",
    folio_id: Optional[int] = None,
    transaction_code: Optional[str] = None,
    description: str = "",
    actor_id: Optional[int] = None,
) -> GuestActivity:
    """Log payment event"""
    guest_id = _get_guest_id_from_hotel_guest(hotel_guest)
    if not guest_id:
        return None

    return log_activity(
        db=db,
        guest_id=guest_id,
        activity_type=ActivityType.PAYMENT_RECEIVED,
        activity_group=ActivityGroup.PAYMENT,
        title=f"Thanh toán {amount:,.0f}đ",
        description=description or f"Thanh toán {amount:,.0f}đ - {payment_method}",
        stay_id=stay.id,
        branch_id=stay.branch_id,
        amount=amount,
        currency="VND",
        actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
        actor_id=actor_id,
        extra_data={
            "method": payment_method,
            "folio_id": folio_id,
            "transaction_code": transaction_code,
        }
    )


def log_deposit(
    db: Session,
    stay: HotelStay,
    hotel_guest: HotelGuest,
    amount: float,
    deposit_type: str = "cash",
    actor_id: Optional[int] = None,
) -> GuestActivity:
    """Log deposit added event"""
    guest_id = _get_guest_id_from_hotel_guest(hotel_guest)
    if not guest_id:
        return None

    return log_activity(
        db=db,
        guest_id=guest_id,
        activity_type=ActivityType.DEPOSIT_ADDED,
        activity_group=ActivityGroup.PAYMENT,
        title=f"Cọc {amount:,.0f}đ",
        description=f"Đặt cọc {amount:,.0f}đ - {deposit_type}",
        stay_id=stay.id,
        branch_id=stay.branch_id,
        amount=amount,
        currency="VND",
        actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
        actor_id=actor_id,
        extra_data={
            "deposit_type": deposit_type,
        }
    )


def log_booking(
    db: Session,
    booking: Booking,
    guest_id: int,
    source: str = Source.OTA,
    actor_id: Optional[int] = None,
) -> GuestActivity:
    """Log booking created event"""
    return log_activity(
        db=db,
        guest_id=guest_id,
        activity_type=ActivityType.BOOKING_CREATED,
        activity_group=ActivityGroup.BOOKING,
        title=f"Đặt phòng mới",
        description=f"Booking #{booking.id} - {source}",
        stay_id=None,
        booking_id=booking.id,
        branch_id=booking.branch_id,
        amount=float(booking.total_price) if booking.total_price else None,
        currency="VND",
        actor_type=ActorType.GUEST,
        source=source,
        extra_data={
            "check_in": booking.check_in_at.isoformat() if booking.check_in_at else None,
            "check_out": booking.check_out_at.isoformat() if booking.check_out_at else None,
            "source": source,
        }
    )


def log_booking_cancelled(
    db: Session,
    booking: Booking,
    guest_id: int,
    reason: str = "",
    actor_id: Optional[int] = None,
) -> GuestActivity:
    """Log booking cancelled event"""
    return log_activity(
        db=db,
        guest_id=guest_id,
        activity_type=ActivityType.BOOKING_CANCELLED,
        activity_group=ActivityGroup.BOOKING,
        title=f"Hủy đặt phòng",
        description=f"Hủy booking #{booking.id}" + (f" - Lý do: {reason}" if reason else ""),
        stay_id=None,
        booking_id=booking.id,
        branch_id=booking.branch_id,
        amount=float(booking.total_price) if booking.total_price else None,
        currency="VND",
        actor_type=ActorType.USER if actor_id else ActorType.GUEST,
        extra_data={
            "reason": reason,
        }
    )


def log_complaint(
    db: Session,
    stay: HotelStay,
    hotel_guest: HotelGuest,
    content: str,
    actor_id: Optional[int] = None,
) -> GuestActivity:
    """Log complaint event"""
    guest_id = _get_guest_id_from_hotel_guest(hotel_guest)
    if not guest_id:
        return None

    room_number = _get_room_number(stay)

    return log_activity(
        db=db,
        guest_id=guest_id,
        activity_type=ActivityType.COMPLAINT,
        activity_group=ActivityGroup.EXPERIENCE,
        title=f"Khiếu nại",
        description=content,
        stay_id=stay.id,
        branch_id=stay.branch_id,
        actor_type=ActorType.USER if actor_id else ActorType.GUEST,
        actor_id=actor_id,
        extra_data={
            "room_number": room_number,
        }
    )


def log_profile_updated(
    db: Session,
    guest: Guest,
    changes: Dict[str, Any],
    actor_id: Optional[int] = None,
) -> GuestActivity:
    """Log profile updated event"""
    return log_activity(
        db=db,
        guest_id=guest.id,
        activity_type=ActivityType.PROFILE_UPDATED,
        activity_group=ActivityGroup.SYSTEM,
        title="Cập nhật thông tin",
        description="Cập nhật thông tin cá nhân",
        branch_id=None,
        actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
        actor_id=actor_id,
        extra_data={"changes": changes}
    )


def log_blacklisted(
    db: Session,
    guest: Guest,
    reason: str = "",
    actor_id: Optional[int] = None,
) -> GuestActivity:
    """Log blacklisted event"""
    return log_activity(
        db=db,
        guest_id=guest.id,
        activity_type=ActivityType.BLACKLISTED,
        activity_group=ActivityGroup.SYSTEM,
        title="Thêm vào danh sách đen",
        description="Khách hàng bị thêm vào danh sách đen" + (f" - Lý do: {reason}" if reason else ""),
        branch_id=None,
        actor_type=ActorType.USER if actor_id else ActorType.SYSTEM,
        actor_id=actor_id,
        extra_data={"reason": reason}
    )


# ─────────────────────────────────────────────────────────────────────────────
# Query helpers for timeline
# ─────────────────────────────────────────────────────────────────────────────

def get_guest_timeline(
    db: Session,
    guest_id: int,
    limit: int = 50,
    offset: int = 0,
    activity_type: Optional[str] = None,
    activity_group: Optional[str] = None,
    stay_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> list:
    """Lấy timeline của guest"""
    query = db.query(GuestActivity).filter(GuestActivity.guest_id == guest_id)

    if activity_type:
        query = query.filter(GuestActivity.activity_type == activity_type)
    if activity_group:
        query = query.filter(GuestActivity.activity_group == activity_group)
    if stay_id:
        query = query.filter(GuestActivity.stay_id == stay_id)
    if branch_id:
        query = query.filter(GuestActivity.branch_id == branch_id)
    if date_from:
        query = query.filter(GuestActivity.created_at >= date_from)
    if date_to:
        query = query.filter(GuestActivity.created_at <= date_to)

    return query.order_by(GuestActivity.created_at.desc()).offset(offset).limit(limit).all()


def get_stay_timeline(
    db: Session,
    stay_id: int,
    limit: int = 50,
    offset: int = 0,
    activity_type: Optional[str] = None,
    activity_group: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> list:
    query = db.query(GuestActivity).filter(GuestActivity.stay_id == stay_id)
    if activity_type:
        query = query.filter(GuestActivity.activity_type == activity_type)
    if activity_group:
        query = query.filter(GuestActivity.activity_group == activity_group)
    if date_from:
        query = query.filter(GuestActivity.created_at >= date_from)
    if date_to:
        query = query.filter(GuestActivity.created_at <= date_to)
    return query.order_by(GuestActivity.created_at.desc()).offset(offset).limit(limit).all()


def get_stay_activity_stats(db: Session, stay_id: int) -> Dict[str, Any]:
    activities = db.query(GuestActivity).filter(GuestActivity.stay_id == stay_id).all()
    total_spent = sum(float(a.amount or 0) for a in activities if a.activity_type == ActivityType.PAYMENT_RECEIVED)
    total_checkins = sum(1 for a in activities if a.activity_type == ActivityType.CHECK_IN)
    total_complaints = sum(1 for a in activities if a.activity_type == ActivityType.COMPLAINT)
    total_payments = sum(1 for a in activities if a.activity_type == ActivityType.PAYMENT_RECEIVED)
    return {
        "total_activities": len(activities),
        "total_checkins": total_checkins,
        "total_checkouts": sum(1 for a in activities if a.activity_type == ActivityType.CHECK_OUT),
        "total_payments": total_payments,
        "total_spent": total_spent,
        "total_complaints": total_complaints,
        "total_reviews": sum(1 for a in activities if a.activity_type == ActivityType.REVIEW),
    }


def get_guest_stats(
    db: Session,
    guest_id: int,
) -> Dict[str, Any]:
    """Lấy thống kê của guest từ activities"""
    activities = db.query(GuestActivity).filter(
        GuestActivity.guest_id == guest_id
    ).all()

    total_spent = sum(float(a.amount or 0) for a in activities if a.activity_type == ActivityType.PAYMENT_RECEIVED)
    total_checkins = sum(1 for a in activities if a.activity_type == ActivityType.CHECK_IN)
    total_complaints = sum(1 for a in activities if a.activity_type == ActivityType.COMPLAINT)
    total_payments = sum(1 for a in activities if a.activity_type == ActivityType.PAYMENT_RECEIVED)

    return {
        "total_activities": len(activities),
        "total_checkins": total_checkins,
        "total_checkouts": sum(1 for a in activities if a.activity_type == ActivityType.CHECK_OUT),
        "total_payments": total_payments,
        "total_spent": total_spent,
        "total_complaints": total_complaints,
        "total_reviews": sum(1 for a in activities if a.activity_type == ActivityType.REVIEW),
    }
