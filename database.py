from sqlalchemy import create_engine, NullPool
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from config import DATABASE_URL
import re

# For Supabase's connection pooler, it's mandatory to use sslmode=require.
# The most robust way to ensure this is to modify the URL string directly,
# replacing any existing sslmode value. The `connect_args` approach can be
# unreliable if the URL already contains a conflicting sslmode.
final_db_url = DATABASE_URL
if "pooler.supabase.com" in final_db_url:
    if "sslmode=" in final_db_url:
        final_db_url = re.sub(r'sslmode=[^&]*', 'sslmode=require', final_db_url)
    else:
        separator = "&" if "?" in final_db_url else "?"
        final_db_url += f"{separator}sslmode=require"

engine = create_engine(
    final_db_url,
    connect_args={"prepare_threshold": None}, # For PgBouncer on Render
    poolclass=NullPool # Delegate pooling to PgBouncer
)

# Tạo một lớp Session để quản lý các phiên làm việc với DB
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class cho các model. Tất cả các model của bạn (User, Task,...)
# phải kế thừa từ lớp Base này.
Base = declarative_base()

def get_db():
    """Dependency to get a DB session."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """
    Hàm này sẽ được gọi khi ứng dụng khởi động.
    Nó import tất cả các model và tạo bảng trong database nếu chúng chưa tồn tại.
    """
    # Import tất cả các model để chúng được đăng ký
    from models import User, Task, AttendanceLog, AttendanceRecord, ServiceRecord

    print("Đang khởi tạo database và tạo các bảng nếu chưa tồn tại...")
    Base.metadata.create_all(bind=engine)
    print("Hoàn tất khởi tạo database.")
