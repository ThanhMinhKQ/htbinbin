"""Add total_discount column to folios table

Revision ID: add_total_discount_to_folios
Revises: extend_pricing_mode_final
Create Date: 2026-04-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_total_discount_to_folios'
down_revision: Union[str, None] = 'extend_pricing_mode_final'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('folios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('total_discount', sa.NUMERIC(15, 2), nullable=False, server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('folios', schema=None) as batch_op:
        batch_op.drop_column('total_discount')
