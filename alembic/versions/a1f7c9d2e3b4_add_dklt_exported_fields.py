"""add_dklt_exported_fields

Revision ID: a1f7c9d2e3b4
Revises: 4c3c30f314f2
Create Date: 2026-05-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f7c9d2e3b4'
down_revision: Union[str, Sequence[str], None] = '4c3c30f314f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'hotel_guests',
        sa.Column('dklt_exported_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'hotel_guests',
        sa.Column('dklt_exported_by', sa.BIGINT(), nullable=True),
    )
    op.create_foreign_key(
        'fk_hotel_guests_dklt_exported_by_users',
        'hotel_guests', 'users',
        ['dklt_exported_by'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_hotel_guests_dklt_exported_by_users',
        'hotel_guests', type_='foreignkey',
    )
    op.drop_column('hotel_guests', 'dklt_exported_by')
    op.drop_column('hotel_guests', 'dklt_exported_at')
