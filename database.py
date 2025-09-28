from sqlalchemy import create_engine, NullPool
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from config import DATABASE_URL

# Tạo engine kết nối đến database từ URL trong file config.
# Thêm connect_args để tắt prepared statements, tương thích với PgBouncer trên Render.
# Thêm poolclass=NullPool để SQLAlchemy không quản lý pool, giao cho PgBouncer.
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "prepare_threshold": None,
        "options": "-c TimeZone=Asia/Ho_Chi_Minh"
    },
    poolclass=NullPool,
    pool_pre_ping=True, # Kiểm tra kết nối trước mỗi lần checkout
    pool_recycle=300,   # Tái sử dụng kết nối sau 300 giây
    echo=False          # Tắt logging SQL query để tránh làm rối log
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
