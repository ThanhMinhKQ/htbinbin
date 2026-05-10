"""Extend pricing_mode_final column length in hotel_stays

Revision ID: extend_pricing_mode_final
Revises: b2f4b9b11a21
Create Date: 2026-04-13 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'extend_pricing_mode_final'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('hotel_stays', schema=None) as batch_op:
        batch_op.alter_column('pricing_mode_final', existing_type=sa.String(length=10), type_=sa.String(length=20), existing_nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('hotel_stays', schema=None) as batch_op:
        batch_op.alter_column('pricing_mode_final', existing_type=sa.String(length=20), type_=sa.String(length=10), existing_nullable=True)
