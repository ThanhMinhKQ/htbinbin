# app/db/session.py

from sqlalchemy import create_engine, NullPool
from sqlalchemy.orm import sessionmaker, Session, declarative_base

from ..core.config import settings

# ── Main engine (cho HTTP requests) ──────────────────────────────────────────
# Supabase Pro ($25): session pooler ~200 connections. Giữ 20+20 an toàn cho
# nhiều worker + background tasks + dash poll đồng thời.
engine = create_engine(
    str(settings.DATABASE_URL),
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=20,
    pool_timeout=10,
    pool_recycle=1800,
    connect_args={"prepare_threshold": None}
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