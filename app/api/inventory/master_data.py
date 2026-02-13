from fastapi import APIRouter, Request, Depends, HTTPException, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse
import unicodedata
import re
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, or_
from pydantic import BaseModel, field_validator
from typing import Optional, List
import math

from ...db.session import get_db
from ...db.models import (
    User, Branch, 
    Product, ProductCategory, 
    StockMovement, InventoryLevel,
    Warehouse, InventoryReceipt, InventoryTransfer
)

router = APIRouter()

# ====================================================================
# SCHEMAS (Master Data)
# ====================================================================

class CategorySchema(BaseModel):
    name: str
    code: str

class CategoryUpdateSchema(BaseModel):
    name: str
    code: str

class ProductSchema(BaseModel):
    name: str
    code: Optional[str] = None
    category_id: int
    base_unit: str              
    packing_unit: Optional[str] = None 
    conversion_rate: int = 1    
    min_stock_global: int = 0
    cost_price: float = 0
    is_active: bool = True

class ProductUpdateSchema(ProductSchema):
    pass

class ProductStatusSchema(BaseModel):
    is_active: bool

class WarehouseSchema(BaseModel):
    name: str
    type: str = "BRANCH"
    branch_id: Optional[int] = None

    @field_validator('branch_id', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        if v == "" or v == 0:
            return None
        return v

class WarehouseStatusSchema(BaseModel):
    is_active: bool

class WarehouseReorderSchema(BaseModel):
    ids: List[int]

# ====================================================================
# API: WAREHOUSES
# ====================================================================

@router.get("/warehouses")
async def get_warehouses(db: Session = Depends(get_db)):
    """Lấy danh sách kho"""
    warehouses = db.query(Warehouse).options(joinedload(Warehouse.branch)).order_by(Warehouse.sort_order.asc()).all()
    data = []
    for w in warehouses:
        data.append({
            "id": w.id,
            "name": w.name,
            "type": w.type,
            "branch_id": w.branch_id,
            "branch_name": w.branch.name if w.branch else "Kho Tổng",
            "is_active": w.is_active 
        })
    return data

@router.post("/warehouses")
async def create_warehouse(
    payload: WarehouseSchema,
    request: Request,
    db: Session = Depends(get_db)
):
    """Tạo kho mới"""
    new_wh = Warehouse(
        name=payload.name,
        type=payload.type,
        branch_id=payload.branch_id if payload.type == 'BRANCH' else None,
        is_active=True
    )
    db.add(new_wh)
    db.commit()
    return {"status": "success", "message": "Đã tạo kho thành công", "id": new_wh.id}

@router.put("/warehouses/{warehouse_id}/status")
async def update_warehouse_status(
    warehouse_id: int,
    payload: WarehouseStatusSchema,
    db: Session = Depends(get_db)
):
    """Cập nhật trạng thái Kho (Active/Inactive)"""
    wh = db.query(Warehouse).get(warehouse_id)
    if not wh:
        raise HTTPException(status_code=404, detail="Kho không tồn tại")
    
    wh.is_active = payload.is_active
    db.commit()
    return {"status": "success", "message": "Đã cập nhật trạng thái kho"}

@router.put("/warehouses/reorder")
async def reorder_warehouses(
    payload: WarehouseReorderSchema,
    db: Session = Depends(get_db)
):
    """Cập nhật thứ tự sắp xếp kho"""
    order_map = {id: index for index, id in enumerate(payload.ids)}
    warehouses = db.query(Warehouse).filter(Warehouse.id.in_(payload.ids)).all()
    
    for w in warehouses:
        if w.id in order_map:
            w.sort_order = order_map[w.id]
            
    db.commit()
    return {"status": "success", "message": "Đã cập nhật thứ tự kho"}

@router.delete("/warehouses/{warehouse_id}")
async def delete_warehouse(warehouse_id: int, db: Session = Depends(get_db)):
    """Xóa kho: HARD DELETE (Xóa Vĩnh Viễn kèm dữ liệu liên quan)"""
    wh = db.query(Warehouse).get(warehouse_id)
    if not wh:
        raise HTTPException(status_code=404, detail="Kho không tồn tại")
        
    db.query(InventoryLevel).filter(InventoryLevel.warehouse_id == warehouse_id).delete()
    db.query(StockMovement).filter(StockMovement.warehouse_id == warehouse_id).delete()
    db.query(InventoryReceipt).filter(InventoryReceipt.warehouse_id == warehouse_id).delete()
    db.query(InventoryTransfer).filter(or_(
        InventoryTransfer.source_warehouse_id == warehouse_id,
        InventoryTransfer.dest_warehouse_id == warehouse_id
    )).delete()

    db.delete(wh)
    db.commit()
    return {"status": "success", "message": "Đã xóa vĩnh viễn kho và toàn bộ dữ liệu liên quan."}

# ====================================================================
# API: CATEGORIES
# ====================================================================

@router.get("/categories")
async def get_categories(db: Session = Depends(get_db)):
    """Lấy danh sách danh mục"""
    cats = db.query(ProductCategory).all()
    return [{"id": c.id, "name": c.name, "code": c.code} for c in cats]

@router.post("/categories")
async def create_category(
    payload: CategorySchema, 
    request: Request, 
    db: Session = Depends(get_db)
):
    """Tạo danh mục mới"""
    if db.query(ProductCategory).filter(ProductCategory.code == payload.code).first():
        raise HTTPException(status_code=400, detail="Mã danh mục đã tồn tại")
        
    new_cat = ProductCategory(name=payload.name, code=payload.code)
    db.add(new_cat)
    db.commit()
    return {"status": "success", "id": new_cat.id}

@router.put("/categories/{category_id}")
async def update_category(
    category_id: int,
    payload: CategoryUpdateSchema,
    db: Session = Depends(get_db)
):
    """Cập nhật danh mục"""
    category = db.query(ProductCategory).filter(ProductCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Danh mục không tồn tại")
    
    # Kiểm tra mã danh mục không trùng với danh mục khác
    existing = db.query(ProductCategory).filter(
        ProductCategory.code == payload.code,
        ProductCategory.id != category_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Mã danh mục đã tồn tại")
    
    category.name = payload.name
    category.code = payload.code
    db.commit()
    return {"status": "success", "message": "Cập nhật danh mục thành công"}

@router.delete("/categories/{category_id}")
async def delete_category(category_id: int, db: Session = Depends(get_db)):
    """Xóa danh mục"""
    category = db.query(ProductCategory).filter(ProductCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Danh mục không tồn tại")
    
    # Kiểm tra xem có sản phẩm nào thuộc danh mục này không
    has_products = db.query(Product).filter(Product.category_id == category_id).first()
    if has_products:
        raise HTTPException(
            status_code=400, 
            detail=f"Không thể xóa danh mục '{category.name}' vì đang có sản phẩm thuộc danh mục này"
        )
    
    db.delete(category)
    db.commit()
    return {"status": "success", "message": "Đã xóa danh mục thành công"}


# ====================================================================
# API: PRODUCTS
# ====================================================================

@router.get("/products")
async def get_products(
    request: Request,
    page: int = 1,
    limit: int = 20,
    search: str = None,
    category_id: int = None,
    db: Session = Depends(get_db)
):
    """Lấy danh sách sản phẩm (có tìm kiếm & phân trang)"""
    query = db.query(Product).options(joinedload(Product.category))
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(or_(
            Product.name.ilike(search_term),
            Product.code.ilike(search_term)
        ))
    
    if category_id:
        query = query.filter(Product.category_id == category_id)

    query = query.order_by(Product.category_id, Product.name)
    total = query.count()
    products = query.offset((page - 1) * limit).limit(limit).all()
    
    data = []
    for p in products:
        data.append({
            "id": p.id,
            "code": p.code,
            "name": p.name,
            "category_name": p.category.name if p.category else "N/A",
            "base_unit": p.base_unit,
            "packing_unit": p.packing_unit,
            "conversion_rate": p.conversion_rate,
            "cost_price": float(p.cost_price or 0),
            "is_active": p.is_active
        })

    return {
        "data": data,
        "total": total,
        "page": page,
        "total_pages": math.ceil(total / limit)
    }

@router.post("/products")
async def create_product(
    payload: ProductSchema,
    request: Request, 
    db: Session = Depends(get_db)
):
    """Tạo sản phẩm mới với logic quy đổi"""
    
    # Logic sinh mã tự động nếu không có code
    if not payload.code:
        # 1. Lấy mã danh mục
        category = db.query(ProductCategory).get(payload.category_id)
        if not category:
             raise HTTPException(status_code=400, detail="Danh mục không tồn tại")
        
        # 2. Slugify tên sản phẩm
        def slugify(text):
            text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
            text = text.upper()
            text = re.sub(r'[^A-Z0-9]+', '_', text)
            return text.strip('_')

        slug_name = slugify(payload.name)
        payload.code = f"{category.code}_{slug_name}"

    if db.query(Product).filter(Product.code == payload.code).first():
        raise HTTPException(status_code=400, detail=f"Mã sản phẩm '{payload.code}' đã tồn tại")

    new_product = Product(
        name=payload.name,
        code=payload.code,
        category_id=payload.category_id,
        base_unit=payload.base_unit,
        packing_unit=payload.packing_unit,
        conversion_rate=payload.conversion_rate if payload.conversion_rate > 0 else 1,
        min_stock_global=payload.min_stock_global,
        cost_price=payload.cost_price,
        is_active=payload.is_active
    )
    
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    
    return {"status": "success", "message": "Tạo sản phẩm thành công", "data": {"id": new_product.id, "code": new_product.code}}

@router.put("/products/{product_id}/status")
async def update_product_status(
    product_id: int,
    payload: ProductStatusSchema,
    db: Session = Depends(get_db)
):
    """Cập nhật trạng thái Sản phẩm (Active/Inactive)"""
    product = db.query(Product).get(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại")
    
    product.is_active = payload.is_active
    db.commit()
    return {"status": "success", "message": "Đã cập nhật trạng thái sản phẩm"}

@router.put("/products/{product_id}")
async def update_product(
    product_id: int,
    payload: ProductUpdateSchema,
    db: Session = Depends(get_db)
):
    """Cập nhật thông tin sản phẩm"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Không tìm thấy sản phẩm")

    product.name = payload.name
    product.category_id = payload.category_id
    product.base_unit = payload.base_unit
    product.packing_unit = payload.packing_unit
    product.conversion_rate = payload.conversion_rate
    product.cost_price = payload.cost_price
    product.is_active = payload.is_active
    
    db.commit()
    return {"status": "success", "message": "Cập nhật thành công"}

@router.delete("/products/{product_id}")
async def delete_product(product_id: int, db: Session = Depends(get_db)):
    """Soft Delete (Chỉ tắt kích hoạt)"""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại")
        
    has_trans = db.query(StockMovement).filter(StockMovement.product_id == product_id).first()
    
    if has_trans:
        product.is_active = False
        msg = "Sản phẩm đã phát sinh giao dịch, đã chuyển sang trạng thái Ngưng hoạt động."
    else:
        db.delete(product)
        msg = "Đã xóa sản phẩm hoàn toàn."
        
    db.commit()
    return {"status": "success", "message": msg}
