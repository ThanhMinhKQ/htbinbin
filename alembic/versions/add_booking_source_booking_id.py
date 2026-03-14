"""Add source_booking_id to bookings (bản sao chỉ đọc khi chuyển chi nhánh)

Revision ID: a1b2c3d4e5f6
Revises: b2f4b9b11a21
Create Date: 2026-03-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'b2f4b9b11a21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bookings', sa.Column('source_booking_id', sa.BIGINT(), nullable=True))
    op.create_foreign_key(
        'fk_bookings_source_booking_id',
        'bookings', 'bookings',
        ['source_booking_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_index('ix_bookings_source_booking_id', 'bookings', ['source_booking_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_bookings_source_booking_id', table_name='bookings')
    op.drop_constraint('fk_bookings_source_booking_id', 'bookings', type_='foreignkey')
    op.drop_column('bookings', 'source_booking_id')
