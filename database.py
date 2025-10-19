from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from config import DATABASE_URL
# KHÔNG CẦN import NullPool

# Tạo engine kết nối đến database từ URL trong file config.
engine = create_engine(
    DATABASE_URL,
    connect_args={
        # Giữ lại cài đặt TimeZone là rất tốt
        "options": "-c TimeZone=Asia/Ho_Chi_Minh"
    },
    
    # Đây là các cài đặt VÀNG để làm việc với PgBouncer (cổng 6543)
    pool_pre_ping=True,   # Luôn kiểm tra kết nối có "sống" không trước khi dùng
    pool_recycle=300,   # Tái tạo kết nối sau 5 phút (tránh bị ngắt)
    pool_size=5,        # Giữ 5 kết nối sẵn sàng
    max_overflow=10,    # Cho phép mở thêm 10 (Tổng 15) khi có nhiều request
    
    echo=False
)

# Tạo một lớp Session để quản lý các phiên làm việc với DB
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class cho các model.
Base = declarative_base()

def get_db():
    """Dependency to get a DB session."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        # Lệnh này sẽ "trả" kết nối về pool, sẵn sàng cho request tiếp theo
        db.close()
