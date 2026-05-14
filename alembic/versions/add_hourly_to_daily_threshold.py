"""Add hourly-to-daily threshold to room types

Revision ID: add_hourly_to_daily_threshold
Revises: add_room_type_promo_discount_amount
Create Date: 2026-05-14
"""
from typing import Sequence, Union

from alembic import op


revision: str = "add_hourly_to_daily_threshold"
down_revision: Union[str, None] = "add_room_type_promo_discount_amount"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hotel_room_types "
        "ADD COLUMN IF NOT EXISTS hourly_to_daily_threshold INTEGER DEFAULT 8"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE hotel_room_types DROP COLUMN IF EXISTS hourly_to_daily_threshold")
