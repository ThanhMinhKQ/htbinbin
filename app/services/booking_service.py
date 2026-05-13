"""Reservation Hub orchestration for PMS bookings."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from ..core.utils import VN_TZ
from ..db.models import (
    Booking,
    BookingStatus,
    Guest,
    GuestActivity,
    GuestIdentity,
    HotelRoom,
    HotelRoomType,
    HotelStay,
    HotelStayStatus,
    RoomBlock,
)
from .room_inventory_service import InventoryService, iter_stay_dates
from .shift_report_service import post_booking_deposit_to_shift


TERMINAL_STATUSES = {"CANCELLED", "CHECKED_OUT", "NO_SHOW"}
ACTIVE_RESERVATION_STATUSES = {"PENDING", "CONFIRMED", "CHECKED_IN"}


def legacy_to_reservation_status(status) -> str:
    value = status.value if hasattr(status, "value") else str(status or "")
    return {
        "CONFIRMED": "CONFIRMED",
        "CANCELLED": "CANCELLED",
        "COMPLETED": "CHECKED_OUT",
        "NO_SHOW": "NO_SHOW",
    }.get(value.upper(), "PENDING")


def reservation_to_legacy_status(status: str) -> BookingStatus:
    value = (status or "").upper()
    return {
        "CANCELLED": BookingStatus.CANCELLED,
        "CHECKED_OUT": BookingStatus.COMPLETED,
        "NO_SHOW": BookingStatus.NO_SHOW,
    }.get(value, BookingStatus.CONFIRMED)


def is_ota_like_booking(booking: Booking) -> bool:
    booking_type = (booking.booking_type or "").upper()
    source = (booking.booking_source or "").strip().lower()
    return booking_type == "OTA" or source not in {"direct", "phone", "walk-in"}


class BookingService:
    def __init__(self, db: Session):
        self.db = db
        self.inventory = InventoryService(db)

    def _now(self) -> datetime:
        return datetime.now(VN_TZ)

    def _booking_type_source(self, booking_type: str) -> str:
        return {
            "OTA": "OTA",
            "WALK_IN": "Walk-in",
            "WEBSITE": "Website",
            "PHONE": "Phone",
            "SALES": "Sales",
            "BOOKING": "Booking",
            "ZALO": "Zalo",
            "DIRECT": "Direct",
        }.get((booking_type or "DIRECT").upper(), "Direct")

    def _generate_external_id(self, booking_type: str) -> str:
        prefix = {
            "WALK_IN": "WALK",
            "WEBSITE": "WEB",
            "PHONE": "PHONE",
            "SALES": "SALES",
            "BOOKING": "BOOK",
            "ZALO": "ZALO",
            "DIRECT": "DIR",
            "OTA": "OTA",
        }.get((booking_type or "DIRECT").upper(), "RSV")
        stamp = self._now().strftime("%y%m%d%H%M%S%f")[:-3]
        return f"{prefix}-{stamp}"

    def _generate_group_code(self, booking_type: str) -> str:
        prefix = {
            "WALK_IN": "WALK",
            "WEBSITE": "WEB",
            "PHONE": "PHONE",
            "SALES": "SALES",
            "BOOKING": "BOOK",
            "ZALO": "ZALO",
            "DIRECT": "DIR",
            "OTA": "OTA",
        }.get((booking_type or "DIRECT").upper(), "RSV")
        stamp = self._now().strftime("%y%m%d%H%M%S%f")[:-3]
        return f"{prefix}-GRP-{stamp}"

    def _room_type_from_payload(self, payload: Dict[str, Any]) -> HotelRoomType:
        room_type_id = payload.get("room_type_id")
        room_type = None
        if room_type_id:
            room_type = self.db.query(HotelRoomType).filter(HotelRoomType.id == int(room_type_id)).first()
        if not room_type and payload.get("room_type"):
            q = self.db.query(HotelRoomType).filter(
                func.lower(HotelRoomType.name) == str(payload["room_type"]).strip().lower()
            )
            if payload.get("branch_id"):
                q = q.filter(HotelRoomType.branch_id == int(payload["branch_id"]))
            room_type = q.first()
        if not room_type:
            raise ValueError("Không tìm thấy loại phòng")
        return room_type

    def _resolve_room_type_id(self, branch_id: Optional[int], room_type_name: Optional[str]) -> Optional[int]:
        if not branch_id or not room_type_name:
            return None
        clean_name = str(room_type_name).strip()
        if not clean_name:
            return None
        normalized = clean_name.lower()
        q = self.db.query(HotelRoomType).filter(
            HotelRoomType.branch_id == branch_id,
            HotelRoomType.is_active == True,
        )
        exact = q.filter(func.lower(HotelRoomType.name) == normalized).first()
        if exact:
            return exact.id
        compact = normalized.replace("(", " ").replace(")", " ")
        for room_type in q.order_by(HotelRoomType.sort_order, HotelRoomType.name).all():
            type_name = (room_type.name or "").lower()
            if type_name and (type_name in compact or compact in type_name):
                return room_type.id
        return None

    def _find_or_create_guest(self, payload: Dict[str, Any], user_id: Optional[int]) -> Optional[Guest]:
        name = (payload.get("guest_name") or "").strip()
        phone = (payload.get("guest_phone") or "").strip()
        email = (payload.get("guest_email") or payload.get("email") or "").strip().lower()
        cccd = (payload.get("guest_cccd") or payload.get("cccd") or payload.get("id_number") or "").strip()
        if not name:
            return None

        guest = None
        if cccd:
            guest = self.db.query(Guest).filter(Guest.cccd == cccd, Guest.deleted_at.is_(None)).first()
        if phone:
            guest = guest or self.db.query(Guest).filter(Guest.phone == phone, Guest.deleted_at.is_(None)).first()
        if email:
            guest = guest or self.db.query(Guest).filter(Guest.email == email, Guest.deleted_at.is_(None)).first()
        if guest:
            guest.phone = phone or guest.phone
            guest.email = email or guest.email
            guest.cccd = cccd or guest.cccd
            if payload.get("date_of_birth"):
                guest.date_of_birth = date.fromisoformat(str(payload["date_of_birth"])[:10])
            guest.gender = payload.get("gender") or guest.gender
            guest.nationality = payload.get("nationality") or guest.nationality
            guest.default_address = payload.get("default_address") or payload.get("address") or guest.default_address
            if payload.get("id_expire"):
                guest.id_expire = date.fromisoformat(str(payload["id_expire"])[:10])
            guest.last_seen_at = self._now()
            guest.updated_by = user_id
            self._sync_guest_identities(guest, phone=phone, email=email, cccd=cccd)
            return guest

        guest = Guest(
            full_name=name,
            phone=phone or None,
            email=email or None,
            cccd=cccd or None,
            date_of_birth=date.fromisoformat(str(payload["date_of_birth"])[:10]) if payload.get("date_of_birth") else None,
            gender=payload.get("gender"),
            nationality=payload.get("nationality"),
            id_expire=date.fromisoformat(str(payload["id_expire"])[:10]) if payload.get("id_expire") else None,
            default_address=payload.get("default_address") or payload.get("address"),
            first_seen_at=self._now(),
            last_seen_at=self._now(),
            created_by=user_id,
        )
        self.db.add(guest)
        self.db.flush()
        self._sync_guest_identities(guest, phone=phone, email=email, cccd=cccd)
        return guest

    def _sync_guest_identities(self, guest: Guest, phone: str = "", email: str = "", cccd: str = "") -> None:
        identities = [
            ("phone", phone.strip()),
            ("email", email.strip().lower()),
            ("cccd", cccd.strip()),
        ]
        for identity_type, value in identities:
            if not value:
                continue
            exists = self.db.query(GuestIdentity).filter(
                GuestIdentity.identity_type == identity_type,
                GuestIdentity.normalized_value == value,
            ).first()
            if exists:
                continue
            self.db.add(GuestIdentity(
                guest_id=guest.id,
                identity_type=identity_type,
                identity_value=value,
                normalized_value=value,
                is_primary=True,
            ))

    def _log_booking_activity(self, booking: Booking, activity_type: str, title: str, user_id: Optional[int], description: str = "") -> None:
        if not booking.guest_id:
            return
        self.db.add(GuestActivity(
            guest_id=booking.guest_id,
            activity_type=activity_type,
            activity_group="booking",
            title=title,
            description=description or f"Booking {booking.external_id}",
            booking_id=booking.id,
            branch_id=booking.branch_id,
            amount=booking.total_price or Decimal("0"),
            currency=booking.currency or "VND",
            actor_type="user" if user_id else "system",
            actor_id=user_id,
            source="pms",
            extra_data={
                "booking_type": booking.booking_type,
                "reservation_status": booking.reservation_status,
                "check_in": booking.check_in.isoformat() if booking.check_in else None,
                "check_out": booking.check_out.isoformat() if booking.check_out else None,
            },
        ))

    def _post_booking_deposit_once(self, booking: Booking, user_id: Optional[int]) -> None:
        if not booking.deposit_amount or booking.deposit_amount <= 0:
            return

        # Row-lock booking và re-check flag trong cùng một giao dịch để
        # chống double-post khi hai tiến trình (vd: check-in + cron sync)
        # cùng xử lý một booking.
        locked = (
            self.db.query(Booking)
            .filter(Booking.id == booking.id)
            .with_for_update()
            .first()
        )
        if locked is None:
            return

        raw = dict(locked.raw_data or {})
        if raw.get("deposit_shift_posted"):
            # Đã có tiến trình khác post xong trước — đồng bộ object in-memory
            if booking is not locked:
                booking.raw_data = dict(raw)
            return

        tx = post_booking_deposit_to_shift(
            db=self.db,
            branch_id=locked.branch_id,
            user_id=user_id,
            booking_code=locked.external_id,
            guest_name=locked.guest_name,
            amount=locked.deposit_amount,
            payment_method=locked.payment_method or raw.get("deposit_type") or "Chi nhánh",
            room_label=locked.room_type or "Đặt phòng",
        )
        if not tx:
            return

        raw["deposit_shift_posted"] = True
        raw["deposit_shift_transaction_id"] = tx.id
        raw["deposit_shift_transaction_code"] = tx.transaction_code
        raw["deposit_applied_to_folio"] = False
        locked.raw_data = raw
        # Flush ngay để flag được persist trước khi commit tổng; nếu nhánh ngoài
        # rollback thì ShiftReportTransaction mới tạo cũng rollback theo.
        self.db.flush()
        if booking is not locked:
            booking.raw_data = dict(raw)

    def _reserved_snapshot(self, booking: Booking) -> Dict[str, Any]:
        raw = dict(booking.raw_data or {})
        room_type_id = raw.get("reservation_reserved_room_type_id") or raw.get("room_type_id")
        return {
            "reserved": bool(raw.get("reservation_inventory_reserved")) or booking.reservation_status == "CONFIRMED",
            "room_type_id": int(room_type_id) if room_type_id else None,
            "check_in": date.fromisoformat(raw.get("reservation_reserved_check_in")) if raw.get("reservation_reserved_check_in") else booking.check_in,
            "check_out": date.fromisoformat(raw.get("reservation_reserved_check_out")) if raw.get("reservation_reserved_check_out") else booking.check_out,
            "quantity": int(raw.get("reservation_reserved_qty") or (1 if raw.get("group_code") or raw.get("group_index") else raw.get("num_rooms") or 1)),
        }

    def _mark_reserved(self, booking: Booking, room_type_id: int, quantity: int = 1) -> None:
        raw = dict(booking.raw_data or {})
        raw["room_type_id"] = int(room_type_id)
        raw["reservation_inventory_reserved"] = True
        raw["reservation_reserved_room_type_id"] = int(room_type_id)
        raw["reservation_reserved_check_in"] = booking.check_in.isoformat()
        raw["reservation_reserved_check_out"] = booking.check_out.isoformat()
        raw["reservation_reserved_qty"] = int(quantity)
        raw.pop("over_capacity_pending", None)
        raw.pop("over_capacity_reason", None)
        raw.pop("over_capacity_dates", None)
        booking.raw_data = raw

    def _mark_over_capacity_pending(self, raw: Dict[str, Any], branch_id: int, room_type_id: int, check_in: date, check_out: date, quantity: int = 1) -> Dict[str, Any]:
        shortages = []
        for target_date in iter_stay_dates(check_in, check_out):
            inv = self.inventory.get_or_create_inventory(branch_id, room_type_id, target_date)
            if inv.available_rooms < quantity:
                shortages.append(target_date.isoformat())
        raw["over_capacity_pending"] = True
        raw["over_capacity_reason"] = "Không đủ tồn phòng để xác nhận"
        raw["over_capacity_dates"] = shortages
        raw["reservation_inventory_reserved"] = False
        return raw

    def _has_available_inventory(self, branch_id: int, room_type_id: int, check_in: date, check_out: date, quantity: int = 1) -> bool:
        for target_date in iter_stay_dates(check_in, check_out):
            inv = self.inventory.get_or_create_inventory(branch_id, room_type_id, target_date)
            if inv.available_rooms < quantity:
                return False
        return True

    def _mark_unreserved(self, booking: Booking) -> None:
        raw = dict(booking.raw_data or {})
        raw["reservation_inventory_reserved"] = False
        booking.raw_data = raw

    def _release_reserved_snapshot(self, booking: Booking, snapshot: Dict[str, Any], user_id: Optional[int], change_type: str) -> None:
        if not snapshot.get("reserved") or not snapshot.get("room_type_id"):
            return
        self.inventory.release_booking(
            booking.id,
            booking.branch_id,
            int(snapshot["room_type_id"]),
            snapshot["check_in"],
            snapshot["check_out"],
            int(snapshot.get("quantity") or 1),
            user_id,
            change_type,
        )
        self._mark_unreserved(booking)

    def _stay_blocks_booking_dates(self, stay: HotelStay, booking: Booking) -> bool:
        stay_start = stay.check_in_at.astimezone(VN_TZ).date() if stay.check_in_at.tzinfo else stay.check_in_at.date()
        stay_end = stay.check_out_at.astimezone(VN_TZ).date() if stay.check_out_at and stay.check_out_at.tzinfo else (stay.check_out_at.date() if stay.check_out_at else None)
        return stay_start < booking.check_out and (stay_end is None or stay_end > booking.check_in)

    def _room_conflict_reason(self, booking: Booking, room_id: int) -> Optional[str]:
        active_stays = self.db.query(HotelStay).filter(
            HotelStay.room_id == room_id,
            HotelStay.status == HotelStayStatus.ACTIVE,
        ).all()
        if any(self._stay_blocks_booking_dates(stay, booking) for stay in active_stays):
            return "Phòng đang có khách ở trong khoảng ngày này"

        other_booking = self.db.query(Booking).filter(
            Booking.id != booking.id,
            Booking.assigned_room_id == room_id,
            Booking.reservation_status.in_(list(ACTIVE_RESERVATION_STATUSES)),
            Booking.check_in < booking.check_out,
            Booking.check_out > booking.check_in,
        ).first()
        if other_booking:
            return f"Phòng đã được gán cho booking {other_booking.external_id}"

        block = self.db.query(RoomBlock).filter(
            RoomBlock.room_id == room_id,
            RoomBlock.status == "ACTIVE",
            RoomBlock.start_date < booking.check_out,
            RoomBlock.end_date > booking.check_in,
        ).first()
        if block:
            return "Phòng đang bị khóa/bảo trì trong khoảng ngày này"
        return None

    def list_assignable_rooms(self, booking: Booking) -> list[Dict[str, Any]]:
        room_type_id = (booking.raw_data or {}).get("room_type_id")
        q = self.db.query(HotelRoom).filter(
            HotelRoom.branch_id == booking.branch_id,
            HotelRoom.is_active == True,
        ).options(joinedload(HotelRoom.room_type_obj))
        if room_type_id:
            q = q.filter(HotelRoom.room_type_id == int(room_type_id))

        candidate_rooms = q.order_by(HotelRoom.floor, HotelRoom.sort_order, HotelRoom.room_number).all()
        if not candidate_rooms:
            return []

        room_ids = [room.id for room in candidate_rooms]
        active_stay_room_ids = {
            int(stay.room_id) for stay in self.db.query(HotelStay).filter(
                HotelStay.room_id.in_(room_ids),
                HotelStay.status == HotelStayStatus.ACTIVE,
            ).all()
            if self._stay_blocks_booking_dates(stay, booking)
        }
        assigned_room_ids = {
            row[0] for row in self.db.query(Booking.assigned_room_id).filter(
                Booking.id != booking.id,
                Booking.assigned_room_id.in_(room_ids),
                Booking.reservation_status.in_(list(ACTIVE_RESERVATION_STATUSES)),
                Booking.check_in < booking.check_out,
                Booking.check_out > booking.check_in,
            ).all()
        }
        blocked_room_ids = {
            row[0] for row in self.db.query(RoomBlock.room_id).filter(
                RoomBlock.room_id.in_(room_ids),
                RoomBlock.status == "ACTIVE",
                RoomBlock.start_date < booking.check_out,
                RoomBlock.end_date > booking.check_in,
            ).all()
        }
        unavailable_room_ids = active_stay_room_ids | assigned_room_ids | blocked_room_ids

        rooms = []
        for room in candidate_rooms:
            if room.id in unavailable_room_ids and room.id != booking.assigned_room_id:
                continue
            rooms.append({
                "id": room.id,
                "room_number": room.room_number,
                "floor": room.floor,
                "room_type_id": room.room_type_id,
                "room_type_name": room.room_type_obj.name if room.room_type_obj else None,
                "is_assigned": room.id == booking.assigned_room_id,
            })
        return rooms

    def serialize(self, booking: Booking) -> Dict[str, Any]:
        raw = booking.raw_data or {}
        status = booking.reservation_status or legacy_to_reservation_status(booking.status)
        room_type_id = raw.get("room_type_id")
        if not room_type_id:
            room_type_id = self._resolve_room_type_id(booking.branch_id, booking.room_type)
        return {
            "id": booking.id,
            "external_id": booking.external_id,
            "booking_source": booking.booking_source,
            "booking_type": booking.booking_type or "OTA",
            "reservation_status": status,
            "status": booking.status.value if hasattr(booking.status, "value") else str(booking.status),
            "guest_name": booking.guest_name,
            "guest_phone": booking.guest_phone,
            "check_in": booking.check_in.isoformat() if booking.check_in else None,
            "check_out": booking.check_out.isoformat() if booking.check_out else None,
            "room_type": booking.room_type,
            "room_type_id": room_type_id,
            "group_code": raw.get("group_code"),
            "group_index": raw.get("group_index"),
            "group_total": raw.get("group_total"),
            "group_summary": raw.get("group_summary"),
            "ota_group_code": raw.get("ota_group_code"),
            "ota_group_total": float(raw.get("ota_group_total") or 0),
            "ota_group_child_total": float(raw.get("ota_group_child_total") or 0),
            "ota_group_reference_total": float(raw.get("ota_group_reference_total") or 0),
            "ota_group_reference_child_total": float(raw.get("ota_group_reference_child_total") or 0),
            "source_booking_id": booking.source_booking_id,
            "num_guests": booking.num_guests or 1,
            "num_adults": booking.num_adults or 1,
            "num_children": booking.num_children or 0,
            "total_price": float(booking.total_price or 0),
            "currency": booking.currency or "VND",
            "is_prepaid": bool(booking.is_prepaid),
            "deposit_amount": float(booking.deposit_amount or 0),
            "payment_method": booking.payment_method,
            "deposit_type": raw.get("deposit_type"),
            "deposit_meta": raw.get("deposit_meta"),
            "deposit_shift_posted": bool(raw.get("deposit_shift_posted")),
            "deposit_shift_transaction_id": raw.get("deposit_shift_transaction_id"),
            "deposit_applied_to_folio": bool(raw.get("deposit_applied_to_folio")),
            "raw_data": raw,
            "guest_id_type": raw.get("guest_id_type") or "cccd",
            "branch_id": booking.branch_id,
            "branch_name": booking.branch.name if booking.branch else None,
            "branch_code": booking.branch.branch_code if booking.branch else None,
            "branch_address": booking.branch.address if booking.branch else None,
            "guest_id": booking.guest_id,
            "assigned_room_id": booking.assigned_room_id,
            "assigned_room_number": booking.assigned_room.room_number if booking.assigned_room else None,
            "stay_id": booking.stay_id,
            "estimated_arrival": booking.estimated_arrival.isoformat() if booking.estimated_arrival else None,
            "special_requests": booking.special_requests or (booking.raw_data or {}).get("special_requests") or (booking.raw_data or {}).get("notes"),
            "internal_notes": booking.internal_notes,
            "cancel_reason": booking.cancel_reason,
            "guest_email": booking.guest.email if booking.guest else (booking.raw_data or {}).get("guest_email"),
            "guest_cccd": booking.guest.cccd if booking.guest else (booking.raw_data or {}).get("guest_cccd"),
            "gender": booking.guest.gender if booking.guest else (booking.raw_data or {}).get("gender"),
            "date_of_birth": booking.guest.date_of_birth.isoformat() if booking.guest and booking.guest.date_of_birth else (booking.raw_data or {}).get("date_of_birth"),
            "nationality": booking.guest.nationality if booking.guest else (booking.raw_data or {}).get("nationality"),
            "id_expire": booking.guest.id_expire.isoformat() if booking.guest and booking.guest.id_expire else (booking.raw_data or {}).get("id_expire"),
            "address": booking.guest.default_address if booking.guest else (booking.raw_data or {}).get("address"),
            "address_detail": raw.get("address_detail") or raw.get("guest_address_detail") or raw.get("address"),
            "address_type": raw.get("address_type") or "new",
            "city": raw.get("city") or raw.get("new_city") or "",
            "district": raw.get("district") or "",
            "ward": raw.get("ward") or raw.get("new_ward") or "",
            "new_city": raw.get("new_city") or "",
            "new_ward": raw.get("new_ward") or "",
            "old_city": raw.get("old_city") or "",
            "old_district": raw.get("old_district") or "",
            "old_ward": raw.get("old_ward") or "",
            "guest_tier": booking.guest.membership.tier.value if booking.guest and booking.guest.membership else "BASIC",
            "created_at": booking.created_at.isoformat() if booking.created_at else None,
            "updated_at": booking.updated_at.isoformat() if booking.updated_at else None,
        }

    def list_reservations(
        self,
        branch_id: Optional[int] = None,
        status: Optional[str] = None,
        source: Optional[str] = None,
        search: Optional[str] = None,
        check_in_from: Optional[date] = None,
        check_in_to: Optional[date] = None,
        page: int = 1,
        page_size: int = 30,
    ) -> Dict[str, Any]:
        q = self.db.query(Booking).options(
            joinedload(Booking.branch),
            joinedload(Booking.assigned_room),
            joinedload(Booking.guest).joinedload(Guest.membership),
        )
        if branch_id:
            q = q.filter(Booking.branch_id == branch_id)
        if status:
            q = q.filter(Booking.reservation_status == status.upper())
        if source:
            q = q.filter(Booking.booking_type == source.upper())
        if search:
            like = f"%{search.strip()}%"
            q = q.filter(or_(
                Booking.guest_name.ilike(like),
                Booking.guest_phone.ilike(like),
                Booking.external_id.ilike(like),
                Booking.room_type.ilike(like),
            ))
        if check_in_from:
            q = q.filter(Booking.check_in >= check_in_from)
        if check_in_to:
            q = q.filter(Booking.check_in <= check_in_to)

        total = q.count()
        items = q.order_by(Booking.created_at.desc(), Booking.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return {
            "items": [self.serialize(b) for b in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total else 0,
        }

    def create_reservation(self, payload: Dict[str, Any], user_id: Optional[int]) -> Booking:
        room_type = self._room_type_from_payload(payload)
        branch_id = int(payload.get("branch_id") or room_type.branch_id)
        check_in = date.fromisoformat(str(payload["check_in"]))
        check_out = date.fromisoformat(str(payload["check_out"]))
        if check_out <= check_in:
            raise ValueError("Ngày trả phòng phải sau ngày nhận phòng")

        booking_type = str(payload.get("booking_type") or "DIRECT").upper()
        auto_confirm = booking_type == "WALK_IN"
        reservation_status = str(payload.get("reservation_status") or ("CONFIRMED" if auto_confirm else "PENDING")).upper()
        if reservation_status not in {"PENDING", "CONFIRMED"}:
            reservation_status = "PENDING"

        guest = None
        external_id = (payload.get("external_id") or "").strip() or self._generate_external_id(booking_type)
        estimated_arrival = None
        if payload.get("estimated_arrival"):
            estimated_arrival = time.fromisoformat(str(payload["estimated_arrival"]))

        raw_data = dict(payload.get("raw_data") or {})
        raw_data["room_type_id"] = room_type.id
        if reservation_status == "CONFIRMED" and not self._has_available_inventory(branch_id, room_type.id, check_in, check_out, 1):
            reservation_status = "PENDING"
            raw_data = self._mark_over_capacity_pending(raw_data, branch_id, room_type.id, check_in, check_out, 1)
        if payload.get("guest_id"):
            raw_data["selected_crm_guest_id"] = payload.get("guest_id")

        booking = Booking(
            booking_source=payload.get("booking_source") or self._booking_type_source(booking_type),
            external_id=external_id,
            guest_name=(str(payload.get("guest_name") or "").strip() or "Khách lẻ"),
            guest_phone=(payload.get("guest_phone") or "").strip() or None,
            check_in=check_in,
            check_out=check_out,
            room_type=room_type.name,
            num_guests=int(payload.get("num_guests") or 1),
            num_adults=int(payload.get("num_adults") or payload.get("num_guests") or 1),
            num_children=int(payload.get("num_children") or 0),
            total_price=Decimal(str(payload.get("total_price") or 0)),
            currency=payload.get("currency") or "VND",
            is_prepaid=bool(payload.get("is_prepaid") or False),
            payment_method=payload.get("payment_method"),
            deposit_amount=Decimal(str(payload.get("deposit_amount") or 0)),
            status=reservation_to_legacy_status(reservation_status),
            branch_id=branch_id,
            guest_id=guest.id if guest else None,
            raw_data=raw_data,
            created_by=user_id,
            updated_by=user_id,
            booking_type=booking_type,
            reservation_status=reservation_status,
            estimated_arrival=estimated_arrival,
            special_requests=payload.get("special_requests"),
            internal_notes=payload.get("internal_notes"),
            confirmed_at=self._now() if reservation_status == "CONFIRMED" else None,
        )
        self.db.add(booking)
        self.db.flush()

        if reservation_status == "CONFIRMED":
            self.inventory.reserve_booking(booking.id, branch_id, room_type.id, check_in, check_out, 1, user_id)
            self._mark_reserved(booking, room_type.id)

        self._log_booking_activity(booking, "BOOKING_CREATED", "Tạo đặt phòng", user_id)
        self._post_booking_deposit_once(booking, user_id)
        self.db.flush()
        return booking

    def create_group_reservation(self, payload: Dict[str, Any], user_id: Optional[int]) -> list[Booking]:
        items = payload.get("room_items") or []
        if not isinstance(items, list) or not items:
            raise ValueError("Cần chọn ít nhất một loại phòng")

        normalized_items = []
        for item in items:
            room_type_id = item.get("room_type_id")
            qty = int(item.get("quantity") or 0)
            if not room_type_id or qty < 1:
                continue
            room_type = self.db.query(HotelRoomType).filter(HotelRoomType.id == int(room_type_id)).first()
            if not room_type:
                raise ValueError("Không tìm thấy loại phòng")
            branch_id = int(payload.get("branch_id") or room_type.branch_id)
            if int(room_type.branch_id) != branch_id:
                raise ValueError("Loại phòng không thuộc chi nhánh đang chọn")
            normalized_items.append({
                "room_type": room_type,
                "quantity": qty,
                "unit_total": Decimal(str(item.get("unit_total") or 0)),
                "reference_unit_total": Decimal(str(item.get("reference_unit_total") or item.get("unit_total") or 0)),
            })

        if not normalized_items:
            raise ValueError("Cần chọn ít nhất một loại phòng")

        total_qty = sum(item["quantity"] for item in normalized_items)
        booking_type = str(payload.get("booking_type") or "DIRECT").upper()
        is_ota = booking_type == "OTA"
        total_price = Decimal(str(payload.get("total_price") or 0))
        raw_payload = dict(payload.get("raw_data") or {})
        ota_group_code = str(
            payload.get("external_id")
            or raw_payload.get("booking_reference_code")
            or raw_payload.get("ota_group_code")
            or ""
        ).strip()

        if total_qty == 1:
            single = normalized_items[0]
            single_payload = dict(payload)
            single_payload.pop("room_items", None)
            single_payload["room_type_id"] = single["room_type"].id
            single_payload["total_price"] = float(total_price if is_ota and total_price else single["unit_total"] or total_price)
            if is_ota:
                raw_data = dict(raw_payload)
                raw_data.update({
                    "ota_price_mode": "manual_channel_total",
                    "ota_group_code": ota_group_code,
                    "ota_group_total": float(total_price),
                    "ota_group_child_total": float(total_price),
                    "ota_group_reference_total": float(single["reference_unit_total"]),
                    "ota_group_reference_child_total": float(single["reference_unit_total"]),
                })
                single_payload["raw_data"] = raw_data
            return [self.create_reservation(single_payload, user_id)]

        group_code = ota_group_code or self._generate_group_code(booking_type)
        group_summary = ", ".join(
            f"{item['room_type'].name} x{item['quantity']}" for item in normalized_items
        )
        deposit_amount = Decimal(str(payload.get("deposit_amount") or 0))
        deposit_allocation = raw_payload.get("deposit_allocation") if isinstance(raw_payload, dict) else None
        explicit_deposits: dict[tuple[int, int], Decimal] = {}
        if isinstance(deposit_allocation, dict):
            for allocation_item in deposit_allocation.get("items") or []:
                if not isinstance(allocation_item, dict):
                    continue
                try:
                    key = (int(allocation_item.get("room_type_id")), int(allocation_item.get("room_type_index") or 1))
                    explicit_deposits[key] = Decimal(str(allocation_item.get("amount") or 0))
                except (TypeError, ValueError):
                    continue
        use_explicit_deposits = bool(explicit_deposits)
        bookings: list[Booking] = []
        group_index = 0
        reference_total = sum((item["reference_unit_total"] * item["quantity"] for item in normalized_items), Decimal("0"))
        has_item_totals = any(item["unit_total"] > 0 for item in normalized_items)
        split_total = total_price if total_price and (is_ota or not has_item_totals) else Decimal("0")
        price_left = split_total
        ref_left = reference_total
        deposit_left = deposit_amount

        for item_idx, item in enumerate(normalized_items):
            for qty_idx in range(item["quantity"]):
                group_index += 1
                is_last = group_index == total_qty
                reference_unit_total = item["reference_unit_total"]
                unit_total = item["unit_total"]
                if split_total:
                    if is_last:
                        unit_total = price_left
                    elif is_ota and reference_total > 0 and reference_unit_total > 0:
                        unit_total = (split_total * reference_unit_total / reference_total).quantize(Decimal("1"))
                    else:
                        unit_total = (split_total / Decimal(total_qty)).quantize(Decimal("1"))
                    price_left -= unit_total
                if not is_ota and not unit_total and split_total:
                    unit_total = price_left if is_last else (split_total / Decimal(total_qty)).quantize(Decimal("1"))
                    price_left -= unit_total
                reference_child_total = ref_left if is_last else reference_unit_total
                ref_left -= reference_child_total
                if use_explicit_deposits:
                    unit_deposit = explicit_deposits.get((int(item["room_type"].id), qty_idx + 1), Decimal("0"))
                else:
                    unit_deposit = deposit_left if is_last else (deposit_amount / Decimal(total_qty)).quantize(Decimal("1"))
                    deposit_left -= unit_deposit

                raw_data = dict(raw_payload)
                raw_data.update({
                    "group_code": group_code,
                    "group_index": group_index,
                    "group_total": total_qty,
                    "group_summary": group_summary,
                    "group_room_type_quantity": item["quantity"],
                    "group_room_type_index": qty_idx + 1,
                    "num_rooms": 1,
                })
                if is_ota:
                    raw_data.update({
                        "booking_reference_code": ota_group_code,
                        "ota_group_code": ota_group_code,
                        "ota_price_mode": "manual_channel_total",
                        "ota_group_total": float(total_price),
                        "ota_group_child_total": float(unit_total),
                        "ota_group_reference_total": float(reference_total),
                        "ota_group_reference_child_total": float(reference_child_total),
                        "ota_actual_total": float(unit_total),
                        "pms_reference_total": float(reference_child_total),
                        "ota_price_delta": float(unit_total - reference_child_total),
                    })
                item_payload = dict(payload)
                item_payload.pop("room_items", None)
                item_payload["room_type_id"] = item["room_type"].id
                item_payload["total_price"] = float(unit_total)
                item_payload["deposit_amount"] = float(unit_deposit)
                item_payload["external_id"] = f"{group_code}-{group_index:02d}"
                item_payload["raw_data"] = raw_data
                booking = self.create_reservation(item_payload, user_id)
                bookings.append(booking)

        parent_id = bookings[0].id if bookings else None
        for booking in bookings[1:]:
            booking.source_booking_id = parent_id
        self.db.flush()
        return bookings

    def normalize_existing_booking(self, booking: Booking, user_id: Optional[int] = None, reserve_inventory: bool = True) -> Booking:
        raw = dict(booking.raw_data or {})
        old_reserved_key = "reservation_inventory_reserved"
        old_room_type_id = raw.get("room_type_id")

        booking_type = (booking.booking_type or "").upper()
        if not booking_type:
            booking_type = "OTA" if (booking.booking_source or "").lower() not in {"direct", "phone", "walk-in"} else "DIRECT"
        booking.booking_type = booking_type
        booking.reservation_status = booking.reservation_status or legacy_to_reservation_status(booking.status)
        if booking.status in {BookingStatus.CANCELLED, BookingStatus.NO_SHOW, BookingStatus.COMPLETED}:
            booking.reservation_status = legacy_to_reservation_status(booking.status)

        room_type_id = old_room_type_id or self._resolve_room_type_id(booking.branch_id, booking.room_type)
        if room_type_id:
            raw["room_type_id"] = int(room_type_id)

        for key in ("special_requests", "special_request", "guest_requests", "guest_notes", "notes", "remarks", "requests"):
            if raw.get(key) and not booking.special_requests:
                booking.special_requests = raw.get(key)
                break

        # Chỉ link CRM khi user chủ động chọn guest từ CRM (selected_crm_guest_id).
        # Không tự động tạo guest mới khi tạo/cập nhật booking — CRM chỉ được tạo khi check-in.
        selected_crm_guest_id = raw.get("selected_crm_guest_id")
        if selected_crm_guest_id and not booking.guest_id:
            existing_guest = self.db.query(Guest).filter(
                Guest.id == int(selected_crm_guest_id),
                Guest.deleted_at.is_(None)
            ).first()
            if existing_guest:
                booking.guest_id = existing_guest.id

        if isinstance(booking.check_in, str):
            booking.check_in = date.fromisoformat(booking.check_in[:10])
        if isinstance(booking.check_out, str):
            booking.check_out = date.fromisoformat(booking.check_out[:10])
        if booking.check_in and booking.check_out and booking.check_out <= booking.check_in:
            booking.check_out = booking.check_in + timedelta(days=1)
            raw["ota_actual_check_out"] = raw.get("check_out") or booking.check_out.isoformat()
            raw["ota_same_day_booking"] = True

        has_reserved = bool(raw.get(old_reserved_key))
        reserved_room_type_id = raw.get("reservation_reserved_room_type_id") or room_type_id
        reserved_check_in = raw.get("reservation_reserved_check_in") or (booking.check_in.isoformat() if booking.check_in else None)
        reserved_check_out = raw.get("reservation_reserved_check_out") or (booking.check_out.isoformat() if booking.check_out else None)
        is_group_child = bool(raw.get("group_code") or raw.get("group_index"))
        effective_qty = int(raw.get("reservation_reserved_qty") or (1 if is_group_child else raw.get("num_rooms") or 1))
        reserved_qty = effective_qty
        should_reserve = (
            reserve_inventory
            and booking.reservation_status == "CONFIRMED"
            and bool(room_type_id)
            and bool(booking.branch_id)
        )
        reserved_changed = (
            has_reserved
            and should_reserve
            and (
                int(reserved_room_type_id or 0) != int(room_type_id or 0)
                or reserved_check_in != (booking.check_in.isoformat() if booking.check_in else None)
                or reserved_check_out != (booking.check_out.isoformat() if booking.check_out else None)
                or reserved_qty != effective_qty
            )
        )
        if reserved_changed and reserved_room_type_id:
            self.inventory.release_booking(
                booking.id,
                booking.branch_id,
                int(reserved_room_type_id),
                date.fromisoformat(reserved_check_in),
                date.fromisoformat(reserved_check_out),
                reserved_qty,
                user_id,
                "MODIFY",
            )
            raw[old_reserved_key] = False
            has_reserved = False

        if should_reserve and not has_reserved:
            self.inventory.reserve_booking(
                booking.id,
                booking.branch_id,
                int(room_type_id),
                booking.check_in,
                booking.check_out,
                effective_qty,
                user_id,
            )
            raw[old_reserved_key] = True
            raw["reservation_reserved_room_type_id"] = int(room_type_id)
            raw["reservation_reserved_check_in"] = booking.check_in.isoformat()
            raw["reservation_reserved_check_out"] = booking.check_out.isoformat()
            raw["reservation_reserved_qty"] = effective_qty
        elif has_reserved and booking.reservation_status in {"CANCELLED", "NO_SHOW"}:
            if reserved_room_type_id:
                self.inventory.release_booking(
                    booking.id,
                    booking.branch_id,
                    int(reserved_room_type_id),
                    date.fromisoformat(reserved_check_in),
                    date.fromisoformat(reserved_check_out),
                    reserved_qty,
                    user_id,
                    "NO_SHOW" if booking.reservation_status == "NO_SHOW" else "CANCEL",
                )
            raw[old_reserved_key] = False

        booking.raw_data = raw
        booking.status = reservation_to_legacy_status(booking.reservation_status)
        booking.updated_by = user_id or booking.updated_by
        booking.updated_at = self._now()
        self._log_booking_activity(booking, "BOOKING_MODIFIED", "Đồng bộ đặt phòng", user_id)
        self.db.flush()
        return booking

    def stage_ota_booking_for_review(self, booking: Booking, user_id: Optional[int] = None) -> Booking:
        raw = dict(booking.raw_data or {})
        raw.pop("ota_review_required", None)
        raw["ota_review_status"] = "AUTO_IMPORTED"
        # OTA tự động chỉ tạo đặt phòng kèm tổng tiền (total_price), không ghi nhận tiền cọc.
        # Giữ payment/is_prepaid nếu cần hiển thị trạng thái OTA, nhưng deposit phải luôn bằng 0
        # để không phát sinh giao dịch cọc ca trực và không tự áp cọc lúc check-in.
        raw["ota_auto_no_deposit"] = True
        raw["deposit_amount"] = 0
        booking.raw_data = raw
        booking.booking_type = "OTA"
        booking.deposit_amount = Decimal("0")
        booking.reservation_status = "PENDING"
        booking.status = BookingStatus.CONFIRMED
        booking.confirmed_at = None
        return self.normalize_existing_booking(
            booking,
            user_id=user_id,
            reserve_inventory=False,
        )

    def update_reservation(self, booking_id: int, payload: Dict[str, Any], user_id: Optional[int]) -> Booking:
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError("Không tìm thấy đặt phòng")
        if booking.reservation_status in TERMINAL_STATUSES:
            raise ValueError("Không thể sửa đặt phòng đã kết thúc")

        editing_core = any(payload.get(key) is not None for key in ("room_type_id", "check_in", "check_out", "reservation_status"))
        if booking.reservation_status == "CHECKED_IN" and editing_core:
            raise ValueError("Đặt phòng đã nhận phòng chỉ cho phép sửa thông tin khách và ghi chú")

        old_snapshot = self._reserved_snapshot(booking)
        old_status = booking.reservation_status
        raw = dict(booking.raw_data or {})
        raw.update(payload.get("raw_data") or {})

        room_type_id = payload.get("room_type_id") or raw.get("room_type_id") or self._resolve_room_type_id(booking.branch_id, booking.room_type)
        room_type = None
        if room_type_id:
            room_type = self.db.query(HotelRoomType).filter(HotelRoomType.id == int(room_type_id)).first()
            if not room_type:
                raise ValueError("Không tìm thấy loại phòng")

        new_check_in = date.fromisoformat(str(payload["check_in"])[:10]) if payload.get("check_in") else booking.check_in
        new_check_out = date.fromisoformat(str(payload["check_out"])[:10]) if payload.get("check_out") else booking.check_out
        if new_check_out <= new_check_in:
            raise ValueError("Ngày trả phòng phải sau ngày nhận phòng")

        new_status = str(payload.get("reservation_status") or booking.reservation_status or "PENDING").upper()
        if new_status not in {"PENDING", "CONFIRMED", "CHECKED_IN"}:
            new_status = booking.reservation_status or "PENDING"

        if old_status == "CONFIRMED":
            self._release_reserved_snapshot(booking, old_snapshot, user_id, "MODIFY")

        if payload.get("guest_name") is not None:
            booking.guest_name = str(payload["guest_name"]).strip()
        if payload.get("guest_phone") is not None:
            booking.guest_phone = str(payload["guest_phone"] or "").strip() or None
        for raw_key in ("guest_email", "guest_cccd", "gender", "date_of_birth", "nationality", "id_expire", "address"):
            if payload.get(raw_key) is not None:
                raw[raw_key] = payload[raw_key]
        if payload.get("booking_type") is not None:
            booking.booking_type = str(payload["booking_type"] or booking.booking_type or "DIRECT").upper()
            booking.booking_source = payload.get("booking_source") or self._booking_type_source(booking.booking_type)
        elif payload.get("booking_source") is not None:
            booking.booking_source = payload.get("booking_source") or booking.booking_source
        if payload.get("external_id") is not None:
            booking.external_id = str(payload["external_id"] or booking.external_id).strip() or booking.external_id
        if room_type:
            raw["room_type_id"] = int(room_type.id)
            booking.room_type = room_type.name
            if booking.assigned_room and booking.assigned_room.room_type_id != room_type.id:
                booking.assigned_room_id = None
        booking.check_in = new_check_in
        booking.check_out = new_check_out
        booking.reservation_status = new_status
        booking.status = reservation_to_legacy_status(new_status)
        for field in ("num_guests", "num_adults", "num_children"):
            if payload.get(field) is not None:
                setattr(booking, field, int(payload[field]))
        if payload.get("total_price") is not None:
            booking.total_price = Decimal(str(payload["total_price"] or 0))
        if payload.get("deposit_amount") is not None:
            booking.deposit_amount = Decimal(str(payload["deposit_amount"] or 0))
        if payload.get("payment_method") is not None:
            booking.payment_method = payload["payment_method"]
        if payload.get("special_requests") is not None:
            booking.special_requests = payload["special_requests"]
        if payload.get("internal_notes") is not None:
            booking.internal_notes = payload["internal_notes"]
        if payload.get("estimated_arrival") is not None:
            booking.estimated_arrival = time.fromisoformat(str(payload["estimated_arrival"])) if payload.get("estimated_arrival") else None

        if booking.assigned_room_id:
            reason = self._room_conflict_reason(booking, booking.assigned_room_id)
            if reason:
                booking.assigned_room_id = None

        booking.raw_data = raw
        if new_status == "CONFIRMED":
            if not room_type_id:
                raise ValueError("Không xác định được loại phòng để giữ tồn")
            self.inventory.reserve_booking(booking.id, booking.branch_id, int(room_type_id), new_check_in, new_check_out, 1, user_id)
            self._mark_reserved(booking, int(room_type_id))
            if not booking.confirmed_at:
                booking.confirmed_at = self._now()
        else:
            self._mark_unreserved(booking)

        booking.guest_id = None
        raw.pop("selected_crm_guest_id", None)
        booking.raw_data = raw

        booking.updated_by = user_id
        booking.updated_at = self._now()
        self._log_booking_activity(booking, "BOOKING_MODIFIED", "Cập nhật đặt phòng", user_id)
        self._post_booking_deposit_once(booking, user_id)
        self.db.flush()
        return booking

    def confirm_reservation(self, booking_id: int, user_id: Optional[int], room_type_id: Optional[int] = None) -> Booking:
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError("Không tìm thấy đặt phòng")
        if booking.reservation_status == "CONFIRMED":
            return booking
        if booking.reservation_status in TERMINAL_STATUSES:
            raise ValueError("Không thể xác nhận đặt phòng đã kết thúc")
        if booking.assigned_room_id:
            raise ValueError("Chỉ có thể đổi trạng thái khi đặt phòng chưa gán phòng")

        selected_room_type = None
        if room_type_id:
            selected_room_type = self.db.query(HotelRoomType).filter(
                HotelRoomType.id == int(room_type_id),
                HotelRoomType.branch_id == booking.branch_id,
                HotelRoomType.is_active == True,
            ).first()
            if not selected_room_type:
                raise ValueError("Loại phòng không thuộc chi nhánh của đặt phòng")
            room_type_id = selected_room_type.id
        else:
            room_type_id = (booking.raw_data or {}).get("room_type_id")
            if not room_type_id:
                selected_room_type = self.db.query(HotelRoomType).filter(
                    HotelRoomType.branch_id == booking.branch_id,
                    func.lower(HotelRoomType.name) == (booking.room_type or "").lower(),
                ).first()
                room_type_id = selected_room_type.id if selected_room_type else None
        if not room_type_id:
            raise ValueError("Không xác định được loại phòng để giữ tồn")

        try:
            self.inventory.reserve_booking(booking.id, booking.branch_id, int(room_type_id), booking.check_in, booking.check_out, 1, user_id)
        except ValueError as exc:
            raise ValueError(f"Không thể xác nhận vì tồn phòng không đủ: {exc}") from exc
        if selected_room_type:
            raw = dict(booking.raw_data or {})
            raw["room_type_id"] = int(selected_room_type.id)
            booking.raw_data = raw
            booking.room_type = selected_room_type.name
        self._mark_reserved(booking, int(room_type_id))
        booking.reservation_status = "CONFIRMED"
        booking.status = BookingStatus.CONFIRMED
        booking.confirmed_at = self._now()
        booking.updated_by = user_id
        booking.updated_at = self._now()
        self._log_booking_activity(booking, "BOOKING_MODIFIED", "Xác nhận đặt phòng", user_id)
        self.db.flush()
        return booking

    def set_reservation_confirmation_status(self, booking_id: int, status: str, user_id: Optional[int]) -> Booking:
        target_status = (status or "").upper()
        if target_status not in {"PENDING", "CONFIRMED"}:
            raise ValueError("Trạng thái không hợp lệ")
        if target_status == "CONFIRMED":
            return self.confirm_reservation(booking_id, user_id)

        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError("Không tìm thấy đặt phòng")
        if booking.reservation_status == "PENDING":
            return booking
        if booking.reservation_status in TERMINAL_STATUSES or booking.reservation_status == "CHECKED_IN":
            raise ValueError("Không thể đổi trạng thái đặt phòng này")
        if booking.assigned_room_id:
            raise ValueError("Chỉ có thể đổi trạng thái khi đặt phòng chưa gán phòng")

        if booking.reservation_status == "CONFIRMED":
            self._release_reserved_snapshot(booking, self._reserved_snapshot(booking), user_id, "MODIFY")
        booking.reservation_status = "PENDING"
        booking.status = reservation_to_legacy_status("PENDING")
        booking.confirmed_at = None
        self._mark_unreserved(booking)
        booking.updated_by = user_id
        booking.updated_at = self._now()
        self._log_booking_activity(booking, "BOOKING_MODIFIED", "Chuyển về chờ xác nhận", user_id)
        self.db.flush()
        return booking

    def transfer_branch(self, booking_id: int, target_branch_id: int, target_room_type_id: int, reason: str = "", user_id: Optional[int] = None) -> Booking:
        booking = self.db.query(Booking).options(joinedload(Booking.branch)).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError("Không tìm thấy đặt phòng")
        if booking.reservation_status in TERMINAL_STATUSES or booking.reservation_status == "CHECKED_IN" or booking.stay_id:
            raise ValueError("Không thể chuyển chi nhánh cho đặt phòng đã kết thúc hoặc đã nhận phòng")
        if booking.assigned_room_id:
            raise ValueError("Cần gỡ gán phòng trước khi chuyển chi nhánh")
        if int(target_branch_id) == int(booking.branch_id or 0):
            raise ValueError("Chi nhánh đích phải khác chi nhánh hiện tại")

        target_branch = self.db.query(Branch).filter(Branch.id == int(target_branch_id)).first()
        if not target_branch:
            raise ValueError("Không tìm thấy chi nhánh đích")
        target_room_type = self.db.query(HotelRoomType).filter(
            HotelRoomType.id == int(target_room_type_id),
            HotelRoomType.branch_id == int(target_branch_id),
            HotelRoomType.is_active == True,
        ).first()
        if not target_room_type:
            raise ValueError("Loại phòng không thuộc chi nhánh đích")

        old_snapshot = self._reserved_snapshot(booking)
        old_branch_id = booking.branch_id
        old_branch_name = booking.branch.name if booking.branch else ""
        old_status = booking.reservation_status
        old_raw = dict(booking.raw_data or {})
        if old_status == "CONFIRMED":
            self._release_reserved_snapshot(booking, old_snapshot, user_id, "TRANSFER")

        shadow_raw = dict(old_raw)
        shadow_raw.update({
            "transfer_shadow": True,
            "transferred_to_branch_id": int(target_branch_id),
            "transferred_to_branch_name": target_branch.name,
            "transfer_reason": reason or "Chuyển nhầm chi nhánh",
            "original_booking_id": booking.id,
        })
        shadow_external_id = f"{(booking.external_id or booking.id)}-OLD-{old_branch_id}-{int(self._now().timestamp())}"
        shadow = Booking(
            booking_source=booking.booking_source,
            external_id=shadow_external_id[:50],
            guest_name=booking.guest_name,
            guest_phone=booking.guest_phone,
            check_in=booking.check_in,
            check_out=booking.check_out,
            room_type=booking.room_type,
            num_guests=booking.num_guests,
            num_adults=booking.num_adults,
            num_children=booking.num_children,
            total_price=booking.total_price,
            currency=booking.currency,
            is_prepaid=booking.is_prepaid,
            payment_method=booking.payment_method,
            deposit_amount=booking.deposit_amount,
            status=BookingStatus.CANCELLED,
            branch_id=old_branch_id,
            source_booking_id=booking.id,
            guest_id=booking.guest_id,
            raw_data=shadow_raw,
            created_by=user_id,
            updated_by=user_id,
            booking_type=booking.booking_type,
            reservation_status="CANCELLED",
            estimated_arrival=booking.estimated_arrival,
            special_requests=booking.special_requests,
            internal_notes=booking.internal_notes,
            cancel_reason=f"Đã chuyển sang {target_branch.name}" + (f": {reason}" if reason else ""),
            cancelled_at=self._now(),
        )
        self.db.add(shadow)

        raw = dict(booking.raw_data or {})
        history = list(raw.get("branch_transfer_history") or [])
        history.append({
            "from_branch_id": old_branch_id,
            "from_branch_name": old_branch_name,
            "to_branch_id": int(target_branch_id),
            "to_branch_name": target_branch.name,
            "reason": reason or "",
            "transferred_at": self._now().isoformat(),
        })
        raw["branch_transfer_history"] = history
        raw["room_type_id"] = int(target_room_type.id)
        raw.pop("reservation_reserved_room_type_id", None)
        raw.pop("reservation_reserved_check_in", None)
        raw.pop("reservation_reserved_check_out", None)
        raw.pop("reservation_reserved_qty", None)
        raw["reservation_inventory_reserved"] = False

        booking.branch_id = int(target_branch_id)
        booking.room_type = target_room_type.name
        booking.assigned_room_id = None
        booking.raw_data = raw
        if old_status == "CONFIRMED":
            if self._has_available_inventory(booking.branch_id, target_room_type.id, booking.check_in, booking.check_out, 1):
                self.inventory.reserve_booking(booking.id, booking.branch_id, target_room_type.id, booking.check_in, booking.check_out, 1, user_id)
                self._mark_reserved(booking, target_room_type.id)
                booking.reservation_status = "CONFIRMED"
                booking.status = BookingStatus.CONFIRMED
                booking.confirmed_at = booking.confirmed_at or self._now()
            else:
                booking.raw_data = self._mark_over_capacity_pending(raw, booking.branch_id, target_room_type.id, booking.check_in, booking.check_out, 1)
                booking.reservation_status = "PENDING"
                booking.status = reservation_to_legacy_status("PENDING")
                booking.confirmed_at = None
        else:
            booking.reservation_status = "PENDING"
            booking.status = reservation_to_legacy_status("PENDING")
            booking.confirmed_at = None
        booking.updated_by = user_id
        booking.updated_at = self._now()
        self._log_booking_activity(booking, "BOOKING_MODIFIED", "Chuyển chi nhánh đặt phòng", user_id, reason)
        self.db.flush()
        return booking

    def cancel_reservation(self, booking_id: int, reason: str, user_id: Optional[int], no_show: bool = False) -> Booking:
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError("Không tìm thấy đặt phòng")
        if booking.reservation_status in {"CANCELLED", "CHECKED_OUT", "NO_SHOW"}:
            return booking

        if booking.reservation_status == "CONFIRMED":
            self._release_reserved_snapshot(
                booking,
                self._reserved_snapshot(booking),
                user_id,
                "NO_SHOW" if no_show else "CANCEL",
            )

        booking.reservation_status = "NO_SHOW" if no_show else "CANCELLED"
        booking.status = BookingStatus.NO_SHOW if no_show else BookingStatus.CANCELLED
        booking.no_show_at = self._now() if no_show else None
        booking.cancelled_at = self._now() if not no_show else booking.cancelled_at
        booking.cancel_reason = reason
        booking.updated_by = user_id
        booking.updated_at = self._now()
        self._log_booking_activity(
            booking,
            "BOOKING_CANCELLED",
            "No-show đặt phòng" if no_show else "Hủy đặt phòng",
            user_id,
            reason,
        )
        self.db.flush()
        return booking

    def restore_reservation(self, booking_id: int, user_id: Optional[int]) -> Booking:
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError("Không tìm thấy đặt phòng")
        if booking.reservation_status not in {"CANCELLED", "NO_SHOW"}:
            return booking

        booking.reservation_status = "PENDING"
        booking.status = BookingStatus.CONFIRMED
        booking.no_show_at = None
        booking.cancel_reason = None
        booking.updated_by = user_id
        booking.updated_at = self._now()
        self._log_booking_activity(booking, "BOOKING_MODIFIED", "Khôi phục đặt phòng", user_id)
        self.db.flush()
        return booking

    def assign_room(self, booking_id: int, room_id: int, user_id: Optional[int]) -> Booking:
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        room = self.db.query(HotelRoom).filter(HotelRoom.id == room_id, HotelRoom.is_active == True).first()
        if not booking or not room:
            raise ValueError("Không tìm thấy đặt phòng hoặc phòng")
        if booking.branch_id and room.branch_id != booking.branch_id:
            raise ValueError("Phòng không thuộc chi nhánh của đặt phòng")
        room_type_id = (booking.raw_data or {}).get("room_type_id")
        if room_type_id and room.room_type_id != int(room_type_id):
            raise ValueError("Phòng không đúng loại phòng đã đặt")
        reason = self._room_conflict_reason(booking, room.id)
        if reason:
            raise ValueError(reason)
        booking.assigned_room_id = room.id
        booking.updated_by = user_id
        booking.updated_at = self._now()
        self._log_booking_activity(booking, "BOOKING_MODIFIED", "Gán phòng đặt trước", user_id, f"Phòng {room.room_number}")
        self.db.flush()
        return booking

    def unassign_room(self, booking_id: int, user_id: Optional[int]) -> Booking:
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError("Không tìm thấy đặt phòng")
        if booking.reservation_status not in {"PENDING", "CONFIRMED"}:
            raise ValueError("Chỉ có thể gỡ gán phòng với đặt phòng chưa nhận phòng")
        if not booking.assigned_room_id:
            return booking
        old_room = booking.assigned_room.room_number if booking.assigned_room else None
        booking.assigned_room_id = None
        booking.updated_by = user_id
        booking.updated_at = self._now()
        self._log_booking_activity(
            booking,
            "BOOKING_MODIFIED",
            "Gỡ gán phòng đặt trước",
            user_id,
            f"Phòng {old_room}" if old_room else None,
        )
        self.db.flush()
        return booking

    def stats(self, branch_id: Optional[int] = None) -> Dict[str, Any]:
        today = datetime.now(VN_TZ).date()
        q = self.db.query(Booking)
        if branch_id:
            q = q.filter(Booking.branch_id == branch_id)

        row = q.with_entities(
            func.count(Booking.id).label("total"),
            func.count(Booking.id).filter(
                Booking.check_in == today,
                Booking.reservation_status.in_(["PENDING", "CONFIRMED"]),
            ).label("today_arrivals"),
            func.count(Booking.id).filter(
                Booking.check_out == today,
                Booking.reservation_status.in_(["CONFIRMED", "CHECKED_IN"]),
            ).label("today_departures"),
            func.count(Booking.id).filter(Booking.reservation_status == "CONFIRMED").label("confirmed"),
            func.count(Booking.id).filter(Booking.reservation_status == "PENDING").label("pending"),
            func.count(Booking.id).filter(Booking.reservation_status == "NO_SHOW").label("no_show"),
            func.count(Booking.id).filter(Booking.reservation_status == "CANCELLED").label("cancelled"),
            func.count(Booking.id).filter(
                Booking.check_in >= today,
                Booking.check_in <= today + timedelta(days=7),
                Booking.reservation_status.in_(["PENDING", "CONFIRMED"]),
            ).label("upcoming_7d"),
        ).one()
        return {
            "total": row.total or 0,
            "today_arrivals": row.today_arrivals or 0,
            "today_departures": row.today_departures or 0,
            "confirmed": row.confirmed or 0,
            "pending": row.pending or 0,
            "no_show": row.no_show or 0,
            "cancelled": row.cancelled or 0,
            "upcoming_7d": row.upcoming_7d or 0,
        }
