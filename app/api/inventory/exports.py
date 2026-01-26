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

router = APIRouter()

# ====================================================================
# SCHEMAS (Export/Transfer)
# ====================================================================

class RequestItemSchema(BaseModel):
    product_id: int
    quantity: float
    unit: str

class RequestTicketSchema(BaseModel):
    source_warehouse_id: Optional[int] = None # [NEW] Cho phép chọn kho nguồn
    dest_warehouse_id: int 
    items: List[RequestItemSchema]
    notes: Optional[str] = None
    
class UpdateRequestTicketSchema(BaseModel):
    items: List[RequestItemSchema]
    notes: Optional[str] = None
    source_warehouse_id: Optional[int] = None

class ApproveItemSchema(BaseModel):
    id: Optional[int] = None 
    product_id: int
    approved_quantity: float 

class ApproveTicketSchema(BaseModel):
    items: List[ApproveItemSchema]
    approver_notes: Optional[str] = None

class DirectTransferItemSchema(BaseModel):
    product_id: int
    quantity: float
    unit: str

class DirectTransferSchema(BaseModel):
    source_warehouse_id: Optional[int] = None 
    dest_warehouse_id: int 
    items: List[DirectTransferItemSchema]
    notes: Optional[str] = None

class UpdateDirectExportItemSchema(BaseModel):
    product_id: int
    quantity: float
    unit: str

class UpdateDirectExportSchema(BaseModel):
    items: List[UpdateDirectExportItemSchema]
    notes: Optional[str] = None

class ReceiveItemSchema(BaseModel):
    id: Optional[int] = None 
    product_id: int
    received_quantity: float
    loss_quantity: float = 0.0
    loss_reason: Optional[str] = None

class ReceiveTicketSchema(BaseModel):
    items: List[ReceiveItemSchema]
    notes: Optional[str] = None
    compensation_mode: str = "none" # "none", "loss", "full"
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

@router.post("/direct-export")
async def create_direct_export_ticket(
    payload: DirectTransferSchema,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Xuất kho trực tiếp từ Kho Admin -> Kho Con (Bỏ qua bước Duyệt)
    Tạo phiếu với trạng thái SHIPPING (Đang giao) và trừ kho nguồn ngay lập tức.
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Chưa đăng nhập")

    # 1. Xác định Kho Nguồn (Thường là ADMIN/MAIN)
    if payload.source_warehouse_id:
        source_warehouse = db.query(Warehouse).get(payload.source_warehouse_id)
        if not source_warehouse:
            raise HTTPException(status_code=404, detail="Kho nguồn không tồn tại")
    else:
        # Mặc định lấy kho hiện tại của user (Admin)
        active_branch_code = request.session.get("active_branch")
        branch_obj = db.query(Branch).filter(Branch.branch_code == active_branch_code).first()
        if branch_obj:
            source_warehouse = db.query(Warehouse).filter(Warehouse.branch_id == branch_obj.id).first()
        else:
            source_warehouse = None
            
    if not source_warehouse:
        raise HTTPException(status_code=400, detail="Không xác định được Kho nguồn.")

    # 2. Xác định Kho Đích (Bắt buộc)
    dest_warehouse = db.query(Warehouse).get(payload.dest_warehouse_id)
    if not dest_warehouse:
        raise HTTPException(status_code=404, detail="Kho đích không tồn tại")
    
    if source_warehouse.id == dest_warehouse.id:
        raise HTTPException(status_code=400, detail="Kho nguồn và kho đích không được trùng nhau.")

    # 3. Tạo phiếu với trạng thái SHIPPING (Đang giao)
    code = f"EXP_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    ticket = InventoryTransfer(
        code=code,
        source_warehouse_id=source_warehouse.id,
        dest_warehouse_id=dest_warehouse.id,
        requester_id=user_data['id'],
        approver_id=user_data['id'], # Auto approved by creator
        approved_at=datetime.now(timezone.utc),
        status=TicketStatus.SHIPPING,
        notes=payload.notes
    )
    db.add(ticket)
    db.flush()

    # 4. Xử lý Items & Trừ kho nguồn
    transit_wh = db.query(Warehouse).filter(Warehouse.type == 'TRANSIT').first()
    if not transit_wh:
        transit_wh = Warehouse(name="Kho Đang Vận Chuyển", type="TRANSIT", branch_id=None)
        db.add(transit_wh)
        db.flush()

    for item in payload.items:
        # Deduct Source Stock & Calculate Base Qty
        product = db.query(Product).get(item.product_id)
        qty_base = Decimal(str(item.quantity))
        
        # Convert to base unit if necessary
        if item.unit == product.packing_unit and product.conversion_rate > 1:
            qty_base = qty_base * Decimal(product.conversion_rate)

        # Add Item to Ticket (Stored in Base Unit for consistency with approved_qty logic)
        t_item = InventoryTransferItem(
            transfer_id=ticket.id,
            product_id=item.product_id,
            request_quantity=item.quantity,
            request_unit=item.unit,
            approved_quantity=qty_base # [FIX] Auto approve using BASE quantity
        )
        db.add(t_item)
            
        source_stock = db.query(InventoryLevel).filter(
            InventoryLevel.warehouse_id == source_warehouse.id,
            InventoryLevel.product_id == product.id
        ).first()
        
        current_source_qty = source_stock.quantity if source_stock else Decimal(0)
        
        # Create/Update Source Stock Record (Allow negative if needed, but warning if strictly implemented)
        if not source_stock:
             # [STRICT] Block if product doesn't exist in stock
             raise HTTPException(status_code=400, detail=f"Sản phẩm {product.name} chưa có trong kho nguồn (Tồn: 0)")
        
        if source_stock.quantity < qty_base:
             # [STRICT] Block negative stock
             raise HTTPException(status_code=400, detail=f"Kho không đủ hàng: {product.name} (Tồn: {source_stock.quantity}, Cần: {qty_base})")

        source_stock.quantity -= qty_base
        
        # Log Transaction Out
        trans_out = StockMovement(
            warehouse_id=source_warehouse.id,
            product_id=product.id,
            transaction_type=TransactionTypeWMS.EXPORT_TRANSFER,
            quantity_change=-qty_base,
            balance_after=source_stock.quantity,
            ref_ticket_id=ticket.id,
            ref_ticket_type="DIRECT_EXPORT_OUT",
            actor_id=user_data['id']
        )
        db.add(trans_out)
        
        # Add to Transit Warehouse
        transit_stock = db.query(InventoryLevel).filter(
            InventoryLevel.warehouse_id == transit_wh.id,
            InventoryLevel.product_id == product.id
        ).with_for_update().first()
        
        if not transit_stock:
            # Double check to avoid race condition or stale session state
            # If with_for_update returned None, it should be safe to create, 
            # BUT to be absolutely safe against parallel requests within same transaction block issues:
            transit_stock = InventoryLevel(warehouse_id=transit_wh.id, product_id=product.id, quantity=0, min_stock=0)
            db.add(transit_stock)
            db.flush() # Flush immediately to ensure ID availability for subsequent items if same product
            
        transit_stock.quantity += qty_base
        
        # Log Transaction Transit
        trans_transit = StockMovement(
            warehouse_id=transit_wh.id,
            product_id=product.id,
            transaction_type=TransactionTypeWMS.IMPORT_TRANSFER,
            quantity_change=qty_base,
            balance_after=transit_stock.quantity,
            ref_ticket_id=ticket.id,
            ref_ticket_type="DIRECT_EXPORT_TRANSIT",
            actor_id=user_data['id']
        )
        db.add(trans_transit)
    
    db.commit()
    return {"status": "success", "message": "Đã tạo phiếu xuất kho thành công! Hàng đang được giao."}

@router.put("/direct-export/{ticket_id}")
async def update_direct_export_ticket(
    ticket_id: int,
    payload: UpdateDirectExportSchema,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Cập nhật phiếu xuất kho trực tiếp (chỉ khi đang ở trạng thái SHIPPING - trước khi nhận hàng)
    - Reverse stock movements cũ
    - Cập nhật danh sách items và số lượng
    - Re-apply stock movements mới
    """
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Chưa đăng nhập")

    # 1. Validate ticket
    ticket = db.query(InventoryTransfer).get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Phiếu xuất không tồn tại")

    if ticket.status != TicketStatus.SHIPPING:
        raise HTTPException(
            status_code=400, 
            detail="Chỉ có thể chỉnh sửa phiếu khi đang ở trạng thái 'Đang giao hàng' (SHIPPING). Phiếu đã hoàn thành không thể sửa."
        )

    # 2. Check permissions
    if ticket.requester_id != user_data['id'] and user_data.get('role') not in ['admin', 'manager', 'quanly', 'boss']:
        raise HTTPException(status_code=403, detail="Bạn không có quyền chỉnh sửa phiếu này")

    try:
        # 3. Get warehouses
        source_warehouse = db.query(Warehouse).get(ticket.source_warehouse_id)
        if not source_warehouse:
            raise HTTPException(status_code=404, detail="Kho nguồn không tồn tại")
        
        transit_wh = db.query(Warehouse).filter(Warehouse.type == 'TRANSIT').first()
        if not transit_wh:
            raise HTTPException(status_code=500, detail="Kho transit không tồn tại")

        # 4. Reverse previous stock movements
        # Find all stock movements related to this ticket
        old_movements = db.query(StockMovement).filter(
            StockMovement.ref_ticket_id == ticket.id,
            StockMovement.ref_ticket_type.in_(['DIRECT_EXPORT_OUT', 'DIRECT_EXPORT_TRANSIT'])
        ).all()

        for movement in old_movements:
            # Reverse the movement
            stock = db.query(InventoryLevel).filter(
                InventoryLevel.warehouse_id == movement.warehouse_id,
                InventoryLevel.product_id == movement.product_id
            ).first()
            
            if stock:
                # Reverse: if it was -100, add back +100
                stock.quantity -= movement.quantity_change
            
            # Delete the movement record
            db.delete(movement)

        # 5. Delete old items
        for item in ticket.items:
            db.delete(item)
        
        db.flush()

        # 6. Create new items and apply new stock movements
        for item in payload.items:
            product = db.query(Product).get(item.product_id)
            if not product:
                raise HTTPException(status_code=404, detail=f"Sản phẩm ID {item.product_id} không tồn tại")
            
            qty_base = Decimal(str(item.quantity))
            
            # Convert to base unit if necessary
            if item.unit == product.packing_unit and product.conversion_rate > 1:
                qty_base = qty_base * Decimal(product.conversion_rate)

            # Add new item to ticket
            t_item = InventoryTransferItem(
                transfer_id=ticket.id,
                product_id=item.product_id,
                request_quantity=item.quantity,
                request_unit=item.unit,
                approved_quantity=qty_base
            )
            db.add(t_item)
            
            # Deduct from source warehouse
            source_stock = db.query(InventoryLevel).filter(
                InventoryLevel.warehouse_id == source_warehouse.id,
                InventoryLevel.product_id == product.id
            ).first()
            
            if not source_stock:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Sản phẩm {product.name} chưa có trong kho nguồn (Tồn: 0)"
                )
            
            if source_stock.quantity < qty_base:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Kho không đủ hàng: {product.name} (Tồn: {source_stock.quantity}, Cần: {qty_base})"
                )

            source_stock.quantity -= qty_base
            
            # Log transaction out
            trans_out = StockMovement(
                warehouse_id=source_warehouse.id,
                product_id=product.id,
                transaction_type=TransactionTypeWMS.EXPORT_TRANSFER,
                quantity_change=-qty_base,
                balance_after=source_stock.quantity,
                ref_ticket_id=ticket.id,
                ref_ticket_type="DIRECT_EXPORT_OUT",
                actor_id=user_data['id']
            )
            db.add(trans_out)
            
            # Add to transit warehouse
            transit_stock = db.query(InventoryLevel).filter(
                InventoryLevel.warehouse_id == transit_wh.id,
                InventoryLevel.product_id == product.id
            ).with_for_update().first()
            
            if not transit_stock:
                transit_stock = InventoryLevel(
                    warehouse_id=transit_wh.id, 
                    product_id=product.id, 
                    quantity=0,
                    min_stock=0
                )
                db.add(transit_stock)
                db.flush()
            
            transit_stock.quantity += qty_base
            
            # Log transaction transit
            trans_transit = StockMovement(
                warehouse_id=transit_wh.id,
                product_id=product.id,
                transaction_type=TransactionTypeWMS.IMPORT_TRANSFER,
                quantity_change=qty_base,
                balance_after=transit_stock.quantity,
                ref_ticket_id=ticket.id,
                ref_ticket_type="DIRECT_EXPORT_TRANSIT",
                actor_id=user_data['id']
            )
            db.add(trans_transit)

        # 7. Update notes if provided
        if payload.notes is not None:
            ticket.notes = payload.notes

        db.commit()
        return {"status": "success", "message": "Đã cập nhật phiếu xuất kho thành công!"}
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Lỗi khi cập nhật phiếu: {str(e)}")


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
    user_data = request.session.get("user")
    
    ticket = db.query(InventoryTransfer).get(ticket_id)
    if not ticket or ticket.status != TicketStatus.PENDING:
        raise HTTPException(status_code=400, detail="Phiếu không tồn tại hoặc không ở trạng thái chờ duyệt")

    ticket.status = TicketStatus.SHIPPING # [MODIFIED] Chuyển trạng thái sang ĐANG GIAO
    ticket.approver_id = user_data['id']
    ticket.approved_at = datetime.now(timezone.utc)
    ticket.approver_notes = payload.approver_notes

    for app_item in payload.items:
        db_item = None
        if app_item.id:
            db_item = next((i for i in ticket.items if i.id == app_item.id), None)
        
        if not db_item:
            db_item = next((i for i in ticket.items if i.product_id == app_item.product_id), None)

        if db_item:
            product = db_item.product
            
            approved_qty_base = Decimal(str(app_item.approved_quantity))
            
            if db_item.request_unit == product.packing_unit and product.conversion_rate > 1:
                approved_qty_base = approved_qty_base * Decimal(product.conversion_rate)
            
            db_item.approved_quantity = approved_qty_base 

            # [FIX] Only deduct stock if we are actually approving a quantity > 0
            if approved_qty_base > 0:
                source_stock = db.query(InventoryLevel).filter(
                    InventoryLevel.warehouse_id == ticket.source_warehouse_id,
                    InventoryLevel.product_id == product.id
                ).first()
                
                if source_stock:
                    # [STRICT] Check Availability
                    if source_stock.quantity < approved_qty_base:
                        raise HTTPException(status_code=400, detail=f"Kho không đủ hàng để duyệt: {product.name} (Tồn: {source_stock.quantity}, Duyệt: {approved_qty_base})")

                    source_stock.quantity -= approved_qty_base 
                    
                    trans_out = StockMovement(
                        warehouse_id=ticket.source_warehouse_id,
                        product_id=product.id,
                        transaction_type=TransactionTypeWMS.EXPORT_TRANSFER,
                        quantity_change=-approved_qty_base,
                        balance_after=source_stock.quantity,
                        ref_ticket_id=ticket.id,
                        ref_ticket_type="TRANSFER_OUT",
                        actor_id=user_data['id']
                    )
                    db.add(trans_out)
                    
                    # [NEW] Move to In-Transit Warehouse
                    transit_wh = db.query(Warehouse).filter(Warehouse.type == 'TRANSIT').first()
                    if not transit_wh:
                        transit_wh = Warehouse(name="Kho Đang Vận Chuyển", type="TRANSIT", branch_id=None)
                        db.add(transit_wh)
                        db.flush()
                    
                    transit_stock = db.query(InventoryLevel).filter(
                        InventoryLevel.warehouse_id == transit_wh.id,
                        InventoryLevel.product_id == product.id
                    ).first()
                    
                    if not transit_stock:
                        transit_stock = InventoryLevel(
                            warehouse_id=transit_wh.id,  
                            product_id=product.id, 
                            quantity=0, 
                            min_stock=0
                        )
                        db.add(transit_stock)
                        db.flush()
                        
                    transit_stock.quantity += approved_qty_base
                    
                    trans_transit = StockMovement(
                        warehouse_id=transit_wh.id,
                        product_id=product.id,
                        transaction_type=TransactionTypeWMS.IMPORT_TRANSFER, # Technically import to transit
                        quantity_change=approved_qty_base,
                        balance_after=transit_stock.quantity,
                        ref_ticket_id=ticket.id,
                        ref_ticket_type="TRANSFER_TO_TRANSIT",
                        actor_id=user_data['id']
                    )
                    db.add(trans_transit)

                else:
                     # Cho phép xuất âm hoặc báo lỗi tùy policy. Ở đây báo lỗi nếu không có record stock
                    raise HTTPException(status_code=400, detail=f"Sản phẩm {product.name} chưa được khởi tạo ở kho nguồn")
             
             # [REMOVED] Logic cộng kho đích đã được dời sang bước Nhận Hàng (confirm_receipt)

    db.commit()
    return {"status": "success", "message": "Đã duyệt và chuyển hàng sang Kho 'Đang vận chuyển'"}

class ReceiveItemSchema(BaseModel):
    id: int # [FIX] Require ID to distinguish multiple lines of same product
    product_id: int
    received_quantity: float
    loss_quantity: float = 0.0
    loss_reason: Optional[str] = None
    
class ReceiveTicketSchema(BaseModel):
    items: List[ReceiveItemSchema]
    compensation_mode: str = "none"

@router.post("/receive/{ticket_id}")
async def confirm_receipt(
    ticket_id: int,
    payload: ReceiveTicketSchema,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Xác nhận nhận hàng từ Phiếu Đang Giao (SHIPPING)
    """
    user_data = request.session.get("user")
    
    ticket = db.query(InventoryTransfer).get(ticket_id)
    if not ticket or ticket.status != TicketStatus.SHIPPING:
        raise HTTPException(status_code=400, detail="Phiếu không tồn tại hoặc không ở trạng thái Đang giao")

    # Chỉ người yêu cầu mới được xác nhận nhận hàng (hoặc admin)
    # if ticket.requester_id != user_data['id']: ... (Tùy chọn check quyền)

    transit_wh = db.query(Warehouse).filter(Warehouse.type == 'TRANSIT').first()
    
    compensation_items = []
    
    for rec_item in payload.items:
        # [FIX] Match by Ticket Item ID, not just Product ID
        db_item = db.query(InventoryTransferItem).get(rec_item.id)
        
        # Security check: ensure item belongs to this ticket
        if not db_item or db_item.transfer_id != ticket.id:
            continue
        
        product = db_item.product
        
        # Parse received/loss quantities
        received_qty_base = Decimal(str(rec_item.received_quantity))
        loss_qty_base = Decimal(str(rec_item.loss_quantity))

        # Quy đổi nếu nhập theo đơn vị đóng gói (Logic FE cần gửi đúng unit hoặc BE quy đổi lại)
        # Giả sử FE gửi số lượng đã quy đổi hoặc base. Ở đây giả sử FE gửi base unit hoặc BE tự lo.
        # Simple Logic: Assume base unit for now as per previous logic.
        if db_item.request_unit == product.packing_unit and product.conversion_rate > 1:
             received_qty_base = received_qty_base * Decimal(product.conversion_rate)
             loss_qty_base = loss_qty_base * Decimal(product.conversion_rate)

        # Update Ticket Item with Discrepancy Info
        db_item.received_quantity = received_qty_base
        db_item.loss_quantity = loss_qty_base
        db_item.loss_reason = rec_item.loss_reason

        # 1. Trừ Kho In-Transit (Chỉ trừ số thực nhận, số loss treo lại theo yêu cầu)
        if transit_wh:
            transit_stock = db.query(InventoryLevel).filter(
                InventoryLevel.warehouse_id == transit_wh.id,
                InventoryLevel.product_id == product.id
            ).first()
            
            if transit_stock:
                # IMPORTANT: Only subtract Actual Received. Loss remains in Transit as "Zombie/Lost" stock.
                transit_stock.quantity -= received_qty_base

                trans_transit_out = StockMovement(
                    warehouse_id=transit_wh.id,
                    product_id=product.id,
                    transaction_type=TransactionTypeWMS.EXPORT_TRANSFER,
                    quantity_change=-received_qty_base,
                    balance_after=transit_stock.quantity,
                    ref_ticket_id=ticket.id,
                    ref_ticket_type="TRANSIT_TO_DEST",
                    actor_id=user_data['id']
                )
                db.add(trans_transit_out)

        # 2. Cộng Kho Đích (Số thực nhận)
        dest_stock = db.query(InventoryLevel).filter(
            InventoryLevel.warehouse_id == ticket.dest_warehouse_id,
            InventoryLevel.product_id == product.id
        ).first()

        if not dest_stock:
            dest_stock = InventoryLevel(
                warehouse_id=ticket.dest_warehouse_id,
                product_id=product.id,
                quantity=0,
                min_stock=0
            )
            db.add(dest_stock)
            db.flush() 
        
        dest_stock.quantity += received_qty_base

        trans_in = StockMovement(
            warehouse_id=ticket.dest_warehouse_id,
            product_id=product.id,
            transaction_type=TransactionTypeWMS.IMPORT_TRANSFER,
            quantity_change=received_qty_base,
            balance_after=dest_stock.quantity,
            ref_ticket_id=ticket.id,
            ref_ticket_type="TRANSFER_IN",
            actor_id=user_data['id'] 
        )
        db.add(trans_in)
        
        # 3. Tính toán Bù Hàng
        if payload.compensation_mode == 'loss':
            # Chỉ bù số lượng khai báo mất
            if loss_qty_base > 0:
                # Convert back to Request Unit
                qty_to_compensate = float(loss_qty_base)
                if db_item.request_unit == product.packing_unit and product.conversion_rate > 1:
                     qty_to_compensate = qty_to_compensate / float(product.conversion_rate)

                compensation_items.append({
                    "product_id": product.id,
                    "quantity": qty_to_compensate,
                    "unit": db_item.request_unit
                })
        elif payload.compensation_mode == 'full':
            # Bù đủ gốc: Logic Item-Based để hỗ trợ nhiều đơn vị tính (Box vs Bottle)
            # 1. Tìm Root Item tương ứng (Match Product + Unit)
            root_ticket = ticket.related_transfer if ticket.related_transfer_id else ticket
            
            # Match by Product AND Unit to distinguish lines (e.g. Box vs Bottle)
            root_item = next((
                i for i in root_ticket.items 
                if i.product_id == product.id and i.request_unit == db_item.request_unit
            ), None)
            
            if root_item:
                # 2. Tính tổng đã nhận (Cumulative Received) cho Line này
                # Query trực tiếp TransferTicketItem từ các phiếu liên quan
                all_ticket_ids = [root_ticket.id] + [t.id for t in root_ticket.compensation_transfers]
                
                related_items = db.query(InventoryTransferItem).filter(
                    InventoryTransferItem.transfer_id.in_(all_ticket_ids),
                    InventoryTransferItem.product_id == product.id,
                    InventoryTransferItem.request_unit == root_item.request_unit # Strict Unit Match
                ).all()
                
                total_received_base = 0.0
                for ri in related_items:
                    r_qty = Decimal(str(ri.received_quantity)) if ri.received_quantity is not None else Decimal(0)
                    
                    # Convert to Base if needed (though usually stored as Base?)
                    # Model definition says `received_quantity` is NUMERIC. 
                    # Assuming it stores the value consistent with logic elsewhere.
                    # Previous logic: stored as Base.
                    total_received_base += float(r_qty)

                # 3. Tính số lượng gốc yêu cầu (Base Unit)
                root_req_qty_base = Decimal(str(root_item.request_quantity))
                if root_item.request_unit == product.packing_unit and product.conversion_rate > 1:
                    root_req_qty_base = root_req_qty_base * Decimal(product.conversion_rate)
                
                # 4. Tính thiếu (Shortage)
                shortage_base = float(root_req_qty_base) - total_received_base
                
                if shortage_base > 0.01: # Tolerance
                    # 5. Quy đổi ngược về đơn vị yêu cầu
                    qty_to_compensate = shortage_base
                    if root_item.request_unit == product.packing_unit and product.conversion_rate > 1:
                         qty_to_compensate = qty_to_compensate / float(product.conversion_rate)
                    
                    compensation_items.append({
                        "product_id": product.id,
                        "quantity": qty_to_compensate,
                        "unit": root_item.request_unit
                    })

    # 4. Cập nhật Status Phiếu (Current)
    ticket.status = TicketStatus.COMPLETED
    
    # 5. Tạo Phiếu Bù (Nếu có)
    message = "Đã nhận hàng thành công."
    if compensation_items:
        root_ticket = ticket.related_transfer if ticket.related_transfer_id else ticket
        
        new_code = f"REQ_COMP_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        comp_ticket = InventoryTransfer(
            code=new_code,
            source_warehouse_id=root_ticket.source_warehouse_id,
            dest_warehouse_id=root_ticket.dest_warehouse_id,
            requester_id=user_data['id'],
            status=TicketStatus.PENDING,
            related_transfer_id=root_ticket.id, # ALWAYS LINK TO ROOT
            notes=f"Bù hàng cho phiếu {root_ticket.code}"
        )
        db.add(comp_ticket)
        db.flush()
        
        for m_item in compensation_items:
            # Create item
            t_item = InventoryTransferItem(
                transfer_id=comp_ticket.id,
                product_id=m_item['product_id'],
                request_quantity=m_item['quantity'],
                request_unit=m_item['unit']
            )
            db.add(t_item)
            
        message += f" Hệ thống đã tạo yêu cầu bù hàng mới ({new_code})."


    db.commit()
    return {"status": "success", "message": message}

@router.post("/reject/{ticket_id}")
async def reject_ticket(
    ticket_id: int,
    request: Request,
    db: Session = Depends(get_db),
    rejection_notes: str = None
):
    """
    Từ chối yêu cầu chuyển kho
    """
    user_data = request.session.get("user")
    
    ticket = db.query(InventoryTransfer).get(ticket_id)
    if not ticket or ticket.status != TicketStatus.PENDING:
        raise HTTPException(status_code=400, detail="Phiếu không tồn tại hoặc không ở trạng thái chờ duyệt")

    # Cập nhật trạng thái thành REJECTED
    ticket.status = TicketStatus.REJECTED
    ticket.approver_id = user_data['id']
    ticket.approved_at = datetime.now(timezone.utc)
    ticket.approver_notes = rejection_notes or "Đã từ chối yêu cầu"

    db.commit()
    return {"status": "success", "message": "Đã từ chối yêu cầu"}


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

    # Kiểm tra quyền: Chỉ người tạo hoặc Admin/Manager mới được xóa
    # (Tùy chọn, ở đây tạm thời cho phép người tạo và quản lý)
    if ticket.requester_id != user_data['id'] and user_data.get('role') not in ['admin', 'manager', 'quanly', 'boss']:
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

    if ticket.requester_id != user_data['id'] and user_data.get('role') not in ['admin', 'manager', 'quanly', 'boss']:
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
# API: IMAGE UPLOAD FOR TRANSFERS (RECEIPTS)
# ====================================================================

@router.post("/transfer/{ticket_id}/images")
async def upload_transfer_images(
    ticket_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload multiple images for a transfer ticket (reception proof).
    """
    try:
        ticket = db.query(InventoryTransfer).get(ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="Phiếu không tồn tại")
        
        uploaded_images = []
        
        for file in files:
            if not file.content_type or not file.content_type.startswith('image/'):
                continue
            
            image_bytes = await file.read()
            if len(image_bytes) > 10 * 1024 * 1024:
                raise HTTPException(status_code=400, detail=f"File {file.filename} quá lớn (max 10MB)")
            
            try:
                # Use 'transfer' prefix or subfolder logic if supported by ImageOptimizer
                # Assuming simple save_optimized takes (bytes, id, filename)
                full_path, thumb_path, width, height = ImageOptimizer.save_optimized(
                    image_bytes,
                    f"TR_{ticket_id}", # custom ID prefix to distinguish from receipts? Or just ID. 
                    file.filename
                )
                
                transfer_image = TransferImage(
                    transfer_id=ticket_id,
                    file_path=full_path,
                    thumbnail_path=thumb_path,
                    file_size=len(image_bytes),
                    width=width,
                    height=height,
                    display_order=len(uploaded_images)
                )
                db.add(transfer_image)
                uploaded_images.append({
                    "filename": file.filename
                })
                
            except Exception as e:
                print(f"Error processing image {file.filename}: {e}")
                continue
        
        db.commit()
        return {
            "status": "success",
            "message": f"Đã upload {len(uploaded_images)} hình ảnh",
            "images": uploaded_images
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/transfer/{ticket_id}/images")
async def get_transfer_images(
    ticket_id: int,
    db: Session = Depends(get_db)
):
    try:
        images = db.query(TransferImage).filter(
            TransferImage.transfer_id == ticket_id
        ).order_by(TransferImage.display_order).all()
        
        return {
            "images": [
                {
                    "id": img.id,
                    "file_path": "/" + img.file_path if img.file_path and not img.file_path.startswith("/") else img.file_path,
                    "thumbnail_path": "/" + img.thumbnail_path if img.thumbnail_path and not img.thumbnail_path.startswith("/") else img.thumbnail_path,
                    "file_size": img.file_size,
                    "width": img.width,
                    "height": img.height,
                    "uploaded_at": img.uploaded_at.isoformat() if img.uploaded_at else ""
                }
                for img in images
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
