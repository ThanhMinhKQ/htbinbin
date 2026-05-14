# app/db/session.py

from sqlalchemy import create_engine, NullPool
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from ..core.config import settings


# Main engine: HTTP requests
# Supabase Pro + uvicorn 1 worker + ~50 active users.
# Max HTTP DB connections = pool_size + max_overflow = 50.
engine = create_engine(
    str(settings.DATABASE_URL),
    pool_pre_ping=True,
    pool_size=25,
    max_overflow=25,
    pool_timeout=30,
    pool_recycle=1800,
    connect_args={"prepare_threshold": None},
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# Task engine: background jobs / OTA / scheduler
# NullPool keeps background jobs from holding idle connections.
_task_engine = create_engine(
    str(settings.DATABASE_URL),
    poolclass=NullPool,
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args={"prepare_threshold": None},
)

TaskSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=_task_engine,
)


Base = declarative_base()


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
