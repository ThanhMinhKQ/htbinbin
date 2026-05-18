from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from ...db.session import get_db
from ...db.models import (
    Product, StockMovement, Warehouse, User, TransactionTypeWMS
)
from ...core.utils import VN_TZ, get_current_work_shift

router = APIRouter()

ADMIN_ROLES = {"boss", "admin", "quanly"}


def _shift_window():
    now_vn = datetime.now(VN_TZ)
    if now_vn.hour < 7:
        start = (now_vn - timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
    else:
        start = now_vn.replace(hour=7, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


def _build_sales_response(db, actor_id, actor_name, warehouse_id, start_dt, end_dt, work_date, shift_name):
    base_q = db.query(StockMovement).filter(
        StockMovement.actor_id == actor_id,
        StockMovement.transaction_type.in_([
            TransactionTypeWMS.EXPORT_SERVICE,
            TransactionTypeWMS.VOID_SERVICE,
        ]),
        StockMovement.created_at >= start_dt,
        StockMovement.created_at < end_dt,
    )
    if warehouse_id:
        base_q = base_q.filter(StockMovement.warehouse_id == warehouse_id)

    rows = base_q.with_entities(
        StockMovement.product_id,
        StockMovement.transaction_type,
        func.sum(StockMovement.quantity_change).label("total_change"),
        func.count(StockMovement.id).label("tx_count"),
    ).group_by(StockMovement.product_id, StockMovement.transaction_type).all()

    shift_info = {
        "work_date": work_date.isoformat(),
        "shift_name": shift_name,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }
    actor_info = {"id": actor_id, "name": actor_name}

    if not rows:
        return {
            "shift": shift_info,
            "actor": actor_info,
            "items": [],
            "transactions": [],
            "totals": {"total_qty": 0, "total_amount": 0.0, "tx_count": 0},
        }

    product_ids = list({r.product_id for r in rows})
    products = db.query(Product).filter(Product.id.in_(product_ids)).all()
    product_map = {p.id: p for p in products}

    by_product: dict = {}
    for r in rows:
        bucket = by_product.setdefault(r.product_id, {"sold_qty": 0.0, "void_qty": 0.0, "tx_count": 0})
        change = float(r.total_change or 0)
        if r.transaction_type == TransactionTypeWMS.EXPORT_SERVICE:
            bucket["sold_qty"] += abs(change)
        else:
            bucket["void_qty"] += abs(change)
        bucket["tx_count"] += int(r.tx_count or 0)

    items = []
    total_qty = total_amount = 0.0
    total_tx = 0
    for pid, agg in by_product.items():
        product = product_map.get(pid)
        net_qty = agg["sold_qty"] - agg["void_qty"]
        if net_qty <= 0 and agg["sold_qty"] == 0:
            continue
        sell_price = float(product.sell_price or 0) if product else 0.0
        amount = sell_price * net_qty
        total_qty += net_qty
        total_amount += amount
        total_tx += agg["tx_count"]
        items.append({
            "product_id": pid,
            "product_name": product.name if product else f"#{pid}",
            "product_code": product.code if product else "",
            "base_unit": product.base_unit if product else "",
            "sold_qty": round(agg["sold_qty"], 2),
            "void_qty": round(agg["void_qty"], 2),
            "net_qty": round(net_qty, 2),
            "sell_price": sell_price,
            "amount": round(amount, 2),
            "tx_count": agg["tx_count"],
        })
    items.sort(key=lambda x: x["amount"], reverse=True)

    tx_q = db.query(StockMovement).filter(
        StockMovement.actor_id == actor_id,
        StockMovement.transaction_type.in_([
            TransactionTypeWMS.EXPORT_SERVICE,
            TransactionTypeWMS.VOID_SERVICE,
        ]),
        StockMovement.created_at >= start_dt,
        StockMovement.created_at < end_dt,
    )
    if warehouse_id:
        tx_q = tx_q.filter(StockMovement.warehouse_id == warehouse_id)
    movements = tx_q.order_by(StockMovement.created_at.desc()).limit(100).all()

    transactions = [
        {
            "id": m.id,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "type": m.transaction_type.value if hasattr(m.transaction_type, "value") else str(m.transaction_type),
            "product_id": m.product_id,
            "product_name": product_map.get(m.product_id).name if product_map.get(m.product_id) else f"#{m.product_id}",
            "quantity_change": float(m.quantity_change),
        }
        for m in movements
    ]

    return {
        "shift": shift_info,
        "actor": actor_info,
        "items": items,
        "transactions": transactions,
        "totals": {
            "total_qty": round(total_qty, 2),
            "total_amount": round(total_amount, 2),
            "tx_count": total_tx,
        },
    }


@router.get("/my-shift-sales")
async def get_my_shift_sales(
    request: Request,
    warehouse_id: int = None,
    target_user_id: int = None,
    db: Session = Depends(get_db)
):
    """Doanh số ca làm việc.

    - Nhân viên thường: chỉ xem của mình.
    - Admin/boss/quanly: có thể truyền target_user_id để xem của nhân viên khác.
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Không có phiên đăng nhập")

    caller_id = user_data.get("id")
    caller_role = user_data.get("role", "")
    is_admin = caller_role in ADMIN_ROLES

    if target_user_id and target_user_id != caller_id:
        if not is_admin:
            raise HTTPException(status_code=403, detail="Không có quyền xem dữ liệu nhân viên khác")
        target_user = db.query(User).filter(User.id == target_user_id, User.is_active == True).first()
        if not target_user:
            raise HTTPException(status_code=404, detail="Không tìm thấy nhân viên")
        actor_id = target_user.id
        actor_name = target_user.name
    else:
        actor_id = caller_id
        actor_name = user_data.get("name") or ""

    start_dt, end_dt = _shift_window()
    work_date, shift_name = get_current_work_shift()

    return _build_sales_response(db, actor_id, actor_name, warehouse_id, start_dt, end_dt, work_date, shift_name)


@router.get("/shift-sales-staff")
async def get_shift_sales_staff(
    request: Request,
    warehouse_id: int = None,
    db: Session = Depends(get_db)
):
    """Danh sách nhân viên có giao dịch trong ca hiện tại tại kho.

    Chỉ admin/boss/quanly mới được gọi.
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Không có phiên đăng nhập")

    caller_role = user_data.get("role", "")
    if caller_role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Không có quyền truy cập")

    start_dt, end_dt = _shift_window()

    q = db.query(StockMovement.actor_id, func.count(StockMovement.id).label("tx_count")).filter(
        StockMovement.transaction_type.in_([
            TransactionTypeWMS.EXPORT_SERVICE,
            TransactionTypeWMS.VOID_SERVICE,
        ]),
        StockMovement.created_at >= start_dt,
        StockMovement.created_at < end_dt,
        StockMovement.actor_id.isnot(None),
    )
    if warehouse_id:
        q = q.filter(StockMovement.warehouse_id == warehouse_id)

    rows = q.group_by(StockMovement.actor_id).all()

    if not rows:
        return []

    user_ids = [r.actor_id for r in rows]
    tx_map = {r.actor_id: r.tx_count for r in rows}

    users = db.query(User).filter(User.id.in_(user_ids)).all()

    return [
        {
            "id": u.id,
            "name": u.name,
            "tx_count": tx_map.get(u.id, 0),
        }
        for u in sorted(users, key=lambda x: tx_map.get(x.id, 0), reverse=True)
    ]
