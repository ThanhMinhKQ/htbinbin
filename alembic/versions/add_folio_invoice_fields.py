"""Add invoice fields to folios table (structured split-bill invoice)

Revision ID: add_folio_invoice_fields
Revises: add_guest_invoice_fields
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_folio_invoice_fields'
down_revision: Union[str, None] = 'add_guest_invoice_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('folios', sa.Column('invoice_name', sa.String(255), nullable=True))
    op.add_column('folios', sa.Column('invoice_tax_code', sa.String(50), nullable=True))
    op.add_column('folios', sa.Column('invoice_contact', sa.String(255), nullable=True))
    op.add_column('folios', sa.Column('invoice_address', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('folios', 'invoice_address')
    op.drop_column('folios', 'invoice_contact')
    op.drop_column('folios', 'invoice_tax_code')
    op.drop_column('folios', 'invoice_name')
