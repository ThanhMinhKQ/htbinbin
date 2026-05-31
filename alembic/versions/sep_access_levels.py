"""separate access levels from departments + decouple head office branch

Tách cấp quyền (access_level) khỏi phòng ban, gỡ chi nhánh giả (KTV/QL/ADMIN/BOSS/DI DONG):
- departments: thêm access_level / is_active / is_system, backfill từ role_code.
- branches: thêm is_headoffice / is_active; chuyển chi nhánh ADMIN/BOSS cũ thành head office
  (Kho Tổng), nếu không có thì tạo branch HEAD.
- users: gỡ main_branch_id/last_active_branch_id đang trỏ chi nhánh giả (đặt NULL).
- giữ lại các row chi nhánh giả (history attendance/service RESTRICT FK + calendar snapshot
  phụ thuộc) nhưng đặt is_active=false để ẩn khỏi picker.

LƯU Ý: bước gỡ user khỏi chi nhánh giả KHÔNG tự revert được (mất gán cũ). Backup DB trước.

Revision ID: sep_access_levels
Revises: a1f7c9d2e3b4
Create Date: 2026-05-31 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'sep_access_levels'
down_revision: Union[str, Sequence[str], None] = 'a1f7c9d2e3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# role_code -> access_level
_ROLE_TO_LEVEL = {
    "boss": "OWNER",
    "admin": "ADMIN",
    "quanly": "MANAGER",
    "letan": "STAFF",
    "buongphong": "STAFF",
    "baove": "STAFF",
    "ktv": "STAFF",
    "khac": "STAFF",
}

_FAKE_BRANCH_CODES = ["KTV", "QL", "DI DONG", "ADMIN", "BOSS"]
_HEADOFFICE_CANDIDATES = ["HEAD", "TONG", "ADMIN", "BOSS"]


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Enum access_level
    access_level_enum = postgresql.ENUM(
        "OWNER", "ADMIN", "MANAGER", "STAFF", name="access_level"
    )
    access_level_enum.create(bind, checkfirst=True)

    # 2) Thêm cột departments (access_level nullable trước để backfill)
    op.add_column("departments", sa.Column("access_level", access_level_enum, nullable=True))
    op.add_column("departments", sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False))
    op.add_column("departments", sa.Column("is_system", sa.Boolean(), server_default="false", nullable=False))

    # 3) Thêm cột branches
    op.add_column("branches", sa.Column("is_headoffice", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("branches", sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False))

    # 4) Backfill departments.access_level từ role_code
    for code, level in _ROLE_TO_LEVEL.items():
        op.execute(
            sa.text("UPDATE departments SET access_level = CAST(:lvl AS access_level) WHERE role_code = :code")
            .bindparams(lvl=level, code=code)
        )
    # role_code lạ (không map) -> STAFF an toàn
    op.execute("UPDATE departments SET access_level = 'STAFF' WHERE access_level IS NULL")

    # 5) Heal: đảm bảo có đủ 8 phòng ban built-in; đánh dấu is_system
    builtin = [
        ("boss", "Boss", "OWNER"),
        ("admin", "Admin", "ADMIN"),
        ("quanly", "Quản lý", "MANAGER"),
        ("letan", "Lễ tân", "STAFF"),
        ("buongphong", "Buồng Phòng", "STAFF"),
        ("ktv", "Kỹ thuật viên", "STAFF"),
        ("baove", "Bảo vệ", "STAFF"),
        ("khac", "Khác", "STAFF"),
    ]
    for code, name, level in builtin:
        op.execute(
            sa.text("""
                INSERT INTO departments (role_code, name, access_level, is_active, is_system)
                VALUES (:code, :name, CAST(:lvl AS access_level), true, true)
                ON CONFLICT (role_code) DO UPDATE SET is_system = true
            """).bindparams(code=code, name=name, lvl=level)
        )

    # 6) access_level NOT NULL sau khi backfill xong
    op.alter_column("departments", "access_level", nullable=False)

    # 7) Head office: chỉ chọn DUY NHẤT 1 chi nhánh làm Kho Tổng (theo thứ tự ưu tiên).
    #    Tránh đánh dấu nhiều branch khiến picker/dispatch mơ hồ.
    chosen = None
    for cand in _HEADOFFICE_CANDIDATES:  # HEAD > TONG > ADMIN > BOSS
        row = bind.execute(
            sa.text("SELECT id FROM branches WHERE upper(branch_code) = :c").bindparams(c=cand)
        ).first()
        if row:
            chosen = row[0]
            break
    if chosen is not None:
        op.execute(
            sa.text("UPDATE branches SET is_headoffice = true WHERE id = :id").bindparams(id=chosen)
        )
    else:
        # Không có candidate nào → tạo branch HEAD mới
        op.execute(
            "INSERT INTO branches (branch_code, name, is_headoffice, is_active) "
            "VALUES ('HEAD', 'Kho Tổng / Văn phòng', true, true)"
        )

    # 8) Gỡ users khỏi chi nhánh giả (đặt main_branch_id / last_active_branch_id = NULL)
    #    - Mọi user trỏ vào chi nhánh giả (trừ head office) đều được gỡ.
    op.execute(
        sa.text("""
            UPDATE users SET main_branch_id = NULL
            WHERE main_branch_id IN (
                SELECT id FROM branches
                WHERE upper(branch_code) IN :codes AND is_headoffice = false
            )
        """).bindparams(sa.bindparam("codes", value=tuple(_FAKE_BRANCH_CODES), expanding=True))
    )
    op.execute(
        sa.text("""
            UPDATE users SET last_active_branch_id = NULL
            WHERE last_active_branch_id IN (
                SELECT id FROM branches
                WHERE upper(branch_code) IN :codes AND is_headoffice = false
            )
        """).bindparams(sa.bindparam("codes", value=tuple(_FAKE_BRANCH_CODES), expanding=True))
    )
    # Cấp cao (OWNER/ADMIN/MANAGER) không gắn chi nhánh
    op.execute("""
        UPDATE users SET main_branch_id = NULL
        WHERE department_id IN (
            SELECT id FROM departments WHERE access_level IN ('OWNER','ADMIN','MANAGER')
        )
    """)

    # 9) Ẩn chi nhánh giả khỏi picker (giữ row cho history); head office vẫn active
    op.execute(
        sa.text("""
            UPDATE branches SET is_active = false
            WHERE upper(branch_code) IN :codes AND is_headoffice = false
        """).bindparams(sa.bindparam("codes", value=tuple(_FAKE_BRANCH_CODES), expanding=True))
    )


def downgrade() -> None:
    # LƯU Ý: phần gỡ user khỏi chi nhánh giả (bước 8 upgrade) KHÔNG khôi phục được.
    # Chỉ revert được phần schema.
    op.drop_column("branches", "is_active")
    op.drop_column("branches", "is_headoffice")
    op.drop_column("departments", "is_system")
    op.drop_column("departments", "is_active")
    op.drop_column("departments", "access_level")
    access_level_enum = postgresql.ENUM(
        "OWNER", "ADMIN", "MANAGER", "STAFF", name="access_level"
    )
    access_level_enum.drop(op.get_bind(), checkfirst=True)
