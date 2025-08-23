# models.py
from sqlalchemy import Column, String, Integer, DateTime, Text, Date, Boolean, JSON
from sqlalchemy.dialects.postgresql import JSONB
from database import Base

class User(Base):
    __tablename__ = "users"

    code = Column(String(50), primary_key=True, index=True)  # Supabase chấp nhận varchar
    name = Column(String(100), nullable=False)
    password = Column(String(255), nullable=True)
    role = Column(String(50), nullable=False)
    branch = Column(String(50), nullable=False)
    last_checked_in_bp = Column(JSONB, nullable=True)  # Dùng JSONB chuẩn PostgreSQL

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    chi_nhanh = Column(String(50), nullable=False)
    phong = Column(String(50), nullable=False)
    mo_ta = Column(Text, nullable=False)
    ngay_tao = Column(DateTime(timezone=True), nullable=False)
    han_hoan_thanh = Column(DateTime(timezone=True), nullable=False)
    ngay_hoan_thanh = Column(DateTime(timezone=True), nullable=True)
    trang_thai = Column(String(50), nullable=False)
    nguoi_tao = Column(String(50), nullable=False)
    nguoi_thuc_hien = Column(String(50), nullable=True)
    ghi_chu = Column(Text, nullable=True)

class AttendanceLog(Base):
    __tablename__ = "attendance_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_code = Column(String(50), index=True)
    date = Column(Date, index=True)
    shift = Column(String(20), index=True)  # Ca làm việc: 'day' hoặc 'night'
    token = Column(String(255), unique=True, index=True)
    checked_in = Column(Boolean, default=False)
