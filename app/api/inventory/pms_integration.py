from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from decimal import Decimal

from ...db.session import get_db
from ...db.models import (
    Product, InventoryLevel, StockMovement, Warehouse,
    TransactionTypeWMS
)

router = APIRouter()


class ConsumeRequest(BaseModel):
    product_id: Optional[int] = None
    service_code: Optional[str] = None
    quantity: float
    warehouse_id: int
    stay_id: Optional[int] = None
    folio_id: Optional[int] = None
    folio_transaction_id: Optional[int] = None
    notes: Optional[str] = None


class VoidRequest(BaseModel):
    movement_id: int
    notes: Optional[str] = None


@router.post("/pms/consume")
async def consume_for_service(
    payload: ConsumeRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """Trừ kho tự động khi PMS charge minibar/dịch vụ phòng."""
    user_data = request.session.get("user")
    actor_id = user_data["id"] if user_data else None

    product = None
    if payload.product_id:
        product = db.query(Product).get(payload.product_id)
    elif payload.service_code:
        product = db.query(Product).filter(
            Product.service_code == payload.service_code,
            Product.is_active == True
        ).first()

    if not product:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại hoặc chưa map service_code")

    qty = Decimal(str(payload.quantity))
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Số lượng phải > 0")

    level = db.query(InventoryLevel).filter(
        InventoryLevel.warehouse_id == payload.warehouse_id,
        InventoryLevel.product_id == product.id
    ).with_for_update().first()

    if not level:
        raise HTTPException(
            status_code=400,
            detail=f"Sản phẩm '{product.name}' chưa có trong kho (warehouse_id={payload.warehouse_id})"
        )

    if level.quantity < qty:
        raise HTTPException(
            status_code=400,
            detail=f"Không đủ tồn kho: {product.name} (Tồn: {level.quantity}, Cần: {qty})"
        )

    level.quantity -= qty

    ref_id = payload.folio_transaction_id or payload.folio_id or payload.stay_id
    movement = StockMovement(
        warehouse_id=payload.warehouse_id,
        product_id=product.id,
        transaction_type=TransactionTypeWMS.EXPORT_SERVICE,
        quantity_change=-qty,
        balance_after=level.quantity,
        ref_ticket_id=ref_id,
        ref_ticket_type="FOLIO_SERVICE",
        actor_id=actor_id
    )
    db.add(movement)
    db.commit()

    return {
        "status": "success",
        "movement_id": movement.id,
        "product_name": product.name,
        "quantity_deducted": float(qty),
        "balance_after": float(level.quantity)
    }


@router.post("/pms/void")
async def void_service_stock(
    payload: VoidRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """Hoàn kho khi void dịch vụ PMS (minibar, phòng)."""
    user_data = request.session.get("user")
    actor_id = user_data["id"] if user_data else None

    original = db.query(StockMovement).get(payload.movement_id)
    if not original:
        raise HTTPException(status_code=404, detail="Không tìm thấy giao dịch kho gốc")

    if original.transaction_type != TransactionTypeWMS.EXPORT_SERVICE:
        raise HTTPException(status_code=400, detail="Chỉ có thể void giao dịch EXPORT_SERVICE")

    existing_void = db.query(StockMovement).filter(
        StockMovement.ref_ticket_id == original.id,
        StockMovement.ref_ticket_type == "VOID_SERVICE_REF",
        StockMovement.transaction_type == TransactionTypeWMS.VOID_SERVICE
    ).first()
    if existing_void:
        raise HTTPException(status_code=400, detail="Giao dịch này đã được void trước đó")

    qty_to_restore = abs(original.quantity_change)

    level = db.query(InventoryLevel).filter(
        InventoryLevel.warehouse_id == original.warehouse_id,
        InventoryLevel.product_id == original.product_id
    ).with_for_update().first()

    if not level:
        level = InventoryLevel(
            warehouse_id=original.warehouse_id,
            product_id=original.product_id,
            quantity=0,
            min_stock=0
        )
        db.add(level)
        db.flush()

    level.quantity += qty_to_restore

    void_movement = StockMovement(
        warehouse_id=original.warehouse_id,
        product_id=original.product_id,
        transaction_type=TransactionTypeWMS.VOID_SERVICE,
        quantity_change=qty_to_restore,
        balance_after=level.quantity,
        ref_ticket_id=original.id,
        ref_ticket_type="VOID_SERVICE_REF",
        actor_id=actor_id
    )
    db.add(void_movement)
    db.commit()

    return {
        "status": "success",
        "void_movement_id": void_movement.id,
        "quantity_restored": float(qty_to_restore),
        "balance_after": float(level.quantity)
    }
