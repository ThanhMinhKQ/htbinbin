"""Add shift notifications

Revision ID: add_shift_notifications
Revises: 3875059fd0d9, add_invoice_splits
Create Date: 2026-05-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_shift_notifications"
down_revision: Union[str, Sequence[str], None] = ("3875059fd0d9", "add_invoice_splits")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shift_notifications",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schedule_shift", sa.String(10), nullable=True),
        sa.Column("min_read_seconds", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("audience_roles", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("branch_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.Column("updated_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shift_notifications_is_active", "shift_notifications", ["is_active"])
    op.create_index("ix_shift_notifications_starts_at", "shift_notifications", ["starts_at"])
    op.create_index("ix_shift_notifications_ends_at", "shift_notifications", ["ends_at"])
    op.create_index("ix_shift_notifications_schedule_shift", "shift_notifications", ["schedule_shift"])
    op.create_index("ix_shift_notifications_deleted_at", "shift_notifications", ["deleted_at"])
    op.create_index("ix_shift_notifications_created_by_id", "shift_notifications", ["created_by_id"])
    op.create_index("ix_shift_notifications_updated_by_id", "shift_notifications", ["updated_by_id"])

    op.create_table(
        "shift_notification_reads",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("notification_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("attendance_log_id", sa.BigInteger(), nullable=True),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("shift", sa.String(10), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["attendance_log_id"], ["attendance_log.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["notification_id"], ["shift_notifications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notification_id", "user_id", "work_date", "shift", name="uq_shift_notification_read_once"),
    )
    op.create_index("ix_shift_notification_reads_notification_id", "shift_notification_reads", ["notification_id"])
    op.create_index("ix_shift_notification_reads_user_id", "shift_notification_reads", ["user_id"])
    op.create_index("ix_shift_notification_reads_attendance_log_id", "shift_notification_reads", ["attendance_log_id"])
    op.create_index("ix_shift_notification_reads_work_date", "shift_notification_reads", ["work_date"])
    op.create_index("ix_shift_notification_reads_shift", "shift_notification_reads", ["shift"])


def downgrade() -> None:
    op.drop_index("ix_shift_notification_reads_shift", table_name="shift_notification_reads")
    op.drop_index("ix_shift_notification_reads_work_date", table_name="shift_notification_reads")
    op.drop_index("ix_shift_notification_reads_attendance_log_id", table_name="shift_notification_reads")
    op.drop_index("ix_shift_notification_reads_user_id", table_name="shift_notification_reads")
    op.drop_index("ix_shift_notification_reads_notification_id", table_name="shift_notification_reads")
    op.drop_table("shift_notification_reads")
    op.drop_index("ix_shift_notifications_updated_by_id", table_name="shift_notifications")
    op.drop_index("ix_shift_notifications_created_by_id", table_name="shift_notifications")
    op.drop_index("ix_shift_notifications_deleted_at", table_name="shift_notifications")
    op.drop_index("ix_shift_notifications_schedule_shift", table_name="shift_notifications")
    op.drop_index("ix_shift_notifications_ends_at", table_name="shift_notifications")
    op.drop_index("ix_shift_notifications_starts_at", table_name="shift_notifications")
    op.drop_index("ix_shift_notifications_is_active", table_name="shift_notifications")
    op.drop_table("shift_notifications")
