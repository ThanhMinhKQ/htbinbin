from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ..db.models import (
    Product, InventoryTransfer, InventoryTransferItem,
    TicketStatus, Warehouse
)
from .inventory_stock_service import (
    move_to_transit, receive_from_transit, deduct_stock, add_stock,
    get_or_create_transit_warehouse
)


def reject_ticket(db: Session, ticket_id: int, user_id: int, rejection_notes: str = None) -> dict:
    ticket = db.query(InventoryTransfer).get(ticket_id)
    if not ticket or ticket.status != TicketStatus.PENDING:
        raise HTTPException(status_code=400, detail="Phiếu không tồn tại hoặc không ở trạng thái chờ duyệt")

    ticket.status = TicketStatus.REJECTED
    ticket.approver_id = user_id
    ticket.approved_at = datetime.now(timezone.utc)
    ticket.approver_notes = rejection_notes or "Đã từ chối yêu cầu"

    db.commit()
    return {"status": "success", "message": "Đã từ chối yêu cầu"}


def approve_ticket(db: Session, ticket_id: int, payload, user_id: int) -> dict:
    ticket = db.query(InventoryTransfer).get(ticket_id)
    if not ticket or ticket.status != TicketStatus.PENDING:
        raise HTTPException(status_code=400, detail="Phiếu không tồn tại hoặc không ở trạng thái chờ duyệt")

    try:
        ticket.status = TicketStatus.SHIPPING
        ticket.approver_id = user_id
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

                if approved_qty_base > 0:
                    try:
                        move_to_transit(
                            db,
                            source_warehouse_id=ticket.source_warehouse_id,
                            product_id=product.id,
                            qty_base=approved_qty_base,
                            ref_ticket_id=ticket.id,
                            actor_id=user_id
                        )
                    except ValueError as e:
                        raise HTTPException(status_code=400, detail=f"{product.name}: {str(e)}")

        db.commit()
        return {"status": "success", "message": "Đã duyệt và chuyển hàng sang Kho 'Đang vận chuyển'"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống khi duyệt phiếu: {str(e)}")


def confirm_receipt(db: Session, ticket_id: int, payload, user_id: int) -> dict:
    ticket = db.query(InventoryTransfer).get(ticket_id)
    if not ticket or ticket.status != TicketStatus.SHIPPING:
        raise HTTPException(status_code=400, detail="Phiếu không tồn tại hoặc không ở trạng thái Đang giao")

    try:
        compensation_items = []

        for rec_item in payload.items:
            db_item = db.query(InventoryTransferItem).get(rec_item.id)

            if not db_item or db_item.transfer_id != ticket.id:
                continue

            product = db_item.product

            received_qty_base = Decimal(str(rec_item.received_quantity))
            loss_qty_base = Decimal(str(rec_item.loss_quantity))

            if db_item.request_unit == product.packing_unit and product.conversion_rate > 1:
                received_qty_base = received_qty_base * Decimal(product.conversion_rate)
                loss_qty_base = loss_qty_base * Decimal(product.conversion_rate)

            db_item.received_quantity = received_qty_base
            db_item.loss_quantity = loss_qty_base
            db_item.loss_reason = rec_item.loss_reason

            receive_from_transit(
                db,
                dest_warehouse_id=ticket.dest_warehouse_id,
                product_id=product.id,
                qty_base=received_qty_base,
                ref_ticket_id=ticket.id,
                actor_id=user_id
            )

            compensation_items = _calculate_compensation(
                db, payload.compensation_mode, ticket, db_item, product,
                loss_qty_base, compensation_items
            )

        ticket.status = TicketStatus.COMPLETED

        message = "Đã nhận hàng thành công."
        if compensation_items:
            comp_ticket = _create_compensation_ticket(db, ticket, compensation_items, user_id)
            message += f" Hệ thống đã tạo yêu cầu bù hàng mới ({comp_ticket.code})."

        db.commit()
        return {"status": "success", "message": message}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống khi xác nhận nhận hàng: {str(e)}")


def _calculate_compensation(
    db: Session, mode: str, ticket, db_item, product,
    loss_qty_base: Decimal, compensation_items: list
) -> list:
    if mode == 'loss':
        if loss_qty_base > 0:
            qty_to_compensate = float(loss_qty_base)
            if db_item.request_unit == product.packing_unit and product.conversion_rate > 1:
                qty_to_compensate = qty_to_compensate / float(product.conversion_rate)

            compensation_items.append({
                "product_id": product.id,
                "quantity": qty_to_compensate,
                "unit": db_item.request_unit
            })
    elif mode == 'full':
        root_ticket = ticket.related_transfer if ticket.related_transfer_id else ticket

        root_item = next((
            i for i in root_ticket.items
            if i.product_id == product.id and i.request_unit == db_item.request_unit
        ), None)

        if root_item:
            all_ticket_ids = [root_ticket.id] + [t.id for t in root_ticket.compensation_transfers]

            related_items = db.query(InventoryTransferItem).filter(
                InventoryTransferItem.transfer_id.in_(all_ticket_ids),
                InventoryTransferItem.product_id == product.id,
                InventoryTransferItem.request_unit == root_item.request_unit
            ).all()

            total_received_base = 0.0
            for ri in related_items:
                r_qty = Decimal(str(ri.received_quantity)) if ri.received_quantity is not None else Decimal(0)
                total_received_base += float(r_qty)

            root_req_qty_base = Decimal(str(root_item.request_quantity))
            if root_item.request_unit == product.packing_unit and product.conversion_rate > 1:
                root_req_qty_base = root_req_qty_base * Decimal(product.conversion_rate)

            shortage_base = float(root_req_qty_base) - total_received_base

            if shortage_base > 0.01:
                qty_to_compensate = shortage_base
                if root_item.request_unit == product.packing_unit and product.conversion_rate > 1:
                    qty_to_compensate = qty_to_compensate / float(product.conversion_rate)

                compensation_items.append({
                    "product_id": product.id,
                    "quantity": qty_to_compensate,
                    "unit": root_item.request_unit
                })

    return compensation_items


def _create_compensation_ticket(
    db: Session, ticket: InventoryTransfer, items: list, user_id: int
) -> InventoryTransfer:
    root_ticket = ticket.related_transfer if ticket.related_transfer_id else ticket

    new_code = f"REQ_COMP_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    comp_ticket = InventoryTransfer(
        code=new_code,
        source_warehouse_id=root_ticket.source_warehouse_id,
        dest_warehouse_id=root_ticket.dest_warehouse_id,
        requester_id=user_id,
        status=TicketStatus.PENDING,
        related_transfer_id=root_ticket.id,
        notes=f"Bù hàng cho phiếu {root_ticket.code}"
    )
    db.add(comp_ticket)
    db.flush()

    for m_item in items:
        t_item = InventoryTransferItem(
            transfer_id=comp_ticket.id,
            product_id=m_item['product_id'],
            request_quantity=m_item['quantity'],
            request_unit=m_item['unit']
        )
        db.add(t_item)

    return comp_ticket
