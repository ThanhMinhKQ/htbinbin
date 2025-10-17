from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={
        "options": "-c TimeZone=Asia/Ho_Chi_Minh"
    },
    pool_pre_ping=True, # Vẫn giữ, cực kỳ quan trọng
    pool_recycle=240,   # Vẫn giữ, rất tốt

    # SỬA LẠI CÁC THAM SỐ NÀY
    pool_size=3,        # Giữ 3 kết nối luôn mở
    max_overflow=5,     # Cho phép tạo thêm tối đa 5 kết nối khi cần
    
    echo=False
)

# ... phần còn lại giữ nguyên ...
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
