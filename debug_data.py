from app.db.session import SessionLocal
from app.db.models import Product, ProductCategory

db = SessionLocal()
try:
    products = db.query(Product).all()
    print(f"Total Products: {len(products)}")
    for p in products:
        cat_name = p.category.name if p.category else "None"
        print(f"Product: {p.name}, Category ID: {p.category_id}, Category Name: {cat_name}")

    categories = db.query(ProductCategory).all()
    print(f"Total Categories: {len(categories)}")
    for c in categories:
        print(f"Category: {c.id} - {c.name}")
except Exception as e:
    print(e)
finally:
    db.close()
