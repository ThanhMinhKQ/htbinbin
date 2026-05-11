from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
from decimal import Decimal

from ...db.session import get_db
from ...db.models import (
    Stocktake, StocktakeItem, StocktakeStatus,
    InventoryLevel, StockMovement, Product, Warehouse, TransactionTypeWMS
)

router = APIRouter()


class StocktakeItemInput(BaseModel):
    product_id: int
    actual_quantity: float
    notes: Optional[str] = None


class StocktakeCreate(BaseModel):
    warehouse_id: int
    notes: Optional[str] = None


class StocktakeComplete(BaseModel):
    items: List[StocktakeItemInput]
    notes: Optional[str] = None


@router.post("/stocktake")
async def create_stocktake(
    payload: StocktakeCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Chưa đăng nhập")

    warehouse = db.query(Warehouse).get(payload.warehouse_id)
    if not warehouse:
        raise HTTPException(status_code=404, detail="Kho không tồn tại")

    code = f"STK_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    stocktake = Stocktake(
        code=code,
        warehouse_id=payload.warehouse_id,
        status=StocktakeStatus.IN_PROGRESS,
        creator_id=user_data["id"],
        notes=payload.notes
    )
    db.add(stocktake)
    db.flush()

    levels = db.query(InventoryLevel).filter(
        InventoryLevel.warehouse_id == payload.warehouse_id,
        InventoryLevel.quantity > 0
    ).all()

    for lv in levels:
        item = StocktakeItem(
            stocktake_id=stocktake.id,
            product_id=lv.product_id,
            system_quantity=lv.quantity
        )
        db.add(item)

    db.commit()
    return {
        "status": "success",
        "id": stocktake.id,
        "code": stocktake.code,
        "item_count": len(levels),
        "message": f"Đã tạo phiếu kiểm kê {code} với {len(levels)} sản phẩm"
    }


@router.get("/stocktakes")
async def get_stocktakes(
    warehouse_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    per_page: int = 10,
    db: Session = Depends(get_db)
):
    query = db.query(Stocktake).options(
        joinedload(Stocktake.warehouse),
        joinedload(Stocktake.creator)
    )

    if warehouse_id:
        query = query.filter(Stocktake.warehouse_id == warehouse_id)
    if status:
        query = query.filter(Stocktake.status == status)

    total = query.count()
    stocktakes = query.order_by(Stocktake.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return {
        "data": [
            {
                "id": s.id,
                "code": s.code,
                "warehouse_name": s.warehouse.name if s.warehouse else "",
                "status": s.status,
                "creator_name": s.creator.name if s.creator else "",
                "item_count": len(s.items) if s.items else 0,
                "notes": s.notes,
                "created_at": s.created_at.isoformat() if s.created_at else "",
                "completed_at": s.completed_at.isoformat() if s.completed_at else ""
            }
            for s in stocktakes
        ],
        "total": total,
        "pages": (total + per_page - 1) // per_page
    }


@router.get("/stocktake/{stocktake_id}")
async def get_stocktake_detail(
    stocktake_id: int,
    db: Session = Depends(get_db)
):
    stocktake = db.query(Stocktake).options(
        joinedload(Stocktake.items).joinedload(StocktakeItem.product),
        joinedload(Stocktake.warehouse),
        joinedload(Stocktake.creator)
    ).get(stocktake_id)

    if not stocktake:
        raise HTTPException(status_code=404, detail="Phiếu kiểm kê không tồn tại")

    return {
        "id": stocktake.id,
        "code": stocktake.code,
        "warehouse_id": stocktake.warehouse_id,
        "warehouse_name": stocktake.warehouse.name if stocktake.warehouse else "",
        "status": stocktake.status,
        "creator_name": stocktake.creator.name if stocktake.creator else "",
        "notes": stocktake.notes,
        "created_at": stocktake.created_at.isoformat() if stocktake.created_at else "",
        "completed_at": stocktake.completed_at.isoformat() if stocktake.completed_at else "",
        "items": [
            {
                "id": i.id,
                "product_id": i.product_id,
                "product_name": i.product.name if i.product else "",
                "product_code": i.product.code if i.product else "",
                "base_unit": i.product.base_unit if i.product else "",
                "system_quantity": float(i.system_quantity),
                "actual_quantity": float(i.actual_quantity) if i.actual_quantity is not None else None,
                "difference": float(i.difference) if i.difference is not None else None,
                "notes": i.notes
            }
            for i in stocktake.items
        ]
    }


@router.post("/stocktake/{stocktake_id}/complete")
async def complete_stocktake(
    stocktake_id: int,
    payload: StocktakeComplete,
    request: Request,
    db: Session = Depends(get_db)
):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Chưa đăng nhập")

    stocktake = db.query(Stocktake).options(
        joinedload(Stocktake.items)
    ).get(stocktake_id)

    if not stocktake:
        raise HTTPException(status_code=404, detail="Phiếu kiểm kê không tồn tại")

    if stocktake.status not in (StocktakeStatus.DRAFT, StocktakeStatus.IN_PROGRESS):
        raise HTTPException(status_code=400, detail="Phiếu đã hoàn thành hoặc bị hủy")

    item_map = {i.product_id: i for i in stocktake.items}
    adjustments = 0

    for entry in payload.items:
        item = item_map.get(entry.product_id)
        if not item:
            item = StocktakeItem(
                stocktake_id=stocktake.id,
                product_id=entry.product_id,
                system_quantity=0
            )
            db.add(item)
            db.flush()

        actual = Decimal(str(entry.actual_quantity))
        item.actual_quantity = actual
        item.difference = actual - item.system_quantity
        item.notes = entry.notes

        diff = actual - item.system_quantity
        if diff != 0:
            level = db.query(InventoryLevel).filter(
                InventoryLevel.warehouse_id == stocktake.warehouse_id,
                InventoryLevel.product_id == entry.product_id
            ).first()

            if not level:
                level = InventoryLevel(
                    warehouse_id=stocktake.warehouse_id,
                    product_id=entry.product_id,
                    quantity=0,
                    min_stock=0
                )
                db.add(level)
                db.flush()

            level.quantity = actual

            movement = StockMovement(
                warehouse_id=stocktake.warehouse_id,
                product_id=entry.product_id,
                transaction_type=TransactionTypeWMS.ADJUSTMENT,
                quantity_change=diff,
                balance_after=actual,
                ref_ticket_id=stocktake.id,
                ref_ticket_type="STOCKTAKE",
                actor_id=user_data["id"]
            )
            db.add(movement)
            adjustments += 1

    stocktake.status = StocktakeStatus.COMPLETED
    stocktake.completed_at = datetime.now(timezone.utc)
    stocktake.completed_by = user_data["id"]
    if payload.notes:
        stocktake.notes = payload.notes

    db.commit()
    return {
        "status": "success",
        "adjustments": adjustments,
        "message": f"Kiểm kê hoàn tất. {adjustments} sản phẩm được điều chỉnh."
    }


@router.post("/stocktake/{stocktake_id}/cancel")
async def cancel_stocktake(
    stocktake_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Chưa đăng nhập")

    stocktake = db.query(Stocktake).get(stocktake_id)
    if not stocktake:
        raise HTTPException(status_code=404, detail="Phiếu kiểm kê không tồn tại")

    if stocktake.status == StocktakeStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Không thể hủy phiếu đã hoàn thành")

    stocktake.status = StocktakeStatus.CANCELLED
    db.commit()
    return {"status": "success", "message": "Đã hủy phiếu kiểm kê"}
