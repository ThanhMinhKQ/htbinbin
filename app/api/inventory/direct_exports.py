from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, func
from datetime import datetime, timezone
from decimal import Decimal

from ...db.session import get_db
from ...db.models import (
    Branch, Product, InventoryLevel, StockMovement, Warehouse,
    InventoryTransfer, InventoryTransferItem, TicketStatus, TransactionTypeWMS
)
from .schemas import DirectTransferSchema, UpdateDirectExportSchema

router = APIRouter()


@router.post("/direct-export")
async def create_direct_export_ticket(
    payload: DirectTransferSchema,
    request: Request,
    db: Session = Depends(get_db)
):
    """Xuất kho trực tiếp từ Kho Admin -> Kho Con (Bỏ qua bước Duyệt)"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Chưa đăng nhập")

    if payload.source_warehouse_id:
        source_warehouse = db.query(Warehouse).get(payload.source_warehouse_id)
        if not source_warehouse:
            raise HTTPException(status_code=404, detail="Kho nguồn không tồn tại")
    else:
        active_branch_code = request.session.get("active_branch")
        branch_obj = db.query(Branch).filter(Branch.branch_code == active_branch_code).first()
        if branch_obj:
            source_warehouse = db.query(Warehouse).filter(Warehouse.branch_id == branch_obj.id).first()
        else:
            source_warehouse = None

    if not source_warehouse:
        raise HTTPException(status_code=400, detail="Không xác định được Kho nguồn.")

    dest_warehouse = db.query(Warehouse).get(payload.dest_warehouse_id)
    if not dest_warehouse:
        raise HTTPException(status_code=404, detail="Kho đích không tồn tại")

    if source_warehouse.id == dest_warehouse.id:
        raise HTTPException(status_code=400, detail="Kho nguồn và kho đích không được trùng nhau.")

    code = f"EXP_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    ticket = InventoryTransfer(
        code=code,
        source_warehouse_id=source_warehouse.id,
        dest_warehouse_id=dest_warehouse.id,
        requester_id=user_data['id'],
        approver_id=user_data['id'],
        approved_at=datetime.now(timezone.utc),
        status=TicketStatus.SHIPPING,
        notes=payload.notes
    )
    db.add(ticket)
    db.flush()

    transit_wh = db.query(Warehouse).filter(Warehouse.type == 'TRANSIT').first()
    if not transit_wh:
        transit_wh = Warehouse(name="Kho Đang Vận Chuyển", type="TRANSIT", branch_id=None)
        db.add(transit_wh)
        db.flush()

    for item in payload.items:
        product = db.query(Product).get(item.product_id)
        qty_base = Decimal(str(item.quantity))

        if item.unit == product.packing_unit and product.conversion_rate > 1:
            qty_base = qty_base * Decimal(product.conversion_rate)

        t_item = InventoryTransferItem(
            transfer_id=ticket.id,
            product_id=item.product_id,
            request_quantity=item.quantity,
            request_unit=item.unit,
            approved_quantity=qty_base
        )
        db.add(t_item)

        source_stock = db.query(InventoryLevel).filter(
            InventoryLevel.warehouse_id == source_warehouse.id,
            InventoryLevel.product_id == product.id
        ).first()

        if not source_stock:
            raise HTTPException(status_code=400, detail=f"Sản phẩm {product.name} chưa có trong kho nguồn (Tồn: 0)")

        if source_stock.quantity < qty_base:
            raise HTTPException(status_code=400, detail=f"Kho không đủ hàng: {product.name} (Tồn: {source_stock.quantity}, Cần: {qty_base})")

        source_stock.quantity -= qty_base

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

        transit_stock = db.query(InventoryLevel).filter(
            InventoryLevel.warehouse_id == transit_wh.id,
            InventoryLevel.product_id == product.id
        ).with_for_update().first()

        if not transit_stock:
            transit_stock = InventoryLevel(warehouse_id=transit_wh.id, product_id=product.id, quantity=0, min_stock=0)
            db.add(transit_stock)
            db.flush()

        transit_stock.quantity += qty_base

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
    """Cập nhật phiếu xuất kho trực tiếp (chỉ khi SHIPPING)"""
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Chưa đăng nhập")

    ticket = db.query(InventoryTransfer).get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Phiếu xuất không tồn tại")

    if ticket.status != TicketStatus.SHIPPING:
        raise HTTPException(
            status_code=400,
            detail="Chỉ có thể chỉnh sửa phiếu khi đang ở trạng thái 'Đang giao hàng' (SHIPPING)."
        )

    if ticket.requester_id != user_data['id'] and user_data.get('role') not in ['admin', 'manager', 'quanly', 'boss']:
        raise HTTPException(status_code=403, detail="Bạn không có quyền chỉnh sửa phiếu này")

    try:
        source_warehouse = db.query(Warehouse).get(ticket.source_warehouse_id)
        if not source_warehouse:
            raise HTTPException(status_code=404, detail="Kho nguồn không tồn tại")

        transit_wh = db.query(Warehouse).filter(Warehouse.type == 'TRANSIT').first()
        if not transit_wh:
            raise HTTPException(status_code=500, detail="Kho transit không tồn tại")

        old_movements = db.query(StockMovement).filter(
            StockMovement.ref_ticket_id == ticket.id,
            StockMovement.ref_ticket_type.in_(['DIRECT_EXPORT_OUT', 'DIRECT_EXPORT_TRANSIT'])
        ).all()

        for movement in old_movements:
            stock = db.query(InventoryLevel).filter(
                InventoryLevel.warehouse_id == movement.warehouse_id,
                InventoryLevel.product_id == movement.product_id
            ).first()
            if stock:
                stock.quantity -= movement.quantity_change
            db.delete(movement)

        for item in ticket.items:
            db.delete(item)

        db.flush()

        for item in payload.items:
            product = db.query(Product).get(item.product_id)
            if not product:
                raise HTTPException(status_code=404, detail=f"Sản phẩm ID {item.product_id} không tồn tại")

            qty_base = Decimal(str(item.quantity))
            if item.unit == product.packing_unit and product.conversion_rate > 1:
                qty_base = qty_base * Decimal(product.conversion_rate)

            t_item = InventoryTransferItem(
                transfer_id=ticket.id,
                product_id=item.product_id,
                request_quantity=item.quantity,
                request_unit=item.unit,
                approved_quantity=qty_base
            )
            db.add(t_item)

            source_stock = db.query(InventoryLevel).filter(
                InventoryLevel.warehouse_id == source_warehouse.id,
                InventoryLevel.product_id == product.id
            ).first()

            if not source_stock:
                raise HTTPException(status_code=400, detail=f"Sản phẩm {product.name} chưa có trong kho nguồn (Tồn: 0)")

            if source_stock.quantity < qty_base:
                raise HTTPException(status_code=400, detail=f"Kho không đủ hàng: {product.name} (Tồn: {source_stock.quantity}, Cần: {qty_base})")

            source_stock.quantity -= qty_base

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

            transit_stock = db.query(InventoryLevel).filter(
                InventoryLevel.warehouse_id == transit_wh.id,
                InventoryLevel.product_id == product.id
            ).with_for_update().first()

            if not transit_stock:
                transit_stock = InventoryLevel(warehouse_id=transit_wh.id, product_id=product.id, quantity=0, min_stock=0)
                db.add(transit_stock)
                db.flush()

            transit_stock.quantity += qty_base

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
