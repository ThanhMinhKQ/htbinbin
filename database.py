# database.py

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={
        "options": "-c TimeZone=Asia/Ho_Chi_Minh"
    },
    pool_pre_ping=True, # GIỮ NGUYÊN: Rất quan trọng để kiểm tra kết nối
    pool_recycle=240,   # SỬA LẠI: Giảm từ 300 xuống 240 giây (4 phút)
    pool_size=5,        
    max_overflow=10,    
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
