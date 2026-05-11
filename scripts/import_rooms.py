"""
Import script: Tạo HotelRoomType + HotelRoom từ dữ liệu danh sách phòng và giá phòng.
Chạy: python -m scripts.import_rooms
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.db.models import Branch, HotelRoomType, HotelRoom
from decimal import Decimal

# === DATA: Danh sách phòng theo chi nhánh ===
ROOM_DATA = {
    "B1": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["101", "102", "104", "201", "202", "204", "301", "303"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["103", "105", "203", "205", "302", "304"]},
    ],
    "B2": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["102", "104", "202", "204", "303", "304", "G01", "G04"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["302", "G02", "G03"]},
        {"loai_phong": "Twin", "danh_sach_phong": ["101", "103", "201", "203", "301"]},
    ],
    "B3": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["101", "202", "B01", "B02"]},
        {"loai_phong": "Suite Flexible", "danh_sach_phong": ["201", "301", "401"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["102", "203", "502", "G01"]},
        {"loai_phong": "Twin Flexible", "danh_sach_phong": ["302", "402", "501"]},
    ],
    "B5": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["101", "201", "301"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["102", "103", "104", "202", "203", "204", "205", "302", "303", "304", "305", "401", "402", "G01", "G02", "G03"]},
        {"loai_phong": "Twin", "danh_sach_phong": ["105", "206", "306", "G04"]},
    ],
    "B6": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["M01", "M02"]},
        {"loai_phong": "Deluxe Flexible", "danh_sach_phong": ["403"]},
        {"loai_phong": "Suite", "danh_sach_phong": ["401"]},
        {"loai_phong": "Suite Flexible", "danh_sach_phong": ["101"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["102", "202", "302", "402", "G01"]},
        {"loai_phong": "Twin", "danh_sach_phong": ["103", "201", "203", "301", "303"]},
    ],
    "B7": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["202", "302", "402"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["102", "104", "203", "204", "303", "304", "403", "404"]},
        {"loai_phong": "Twin", "danh_sach_phong": ["101", "103", "201", "301", "401", "501"]},
    ],
    "B8": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["101", "201", "202", "204", "301", "302", "304"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["102", "104", "105", "402", "403", "404", "501"]},
        {"loai_phong": "Twin", "danh_sach_phong": ["103", "203", "303", "401"]},
    ],
    "B9": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["101", "102", "201", "202", "301", "302", "401", "402"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["103", "104", "105", "203", "303", "403"]},
        {"loai_phong": "Twin", "danh_sach_phong": ["204", "304", "404"]},
    ],
    "B10": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["202", "304", "404", "504", "604", "704", "804"]},
        {"loai_phong": "Suite", "danh_sach_phong": ["301", "401", "501"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["302", "303", "402", "403", "502", "503", "603", "703", "803"]},
        {"loai_phong": "Twin", "danh_sach_phong": ["601", "701", "801"]},
    ],
    "B11": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["105", "106", "204", "301", "304", "401", "404", "501", "504"]},
        {"loai_phong": "Deluxe Flexible", "danh_sach_phong": ["103"]},
        {"loai_phong": "Suite", "danh_sach_phong": ["203", "205", "303", "305", "403", "405", "503", "505"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["104", "107", "201"]},
        {"loai_phong": "Twin", "danh_sach_phong": ["101", "102", "202", "302", "402", "502"]},
    ],
    "B12": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["204", "205", "304", "305", "403", "404"]},
        {"loai_phong": "Deluxe Flexible", "danh_sach_phong": ["103", "104"]},
        {"loai_phong": "Suite", "danh_sach_phong": ["201", "202", "301", "302", "401"]},
        {"loai_phong": "Suite Flexible", "danh_sach_phong": ["101", "402"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["203", "303"]},
        {"loai_phong": "Twin", "danh_sach_phong": ["102"]},
    ],
    "B14": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["102", "105", "106", "204", "304", "404"]},
        {"loai_phong": "Suite Flexible", "danh_sach_phong": ["202", "205", "302", "305", "402", "405"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["103", "104", "203", "303", "403"]},
        {"loai_phong": "Twin", "danh_sach_phong": ["101", "201", "301", "401"]},
    ],
    "B15": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["101", "103", "201", "203", "204", "205"]},
        {"loai_phong": "Suite", "danh_sach_phong": ["301", "401", "501", "502"]},
        {"loai_phong": "Suite Flexible", "danh_sach_phong": ["102", "303", "403", "503", "504"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["104", "105", "106"]},
        {"loai_phong": "Twin", "danh_sach_phong": ["202", "302", "304", "402", "404"]},
    ],
    "B16": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["101", "201", "503", "601"]},
        {"loai_phong": "Suite", "danh_sach_phong": ["301", "401", "501"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["202", "302", "402", "502"]},
        {"loai_phong": "Twin", "danh_sach_phong": ["102", "203", "303", "403"]},
    ],
    "B17": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["106", "108", "401", "402"]},
        {"loai_phong": "Deluxe Flexible", "danh_sach_phong": ["101"]},
        {"loai_phong": "Suite", "danh_sach_phong": ["201", "202", "205", "206", "301", "302", "305", "306", "403", "404"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["103", "104", "203", "303"]},
        {"loai_phong": "Twin", "danh_sach_phong": ["102", "105", "107", "204", "304"]},
    ],
    "B18": [
        {"loai_phong": "Deluxe", "danh_sach_phong": ["102", "103", "104", "204", "205", "305", "405", "505", "605"]},
        {"loai_phong": "Deluxe Flexible", "danh_sach_phong": ["304", "404", "504", "604"]},
        {"loai_phong": "Suite", "danh_sach_phong": ["101", "201", "202"]},
        {"loai_phong": "Suite Flexible", "danh_sach_phong": ["301", "401", "501", "601"]},
        {"loai_phong": "Superior", "danh_sach_phong": ["203", "303", "403", "503", "603"]},
        {"loai_phong": "Twin", "danh_sach_phong": ["302", "402", "502", "602"]},
    ],
}

# === DATA: Giá phòng theo chi nhánh ===
# Flexible rooms kế thừa giá từ phòng gốc (Suite Flexible = Suite, Deluxe Flexible = Deluxe, Twin Flexible = Twin)
PRICE_DATA = {
    "B1": [
        {"type": "Superior", "day": 500000, "hour": 200000, "next_hour": 50000},
        {"type": "Deluxe", "day": 550000, "hour": 250000, "next_hour": 50000},
    ],
    "B2": [
        {"type": "Superior", "day": 550000, "hour": 200000, "next_hour": 50000},
        {"type": "Deluxe", "day": 600000, "hour": 250000, "next_hour": 50000},
        {"type": "Twin", "day": 700000, "hour": 250000, "next_hour": 50000},
    ],
    "B3": [
        {"type": "Superior", "day": 550000, "hour": 250000, "next_hour": 50000},
        {"type": "Deluxe", "day": 650000, "hour": 250000, "next_hour": 50000},
        {"type": "Suite", "day": 750000, "hour": 300000, "next_hour": 50000},
        {"type": "Twin", "day": 850000, "hour": 300000, "next_hour": 50000},
    ],
    "B5": [
        {"type": "Superior", "day": 550000, "hour": 200000, "next_hour": 50000},
        {"type": "Deluxe", "day": 600000, "hour": 250000, "next_hour": 50000},
        {"type": "Twin", "day": 700000, "hour": 250000, "next_hour": 50000},
    ],
    "B6": [
        {"type": "Superior", "day": 550000, "hour": 250000, "next_hour": 50000},
        {"type": "Deluxe", "day": 650000, "hour": 250000, "next_hour": 50000},
        {"type": "Suite", "day": 750000, "hour": 300000, "next_hour": 50000},
        {"type": "Twin", "day": 850000, "hour": 300000, "next_hour": 50000},
    ],
    "B7": [
        {"type": "Superior", "day": 650000, "hour": 250000, "next_hour": 50000},
        {"type": "Deluxe", "day": 750000, "hour": 300000, "next_hour": 50000},
        {"type": "Twin", "day": 850000, "hour": 300000, "next_hour": 50000},
    ],
    "B8": [
        {"type": "Superior", "day": 650000, "hour": 250000, "next_hour": 50000},
        {"type": "Deluxe", "day": 750000, "hour": 250000, "next_hour": 50000},
        {"type": "Twin", "day": 850000, "hour": 250000, "next_hour": 50000},
    ],
    "B9": [
        {"type": "Superior", "day": 650000, "hour": 250000, "next_hour": 50000},
        {"type": "Deluxe", "day": 750000, "hour": 250000, "next_hour": 50000},
        {"type": "Twin", "day": 850000, "hour": 250000, "next_hour": 50000},
    ],
    "B10": [
        {"type": "Superior", "day": 550000, "hour": 150000, "next_hour": 50000},
        {"type": "Deluxe", "day": 600000, "hour": 200000, "next_hour": 50000},
        {"type": "Suite", "day": 700000, "hour": 250000, "next_hour": 50000},
        {"type": "Twin", "day": 1000000, "hour": 300000, "next_hour": 100000},
    ],
    "B11": [
        {"type": "Superior", "day": 550000, "hour": 200000, "next_hour": 50000},
        {"type": "Deluxe", "day": 650000, "hour": 250000, "next_hour": 50000},
        {"type": "Suite", "day": 750000, "hour": 300000, "next_hour": 50000},
        {"type": "Twin", "day": 850000, "hour": 300000, "next_hour": 50000},
    ],
    "B12": [
        {"type": "Superior", "day": 550000, "hour": 200000, "next_hour": 50000},
        {"type": "Deluxe", "day": 650000, "hour": 250000, "next_hour": 50000},
        {"type": "Suite", "day": 750000, "hour": 300000, "next_hour": 50000},
        {"type": "Twin", "day": 850000, "hour": 300000, "next_hour": 50000},
    ],
    "B14": [
        {"type": "Superior", "day": 650000, "hour": 250000, "next_hour": 50000},
        {"type": "Deluxe", "day": 750000, "hour": 250000, "next_hour": 50000},
        {"type": "Suite", "day": 750000, "hour": 250000, "next_hour": 50000},
        {"type": "Twin", "day": 850000, "hour": 250000, "next_hour": 50000},
    ],
    "B15": [
        {"type": "Superior", "day": 550000, "hour": 200000, "next_hour": 50000},
        {"type": "Deluxe", "day": 650000, "hour": 250000, "next_hour": 50000},
        {"type": "Suite", "day": 750000, "hour": 300000, "next_hour": 50000},
        {"type": "Twin", "day": 850000, "hour": 300000, "next_hour": 50000},
    ],
    "B16": [
        {"type": "Superior", "day": 550000, "hour": 200000, "next_hour": 50000},
        {"type": "Deluxe", "day": 650000, "hour": 250000, "next_hour": 50000},
        {"type": "Suite", "day": 750000, "hour": 300000, "next_hour": 50000},
        {"type": "Twin", "day": 850000, "hour": 300000, "next_hour": 50000},
    ],
    "B17": [
        {"type": "Superior", "day": 550000, "hour": 200000, "next_hour": 50000},
        {"type": "Deluxe", "day": 650000, "hour": 250000, "next_hour": 50000},
        {"type": "Suite", "day": 750000, "hour": 300000, "next_hour": 50000},
        {"type": "Twin", "day": 850000, "hour": 300000, "next_hour": 50000},
    ],
    "B18": [
        {"type": "Superior", "day": 550000, "hour": 200000, "next_hour": 50000},
        {"type": "Deluxe", "day": 650000, "hour": 250000, "next_hour": 50000},
        {"type": "Suite", "day": 750000, "hour": 300000, "next_hour": 50000},
        {"type": "Twin", "day": 850000, "hour": 300000, "next_hour": 50000},
    ],
}

# Flexible room → base room mapping (kế thừa giá)
FLEXIBLE_BASE = {
    "Suite Flexible": "Suite",
    "Deluxe Flexible": "Deluxe",
    "Twin Flexible": "Twin",
}

SORT_ORDER = {
    "Superior": 1,
    "Deluxe": 2,
    "Deluxe Flexible": 3,
    "Suite": 4,
    "Suite Flexible": 5,
    "Twin": 6,
    "Twin Flexible": 7,
}


def get_price(branch_code: str, room_type_name: str) -> dict:
    base_name = FLEXIBLE_BASE.get(room_type_name, room_type_name)
    prices = PRICE_DATA.get(branch_code, [])
    for p in prices:
        if p["type"] == base_name:
            return p
    return {"day": 0, "hour": 0, "next_hour": 0}


def get_floor(room_number: str) -> int:
    if room_number.startswith(("G", "g")):
        return 0
    if room_number.startswith(("B", "b", "M", "m")):
        return -1
    digits = "".join(c for c in room_number if c.isdigit())
    if len(digits) >= 2:
        return int(digits[0])
    return 1


def run_import():
    db = SessionLocal()
    try:
        branches = {b.branch_code: b for b in db.query(Branch).all()}
        total_types = 0
        total_rooms = 0

        for branch_code, room_list in ROOM_DATA.items():
            branch = branches.get(branch_code)
            if not branch:
                print(f"⚠️  Branch {branch_code} không tồn tại trong DB — bỏ qua")
                continue

            print(f"\n{'='*50}")
            print(f"Chi nhánh: {branch.name} ({branch_code}) — id={branch.id}")
            print(f"{'='*50}")

            for entry in room_list:
                room_type_name = entry["loai_phong"]
                rooms = entry["danh_sach_phong"]
                price = get_price(branch_code, room_type_name)

                # Upsert room type
                existing_type = db.query(HotelRoomType).filter(
                    HotelRoomType.branch_id == branch.id,
                    HotelRoomType.name == room_type_name,
                ).first()

                if existing_type:
                    existing_type.price_per_night = Decimal(str(price["day"]))
                    existing_type.price_per_hour = Decimal(str(price["hour"]))
                    existing_type.price_next_hour = Decimal(str(price["next_hour"]))
                    existing_type.sort_order = SORT_ORDER.get(room_type_name, 10)
                    existing_type.is_active = True
                    rt = existing_type
                    print(f"  ✏️  Update: {room_type_name} — {price['day']:,.0f}₫/đêm")
                else:
                    rt = HotelRoomType(
                        branch_id=branch.id,
                        name=room_type_name,
                        price_per_night=Decimal(str(price["day"])),
                        price_per_hour=Decimal(str(price["hour"])),
                        price_next_hour=Decimal(str(price["next_hour"])),
                        max_guests=2,
                        min_hours=1,
                        sort_order=SORT_ORDER.get(room_type_name, 10),
                        is_active=True,
                    )
                    db.add(rt)
                    db.flush()
                    total_types += 1
                    print(f"  ✅ Tạo mới: {room_type_name} — {price['day']:,.0f}₫/đêm")

                # Upsert rooms
                for room_number in rooms:
                    existing_room = db.query(HotelRoom).filter(
                        HotelRoom.branch_id == branch.id,
                        HotelRoom.room_number == room_number,
                    ).first()

                    if existing_room:
                        existing_room.room_type_id = rt.id
                        existing_room.is_active = True
                    else:
                        db.add(HotelRoom(
                            branch_id=branch.id,
                            room_type_id=rt.id,
                            floor=get_floor(room_number),
                            room_number=room_number,
                            is_active=True,
                        ))
                        total_rooms += 1

                print(f"       Phòng: {', '.join(rooms)} ({len(rooms)} phòng)")

        db.commit()
        print(f"\n{'='*50}")
        print(f"HOÀN TẤT: Tạo {total_types} loại phòng mới, {total_rooms} phòng mới")
        print(f"{'='*50}")

    except Exception as e:
        db.rollback()
        print(f"❌ Lỗi: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_import()
