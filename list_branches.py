from app.db.session import SessionLocal
from app.db.models import Branch

db = SessionLocal()
branches = db.query(Branch).order_by(Branch.id).all()
print(f"{'ID':<5} {'Code':<10} {'Name'}")
print("-" * 30)
for b in branches:
    print(f"{b.id:<5} {b.branch_code:<10} {b.name}")
db.close()
