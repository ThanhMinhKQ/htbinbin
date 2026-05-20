"""Add invoice fields to guests table (CRM master)

Revision ID: add_guest_invoice_fields
Revises: shift_folio_bidirectional_links
Create Date: 2026-05-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_guest_invoice_fields'
down_revision: Union[str, None] = 'shift_folio_bidirectional_links'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('guests', sa.Column('tax_code', sa.String(50), nullable=True))
    op.add_column('guests', sa.Column('invoice_contact', sa.String(255), nullable=True))
    op.add_column('guests', sa.Column('company_name', sa.String(255), nullable=True))
    op.add_column('guests', sa.Column('company_address', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('guests', 'company_address')
    op.drop_column('guests', 'company_name')
    op.drop_column('guests', 'invoice_contact')
    op.drop_column('guests', 'tax_code')
