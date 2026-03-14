from app.db.session import SessionLocal
from app.db.models import Booking, Branch
from sqlalchemy import func, or_

db = SessionLocal()

# Test the query that Lễ tân runs
branch_name = "B8"
booking_q = db.query(Booking).join(Branch, Booking.branch_id == Branch.id).filter(
    or_(Branch.name.ilike(branch_name), Branch.branch_code.ilike(branch_name))
)
print("B8 stats:", booking_q.count())

