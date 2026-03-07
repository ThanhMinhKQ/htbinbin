# app/db/session.py

from sqlalchemy import create_engine, NullPool
from sqlalchemy.orm import sessionmaker, Session, declarative_base

from ..core.config import settings

# ── Main engine (cho HTTP requests) ──────────────────────────────────────────
# Supabase free tier giới hạn ~10 connections tổng.
# Giữ pool_size nhỏ để dành chỗ cho các request đồng thời + background tasks.
engine = create_engine(
    str(settings.DATABASE_URL),
    pool_pre_ping=True,
    pool_size=3,            # 3 connections luôn sẵn (HTTP requests thông thường)
    max_overflow=2,         # Tối đa 5 connections tổng
    pool_timeout=20,        # Timeout sau 20s, fail nhanh thay vì chờ mãi
    pool_recycle=1800,      # Recycle sau 30 phút tránh stale connection
    connect_args={"prepare_threshold": None}  # Fix lỗi prepared statements
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── Task engine (cho background tasks: OTA, scheduler) ───────────────────────
# Dùng NullPool: mỗi query tạo/huỷ connection riêng.
# Không dùng chung pool với HTTP → background task KHÔNG cạnh tranh với user
_task_engine = create_engine(
    str(settings.DATABASE_URL),
    poolclass=NullPool,     # Không giữ connection sau khi close()
    pool_pre_ping=True,
    connect_args={"prepare_threshold": None}
)

TaskSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_task_engine)


# ── Base & Dependency ─────────────────────────────────────────────────────────
Base = declarative_base()

def get_db():
    """Dependency FastAPI: HTTP requests dùng SessionLocal (có pool)."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()