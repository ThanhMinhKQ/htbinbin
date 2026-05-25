from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case, desc, text
from datetime import datetime

from ...db.session import get_db
from ...db.models import Product, InventoryLevel, Warehouse, InventoryTransfer, InventoryReceipt, TicketStatus, StockMovement, InventoryTransferItem, TransactionTypeWMS
from ...core.utils import VN_TZ

router = APIRouter()

@router.get("/report-realtime")
async def get_inventory_report_realtime(
    branch_id: int = None, # Deprecated
    warehouse_id: int = None, # [NEW] Filter by specific Warehouse
    category_id: int = None,
    db: Session = Depends(get_db)
):
    """
    Lấy tồn kho realtime từ bảng InventoryLevel
    """
    query = db.query(InventoryLevel).options(
        joinedload(InventoryLevel.product),
        joinedload(InventoryLevel.warehouse)
    )

    if warehouse_id:
        query = query.filter(InventoryLevel.warehouse_id == warehouse_id)
    elif branch_id:
        # Legacy support
        from ...db.models import Branch
        branch = db.query(Branch).get(branch_id)
        # [FIX] Admin Branch should see Main Warehouse (branch_id=None) too
        from ...db.models import Branch
        branch = db.query(Branch).get(branch_id)
        is_admin = branch and branch.branch_code.upper() in ['ADMIN', 'BOSS', 'HEAD']
        
        if is_admin:
            query = query.join(InventoryLevel.warehouse).filter(
                (Warehouse.branch_id == branch_id) | (Warehouse.branch_id.is_(None))
            )
        else:
            query = query.join(InventoryLevel.warehouse).filter(Warehouse.branch_id == branch_id)
        
    if category_id:
        query = query.join(InventoryLevel.product).filter(Product.category_id == category_id)

    stocks = query.all()
    
    result = []
    for s in stocks:
        if not s.product.is_active and s.quantity <= 0:
            continue
            
        result.append({
            "product_id": s.product_id,
            "product_name": s.product.name,
            "product_code": s.product.code,
            "warehouse_name": s.warehouse.name,
            "quantity_base": float(s.quantity),
            "display_quantity": s.display_quantity, 
            "min_stock": s.min_stock,
            "status": "Cảnh báo" if s.quantity <= s.min_stock else "Ổn định"
        })
        
    return {"data": result}

@router.get("/stock-summary")
async def get_stock_summary(
    warehouse_id: int = None,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db)
):
    """Tồn kho theo kỳ: tồn đầu, nhập, xuất, tồn cuối — batch query, không N+1."""
    start_time = None
    end_time = None
    try:
        if date_from:
            f_date = datetime.strptime(date_from, "%Y-%m-%d").date()
            start_time = datetime.combine(f_date, datetime.min.time()).replace(tzinfo=VN_TZ)
        if date_to:
            t_date = datetime.strptime(date_to, "%Y-%m-%d").date()
            end_time = datetime.combine(t_date, datetime.max.time()).replace(tzinfo=VN_TZ)
    except ValueError:
        pass

    if not warehouse_id:
        return {"data": []}

    # 1. Batch: current inventory levels
    stocks = db.query(InventoryLevel).options(
        joinedload(InventoryLevel.product)
    ).filter(InventoryLevel.warehouse_id == warehouse_id).all()

    active_stocks = [s for s in stocks if s.product.is_active or s.quantity > 0]
    if not active_stocks:
        return {"data": []}

    product_ids = [s.product_id for s in active_stocks]

    # 2. Batch: all movements for this warehouse + period in ONE query
    mv_query = db.query(
        StockMovement.product_id,
        StockMovement.transaction_type,
        func.sum(StockMovement.quantity_change).label("total_change")
    ).filter(
        StockMovement.warehouse_id == warehouse_id,
        StockMovement.product_id.in_(product_ids)
    )

    if start_time:
        mv_query = mv_query.filter(StockMovement.created_at >= start_time)
    if end_time:
        mv_query = mv_query.filter(StockMovement.created_at <= end_time)

    mv_rows = mv_query.group_by(
        StockMovement.product_id,
        StockMovement.transaction_type
    ).all()

    # 3. Build movement map: {product_id: {tx_type: total_change}}
    mv_map: dict = {}
    for row in mv_rows:
        pid = row.product_id
        if pid not in mv_map:
            mv_map[pid] = {}
        mv_map[pid][row.transaction_type] = float(row.total_change)

    # 4. Compute per-product stats
    result = []
    for stock in active_stocks:
        pid = stock.product_id
        closing = float(stock.quantity)
        txs = mv_map.get(pid, {})

        total_import = 0.0
        total_export = 0.0

        for tx_type, change in txs.items():
            if tx_type == TransactionTypeWMS.VOID_SERVICE:
                total_export -= abs(change)
            elif change > 0:
                total_import += change
            else:
                total_export += abs(change)

        if total_export < 0:
            total_export = 0.0

        opening = closing - (total_import - total_export)

        result.append({
            "product_id": pid,
            "product_name": stock.product.name,
            "product_code": stock.product.code,
            "base_unit": stock.product.base_unit,
            "packing_unit": stock.product.packing_unit,
            "conversion_rate": stock.product.conversion_rate,
            "category_id": stock.product.category_id,
            "opening_balance": round(opening, 2),
            "total_import": round(total_import, 2),
            "total_export": round(total_export, 2),
            "closing_balance": round(closing, 2),
            "min_stock": stock.min_stock,
            "status": "Cảnh báo" if stock.quantity <= stock.min_stock else "Ổn định"
        })

    return {"data": result}


@router.get("/dashboard-stats")
async def get_dashboard_stats(
    branch_id: int = None,
    warehouse_id: int = None,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db)
):
    """Dashboard stats — single raw SQL query for all aggregations."""
    start_time = None
    end_time = None
    try:
        if date_from:
            f_date = datetime.strptime(date_from, "%Y-%m-%d").date()
            start_time = datetime.combine(f_date, datetime.min.time()).replace(tzinfo=VN_TZ)
        if date_to:
            t_date = datetime.strptime(date_to, "%Y-%m-%d").date()
            end_time = datetime.combine(t_date, datetime.max.time()).replace(tzinfo=VN_TZ)
    except ValueError:
        pass

    params: dict = {}

    # Build warehouse filter clause
    if warehouse_id:
        wh_dest_filter = "it.dest_warehouse_id = :wh_id AND it.related_transfer_id IS NULL"
        wh_src_filter = "it.source_warehouse_id = :wh_id AND it.related_transfer_id IS NULL"
        wh_imp_filter = "ir.warehouse_id = :wh_id"
        wh_sm_filter = "sm.warehouse_id = :wh_id"
        params["wh_id"] = warehouse_id
    elif branch_id:
        wh_dest_filter = "dw.branch_id = :br_id AND it.related_transfer_id IS NULL"
        wh_src_filter = "sw.branch_id = :br_id AND it.related_transfer_id IS NULL"
        wh_imp_filter = "iw.branch_id = :br_id"
        wh_sm_filter = "smw.branch_id = :br_id"
        params["br_id"] = branch_id
    else:
        wh_dest_filter = "1=1"
        wh_src_filter = "1=1"
        wh_imp_filter = "1=1"
        wh_sm_filter = "1=1"

    date_filter_it = ""
    date_filter_ir = ""
    date_filter_sm = ""
    if start_time:
        date_filter_it += " AND it.created_at >= :start_time"
        date_filter_ir += " AND ir.created_at >= :start_time"
        date_filter_sm += " AND sm.created_at >= :start_time"
        params["start_time"] = start_time
    if end_time:
        date_filter_it += " AND it.created_at <= :end_time"
        date_filter_ir += " AND ir.created_at <= :end_time"
        date_filter_sm += " AND sm.created_at <= :end_time"
        params["end_time"] = end_time

    dest_join = "LEFT JOIN warehouses dw ON it.dest_warehouse_id = dw.id" if branch_id else ""
    src_join = "LEFT JOIN warehouses sw ON it.source_warehouse_id = sw.id" if branch_id else ""
    imp_join = "LEFT JOIN warehouses iw ON ir.warehouse_id = iw.id" if branch_id else ""
    sm_join = "LEFT JOIN warehouses smw ON sm.warehouse_id = smw.id" if branch_id else ""

    sql = text(f"""
        SELECT
            -- requests
            (SELECT COUNT(*) FROM inventory_transfers it {dest_join}
             WHERE {wh_dest_filter} {date_filter_it}) AS req_total,
            (SELECT COUNT(*) FROM inventory_transfers it {dest_join}
             WHERE {wh_dest_filter} AND it.status = 'PENDING') AS req_pending,
            (SELECT COUNT(*) FROM inventory_transfers it {dest_join}
             WHERE {wh_dest_filter} AND it.status = 'SHIPPING') AS req_shipping,
            (SELECT COUNT(*) FROM inventory_transfers it {dest_join}
             WHERE {wh_dest_filter} AND it.status = 'COMPLETED' {date_filter_it}) AS req_completed,
            -- imports
            (SELECT COUNT(*) FROM inventory_receipts ir {imp_join}
             WHERE {wh_imp_filter} {date_filter_ir}) AS imp_count,
            (SELECT COALESCE(SUM(ir.total_amount), 0) FROM inventory_receipts ir {imp_join}
             WHERE {wh_imp_filter} {date_filter_ir}) AS imp_amount,
            -- incoming transfer value
            (SELECT COALESCE(SUM(iti.received_quantity * p.cost_price), 0)
             FROM inventory_transfer_items iti
             JOIN inventory_transfers it ON iti.transfer_id = it.id {dest_join}
             JOIN products p ON iti.product_id = p.id
             WHERE {wh_dest_filter} AND it.status = 'COMPLETED' {date_filter_it}) AS incoming_val,
            -- export count
            (SELECT COUNT(*) FROM inventory_transfers it {src_join}
             WHERE {wh_src_filter} AND it.status = 'COMPLETED' {date_filter_it}) AS exp_count,
            -- sales
            (SELECT COALESCE(ABS(SUM(sm.quantity_change * p.sell_price)), 0)
             FROM stock_movements sm
             JOIN products p ON sm.product_id = p.id {sm_join}
             WHERE sm.transaction_type IN ('EXPORT_SERVICE', 'VOID_SERVICE')
             AND {wh_sm_filter} {date_filter_sm}) AS sales_amount
    """)

    row = db.execute(sql, params).fetchone()

    import_amount = float(row.imp_amount or 0) + float(row.incoming_val or 0)
    sales_amount = float(row.sales_amount or 0)

    return {
        "requests": {
            "total": row.req_total or 0,
            "pending": row.req_pending or 0,
            "shipping": row.req_shipping or 0,
            "completed": row.req_completed or 0
        },
        "imports": {
            "total": row.imp_count or 0,
            "total_amount": import_amount
        },
        "exports": {
            "total": row.exp_count or 0
        },
        "sales": {
            "total_amount": sales_amount
        },
        "cashflow": {
            "inflow": sales_amount,
            "outflow": import_amount,
            "net": sales_amount - import_amount
        }
    }


@router.get("/overview-combined")
async def get_overview_combined(
    warehouse_id: int = None,
    branch_id: int = None,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db)
):
    """Single endpoint combining stock-summary + dashboard-stats — 1 round-trip."""
    stock_data = await get_stock_summary(
        warehouse_id=warehouse_id, date_from=date_from, date_to=date_to, db=db
    )
    stats_data = await get_dashboard_stats(
        warehouse_id=warehouse_id, branch_id=branch_id,
        date_from=date_from, date_to=date_to, db=db
    )
    return {"stock": stock_data, "stats": stats_data}


@router.get("/product-history")
async def get_product_history(
    product_id: int,
    branch_id: int = None,
    warehouse_id: int = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    Get transaction history for a specific product.
    """
    
    query = db.query(StockMovement).options(
        joinedload(StockMovement.actor),
        joinedload(StockMovement.warehouse)
    ).join(Warehouse).filter(StockMovement.product_id == product_id)

    if warehouse_id:
        query = query.filter(StockMovement.warehouse_id == warehouse_id)
    elif branch_id:
        query = query.filter(Warehouse.branch_id == branch_id)

    # Sort by Newest first
    query = query.order_by(desc(StockMovement.created_at)).limit(limit)

    movements = query.all()

    # Collect IDs for batch fetching
    receipt_ids = set()
    transfer_ids = set()

    for m in movements:
        if m.ref_ticket_id:
            # Simple heuristic based on known types
            if m.transaction_type in ['IMPORT_PO']:
                receipt_ids.add(m.ref_ticket_id)
            elif m.transaction_type in ['IMPORT_TRANSFER', 'EXPORT_TRANSFER', 'TRANSIT_TO_DEST', 'TRANSFER_TO_TRANSIT']:
                transfer_ids.add(m.ref_ticket_id)

    # Fetch Codes
    code_map = {}
    
    if receipt_ids:
        receipts = db.query(InventoryReceipt.id, InventoryReceipt.code).filter(InventoryReceipt.id.in_(receipt_ids)).all()
        for r in receipts:
            code_map[f"IMPORT_{r.id}"] = r.code

    if transfer_ids:
        transfers = db.query(InventoryTransfer.id, InventoryTransfer.code).filter(InventoryTransfer.id.in_(transfer_ids)).all()
        for t in transfers:
            code_map[f"TRANSFER_{t.id}"] = t.code
    
    return [
        {
            "id": m.id,
            "created_at": m.created_at.isoformat(),
            "type": m.transaction_type,
            "quantity_change": float(m.quantity_change),
            "balance_after": float(m.balance_after),
            "warehouse_name": m.warehouse.name,
            "actor_name": m.actor.name if m.actor else "System",
            "ref_ticket_id": m.ref_ticket_id, # Return raw ID for linking
            "ref_ticket_type": m.transaction_type, # Use type to determine link target
            "ref_code": code_map.get(f"IMPORT_{m.ref_ticket_id}", code_map.get(f"TRANSFER_{m.ref_ticket_id}", "N/A")) if m.ref_ticket_id else "N/A"
        }
        for m in movements
    ]
