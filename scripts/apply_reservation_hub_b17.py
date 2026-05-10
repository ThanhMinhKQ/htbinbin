#!/usr/bin/env python3
"""
Apply Reservation Hub schema and seed B17 test data.

Usage:
    python scripts/apply_reservation_hub_b17.py

The script reads DATABASE_URL from .env or the current environment.
It intentionally does not store credentials in this file.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def load_database_url() -> str:
    load_dotenv(ENV_PATH)
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is missing. Put it in .env or export it before running.")
    return url


def table_columns(conn: Connection, table_name: str) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT
                c.column_name,
                c.data_type,
                c.udt_name,
                c.is_nullable,
                c.column_default
            FROM information_schema.columns c
            WHERE c.table_schema = 'public'
              AND c.table_name = :table_name
            ORDER BY c.ordinal_position
            """
        ),
        {"table_name": table_name},
    ).mappings()
    return {row["column_name"]: dict(row) for row in rows}


def fallback_value(col: dict[str, Any]) -> Any:
    data_type = str(col.get("data_type") or "").lower()
    udt_name = str(col.get("udt_name") or "").lower()
    name = str(col.get("column_name") or "").lower()

    if data_type == "boolean":
        return False
    if data_type in {"integer", "bigint", "smallint"}:
        return 0
    if data_type in {"numeric", "double precision", "real"}:
        return 0
    if data_type == "date":
        return date.today()
    if data_type.startswith("timestamp"):
        return None
    if data_type == "time without time zone":
        return time(0, 0)
    if data_type in {"json", "jsonb"}:
        return "{}"
    if data_type == "USER-DEFINED".lower() or data_type == "user-defined":
        if "roomcondition" in udt_name or name == "condition":
            return "CLEAN"
        if "bookingstatus" in udt_name or name == "status":
            return "CONFIRMED"
        return ""
    return ""


def fill_required(conn: Connection, table_name: str, values: dict[str, Any]) -> dict[str, Any]:
    cols = table_columns(conn, table_name)
    filled = dict(values)
    for name, col in cols.items():
        if name in filled:
            continue
        if name == "id":
            continue
        if col.get("is_nullable") == "NO" and col.get("column_default") is None:
            filled[name] = fallback_value(col)
    return {k: v for k, v in filled.items() if k in cols}


def insert_if_missing(
    conn: Connection,
    table_name: str,
    values: dict[str, Any],
    where_sql: str,
    where_params: dict[str, Any],
) -> None:
    exists = conn.execute(text(f"SELECT 1 FROM {table_name} WHERE {where_sql} LIMIT 1"), where_params).first()
    if exists:
        return

    values = fill_required(conn, table_name, values)
    columns = list(values.keys())
    params = {f"v_{col}": value for col, value in values.items()}
    column_sql = ", ".join(columns)
    value_sql_parts = []
    for col in columns:
        if isinstance(values[col], (dict, list)):
            params[f"v_{col}"] = json.dumps(values[col], ensure_ascii=False)
            value_sql_parts.append(f"CAST(:v_{col} AS jsonb)")
        else:
            value_sql_parts.append(f":v_{col}")
    value_sql = ", ".join(value_sql_parts)
    conn.execute(text(f"INSERT INTO {table_name} ({column_sql}) VALUES ({value_sql})"), params)


def scalar(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> Any:
    return conn.execute(text(sql), params or {}).scalar_one_or_none()


def apply_schema(conn: Connection) -> None:
    statements = [
        """
        ALTER TABLE bookings
          ADD COLUMN IF NOT EXISTS booking_type varchar(20) NOT NULL DEFAULT 'OTA',
          ADD COLUMN IF NOT EXISTS reservation_status varchar(20) NOT NULL DEFAULT 'CONFIRMED',
          ADD COLUMN IF NOT EXISTS assigned_room_id integer NULL,
          ADD COLUMN IF NOT EXISTS stay_id bigint NULL,
          ADD COLUMN IF NOT EXISTS estimated_arrival time NULL,
          ADD COLUMN IF NOT EXISTS special_requests text NULL,
          ADD COLUMN IF NOT EXISTS internal_notes text NULL,
          ADD COLUMN IF NOT EXISTS confirmed_at timestamptz NULL,
          ADD COLUMN IF NOT EXISTS cancelled_at timestamptz NULL,
          ADD COLUMN IF NOT EXISTS cancel_reason text NULL,
          ADD COLUMN IF NOT EXISTS no_show_at timestamptz NULL
        """,
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_bookings_assigned_room_id') THEN
            ALTER TABLE bookings
              ADD CONSTRAINT fk_bookings_assigned_room_id
              FOREIGN KEY (assigned_room_id) REFERENCES hotel_rooms(id) ON DELETE SET NULL;
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_bookings_stay_id') THEN
            ALTER TABLE bookings
              ADD CONSTRAINT fk_bookings_stay_id
              FOREIGN KEY (stay_id) REFERENCES hotel_stays(id) ON DELETE SET NULL;
          END IF;
        END $$
        """,
        "CREATE INDEX IF NOT EXISTS ix_bookings_booking_type ON bookings(booking_type)",
        "CREATE INDEX IF NOT EXISTS ix_bookings_assigned_room_id ON bookings(assigned_room_id)",
        "CREATE INDEX IF NOT EXISTS ix_bookings_stay_id ON bookings(stay_id)",
        "CREATE INDEX IF NOT EXISTS ix_booking_reservation_status ON bookings(reservation_status)",
        "CREATE INDEX IF NOT EXISTS ix_booking_branch_checkin_status ON bookings(branch_id, check_in, reservation_status)",
        """
        CREATE TABLE IF NOT EXISTS room_inventory_daily (
          id bigserial PRIMARY KEY,
          branch_id integer NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
          room_type_id integer NOT NULL REFERENCES hotel_room_types(id) ON DELETE CASCADE,
          date date NOT NULL,
          total_rooms integer NOT NULL DEFAULT 0,
          available_rooms integer NOT NULL DEFAULT 0,
          reserved_rooms integer NOT NULL DEFAULT 0,
          sold_rooms integer NOT NULL DEFAULT 0,
          out_of_order_rooms integer NOT NULL DEFAULT 0,
          overbooking_limit integer NOT NULL DEFAULT 0,
          base_price numeric(15,2) NOT NULL DEFAULT 0,
          created_at timestamptz DEFAULT now(),
          updated_at timestamptz DEFAULT now()
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_room_inventory_branch_type_date ON room_inventory_daily(branch_id, room_type_id, date)",
        "CREATE INDEX IF NOT EXISTS ix_room_inventory_branch_date ON room_inventory_daily(branch_id, date)",
        """
        CREATE TABLE IF NOT EXISTS room_blocks (
          id bigserial PRIMARY KEY,
          room_id integer NOT NULL REFERENCES hotel_rooms(id) ON DELETE CASCADE,
          branch_id integer NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
          start_date date NOT NULL,
          end_date date NOT NULL,
          reason text NULL,
          status varchar(20) NOT NULL DEFAULT 'ACTIVE',
          created_by bigint NULL REFERENCES users(id) ON DELETE SET NULL,
          created_at timestamptz DEFAULT now(),
          updated_at timestamptz DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_room_blocks_room_id ON room_blocks(room_id)",
        "CREATE INDEX IF NOT EXISTS ix_room_blocks_branch_id ON room_blocks(branch_id)",
        "CREATE INDEX IF NOT EXISTS ix_room_blocks_start_date ON room_blocks(start_date)",
        "CREATE INDEX IF NOT EXISTS ix_room_blocks_end_date ON room_blocks(end_date)",
        "CREATE INDEX IF NOT EXISTS ix_room_blocks_status ON room_blocks(status)",
        """
        CREATE TABLE IF NOT EXISTS room_inventory_holds (
          id bigserial PRIMARY KEY,
          booking_id bigint NULL REFERENCES bookings(id) ON DELETE CASCADE,
          branch_id integer NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
          room_type_id integer NOT NULL REFERENCES hotel_room_types(id) ON DELETE CASCADE,
          date date NOT NULL,
          quantity integer NOT NULL DEFAULT 1,
          hold_type varchar(20) NOT NULL DEFAULT 'MANUAL',
          expire_at timestamptz NOT NULL,
          released boolean NOT NULL DEFAULT false,
          created_at timestamptz DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_room_inventory_holds_booking_id ON room_inventory_holds(booking_id)",
        "CREATE INDEX IF NOT EXISTS ix_room_inventory_holds_branch_id ON room_inventory_holds(branch_id)",
        "CREATE INDEX IF NOT EXISTS ix_room_inventory_holds_room_type_id ON room_inventory_holds(room_type_id)",
        "CREATE INDEX IF NOT EXISTS ix_room_inventory_holds_date ON room_inventory_holds(date)",
        "CREATE INDEX IF NOT EXISTS ix_room_inventory_holds_expire_at ON room_inventory_holds(expire_at)",
        "CREATE INDEX IF NOT EXISTS ix_room_inventory_holds_released ON room_inventory_holds(released)",
        """
        CREATE TABLE IF NOT EXISTS room_inventory_logs (
          id bigserial PRIMARY KEY,
          branch_id integer NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
          room_type_id integer NOT NULL REFERENCES hotel_room_types(id) ON DELETE CASCADE,
          date date NOT NULL,
          change_type varchar(30) NOT NULL,
          delta integer NOT NULL,
          field_changed varchar(20) NOT NULL,
          ref_type varchar(20) NULL,
          ref_id bigint NULL,
          note text NULL,
          created_by bigint NULL REFERENCES users(id) ON DELETE SET NULL,
          created_at timestamptz DEFAULT now()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_room_inventory_logs_branch_id ON room_inventory_logs(branch_id)",
        "CREATE INDEX IF NOT EXISTS ix_room_inventory_logs_room_type_id ON room_inventory_logs(room_type_id)",
        "CREATE INDEX IF NOT EXISTS ix_room_inventory_logs_date ON room_inventory_logs(date)",
        "CREATE INDEX IF NOT EXISTS ix_room_inventory_logs_change_type ON room_inventory_logs(change_type)",
        "CREATE INDEX IF NOT EXISTS ix_room_inventory_logs_ref_id ON room_inventory_logs(ref_id)",
        "CREATE INDEX IF NOT EXISTS ix_room_inventory_logs_created_at ON room_inventory_logs(created_at)",
    ]
    for stmt in statements:
        conn.execute(text(stmt))


def seed_b17(conn: Connection) -> None:
    insert_if_missing(
        conn,
        "branches",
        {"branch_code": "B17", "name": "Chi nhánh B17", "address": "Dữ liệu test Reservation Hub"},
        "branch_code = :branch_code",
        {"branch_code": "B17"},
    )
    branch_id = scalar(conn, "SELECT id FROM branches WHERE branch_code = 'B17'")
    if not branch_id:
        raise RuntimeError("Cannot find or create branch B17")

    room_types = [
        {
            "name": "Deluxe Test B17",
            "description": "Loại phòng test cho Booking Hub",
            "price_per_night": 540000,
            "price_per_hour": 160000,
            "price_next_hour": 60000,
            "promo_discount_amount": 0,
            "promo_discount_percent": 0,
            "min_hours": 2,
            "max_guests": 2,
            "is_active": True,
            "sort_order": 10,
            "standard_checkin_time": time(14, 0),
            "standard_checkout_time": time(12, 0),
            "early_checkin_fee_per_hour": 50000,
            "late_checkout_fee_per_hour": 50000,
            "grace_minutes": 10,
            "day_threshold_hours": 8,
        },
        {
            "name": "Suite Test B17",
            "description": "Loại phòng test cao cấp cho Booking Hub",
            "price_per_night": 850000,
            "price_per_hour": 220000,
            "price_next_hour": 80000,
            "promo_discount_amount": 0,
            "promo_discount_percent": 0,
            "min_hours": 2,
            "max_guests": 4,
            "is_active": True,
            "sort_order": 20,
            "standard_checkin_time": time(14, 0),
            "standard_checkout_time": time(12, 0),
            "early_checkin_fee_per_hour": 50000,
            "late_checkout_fee_per_hour": 50000,
            "grace_minutes": 10,
            "day_threshold_hours": 8,
        },
    ]
    for rt in room_types:
        insert_if_missing(
            conn,
            "hotel_room_types",
            {"branch_id": branch_id, **rt},
            "branch_id = :branch_id AND name = :name",
            {"branch_id": branch_id, "name": rt["name"]},
        )

    rt_ids = {
        row["name"]: row["id"]
        for row in conn.execute(
            text("SELECT id, name FROM hotel_room_types WHERE branch_id = :branch_id"),
            {"branch_id": branch_id},
        ).mappings()
    }
    rooms = [
        ("101", 1, "Deluxe Test B17", 10),
        ("102", 1, "Deluxe Test B17", 20),
        ("103", 1, "Deluxe Test B17", 30),
        ("201", 2, "Suite Test B17", 40),
        ("202", 2, "Suite Test B17", 50),
    ]
    for room_number, floor, rt_name, sort_order in rooms:
        insert_if_missing(
            conn,
            "hotel_rooms",
            {
                "branch_id": branch_id,
                "room_type_id": rt_ids[rt_name],
                "floor": floor,
                "room_number": room_number,
                "condition": "CLEAN",
                "is_active": True,
                "sort_order": sort_order,
            },
            "branch_id = :branch_id AND room_number = :room_number",
            {"branch_id": branch_id, "room_number": room_number},
        )

    usable_room_types = conn.execute(
        text(
            """
            SELECT rt.id, rt.name, rt.price_per_night
            FROM hotel_room_types rt
            WHERE rt.branch_id = :branch_id
              AND rt.is_active = true
              AND EXISTS (
                SELECT 1
                FROM hotel_rooms hr
                WHERE hr.branch_id = rt.branch_id
                  AND hr.room_type_id = rt.id
                  AND hr.is_active = true
              )
            ORDER BY rt.sort_order, rt.id
            """
        ),
        {"branch_id": branch_id},
    ).mappings().all()
    if not usable_room_types:
        raise RuntimeError("B17 has no active rooms with room type")
    deluxe = usable_room_types[0]
    suite = usable_room_types[1] if len(usable_room_types) > 1 else usable_room_types[0]
    room_101 = scalar(
        conn,
        """
        SELECT id
        FROM hotel_rooms
        WHERE branch_id = :branch_id
          AND room_type_id = :room_type_id
          AND is_active = true
        ORDER BY sort_order, id
        LIMIT 1
        """,
        {"branch_id": branch_id, "room_type_id": deluxe["id"]},
    )

    bookings = [
        {
            "booking_source": "DIRECT",
            "external_id": "B17-DIRECT-CONFIRMED-001",
            "guest_name": "Nguyễn Test Confirmed",
            "guest_phone": "0901000001",
            "check_in": "current_date + 1",
            "check_out": "current_date + 2",
            "room_type": deluxe["name"],
            "num_guests": 2,
            "num_adults": 2,
            "num_children": 0,
            "total_price": deluxe["price_per_night"],
            "currency": "VND",
            "is_prepaid": False,
            "payment_method": "CASH",
            "deposit_amount": 200000,
            "status": "CONFIRMED",
            "branch_id": branch_id,
            "raw_data": {"room_type_id": deluxe["id"], "guest_email": "confirmed.b17@test.local", "guest_cccd": "001TEST000001"},
            "booking_type": "DIRECT",
            "reservation_status": "CONFIRMED",
            "assigned_room_id": room_101,
            "estimated_arrival": time(14, 30),
            "special_requests": "Khách muốn phòng yên tĩnh",
            "internal_notes": "Seed test booking đã gán phòng",
        },
        {
            "booking_source": "DIRECT",
            "external_id": "B17-DIRECT-PENDING-001",
            "guest_name": "Trần Test Pending",
            "guest_phone": "0901000002",
            "check_in": "current_date + 3",
            "check_out": "current_date + 5",
            "room_type": deluxe["name"],
            "num_guests": 1,
            "num_adults": 1,
            "num_children": 0,
            "total_price": deluxe["price_per_night"] * 2,
            "currency": "VND",
            "is_prepaid": False,
            "payment_method": "CASH",
            "deposit_amount": 0,
            "status": "CONFIRMED",
            "branch_id": branch_id,
            "raw_data": {"room_type_id": deluxe["id"], "guest_email": "pending.b17@test.local", "guest_cccd": "001TEST000002"},
            "booking_type": "DIRECT",
            "reservation_status": "PENDING",
            "estimated_arrival": time(18, 0),
            "special_requests": "Đang chờ khách xác nhận",
            "internal_notes": "Seed test booking pending",
        },
        {
            "booking_source": "Booking.com",
            "external_id": "B17-OTA-CONFIRMED-001",
            "guest_name": "OTA Test Guest",
            "guest_phone": "0901000003",
            "check_in": "current_date + 6",
            "check_out": "current_date + 8",
            "room_type": suite["name"],
            "num_guests": 2,
            "num_adults": 2,
            "num_children": 0,
            "total_price": suite["price_per_night"] * 2,
            "currency": "VND",
            "is_prepaid": True,
            "payment_method": "OTA_COLLECT",
            "deposit_amount": suite["price_per_night"] * 2,
            "status": "CONFIRMED",
            "branch_id": branch_id,
            "raw_data": {"room_type_id": suite["id"], "guest_email": "ota.b17@test.local", "guest_cccd": "001TEST000003"},
            "booking_type": "OTA",
            "reservation_status": "CONFIRMED",
            "special_requests": "Booking OTA seed",
            "internal_notes": "Seed OTA booking",
        },
    ]
    for booking in bookings:
        date_expr = {
            "check_in": booking.pop("check_in"),
            "check_out": booking.pop("check_out"),
        }
        exists = scalar(
            conn,
            "SELECT id FROM bookings WHERE booking_source = :source AND external_id = :external_id",
            {"source": booking["booking_source"], "external_id": booking["external_id"]},
        )
        if exists:
            conn.execute(
                text(
                    f"""
                    UPDATE bookings
                    SET
                      guest_name = :guest_name,
                      guest_phone = :guest_phone,
                      check_in = {date_expr["check_in"]},
                      check_out = {date_expr["check_out"]},
                      room_type = :room_type,
                      num_guests = :num_guests,
                      num_adults = :num_adults,
                      num_children = :num_children,
                      total_price = :total_price,
                      currency = :currency,
                      is_prepaid = :is_prepaid,
                      payment_method = :payment_method,
                      deposit_amount = :deposit_amount,
                      branch_id = :branch_id,
                      raw_data = CAST(:raw_data AS jsonb),
                      booking_type = :booking_type,
                      reservation_status = :reservation_status,
                      assigned_room_id = :assigned_room_id,
                      estimated_arrival = :estimated_arrival,
                      special_requests = :special_requests,
                      internal_notes = :internal_notes,
                      updated_at = now()
                    WHERE id = :id
                    """
                ),
                {
                    "id": exists,
                    "guest_name": booking["guest_name"],
                    "guest_phone": booking["guest_phone"],
                    "room_type": booking["room_type"],
                    "num_guests": booking["num_guests"],
                    "num_adults": booking["num_adults"],
                    "num_children": booking["num_children"],
                    "total_price": booking["total_price"],
                    "currency": booking["currency"],
                    "is_prepaid": booking["is_prepaid"],
                    "payment_method": booking["payment_method"],
                    "deposit_amount": booking["deposit_amount"],
                    "branch_id": booking["branch_id"],
                    "raw_data": json.dumps(booking["raw_data"], ensure_ascii=False),
                    "booking_type": booking["booking_type"],
                    "reservation_status": booking["reservation_status"],
                    "assigned_room_id": booking.get("assigned_room_id"),
                    "estimated_arrival": booking.get("estimated_arrival"),
                    "special_requests": booking.get("special_requests"),
                    "internal_notes": booking.get("internal_notes"),
                },
            )
            continue
        values = fill_required(conn, "bookings", booking)
        values.pop("check_in", None)
        values.pop("check_out", None)
        values.pop("confirmed_at", None)
        if "version" in values and not values["version"]:
            values["version"] = 1
        columns = list(values.keys()) + ["check_in", "check_out", "confirmed_at"]
        params = {f"v_{col}": value for col, value in values.items()}
        parts = []
        for col in values:
            if isinstance(values[col], (dict, list)):
                params[f"v_{col}"] = json.dumps(values[col], ensure_ascii=False)
                parts.append(f"CAST(:v_{col} AS jsonb)")
            else:
                parts.append(f":v_{col}")
        parts.extend([date_expr["check_in"], date_expr["check_out"], "now()"])
        conn.execute(text(f"INSERT INTO bookings ({', '.join(columns)}) VALUES ({', '.join(parts)})"), params)

    room_202 = conn.execute(
        text(
            """
            SELECT id, branch_id, room_type_id
            FROM hotel_rooms
            WHERE branch_id = :branch_id AND room_number = '202'
            LIMIT 1
            """
        ),
        {"branch_id": branch_id},
    ).mappings().first()
    if room_202:
        exists = scalar(
            conn,
            """
            SELECT id FROM room_blocks
            WHERE room_id = :room_id
              AND status = 'ACTIVE'
              AND start_date = current_date + 4
              AND end_date = current_date + 5
            """,
            {"room_id": room_202["id"]},
        )
        if not exists:
            conn.execute(
                text(
                    """
                    INSERT INTO room_blocks (room_id, branch_id, start_date, end_date, reason, status)
                    VALUES (:room_id, :branch_id, current_date + 4, current_date + 5, :reason, 'ACTIVE')
                    """
                ),
                {"room_id": room_202["id"], "branch_id": branch_id, "reason": "Seed test: bảo trì phòng B17"},
            )

    conn.execute(
        text(
            """
            WITH days AS (
              SELECT generate_series(current_date, current_date + interval '119 days', interval '1 day')::date AS d
            ),
            rt AS (
              SELECT id, branch_id, price_per_night
              FROM hotel_room_types
              WHERE branch_id = :branch_id AND is_active = true
            ),
            calc AS (
              SELECT
                rt.branch_id,
                rt.id AS room_type_id,
                days.d AS date,
                (
                  SELECT count(*)::int
                  FROM hotel_rooms r
                  WHERE r.branch_id = rt.branch_id
                    AND r.room_type_id = rt.id
                    AND r.is_active = true
                ) AS total_rooms,
                (
                  SELECT count(*)::int
                  FROM bookings bk
                  WHERE bk.branch_id = rt.branch_id
                    AND COALESCE((bk.raw_data->>'room_type_id')::int, 0) = rt.id
                    AND bk.reservation_status = 'CONFIRMED'
                    AND bk.stay_id IS NULL
                    AND bk.check_in <= days.d
                    AND bk.check_out > days.d
                ) AS reserved_rooms,
                (
                  SELECT count(DISTINCT hs.room_id)::int
                  FROM hotel_stays hs
                  JOIN hotel_rooms r ON r.id = hs.room_id
                  WHERE hs.branch_id = rt.branch_id
                    AND hs.status = 'ACTIVE'
                    AND r.room_type_id = rt.id
                    AND hs.check_in_at < (days.d + interval '1 day')
                    AND (hs.check_out_at IS NULL OR hs.check_out_at > days.d)
                ) AS sold_rooms,
                (
                  SELECT count(*)::int
                  FROM room_blocks rb
                  JOIN hotel_rooms r ON r.id = rb.room_id
                  WHERE rb.branch_id = rt.branch_id
                    AND r.room_type_id = rt.id
                    AND rb.status = 'ACTIVE'
                    AND rb.start_date <= days.d
                    AND rb.end_date > days.d
                ) AS out_of_order_rooms,
                rt.price_per_night AS base_price
              FROM rt
              CROSS JOIN days
            )
            INSERT INTO room_inventory_daily (
              branch_id, room_type_id, date,
              total_rooms, reserved_rooms, sold_rooms, out_of_order_rooms,
              available_rooms, overbooking_limit, base_price,
              created_at, updated_at
            )
            SELECT
              branch_id,
              room_type_id,
              date,
              total_rooms,
              reserved_rooms,
              sold_rooms,
              out_of_order_rooms,
              GREATEST(total_rooms - reserved_rooms - sold_rooms - out_of_order_rooms, 0),
              0,
              base_price,
              now(),
              now()
            FROM calc
            ON CONFLICT (branch_id, room_type_id, date)
            DO UPDATE SET
              total_rooms = EXCLUDED.total_rooms,
              reserved_rooms = EXCLUDED.reserved_rooms,
              sold_rooms = EXCLUDED.sold_rooms,
              out_of_order_rooms = EXCLUDED.out_of_order_rooms,
              available_rooms = EXCLUDED.available_rooms,
              base_price = EXCLUDED.base_price,
              updated_at = now()
            """
        ),
        {"branch_id": branch_id},
    )

    conn.execute(
        text(
            """
            INSERT INTO room_inventory_logs (
              branch_id, room_type_id, date,
              change_type, delta, field_changed,
              ref_type, ref_id, note
            )
            SELECT
              rb.branch_id,
              r.room_type_id,
              rb.start_date,
              'BLOCK_ROOM',
              1,
              'out_of_order_rooms',
              'room_block',
              rb.id,
              'Seed test block B17'
            FROM room_blocks rb
            JOIN hotel_rooms r ON r.id = rb.room_id
            WHERE rb.branch_id = :branch_id
              AND rb.reason = 'Seed test: bảo trì phòng B17'
              AND NOT EXISTS (
                SELECT 1
                FROM room_inventory_logs l
                WHERE l.ref_type = 'room_block'
                  AND l.ref_id = rb.id
                  AND l.change_type = 'BLOCK_ROOM'
              )
            """
        ),
        {"branch_id": branch_id},
    )


def verify(conn: Connection) -> None:
    rows = conn.execute(
        text(
            """
            SELECT
              (SELECT count(*) FROM hotel_room_types rt JOIN branches b ON b.id = rt.branch_id WHERE b.branch_code = 'B17') AS room_types,
              (SELECT count(*) FROM hotel_rooms r JOIN branches b ON b.id = r.branch_id WHERE b.branch_code = 'B17') AS rooms,
              (SELECT count(*) FROM bookings bk JOIN branches b ON b.id = bk.branch_id WHERE b.branch_code = 'B17') AS bookings,
              (SELECT count(*) FROM room_inventory_daily inv JOIN branches b ON b.id = inv.branch_id WHERE b.branch_code = 'B17') AS inventory_days,
              (SELECT count(*) FROM room_blocks rb JOIN branches b ON b.id = rb.branch_id WHERE b.branch_code = 'B17') AS blocks
            """
        )
    ).mappings().first()
    print("Done. B17 summary:")
    print(f"  room_types    : {rows['room_types']}")
    print(f"  rooms         : {rows['rooms']}")
    print(f"  bookings      : {rows['bookings']}")
    print(f"  inventory rows: {rows['inventory_days']}")
    print(f"  room blocks   : {rows['blocks']}")


def main() -> int:
    database_url = load_database_url()
    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.begin() as conn:
        print("Applying Reservation Hub schema...")
        apply_schema(conn)
        print("Seeding B17 data...")
        seed_b17(conn)
        verify(conn)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
