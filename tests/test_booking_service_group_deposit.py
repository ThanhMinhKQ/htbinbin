import unittest
from datetime import date
from types import SimpleNamespace

from app.services.booking_service import BookingService


class QueryStub:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class DbStub:
    def __init__(self, query_rows):
        self.query_rows = list(query_rows)
        self.added = []
        self.flushed = 0

    def query(self, *args, **kwargs):
        return QueryStub(self.query_rows.pop(0))

    def add(self, item):
        item.id = len(self.added) + 1
        self.added.append(item)

    def flush(self):
        self.flushed += 1


class InventoryStub:
    def reserve_booking(self, *args, **kwargs):
        return None


class RecordingInventoryStub:
    def __init__(self):
        self.releases = []
        self.reserves = []

    def release_booking(self, *args, **kwargs):
        self.releases.append(args)

    def reserve_booking(self, *args, **kwargs):
        self.reserves.append(args)


class BookingServiceGroupDepositTest(unittest.TestCase):
    def test_group_reservation_uses_single_room_deposit_allocation(self):
        room_type = SimpleNamespace(id=11, branch_id=1, name="Deluxe")
        db = DbStub([[room_type], [room_type], [room_type]])
        service = BookingService(db)
        service.inventory = InventoryStub()
        service._post_booking_deposit_once = lambda *args, **kwargs: None

        bookings = service.create_group_reservation({
            "branch_id": 1,
            "booking_type": "DIRECT",
            "reservation_status": "PENDING",
            "guest_name": "Nguyen Van A",
            "check_in": date(2026, 5, 6),
            "check_out": date(2026, 5, 7),
            "total_price": 1_000_000,
            "deposit_amount": 300_000,
            "room_items": [{
                "room_type_id": 11,
                "quantity": 2,
                "unit_total": 500_000,
                "reference_unit_total": 500_000,
            }],
            "raw_data": {
                "deposit_allocation": {
                    "mode": "single",
                    "target_key": "11:2",
                    "items": [
                        {"room_type_id": 11, "room_type_index": 1, "amount": 0},
                        {"room_type_id": 11, "room_type_index": 2, "amount": 300_000},
                    ],
                }
            },
        }, user_id=9)

        self.assertEqual(len(bookings), 2)
        self.assertEqual(float(bookings[0].deposit_amount), 0)
        self.assertEqual(float(bookings[1].deposit_amount), 300_000)

    def test_group_reservation_keeps_equal_deposit_split_without_allocation(self):
        room_type = SimpleNamespace(id=11, branch_id=1, name="Deluxe")
        db = DbStub([[room_type], [room_type], [room_type]])
        service = BookingService(db)
        service.inventory = InventoryStub()
        service._post_booking_deposit_once = lambda *args, **kwargs: None

        bookings = service.create_group_reservation({
            "branch_id": 1,
            "booking_type": "DIRECT",
            "reservation_status": "PENDING",
            "guest_name": "Nguyen Van A",
            "check_in": date(2026, 5, 6),
            "check_out": date(2026, 5, 7),
            "total_price": 1_000_000,
            "deposit_amount": 300_000,
            "room_items": [{
                "room_type_id": 11,
                "quantity": 2,
                "unit_total": 500_000,
                "reference_unit_total": 500_000,
            }],
            "raw_data": {},
        }, user_id=9)

        self.assertEqual(len(bookings), 2)
        self.assertEqual(float(bookings[0].deposit_amount), 150_000)
        self.assertEqual(float(bookings[1].deposit_amount), 150_000)
    def test_group_reservation_uses_manual_split_deposit_allocation(self):
        room_type = SimpleNamespace(id=11, branch_id=1, name="Deluxe")
        db = DbStub([[room_type], [room_type], [room_type]])
        service = BookingService(db)
        service.inventory = InventoryStub()
        service._post_booking_deposit_once = lambda *args, **kwargs: None

        bookings = service.create_group_reservation({
            "branch_id": 1,
            "booking_type": "DIRECT",
            "reservation_status": "PENDING",
            "guest_name": "Nguyen Van A",
            "check_in": date(2026, 5, 6),
            "check_out": date(2026, 5, 7),
            "total_price": 1_000_000,
            "deposit_amount": 1_000_000,
            "room_items": [{
                "room_type_id": 11,
                "quantity": 2,
                "unit_total": 500_000,
                "reference_unit_total": 500_000,
            }],
            "raw_data": {
                "deposit_allocation": {
                    "mode": "split",
                    "items": [
                        {"room_type_id": 11, "room_type_index": 1, "amount": 300_000},
                        {"room_type_id": 11, "room_type_index": 2, "amount": 700_000},
                    ],
                }
            },
        }, user_id=9)

        self.assertEqual(len(bookings), 2)
        self.assertEqual(float(bookings[0].deposit_amount), 300_000)
        self.assertEqual(float(bookings[1].deposit_amount), 700_000)

    def test_single_room_group_reservation_honors_manual_total_override(self):
        room_type = SimpleNamespace(id=11, branch_id=1, name="Deluxe")
        db = DbStub([[room_type], [room_type]])
        service = BookingService(db)
        service.inventory = InventoryStub()
        service._post_booking_deposit_once = lambda *args, **kwargs: None

        bookings = service.create_group_reservation({
            "branch_id": 1,
            "booking_type": "DIRECT",
            "reservation_status": "PENDING",
            "guest_name": "Nguyen Van A",
            "check_in": date(2026, 5, 6),
            "check_out": date(2026, 5, 7),
            "total_price": 450_000,
            "deposit_amount": 100_000,
            "room_items": [{
                "room_type_id": 11,
                "quantity": 1,
                "unit_total": 500_000,
                "reference_unit_total": 500_000,
            }],
            "raw_data": {
                "manual_total_override": True,
                "manual_total_price": 450_000,
                "manual_total_reference": 500_000,
                "manual_total_delta": -50_000,
            },
        }, user_id=9)

        self.assertEqual(len(bookings), 1)
        self.assertEqual(float(bookings[0].total_price), 450_000)
        self.assertEqual(float(bookings[0].deposit_amount), 100_000)
        self.assertTrue(bookings[0].raw_data["manual_total_override"])

    def test_update_confirmed_reservation_keeps_reserved_room_type_in_sync(self):
        booking = SimpleNamespace(
            id=206,
            branch_id=15,
            reservation_status="CONFIRMED",
            status=None,
            raw_data={
                "room_type_id": 57,
                "reservation_inventory_reserved": True,
                "reservation_reserved_room_type_id": 56,
                "reservation_reserved_check_in": "2026-05-23",
                "reservation_reserved_check_out": "2026-05-24",
                "reservation_reserved_qty": 1,
            },
            room_type="Deluxe",
            assigned_room_id=None,
            assigned_room=None,
            check_in=date(2026, 5, 23),
            check_out=date(2026, 5, 24),
            guest_name="Nguyen Van A",
            guest_phone=None,
            booking_type="DIRECT",
            booking_source="Direct",
            external_id="B17-001",
            num_guests=1,
            num_adults=1,
            num_children=0,
            total_price=900_000,
            deposit_amount=0,
            payment_method=None,
            special_requests=None,
            internal_notes=None,
            estimated_arrival=None,
            guest_id=123,
            confirmed_at=object(),
            updated_by=None,
            updated_at=None,
        )
        room_type = SimpleNamespace(id=57, branch_id=15, name="Deluxe Flexible")
        db = DbStub([[booking], [room_type]])
        service = BookingService(db)
        inventory = RecordingInventoryStub()
        service.inventory = inventory
        service._log_booking_activity = lambda *args, **kwargs: None
        service._post_booking_deposit_once = lambda *args, **kwargs: None

        service.update_reservation(206, {
            "room_type_id": 57,
            "reservation_status": "CONFIRMED",
            "check_in": "2026-05-23",
            "check_out": "2026-05-24",
            "raw_data": {"reservation_reserved_room_type_id": 56},
        }, user_id=9)

        self.assertEqual(booking.raw_data["room_type_id"], 57)
        self.assertEqual(booking.raw_data["reservation_reserved_room_type_id"], 57)
        self.assertEqual(inventory.releases[0][2], 56)
        self.assertEqual(inventory.reserves[0][2], 57)

    def test_multi_room_group_reservation_distributes_manual_total_by_reference(self):
        deluxe = SimpleNamespace(id=11, branch_id=1, name="Deluxe")
        suite = SimpleNamespace(id=12, branch_id=1, name="Suite")
        db = DbStub([[deluxe], [suite], [deluxe], [suite]])
        service = BookingService(db)
        service.inventory = InventoryStub()
        service._post_booking_deposit_once = lambda *args, **kwargs: None

        bookings = service.create_group_reservation({
            "branch_id": 1,
            "booking_type": "DIRECT",
            "reservation_status": "PENDING",
            "guest_name": "Nguyen Van A",
            "check_in": date(2026, 5, 6),
            "check_out": date(2026, 5, 7),
            "total_price": 900_000,
            "deposit_amount": 0,
            "room_items": [
                {
                    "room_type_id": 11,
                    "quantity": 1,
                    "unit_total": 600_000,
                    "reference_unit_total": 600_000,
                },
                {
                    "room_type_id": 12,
                    "quantity": 1,
                    "unit_total": 400_000,
                    "reference_unit_total": 400_000,
                },
            ],
            "raw_data": {
                "manual_total_override": True,
                "manual_total_price": 900_000,
                "manual_total_reference": 1_000_000,
                "manual_total_delta": -100_000,
            },
        }, user_id=9)

        self.assertEqual(len(bookings), 2)
        self.assertEqual(float(bookings[0].total_price), 540_000)
        self.assertEqual(float(bookings[1].total_price), 360_000)
        self.assertEqual(sum(float(b.total_price) for b in bookings), 900_000)
        self.assertEqual(float(bookings[0].raw_data["manual_group_child_total"]), 540_000)


if __name__ == "__main__":
    unittest.main()
