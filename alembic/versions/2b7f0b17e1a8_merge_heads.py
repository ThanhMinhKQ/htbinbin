"""merge heads

Revision ID: 2b7f0b17e1a8
Revises: add_handbook_entries, add_shift_notifications
Create Date: 2026-05-26 07:02:07.384021

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b7f0b17e1a8'
down_revision: Union[str, Sequence[str], None] = ('add_handbook_entries', 'add_shift_notifications')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
