from app.db.session import SessionLocal
from app.db.models import Warehouse, Branch, InventoryTransfer

db = SessionLocal()
try:
    print("--- BRANCHES ---")
    branches = db.query(Branch).all()
    for b in branches:
        print(f"ID: {b.id}, Code: {b.branch_code}, Name: {b.name}")

    print("\n--- WAREHOUSES ---")
    warehouses = db.query(Warehouse).all()
    for w in warehouses:
        print(f"ID: {w.id}, Name: {w.name}, BranchID: {w.branch_id}, Type: {w.type}")

    print("\n--- RECENT REQUESTS ---")
    reqs = db.query(InventoryTransfer).order_by(InventoryTransfer.id.desc()).limit(5).all()
    for r in reqs:
        print(f"ID: {r.id}, Code: {r.code}, DestWhID: {r.dest_warehouse_id}, SourceWhID: {r.source_warehouse_id}")

except Exception as e:
    print(e)
finally:
    db.close()
