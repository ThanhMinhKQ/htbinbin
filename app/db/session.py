# session.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool  # <--- IMPORT QUAN TRỌNG

from ..core.config import settings

# 1. Cấu hình Engine tối ưu cho Supabase Transaction Pooler
engine = create_engine(
    str(settings.DATABASE_URL),
    # Sử dụng NullPool để vô hiệu hóa connection pooling phía client (FastAPI).
    # Lý do: Chúng ta sẽ dùng Transaction Pooler (port 6543) của Supabase để quản lý kết nối.
    # Nếu dùng QueuePool (mặc định) chồng lên Transaction Pooler sẽ gây lỗi và lãng phí RAM.
    poolclass=NullPool,
    
    # Giữ pre_ping=True để kiểm tra kết nối sống trước khi dùng (tránh lỗi connection closed)
    pool_pre_ping=True,
    
    # Cấu hình này cực kỳ quan trọng với PgBouncer/Supavisor transaction mode
    # Nó ngăn SQLAlchemy tạo prepared statements, thứ không tương thích tốt với transaction pooling.
    connect_args={
        "prepare_threshold": None, 
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5
    }
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    """
    Dependency lấy DB session. 
    Session sẽ được đóng ngay sau khi request hoàn tất để trả kết nối về Pooler của Supabase.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
