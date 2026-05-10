"""Add guest_stay_mappings table for co-guest relationships

Revision ID: add_guest_stay_mappings
Revises: shift_folio_bidirectional_links
Create Date: 2026-04-28

- Create guest_stay_mappings table to store co-guest relationships
- Each row links a guest to a stay they were part of
- Used to query "who stayed with whom"
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "add_guest_stay_mappings"
down_revision: Union[str, None] = "shift_folio_bidirectional_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guest_stay_mappings",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("guest_id", sa.BigInteger(), nullable=False),
        sa.Column("stay_id", sa.BigInteger(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("room_number", sa.String(20), nullable=True),
        sa.Column("check_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["guest_id"], ["guests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stay_id"], ["hotel_stays.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_guest_stay_mapping_unique", "guest_stay_mappings", ["guest_id", "stay_id"], unique=True)
    op.create_index("ix_guest_stay_mapping_guest", "guest_stay_mappings", ["guest_id"])
    op.create_index("ix_guest_stay_mapping_stay", "guest_stay_mappings", ["stay_id"])


def downgrade() -> None:
    op.drop_index("ix_guest_stay_mapping_stay", table_name="guest_stay_mappings")
    op.drop_index("ix_guest_stay_mapping_guest", table_name="guest_stay_mappings")
    op.drop_index("ix_guest_stay_mapping_unique", table_name="guest_stay_mappings")
    op.drop_table("guest_stay_mappings")
