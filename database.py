from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from config import DATABASE_URL
from sqlalchemy.pool import NullPool  # <-- 1. THÊM DÒNG NÀY

# Tạo engine kết nối đến database từ URL trong file config.
engine = create_engine(
    DATABASE_URL,
    connect_args={
        # Giữ lại cài đặt TimeZone là tốt, không ảnh hưởng đến pool
        "options": "-c TimeZone=Asia/Ho_Chi_Minh"
    },
    
    # <-- 2. THAY THẾ TOÀN BỘ CẤU HÌNH POOL CŨ BẰNG DÒNG NÀY
    poolclass=NullPool,
    
    # Bỏ tất cả các cài đặt cũ:
    # pool_pre_ping, pool_recycle, pool_size, max_overflow
    # Vì NullPool có nghĩa là "không có pool", nên các cài đặt đó
    # không còn ý nghĩa và bị vô hiệu hóa.
    
    echo=False
)

# Tạo một lớp Session để quản lý các phiên làm việc với DB
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class cho các model. Tất cả các model của bạn (User, Task,...)
# phải kế thừa từ lớp Base này.
Base = declarative_base()

def get_db():
    """
    Dependency để lấy một DB session.
    Với NullPool, mỗi lần gọi hàm này sẽ TẠO MỘT KẾT NỐI MỚI.
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        # Lệnh close() này bây giờ sẽ THỰC SỰ ĐÓNG kết nối vật lý,
        # ngay lập tức trả lại slot trống cho Supabase.
        # Đây là chìa khóa để không bao giờ bị cạn kiệt kết nối.
        db.close()
