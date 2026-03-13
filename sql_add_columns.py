import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app.db.session import engine
from sqlalchemy import text

with engine.begin() as conn:
    try:
        conn.execute(text("ALTER TABLE hotel_room_types ADD COLUMN price_next_hour NUMERIC(15, 2) DEFAULT 0 NOT NULL;"))
        print("Added price_next_hour")
    except Exception as e:
        print("Error price_next_hour:", e)

    try:
        conn.execute(text("ALTER TABLE hotel_room_types ADD COLUMN promo_start_time TIME;"))
        print("Added promo_start_time")
    except Exception as e:
        print("Error promo_start_time:", e)

    try:
        conn.execute(text("ALTER TABLE hotel_room_types ADD COLUMN promo_end_time TIME;"))
        print("Added promo_end_time")
    except Exception as e:
        print("Error promo_end_time:", e)

    try:
        conn.execute(text("ALTER TABLE hotel_room_types ADD COLUMN promo_discount_percent FLOAT DEFAULT 0 NOT NULL;"))
        print("Added promo_discount_percent")
    except Exception as e:
        print("Error promo_discount_percent:", e)

print("Done")
