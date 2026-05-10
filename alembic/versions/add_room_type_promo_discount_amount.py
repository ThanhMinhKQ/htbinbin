"""Add fixed promo discount amount for room types

Revision ID: add_room_type_promo_discount_amount
Revises: perf_add_ota_and_stay_indexes
Create Date: 2026-05-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "add_room_type_promo_discount_amount"
down_revision: Union[str, None] = "perf_add_ota_and_stay_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hotel_room_types",
        sa.Column(
            "promo_discount_amount",
            sa.NUMERIC(15, 2),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("hotel_room_types", "promo_discount_amount")
