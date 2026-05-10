#!/usr/bin/env python3
"""Reset B17 Reservation Hub test data and seed aligned demo reservations."""
from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    load_dotenv(ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is missing")

    engine = create_engine(database_url, pool_pre_ping=True)
    with Session(engine) as db:
        branch_id = db.execute(
            text("select id from branches where branch_code = 'B17'")
        ).scalar_one_or_none()
        if not branch_id:
            raise RuntimeError("Không tìm thấy Chi nhánh B17")

        _cleanup(db, branch_id)
        seeded = _seed(db, branch_id)
        _reset_sequences(db)
        db.commit()
        _verify(db, branch_id, seeded)

    return 0


def _cleanup(db: Session, branch_id: int) -> None:
    booking_ids = [
        row[0]
        for row in db.execute(
            text("select id from bookings where branch_id = :branch_id"),
            {"branch_id": branch_id},
        )
    ]

    if booking_ids:
        db.execute(
            text("update bookings set source_booking_id = null where source_booking_id = any(:booking_ids)"),
            {"booking_ids": booking_ids},
        )
        db.execute(
            text("update ota_parsing_logs set booking_id = null where booking_id = any(:booking_ids)"),
            {"booking_ids": booking_ids},
        )
        db.execute(
            text("update guest_activities set booking_id = null where booking_id = any(:booking_ids)"),
            {"booking_ids": booking_ids},
        )

    db.execute(text("delete from room_inventory_holds where branch_id = :branch_id"), {"branch_id": branch_id})
    db.execute(text("delete from room_inventory_logs where branch_id = :branch_id"), {"branch_id": branch_id})
    db.execute(text("delete from room_inventory_daily where branch_id = :branch_id"), {"branch_id": branch_id})
    db.execute(text("delete from room_blocks where branch_id = :branch_id"), {"branch_id": branch_id})
    db.execute(text("delete from bookings where branch_id = :branch_id"), {"branch_id": branch_id})

    db.execute(
        text(
            """
            delete from hotel_room_types rt
            where rt.branch_id = :branch_id
              and rt.name in ('Deluxe Test B17', 'Suite Test B17')
              and not exists (
                select 1 from hotel_rooms hr where hr.room_type_id = rt.id
              )
            """
        ),
        {"branch_id": branch_id},
    )
    db.flush()


def _seed(db: Session, branch_id: int) -> list[int]:
    room_types = db.execute(
        text(
            """
            select
              rt.id,
              rt.name,
              rt.price_per_night,
              rt.max_guests,
              count(hr.id) as active_rooms
            from hotel_room_types rt
            join hotel_rooms hr
              on hr.room_type_id = rt.id
             and hr.branch_id = rt.branch_id
             and hr.is_active = true
            where rt.branch_id = :branch_id
              and rt.is_active = true
            group by rt.id, rt.name, rt.price_per_night, rt.max_guests, rt.sort_order
            order by rt.sort_order, rt.id
            """
        ),
        {"branch_id": branch_id},
    ).mappings().all()
    if not room_types:
        raise RuntimeError("B17 không có loại phòng active nào có phòng active")

    today = date.today()
    seeded_ids: list[int] = []

    preferred = ["Sup", "Deluxe", "Deluxe Kéo", "Suite", "Twin"]
    type_by_name = {row["name"]: row for row in room_types}
    ordered_types = [type_by_name[name] for name in preferred if name in type_by_name]
    ordered_types.extend(row for row in room_types if row["name"] not in preferred)

    seed_specs = [
        ("DIRECT", "B17-DIRECT-SUP-001", "Nguyễn Minh B17", 1, 2, "CONFIRMED", True),
        ("DIRECT", "B17-DIRECT-DELUXE-001", "Trần Hạnh B17", 3, 5, "PENDING", False),
        ("PHONE", "B17-PHONE-DELUXE-KEO-001", "Lê Gia B17", 4, 6, "CONFIRMED", False),
        ("OTA", "B17-OTA-SUITE-001", "OTA Suite B17", 7, 9, "CONFIRMED", False),
        ("WEBSITE", "B17-WEB-TWIN-001", "Website Twin B17", 10, 12, "CONFIRMED", False),
    ]

    for index, spec in enumerate(seed_specs):
        booking_type, external_id, guest_name, start_offset, end_offset, status, assign_room = spec
        room_type = ordered_types[min(index, len(ordered_types) - 1)]
        check_in = today + timedelta(days=start_offset)
        check_out = today + timedelta(days=end_offset)
        nights = (check_out - check_in).days
        price = Decimal(room_type["price_per_night"] or 0) * nights
        room = _first_available_room(db, branch_id, int(room_type["id"]), check_in, check_out) if assign_room else None
        booking_id = db.execute(
            text(
                """
                insert into bookings (
                  booking_source, external_id, guest_name, guest_phone,
                  check_in, check_out, room_type,
                  num_guests, num_adults, num_children,
                  total_price, currency, is_prepaid, payment_method, deposit_amount,
                  status, branch_id, raw_data,
                  booking_type, reservation_status, assigned_room_id,
                  estimated_arrival, special_requests, internal_notes,
                  confirmed_at, created_at, updated_at, version
                )
                values (
                  :booking_source, :external_id, :guest_name, :guest_phone,
                  :check_in, :check_out, :room_type,
                  :num_guests, :num_adults, 0,
                  :total_price, 'VND', :is_prepaid, :payment_method, :deposit_amount,
                  'CONFIRMED', :branch_id,
                  jsonb_build_object(
                    'room_type_id', :room_type_id,
                    'reservation_inventory_reserved', :reserved,
                    'reservation_reserved_room_type_id', case when :reserved then :room_type_id else null end,
                    'reservation_reserved_check_in', case when :reserved then cast(:check_in as text) else null end,
                    'reservation_reserved_check_out', case when :reserved then cast(:check_out as text) else null end,
                    'reservation_reserved_qty', case when :reserved then 1 else null end,
                    'seed_scope', 'B17_RESERVATION_RESET'
                  ),
                  :booking_type, :reservation_status, :assigned_room_id,
                  :estimated_arrival, :special_requests, :internal_notes,
                  case when :is_confirmed then now() else null end,
                  now(), now(), 1
                )
                returning id
                """
            ),
            {
                "booking_source": _booking_source(booking_type),
                "external_id": external_id,
                "guest_name": guest_name,
                "guest_phone": f"09017{index + 1:05d}",
                "check_in": check_in,
                "check_out": check_out,
                "room_type": room_type["name"],
                "num_guests": min(int(room_type["max_guests"] or 2), 2),
                "num_adults": min(int(room_type["max_guests"] or 2), 2),
                "total_price": price,
                "is_prepaid": booking_type in {"OTA", "WEBSITE"},
                "payment_method": "OTA_COLLECT" if booking_type == "OTA" else "CASH",
                "deposit_amount": price if booking_type == "OTA" else Decimal("200000") if status == "CONFIRMED" else Decimal("0"),
                "branch_id": branch_id,
                "room_type_id": int(room_type["id"]),
                "reserved": status == "CONFIRMED",
                "booking_type": booking_type,
                "reservation_status": status,
                "is_confirmed": status == "CONFIRMED",
                "assigned_room_id": room["id"] if room else None,
                "estimated_arrival": "14:30" if status == "CONFIRMED" else "18:00",
                "special_requests": f"Seed {room_type['name']} đúng hạng phòng B17",
                "internal_notes": "Seed lại sau khi dọn dữ liệu test Reservation Hub",
            },
        ).scalar_one()
        seeded_ids.append(int(booking_id))

    block_room = _room_for_type_name(db, branch_id, "Suite") or _room_for_type_name(db, branch_id, ordered_types[-1]["name"])
    if block_room:
        block_id = db.execute(
            text(
                """
                insert into room_blocks (room_id, branch_id, start_date, end_date, reason, status, created_at, updated_at)
                values (:room_id, :branch_id, :start_date, :end_date, :reason, 'ACTIVE', now(), now())
                returning id
                """
            ),
            {
                "room_id": block_room["id"],
                "branch_id": branch_id,
                "start_date": today + timedelta(days=2),
                "end_date": today + timedelta(days=3),
                "reason": "Seed B17: bảo trì kiểm tra sau reset Reservation Hub",
            },
        ).scalar_one()
        db.execute(
            text(
                """
                insert into room_inventory_logs (
                  branch_id, room_type_id, date, change_type,
                  delta, field_changed, ref_type, ref_id, note, created_at
                )
                values (
                  :branch_id, :room_type_id, :date, 'BLOCK_ROOM',
                  1, 'out_of_order_rooms', 'room_block', :block_id, :note, now()
                )
                """
            ),
            {
                "branch_id": branch_id,
                "room_type_id": block_room["room_type_id"],
                "date": today + timedelta(days=2),
                "block_id": block_id,
                "note": "Seed lại dữ liệu khóa phòng B17",
            },
        )

    _rebuild_inventory(db, branch_id, today, 120)
    return seeded_ids


def _booking_source(booking_type: str) -> str:
    return {
        "DIRECT": "Direct",
        "PHONE": "Phone",
        "WEBSITE": "Website",
        "OTA": "Booking.com",
    }.get(booking_type, "Direct")


def _first_available_room(db: Session, branch_id: int, room_type_id: int, check_in: date, check_out: date):
    return db.execute(
        text(
            """
            select hr.id, hr.room_type_id
            from hotel_rooms hr
            where hr.branch_id = :branch_id
              and hr.room_type_id = :room_type_id
              and hr.is_active = true
              and not exists (
                select 1
                from room_blocks rb
                where rb.room_id = hr.id
                  and rb.status = 'ACTIVE'
                  and rb.start_date < :check_out
                  and rb.end_date > :check_in
              )
            order by hr.sort_order, hr.id
            limit 1
            """
        ),
        {"branch_id": branch_id, "room_type_id": room_type_id, "check_in": check_in, "check_out": check_out},
    ).mappings().first()


def _room_for_type_name(db: Session, branch_id: int, type_name: str):
    return db.execute(
        text(
            """
            select hr.id, hr.room_type_id
            from hotel_rooms hr
            join hotel_room_types rt on rt.id = hr.room_type_id
            where hr.branch_id = :branch_id
              and hr.is_active = true
              and rt.name = :type_name
            order by hr.sort_order desc, hr.id desc
            limit 1
            """
        ),
        {"branch_id": branch_id, "type_name": type_name},
    ).mappings().first()


def _rebuild_inventory(db: Session, branch_id: int, start_date: date, days: int) -> None:
    db.execute(
        text(
            """
            with days as (
              select generate_series(cast(:start_date as date), (cast(:start_date as date) + (:days - 1)), interval '1 day')::date as d
            ),
            rt as (
              select id, branch_id, price_per_night
              from hotel_room_types
              where branch_id = :branch_id
                and is_active = true
                and exists (
                  select 1
                  from hotel_rooms hr
                  where hr.branch_id = hotel_room_types.branch_id
                    and hr.room_type_id = hotel_room_types.id
                    and hr.is_active = true
                )
            ),
            calc as (
              select
                rt.branch_id,
                rt.id as room_type_id,
                days.d as date,
                (
                  select count(*)::int
                  from hotel_rooms r
                  where r.branch_id = rt.branch_id
                    and r.room_type_id = rt.id
                    and r.is_active = true
                ) as total_rooms,
                (
                  select count(*)::int
                  from bookings bk
                  where bk.branch_id = rt.branch_id
                    and coalesce((bk.raw_data->>'room_type_id')::int, 0) = rt.id
                    and bk.reservation_status = 'CONFIRMED'
                    and bk.stay_id is null
                    and bk.check_in <= days.d
                    and bk.check_out > days.d
                ) as reserved_rooms,
                (
                  select count(distinct hs.room_id)::int
                  from hotel_stays hs
                  join hotel_rooms r on r.id = hs.room_id
                  where hs.branch_id = rt.branch_id
                    and hs.status = 'ACTIVE'
                    and r.room_type_id = rt.id
                    and hs.check_in_at < (days.d + interval '1 day')
                    and (hs.check_out_at is null or hs.check_out_at > days.d)
                ) as sold_rooms,
                (
                  select count(*)::int
                  from room_blocks rb
                  join hotel_rooms r on r.id = rb.room_id
                  where rb.branch_id = rt.branch_id
                    and r.room_type_id = rt.id
                    and rb.status = 'ACTIVE'
                    and rb.start_date <= days.d
                    and rb.end_date > days.d
                ) as out_of_order_rooms,
                rt.price_per_night as base_price
              from rt
              cross join days
            )
            insert into room_inventory_daily (
              branch_id, room_type_id, date,
              total_rooms, reserved_rooms, sold_rooms, out_of_order_rooms,
              available_rooms, overbooking_limit, base_price,
              created_at, updated_at
            )
            select
              branch_id,
              room_type_id,
              date,
              total_rooms,
              reserved_rooms,
              sold_rooms,
              out_of_order_rooms,
              greatest(total_rooms - reserved_rooms - sold_rooms - out_of_order_rooms, 0),
              0,
              base_price,
              now(),
              now()
            from calc
            on conflict (branch_id, room_type_id, date)
            do update set
              total_rooms = excluded.total_rooms,
              reserved_rooms = excluded.reserved_rooms,
              sold_rooms = excluded.sold_rooms,
              out_of_order_rooms = excluded.out_of_order_rooms,
              available_rooms = excluded.available_rooms,
              base_price = excluded.base_price,
              updated_at = now()
            """
        ),
        {"branch_id": branch_id, "start_date": start_date, "days": days},
    )


def _reset_sequences(db: Session) -> None:
    if db.bind.dialect.name != "postgresql":
        return
    tables = [
        "bookings",
        "room_blocks",
        "room_inventory_daily",
        "room_inventory_holds",
        "room_inventory_logs",
        "hotel_room_types",
    ]
    for table_name in tables:
        seq_name = db.execute(text("select pg_get_serial_sequence(:table_name, 'id')"), {"table_name": table_name}).scalar()
        if not seq_name:
            continue
        max_id = db.execute(text(f'select coalesce(max(id), 0) from "{table_name}"')).scalar() or 0
        db.execute(text("select setval(:seq_name, :next_id, false)"), {"seq_name": seq_name, "next_id": int(max_id) + 1})


def _verify(db: Session, branch_id: int, seeded_ids: list[int]) -> None:
    summary = db.execute(
        text(
            """
            select
              (select count(*) from hotel_room_types where branch_id = :branch_id and is_active = true) as room_types,
              (select count(*) from hotel_rooms where branch_id = :branch_id and is_active = true) as rooms,
              (select count(*) from bookings where branch_id = :branch_id) as bookings,
              (select count(*) from room_blocks where branch_id = :branch_id) as blocks,
              (select count(*) from room_inventory_daily where branch_id = :branch_id) as inventory_rows
            """
        ),
        {"branch_id": branch_id},
    ).mappings().one()
    print("B17 Reservation Hub reset complete")
    print(f"  seeded booking ids : {seeded_ids}")
    print(f"  active room types  : {summary['room_types']}")
    print(f"  active rooms       : {summary['rooms']}")
    print(f"  bookings           : {summary['bookings']}")
    print(f"  room blocks        : {summary['blocks']}")
    print(f"  inventory rows     : {summary['inventory_rows']}")


if __name__ == "__main__":
    raise SystemExit(main())
