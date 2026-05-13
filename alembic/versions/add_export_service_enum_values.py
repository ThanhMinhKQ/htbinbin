"""add EXPORT_SERVICE and VOID_SERVICE to transactiontypewms enum

Revision ID: add_export_service_enum_values
Revises: perf_add_inventory_indexes
Create Date: 2026-05-13
"""

from alembic import op

revision = "add_export_service_enum_values"
down_revision = "perf_add_inventory_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE transactiontypewms ADD VALUE IF NOT EXISTS 'EXPORT_SERVICE'")
    op.execute("ALTER TYPE transactiontypewms ADD VALUE IF NOT EXISTS 'VOID_SERVICE'")


def downgrade():
    pass
