# BẢN NÀY DÙNG ĐỂ CHẠY LOCAL NHANH BẢN PHÙ HỢP NHẤT LÀ BẢN ĐANG TRÊN RENDER ĐỂ TẬN DỤNG HẾT SỨC MẠNH CỦA BẢN PRO

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base

# Import đối tượng `settings` từ file config
from ..core.config import settings

# === SỬA LỖI Ở ĐÂY: Ép kiểu str() cho settings.DATABASE_URL ===
engine = create_engine(
    str(settings.DATABASE_URL),  # Chuyển đổi PostgresDsn thành string
    pool_pre_ping=True,
    pool_size=10,           # 10 connections luôn sẵn trong pool
    max_overflow=5,         # Tối đa 15 connections tổng (10 + 5 overflow)
    pool_timeout=30,        # Timeout sau 30s nếu không lấy được connection (thay vì chờ mãi)
    pool_recycle=1800,      # Recycle connection sau 30 phút tránh stale connection
    connect_args={"prepare_threshold": None}  # Fix lỗi prepared statements
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class cho các model. Tất cả các model sẽ kế thừa từ lớp này.
Base = declarative_base()

def get_db():
    """Dependency to get a DB session for FastAPI."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()