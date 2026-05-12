"""perf: add inventory performance indexes

Revision ID: perf_add_inventory_indexes
Revises:
Create Date: 2026-05-12

Indexes added:
- inventory_transfers: (source_warehouse_id, status, created_at) for approvals query
- inventory_transfers: (dest_warehouse_id, status, created_at) for requests query
- inventory_transfers: (created_at DESC) for date range scans
- inventory_receipts: (warehouse_id, created_at DESC) for imports query
- stock_movements: (warehouse_id, transaction_type, created_at) for stats query
"""
from alembic import op

revision = 'perf_add_inventory_indexes'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # InventoryTransfer: approvals query (source_warehouse_id + status + created_at)
    op.create_index(
        'ix_inv_transfers_src_wh_status_created',
        'inventory_transfers',
        ['source_warehouse_id', 'status', 'created_at'],
        postgresql_ops={'created_at': 'DESC'}
    )

    # InventoryTransfer: requests query (dest_warehouse_id + status + created_at)
    op.create_index(
        'ix_inv_transfers_dest_wh_status_created',
        'inventory_transfers',
        ['dest_warehouse_id', 'status', 'created_at'],
        postgresql_ops={'created_at': 'DESC'}
    )

    # InventoryTransfer: date range scan
    op.create_index(
        'ix_inv_transfers_created_desc',
        'inventory_transfers',
        ['created_at'],
        postgresql_ops={'created_at': 'DESC'}
    )

    # InventoryReceipt: imports query (warehouse_id + created_at)
    op.create_index(
        'ix_inv_receipts_wh_created',
        'inventory_receipts',
        ['warehouse_id', 'created_at'],
        postgresql_ops={'created_at': 'DESC'}
    )

    # StockMovement: stats query (warehouse_id + transaction_type + created_at)
    op.create_index(
        'ix_stock_movements_wh_type_created',
        'stock_movements',
        ['warehouse_id', 'transaction_type', 'created_at'],
        postgresql_ops={'created_at': 'DESC'}
    )


def downgrade():
    op.drop_index('ix_inv_transfers_src_wh_status_created', 'inventory_transfers')
    op.drop_index('ix_inv_transfers_dest_wh_status_created', 'inventory_transfers')
    op.drop_index('ix_inv_transfers_created_desc', 'inventory_transfers')
    op.drop_index('ix_inv_receipts_wh_created', 'inventory_receipts')
    op.drop_index('ix_stock_movements_wh_type_created', 'stock_movements')
