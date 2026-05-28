from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import desc, text as sa_text
from datetime import datetime

from ...db.session import get_db
from ...db.models import (
    InventoryTransfer, InventoryTransferItem, TicketStatus, InventoryReceipt,
    Branch, Warehouse,
)

router = APIRouter()

@router.get("/page-init")
async def get_page_init(
    request: Request,
    warehouse_id: int = None,
    date_from: str = None,
    date_to: str = None,
    page: int = 1,
    per_page: int = 10,
    db: Session = Depends(get_db)
):
    """Combined init: approvals (PENDING) + imports list. Replaces 2 separate requests."""
    from ...core.utils import VN_TZ

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

    # 1. Approvals (PENDING)
    aq = db.query(InventoryTransfer).options(
        selectinload(InventoryTransfer.items).joinedload(InventoryTransferItem.product),
        joinedload(InventoryTransfer.dest_warehouse),
        joinedload(InventoryTransfer.source_warehouse),
        joinedload(InventoryTransfer.requester),
        selectinload(InventoryTransfer.compensation_transfers)
    ).filter(InventoryTransfer.status == TicketStatus.PENDING)

    if warehouse_id:
        aq = aq.filter(InventoryTransfer.source_warehouse_id == warehouse_id)
    # Active pending approvals should not be filtered by date range so they do not get hidden on initial load

    total_approvals = aq.count()
    approvals = aq.order_by(desc(InventoryTransfer.created_at)).offset((page - 1) * per_page).limit(per_page).all()

    approvals_data = []
    for t in approvals:
        items = [{"id": i.id, "product_id": i.product_id, "product_name": i.product.name,
                  "category_id": i.product.category_id,
                  "category_name": i.product.category.name if i.product.category else "Other",
                  "request_quantity": float(i.request_quantity), "request_unit": i.request_unit,
                  "approved_quantity": float(i.approved_quantity) if i.approved_quantity else None,
                  "received_quantity": float(i.received_quantity) if i.received_quantity is not None else 0,
                  "current_stock": 0, "loss_quantity": 0, "loss_reason": ""} for i in t.items]
        approvals_data.append({
            "id": t.id, "code": t.code, "is_comp": False,
            "branch_name": t.dest_warehouse.name if t.dest_warehouse else "Unknown",
            "source_warehouse_name": t.source_warehouse.name if t.source_warehouse else "Kho Tổng",
            "source_warehouse_id": t.source_warehouse_id,
            "requester_name": t.requester.name if t.requester else "Unknown",
            "approver_name": "", "created_at": t.created_at.isoformat() if t.created_at else "",
            "approved_at": "", "approver_notes": t.approver_notes, "status": t.status,
            "notes": t.notes, "items": items, "has_shortage": False, "has_excess": False,
            "is_compensated_enough": False, "has_compensation": len(t.compensation_transfers) > 0,
            "compensation_history": [], "images": []
        })

    # 2. Imports
    iq = db.query(InventoryReceipt).options(
        joinedload(InventoryReceipt.creator),
        selectinload(InventoryReceipt.items)
    )
    if warehouse_id:
        iq = iq.filter(InventoryReceipt.warehouse_id == warehouse_id)
    if start_time:
        iq = iq.filter(InventoryReceipt.created_at >= start_time)
    if end_time:
        iq = iq.filter(InventoryReceipt.created_at <= end_time)

    total_imports = iq.count()
    imports = iq.order_by(desc(InventoryReceipt.created_at)).offset((page - 1) * per_page).limit(per_page).all()
    imports_data = [{
        "id": r.id,
        "code": r.code,
        "supplier_name": r.supplier_name or "",
        "creator_name": r.creator.name if r.creator else "N/A",
        "total_amount": float(r.total_amount or 0),
        "notes": r.notes or "",
        "items_count": len(r.items),
        "created_at": r.created_at.isoformat() if r.created_at else ""
    } for r in imports]

    return {
        "approvals": {"records": approvals_data, "totalRecords": total_approvals,
                      "totalPages": (total_approvals + per_page - 1) // per_page,
                      "currentPage": page, "pendingCount": total_approvals},
        "imports": {"records": imports_data, "totalRecords": total_imports,
                    "totalPages": (total_imports + per_page - 1) // per_page, "currentPage": page}
    }


@router.get("/page-load")
async def get_page_load(
    request: Request,
    perspective: str = "manager",
    warehouse_id: int = None,
    branch_id: int = None,
    date_from: str = None,
    date_to: str = None,
    overview_date_from: str = None,
    overview_date_to: str = None,
    page: int = 1,
    per_page: int = 10,
    db: Session = Depends(get_db)
):
    """Single endpoint for full page init: approvals + imports + overview stats."""
    from ...core.utils import VN_TZ

    is_reception = perspective == "reception"

    # Parse dates
    start_time = end_time = ov_start = ov_end = None
    try:
        if date_from:
            start_time = datetime.combine(datetime.strptime(date_from, "%Y-%m-%d").date(), datetime.min.time()).replace(tzinfo=VN_TZ)
        if date_to:
            end_time = datetime.combine(datetime.strptime(date_to, "%Y-%m-%d").date(), datetime.max.time()).replace(tzinfo=VN_TZ)
        if overview_date_from:
            ov_start = datetime.combine(datetime.strptime(overview_date_from, "%Y-%m-%d").date(), datetime.min.time()).replace(tzinfo=VN_TZ)
        if overview_date_to:
            ov_end = datetime.combine(datetime.strptime(overview_date_to, "%Y-%m-%d").date(), datetime.max.time()).replace(tzinfo=VN_TZ)
    except ValueError:
        pass

    # ── 1. Approvals (PENDING) ──
    aq = db.query(InventoryTransfer).options(
        selectinload(InventoryTransfer.items).joinedload(InventoryTransferItem.product),
        joinedload(InventoryTransfer.dest_warehouse),
        joinedload(InventoryTransfer.source_warehouse),
        joinedload(InventoryTransfer.requester),
        selectinload(InventoryTransfer.compensation_transfers)
    ).filter(InventoryTransfer.status == TicketStatus.PENDING)
    if is_reception and branch_id:
        source_branch = db.query(Branch).get(branch_id)
        is_admin_branch = source_branch and source_branch.branch_code.upper() in ['ADMIN', 'BOSS']
        if is_admin_branch:
            source_warehouses = db.query(Warehouse).filter(
                (Warehouse.branch_id == branch_id) |
                (Warehouse.branch_id.is_(None))
            ).all()
        else:
            source_warehouses = db.query(Warehouse).filter(Warehouse.branch_id == branch_id).all()
        source_warehouse_ids = [w.id for w in source_warehouses]
        if source_warehouse_ids:
            aq = aq.filter(InventoryTransfer.source_warehouse_id.in_(source_warehouse_ids))
        else:
            aq = aq.filter(False)
    elif warehouse_id:
        if is_reception:
            aq = aq.filter(InventoryTransfer.dest_warehouse_id == warehouse_id)
        else:
            aq = aq.filter(InventoryTransfer.source_warehouse_id == warehouse_id)
    # Active pending approvals should not be filtered by date range so they do not get hidden on initial load

    total_approvals = aq.count()
    approvals = aq.order_by(desc(InventoryTransfer.created_at)).offset((page - 1) * per_page).limit(per_page).all()
    approvals_data = []
    for t in approvals:
        items = [{"id": i.id, "product_id": i.product_id, "product_name": i.product.name,
                  "category_id": i.product.category_id,
                  "category_name": i.product.category.name if i.product.category else "Other",
                  "request_quantity": float(i.request_quantity), "request_unit": i.request_unit,
                  "approved_quantity": float(i.approved_quantity) if i.approved_quantity else None,
                  "received_quantity": float(i.received_quantity) if i.received_quantity is not None else 0,
                  "current_stock": 0, "loss_quantity": 0, "loss_reason": ""} for i in t.items]
        approvals_data.append({
            "id": t.id, "code": t.code, "is_comp": False,
            "branch_name": t.dest_warehouse.name if t.dest_warehouse else "Unknown",
            "source_warehouse_name": t.source_warehouse.name if t.source_warehouse else "Kho Tổng",
            "source_warehouse_id": t.source_warehouse_id,
            "requester_name": t.requester.name if t.requester else "Unknown",
            "approver_name": "", "created_at": t.created_at.isoformat() if t.created_at else "",
            "approved_at": "", "approver_notes": t.approver_notes, "status": t.status,
            "notes": t.notes, "items": items, "has_shortage": False, "has_excess": False,
            "is_compensated_enough": False, "has_compensation": len(t.compensation_transfers) > 0,
            "compensation_history": [], "images": []
        })

    # ── 2. Imports ──
    iq = db.query(InventoryReceipt).options(
        joinedload(InventoryReceipt.creator),
        selectinload(InventoryReceipt.items)
    )
    if warehouse_id:
        iq = iq.filter(InventoryReceipt.warehouse_id == warehouse_id)
    if start_time:
        iq = iq.filter(InventoryReceipt.created_at >= start_time)
    if end_time:
        iq = iq.filter(InventoryReceipt.created_at <= end_time)
    total_imports = iq.count()
    imports = iq.order_by(desc(InventoryReceipt.created_at)).offset((page - 1) * per_page).limit(per_page).all()
    imports_data = [{
        "id": r.id,
        "code": r.code,
        "supplier_name": r.supplier_name or "",
        "creator_name": r.creator.name if r.creator else "N/A",
        "total_amount": float(r.total_amount or 0),
        "notes": r.notes or "",
        "items_count": len(r.items),
        "created_at": r.created_at.isoformat() if r.created_at else ""
    } for r in imports]

    # ── 3. Overview stats (raw SQL single query) ──
    ov_params: dict = {}
    if is_reception:
        ov_wh_export = "it.dest_warehouse_id = :wh_id AND it.related_transfer_id IS NULL" if warehouse_id else "1=1"
    else:
        ov_wh_export = "it.source_warehouse_id = :wh_id AND it.related_transfer_id IS NULL" if warehouse_id else "1=1"
    ov_wh_dest = "it.dest_warehouse_id = :wh_id AND it.related_transfer_id IS NULL" if warehouse_id else "1=1"
    ov_wh_ir = "ir.warehouse_id = :wh_id" if warehouse_id else "1=1"
    ov_wh_sm = "sm.warehouse_id = :wh_id" if warehouse_id else "1=1"
    if warehouse_id:
        ov_params["wh_id"] = warehouse_id
    ov_date_it = ""
    ov_date_ir = ""
    ov_date_sm = ""
    if ov_start:
        ov_date_it += " AND it.created_at >= :ov_start"
        ov_date_ir += " AND ir.created_at >= :ov_start"
        ov_date_sm += " AND sm.created_at >= :ov_start"
        ov_params["ov_start"] = ov_start
    if ov_end:
        ov_date_it += " AND it.created_at <= :ov_end"
        ov_date_ir += " AND ir.created_at <= :ov_end"
        ov_date_sm += " AND sm.created_at <= :ov_end"
        ov_params["ov_end"] = ov_end

    stats_sql = sa_text(f"""
        SELECT
            (SELECT COUNT(*) FROM inventory_transfers it WHERE {ov_wh_dest} {ov_date_it}) AS req_total,
            (SELECT COUNT(*) FROM inventory_transfers it WHERE {ov_wh_dest} AND it.status='PENDING') AS req_pending,
            (SELECT COUNT(*) FROM inventory_transfers it WHERE {ov_wh_dest} AND it.status='SHIPPING') AS req_shipping,
            (SELECT COUNT(*) FROM inventory_transfers it WHERE {ov_wh_dest} AND it.status='COMPLETED' {ov_date_it}) AS req_completed,
            (SELECT COUNT(*) FROM inventory_receipts ir WHERE {ov_wh_ir} {ov_date_ir}) AS imp_count,
            (SELECT COALESCE(SUM(ir.total_amount),0) FROM inventory_receipts ir WHERE {ov_wh_ir} {ov_date_ir}) AS imp_amount,
            (SELECT COALESCE(SUM(iti.received_quantity * p.cost_price),0)
             FROM inventory_transfer_items iti
             JOIN inventory_transfers it ON iti.transfer_id = it.id
             JOIN products p ON iti.product_id = p.id
             WHERE {ov_wh_dest} AND it.status='COMPLETED' {ov_date_it}) AS incoming_val,
            (SELECT COUNT(*) FROM inventory_transfers it WHERE {ov_wh_export} AND it.status='COMPLETED' {ov_date_it}) AS exp_count,
            (SELECT COALESCE(ABS(SUM(sm.quantity_change * p.sell_price)),0)
             FROM stock_movements sm
             JOIN products p ON sm.product_id = p.id
             WHERE sm.transaction_type IN ('EXPORT_SERVICE', 'VOID_SERVICE')
             AND {ov_wh_sm} {ov_date_sm}) AS sales_amount
    """)
    stats_row = db.execute(stats_sql, ov_params).fetchone()
    import_amount = float(stats_row.imp_amount or 0) + float(stats_row.incoming_val or 0)
    sales_amount = float(stats_row.sales_amount or 0)

    return {
        "approvals": {
            "records": approvals_data,
            "totalRecords": total_approvals,
            "totalPages": (total_approvals + per_page - 1) // per_page,
            "currentPage": page,
            "pendingCount": total_approvals
        },
        "imports": {
            "records": imports_data,
            "totalRecords": total_imports,
            "totalPages": (total_imports + per_page - 1) // per_page,
            "currentPage": page
        },
        "stats": {
            "requests": {"total": stats_row.req_total or 0, "pending": stats_row.req_pending or 0,
                         "shipping": stats_row.req_shipping or 0, "completed": stats_row.req_completed or 0},
            "imports": {"total": stats_row.imp_count or 0, "total_amount": import_amount},
            "exports": {"total": stats_row.exp_count or 0},
            "sales": {"total_amount": sales_amount},
            "cashflow": {
                "inflow": sales_amount,
                "outflow": import_amount,
                "net": sales_amount - import_amount
            }
        }
    }


@router.get("/reception-page-load")
async def get_reception_page_load(
    request: Request,
    warehouse_id: int = None,
    branch_id: int = None,
    date_from: str = None,
    date_to: str = None,
    overview_date_from: str = None,
    overview_date_to: str = None,
    page: int = 1,
    per_page: int = 10,
    db: Session = Depends(get_db)
):
    """Backward-compatible reception page init wrapper."""
    return await get_page_load(
        request=request,
        perspective="reception",
        warehouse_id=warehouse_id,
        branch_id=branch_id,
        date_from=date_from,
        date_to=date_to,
        overview_date_from=overview_date_from,
        overview_date_to=overview_date_to,
        page=page,
        per_page=per_page,
        db=db,
    )
