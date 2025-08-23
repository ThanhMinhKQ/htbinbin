from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL

# Tạo engine kết nối đến database từ URL trong file config
engine = create_engine(DATABASE_URL)

# Tạo một lớp Session để quản lý các phiên làm việc với DB
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class cho các model. Tất cả các model của bạn (User, Task,...)
# phải kế thừa từ lớp Base này.
Base = declarative_base()

def init_db():
    """
    Hàm này sẽ được gọi khi ứng dụng khởi động.
    Nó import tất cả các model và tạo bảng trong database nếu chúng chưa tồn tại.
    """
    # Import tất cả các model ở đây để chúng được đăng ký với Base
    from models import User, Task, AttendanceLog
    print("Đang khởi tạo database và tạo các bảng nếu chưa tồn tại...")
    Base.metadata.create_all(bind=engine)
    print("Hoàn tất khởi tạo database.")
