from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case, desc
from datetime import datetime

from ...db.session import get_db
from ...db.models import Product, InventoryLevel, Warehouse, InventoryTransfer, InventoryReceipt, TicketStatus, StockMovement, InventoryTransferItem
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
    """
    Lấy thống kê tồn kho theo tháng với tồn đầu, nhập, xuất, tồn cuối
    """
    # Parse date range
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

    # Get current inventory levels (closing balance)
    query = db.query(InventoryLevel).options(
        joinedload(InventoryLevel.product)
    ).filter(InventoryLevel.warehouse_id == warehouse_id)
    
    stocks = query.all()
    
    result = []
    for stock in stocks:
        if not stock.product.is_active and stock.quantity <= 0:
            continue
        
        product_id = stock.product_id
        closing_balance = float(stock.quantity)
        
        # Calculate imports and exports in the period from StockMovement
        movements_query = db.query(StockMovement).filter(
            StockMovement.product_id == product_id,
            StockMovement.warehouse_id == warehouse_id
        )
        
        if start_time:
            movements_query = movements_query.filter(StockMovement.created_at >= start_time)
        if end_time:
            movements_query = movements_query.filter(StockMovement.created_at <= end_time)
        
        movements = movements_query.all()
        
        total_import = 0.0
        total_export = 0.0
        
        for m in movements:
            if m.quantity_change > 0:
                total_import += float(m.quantity_change)
            else:
                total_export += abs(float(m.quantity_change))
        
        # Calculate opening balance: closing - (imports - exports)
        opening_balance = closing_balance - (total_import - total_export)
        
        result.append({
            "product_id": product_id,
            "product_name": stock.product.name,
            "product_code": stock.product.code,
            "base_unit": stock.product.base_unit,
            "packing_unit": stock.product.packing_unit,
            "conversion_rate": stock.product.conversion_rate,
            "category_id": stock.product.category_id,
            "opening_balance": round(opening_balance, 2),
            "total_import": round(total_import, 2),
            "total_export": round(total_export, 2),
            "closing_balance": round(closing_balance, 2),
            "min_stock": stock.min_stock,
            "status": "Cảnh báo" if stock.quantity <= stock.min_stock else "Ổn định"
        })
    
    return {"data": result}


@router.get("/dashboard-stats")
async def get_dashboard_stats(

    branch_id: int = None, # Deprecated
    warehouse_id: int = None, # [NEW]
    date_from: str = None, 
    date_to: str = None,
    db: Session = Depends(get_db)
):
    """
    Optimized endpoint for dashboard statistics.
    Aggregates request counts and import totals in a single response.
    """
    
    # 1. Date Range Filter
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

    # 2. Requests Stats (Aggregation)
    # Filter by branch (destination warehouse) if branch_id is provided
    # Only count requests related to this branch (inbound)
    req_query = db.query(
        func.count(InventoryTransfer.id).label("total"),
        func.sum(case((InventoryTransfer.status == TicketStatus.PENDING, 1), else_=0)).label("pending"),
        func.sum(case((InventoryTransfer.status == TicketStatus.SHIPPING, 1), else_=0)).label("shipping"),
        func.sum(case((InventoryTransfer.status == TicketStatus.COMPLETED, 1), else_=0)).label("completed")
    )

    if warehouse_id:
        # Filter requests where destination is this warehouse
        req_query = req_query.filter(InventoryTransfer.dest_warehouse_id == warehouse_id)
        # Hide compensation tickets from owned list logic (same as list API)
        req_query = req_query.filter(InventoryTransfer.related_transfer_id.is_(None))
    elif branch_id:
        req_query = req_query.join(Warehouse, InventoryTransfer.dest_warehouse_id == Warehouse.id)\
                             .filter(Warehouse.branch_id == branch_id)
        # Hide compensation tickets from owned list logic (same as list API)
        req_query = req_query.filter(InventoryTransfer.related_transfer_id.is_(None))

    if start_time:
        req_query = req_query.filter(InventoryTransfer.created_at >= start_time)
    if end_time:
        req_query = req_query.filter(InventoryTransfer.created_at <= end_time)

    req_stats = req_query.first()

    # 3. Import Stats
    # Filter by branch (warehouse)
    imp_query = db.query(
        func.count(InventoryReceipt.id).label("total_count"),
        func.sum(InventoryReceipt.total_amount).label("total_amount")
    )

    if warehouse_id:
        imp_query = imp_query.filter(InventoryReceipt.warehouse_id == warehouse_id)
    elif branch_id:
        imp_query = imp_query.join(Warehouse, InventoryReceipt.warehouse_id == Warehouse.id)\
                             .filter(Warehouse.branch_id == branch_id)

    if start_time:
        imp_query = imp_query.filter(InventoryReceipt.created_at >= start_time)
    if end_time:
        imp_query = imp_query.filter(InventoryReceipt.created_at <= end_time)

    imp_stats = imp_query.first()
    
    # 3.1 Calculate Transfer Values (Received & Sent)
    # Incoming Transfers (Received Value)
    incoming_val_query = db.query(
        func.sum(InventoryTransferItem.received_quantity * Product.cost_price).label("total_value")
    ).join(InventoryTransferItem.transfer)\
     .join(InventoryTransferItem.product)\
     .filter(InventoryTransfer.status == TicketStatus.COMPLETED)

    # Outgoing Transfers (Sent Value)
    outgoing_val_query = db.query(
        func.sum(InventoryTransferItem.approved_quantity * Product.cost_price).label("total_value")
    ).join(InventoryTransferItem.transfer)\
     .join(InventoryTransferItem.product)\
     .filter(InventoryTransfer.status == TicketStatus.COMPLETED)

    if warehouse_id:
        incoming_val_query = incoming_val_query.filter(InventoryTransfer.dest_warehouse_id == warehouse_id)
        outgoing_val_query = outgoing_val_query.filter(InventoryTransfer.source_warehouse_id == warehouse_id)
        # Exclude compensations
        incoming_val_query = incoming_val_query.filter(InventoryTransfer.related_transfer_id.is_(None))
        outgoing_val_query = outgoing_val_query.filter(InventoryTransfer.related_transfer_id.is_(None))
    elif branch_id:
        incoming_val_query = incoming_val_query.join(Warehouse, InventoryTransfer.dest_warehouse_id == Warehouse.id)\
                                               .filter(Warehouse.branch_id == branch_id)
        outgoing_val_query = outgoing_val_query.join(Warehouse, InventoryTransfer.source_warehouse_id == Warehouse.id)\
                                               .filter(Warehouse.branch_id == branch_id)
        # Exclude compensations
        incoming_val_query = incoming_val_query.filter(InventoryTransfer.related_transfer_id.is_(None))
        outgoing_val_query = outgoing_val_query.filter(InventoryTransfer.related_transfer_id.is_(None))

    if start_time:
        incoming_val_query = incoming_val_query.filter(InventoryTransfer.created_at >= start_time)
        outgoing_val_query = outgoing_val_query.filter(InventoryTransfer.created_at >= start_time)
    if end_time:
        incoming_val_query = incoming_val_query.filter(InventoryTransfer.created_at <= end_time)
        outgoing_val_query = outgoing_val_query.filter(InventoryTransfer.created_at <= end_time)

    incoming_val = incoming_val_query.scalar() or 0
    outgoing_val = outgoing_val_query.scalar() or 0
    
    total_transaction_value = float(imp_stats.total_amount or 0) + float(incoming_val)
    # NOTE: User requested to EXCLUDE outgoing value (Sent Transfers) from "Import Value" for Main Warehouse accuracy.
    # logical: Import Value = Direct Imports + Received Transfers. 


    # 4. Export Stats (Completed exports from this warehouse)
    exp_query = db.query(
        func.count(InventoryTransfer.id).label("total_count")
    ).filter(InventoryTransfer.status == TicketStatus.COMPLETED)

    if warehouse_id:
        # Filter exports where source is this warehouse
        exp_query = exp_query.filter(InventoryTransfer.source_warehouse_id == warehouse_id)
        # Exclude compensation tickets
        exp_query = exp_query.filter(InventoryTransfer.related_transfer_id.is_(None))
    elif branch_id:
        exp_query = exp_query.join(Warehouse, InventoryTransfer.source_warehouse_id == Warehouse.id)\
                             .filter(Warehouse.branch_id == branch_id)
        # Exclude compensation tickets
        exp_query = exp_query.filter(InventoryTransfer.related_transfer_id.is_(None))

    if start_time:
        exp_query = exp_query.filter(InventoryTransfer.created_at >= start_time)
    if end_time:
        exp_query = exp_query.filter(InventoryTransfer.created_at <= end_time)

    exp_stats = exp_query.first()

    return {
        "requests": {
            "total": req_stats.total or 0,
            "pending": req_stats.pending or 0,
            "shipping": req_stats.shipping or 0,
            "completed": req_stats.completed or 0
        },
        "imports": {
            "total": imp_stats.total_count or 0,
            "total_amount": total_transaction_value
        },
        "exports": {
            "total": exp_stats.total_count or 0
        }
    }

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
