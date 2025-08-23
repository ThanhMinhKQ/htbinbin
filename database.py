# database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL

# Tạo PostgreSQL engine, tối ưu cho Transaction Pooler
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

# Tạo session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base cho models
Base = declarative_base()

# Hàm tạo bảng
def init_db():
    # Import tất cả models
    from models import User, Task, AttendanceLog
    Base.metadata.create_all(bind=engine)
    print("✅ All tables created successfully!")
