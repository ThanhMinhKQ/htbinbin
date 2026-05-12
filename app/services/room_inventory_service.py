# type: ignore
"""Room inventory management for PMS reservations."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, cast

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..core.utils import VN_TZ
from ..db.models import (
    Booking,
    HotelGuest,
    HotelRoom,
    HotelRoomType,
    HotelStay,
    HotelStayStatus,
    RoomBlock,
    RoomCondition,
    RoomInventoryHold,
    RoomInventoryDaily,
    RoomInventoryLog,
)


def iter_stay_dates(check_in: date, check_out: date):
    """Yield room nights from check-in date up to, but not including, check-out."""
    current = check_in
    while current < check_out:
        yield current
        current += timedelta(days=1)


class InventoryService:
    def __init__(self, db: Session):
        self.db = db

    def _booking_room_type_id(self, booking: Booking) -> Optional[int]:
        raw = booking.raw_data or {}
        room_type_id = raw.get("reservation_reserved_room_type_id") or raw.get("room_type_id")
        if room_type_id:
            return int(room_type_id)
        room_type = self.db.query(HotelRoomType.id).filter(
            HotelRoomType.branch_id == booking.branch_id,
            func.lower(HotelRoomType.name) == (booking.room_type or "").lower(),
            HotelRoomType.is_active == True,
        ).first()
        return int(room_type[0]) if room_type else None

    def _reserved_booking_quantity(self, booking: Booking) -> int:
        raw = booking.raw_data or {}
        if raw.get("reservation_reserved_qty"):
            return int(raw["reservation_reserved_qty"])
        # Group bookings (split from multi-room OTA) always represent 1 room each
        if raw.get("group_code") or raw.get("group_index"):
            return 1
        return int(raw.get("num_rooms") or 1)

    def _recalculate_available(self, inv: RoomInventoryDaily) -> None:
        total_rooms = cast(int, inv.total_rooms or 0)
        reserved_rooms = cast(int, inv.reserved_rooms or 0)
        sold_rooms = cast(int, inv.sold_rooms or 0)
        out_of_order_rooms = cast(int, inv.out_of_order_rooms or 0)
        overbooking_limit = cast(int, inv.overbooking_limit or 0)
        inv.available_rooms = cast(Any, total_rooms - reserved_rooms - sold_rooms - out_of_order_rooms + overbooking_limit)

    def _physical_counts(self, branch_id: int, room_type_id: int, target_date: date) -> Dict[str, int]:
        total_rooms = self.db.query(func.count(HotelRoom.id)).filter(
            HotelRoom.branch_id == branch_id,
            HotelRoom.room_type_id == room_type_id,
            HotelRoom.is_active == True,
        ).scalar() or 0

        day_start = datetime.combine(target_date, time.min)
        day_end = datetime.combine(target_date + timedelta(days=1), time.min)
        if day_start.tzinfo is None:
            day_start = VN_TZ.localize(day_start)
            day_end = VN_TZ.localize(day_end)

        sold_rooms = self.db.query(func.count(func.distinct(HotelStay.room_id))).join(
            HotelRoom, HotelRoom.id == HotelStay.room_id
        ).filter(
            HotelStay.branch_id == branch_id,
            HotelStay.status == HotelStayStatus.ACTIVE,
            HotelRoom.room_type_id == room_type_id,
            HotelStay.check_in_at < day_end,
            or_(HotelStay.check_out_at.is_(None), HotelStay.check_out_at > day_start),
        ).scalar() or 0

        out_of_order_rooms = self.db.query(func.count(RoomBlock.id)).join(
            HotelRoom, HotelRoom.id == RoomBlock.room_id
        ).filter(
            RoomBlock.branch_id == branch_id,
            HotelRoom.room_type_id == room_type_id,
            RoomBlock.status == "ACTIVE",
            RoomBlock.start_date <= target_date,
            RoomBlock.end_date > target_date,
        ).scalar() or 0

        return {
            "total_rooms": int(total_rooms),
            "sold_rooms": int(sold_rooms),
            "out_of_order_rooms": int(out_of_order_rooms),
        }

    def _physical_counts_batch(
        self, branch_id: int, room_type_ids: List[int], target_date: date
    ) -> Dict[int, Dict[str, int]]:
        """Batch version: tính total/sold/ooo cho TẤT CẢ room_types trong 3 query thay vì 3×N."""
        day_start = datetime.combine(target_date, time.min)
        day_end = datetime.combine(target_date + timedelta(days=1), time.min)
        if day_start.tzinfo is None:
            day_start = VN_TZ.localize(day_start)
            day_end = VN_TZ.localize(day_end)

        # Q1: total rooms per type
        total_rows = self.db.query(
            HotelRoom.room_type_id, func.count(HotelRoom.id)
        ).filter(
            HotelRoom.branch_id == branch_id,
            HotelRoom.room_type_id.in_(room_type_ids),
            HotelRoom.is_active == True,
        ).group_by(HotelRoom.room_type_id).all()
        total_map = {int(r[0]): int(r[1]) for r in total_rows}

        # Q2: sold rooms per type (active stays overlapping target_date)
        sold_rows = self.db.query(
            HotelRoom.room_type_id, func.count(func.distinct(HotelStay.room_id))
        ).join(
            HotelRoom, HotelRoom.id == HotelStay.room_id
        ).filter(
            HotelStay.branch_id == branch_id,
            HotelStay.status == HotelStayStatus.ACTIVE,
            HotelRoom.room_type_id.in_(room_type_ids),
            HotelStay.check_in_at < day_end,
            or_(HotelStay.check_out_at.is_(None), HotelStay.check_out_at > day_start),
        ).group_by(HotelRoom.room_type_id).all()
        sold_map = {int(r[0]): int(r[1]) for r in sold_rows}

        # Q3: out-of-order rooms per type
        ooo_rows = self.db.query(
            HotelRoom.room_type_id, func.count(RoomBlock.id)
        ).join(
            HotelRoom, HotelRoom.id == RoomBlock.room_id
        ).filter(
            RoomBlock.branch_id == branch_id,
            HotelRoom.room_type_id.in_(room_type_ids),
            RoomBlock.status == "ACTIVE",
            RoomBlock.start_date <= target_date,
            RoomBlock.end_date > target_date,
        ).group_by(HotelRoom.room_type_id).all()
        ooo_map = {int(r[0]): int(r[1]) for r in ooo_rows}

        return {
            rt_id: {
                "total_rooms": total_map.get(rt_id, 0),
                "sold_rooms": sold_map.get(rt_id, 0),
                "out_of_order_rooms": ooo_map.get(rt_id, 0),
            }
            for rt_id in room_type_ids
        }

    def get_or_create_inventory(
        self,
        branch_id: int,
        room_type_id: int,
        target_date: date,
        refresh_counts: bool = False,
    ) -> RoomInventoryDaily:
        inv = self.db.query(RoomInventoryDaily).filter(
            RoomInventoryDaily.branch_id == branch_id,
            RoomInventoryDaily.room_type_id == room_type_id,
            RoomInventoryDaily.date == target_date,
        ).first()
        if inv:
            if refresh_counts:
                counts = self._physical_counts(branch_id, room_type_id, target_date)
                inv.total_rooms = counts["total_rooms"]
                inv.sold_rooms = counts["sold_rooms"]
                inv.out_of_order_rooms = counts["out_of_order_rooms"]
            self._recalculate_available(inv)
            return inv

        room_type = self.db.query(HotelRoomType).filter(HotelRoomType.id == room_type_id).first()
        counts = self._physical_counts(branch_id, room_type_id, target_date)
        inv = RoomInventoryDaily(
            branch_id=branch_id,
            room_type_id=room_type_id,
            date=target_date,
            total_rooms=counts["total_rooms"],
            reserved_rooms=0,
            sold_rooms=counts["sold_rooms"],
            out_of_order_rooms=counts["out_of_order_rooms"],
            base_price=room_type.price_per_night if room_type else Decimal("0"),
        )
        self._recalculate_available(inv)
        self.db.add(inv)
        self.db.flush()
        return inv

    def log_change(
        self,
        inv: RoomInventoryDaily,
        change_type: str,
        delta: int,
        field_changed: str,
        ref_type: str,
        ref_id: Optional[int],
        user_id: Optional[int] = None,
        note: Optional[str] = None,
    ) -> None:
        self.db.add(RoomInventoryLog(
            branch_id=inv.branch_id,
            room_type_id=inv.room_type_id,
            date=inv.date,
            change_type=change_type,
            delta=delta,
            field_changed=field_changed,
            ref_type=ref_type,
            ref_id=ref_id,
            note=note,
            created_by=user_id,
        ))

    def generate_daily_inventory(
        self,
        branch_id: int,
        start_date: date,
        days: int = 365,
        refresh_counts: bool = True,
    ) -> Dict[str, int]:
        room_types = self.db.query(HotelRoomType).filter(
            HotelRoomType.branch_id == branch_id,
            HotelRoomType.is_active == True,
        ).all()
        if not room_types or days <= 0:
            return {"days": days, "records": 0}

        room_type_by_id = {int(room_type.id): room_type for room_type in room_types}
        room_type_ids = list(room_type_by_id)
        target_dates = [start_date + timedelta(days=offset) for offset in range(days)]
        end_date = start_date + timedelta(days=days)

        existing = self.db.query(RoomInventoryDaily).filter(
            RoomInventoryDaily.branch_id == branch_id,
            RoomInventoryDaily.room_type_id.in_(room_type_ids),
            RoomInventoryDaily.date >= start_date,
            RoomInventoryDaily.date < end_date,
        ).all()
        inventory_by_key = {(int(inv.room_type_id), inv.date): inv for inv in existing}

        total_by_type: Dict[int, int] = defaultdict(int)
        sold_by_key: Dict[tuple[int, date], set[int]] = defaultdict(set)
        blocked_by_key: Dict[tuple[int, date], set[int]] = defaultdict(set)
        reserved_by_key: Dict[tuple[int, date], int] = defaultdict(int)

        room_rows = self.db.query(
            HotelRoom.id,
            HotelRoom.room_type_id,
            HotelRoom.condition,
        ).filter(
            HotelRoom.branch_id == branch_id,
            HotelRoom.room_type_id.in_(room_type_ids),
            HotelRoom.is_active == True,
        ).all()
        room_type_for_room = {int(room_id): int(room_type_id) for room_id, room_type_id, _condition in room_rows if room_type_id}
        for _room_id, room_type_id, _condition in room_rows:
            if room_type_id:
                total_by_type[int(room_type_id)] += 1

        day_start = datetime.combine(start_date, time.min)
        day_end = datetime.combine(end_date, time.min)
        if day_start.tzinfo is None:
            day_start = VN_TZ.localize(day_start)
            day_end = VN_TZ.localize(day_end)

        stays = self.db.query(
            HotelStay.room_id,
            HotelStay.check_in_at,
            HotelStay.check_out_at,
        ).filter(
            HotelStay.branch_id == branch_id,
            HotelStay.status == HotelStayStatus.ACTIVE,
            HotelStay.check_in_at < day_end,
            or_(HotelStay.check_out_at.is_(None), HotelStay.check_out_at > day_start),
        ).all()
        occupied_room_dates: set[tuple[int, date]] = set()
        if refresh_counts:
            for room_id, check_in_at, check_out_at in stays:
                room_type_id = room_type_for_room.get(int(room_id))
                if not room_type_id:
                    continue
                first_date = max(start_date, check_in_at.astimezone(VN_TZ).date())
                co_date = check_out_at.astimezone(VN_TZ).date() if check_out_at else end_date
                # ensure same-day stays (check-in and check-out on same date) count as 1 sold night
                if co_date <= first_date:
                    co_date = first_date + timedelta(days=1)
                last_date = min(end_date, co_date)
                for target_date in iter_stay_dates(first_date, last_date):
                    sold_by_key[(room_type_id, target_date)].add(int(room_id))
                    occupied_room_dates.add((int(room_id), target_date))

        bookings = self.db.query(Booking).filter(
            Booking.branch_id == branch_id,
            Booking.reservation_status == "CONFIRMED",
            Booking.stay_id.is_(None),
            Booking.check_in < end_date,
            Booking.check_out > start_date,
        ).all()
        for booking in bookings:
            room_type_id = self._booking_room_type_id(booking)
            if not room_type_id:
                continue
            first_date = max(start_date, booking.check_in)
            last_date = min(end_date, booking.check_out)
            quantity = self._reserved_booking_quantity(booking)
            for target_date in iter_stay_dates(first_date, last_date):
                if booking.assigned_room_id and (int(booking.assigned_room_id), target_date) in occupied_room_dates:
                    continue
                reserved_by_key[(room_type_id, target_date)] += quantity

        if refresh_counts:
            blocks = self.db.query(
                RoomBlock.room_id,
                RoomBlock.start_date,
                RoomBlock.end_date,
            ).filter(
                RoomBlock.branch_id == branch_id,
                RoomBlock.status == "ACTIVE",
                RoomBlock.start_date < end_date,
                RoomBlock.end_date > start_date,
            ).all()
            for room_id, block_start, block_end in blocks:
                room_type_id = room_type_for_room.get(int(room_id))
                if not room_type_id:
                    continue
                first_date = max(start_date, block_start)
                last_date = min(end_date, block_end)
                for target_date in iter_stay_dates(first_date, last_date):
                    blocked_by_key[(room_type_id, target_date)].add(int(room_id))

        created_or_touched = 0
        for target_date in target_dates:
            for room_type_id, room_type in room_type_by_id.items():
                inv = inventory_by_key.get((room_type_id, target_date))
                if not inv:
                    inv = RoomInventoryDaily(
                        branch_id=branch_id,
                        room_type_id=room_type_id,
                        date=target_date,
                        reserved_rooms=0,
                        base_price=room_type.price_per_night or Decimal("0"),
                    )
                    self.db.add(inv)
                    inventory_by_key[(room_type_id, target_date)] = inv
                inv.total_rooms = total_by_type.get(room_type_id, 0)
                inv.reserved_rooms = reserved_by_key.get((room_type_id, target_date), 0)
                if refresh_counts:
                    inv.sold_rooms = len(sold_by_key.get((room_type_id, target_date), set()))
                    inv.out_of_order_rooms = len(blocked_by_key.get((room_type_id, target_date), set()))
                if not inv.base_price:
                    inv.base_price = room_type.price_per_night or Decimal("0")
                self._recalculate_available(inv)
                created_or_touched += 1
        self.db.flush()
        return {"days": days, "records": created_or_touched}

    def reserve_booking(
        self,
        booking_id: int,
        branch_id: int,
        room_type_id: int,
        check_in: date,
        check_out: date,
        quantity: int = 1,
        user_id: Optional[int] = None,
    ) -> None:
        for target_date in iter_stay_dates(check_in, check_out):
            inv = self.get_or_create_inventory(branch_id, room_type_id, target_date)
            if inv.available_rooms < quantity:
                raise ValueError(f"Không đủ phòng ngày {target_date.strftime('%d/%m/%Y')}")
            inv.reserved_rooms += quantity
            self._recalculate_available(inv)
            self.log_change(inv, "BOOKING_CONFIRM", quantity, "reserved_rooms", "booking", booking_id, user_id)
        self.db.flush()

    def release_booking(
        self,
        booking_id: int,
        branch_id: int,
        room_type_id: int,
        check_in: date,
        check_out: date,
        quantity: int = 1,
        user_id: Optional[int] = None,
        change_type: str = "CANCEL",
    ) -> None:
        for target_date in iter_stay_dates(check_in, check_out):
            inv = self.get_or_create_inventory(branch_id, room_type_id, target_date)
            delta = min(quantity, inv.reserved_rooms or 0)
            inv.reserved_rooms = max(0, (inv.reserved_rooms or 0) - quantity)
            self._recalculate_available(inv)
            if delta:
                self.log_change(inv, change_type, -delta, "reserved_rooms", "booking", booking_id, user_id)
        self.db.flush()

    def move_reserved_to_sold(
        self,
        booking_id: int,
        stay_id: int,
        branch_id: int,
        room_type_id: int,
        check_in: date,
        check_out: date,
        user_id: Optional[int] = None,
    ) -> None:
        for target_date in iter_stay_dates(check_in, check_out):
            inv = self.get_or_create_inventory(branch_id, room_type_id, target_date)
            if inv.reserved_rooms > 0:
                inv.reserved_rooms -= 1
                self.log_change(inv, "CHECKIN", -1, "reserved_rooms", "booking", booking_id, user_id)
            inv.sold_rooms += 1
            self.log_change(inv, "CHECKIN", 1, "sold_rooms", "stay", stay_id, user_id)
            self._recalculate_available(inv)
        self.db.flush()

    def add_sold(
        self,
        stay_id: int,
        branch_id: int,
        room_type_id: int,
        check_in: date,
        check_out: date,
        quantity: int = 1,
        user_id: Optional[int] = None,
        change_type: str = "WALKIN_CHECKIN",
    ) -> None:
        for target_date in iter_stay_dates(check_in, check_out):
            inv = self.get_or_create_inventory(branch_id, room_type_id, target_date)
            inv.sold_rooms += quantity
            self._recalculate_available(inv)
            self.log_change(inv, change_type, quantity, "sold_rooms", "stay", stay_id, user_id)
        self.db.flush()

    def release_sold(
        self,
        stay_id: int,
        branch_id: int,
        room_type_id: int,
        check_in: date,
        check_out: date,
        quantity: int = 1,
        user_id: Optional[int] = None,
        change_type: str = "CHECKOUT",
    ) -> None:
        for target_date in iter_stay_dates(check_in, check_out):
            inv = self.get_or_create_inventory(branch_id, room_type_id, target_date)
            delta = min(quantity, inv.sold_rooms or 0)
            inv.sold_rooms = max(0, (inv.sold_rooms or 0) - quantity)
            self._recalculate_available(inv)
            if delta:
                self.log_change(inv, change_type, -delta, "sold_rooms", "stay", stay_id, user_id)
        self.db.flush()

    def list_blockable_rooms(self, branch_id: int) -> List[Dict[str, Any]]:
        rooms = self.db.query(HotelRoom).filter(
            HotelRoom.branch_id == branch_id,
            HotelRoom.is_active == True,
            HotelRoom.room_type_id.isnot(None),
        ).order_by(HotelRoom.floor, HotelRoom.sort_order, HotelRoom.room_number).all()
        return [
            {
                "id": room.id,
                "room_number": room.room_number,
                "floor": room.floor,
                "room_type_id": room.room_type_id,
                "room_type_name": room.room_type_obj.name if room.room_type_obj else None,
                "status": getattr(room.condition, "value", room.condition),
            }
            for room in rooms
        ]

    def list_blocks(
        self,
        branch_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        q = self.db.query(RoomBlock).join(HotelRoom, HotelRoom.id == RoomBlock.room_id).filter(
            RoomBlock.branch_id == branch_id,
        )
        if start_date:
            q = q.filter(RoomBlock.end_date > start_date)
        if end_date:
            q = q.filter(RoomBlock.start_date < end_date)
        if status:
            q = q.filter(RoomBlock.status == status)
        blocks = q.order_by(RoomBlock.start_date.desc(), HotelRoom.room_number.asc()).all()
        return [self.serialize_block(block) for block in blocks]

    def serialize_block(self, block: RoomBlock) -> Dict[str, Any]:
        room = block.room
        return {
            "id": block.id,
            "room_id": block.room_id,
            "room_number": room.room_number if room else None,
            "room_type_id": room.room_type_id if room else None,
            "room_type_name": room.room_type_obj.name if room and room.room_type_obj else None,
            "start_date": block.start_date.isoformat(),
            "end_date": block.end_date.isoformat(),
            "reason": block.reason or "",
            "status": block.status,
            "created_at": block.created_at.isoformat() if block.created_at else None,
        }

    def create_block(
        self,
        room_id: int,
        start_date: date,
        end_date: date,
        reason: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> RoomBlock:
        if end_date <= start_date:
            raise ValueError("Ngày kết thúc khóa phòng phải sau ngày bắt đầu")
        room = self.db.query(HotelRoom).filter(HotelRoom.id == room_id, HotelRoom.is_active == True).first()
        if not room:
            raise ValueError("Không tìm thấy phòng cần khóa")

        overlap = self.db.query(RoomBlock).filter(
            RoomBlock.room_id == room_id,
            RoomBlock.status == "ACTIVE",
            RoomBlock.start_date < end_date,
            RoomBlock.end_date > start_date,
        ).first()
        if overlap:
            raise ValueError("Phòng đã có lịch khóa trong khoảng ngày này")

        day_start = datetime.combine(start_date, time.min)
        day_end = datetime.combine(end_date, time.min)
        if day_start.tzinfo is None:
            day_start = VN_TZ.localize(day_start)
            day_end = VN_TZ.localize(day_end)
        active_stay = self.db.query(HotelStay).filter(
            HotelStay.room_id == room_id,
            HotelStay.status == HotelStayStatus.ACTIVE,
            HotelStay.check_in_at < day_end,
            or_(HotelStay.check_out_at.is_(None), HotelStay.check_out_at > day_start),
        ).first()
        if active_stay:
            raise ValueError("Không thể khóa phòng đang có khách ở")

        assigned_booking = self.db.query(Booking).filter(
            Booking.assigned_room_id == room_id,
            Booking.reservation_status.in_(["PENDING", "CONFIRMED", "CHECKED_IN"]),
            Booking.check_in < end_date,
            Booking.check_out > start_date,
        ).first()
        if assigned_booking:
            raise ValueError(f"Phòng đã được gán cho booking {assigned_booking.external_id}")

        block = RoomBlock(
            room_id=room.id,
            branch_id=room.branch_id,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            status="ACTIVE",
            created_by=user_id,
        )
        self.db.add(block)
        self.db.flush()

        for target_date in iter_stay_dates(start_date, end_date):
            inv = self.get_or_create_inventory(room.branch_id, room.room_type_id, target_date)
            inv.out_of_order_rooms += 1
            self._recalculate_available(inv)
            self.log_change(inv, "BLOCK_ROOM", 1, "out_of_order_rooms", "room_block", block.id, user_id, reason)
        self.db.flush()
        return block

    def release_block(self, block_id: int, user_id: Optional[int] = None) -> RoomBlock:
        block = self.db.query(RoomBlock).filter(RoomBlock.id == block_id).first()
        if not block:
            raise ValueError("Không tìm thấy lịch khóa phòng")
        if block.status != "ACTIVE":
            return block
        room = block.room
        block.status = "RELEASED"
        block.updated_at = datetime.now(VN_TZ)
        if room:
            for target_date in iter_stay_dates(block.start_date, block.end_date):
                inv = self.get_or_create_inventory(block.branch_id, room.room_type_id, target_date)
                delta = min(1, inv.out_of_order_rooms or 0)
                inv.out_of_order_rooms = max(0, (inv.out_of_order_rooms or 0) - 1)
                self._recalculate_available(inv)
                if delta:
                    self.log_change(inv, "UNBLOCK_ROOM", -delta, "out_of_order_rooms", "room_block", block.id, user_id)
        self.db.flush()
        return block

    def create_hold(
        self,
        branch_id: int,
        room_type_id: int,
        check_in: date,
        check_out: date,
        quantity: int = 1,
        booking_id: Optional[int] = None,
        hold_type: str = "MANUAL",
        expire_minutes: int = 15,
    ) -> List[RoomInventoryHold]:
        if check_out <= check_in:
            raise ValueError("Khoảng giữ phòng không hợp lệ")
        for target_date in iter_stay_dates(check_in, check_out):
            inv = self.get_or_create_inventory(branch_id, room_type_id, target_date)
            if inv.available_rooms < quantity:
                raise ValueError(f"Không đủ tồn để giữ phòng ngày {target_date.strftime('%d/%m/%Y')}")
        expire_at = datetime.now(VN_TZ) + timedelta(minutes=expire_minutes)
        holds = []
        for target_date in iter_stay_dates(check_in, check_out):
            hold = RoomInventoryHold(
                booking_id=booking_id,
                branch_id=branch_id,
                room_type_id=room_type_id,
                date=target_date,
                quantity=quantity,
                hold_type=hold_type,
                expire_at=expire_at,
            )
            self.db.add(hold)
            holds.append(hold)
        self.db.flush()
        return holds

    def release_expired_holds(self, now: Optional[datetime] = None) -> int:
        current = now or datetime.now(VN_TZ)
        holds = self.db.query(RoomInventoryHold).filter(
            RoomInventoryHold.released == False,
            RoomInventoryHold.expire_at <= current,
        ).all()
        for hold in holds:
            hold.released = True
        self.db.flush()
        return len(holds)

    def get_timeline(self, branch_id: int, start_date: date, days: int = 14) -> List[Dict[str, Any]]:
        end_date = start_date + timedelta(days=days)
        rooms = self.db.query(HotelRoom).filter(
            HotelRoom.branch_id == branch_id,
            HotelRoom.is_active == True,
        ).order_by(HotelRoom.floor, HotelRoom.sort_order, HotelRoom.room_number).all()

        bookings = self.db.query(
            Booking.id,
            Booking.assigned_room_id,
            Booking.reservation_status,
            Booking.guest_name,
            Booking.check_in,
            Booking.check_out,
        ).filter(
            Booking.branch_id == branch_id,
            Booking.reservation_status == "CONFIRMED",
            Booking.check_in < end_date,
            Booking.check_out > start_date,
        ).all()

        day_start = datetime.combine(start_date, time.min)
        day_end = datetime.combine(end_date, time.min)
        if day_start.tzinfo is None:
            day_start = VN_TZ.localize(day_start)
            day_end = VN_TZ.localize(day_end)
        active_stays = self.db.query(
            HotelStay.id,
            HotelStay.room_id,
            HotelStay.check_in_at,
            HotelStay.check_out_at,
            HotelStay.pricing_mode_initial,
            HotelStay.stay_type,
        ).filter(
            HotelStay.branch_id == branch_id,
            HotelStay.status == HotelStayStatus.ACTIVE,
            HotelStay.check_in_at < day_end,
            or_(HotelStay.check_out_at.is_(None), HotelStay.check_out_at > day_start),
        ).all()

        stay_ids = [s.id for s in active_stays]
        primary_guests = {}
        if stay_ids:
            guest_rows = self.db.query(
                HotelGuest.stay_id,
                HotelGuest.full_name,
                HotelGuest.is_primary,
            ).filter(
                HotelGuest.stay_id.in_(stay_ids),
            ).order_by(HotelGuest.stay_id, HotelGuest.is_primary.desc()).all()
            for stay_id, full_name, is_primary in guest_rows:
                if stay_id not in primary_guests:
                    primary_guests[stay_id] = full_name

        blocks = self.db.query(RoomBlock).filter(
            RoomBlock.branch_id == branch_id,
            RoomBlock.status == "ACTIVE",
            RoomBlock.start_date < end_date,
            RoomBlock.end_date > start_date,
        ).all()

        booking_by_room: Dict[int, List[Booking]] = {}
        unassigned_bookings: List[Booking] = []
        for booking in bookings:
            if booking.assigned_room_id:
                booking_by_room.setdefault(int(booking.assigned_room_id), []).append(booking)
            else:
                unassigned_bookings.append(booking)
        active_stays_by_room: Dict[int, list] = {}
        for stay in active_stays:
            active_stays_by_room.setdefault(int(stay.room_id), []).append(stay)
        blocks_by_room: Dict[int, List[RoomBlock]] = {}
        for block in blocks:
            blocks_by_room.setdefault(int(block.room_id), []).append(block)

        rows = []
        for room in rooms:
            events = []
            for booking in booking_by_room.get(room.id, []):
                events.append({
                    "type": "booking",
                    "status": booking.reservation_status,
                    "label": booking.guest_name,
                    "start_date": booking.check_in.isoformat(),
                    "end_date": booking.check_out.isoformat(),
                    "booking_id": booking.id,
                })
            for stay in active_stays_by_room.get(room.id, []):
                guest_name = primary_guests.get(stay.id, "Đang ở")
                check_in_at = stay.check_in_at.astimezone(VN_TZ) if stay.check_in_at.tzinfo else stay.check_in_at
                check_out_at = stay.check_out_at.astimezone(VN_TZ) if stay.check_out_at and stay.check_out_at.tzinfo else stay.check_out_at
                stay_start = check_in_at.date()
                raw_stay_mode = stay.pricing_mode_initial or stay.stay_type or ""
                stay_mode = str(getattr(raw_stay_mode, "value", raw_stay_mode)).upper()
                is_hourly = stay_mode in {"HOURLY", "HOURLY_CHARGE", "HOUR", "FORCE_HOURLY"}
                stay_end = check_out_at.date() if check_out_at else (stay_start if is_hourly else end_date)
                events.append({
                    "type": "booking",
                    "status": "CHECKED_IN",
                    "label": guest_name,
                    "start_date": stay_start.isoformat(),
                    "end_date": stay_end.isoformat(),
                    "stay_id": stay.id,
                    "is_hourly": is_hourly,
                })
            for block in blocks_by_room.get(room.id, []):
                events.append({
                    "type": "block",
                    "status": block.status,
                    "label": block.reason or "Khóa phòng",
                    "start_date": block.start_date.isoformat(),
                    "end_date": block.end_date.isoformat(),
                    "block_id": block.id,
                })
            rows.append({
                "room_id": room.id,
                "room_number": room.room_number,
                "room_type": room.room_type_obj.name if room.room_type_obj else None,
                "events": sorted(events, key=lambda item: (item["start_date"], item["type"])),
            })
        if unassigned_bookings:
            rows.append({
                "room_id": None,
                "room_number": "Chưa gán phòng",
                "room_type": "Đặt phòng",
                "is_unassigned": True,
                "events": sorted([
                    {
                        "type": "booking",
                        "status": booking.reservation_status,
                        "label": booking.guest_name,
                        "start_date": booking.check_in.isoformat(),
                        "end_date": booking.check_out.isoformat(),
                        "booking_id": booking.id,
                    }
                    for booking in unassigned_bookings
                ], key=lambda item: (item["start_date"], item["label"])),
            })
        return rows

    def get_availability(
        self,
        branch_id: int,
        check_in: date,
        check_out: date,
        room_type_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        q = self.db.query(HotelRoomType).filter(
            HotelRoomType.branch_id == branch_id,
            HotelRoomType.is_active == True,
        )
        if room_type_id:
            q = q.filter(HotelRoomType.id == room_type_id)

        room_types = q.order_by(HotelRoomType.sort_order, HotelRoomType.name).all()
        if not room_types:
            return []

        room_type_ids = [int(room_type.id) for room_type in room_types]
        stay_dates = list(iter_stay_dates(check_in, check_out))
        days = len(stay_dates)
        if days > 0:
            self.generate_daily_inventory(branch_id, check_in, days, refresh_counts=True)

        inventories = self.db.query(RoomInventoryDaily).filter(
            RoomInventoryDaily.branch_id == branch_id,
            RoomInventoryDaily.room_type_id.in_(room_type_ids),
            RoomInventoryDaily.date >= check_in,
            RoomInventoryDaily.date < check_out,
        ).all()
        inventory_by_key = {(int(inv.room_type_id), inv.date): inv for inv in inventories}

        result = []
        for room_type in room_types:
            type_id = int(room_type.id)
            type_inventories = [
                inventory_by_key[key]
                for key in [(type_id, d) for d in stay_dates]
                if key in inventory_by_key
            ]
            min_available = min([i.available_rooms for i in type_inventories], default=0)
            total_rooms = type_inventories[0].total_rooms if type_inventories else 0
            result.append({
                "room_type_id": room_type.id,
                "room_type": room_type.name,
                "max_guests": room_type.max_guests,
                "base_price": float(room_type.price_per_night or 0),
                "total_rooms": int(total_rooms),
                "available_rooms": int(min_available),
                "stop_sell": min_available <= 0,
                "low_inventory": 0 < min_available < 3,
            })
        return result

    def get_calendar(self, branch_id: int, start_date: date, days: int = 30) -> List[Dict[str, Any]]:
        calendar = []
        room_types = self.db.query(HotelRoomType).filter(
            HotelRoomType.branch_id == branch_id,
            HotelRoomType.is_active == True,
        ).order_by(HotelRoomType.sort_order, HotelRoomType.name).all()
        room_type_by_id = {int(room_type.id): room_type for room_type in room_types}
        end_date = start_date + timedelta(days=days)
        inventories = self.db.query(RoomInventoryDaily).filter(
            RoomInventoryDaily.branch_id == branch_id,
            RoomInventoryDaily.room_type_id.in_(list(room_type_by_id) or [0]),
            RoomInventoryDaily.date >= start_date,
            RoomInventoryDaily.date < end_date,
        ).all()
        inventory_by_key = {(int(inv.room_type_id), inv.date): inv for inv in inventories}

        cleaning_counts = dict(
            self.db.query(HotelRoom.room_type_id, func.count(HotelRoom.id)).filter(
                HotelRoom.branch_id == branch_id,
                HotelRoom.room_type_id.in_(list(room_type_by_id) or [0]),
                HotelRoom.is_active == True,
                HotelRoom.condition.in_([RoomCondition.DIRTY, RoomCondition.CLEANING]),
            ).group_by(HotelRoom.room_type_id).all()
        )

        physical_rooms_by_type: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        physical_room_ids_by_type: Dict[int, set[int]] = defaultdict(set)
        room_rows = self.db.query(HotelRoom.id, HotelRoom.room_type_id, HotelRoom.room_number).filter(
            HotelRoom.branch_id == branch_id,
            HotelRoom.room_type_id.in_(list(room_type_by_id) or [0]),
            HotelRoom.is_active == True,
        ).order_by(HotelRoom.floor, HotelRoom.sort_order, HotelRoom.room_number).all()
        for room_id, room_type_id, room_number in room_rows:
            if not room_type_id:
                continue
            type_id = int(room_type_id)
            physical_room_ids_by_type[type_id].add(int(room_id))
            physical_rooms_by_type[type_id].append({
                "room_id": int(room_id),
                "room_number": room_number,
            })

        unavailable_room_ids: Dict[date, set[int]] = defaultdict(set)
        assigned_bookings = self.db.query(Booking.assigned_room_id, Booking.check_in, Booking.check_out).filter(
            Booking.branch_id == branch_id,
            Booking.reservation_status == "CONFIRMED",
            Booking.assigned_room_id.isnot(None),
            Booking.check_in < end_date,
            Booking.check_out > start_date,
        ).all()
        for room_id, check_in, check_out in assigned_bookings:
            for target_date in iter_stay_dates(max(start_date, check_in), min(end_date, check_out)):
                unavailable_room_ids[target_date].add(int(room_id))

        day_start = datetime.combine(start_date, time.min)
        day_end = datetime.combine(end_date, time.min)
        if day_start.tzinfo is None:
            day_start = VN_TZ.localize(day_start)
            day_end = VN_TZ.localize(day_end)
        active_stays = self.db.query(HotelStay.room_id, HotelStay.check_in_at, HotelStay.check_out_at).filter(
            HotelStay.branch_id == branch_id,
            HotelStay.status == HotelStayStatus.ACTIVE,
            HotelStay.check_in_at < day_end,
            or_(HotelStay.check_out_at.is_(None), HotelStay.check_out_at > day_start),
        ).all()
        for room_id, check_in_at, check_out_at in active_stays:
            first_date = max(start_date, check_in_at.astimezone(VN_TZ).date())
            co_date = check_out_at.astimezone(VN_TZ).date() if check_out_at else end_date
            if co_date <= first_date:
                co_date = first_date + timedelta(days=1)
            last_date = min(end_date, co_date)
            for target_date in iter_stay_dates(first_date, last_date):
                unavailable_room_ids[target_date].add(int(room_id))

        blocks = self.db.query(RoomBlock.room_id, RoomBlock.start_date, RoomBlock.end_date).filter(
            RoomBlock.branch_id == branch_id,
            RoomBlock.status == "ACTIVE",
            RoomBlock.start_date < end_date,
            RoomBlock.end_date > start_date,
        ).all()
        for room_id, block_start, block_end in blocks:
            for target_date in iter_stay_dates(max(start_date, block_start), min(end_date, block_end)):
                unavailable_room_ids[target_date].add(int(room_id))

        for offset in range(days):
            target_date = start_date + timedelta(days=offset)
            type_rows = []
            total = reserved = sold = cleaning = ooo = available = 0
            for room_type in room_types:
                inv = inventory_by_key.get((int(room_type.id), target_date))
                if not inv:
                    continue
                cleaning_count = int(cleaning_counts.get(room_type.id, 0) or 0)
                available_room_ids = physical_room_ids_by_type.get(int(room_type.id), set()) - unavailable_room_ids[target_date]
                visible_available_rooms = [
                    room for room in physical_rooms_by_type.get(int(room_type.id), [])
                    if room["room_id"] in available_room_ids
                ][:max(int(inv.available_rooms or 0), 0)]
                type_rows.append({
                    "room_type_id": room_type.id,
                    "room_type": room_type.name,
                    "total_rooms": inv.total_rooms,
                    "available_rooms": inv.available_rooms,
                    "reserved_rooms": inv.reserved_rooms,
                    "sold_rooms": inv.sold_rooms,
                    "cleaning_rooms": cleaning_count,
                    "out_of_order_rooms": inv.out_of_order_rooms,
                    "overbooking_limit": inv.overbooking_limit,
                    "available_room_list": visible_available_rooms,
                })
                total += inv.total_rooms or 0
                reserved += inv.reserved_rooms or 0
                sold += inv.sold_rooms or 0
                cleaning += cleaning_count
                ooo += inv.out_of_order_rooms or 0
                available += inv.available_rooms or 0
            calendar.append({
                "date": target_date.isoformat(),
                "total_rooms": total,
                "available_rooms": available,
                "reserved_rooms": reserved,
                "sold_rooms": sold,
                "cleaning_rooms": cleaning,
                "out_of_order_rooms": ooo,
                "occupancy_rate": round(((reserved + sold) / total * 100), 1) if total else 0,
                "room_types": type_rows,
            })
        return calendar
