from fastapi import APIRouter, Request, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import desc, func, or_
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone
from decimal import Decimal

from ...db.session import get_db
from ...db.models import (
    Branch, Product, InventoryLevel, StockMovement, Warehouse,
    InventoryTransfer, InventoryTransferItem, TicketStatus, TransactionTypeWMS, User,
    InventoryReceipt, InventoryReceiptItem, TransferImage
)
from ...core.image_optimizer import ImageOptimizer

from .schemas import (
    RequestItemSchema, RequestTicketSchema, UpdateRequestTicketSchema,
    ApproveItemSchema, ApproveTicketSchema,
    DirectTransferItemSchema, DirectTransferSchema,
    UpdateDirectExportItemSchema, UpdateDirectExportSchema,
    ReceiveItemSchema, ReceiveTicketSchema,
)

router = APIRouter()

@router.post("/request")
async def create_request_ticket(
    payload: RequestTicketSchema,
    request: Request,
    db: Session = Depends(get_db)
):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Chưa đăng nhập")

    # 1. Xác định Kho Nguồn (Cho phép chọn hoặc default là MAIN/ADMIN)
    if payload.source_warehouse_id:
        source_warehouse = db.query(Warehouse).get(payload.source_warehouse_id)
        if not source_warehouse:
            raise HTTPException(status_code=404, detail="Kho nguồn không tồn tại")
    else:
        # [FIX] Default behavior: Priority Admin Branch's Warehouse -> Main Warehouse -> First Available
        # Find Admin Branch first
        admin_branch = db.query(Branch).filter(Branch.branch_code.in_(['ADMIN', 'BOSS', 'HEAD', 'TONG'])).first()
        if admin_branch:
            source_warehouse = db.query(Warehouse).filter(Warehouse.branch_id == admin_branch.id).first()
        
        if not source_warehouse:
            source_warehouse = db.query(Warehouse).filter(Warehouse.type == 'MAIN').first()
            
        if not source_warehouse:
            source_warehouse = db.query(Warehouse).first() 
        
    if not source_warehouse:
        raise HTTPException(
            status_code=400, 
            detail="Hệ thống chưa có dữ liệu Kho (Warehouse). Vui lòng liên hệ Admin để khởi tạo."
        )

    # 2. Kho Đích
    # 2. Kho Đích (Sử dụng ID từ payload do Frontend gửi - đã qua chọn lọc)
    if payload.dest_warehouse_id:
        dest_warehouse = db.query(Warehouse).get(payload.dest_warehouse_id)
        if not dest_warehouse:
            raise HTTPException(status_code=404, detail="Kho đích không tồn tại")
    else:
        # Fallback (Legacy): Infer from Session
        active_branch_code = request.session.get("active_branch") or user_data.get("branch")
        if not active_branch_code:
             raise HTTPException(status_code=400, detail="Không xác định được Kho đích (vui lòng chọn kho).")
             
        branch_obj = db.query(Branch).filter(Branch.branch_code == active_branch_code).first()
        if branch_obj:
            dest_warehouse = db.query(Warehouse).filter(Warehouse.branch_id == branch_obj.id).first()
        else:
            dest_warehouse = None
            
        if not dest_warehouse:
             # Last resort: Main Warehouse? No, Request must have explicit Dest.
             raise HTTPException(status_code=400, detail="Không tìm thấy Kho đích hợp lệ.")
    
    if source_warehouse.id == dest_warehouse.id:
        raise HTTPException(status_code=400, detail="Kho nguồn và kho đích không được trùng nhau.")

    # 3. Tạo phiếu
    code = f"REQ_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    ticket = InventoryTransfer(
        code=code,
        source_warehouse_id=source_warehouse.id,
        dest_warehouse_id=dest_warehouse.id,
        requester_id=user_data['id'],
        status=TicketStatus.PENDING,
        notes=payload.notes
    )
    db.add(ticket)
    db.flush()

    for item in payload.items:
        t_item = InventoryTransferItem(
            transfer_id=ticket.id,
            product_id=item.product_id,
            request_quantity=item.quantity,
            request_unit=item.unit
        )
        db.add(t_item)
    
    db.commit()
    return {"status": "success", "message": "Đã gửi yêu cầu thành công!"}

@router.get("/request/{ticket_id}")
async def get_request_detail(
    ticket_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Fetch details of a single request ticket by ID.
    Used for displaying details in modals (e.g. from history view).
    """
    try:
        # Re-use the query structure from get_request_tickets for consistency
        query = db.query(InventoryTransfer).options(
            joinedload(InventoryTransfer.items).joinedload(InventoryTransferItem.product).joinedload(Product.category),
            joinedload(InventoryTransfer.dest_warehouse),
            joinedload(InventoryTransfer.source_warehouse),
            joinedload(InventoryTransfer.requester),
            joinedload(InventoryTransfer.approver_user),
            joinedload(InventoryTransfer.dest_warehouse), # [NEW] Load Dest for Compensation too
            joinedload(InventoryTransfer.source_warehouse), # [NEW] Load Source for Compensation too
            joinedload(InventoryTransfer.compensation_transfers).joinedload(InventoryTransfer.items).joinedload(InventoryTransferItem.product).joinedload(Product.category)
        ).filter(InventoryTransfer.id == ticket_id)
        
        t = query.first()
        if not t:
            raise HTTPException(status_code=404, detail="Phiếu không tìm thấy")

        # Logic copied from `get_request_tickets` loop to format ONE ticket
        
        # 1. Related IDs family
        related_ids_family = [t.id]
        if t.compensation_transfers:
                related_ids_family.extend([ct.id for ct in t.compensation_transfers])
        
        # 2. Batch Transaction Map (for this specific family only)
        # Since it's a single detail view, we can just query for this family specifically
        tx_map = {}
        if t.status != TicketStatus.PENDING:
            batch_txs = db.query(StockMovement).filter(
                StockMovement.ref_ticket_id.in_(related_ids_family),
                StockMovement.transaction_type == TransactionTypeWMS.IMPORT_TRANSFER,
                StockMovement.ref_ticket_type == 'TRANSFER_IN'
            ).all()
            for tx in batch_txs:
                tid = tx.ref_ticket_id
                if tid not in tx_map: tx_map[tid] = {}
                pid = tx.product_id
                qty = float(tx.quantity_change)
                tx_map[tid][pid] = tx_map[tid].get(pid, 0.0) + qty

        def get_received_qty_from_map_local(ticket_ids_to_check, product_id):
            total = 0.0
            for tid in ticket_ids_to_check:
                if tid in tx_map and product_id in tx_map[tid]:
                    total += tx_map[tid][product_id]
            return total

        # 3. Status checks
        product_stats = {} 
        has_shortage = False
        has_excess = False
        
        if t.status != TicketStatus.PENDING:
            for i in t.items:
                    pid = i.product_id
                    if pid not in product_stats: product_stats[pid] = {"approved": 0, "received": 0}
                    
                    approved_qty = float(i.approved_quantity) if i.approved_quantity else 0
                    cum_received = get_received_qty_from_map_local(related_ids_family, pid)
                    
                    product_stats[pid]["approved"] += approved_qty
                    product_stats[pid]["received"] = cum_received
            
            if t.status == TicketStatus.COMPLETED:
                tolerance = 0.01
                for pid, stats in product_stats.items():
                    if stats["received"] < (stats["approved"] - tolerance):
                        has_shortage = True
                    elif stats["received"] > (stats["approved"] + tolerance):
                        has_excess = True



        # 4. [FIX] Fetch Current Stock (Smart Aggregation for Main/Admin)
        stock_map_local = {}
        if t.source_warehouse_id:
             # Identify if Source is "Hub" (Main or Admin)
             source_wh = t.source_warehouse
             is_hub = False
             if source_wh:
                 if source_wh.type == 'MAIN': is_hub = True
                 elif source_wh.branch and source_wh.branch.branch_code.upper() in ['ADMIN', 'BOSS', 'HEAD']: is_hub = True
             
             related_wh_ids = [t.source_warehouse_id]
             
             if is_hub:
                 # Find ALL Hub Warehouses
                 hub_warehouses = db.query(Warehouse).outerjoin(Branch).filter(
                     or_(
                         Warehouse.type == 'MAIN',
                         Branch.branch_code.in_(['ADMIN', 'BOSS', 'HEAD', 'HỆ THỐNG']),
                         Warehouse.branch_id.is_(None)
                     )
                 ).all()
                 related_wh_ids = list(set([w.id for w in hub_warehouses]))
             
             pids = [i.product_id for i in t.items]
             s_stocks = db.query(InventoryLevel).filter(
                 InventoryLevel.warehouse_id.in_(related_wh_ids),
                 InventoryLevel.product_id.in_(pids)
             ).all()
             
             for s in s_stocks:
                 current = stock_map_local.get(s.product_id, 0.0)
                 stock_map_local[s.product_id] = current + float(s.quantity)

        items = []
        for i in t.items:
            display_approved_qty = float(i.approved_quantity) if i.approved_quantity else 0
            display_received_qty = float(i.received_quantity) if i.received_quantity is not None else 0
            
            if i.request_unit == i.product.packing_unit and i.product.conversion_rate > 1:
                display_approved_qty = display_approved_qty / float(i.product.conversion_rate)
                display_received_qty = display_received_qty / float(i.product.conversion_rate)

            # [NEW] Current Stock
            current_stock_base = stock_map_local.get(i.product_id, 0.0)
            display_current_stock = current_stock_base
            
            if i.request_unit == i.product.packing_unit and i.product.conversion_rate > 1:
                display_current_stock = int(display_current_stock // float(i.product.conversion_rate))

            items.append({
                "id": i.id,
                "product_id": i.product_id,
                "product_name": i.product.name,
                "category_id": i.product.category_id,
                "category_name": i.product.category.name if i.product.category else "Other",
                "request_quantity": float(i.request_quantity),
                "request_unit": i.request_unit,
                "approved_quantity": round(display_approved_qty, 2),
                "received_quantity": round(display_received_qty, 2),
                "current_stock": round(display_current_stock, 2),
                "loss_quantity": float(i.loss_quantity) if i.loss_quantity is not None else 0.0,
                "loss_reason": i.loss_reason if i.loss_reason else ""
            })

        has_completed_comp = any(ct.status == TicketStatus.COMPLETED for ct in t.compensation_transfers)
        is_compensated_enough = has_completed_comp and not has_shortage and not has_excess

        return {
            "id": t.id,
            "code": t.code,
            "branch_name": t.dest_warehouse.name if t.dest_warehouse else "Unknown",
            "source_warehouse_name": t.source_warehouse.name if t.source_warehouse else "Kho Tổng",
            "source_warehouse_id": t.source_warehouse_id,
            "requester_name": t.requester.name if t.requester else "Unknown",
            "approver_name": t.approver_user.name if t.approver_user else "",
            "created_at": t.created_at.isoformat() if t.created_at else "",
            "approved_at": t.approved_at.isoformat() if t.approved_at else "",
            "approver_notes": t.approver_notes, 
            "status": t.status,
            "notes": t.notes,
            "items": items,
            "has_shortage": has_shortage,
            "has_excess": has_excess,
            "is_compensated_enough": is_compensated_enough,
            "has_compensation": len(t.compensation_transfers) > 0,
            "compensation_history": [
                {
                    "id": ct.id,
                    "code": ct.code,
                    "created_at": ct.created_at.isoformat() if ct.created_at else "",
                    "status": ct.status,
                    # [NEW] Add Warehouse Names for Child Ticket
                    "branch_name": ct.dest_warehouse.name if ct.dest_warehouse else "Unknown",
                    "source_warehouse_name": ct.source_warehouse.name if ct.source_warehouse else "Kho Tổng",
                    "requester_name": ct.requester.name if ct.requester else "Unknown",
                    "approver_name": ct.approver_user.name if ct.approver_user else "",
                    "items": [
                        {
                            "id": cti.id,
                            "product_id": cti.product_id,
                            "product_name": cti.product.name,
                            "category_name": cti.product.category.name if cti.product.category else "Other",
                            "request_quantity": float(cti.request_quantity),
                            "request_unit": cti.request_unit,
                            "approved_quantity": round(
                                float(cti.approved_quantity) / float(cti.product.conversion_rate), 2
                            ) if (cti.approved_quantity and cti.request_unit == cti.product.packing_unit and cti.product.conversion_rate > 1) 
                            else (float(cti.approved_quantity) if cti.approved_quantity else 0),
                            "received_quantity": round(
                                float(cti.received_quantity) / float(cti.product.conversion_rate), 2
                            ) if (cti.received_quantity and cti.request_unit == cti.product.packing_unit and cti.product.conversion_rate > 1) 
                            else (float(cti.received_quantity) if cti.received_quantity else 0)
                        } for cti in ct.items
                    ]
                } for ct in t.compensation_transfers
            ],
            "images": [
                {
                    "id": img.id,
                    "file_path": "/" + img.file_path if img.file_path and not img.file_path.startswith("/") else img.file_path,
                    "thumbnail_path": "/" + img.thumbnail_path if img.thumbnail_path and not img.thumbnail_path.startswith("/") else img.thumbnail_path,
                    "thumbnail_path": "/" + img.thumbnail_path if img.thumbnail_path and not img.thumbnail_path.startswith("/") else img.thumbnail_path,
                    "file_size": img.file_size,
                    "width": img.width,
                    "height": img.height,
                    "uploaded_at": img.uploaded_at.isoformat() if img.uploaded_at else ""
                } for img in t.images
            ]
        }
    except Exception as e:
        print(f"Error fetching request detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/requests")
async def get_request_tickets(
    status: str = None,
    branch_id: int = None, # Deprecated (Destination Branch context)
    source_branch_id: int = None, # Deprecated (Source Branch context)
    dest_warehouse_id: int = None, # Filter requests sent TO this warehouse (My Requests)
    source_warehouse_id: int = None, # [NEW] Filter requests sent FROM this warehouse (Approvals)
    date_from: str = None, 
    date_to: str = None,   
    search: str = None,
    requester_name: str = None, # [NEW]
    page: int = 1,
    per_page: int = 10,
    sort_by: str = 'created_at',
    sort_order: str = 'desc',
    db: Session = Depends(get_db)
):
    # Enforce Pagination
    if not page or page < 1: page = 1
    
    query = db.query(InventoryTransfer).options(
        selectinload(InventoryTransfer.items).joinedload(InventoryTransferItem.product),
        joinedload(InventoryTransfer.dest_warehouse),
        joinedload(InventoryTransfer.source_warehouse),
        joinedload(InventoryTransfer.requester),
        joinedload(InventoryTransfer.approver_user),
        # [NEW] Eager load compensation tickets
        selectinload(InventoryTransfer.compensation_transfers).joinedload(InventoryTransfer.items)
    )
    
    # [FIXED] Parent-Child Logic will be applied conditionally below
    
    if status:
        if ',' in status:
            status_list = status.split(',')
            query = query.filter(InventoryTransfer.status.in_(status_list))
        else:
            query = query.filter(InventoryTransfer.status == status)
    
    # [OPT] Check optimization flag
    is_pending_only = (status == 'PENDING')
    
    # Filter by destination warehouse (Current User's Warehouse Context)
    if dest_warehouse_id:
        query = query.filter(InventoryTransfer.dest_warehouse_id == dest_warehouse_id)
        # [IMPORTANT] Only hide compensation tickets when viewing OWN requests
        query = query.filter(InventoryTransfer.related_transfer_id.is_(None))
    elif branch_id:
        warehouses_in_branch = db.query(Warehouse).filter(Warehouse.branch_id == branch_id).all()
        warehouse_ids = [w.id for w in warehouses_in_branch]
        if not warehouse_ids:
            return {"records": [], "totalRecords": 0, "totalPages": 0, "currentPage": page}
        query = query.filter(InventoryTransfer.dest_warehouse_id.in_(warehouse_ids))
        # [IMPORTANT] Only hide compensation tickets when viewing OWN requests
        query = query.filter(InventoryTransfer.related_transfer_id.is_(None))
    
    # Filter by source warehouse (Requests TO BE APPROVED by this warehouse)
    if source_warehouse_id:
        query = query.filter(InventoryTransfer.source_warehouse_id == source_warehouse_id)
        # [IMPORTANT] Do NOT hide compensation tickets - they must appear for approval!
    elif source_branch_id:
        # [MODIFIED] If Admin, also include warehouses with NO branch (e.g. legacy Main Warehouse)
        source_branch = db.query(Branch).get(source_branch_id)
        is_admin_branch = source_branch and source_branch.branch_code.upper() in ['ADMIN', 'BOSS']
        
        if is_admin_branch:
            source_warehouses = db.query(Warehouse).filter(
                (Warehouse.branch_id == source_branch_id) | 
                (Warehouse.branch_id.is_(None))
            ).all()
        else:
            source_warehouses = db.query(Warehouse).filter(Warehouse.branch_id == source_branch_id).all()
            
        source_warehouse_ids = [w.id for w in source_warehouses]
        if not source_warehouse_ids:
            return {"records": [], "totalRecords": 0, "totalPages": 0, "currentPage": page}
        query = query.filter(InventoryTransfer.source_warehouse_id.in_(source_warehouse_ids))
        # [IMPORTANT] Do NOT hide compensation tickets - they must appear for approval!

    # Filter by date range
    start_time = None
    end_time = None
    try:
        from ...core.utils import VN_TZ
        if date_from:
            f_date = datetime.strptime(date_from, "%Y-%m-%d").date()
            start_time = datetime.combine(f_date, datetime.min.time()).replace(tzinfo=VN_TZ)
        if date_to:
            t_date = datetime.strptime(date_to, "%Y-%m-%d").date()
            end_time = datetime.combine(t_date, datetime.max.time()).replace(tzinfo=VN_TZ)
    except ValueError:
        pass # Ignore invalid dates

    if start_time and end_time:
        query = query.filter(InventoryTransfer.created_at.between(start_time, end_time))
    elif start_time:
        query = query.filter(InventoryTransfer.created_at >= start_time)
    elif end_time:
        query = query.filter(InventoryTransfer.created_at <= end_time)

    # Search filter
    if search:
        search_term = f"%{search}%"
        # Join with necessary tables for comprehensive search
        query = query.outerjoin(InventoryTransfer.items).outerjoin(InventoryTransferItem.product)
        query = query.outerjoin(Warehouse, InventoryTransfer.dest_warehouse_id == Warehouse.id)
        query = query.filter(
            (InventoryTransfer.code.ilike(search_term)) |
            (Product.name.ilike(search_term)) |
            (InventoryTransfer.notes.ilike(search_term)) |
            (Warehouse.name.ilike(search_term))
        ).distinct()

    # [NEW] Filter by Requester Name
    if requester_name:
         # Explicit join if not already joined (though eager load might not be enough for filtering)
         # joinedload doesn't automatically allow filtering on related table without join
         query = query.join(InventoryTransfer.requester)
         query = query.filter(User.name.ilike(f"%{requester_name}%"))

    # [NEW] Dynamic Sorting
    if sort_by == 'source_warehouse':
        query = query.join(Warehouse, InventoryTransfer.source_warehouse_id == Warehouse.id)
        if sort_order == 'asc':
            query = query.order_by(Warehouse.name.asc())
        else:
            query = query.order_by(Warehouse.name.desc())
            
    elif sort_by == 'item_count':
        # Subquery to count items per ticket
        stmt = db.query(
            InventoryTransferItem.transfer_id, 
            func.count(InventoryTransferItem.id).label('count')
        ).group_by(InventoryTransferItem.transfer_id).subquery()
        
        query = query.outerjoin(stmt, InventoryTransfer.id == stmt.c.transfer_id)
        
        if sort_order == 'asc':
            query = query.order_by(stmt.c.count.asc())
        else:
            query = query.order_by(stmt.c.count.desc())
            
    elif sort_by == 'status':
        if sort_order == 'asc':
            query = query.order_by(InventoryTransfer.status.asc())
        else:
            query = query.order_by(InventoryTransfer.status.desc())
            
    # Default to created_at if no other match or explicitly requested
    else: 
        sort_column = InventoryTransfer.created_at
        if sort_order == 'asc':
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())
    
    # Pagination Logic
    total_records = query.count()
    total_pages = (total_records + per_page - 1) // per_page
    tickets = query.offset((page - 1) * per_page).limit(per_page).all()
    
    # =================================================================================
    # [OPTIMIZATION] BATCH LOAD TRANSACTIONS TO AVOID N+1 QUERIES
    # =================================================================================
    
    # 1. Collect all Ticket IDs (Parent and Children)
    all_ticket_ids = []
    for t in tickets:
        all_ticket_ids.append(t.id)
        if t.compensation_transfers:
             all_ticket_ids.extend([ct.id for ct in t.compensation_transfers])
             
    # 2. Batch Fetch Transactions (SKIP IF PENDING ONLY)
    # PENDING tickets have no transactions yet, so we can save a huge DB query here.
    tx_map = {}
    if not is_pending_only: 
        batch_txs = []
        if all_ticket_ids:
            batch_txs = db.query(StockMovement).filter(
                StockMovement.ref_ticket_id.in_(all_ticket_ids),
                StockMovement.transaction_type == TransactionTypeWMS.IMPORT_TRANSFER,
                StockMovement.ref_ticket_type == 'TRANSFER_IN'
            ).all()
            
        # 3. Map Transactions by Ticket ID -> Product ID
        for tx in batch_txs:
            tid = tx.ref_ticket_id
            if tid not in tx_map: tx_map[tid] = {}
            
            pid = tx.product_id
            qty = float(tx.quantity_change)
            tx_map[tid][pid] = tx_map[tid].get(pid, 0.0) + qty

    def get_received_qty_from_map(ticket_ids_to_check, product_id):
        if is_pending_only: return 0.0 # Optimization
        total = 0.0
        for tid in ticket_ids_to_check:
            if tid in tx_map and product_id in tx_map[tid]:
                total += tx_map[tid][product_id]
        return total

    # [NEW] Batch Fetch Stocks for Source Availability
    stock_keys = set()
    for t in tickets:
        if t.source_warehouse_id:
             for i in t.items:
                 stock_keys.add((t.source_warehouse_id, i.product_id))

    stock_map = {}
    if stock_keys:
         wh_ids = {k[0] for k in stock_keys}
         prod_ids = {k[1] for k in stock_keys}
         
         s_stocks = db.query(InventoryLevel).filter(
             InventoryLevel.warehouse_id.in_(wh_ids),
             InventoryLevel.product_id.in_(prod_ids)
         ).all()
         
         for s in s_stocks:
             stock_map[(s.warehouse_id, s.product_id)] = float(s.quantity)


    data = []
    for t in tickets:
        # Collect all related IDs for this specific ticket family
        related_ids_family = [t.id]
        if t.compensation_transfers:
             related_ids_family.extend([ct.id for ct in t.compensation_transfers])

        # [FIXED] Smart Compensation & Status Detection
        # Calculate totals per Product ID for correct status
        product_stats = {} # {product_id: {approved: 0, received: 0}}
        has_shortage = False
        has_excess = False
        
        # [OPT] Skip complex status calc for PENDING
        if not is_pending_only:
            for i in t.items:
                 pid = i.product_id
                 if pid not in product_stats: product_stats[pid] = {"approved": 0, "received": 0}
                 
                 approved_qty = float(i.approved_quantity) if i.approved_quantity else 0
                 
                 # Get cumulative received from the Batch Map
                 cum_received_qty_base = get_received_qty_from_map(related_ids_family, pid)
                 
                 product_stats[pid]["approved"] += approved_qty
                 product_stats[pid]["received"] = cum_received_qty_base
    
            # Determine Ticket-Level Status based on Product Aggregates
            if t.status == TicketStatus.COMPLETED:
                tolerance = 0.01
                for pid, stats in product_stats.items():
                    if stats["received"] < (stats["approved"] - tolerance):
                        has_shortage = True
                    elif stats["received"] > (stats["approved"] + tolerance):
                        has_excess = True

        items = []
        for i in t.items:
            # Row Display Logic
            approved_qty = float(i.approved_quantity) if i.approved_quantity else 0
            
            # Use 'received_quantity' from ITEM if available (what was entered in form), 
            # otherwise 0. We do NOT use the transaction cumulative sum for the individual row display
            # because that would sum up compensation receipts into the parent line, which is confusing if they are separate tickets.
            # HOWEVER, for "Shortage" alerting, we used the cumulative.
            
            display_received_qty = float(i.received_quantity) if i.received_quantity is not None else 0
            
            display_approved_qty = approved_qty
            
            if i.request_unit == i.product.packing_unit and i.product.conversion_rate > 1:
                display_approved_qty = display_approved_qty / float(i.product.conversion_rate)
                display_received_qty = display_received_qty / float(i.product.conversion_rate)

            # [NEW] Attach Current Stock Info
            current_stock_base = stock_map.get((t.source_warehouse_id, i.product_id), 0.0)
            display_current_stock = current_stock_base
            
            if i.request_unit == i.product.packing_unit and i.product.conversion_rate > 1:
                # [MODIFIED] User Req: Only show integer Boxes, ignore decimals/loose bottles
                display_current_stock = int(display_current_stock // float(i.product.conversion_rate))

            items.append({
                "id": i.id,
                "product_id": i.product_id,
                "product_name": i.product.name,
                "category_id": i.product.category_id, # [FIX] Add for Edit Modal
                "category_name": i.product.category.name if i.product.category else "Other",
                "request_quantity": float(i.request_quantity),
                "request_unit": i.request_unit,
                "approved_quantity": round(display_approved_qty, 2),
                "received_quantity": round(display_received_qty, 2),
                "current_stock": round(display_current_stock, 2),
                "loss_quantity": float(i.loss_quantity) if i.loss_quantity is not None else 0.0,
                "loss_reason": i.loss_reason if i.loss_reason else ""
            })

        # Smart Compensation Status
        has_completed_compensation = False
        has_compensation_tickets = len(t.compensation_transfers) > 0
        if has_compensation_tickets:
            for ct in t.compensation_transfers:
                if ct.status == TicketStatus.COMPLETED:
                    has_completed_compensation = True
                    break
        
        is_compensated_enough = False
        if has_completed_compensation and not has_shortage and not has_excess:
            is_compensated_enough = True
        
        data.append({
            "id": t.id,
            "code": t.code,
            "is_comp": False, 
            "branch_name": t.dest_warehouse.name if t.dest_warehouse else "Unknown",
            "source_warehouse_name": t.source_warehouse.name if t.source_warehouse else "Kho Tổng",
            "source_warehouse_id": t.source_warehouse_id, # [FIX] Add for Edit Modal
            "requester_name": t.requester.name if t.requester else "Unknown",
            "approver_name": t.approver_user.name if t.approver_user else "",
            "created_at": t.created_at.isoformat() if t.created_at else "",
            "approved_at": t.approved_at.isoformat() if t.approved_at else "",
            "approver_notes": t.approver_notes, 
            "status": t.status,
            "notes": t.notes,
            "items": items,
            "has_shortage": has_shortage,
            "has_excess": has_excess,
            "is_compensated_enough": is_compensated_enough,
            "has_compensation": has_compensation_tickets,
            "compensation_history": [
                {
                    "id": ct.id,
                    "code": ct.code,
                    "created_at": ct.created_at.isoformat() if ct.created_at else "",
                    "status": ct.status,
                    "items": [
                        {
                            "id": cti.id,
                            "product_id": cti.product_id,
                            "product_name": cti.product.name,
                            "category_id": cti.product.category_id, # [FIX] Add for Edit Modal
                            "category_name": cti.product.category.name if cti.product.category else "Other",
                            "request_quantity": float(cti.request_quantity),
                            "request_unit": cti.request_unit,
                            "approved_quantity": round(
                                float(cti.approved_quantity) / float(cti.product.conversion_rate), 2
                            ) if (cti.approved_quantity and cti.request_unit == cti.product.packing_unit and cti.product.conversion_rate > 1) 
                            else (float(cti.approved_quantity) if cti.approved_quantity else 0),
                            "received_quantity": round(
                                float(cti.received_quantity) / float(cti.product.conversion_rate), 2
                            ) if (cti.received_quantity and cti.request_unit == cti.product.packing_unit and cti.product.conversion_rate > 1) 
                            else (float(cti.received_quantity) if cti.received_quantity else 0)
                        } for cti in ct.items
                    ]
                } for ct in t.compensation_transfers
            ],
            "images": [
                {
                    "id": img.id,
                    "file_path": img.file_path,
                    "thumbnail_path": img.thumbnail_path,
                    "uploaded_at": img.uploaded_at.isoformat() if img.uploaded_at else ""
                } for img in t.images
            ]
        })

    return {
        "records": data,
        "totalRecords": total_records,
        "totalPages": total_pages,
        "currentPage": page
    }

@router.get("/requests/list")
async def get_request_tickets_list(
    status: str = None,
    source_warehouse_id: int = None,
    dest_warehouse_id: int = None,
    date_from: str = None, 
    date_to: str = None,   
    search: str = None,
    page: int = 1,
    per_page: int = 10,
    sort_by: str = 'created_at',
    sort_order: str = 'desc',
    db: Session = Depends(get_db)
):
    """
    Lightweight endpoint for list view - only essential data.
    Optimized for fast loading by avoiding unnecessary joins and data.
    """
    # Enforce Pagination
    if not page or page < 1: page = 1
    
    # Minimal eager loading - only what's needed for display
    query = db.query(InventoryTransfer).options(
        joinedload(InventoryTransfer.dest_warehouse),
        joinedload(InventoryTransfer.source_warehouse),
        joinedload(InventoryTransfer.requester)
    )
    
    # Filter by status
    if status:
        if ',' in status:
            status_list = status.split(',')
            query = query.filter(InventoryTransfer.status.in_(status_list))
        else:
            query = query.filter(InventoryTransfer.status == status)
    
    # Filter by destination warehouse
    if dest_warehouse_id:
        query = query.filter(InventoryTransfer.dest_warehouse_id == dest_warehouse_id)
        query = query.filter(InventoryTransfer.related_transfer_id.is_(None))
    
    # Filter by source warehouse
    if source_warehouse_id:
        query = query.filter(InventoryTransfer.source_warehouse_id == source_warehouse_id)
    
    # Filter by date range
    start_time = None
    end_time = None
    try:
        from ...core.utils import VN_TZ
        if date_from:
            f_date = datetime.strptime(date_from, "%Y-%m-%d").date()
            start_time = datetime.combine(f_date, datetime.min.time()).replace(tzinfo=VN_TZ)
        if date_to:
            t_date = datetime.strptime(date_to, "%Y-%m-%d").date()
            end_time = datetime.combine(t_date, datetime.max.time()).replace(tzinfo=VN_TZ)
    except ValueError:
        pass

    if start_time and end_time:
        query = query.filter(InventoryTransfer.created_at.between(start_time, end_time))
    elif start_time:
        query = query.filter(InventoryTransfer.created_at >= start_time)
    elif end_time:
        query = query.filter(InventoryTransfer.created_at <= end_time)

    # Search filter - simplified, no joins with items/products
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (InventoryTransfer.code.ilike(search_term)) |
            (InventoryTransfer.notes.ilike(search_term))
        )

    # Sorting
    if sort_by == 'code':
        sort_column = InventoryTransfer.code
    else:  # Default to created_at
        sort_column = InventoryTransfer.created_at
    
    if sort_order == 'asc':
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())
    
    # Pagination
    total_records = query.count()
    total_pages = (total_records + per_page - 1) // per_page
    tickets = query.offset((page - 1) * per_page).limit(per_page).all()
    
    # Return minimal data - only what's needed for list view
    data = []
    for t in tickets:
        data.append({
            "id": t.id,
            "code": t.code,
            "branch_name": t.dest_warehouse.name if t.dest_warehouse else "Unknown",
            "source_warehouse_name": t.source_warehouse.name if t.source_warehouse else "Kho Tổng",
            "requester_name": t.requester.name if t.requester else "Unknown",
            "created_at": t.created_at.isoformat() if t.created_at else "",
            "status": t.status,
            "notes": t.notes or ""
        })

    return {
        "records": data,
        "totalRecords": total_records,
        "totalPages": total_pages,
        "currentPage": page
    }


@router.post("/approve/{ticket_id}")
async def approve_ticket(
    ticket_id: int,
    payload: ApproveTicketSchema,
    request: Request,
    db: Session = Depends(get_db)
):
    """Duyệt phiếu chuyển kho"""
    from ...services.inventory_transfer_service import approve_ticket as svc_approve
    user_data = request.session.get("user")
    return svc_approve(db, ticket_id, payload, user_data['id'])


@router.post("/receive/{ticket_id}")
async def confirm_receipt(
    ticket_id: int,
    payload: ReceiveTicketSchema,
    request: Request,
    db: Session = Depends(get_db)
):
    """Xác nhận nhận hàng từ Phiếu Đang Giao (SHIPPING)"""
    from ...services.inventory_transfer_service import confirm_receipt as svc_confirm
    user_data = request.session.get("user")
    return svc_confirm(db, ticket_id, payload, user_data['id'])


@router.post("/reject/{ticket_id}")
async def reject_ticket(
    ticket_id: int,
    request: Request,
    db: Session = Depends(get_db),
    rejection_notes: str = None
):
    """Từ chối yêu cầu chuyển kho"""
    from ...services.inventory_transfer_service import reject_ticket as svc_reject
    user_data = request.session.get("user")
    return svc_reject(db, ticket_id, user_data['id'], rejection_notes)


@router.post("/transfers/direct")
async def create_direct_transfer(
    payload: DirectTransferSchema,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Xuất kho trực tiếp giữa các kho
    """
    user_data = request.session.get("user")
    user_id = user_data.get("id") if user_data else None

    # 1. Xác định Kho Nguồn
    if payload.source_warehouse_id:
        source_wh = db.query(Warehouse).get(payload.source_warehouse_id)
        if not source_wh:
             raise HTTPException(status_code=404, detail="Kho nguồn không tồn tại")
    else:
        source_wh = db.query(Warehouse).filter(Warehouse.type == 'MAIN').first()
        if not source_wh:
            raise HTTPException(status_code=400, detail="Chưa cấu hình Kho Tổng (MAIN)")
    
    # 2. Xác định Kho Đích
    dest_wh = db.query(Warehouse).get(payload.dest_warehouse_id)
    if not dest_wh:
        raise HTTPException(status_code=404, detail="Kho đích không tồn tại")
        
    if source_wh.id == dest_wh.id:
        raise HTTPException(status_code=400, detail="Kho nguồn và Kho đích không được trùng nhau")

    try:
        # 3. Tạo Transfer Ticket (Status = COMPLETED ngay lập tức)
        code = f"TR_DIR_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        ticket = InventoryTransfer(
            code=code,
            source_warehouse_id=source_wh.id,
            dest_warehouse_id=dest_wh.id,
            requester_id=user_id, 
            approver_id=user_id,
            status=TicketStatus.COMPLETED,
            notes=payload.notes or "Xuất kho trực tiếp",
            approved_at=datetime.now(timezone.utc)
        )
        db.add(ticket)
        db.flush()

        dest_stocks_cache = {} 

        for item in payload.items:
            product = db.query(Product).get(item.product_id)
            if not product: continue

            quantity_base = item.quantity
            if item.unit == product.packing_unit and product.conversion_rate > 1:
                quantity_base = item.quantity * product.conversion_rate
            
            quantity_base = Decimal(str(quantity_base))
            
            # 4a. Trừ kho Tổng (Nguồn)
            source_stock = db.query(InventoryLevel).filter_by(
                warehouse_id=source_wh.id, product_id=product.id
            ).with_for_update().first()

            if not source_stock or source_stock.quantity < quantity_base:
                raise HTTPException(status_code=400, detail=f"Kho tổng không đủ hàng: {product.name}")
            
            source_stock.quantity -= quantity_base
            
            trans_out = StockMovement(
                warehouse_id=source_wh.id,
                product_id=product.id,
                transaction_type=TransactionTypeWMS.EXPORT_TRANSFER,
                quantity_change=-quantity_base,
                balance_after=source_stock.quantity,
                ref_ticket_id=ticket.id,
                ref_ticket_type="InventoryTransfer",
                actor_id=user_id
            )
            db.add(trans_out)

            # 4b. Cộng kho Nhánh (Đích)
            dest_stock = None
            if product.id in dest_stocks_cache:
                dest_stock = dest_stocks_cache[product.id]
            else:
                dest_stock = db.query(InventoryLevel).filter_by(
                    warehouse_id=dest_wh.id, product_id=product.id
                ).with_for_update().first()

                if not dest_stock:
                    dest_stock = InventoryLevel(
                        warehouse_id=dest_wh.id,
                        product_id=product.id,
                        quantity=0,
                        min_stock=product.min_stock_global
                    )
                    db.add(dest_stock)
                    db.flush()
                
                dest_stocks_cache[product.id] = dest_stock
            
            dest_stock.quantity += quantity_base

            trans_in = StockMovement(
                warehouse_id=dest_wh.id,
                product_id=product.id,
                transaction_type=TransactionTypeWMS.IMPORT_TRANSFER,
                quantity_change=quantity_base,
                balance_after=dest_stock.quantity,
                ref_ticket_id=ticket.id,
                ref_ticket_type="InventoryTransfer",
                actor_id=user_id
            )
            db.add(trans_in)

            # 4c. Tạo Ticket Item Detail
            ticket_item = InventoryTransferItem(
                transfer_id=ticket.id,
                product_id=product.id,
                request_quantity=item.quantity, 
                request_unit=item.unit,
                approved_quantity=quantity_base 
            )
            db.add(ticket_item)

        db.commit()
        return {"status": "success", "message": f"Đã xuất kho trực tiếp cho {dest_wh.name}"}

    except HTTPException as e:
        raise e

@router.delete("/request/{ticket_id}")
async def delete_request_ticket(
    ticket_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Xóa yêu cầu chuyển kho (chỉ khi đang chờ duyệt)
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Chưa đăng nhập")

    ticket = db.query(InventoryTransfer).get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Phiếu yêu cầu không tồn tại")

    if ticket.status != TicketStatus.PENDING:
        raise HTTPException(status_code=400, detail="Chỉ có thể xóa phiếu khi đang ở trạng thái 'Chờ duyệt' (PENDING)")

    # Kiểm tra quyền: Chỉ người tạo hoặc Admin/Manager/Lễ tân mới được xóa
    if ticket.requester_id != user_data['id'] and user_data.get('role') not in ['admin', 'manager', 'quanly', 'boss', 'letan']:
        raise HTTPException(status_code=403, detail="Bạn không có quyền xóa phiếu này")

    try:
        # Xóa các items trước (cascade delete thường đã handle, nhưng explicit cho chắc nếu chưa config)
        # SQLAlchemy relationship cascade="all, delete-orphan" đã được set trong models.py
        
        db.delete(ticket)
        db.commit()
        return {"status": "success", "message": "Đã xóa yêu cầu thành công"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Lỗi khi xóa phiếu: {str(e)}")

@router.put("/request/{ticket_id}")
async def update_request_ticket(
    ticket_id: int,
    payload: UpdateRequestTicketSchema,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Cập nhật yêu cầu chuyển kho (chỉ khi đang chờ duyệt)
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Chưa đăng nhập")

    ticket = db.query(InventoryTransfer).get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Phiếu yêu cầu không tồn tại")

    if ticket.status != TicketStatus.PENDING:
        raise HTTPException(status_code=400, detail="Chỉ có thể cập nhật phiếu khi đang ở trạng thái 'Chờ duyệt' (PENDING)")

    if ticket.requester_id != user_data['id'] and user_data.get('role') not in ['admin', 'manager', 'quanly', 'boss', 'letan']:
        raise HTTPException(status_code=403, detail="Bạn không có quyền chỉnh sửa phiếu này")

    try:
        # 1. Cập nhật thông tin chung
        if payload.notes is not None:
            ticket.notes = payload.notes
            
        if payload.source_warehouse_id:
             # Validate source warehouse
            source_wh = db.query(Warehouse).get(payload.source_warehouse_id)
            if not source_wh:
                raise HTTPException(status_code=404, detail="Kho nguồn không tồn tại")
            ticket.source_warehouse_id = payload.source_warehouse_id

        # 2. Cập nhật danh sách items
        # Chiến lược: Xóa hết items cũ và tạo lại items mới
        # Điều này đơn giản hơn việc diff từng item
        
        # Xóa items cũ
        for item in ticket.items:
            db.delete(item)
        
        # Thêm items mới
        for item in payload.items:
            t_item = InventoryTransferItem(
                transfer_id=ticket.id,
                product_id=item.product_id,
                request_quantity=item.quantity,
                request_unit=item.unit
            )
            db.add(t_item)

        db.commit()
        return {"status": "success", "message": "Đã cập nhật yêu cầu thành công"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Lỗi khi cập nhật phiếu: {str(e)}")

# ====================================================================


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
    if start_time:
        aq = aq.filter(InventoryTransfer.created_at >= start_time)
    if end_time:
        aq = aq.filter(InventoryTransfer.created_at <= end_time)

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
    warehouse_id: int = None,
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
    from ...db.models import InventoryLevel, InventoryReceipt, Product
    from sqlalchemy import func, case, text as sa_text

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
    if warehouse_id:
        aq = aq.filter(InventoryTransfer.source_warehouse_id == warehouse_id)
    if start_time:
        aq = aq.filter(InventoryTransfer.created_at >= start_time)
    if end_time:
        aq = aq.filter(InventoryTransfer.created_at <= end_time)

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
    ov_wh = f"it.source_warehouse_id = :wh_id AND it.related_transfer_id IS NULL" if warehouse_id else "1=1"
    ov_wh_dest = f"it.dest_warehouse_id = :wh_id AND it.related_transfer_id IS NULL" if warehouse_id else "1=1"
    ov_wh_ir = f"ir.warehouse_id = :wh_id" if warehouse_id else "1=1"
    ov_wh_sm = f"sm.warehouse_id = :wh_id" if warehouse_id else "1=1"
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

    from sqlalchemy import text as sa_text
    stats_sql = sa_text(f"""
        SELECT
            (SELECT COUNT(*) FROM inventory_transfers it WHERE {ov_wh_dest} {ov_date_it}) AS req_total,
            (SELECT COUNT(*) FROM inventory_transfers it WHERE {ov_wh_dest} AND it.status='PENDING' {ov_date_it}) AS req_pending,
            (SELECT COUNT(*) FROM inventory_transfers it WHERE {ov_wh_dest} AND it.status='SHIPPING' {ov_date_it}) AS req_shipping,
            (SELECT COUNT(*) FROM inventory_transfers it WHERE {ov_wh_dest} AND it.status='COMPLETED' {ov_date_it}) AS req_completed,
            (SELECT COUNT(*) FROM inventory_receipts ir WHERE {ov_wh_ir} {ov_date_ir}) AS imp_count,
            (SELECT COALESCE(SUM(ir.total_amount),0) FROM inventory_receipts ir WHERE {ov_wh_ir} {ov_date_ir}) AS imp_amount,
            (SELECT COUNT(*) FROM inventory_transfers it WHERE {ov_wh} AND it.status='COMPLETED' {ov_date_it}) AS exp_count,
            (SELECT COALESCE(ABS(SUM(sm.quantity_change * p.sell_price)),0)
             FROM stock_movements sm
             JOIN products p ON sm.product_id = p.id
             WHERE sm.transaction_type IN ('EXPORT_SERVICE', 'VOID_SERVICE')
             AND {ov_wh_sm} {ov_date_sm}) AS sales_amount
    """)
    stats_row = db.execute(stats_sql, ov_params).fetchone()
    import_amount = float(stats_row.imp_amount or 0)
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
    """Single endpoint for reception page init: approvals (by dest) + imports + overview stats."""
    from ...core.utils import VN_TZ
    from ...db.models import InventoryReceipt, Product
    from sqlalchemy import text as sa_text

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

    # ── 1. Approvals (PENDING) — filter by DEST warehouse (reception receives goods) ──
    aq = db.query(InventoryTransfer).options(
        selectinload(InventoryTransfer.items).joinedload(InventoryTransferItem.product),
        joinedload(InventoryTransfer.dest_warehouse),
        joinedload(InventoryTransfer.source_warehouse),
        joinedload(InventoryTransfer.requester),
        selectinload(InventoryTransfer.compensation_transfers)
    ).filter(InventoryTransfer.status == TicketStatus.PENDING)
    if warehouse_id:
        aq = aq.filter(InventoryTransfer.dest_warehouse_id == warehouse_id)
    if start_time:
        aq = aq.filter(InventoryTransfer.created_at >= start_time)
    if end_time:
        aq = aq.filter(InventoryTransfer.created_at <= end_time)

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

    # ── 3. Overview stats ──
    ov_params: dict = {}
    ov_wh_dest = f"it.dest_warehouse_id = :wh_id AND it.related_transfer_id IS NULL" if warehouse_id else "1=1"
    ov_wh_ir = f"ir.warehouse_id = :wh_id" if warehouse_id else "1=1"
    ov_wh_sm = f"sm.warehouse_id = :wh_id" if warehouse_id else "1=1"
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
            (SELECT COUNT(*) FROM inventory_transfers it WHERE {ov_wh_dest} AND it.status='PENDING' {ov_date_it}) AS req_pending,
            (SELECT COUNT(*) FROM inventory_transfers it WHERE {ov_wh_dest} AND it.status='SHIPPING' {ov_date_it}) AS req_shipping,
            (SELECT COUNT(*) FROM inventory_transfers it WHERE {ov_wh_dest} AND it.status='COMPLETED' {ov_date_it}) AS req_completed,
            (SELECT COUNT(*) FROM inventory_receipts ir WHERE {ov_wh_ir} {ov_date_ir}) AS imp_count,
            (SELECT COALESCE(SUM(ir.total_amount),0) FROM inventory_receipts ir WHERE {ov_wh_ir} {ov_date_ir}) AS imp_amount,
            (SELECT COUNT(*) FROM inventory_transfers it WHERE {ov_wh_dest} AND it.status='COMPLETED' {ov_date_it}) AS exp_count,
            (SELECT COALESCE(ABS(SUM(sm.quantity_change * p.sell_price)),0)
             FROM stock_movements sm
             JOIN products p ON sm.product_id = p.id
             WHERE sm.transaction_type IN ('EXPORT_SERVICE', 'VOID_SERVICE')
             AND {ov_wh_sm} {ov_date_sm}) AS sales_amount
    """)
    stats_row = db.execute(stats_sql, ov_params).fetchone()
    import_amount = float(stats_row.imp_amount or 0)
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
