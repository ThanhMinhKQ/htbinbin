"""merge_heads

Revision ID: 3875059fd0d9
Revises: a5dea715d9ff, cfb2a8b3f522
Create Date: 2026-05-17 10:53:04.349775

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3875059fd0d9'
down_revision: Union[str, Sequence[str], None] = ('a5dea715d9ff', 'cfb2a8b3f522')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
