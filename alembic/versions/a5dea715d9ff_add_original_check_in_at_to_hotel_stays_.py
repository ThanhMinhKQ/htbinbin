"""add_original_check_in_at_to_hotel_stays_manual

Revision ID: a5dea715d9ff
Revises: shift_folio_bidirectional_links
Create Date: 2026-05-17 10:51:56.782881

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5dea715d9ff'
down_revision: Union[str, Sequence[str], None] = 'shift_folio_bidirectional_links'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'hotel_stays',
        sa.Column('original_check_in_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'hotel_stays',
        sa.Column('billing_start_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('hotel_stays', 'billing_start_at')
    op.drop_column('hotel_stays', 'original_check_in_at')
