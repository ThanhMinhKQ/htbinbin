from sqlalchemy import Column, String, Integer, DateTime, Text, Date, Boolean, JSON
from database import Base

class User(Base):
    __tablename__ = "users"

    code = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, nullable=False)
    branch = Column(String, nullable=False)
    last_checked_in_bp = Column(JSON, nullable=True) 

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    chi_nhanh = Column(String, nullable=False)
    phong = Column(String, nullable=False)
    mo_ta = Column(Text, nullable=False)
    ngay_tao = Column(DateTime(timezone=True), nullable=False)
    han_hoan_thanh = Column(DateTime(timezone=True), nullable=False)
    ngay_hoan_thanh = Column(DateTime(timezone=True), nullable=True)
    trang_thai = Column(String, nullable=False)
    nguoi_tao = Column(String, nullable=False)
    nguoi_thuc_hien = Column(String, nullable=True)
    ghi_chu = Column(Text, nullable=True)

class AttendanceLog(Base):
    __tablename__ = "attendance_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_code = Column(String, index=True)
    date = Column(Date, index=True)
    shift = Column(String, index=True) # Ca làm việc: 'day' hoặc 'night'
    token = Column(String, unique=True, index=True)
    checked_in = Column(Boolean, default=False)
