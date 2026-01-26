
import sys
import os
import unicodedata
import re

# Thêm đường dẫn root vào sys.path để import được app
sys.path.append(os.getcwd())

from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.models import ProductCategory, Product

def slugify(text):
    """
    Chuyển đổi tên thành mã code không dấu, viết hoa, nối bằng gạch dưới.
    Ví dụ: "Hủ tiếu" -> "HU_TIEU"
    """
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = text.upper()
    text = re.sub(r'[^A-Z0-9]+', '_', text)
    return text.strip('_')

# Dữ liệu cần nhập nè
DATA = [
    {
        "name": "Thực phẩm ăn liền", "code": "TPAL",
        "items": [
            ("Hủ tiếu", "Gói"),
            ("Mì ly Modern", "Ly"),
            ("Mì ly Hảo Hảo", "Ly"),
        ]
    },
    {
        "name": "Nước uống – Giải khát", "code": "NUGK",
        "items": [
             ("Aquafina 500ml", "Chai"),
             ("La Vie 500ml", "Chai"),
             ("Coca Cola", "Lon"),
             ("Revive", "Chai"),
             ("Sting", "Chai"),
             ("Trà Bí Đao", "Lon"),
             ("Trà Ô Long", "Chai"),
             ("Trà Lipton", "Gói"), 
             ("Nước Yến", "Lon"),
             ("Bò Húc (Red Bull)", "Lon"),
        ]
    },
    {
        "name": "Đồ uống có cồn", "code": "DUCC",
        "items": [
            ("Bia Heineken", "Lon"),
            ("Bia Tiger", "Lon"),
        ]
    },
    {
        "name": "Đồ uống nóng", "code": "DUN",
        "items": [
            ("Cafe", "Gói"),
        ]
    },
    {
        "name": "Bánh kẹo – Quầy lễ tân", "code": "BKLT",
        "items": [
            ("Kẹo (quầy LT)", "Cái"),
        ]
    },
    {
        "name": "Đồ dùng cá nhân (Amenity)", "code": "AMENITY",
        "items": [
            ("Bao cao su", "Cái"),
            ("Dao cạo râu", "Cái"),
            ("Lược", "Cái"),
            ("Bàn chải đánh răng", "Cái"),
            ("Sữa tắm", "Tuýp"),
            ("Dầu gội", "Tuýp"),
            ("Dép", "Đôi"),
        ]
    },
    {
        "name": "Vật tư điện – tiêu hao", "code": "VTDT",
        "items": [
            ("Pin tiểu 3A", "Viên"),
            ("Pin đại 2A", "Viên"),
        ]
    },
    {
        "name": "Vệ sinh – Tẩy rửa – Côn trùng", "code": "VSTT",
        "items": [
            ("Túi rác", "Cuộn"),
            ("Giấy vệ sinh", "Cuộn"),
            ("Tẩy toilet", "Chai"),
            ("Bột giặt", "Gói"),
            ("Nhang muỗi", "Hộp"),
            ("Xịt muỗi", "Chai"),
            ("Xịt phòng", "Chai"),
            ("Sáp thơm", "Hộp"),
        ]
    },
    {
        "name": "Đồ vải – Linen khách sạn", "code": "LINEN",
        "items": [
            ("Mền 1m8", "Cái"),
            ("Ga 1m8", "Cái"),
            ("Ga 1m6", "Cái"),
            ("Ga 1m4", "Cái"),
            ("Khăn tắm", "Cái"),
            ("Khăn mặt", "Cái"),
        ]
    },
    {
        "name": "Thiết bị điện – gia dụng phòng", "code": "TBPT_DIEN",
        "items": [
            ("Ấm đun siêu tốc", "Cái"),
            ("Máy sấy tóc", "Cái"),
        ]
    },
    {
        "name": "Thiết bị phòng tắm – nước", "code": "TBPT_NUOC",
        "items": [
            ("Dây vòi sen", "Cái"),
            ("Vòi sen", "Cái"),
            ("Vòi sen B15 – B16", "Cái"),
            ("Dây vòi xịt", "Cái"),
            ("Vòi xịt", "Cái"),
            ("Vòi xịt kèm dây", "Bộ"),
            ("Đầu vòi xịt inox 304", "Cái"),
            ("Dây vòi xịt inox 304", "Cái"),
        ]
    },
    {
        "name": "Dụng cụ nhà hàng – bếp", "code": "DCNB",
        "items": [
            ("Bộ tô chén dĩa khách sạn", "Bộ"),
        ]
    }
]

def seed_data():
    db = SessionLocal()
    try:
        print("--- BẮT ĐẦU KHỞI TẠO DỮ LIỆU ---")
        
        for cat_data in DATA:
            # 1. Tạo hoặc lấy Category
            cat_code = cat_data["code"]
            cat_name = cat_data["name"]
            
            category = db.query(ProductCategory).filter(ProductCategory.code == cat_code).first()
            if not category:
                category = ProductCategory(name=cat_name, code=cat_code)
                db.add(category)
                db.commit()
                db.refresh(category)
                print(f"[NEW CAT] {cat_name} ({cat_code})")
            else:
                print(f"[EXIST CAT] {cat_name}")
            
            # 2. Tạo Product
            for prod_name, unit in cat_data["items"]:
                # Tạo code cho sản phẩm: CAT_PROD
                prod_slug = slugify(prod_name)
                prod_code = f"{cat_code}_{prod_slug}"
                
                # Check exist
                product = db.query(Product).filter(Product.code == prod_code).first()
                if not product:
                    product = Product(
                        category_id=category.id,
                        code=prod_code,
                        name=prod_name,
                        base_unit=unit,
                        # packing_unit=None, # Mặc định null
                        # conversion_rate=1, # Mặc định 1
                        min_stock_global=5,
                        cost_price=0
                    )
                    db.add(product)
                    db.commit()
                    print(f"  + [NEW PROD] {prod_name} ({prod_code}) - {unit}")
                else:
                    # Cập nhật unit nếu cần (optional) bên dưới
                    print(f"  . [EXIST PROD] {prod_name}")
                    
        print("--- HOÀN TẤT ---")
        
    except Exception as e:
        print(f"LỖI: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_data()
