"""Add PMS integration fields to shift_report_transactions

Revision ID: pms_shift_integration_v1
Revises:
Create Date: 2026-04-19

- Add PMS_CHECKOUT to transactiontype enum
- Add shiftpaymentmethod enum
- Add stay_id, folio_id, payment_method, is_auto_posted to shift_report_transactions
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'pms_shift_integration_v1'
down_revision = None  # Adjust this to the latest migration
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. Add PMS_CHECKOUT to transactiontype enum ──────────────────────
    # PostgreSQL enum: add value without dropping/reattaching
    op.execute("ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'PMS_CHECKOUT'")

    # ── 2. Create shiftpaymentmethod enum ─────────────────────────────────
    op.execute("""
        CREATE TYPE shiftpaymentmethod AS ENUM (
            'CASH',
            'CARD',
            'BANK_TRANSFER',
            'UNC',
            'OTA',
            'DEBT'
        )
    """)

    # ── 3. Add new columns to shift_report_transactions ────────────────────
    op.add_column('shift_report_transactions',
        sa.Column('stay_id', sa.BigInteger(), sa.ForeignKey('hotel_stays.id', ondelete='SET NULL'), nullable=True))
    op.add_column('shift_report_transactions',
        sa.Column('folio_id', sa.BigInteger(), sa.ForeignKey('folios.id', ondelete='SET NULL'), nullable=True))
    op.add_column('shift_report_transactions',
        sa.Column('payment_method', sa.Enum('CASH', 'CARD', 'BANK_TRANSFER', 'UNC', 'OTA', 'DEBT', name='shiftpaymentmethod', create_type=False), nullable=True))
    op.add_column('shift_report_transactions',
        sa.Column('is_auto_posted', sa.Boolean(), nullable=False, server_default='false'))

    # ── 4. Add indexes ──────────────────────────────────────────────────────
    op.create_index('ix_shift_trans_stay_id', 'shift_report_transactions', ['stay_id'])
    op.create_index('ix_shift_trans_folio_id', 'shift_report_transactions', ['folio_id'])
    op.create_index('ix_shift_trans_is_auto_posted', 'shift_report_transactions', ['is_auto_posted'])


def downgrade():
    op.drop_index('ix_shift_trans_is_auto_posted', table_name='shift_report_transactions')
    op.drop_index('ix_shift_trans_folio_id', table_name='shift_report_transactions')
    op.drop_index('ix_shift_trans_stay_id', table_name='shift_report_transactions')

    op.drop_column('shift_report_transactions', 'is_auto_posted')
    op.drop_column('shift_report_transactions', 'payment_method')
    op.drop_column('shift_report_transactions', 'folio_id')
    op.drop_column('shift_report_transactions', 'stay_id')

    op.execute('DROP TYPE IF EXISTS shiftpaymentmethod')
    # Note: PostgreSQL enum values cannot be removed easily
    # In production, you may need to recreate the enum
