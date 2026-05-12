from decimal import Decimal
from sqlalchemy.orm import Session
from ..db.models import (
    InventoryLevel, StockMovement, Warehouse, TransactionTypeWMS
)


def get_or_create_transit_warehouse(db: Session) -> Warehouse:
    transit_wh = db.query(Warehouse).filter(Warehouse.type == 'TRANSIT').first()
    if not transit_wh:
        transit_wh = Warehouse(name="Kho Đang Vận Chuyển", type="TRANSIT", branch_id=None)
        db.add(transit_wh)
        db.flush()
    return transit_wh


def deduct_stock(
    db: Session,
    warehouse_id: int,
    product_id: int,
    qty_base: Decimal,
    ref_ticket_id: int,
    ref_ticket_type: str,
    actor_id: int,
    transaction_type: TransactionTypeWMS = TransactionTypeWMS.EXPORT_TRANSFER
) -> InventoryLevel:
    stock = db.query(InventoryLevel).filter(
        InventoryLevel.warehouse_id == warehouse_id,
        InventoryLevel.product_id == product_id
    ).with_for_update().first()

    if not stock:
        raise ValueError(f"Sản phẩm (id={product_id}) chưa có trong kho (id={warehouse_id})")

    if stock.quantity < qty_base:
        raise ValueError(
            f"Kho không đủ hàng (Tồn: {stock.quantity}, Cần: {qty_base})"
        )

    stock.quantity -= qty_base

    movement = StockMovement(
        warehouse_id=warehouse_id,
        product_id=product_id,
        transaction_type=transaction_type,
        quantity_change=-qty_base,
        balance_after=stock.quantity,
        ref_ticket_id=ref_ticket_id,
        ref_ticket_type=ref_ticket_type,
        actor_id=actor_id
    )
    db.add(movement)
    return stock


def add_stock(
    db: Session,
    warehouse_id: int,
    product_id: int,
    qty_base: Decimal,
    ref_ticket_id: int,
    ref_ticket_type: str,
    actor_id: int,
    transaction_type: TransactionTypeWMS = TransactionTypeWMS.IMPORT_TRANSFER
) -> InventoryLevel:
    stock = db.query(InventoryLevel).filter(
        InventoryLevel.warehouse_id == warehouse_id,
        InventoryLevel.product_id == product_id
    ).with_for_update().first()

    if not stock:
        stock = InventoryLevel(
            warehouse_id=warehouse_id,
            product_id=product_id,
            quantity=0,
            min_stock=0
        )
        db.add(stock)
        db.flush()

    stock.quantity += qty_base

    movement = StockMovement(
        warehouse_id=warehouse_id,
        product_id=product_id,
        transaction_type=transaction_type,
        quantity_change=qty_base,
        balance_after=stock.quantity,
        ref_ticket_id=ref_ticket_id,
        ref_ticket_type=ref_ticket_type,
        actor_id=actor_id
    )
    db.add(movement)
    return stock


def move_to_transit(
    db: Session,
    source_warehouse_id: int,
    product_id: int,
    qty_base: Decimal,
    ref_ticket_id: int,
    actor_id: int
) -> None:
    deduct_stock(
        db, source_warehouse_id, product_id, qty_base,
        ref_ticket_id=ref_ticket_id,
        ref_ticket_type="TRANSFER_OUT",
        actor_id=actor_id
    )

    transit_wh = get_or_create_transit_warehouse(db)
    add_stock(
        db, transit_wh.id, product_id, qty_base,
        ref_ticket_id=ref_ticket_id,
        ref_ticket_type="TRANSFER_TO_TRANSIT",
        actor_id=actor_id
    )


def receive_from_transit(
    db: Session,
    dest_warehouse_id: int,
    product_id: int,
    qty_base: Decimal,
    ref_ticket_id: int,
    actor_id: int
) -> None:
    transit_wh = get_or_create_transit_warehouse(db)

    transit_stock = db.query(InventoryLevel).filter(
        InventoryLevel.warehouse_id == transit_wh.id,
        InventoryLevel.product_id == product_id
    ).with_for_update().first()

    if transit_stock:
        transit_stock.quantity -= qty_base
        movement = StockMovement(
            warehouse_id=transit_wh.id,
            product_id=product_id,
            transaction_type=TransactionTypeWMS.EXPORT_TRANSFER,
            quantity_change=-qty_base,
            balance_after=transit_stock.quantity,
            ref_ticket_id=ref_ticket_id,
            ref_ticket_type="TRANSIT_TO_DEST",
            actor_id=actor_id
        )
        db.add(movement)

    add_stock(
        db, dest_warehouse_id, product_id, qty_base,
        ref_ticket_id=ref_ticket_id,
        ref_ticket_type="TRANSFER_IN",
        actor_id=actor_id
    )
