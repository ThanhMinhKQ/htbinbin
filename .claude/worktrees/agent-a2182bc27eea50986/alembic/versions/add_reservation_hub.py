"""Add reservation hub inventory tables and booking fields

Revision ID: add_reservation_hub
Revises: add_crm_membership_settings
Create Date: 2026-05-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "add_reservation_hub"
down_revision: Union[str, None] = "add_crm_membership_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("bookings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("booking_type", sa.String(length=20), nullable=False, server_default="OTA"))
        batch_op.add_column(sa.Column("reservation_status", sa.String(length=20), nullable=False, server_default="CONFIRMED"))
        batch_op.add_column(sa.Column("assigned_room_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("stay_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("estimated_arrival", sa.Time(), nullable=True))
        batch_op.add_column(sa.Column("special_requests", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("internal_notes", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("cancel_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("no_show_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key("fk_bookings_assigned_room_id", "hotel_rooms", ["assigned_room_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_bookings_stay_id", "hotel_stays", ["stay_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_bookings_booking_type", ["booking_type"])
        batch_op.create_index("ix_bookings_assigned_room_id", ["assigned_room_id"])
        batch_op.create_index("ix_bookings_stay_id", ["stay_id"])
        batch_op.create_index("ix_booking_reservation_status", ["reservation_status"])
        batch_op.create_index("ix_booking_branch_checkin_status", ["branch_id", "check_in", "reservation_status"])

    op.create_table(
        "room_inventory_daily",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("room_type_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("total_rooms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_rooms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_rooms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sold_rooms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("out_of_order_rooms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overbooking_limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("base_price", sa.NUMERIC(15, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["room_type_id"], ["hotel_room_types.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_room_inventory_branch_type_date", "room_inventory_daily", ["branch_id", "room_type_id", "date"], unique=True)
    op.create_index("ix_room_inventory_branch_date", "room_inventory_daily", ["branch_id", "date"])

    op.create_table(
        "room_blocks",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["room_id"], ["hotel_rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_room_blocks_room_id", "room_blocks", ["room_id"])
    op.create_index("ix_room_blocks_branch_id", "room_blocks", ["branch_id"])
    op.create_index("ix_room_blocks_start_date", "room_blocks", ["start_date"])
    op.create_index("ix_room_blocks_end_date", "room_blocks", ["end_date"])
    op.create_index("ix_room_blocks_status", "room_blocks", ["status"])

    op.create_table(
        "room_inventory_holds",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("booking_id", sa.BigInteger(), nullable=True),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("room_type_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("hold_type", sa.String(length=20), nullable=False, server_default="MANUAL"),
        sa.Column("expire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["room_type_id"], ["hotel_room_types.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_room_inventory_holds_booking_id", "room_inventory_holds", ["booking_id"])
    op.create_index("ix_room_inventory_holds_branch_id", "room_inventory_holds", ["branch_id"])
    op.create_index("ix_room_inventory_holds_room_type_id", "room_inventory_holds", ["room_type_id"])
    op.create_index("ix_room_inventory_holds_date", "room_inventory_holds", ["date"])
    op.create_index("ix_room_inventory_holds_expire_at", "room_inventory_holds", ["expire_at"])
    op.create_index("ix_room_inventory_holds_released", "room_inventory_holds", ["released"])

    op.create_table(
        "room_inventory_logs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("room_type_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("change_type", sa.String(length=30), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("field_changed", sa.String(length=20), nullable=False),
        sa.Column("ref_type", sa.String(length=20), nullable=True),
        sa.Column("ref_id", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["room_type_id"], ["hotel_room_types.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_room_inventory_logs_branch_id", "room_inventory_logs", ["branch_id"])
    op.create_index("ix_room_inventory_logs_room_type_id", "room_inventory_logs", ["room_type_id"])
    op.create_index("ix_room_inventory_logs_date", "room_inventory_logs", ["date"])
    op.create_index("ix_room_inventory_logs_change_type", "room_inventory_logs", ["change_type"])
    op.create_index("ix_room_inventory_logs_ref_id", "room_inventory_logs", ["ref_id"])
    op.create_index("ix_room_inventory_logs_created_at", "room_inventory_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_room_inventory_logs_created_at", table_name="room_inventory_logs")
    op.drop_index("ix_room_inventory_logs_ref_id", table_name="room_inventory_logs")
    op.drop_index("ix_room_inventory_logs_change_type", table_name="room_inventory_logs")
    op.drop_index("ix_room_inventory_logs_date", table_name="room_inventory_logs")
    op.drop_index("ix_room_inventory_logs_room_type_id", table_name="room_inventory_logs")
    op.drop_index("ix_room_inventory_logs_branch_id", table_name="room_inventory_logs")
    op.drop_table("room_inventory_logs")

    op.drop_index("ix_room_inventory_holds_released", table_name="room_inventory_holds")
    op.drop_index("ix_room_inventory_holds_expire_at", table_name="room_inventory_holds")
    op.drop_index("ix_room_inventory_holds_date", table_name="room_inventory_holds")
    op.drop_index("ix_room_inventory_holds_room_type_id", table_name="room_inventory_holds")
    op.drop_index("ix_room_inventory_holds_branch_id", table_name="room_inventory_holds")
    op.drop_index("ix_room_inventory_holds_booking_id", table_name="room_inventory_holds")
    op.drop_table("room_inventory_holds")

    op.drop_index("ix_room_blocks_status", table_name="room_blocks")
    op.drop_index("ix_room_blocks_end_date", table_name="room_blocks")
    op.drop_index("ix_room_blocks_start_date", table_name="room_blocks")
    op.drop_index("ix_room_blocks_branch_id", table_name="room_blocks")
    op.drop_index("ix_room_blocks_room_id", table_name="room_blocks")
    op.drop_table("room_blocks")

    op.drop_index("ix_room_inventory_branch_date", table_name="room_inventory_daily")
    op.drop_index("uq_room_inventory_branch_type_date", table_name="room_inventory_daily")
    op.drop_table("room_inventory_daily")

    with op.batch_alter_table("bookings", schema=None) as batch_op:
        batch_op.drop_index("ix_booking_branch_checkin_status")
        batch_op.drop_index("ix_booking_reservation_status")
        batch_op.drop_index("ix_bookings_stay_id")
        batch_op.drop_index("ix_bookings_assigned_room_id")
        batch_op.drop_index("ix_bookings_booking_type")
        batch_op.drop_constraint("fk_bookings_stay_id", type_="foreignkey")
        batch_op.drop_constraint("fk_bookings_assigned_room_id", type_="foreignkey")
        batch_op.drop_column("no_show_at")
        batch_op.drop_column("cancel_reason")
        batch_op.drop_column("cancelled_at")
        batch_op.drop_column("confirmed_at")
        batch_op.drop_column("internal_notes")
        batch_op.drop_column("special_requests")
        batch_op.drop_column("estimated_arrival")
        batch_op.drop_column("stay_id")
        batch_op.drop_column("assigned_room_id")
        batch_op.drop_column("reservation_status")
        batch_op.drop_column("booking_type")
