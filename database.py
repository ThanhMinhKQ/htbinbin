from sqlalchemy import create_engine, NullPool
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from config import DATABASE_URL

# Tạo engine kết nối đến database từ URL trong file config.
# Thêm connect_args để tắt prepared statements, tương thích với PgBouncer trên Render.
# Thêm poolclass=NullPool để SQLAlchemy không quản lý pool, giao cho PgBouncer.
engine = create_engine(
    DATABASE_URL,
    connect_args={"prepare_threshold": None},
    poolclass=NullPool
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

if __name__ == "__main__":
    print("--- SCRIPT TẠO BẢNG DATABASE ---")
    print("Cảnh báo: Script này sẽ tạo các bảng trong database nếu chúng chưa tồn tại.")
    # Hiển thị một phần URL để xác nhận, nhưng giấu thông tin nhạy cảm
    print(f"Kết nối tới database tại: ...{str(engine.url).split('@')[-1]}")
    
    confirm = input("Bạn có chắc chắn muốn tiếp tục? (y/n): ")
    if confirm.lower() == 'y':
        init_db()
    else:
        print("Đã hủy thao tác.")
