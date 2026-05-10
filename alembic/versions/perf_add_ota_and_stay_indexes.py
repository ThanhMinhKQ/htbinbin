"""Perf: add composite indexes for OTA logs and hotel stays

Revision ID: perf_add_ota_and_stay_indexes
Revises: add_reservation_hub
Create Date: 2026-05-08

Mục đích:
- /api/pms/reservations/ota/status: filter status + order by received_at DESC LIMIT 80
  → cần composite (status, received_at DESC) để index scan thay vì seq scan + sort.
- /api/pms/rooms Q2 và _get_occupied_rooms_for_dates: filter status='ACTIVE' + branch_id
  → partial index chỉ chứa stays ACTIVE để index nhỏ, query nhanh.

Dùng CREATE INDEX CONCURRENTLY để không lock bảng trên DB production.
CONCURRENTLY không chạy được trong transaction → COMMIT trước từng statement.

Trước khi chạy, xác nhận head: `alembic heads`
Nếu head không phải `add_reservation_hub`, sửa `down_revision` bên dưới.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "perf_add_ota_and_stay_indexes"
down_revision: Union[str, None] = "add_reservation_hub"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CONCURRENTLY yêu cầu ra ngoài transaction
    op.execute("COMMIT")

    # 1. OTA logs: query pattern là filter status + ORDER BY received_at DESC LIMIT N
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ota_logs_status_received_desc "
        "ON ota_parsing_logs (status, received_at DESC)"
    )

    # 2. OTA logs: join booking_id + lấy mới nhất
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ota_logs_booking_received_desc "
        "ON ota_parsing_logs (booking_id, received_at DESC) "
        "WHERE booking_id IS NOT NULL"
    )

    # 3. hotel_stays: partial index chỉ chứa stays ACTIVE cho branch+room lookup
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_stay_active_branch_room "
        "ON hotel_stays (branch_id, room_id) "
        "WHERE status = 'ACTIVE'"
    )

    # 4. hotel_stays: date-range queries cho availability/occupied rooms
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_stay_active_branch_dates "
        "ON hotel_stays (branch_id, check_in_at, check_out_at) "
        "WHERE status = 'ACTIVE'"
    )


def downgrade() -> None:
    op.execute("COMMIT")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_stay_active_branch_dates")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_stay_active_branch_room")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_ota_logs_booking_received_desc")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_ota_logs_status_received_desc")
