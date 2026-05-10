"""Add CRM membership settings

Revision ID: add_crm_membership_settings
Revises: add_guest_stay_mappings
Create Date: 2026-05-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "add_crm_membership_settings"
down_revision: Union[str, None] = "add_guest_stay_mappings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_membership_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("points_per_1000_vnd", sa.NUMERIC(10, 2), nullable=False, server_default="1"),
        sa.Column("tiers", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("crm_membership_settings")
