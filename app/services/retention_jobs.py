"""Background jobs dọn dữ liệu log/audit cũ để tránh phình database.

Nguyên tắc an toàn:
- KHÔNG đụng dữ liệu tài chính / pháp lý / PII (folios, payments, bookings,
  hotel_stays, guests, attendance_records, shift_report_transactions...).
- Chỉ dọn log thuần (append-only) và dữ liệu tái tạo được.
- Xóa theo lô (batch) để tránh giữ lock bảng quá lâu trên Supabase.
- Mỗi bảng một hàm riêng, log số row đã dọn.

Mức giữ mặc định: 365 ngày (RETENTION_DAYS).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import text

from ..core.config import logger
from ..core.utils import VN_TZ
from ..db.session import SessionLocal

# Số ngày giữ lại dữ liệu log trước khi dọn.
RETENTION_DAYS = 365

# Số ngày giữ tồn phòng quá khứ (room_inventory_daily tái tạo được).
INVENTORY_DAILY_RETENTION_DAYS = 365

# Số row xóa mỗi lô để tránh lock bảng lâu.
_BATCH_SIZE = 5000


def _batched_delete(db, table: str, where_sql: str, params: dict) -> int:
    """Xóa theo lô dùng ctid. Trả về tổng số row đã xóa.

    Lặp lại DELETE ... WHERE ctid IN (SELECT ctid ... LIMIT batch) cho tới khi
    không còn row khớp. Commit sau mỗi lô để giải phóng lock sớm.
    """
    total = 0
    sql = text(
        f"DELETE FROM {table} WHERE ctid IN "
        f"(SELECT ctid FROM {table} WHERE {where_sql} LIMIT :_batch)"
    )
    batch_params = {**params, "_batch": _BATCH_SIZE}
    while True:
        result = db.execute(sql, batch_params)
        deleted = result.rowcount or 0
        if deleted:
            db.commit()
            total += deleted
        if deleted < _BATCH_SIZE:
            break
    return total


def _purge_ota_parsing_logs(db, cutoff: datetime) -> None:
    """Xóa nội dung nặng (raw_content, error_traceback) của log OTA cũ đã SUCCESS.

    Giữ lại metadata (subject, sender, status, booking_id) để vẫn tra cứu được
    lịch sử; chỉ rỗng hóa các cột text nặng nhất.
    """
    result = db.execute(
        text(
            "UPDATE ota_parsing_logs "
            "SET raw_content = NULL, error_traceback = NULL "
            "WHERE received_at < :cutoff "
            "AND status = 'SUCCESS' "
            "AND (raw_content IS NOT NULL OR error_traceback IS NOT NULL)"
        ),
        {"cutoff": cutoff},
    )
    db.commit()
    count = result.rowcount or 0
    if count:
        logger.info("[Retention] ota_parsing_logs: rỗng hóa nội dung %s log cũ", count)


def _purge_plain_logs(db, cutoff: datetime, inventory_cutoff_date) -> None:
    """DELETE row cũ trên các bảng log thuần (append-only, an toàn để xóa)."""
    targets = [
        ("room_inventory_logs", "created_at < :cutoff", {"cutoff": cutoff}),
        ("inventory_audit_logs", "created_at < :cutoff", {"cutoff": cutoff}),
        ("attendance_log", "created_at < :cutoff", {"cutoff": cutoff}),
        ("shift_notification_reads", "read_at < :cutoff", {"cutoff": cutoff}),
        # Holds đã released mới xóa; hold chưa released vẫn đang giữ phòng.
        (
            "room_inventory_holds",
            "released = true AND created_at < :cutoff",
            {"cutoff": cutoff},
        ),
        # Tồn phòng theo ngày quá khứ xa — tái tạo được nếu cần.
        (
            "room_inventory_daily",
            "date < :inv_cutoff",
            {"inv_cutoff": inventory_cutoff_date},
        ),
    ]
    for table, where_sql, params in targets:
        try:
            deleted = _batched_delete(db, table, where_sql, params)
            if deleted:
                logger.info("[Retention] %s: đã xóa %s row cũ", table, deleted)
        except Exception as exc:
            db.rollback()
            logger.error("[Retention] Lỗi dọn %s: %s", table, exc, exc_info=True)


def run_retention_cleanup() -> None:
    """Entry point cho scheduler: dọn toàn bộ nhóm log theo mức giữ cấu hình."""
    db = SessionLocal()
    try:
        now = datetime.now(VN_TZ)
        cutoff = now - timedelta(days=RETENTION_DAYS)
        inventory_cutoff_date = (now - timedelta(days=INVENTORY_DAILY_RETENTION_DAYS)).date()
        logger.info("[Retention] Bắt đầu dọn dữ liệu cũ hơn %s (giữ %s ngày)", cutoff.date(), RETENTION_DAYS)

        _purge_ota_parsing_logs(db, cutoff)
        _purge_plain_logs(db, cutoff, inventory_cutoff_date)

        logger.info("[Retention] Hoàn tất dọn dữ liệu log cũ")
    except Exception as exc:
        db.rollback()
        logger.error("[Retention] Job dọn dữ liệu thất bại: %s", exc, exc_info=True)
    finally:
        db.close()
