# app/api/pms/inventory_integration.py
"""
Inventory ↔ PMS Integration API
Bridges the Warehouse Management System with PMS Folio billing.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ...db.models import (
    Branch,
    Folio, FolioStatus,
    FolioTransaction, FolioTransactionType, FolioTransactionCategory,
    HotelStay,
    InventoryLevel, 
    Product, ProductCategory,
    StockMovement, TransactionTypeWMS,
    Warehouse,
)
from ...db.session import get_db
from ...services.folio_service import create_charge_transaction, rebalance_folio
from ...services.pricing_service import money
from .pms_helpers import _require_login, _active_branch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pms/inventory", tags=["PMS Inventory"])


# ─────────────────────────── Helpers ──────────────────────────────

def _get_branch_warehouse(db: Session, branch_id: int) -> Optional[Warehouse]:
    """Get the warehouse associated with a branch."""
    return db.query(Warehouse).filter(
        Warehouse.branch_id == branch_id,
        Warehouse.is_active == True,
    ).first()


def _get_branch_from_request(request: Request, db: Session) -> Optional[Branch]:
    """Resolve current branch from session/user context."""
    branch_code = _active_branch(request)
    if not branch_code or branch_code in ("HỆ THỐNG", "Chưa phân bổ"):
        return None
    return db.query(Branch).filter(Branch.branch_code == branch_code).first()


# ─────────────────────────── GET Products ──────────────────────────

@router.get("/products")
async def get_sellable_products(
    request: Request,
    branch_id: Optional[int] = Query(default=None),
    category_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Lấy danh sách sản phẩm có thể bán (is_sellable=True) kèm tồn kho chi nhánh.
    """
    user = _require_login(request)

    # Resolve branch
    if not branch_id:
        branch = _get_branch_from_request(request, db)
        if branch:
            branch_id = branch.id

    # Get warehouse for this branch
    warehouse = None
    if branch_id:
        warehouse = _get_branch_warehouse(db, branch_id)

    # Query sellable products
    q = db.query(Product).filter(
        Product.is_active == True,
        Product.is_sellable == True,
    )
    if category_id:
        q = q.filter(Product.category_id == category_id)
    if search:
        q = q.filter(Product.name.ilike(f"%{search}%"))
    
    products = q.order_by(Product.category_id, Product.name).all()

    # Get stock levels for warehouse
    print(f"DEBUG: branch_id={branch_id}, warehouse={warehouse.id if warehouse else None}")
    stock_map = {}
    if warehouse:
        levels = db.query(InventoryLevel).filter(
            InventoryLevel.warehouse_id == warehouse.id,
        ).all()
        stock_map = {lv.product_id: float(lv.quantity) for lv in levels}

    # Get categories for filter sidebar
    cat_ids = set(p.category_id for p in products if p.category_id)
    categories = db.query(ProductCategory).filter(
        ProductCategory.id.in_(cat_ids)
    ).order_by(ProductCategory.name).all() if cat_ids else []

    return JSONResponse({
        "products": [
            {
                "id": p.id,
                "code": p.code,
                "name": p.name,
                "category_id": p.category_id,
                "category_name": p.category.name if p.category else "Khác",
                "base_unit": p.base_unit,
                "sell_price": float(p.sell_price or 0),
                "cost_price": float(p.cost_price or 0),
                "stock": stock_map.get(p.id, 0),
                "min_stock": next(
                    (lv.min_stock for lv in db.query(InventoryLevel).filter(
                        InventoryLevel.warehouse_id == warehouse.id,
                        InventoryLevel.product_id == p.id
                    ).all()) if warehouse else iter([]),
                    p.min_stock_global or 0
                ),
            }
            for p in products
        ],
        "categories": [
            {"id": c.id, "name": c.name, "code": c.code}
            for c in categories
        ],
        "warehouse_id": warehouse.id if warehouse else None,
        "warehouse_name": warehouse.name if warehouse else None,
        "branch_id": branch_id,
    })


# ─────────────────────────── POST Consume ──────────────────────────

class ConsumeItem(BaseModel):
    product_id: int
    quantity: int = 1
    unit_price: Optional[str] = None  # Override sell_price if needed


class ConsumeRequest(BaseModel):
    folio_id: int
    items: List[ConsumeItem]


@router.post("/consume")
async def consume_inventory(
    request: Request,
    payload: ConsumeRequest,
    db: Session = Depends(get_db),
):
    """
    Tiêu hao kho: Trừ tồn kho + Tạo FolioTransaction (atomic).
    Dùng khi lễ tân ghi nhận dịch vụ minibar/phòng từ kho.
    """
    from ...core.utils import VN_TZ

    user = _require_login(request)
    user_id = user.get("id")

    if not payload.items:
        raise HTTPException(status_code=400, detail="Không có sản phẩm nào được chọn")

    with db.begin():
        # 1. Get Folio
        folio = db.query(Folio).filter(Folio.id == payload.folio_id).with_for_update().first()
        if not folio:
            raise HTTPException(status_code=404, detail="Folio không tìm thấy")
        if folio.status == FolioStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Folio đã đóng, không thể thêm dịch vụ")

        # 2. Get warehouse from branch
        warehouse = _get_branch_warehouse(db, folio.branch_id)
        if not warehouse:
            raise HTTPException(status_code=400, detail="Chi nhánh chưa được gán kho hàng")

        results = []
        low_stock_warnings = []

        for item in payload.items:
            # 3. Get product
            product = db.query(Product).filter(
                Product.id == item.product_id,
                Product.is_active == True,
                Product.is_sellable == True,
            ).first()
            if not product:
                raise HTTPException(
                    status_code=404,
                    detail=f"Sản phẩm #{item.product_id} không tìm thấy hoặc không thể bán"
                )

            qty = Decimal(str(item.quantity))
            if qty <= 0:
                raise HTTPException(status_code=400, detail=f"Số lượng phải > 0 ({product.name})")

            # 4. Lock & check inventory level
            inv_level = db.query(InventoryLevel).filter(
                InventoryLevel.warehouse_id == warehouse.id,
                InventoryLevel.product_id == product.id,
            ).with_for_update().first()

            current_stock = Decimal(str(inv_level.quantity)) if inv_level else Decimal("0")
            if current_stock < qty:
                raise HTTPException(
                    status_code=400,
                    detail=f"Không đủ tồn kho: {product.name} (còn {int(current_stock)} {product.base_unit}, cần {int(qty)})"
                )

            # 5. Deduct stock
            new_balance = current_stock - qty
            inv_level.quantity = new_balance

            # 6. Log StockMovement
            movement = StockMovement(
                warehouse_id=warehouse.id,
                product_id=product.id,
                transaction_type=TransactionTypeWMS.EXPORT_SERVICE,
                quantity_change=-qty,
                balance_after=new_balance,
                ref_ticket_type="folio",
                ref_ticket_id=folio.id,
                created_at=datetime.now(VN_TZ),
                actor_id=user_id,
            )
            db.add(movement)
            db.flush()

            # 7. Create FolioTransaction
            unit_price_val = money(item.unit_price) if item.unit_price else money(product.sell_price or 0)
            total_amount = money(unit_price_val * qty)

            tx = create_charge_transaction(
                db=db,
                folio=folio,
                tx_type=FolioTransactionType.MINIBAR_CHARGE,
                description=f"{product.name} x{int(qty)}",
                amount=total_amount,
                created_by=user_id,
                quantity=qty,
                unit_price=unit_price_val,
                reference_id=movement.id,
                reference_type="inventory",
            )
            db.flush()

            results.append({
                "product_id": product.id,
                "product_name": product.name,
                "quantity": int(qty),
                "unit_price": float(unit_price_val),
                "total": float(total_amount),
                "stock_after": float(new_balance),
                "movement_id": movement.id,
                "transaction_id": tx.id,
            })

            # 8. Check low stock warning
            min_stock = inv_level.min_stock if inv_level else (product.min_stock_global or 0)
            if new_balance <= Decimal(str(min_stock)):
                low_stock_warnings.append({
                    "product_id": product.id,
                    "product_name": product.name,
                    "current_stock": float(new_balance),
                    "min_stock": min_stock,
                    "unit": product.base_unit,
                })

    # Refresh after commit
    db.refresh(folio)

    response = {
        "status": "success",
        "message": f"Đã ghi nhận {len(results)} sản phẩm vào Folio",
        "items": results,
        "folio": {
            "id": folio.id,
            "total_charge": float(folio.total_charge or 0),
            "balance": float(folio.balance or 0),
        },
    }

    if low_stock_warnings:
        response["low_stock_warnings"] = low_stock_warnings
        response["message"] += f" ⚠ {len(low_stock_warnings)} sản phẩm sắp hết hàng!"

    return JSONResponse(response)


# ─────────────────────────── Void Consume (Reverse) ──────────────────

@router.post("/void-consume/{movement_id}")
async def void_inventory_consume(
    request: Request,
    movement_id: int,
    db: Session = Depends(get_db),
):
    """
    Hoàn kho khi void FolioTransaction có reference_type='inventory'.
    Tạo StockMovement ngược để hoàn tồn kho.
    """
    from ...core.utils import VN_TZ

    user = _require_login(request)
    user_id = user.get("id")

    with db.begin():
        # Find original movement
        original = db.query(StockMovement).filter(
            StockMovement.id == movement_id,
            StockMovement.transaction_type == TransactionTypeWMS.EXPORT_SERVICE,
        ).first()

        if not original:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi xuất kho")

        qty_to_return = abs(original.quantity_change)

        # Lock inventory level
        inv_level = db.query(InventoryLevel).filter(
            InventoryLevel.warehouse_id == original.warehouse_id,
            InventoryLevel.product_id == original.product_id,
        ).with_for_update().first()

        if not inv_level:
            raise HTTPException(status_code=400, detail="Không tìm thấy mức tồn kho")

        # Return stock
        new_balance = inv_level.quantity + qty_to_return
        inv_level.quantity = new_balance

        # Log reversal movement
        reversal = StockMovement(
            warehouse_id=original.warehouse_id,
            product_id=original.product_id,
            transaction_type=TransactionTypeWMS.VOID_SERVICE,
            quantity_change=qty_to_return,
            balance_after=new_balance,
            ref_ticket_type="void_service",
            ref_ticket_id=original.ref_ticket_id,
            created_at=datetime.now(VN_TZ),
            actor_id=user_id,
        )
        db.add(reversal)

    return JSONResponse({
        "status": "success",
        "message": "Đã hoàn trả tồn kho",
        "product_id": original.product_id,
        "quantity_returned": float(qty_to_return),
        "stock_after": float(new_balance),
    })


# ─────────────────────────── GET Branch Stock ──────────────────────

@router.get("/branch-stock")
async def get_branch_stock(
    request: Request,
    branch_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Xem tổng quan tồn kho chi nhánh hiện tại (nhanh).
    """
    user = _require_login(request)

    if not branch_id:
        branch = _get_branch_from_request(request, db)
        if branch:
            branch_id = branch.id

    if not branch_id:
        raise HTTPException(status_code=400, detail="Không xác định được chi nhánh")

    warehouse = _get_branch_warehouse(db, branch_id)
    if not warehouse:
        return JSONResponse({"items": [], "warehouse": None})

    levels = (
        db.query(InventoryLevel)
        .options(joinedload(InventoryLevel.product).joinedload(Product.category))
        .filter(InventoryLevel.warehouse_id == warehouse.id)
        .all()
    )

    items = []
    low_stock_count = 0
    for lv in levels:
        is_low = lv.quantity <= Decimal(str(lv.min_stock or 0))
        if is_low:
            low_stock_count += 1
        items.append({
            "product_id": lv.product_id,
            "product_name": lv.product.name if lv.product else "?",
            "category": lv.product.category.name if lv.product and lv.product.category else "Khác",
            "quantity": float(lv.quantity),
            "min_stock": lv.min_stock,
            "unit": lv.product.base_unit if lv.product else "",
            "is_low_stock": is_low,
            "is_sellable": lv.product.is_sellable if lv.product else False,
        })

    return JSONResponse({
        "items": items,
        "warehouse": {"id": warehouse.id, "name": warehouse.name},
        "branch_id": branch_id,
        "total_products": len(items),
        "low_stock_count": low_stock_count,
    })
