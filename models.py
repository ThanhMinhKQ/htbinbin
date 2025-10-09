# models.py
import enum
from sqlalchemy import Column, String, Integer, DateTime, Text, Date, Boolean, Float, Time, Enum as SQLAlchemyEnum
from database import Base
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

class User(Base):
    __tablename__ = "users"

    code = Column(String(50), primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    password = Column(String(255), nullable=True)
    role = Column(String(50), nullable=False)
    branch = Column(String(50), nullable=False)
    
    # === THAY ĐỔI CHÍNH Ở ĐÂY ===
    # Sửa từ JSONB thành ARRAY(Text) để khớp với kiểu text[] trong database
    last_checked_in_bp = Column(JSONB, nullable=True)
    last_active_branch = Column(String, nullable=True)

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
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

class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ngay_diem_danh = Column(Date, nullable=False, index=True)
    gio_diem_danh = Column(Time, nullable=False)
    nguoi_diem_danh = Column(String(50), nullable=False, index=True)
    ma_nv = Column(String(50), nullable=False, index=True)
    ten_nv = Column(String(100))
    role = Column(String(50))
    chi_nhanh_chinh = Column(String(50))
    chi_nhanh_lam = Column(String(50), index=True)
    la_tang_ca = Column(Boolean, default=False)
    so_cong_nv = Column(Float, default=1.0)
    ghi_chu = Column(Text)

class ServiceRecord(Base):
    __tablename__ = "service_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ngay_cham = Column(Date, nullable=False, index=True)
    gio_cham = Column(Time, nullable=False)
    nguoi_cham = Column(String(50), nullable=False, index=True)
    ma_nv = Column(String(50), nullable=False, index=True)
    ten_nv = Column(String(100))
    role = Column(String(50))
    chi_nhanh_chinh = Column(String(50))
    chi_nhanh_lam = Column(String(50), index=True)
    la_tang_ca = Column(Boolean, default=False)
    dich_vu = Column(String(100), nullable=False)
    so_phong = Column(String(50))
    so_luong = Column(String(50))
    ghi_chu = Column(Text)

class LostItemStatus(str, enum.Enum):
    STORED = "Đang lưu giữ"
    RETURNED = "Đã trả khách"
    DISPOSED = "Thanh lý"
    DELETED = "Đã xoá"

class LostAndFoundItem(Base):
    __tablename__ = "lost_and_found_items"

    id = Column(Integer, primary_key=True, index=True)
    item_name = Column(String, nullable=False)
    description = Column(String)
    found_date = Column(DateTime(timezone=True), nullable=False)
    found_location = Column(String, nullable=False)
    recorded_by = Column(String, nullable=False)
    status = Column(SQLAlchemyEnum(LostItemStatus, name="lostitemstatus", native_enum=True), default=LostItemStatus.STORED, nullable=False)
    owner_name = Column(String, nullable=True)
    owner_contact = Column(String, nullable=True)
    return_date = Column(DateTime(timezone=True))
    reported_by = Column(String)
    notes = Column(String)
    chi_nhanh = Column(String, nullable=False)
    disposed_by = Column(String, nullable=True)
    disposed_amount = Column(Float, nullable=True)
    deleted_by = Column(String, nullable=True)
    deleted_date = Column(DateTime(timezone=True), nullable=True)
