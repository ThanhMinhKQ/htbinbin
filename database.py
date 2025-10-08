from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from config import DATABASE_URL

# Tạo engine kết nối đến database từ URL trong file config.
engine = create_engine(
    DATABASE_URL,
    connect_args={
        # Bỏ "prepare_threshold": None, không cần thiết với cấu hình mới
        "options": "-c TimeZone=Asia/Ho_Chi_Minh"
    },
    pool_pre_ping=True, # GIỮ LẠI: Đây là chìa khóa!
    pool_recycle=300,   # GIỮ LẠI: Tái tạo kết nối sau 5 phút, trước khi Supabase ngắt.
    pool_size=5,        # THÊM MỚI: Giữ 5 kết nối mở trong pool.
    max_overflow=10,    # THÊM MỚI: Cho phép tạo thêm 10 kết nối nếu pool hết.
    echo=False
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
