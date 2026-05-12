from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from decimal import Decimal

from ...db.session import get_db
from ...db.models import (
    Product, InventoryLevel, StockMovement, Warehouse,
    InventoryTransfer, InventoryTransferItem, TicketStatus, TransactionTypeWMS,
)

from .schemas import (
    ApproveTicketSchema, DirectTransferSchema, ReceiveTicketSchema,
)

router = APIRouter()

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
