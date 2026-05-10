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


if __name__ == "__main__":
    unittest.main()
