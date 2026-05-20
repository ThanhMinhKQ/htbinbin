"""Add invoice_splits table for split-bill invoice views

Revision ID: add_invoice_splits
Revises: add_folio_invoice_fields
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'add_invoice_splits'
down_revision: Union[str, None] = 'add_folio_invoice_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'invoice_splits',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('folio_id', sa.BigInteger(), sa.ForeignKey('folios.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('stay_id', sa.BigInteger(), sa.ForeignKey('hotel_stays.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('hotel_guest_id', sa.BigInteger(), sa.ForeignKey('hotel_guests.id', ondelete='SET NULL'), nullable=True),
        sa.Column('split_amount', sa.Numeric(15, 2), nullable=False),
        sa.Column('line_items', JSONB, server_default='[]', nullable=False),
        sa.Column('invoice_name', sa.String(255), nullable=True),
        sa.Column('invoice_tax_code', sa.String(50), nullable=True),
        sa.Column('invoice_contact', sa.String(255), nullable=True),
        sa.Column('invoice_address', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('printed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('printed_by', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('invoice_splits')
