from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, extract
from typing import Optional
from datetime import datetime, timedelta
from decimal import Decimal

from ...db.session import get_db
from ...db.models import (
    Product, InventoryLevel, StockMovement, Warehouse,
    TransactionTypeWMS
)
from ...core.utils import VN_TZ

router = APIRouter()


@router.get("/alerts")
async def get_low_stock_alerts(
    warehouse_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(InventoryLevel).options(
        joinedload(InventoryLevel.product),
        joinedload(InventoryLevel.warehouse)
    ).filter(InventoryLevel.quantity <= InventoryLevel.min_stock)

    if warehouse_id:
        query = query.filter(InventoryLevel.warehouse_id == warehouse_id)

    alerts = query.all()

    return {
        "data": [
            {
                "product_id": a.product_id,
                "product_name": a.product.name,
                "product_code": a.product.code,
                "warehouse_id": a.warehouse_id,
                "warehouse_name": a.warehouse.name,
                "current_quantity": float(a.quantity),
                "min_stock": a.min_stock,
                "deficit": a.min_stock - float(a.quantity),
                "base_unit": a.product.base_unit,
                "severity": "critical" if a.quantity <= 0 else "warning"
            }
            for a in alerts
            if a.product.is_active
        ],
        "total": len(alerts)
    }


@router.get("/alerts/count")
async def get_alert_count(
    warehouse_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(func.count()).select_from(InventoryLevel).filter(
        InventoryLevel.quantity <= InventoryLevel.min_stock
    )
    if warehouse_id:
        query = query.filter(InventoryLevel.warehouse_id == warehouse_id)

    count = query.scalar() or 0
    return {"count": count}


@router.get("/analytics/consumption")
async def consumption_report(
    warehouse_id: Optional[int] = None,
    months: int = 6,
    db: Session = Depends(get_db)
):
    now = datetime.now(VN_TZ)
    start_date = now - timedelta(days=months * 30)

    query = db.query(
        StockMovement.product_id,
        extract('year', StockMovement.created_at).label('year'),
        extract('month', StockMovement.created_at).label('month'),
        func.sum(func.abs(StockMovement.quantity_change)).label('total_out')
    ).filter(
        StockMovement.transaction_type.in_([
            TransactionTypeWMS.EXPORT_TRANSFER,
            TransactionTypeWMS.EXPORT_SERVICE
        ]),
        StockMovement.created_at >= start_date
    )

    if warehouse_id:
        query = query.filter(StockMovement.warehouse_id == warehouse_id)

    query = query.group_by(
        StockMovement.product_id,
        extract('year', StockMovement.created_at),
        extract('month', StockMovement.created_at)
    ).order_by(
        extract('year', StockMovement.created_at),
        extract('month', StockMovement.created_at)
    )

    rows = query.all()

    product_ids = list(set(r.product_id for r in rows))
    products = {}
    if product_ids:
        prods = db.query(Product).filter(Product.id.in_(product_ids)).all()
        products = {p.id: p for p in prods}

    data = {}
    for r in rows:
        pid = r.product_id
        if pid not in data:
            p = products.get(pid)
            data[pid] = {
                "product_id": pid,
                "product_name": p.name if p else "",
                "product_code": p.code if p else "",
                "months": []
            }
        data[pid]["months"].append({
            "year": int(r.year),
            "month": int(r.month),
            "total_out": float(r.total_out)
        })

    return {"data": list(data.values())}


@router.get("/analytics/forecast")
async def stock_forecast(
    warehouse_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    now = datetime.now(VN_TZ)
    days_back = 30
    start_date = now - timedelta(days=days_back)

    query = db.query(
        StockMovement.product_id,
        func.sum(func.abs(StockMovement.quantity_change)).label('total_out')
    ).filter(
        StockMovement.transaction_type.in_([
            TransactionTypeWMS.EXPORT_TRANSFER,
            TransactionTypeWMS.EXPORT_SERVICE
        ]),
        StockMovement.created_at >= start_date
    )

    if warehouse_id:
        query = query.filter(StockMovement.warehouse_id == warehouse_id)

    query = query.group_by(StockMovement.product_id)
    consumption = {r.product_id: float(r.total_out) for r in query.all()}

    levels_query = db.query(InventoryLevel).options(
        joinedload(InventoryLevel.product),
        joinedload(InventoryLevel.warehouse)
    )
    if warehouse_id:
        levels_query = levels_query.filter(InventoryLevel.warehouse_id == warehouse_id)

    levels = levels_query.all()

    forecasts = []
    for lv in levels:
        if not lv.product.is_active:
            continue
        daily_avg = consumption.get(lv.product_id, 0) / days_back
        if daily_avg > 0:
            days_until_stockout = float(lv.quantity) / daily_avg
        else:
            days_until_stockout = None

        forecasts.append({
            "product_id": lv.product_id,
            "product_name": lv.product.name,
            "product_code": lv.product.code,
            "warehouse_id": lv.warehouse_id,
            "warehouse_name": lv.warehouse.name,
            "current_quantity": float(lv.quantity),
            "daily_avg_consumption": round(daily_avg, 2),
            "days_until_stockout": round(days_until_stockout, 1) if days_until_stockout is not None else None,
            "risk": "critical" if days_until_stockout is not None and days_until_stockout <= 3
                    else "warning" if days_until_stockout is not None and days_until_stockout <= 7
                    else "ok"
        })

    forecasts.sort(key=lambda x: x["days_until_stockout"] if x["days_until_stockout"] is not None else 9999)

    return {"data": forecasts}
