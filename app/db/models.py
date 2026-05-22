# app/db/models.py
import enum
from decimal import Decimal
from sqlalchemy import (
    Column, String, Integer, DateTime, Text, Date, Boolean, Float, Time,
    Enum as SQLAlchemyEnum, ForeignKey, BIGINT, NUMERIC, Index, func,
    CheckConstraint, UniqueConstraint
)
from datetime import date as date_type
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from datetime import datetime

# Import Base từ session
from .session import Base

# ====================================================================
# 1. ENUM TYPES (Định nghĩa các giá trị cố định)
# ====================================================================

class LostItemStatus(str, enum.Enum):
    STORED = "STORED"       
    RETURNED = "RETURNED"
    DISPOSED = "DISPOSED"
    DISPOSABLE = "DISPOSABLE"
    DELETED = "DELETED"

class ShiftReportStatus(str, enum.Enum):
    PENDING = "PENDING"
    CLOSED = "CLOSED"
    DELETED = "DELETED"

class TransactionType(str, enum.Enum):
    CARD = "CARD"
    UNC = "UNC"
    OTA = "OTA"
    COMPANY_ACCOUNT = "COMPANY_ACCOUNT"
    BRANCH_ACCOUNT = "BRANCH_ACCOUNT"
    CASH_EXPENSE = "CASH_EXPENSE"
    OTHER = "OTHER"


class ShiftPaymentMethod(str, enum.Enum):
    """Phương thức thanh toán của PMS khi checkout."""
    CASH = "CASH"             # Tiền mặt (mặc định)
    CARD = "CARD"             # Thẻ
    BANK_TRANSFER = "BANK_TRANSFER"  # Chuyển khoản chi nhánh → BRANCH_ACCOUNT
    UNC = "UNC"               # Công ty → UNC
    OTA = "OTA"               # Kênh OTA
    DEBT = "DEBT"             # Còn nợ

# Enum cho Kho (WMS)
class TicketStatus(str, enum.Enum):
    DRAFT = "DRAFT"           # Nháp
    PENDING = "PENDING"       # Chờ duyệt
    APPROVED = "APPROVED"     # Đã duyệt
    SHIPPING = "SHIPPING"     # Đang giao
    COMPLETED = "COMPLETED"   # Hoàn thành
    REJECTED = "REJECTED"     # Từ chối
    CANCELLED = "CANCELLED"   # Hủy

class TransactionTypeWMS(str, enum.Enum):
    IMPORT_PO = "IMPORT_PO"         # Nhập hàng từ NCC
    EXPORT_TRANSFER = "EXPORT_TRANSFER" # Xuất kho (chuyển đi chi nhánh)
    IMPORT_TRANSFER = "IMPORT_TRANSFER" # Nhập kho (nhận từ kho tổng)
    EXPORT_SERVICE = "EXPORT_SERVICE"   # Xuất kho cho dịch vụ PMS (minibar, phòng)
    VOID_SERVICE = "VOID_SERVICE"       # Hoàn kho khi void dịch vụ PMS
    ADJUSTMENT = "ADJUSTMENT"       # Kiểm kê/Cân chỉnh

# ====================================================================
# 2. MASTER DATA (Dữ liệu nền)
# ====================================================================

class Branch(Base):
    """Chi nhánh"""
    __tablename__ = "branches"

    id = Column(Integer, primary_key=True)
    branch_code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    address = Column(Text)
    phone = Column(String(50), nullable=True)
    gps_lat = Column(NUMERIC(12, 9))
    gps_lng = Column(NUMERIC(12, 9))

    # Company info
    company_name = Column(String(255), nullable=True)
    tax_code = Column(String(50), nullable=True)
    tax_address = Column(Text, nullable=True)

    # Company bank info
    bank_name = Column(String(255), nullable=True)
    bank_account = Column(String(100), nullable=True)
    bank_holder = Column(String(255), nullable=True)

    # Personal bank info
    personal_bank_name = Column(String(255), nullable=True)
    personal_bank_account = Column(String(100), nullable=True)
    personal_bank_holder = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Department(Base):
    """Phòng ban / Vai trò"""
    __tablename__ = "departments"
    
    id = Column(Integer, primary_key=True)
    role_code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)

# ====================================================================
# 3. CORE USER MODEL
# ====================================================================

class User(Base):
    __tablename__ = "users"
    
    id = Column(BIGINT, primary_key=True)
    employee_id = Column(String(50), unique=True, nullable=False, index=True) # NV001
    employee_code = Column(String(50), unique=True, nullable=False, index=True) # lt.nhuptq
    name = Column(String(100), nullable=False)
    password = Column(String(255), nullable=True)
    
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"))
    main_branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"))
    
    shift = Column(String(10), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    phone_number = Column(String(20))
    email = Column(String(255))
    last_active_branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)

    # Thông tin cá nhân bổ sung
    cccd = Column(String(20), nullable=True)           # Số CCCD/CMND
    date_of_birth = Column(Date, nullable=True)        # Ngày sinh
    address = Column(Text, nullable=True)              # Địa chỉ
    gender = Column(String(10), nullable=True)         # Giới tính: Nam / Nữ / Khác

    # --- Relationships ---
    department = relationship("Department")
    main_branch = relationship("Branch", foreign_keys=[main_branch_id])
    last_active_branch = relationship("Branch", foreign_keys=[last_active_branch_id])
    
    # 1. Attendance
    attendance_logs = relationship("AttendanceLog", back_populates="user", cascade="all, delete-orphan")
    
    attendance_records_as_subject = relationship(
        "AttendanceRecord", 
        foreign_keys="AttendanceRecord.user_id",
        back_populates="user", 
        cascade="all, delete-orphan"
    )
    attendance_records_as_checker = relationship(
        "AttendanceRecord", 
        foreign_keys="AttendanceRecord.checker_id",
        back_populates="checker"
    )

    # 2. Service Records
    service_records_as_subject = relationship(
        "ServiceRecord",
        foreign_keys="ServiceRecord.user_id",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    service_records_as_checker = relationship(
        "ServiceRecord",
        foreign_keys="ServiceRecord.checker_id",
        back_populates="checker"
    )
    
    # 3. Tasks
    created_tasks = relationship("Task", foreign_keys="Task.author_id", back_populates="author")
    assigned_tasks = relationship("Task", foreign_keys="Task.assignee_id", back_populates="assignee")
    deleted_tasks = relationship("Task", foreign_keys="Task.deleter_id", back_populates="deleter")

    # 4. Lost & Found
    reported_lost_items = relationship("LostAndFoundItem", foreign_keys="LostAndFoundItem.reporter_id", back_populates="reporter")
    recorded_lost_items = relationship("LostAndFoundItem", foreign_keys="LostAndFoundItem.recorder_id", back_populates="recorder")
    disposed_lost_items = relationship("LostAndFoundItem", foreign_keys="LostAndFoundItem.disposer_id", back_populates="disposer")
    deleted_lost_items = relationship("LostAndFoundItem", foreign_keys="LostAndFoundItem.deleter_id", back_populates="deleter")

    # 5. Shift Transactions
    recorded_shift_transactions = relationship("ShiftReportTransaction", foreign_keys="ShiftReportTransaction.recorder_id", back_populates="recorder")
    closed_shift_transactions = relationship("ShiftReportTransaction", foreign_keys="ShiftReportTransaction.closer_id", back_populates="closer")
    deleted_shift_transactions = relationship("ShiftReportTransaction", foreign_keys="ShiftReportTransaction.deleter_id", back_populates="deleter")

    # 6. Shift Close Logs
    shift_close_logs = relationship("ShiftCloseLog", back_populates="closer")


# ====================================================================
# 4. OPERATIONAL MODELS (Nghiệp vụ hàng ngày)
# ====================================================================

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(BIGINT, primary_key=True)
    id_task = Column(String, unique=True, index=True, nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="CASCADE"), index=True)
    author_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    assignee_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    deleter_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    
    room_number = Column(String(50))
    description = Column(Text, nullable=False)
    department = Column(String(100))
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default='Đang chờ', index=True)

    due_date = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at = Column(DateTime(timezone=True))
    notes = Column(Text)

    branch = relationship("Branch")
    department_obj = relationship("Department")
    author = relationship("User", foreign_keys=[author_id], back_populates="created_tasks")
    assignee = relationship("User", foreign_keys=[assignee_id], back_populates="assigned_tasks")
    deleter = relationship("User", foreign_keys=[deleter_id], back_populates="deleted_tasks")

    __table_args__ = (
        Index("ix_tasks_deleted", "deleted_at",
              postgresql_where=(deleted_at != None)),
    )

class AttendanceLog(Base):
    """Log thô (lúc quẹt thẻ/check-in)."""
    __tablename__ = "attendance_log"
    
    id = Column(BIGINT, primary_key=True)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    work_date = Column(Date, nullable=False, index=True)
    shift = Column(String(10))
    token = Column(String(255), unique=True)
    checked_in = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="attendance_logs")

class ShiftNotification(Base):
    """Thông báo bắt buộc đọc khi nhân viên vào ca."""
    __tablename__ = "shift_notifications"

    id = Column(BIGINT, primary_key=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    priority = Column(String(20), nullable=False, default="normal")
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    starts_at = Column(DateTime(timezone=True), nullable=True, index=True)
    ends_at = Column(DateTime(timezone=True), nullable=True, index=True)
    schedule_shift = Column(String(10), nullable=True, index=True)
    min_read_seconds = Column(Integer, nullable=False, default=5)
    audience_roles = Column(JSONB, nullable=False, server_default="[]")
    branch_ids = Column(JSONB, nullable=False, server_default="[]")
    created_by_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    updated_by_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    created_by = relationship("User", foreign_keys=[created_by_id])
    updated_by = relationship("User", foreign_keys=[updated_by_id])

class ShiftNotificationRead(Base):
    """Dấu vết người dùng đã đọc thông báo trong một ngày/ca làm việc."""
    __tablename__ = "shift_notification_reads"

    id = Column(BIGINT, primary_key=True)
    notification_id = Column(BIGINT, ForeignKey("shift_notifications.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    attendance_log_id = Column(BIGINT, ForeignKey("attendance_log.id", ondelete="SET NULL"), nullable=True, index=True)
    work_date = Column(Date, nullable=False, index=True)
    shift = Column(String(10), nullable=False, index=True)
    read_at = Column(DateTime(timezone=True), server_default=func.now())

    notification = relationship("ShiftNotification")
    user = relationship("User")
    attendance_log = relationship("AttendanceLog")

    __table_args__ = (
        UniqueConstraint("notification_id", "user_id", "work_date", "shift", name="uq_shift_notification_read_once"),
    )

class AttendanceRecord(Base):
    """Bảng công chính thức."""
    __tablename__ = "attendance_records"
    
    id = Column(BIGINT, primary_key=True)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    checker_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    
    employee_code_snapshot = Column(String(50))
    employee_name_snapshot = Column(String(100))
    role_snapshot = Column(String(50))
    main_branch_snapshot = Column(String(50))
    
    attendance_datetime = Column(DateTime(timezone=True), nullable=False, index=True)
    work_units = Column(Float, default=1.0)
    is_overtime = Column(Boolean, default=False)
    notes = Column(Text)

    user = relationship("User", back_populates="attendance_records_as_subject", foreign_keys=[user_id])
    checker = relationship("User", back_populates="attendance_records_as_checker", foreign_keys=[checker_id])
    branch = relationship("Branch")

class ServiceRecord(Base):
    __tablename__ = "service_records"
    
    id = Column(BIGINT, primary_key=True)
    user_id = Column(BIGINT, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    checker_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    
    employee_code_snapshot = Column(String(50))
    employee_name_snapshot = Column(String(100))
    role_snapshot = Column(String(50))
    main_branch_snapshot = Column(String(50))
    
    service_datetime = Column(DateTime(timezone=True), nullable=False, index=True)
    service_type = Column(String(100))
    room_number = Column(String(50))
    quantity = Column(Integer)
    is_overtime = Column(Boolean, default=False)
    notes = Column(Text)
    
    user = relationship("User", back_populates="service_records_as_subject", foreign_keys=[user_id])
    checker = relationship("User", back_populates="service_records_as_checker", foreign_keys=[checker_id])
    branch = relationship("Branch")

# ====================================================================
# 5. LOST & FOUND (Đồ thất lạc)
# ====================================================================

class LostAndFoundItem(Base):
    __tablename__ = "lost_and_found_items"
    
    id = Column(BIGINT, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    reporter_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    recorder_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=False, index=True)
    
    item_name = Column(String(255), nullable=False)
    description = Column(Text)
    found_location = Column(String(255))
    found_datetime = Column(DateTime(timezone=True), nullable=False)
    status = Column(SQLAlchemyEnum(LostItemStatus, name="lostitemstatus", native_enum=True), default=LostItemStatus.STORED, index=True)
    
    owner_name = Column(String(100))
    owner_contact = Column(String(100))
    return_datetime = Column(DateTime(timezone=True))
    receiver_name = Column(String, nullable=True)
    receiver_contact = Column(String, nullable=True)
    update_notes = Column(Text, nullable=True)
    
    disposer_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"))
    disposed_amount = Column(NUMERIC(12, 2))
    
    deleter_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"))
    deleted_datetime = Column(DateTime(timezone=True))
    notes = Column(Text)
    
    fts_vector = Column(TSVECTOR)

    branch = relationship("Branch")
    reporter = relationship("User", foreign_keys=[reporter_id], back_populates="reported_lost_items")
    recorder = relationship("User", foreign_keys=[recorder_id], back_populates="recorded_lost_items")
    disposer = relationship("User", foreign_keys=[disposer_id], back_populates="disposed_lost_items")
    deleter = relationship("User", foreign_keys=[deleter_id], back_populates="deleted_lost_items")

    __table_args__ = (
        Index("ix_lost_items_fts", "fts_vector", postgresql_using="gin"),
    )

# ====================================================================
# 6. SHIFT REPORT (Giao ca)
# ====================================================================

class ShiftReportTransaction(Base):
    __tablename__ = "shift_report_transactions"
    
    id = Column(BIGINT, primary_key=True)
    transaction_code = Column(String(50), unique=True, nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    recorder_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=False, index=True)
    
    transaction_type = Column(SQLAlchemyEnum(TransactionType, name="transactiontype", native_enum=True), nullable=False, index=True)
    amount = Column(NUMERIC(15, 2), nullable=False, index=True)  # Tiền VND, có decimal
    room_number = Column(String(50), nullable=True, index=True)
    transaction_info = Column(String(255), nullable=True)
    status = Column(SQLAlchemyEnum(ShiftReportStatus, name="shiftreportstatus", native_enum=True), default=ShiftReportStatus.PENDING, index=True)

    # ── PMS Integration ──────────────────────────────────────────────
    stay_id = Column(BIGINT, ForeignKey("hotel_stays.id", ondelete="SET NULL"), nullable=True, index=True)   # Liên kết stay checkout
    folio_id = Column(BIGINT, ForeignKey("folios.id", ondelete="SET NULL"), nullable=True, index=True)      # Liên kết folio
    folio_transaction_id = Column(BIGINT, ForeignKey("folio_transactions.id", ondelete="SET NULL"), nullable=True, index=True)  # Liên kết transaction gốc trong Folio
    payment_method = Column(SQLAlchemyEnum(ShiftPaymentMethod, name="shiftpaymentmethod", native_enum=True), nullable=True)  # Phương thức TT
    is_auto_posted = Column(Boolean, default=False, nullable=False)  # True = tự động tạo từ PMS checkout
    # ────────────────────────────────────────────────────────────────

    created_datetime = Column(DateTime(timezone=True), nullable=False, index=True)
    
    closer_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    closed_datetime = Column(DateTime(timezone=True))
    
    deleter_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    deleted_datetime = Column(DateTime(timezone=True))

    fts_vector = Column(TSVECTOR)

    branch = relationship("Branch")
    recorder = relationship("User", foreign_keys=[recorder_id], back_populates="recorded_shift_transactions")
    closer = relationship("User", foreign_keys=[closer_id], back_populates="closed_shift_transactions")
    deleter = relationship("User", foreign_keys=[deleter_id], back_populates="deleted_shift_transactions")
    stay = relationship("HotelStay")
    folio = relationship("Folio")
    folio_transaction = relationship("FolioTransaction", foreign_keys=[folio_transaction_id])

    __table_args__ = (
        Index("ix_shift_trans_fts", "fts_vector", postgresql_using="gin"),
    )

class ShiftCloseLog(Base):
    __tablename__ = 'shift_close_logs'

    id = Column(Integer, primary_key=True, index=True)
    
    branch_id = Column(Integer, ForeignKey('branches.id'), nullable=False)
    branch = relationship("Branch")

    closer_id = Column(BIGINT, ForeignKey('users.id'), nullable=False)
    closer = relationship("User", back_populates="shift_close_logs")

    closed_datetime = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    pms_revenue = Column(NUMERIC(15, 2), nullable=False, default=0)
    closed_online_revenue = Column(NUMERIC(15, 2), nullable=False, default=0)
    closed_branch_revenue = Column(NUMERIC(15, 2), nullable=False, default=0)
    
    closed_transaction_ids = Column(JSONB, nullable=True)

# ====================================================================
# 7. WMS (QUẢN LÝ KHO) - MỚI
# ====================================================================

# 7.1 Master Data (Sản phẩm, Danh mục, Kho)
class ProductCategory(Base):
    """Danh mục sản phẩm"""
    __tablename__ = "product_categories"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    code = Column(String(50), unique=True, index=True)

class Product(Base):
    """Sản phẩm (có logic quy đổi đơn vị)"""
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("product_categories.id"))
    
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    
    base_unit = Column(String(20), nullable=False) # Đơn vị cơ sở (Chai)
    packing_unit = Column(String(20))              # Đơn vị đóng gói (Thùng)
    conversion_rate = Column(Integer, default=1)   # Tỷ lệ: 1 Thùng = n Chai
    
    cost_price = Column(NUMERIC(15, 2), default=0)
    sell_price = Column(NUMERIC(15, 2), default=0)       # Giá bán lẻ cho khách (minibar, dịch vụ)
    min_stock_global = Column(Integer, default=0)
    
    is_active = Column(Boolean, default=True)
    is_sellable = Column(Boolean, default=False)          # Có thể bán cho khách qua PMS
    service_code = Column(String(50), nullable=True, index=True)  # Map với service type trong PMS
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    category = relationship("ProductCategory")

class Warehouse(Base):
    """Kho hàng (Gắn với chi nhánh hoặc Kho tổng)"""
    __tablename__ = "warehouses"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    type = Column(String(20), default="BRANCH") # 'MAIN' hoặc 'BRANCH'
    
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    
    branch = relationship("Branch")

class Supplier(Base):
    """Nhà cung cấp"""
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, index=True)
    name = Column(String(255), nullable=False)
    phone = Column(String(20))
    email = Column(String(255))
    address = Column(Text)
    tax_code = Column(String(20))
    contact_person = Column(String(100))
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# 7.2 Core Inventory (Tồn kho & Lịch sử)
class InventoryLevel(Base):
    """Tồn kho hiện tại (Snapshot)"""
    __tablename__ = "inventory_levels"

    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), primary_key=True)

    quantity = Column(NUMERIC(12, 2), default=0, nullable=False) # Luôn lưu theo Base Unit
    min_stock = Column(Integer, default=10)

    product = relationship("Product")
    warehouse = relationship("Warehouse")

    # Index cho query theo product_id (ngoài PK)
    __table_args__ = (
        Index("ix_inventory_product", "product_id"),
        CheckConstraint("quantity >= 0", name="check_inventory_non_negative"),
    )

    @property
    def display_quantity(self):
        if not self.product.packing_unit or self.product.conversion_rate <= 1:
            return f"{int(self.quantity)} {self.product.base_unit}"
        cartons = int(self.quantity // self.product.conversion_rate)
        units = int(self.quantity % self.product.conversion_rate)
        return f"{cartons} {self.product.packing_unit}, {units} {self.product.base_unit}"

class StockMovement(Base):
    """Lịch sử giao dịch kho (Ledger)"""
    __tablename__ = "stock_movements"
    
    id = Column(BIGINT, primary_key=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    
    transaction_type = Column(SQLAlchemyEnum(TransactionTypeWMS, native_enum=True), nullable=False)
    
    quantity_change = Column(NUMERIC(12, 2), nullable=False)
    balance_after = Column(NUMERIC(12, 2), nullable=False)
    
    ref_ticket_id = Column(BIGINT, index=True)
    ref_ticket_type = Column(String(50))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    actor_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), index=True)

    product = relationship("Product")
    warehouse = relationship("Warehouse")
    actor = relationship("User")

    # Composite index cho reference lookup
    __table_args__ = (
        Index("ix_stock_ref", "ref_ticket_type", "ref_ticket_id"),
    )

# 7.3 Flows (Nhập hàng & Điều chuyển)

# A. Nhập hàng từ NCC
class InventoryReceipt(Base):
    __tablename__ = "inventory_receipts"

    id = Column(BIGINT, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True)
    supplier_name = Column(String(255))

    creator_id = Column(BIGINT, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    total_amount = Column(NUMERIC(15, 2), default=0)
    notes = Column(Text)
    version = Column(Integer, default=1, nullable=False)  # Optimistic locking

    items = relationship("InventoryReceiptItem", back_populates="receipt", cascade="all, delete-orphan")
    images = relationship("ImportImage", back_populates="receipt", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[creator_id])
    supplier = relationship("Supplier", foreign_keys=[supplier_id])

    __table_args__ = (
        Index("ix_inventory_receipts_version", "version"),
    )

class InventoryReceiptItem(Base):
    __tablename__ = "inventory_receipt_items"
    
    id = Column(BIGINT, primary_key=True)
    receipt_id = Column(BIGINT, ForeignKey("inventory_receipts.id", ondelete="CASCADE"))
    product_id = Column(Integer, ForeignKey("products.id"))
    
    input_quantity = Column(NUMERIC(10, 2), nullable=False)
    input_unit = Column(String(20))
    
    converted_quantity = Column(NUMERIC(10, 2), nullable=False) 
    
    unit_price = Column(NUMERIC(15, 2))
    total_price = Column(NUMERIC(15, 2))

    receipt = relationship("InventoryReceipt", back_populates="items")
    product = relationship("Product")

# B. Điều chuyển / Yêu cầu hàng
class InventoryTransfer(Base):
    __tablename__ = "inventory_transfers"
    
    id = Column(BIGINT, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    
    source_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), index=True)
    dest_warehouse_id = Column(Integer, ForeignKey("warehouses.id"), index=True)
    
    requester_id = Column(BIGINT, ForeignKey("users.id"), index=True)
    approver_id = Column(BIGINT, ForeignKey("users.id"), index=True)
    
    # [NEW] Link to parent ticket (for compensation tickets)
    related_transfer_id = Column(BIGINT, ForeignKey("inventory_transfers.id"), nullable=True, index=True)

    status = Column(SQLAlchemyEnum(TicketStatus, native_enum=True), default=TicketStatus.PENDING, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    approved_at = Column(DateTime(timezone=True))

    notes = Column(Text)
    approver_notes = Column(Text)
    version = Column(Integer, default=1, nullable=False)  # Optimistic locking

    items = relationship("InventoryTransferItem", back_populates="transfer", cascade="all, delete-orphan")
    images = relationship("TransferImage", back_populates="transfer", cascade="all, delete-orphan")
    requester = relationship("User", foreign_keys=[requester_id])
    approver_user = relationship("User", foreign_keys=[approver_id])
    source_warehouse = relationship("Warehouse", foreign_keys=[source_warehouse_id])
    dest_warehouse = relationship("Warehouse", foreign_keys=[dest_warehouse_id])

    # Relationship for accessing the parent ticket or children compensation tickets
    related_transfer = relationship("InventoryTransfer", remote_side=[id], backref="compensation_transfers")

    __table_args__ = (
        Index("ix_inventory_transfers_version", "version"),
    )

class InventoryTransferItem(Base):
    __tablename__ = "inventory_transfer_items"
    
    id = Column(BIGINT, primary_key=True)
    transfer_id = Column(BIGINT, ForeignKey("inventory_transfers.id", ondelete="CASCADE"), index=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True)
    
    request_quantity = Column(NUMERIC(10, 2), nullable=False)
    request_unit = Column(String(20)) 
    
    approved_quantity = Column(NUMERIC(10, 2), nullable=True) 
    
    # [NEW] Fields for Reception Discrepancy
    received_quantity = Column(NUMERIC(10, 2), nullable=True)
    loss_quantity = Column(NUMERIC(10, 2), nullable=True)
    loss_reason = Column(String(255), nullable=True) 
    
    transfer = relationship("InventoryTransfer", back_populates="items")
    product = relationship("Product")

# 7.3b Stocktake (Kiểm kê)
class StocktakeStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class Stocktake(Base):
    """Phiếu kiểm kê kho"""
    __tablename__ = "stocktakes"

    id = Column(BIGINT, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False, index=True)
    status = Column(SQLAlchemyEnum(StocktakeStatus, native_enum=True), default=StocktakeStatus.DRAFT, index=True)
    creator_id = Column(BIGINT, ForeignKey("users.id"), index=True)
    completed_at = Column(DateTime(timezone=True))
    completed_by = Column(BIGINT, ForeignKey("users.id"))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    items = relationship("StocktakeItem", back_populates="stocktake", cascade="all, delete-orphan")
    warehouse = relationship("Warehouse")
    creator = relationship("User", foreign_keys=[creator_id])
    completer = relationship("User", foreign_keys=[completed_by])

class StocktakeItem(Base):
    """Dòng kiểm kê từng sản phẩm"""
    __tablename__ = "stocktake_items"

    id = Column(BIGINT, primary_key=True)
    stocktake_id = Column(BIGINT, ForeignKey("stocktakes.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    system_quantity = Column(NUMERIC(12, 2), nullable=False)
    actual_quantity = Column(NUMERIC(12, 2), nullable=True)
    difference = Column(NUMERIC(12, 2), nullable=True)
    notes = Column(Text)

    stocktake = relationship("Stocktake", back_populates="items")
    product = relationship("Product")

# 7.4 Import Images (Hình ảnh đính kèm phiếu nhập)
class ImportImage(Base):
    """Hình ảnh đính kèm cho phiếu nhập hàng"""
    __tablename__ = "import_images"
    
    id = Column(BIGINT, primary_key=True)
    receipt_id = Column(BIGINT, ForeignKey("inventory_receipts.id", ondelete="CASCADE"), nullable=False, index=True)
    
    file_path = Column(String(500), nullable=False)  # Path to full image
    thumbnail_path = Column(String(500))  # Path to thumbnail
    
    file_size = Column(Integer)  # Size in bytes
    width = Column(Integer)  # Image width
    height = Column(Integer)  # Image height
    
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    display_order = Column(Integer, default=0)  # For sorting images
    
    receipt = relationship("InventoryReceipt", back_populates="images")

# 7.5 Transfer Images (Hình ảnh đính kèm phiếu chuyển/nhận hàng)
class TransferImage(Base):
    """Hình ảnh đính kèm cho phiếu chuyển kho (Phiếu nhận hàng/Bằng chứng)"""
    __tablename__ = "transfer_images"
    
    id = Column(BIGINT, primary_key=True)
    transfer_id = Column(BIGINT, ForeignKey("inventory_transfers.id", ondelete="CASCADE"), nullable=False, index=True)
    
    file_path = Column(String(500), nullable=False)
    thumbnail_path = Column(String(500))
    
    file_size = Column(Integer)
    width = Column(Integer)
    height = Column(Integer)
    
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    display_order = Column(Integer, default=0)
    
    transfer = relationship("InventoryTransfer", back_populates="images")

# 7.6 Audit Trail (Lịch sử thao tác kho)
class InventoryAuditLog(Base):
    """Lịch sử thao tác trên hệ thống kho"""
    __tablename__ = "inventory_audit_logs"

    id = Column(BIGINT, primary_key=True)
    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(BIGINT, nullable=False, index=True)
    action = Column(String(50), nullable=False, index=True)
    actor_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    changes_json = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    actor = relationship("User")

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )

# ====================================================================
# 8. OTA BOOKING AGENT (AI AGENT)
# ====================================================================

class BookingStatus(str, enum.Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED" # Đã check-out (nếu cần)
    NO_SHOW = "NO_SHOW"

class OTAParsingStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

class Booking(Base):
    """Đặt phòng từ OTA (Booking.com, Agoda, Traveloka...)"""
    __tablename__ = "bookings"

    id = Column(BIGINT, primary_key=True)
    booking_source = Column(String(50), nullable=False, index=True) # Booking.com, Agoda
    external_id = Column(String(50), nullable=False, index=True) # Mã đặt phòng OTA

    guest_name = Column(String(255), nullable=False, index=True)
    check_in = Column(Date, nullable=False, index=True)
    check_out = Column(Date, nullable=False, index=True)
    room_type = Column(String(255))
    
    num_guests = Column(Integer, default=1)
    num_adults = Column(Integer, default=1)       # Số người lớn
    num_children = Column(Integer, default=0)     # Số trẻ em
    guest_phone = Column(String(50), nullable=True)  # SĐT khách
    checkin_code = Column(String(50), nullable=True) # Mã PIN check-in phòng
    total_price = Column(NUMERIC(15, 2), default=0)
    currency = Column(String(10), default='VND')
    
    # Payment info
    is_prepaid = Column(Boolean, default=False)
    payment_method = Column(String(100)) # Visa ..4242 / Cash
    deposit_amount = Column(NUMERIC(15, 2), default=0)

    status = Column(SQLAlchemyEnum(BookingStatus, native_enum=True), default=BookingStatus.CONFIRMED, index=True)
    
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True)
    # Bản sao chỉ đọc để lại tại chi nhánh cũ khi chuyển đơn sang chi nhánh khác (view only, không đồng bộ)
    source_booking_id = Column(BIGINT, ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True, index=True)
    guest_id = Column(BIGINT, ForeignKey("guests.id", ondelete="SET NULL"), index=True)
    
    raw_data = Column(JSONB) # Full JSON extracted from AI

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    version = Column(Integer, default=1, nullable=False)  # Optimistic locking

    # Reservation Hub fields
    booking_type = Column(String(20), default="OTA", nullable=False, index=True)
    reservation_status = Column(String(20), default="CONFIRMED", nullable=False)
    assigned_room_id = Column(Integer, ForeignKey("hotel_rooms.id", ondelete="SET NULL"), nullable=True, index=True)
    stay_id = Column(BIGINT, ForeignKey("hotel_stays.id", ondelete="SET NULL"), nullable=True, index=True)
    estimated_arrival = Column(Time, nullable=True)
    special_requests = Column(Text, nullable=True)
    internal_notes = Column(Text, nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancel_reason = Column(Text, nullable=True)
    no_show_at = Column(DateTime(timezone=True), nullable=True)

    # Composite indexes + constraints
    __table_args__ = (
        Index("ix_booking_guest_checkin", "guest_id", "check_in"),
        Index("ix_booking_dates", "check_in", "check_out"),
        Index("ix_booking_reservation_status", "reservation_status"),
        Index("ix_booking_branch_checkin_status", "branch_id", "check_in", "reservation_status"),
        Index("uq_booking_source_external", "booking_source", "external_id", unique=True,
              postgresql_where=(external_id != None)),
        Index("ix_bookings_version", "version"),
        CheckConstraint("check_out > check_in", name="check_booking_dates"),
    )

    branch = relationship("Branch")
    guest = relationship("Guest", back_populates="bookings")
    source_booking = relationship("Booking", remote_side="Booking.id", foreign_keys=[source_booking_id])
    assigned_room = relationship("HotelRoom", foreign_keys=[assigned_room_id])
    stay = relationship("HotelStay", foreign_keys=[stay_id])
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class RoomInventoryDaily(Base):
    """Tồn phòng theo ngày, theo chi nhánh và loại phòng."""
    __tablename__ = "room_inventory_daily"

    id = Column(BIGINT, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)
    room_type_id = Column(Integer, ForeignKey("hotel_room_types.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    total_rooms = Column(Integer, default=0, nullable=False)
    available_rooms = Column(Integer, default=0, nullable=False)
    reserved_rooms = Column(Integer, default=0, nullable=False)
    sold_rooms = Column(Integer, default=0, nullable=False)
    out_of_order_rooms = Column(Integer, default=0, nullable=False)
    overbooking_limit = Column(Integer, default=0, nullable=False)
    base_price = Column(NUMERIC(15, 2), default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    branch = relationship("Branch")
    room_type = relationship("HotelRoomType")

    __table_args__ = (
        Index("uq_room_inventory_branch_type_date", "branch_id", "room_type_id", "date", unique=True),
        Index("ix_room_inventory_branch_date", "branch_id", "date"),
    )


class RoomBlock(Base):
    """Khóa phòng do bảo trì hoặc out-of-order."""
    __tablename__ = "room_blocks"

    id = Column(BIGINT, primary_key=True)
    room_id = Column(Integer, ForeignKey("hotel_rooms.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=False, index=True)
    reason = Column(Text, nullable=True)
    status = Column(String(20), default="ACTIVE", nullable=False, index=True)
    created_by = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    room = relationship("HotelRoom")
    branch = relationship("Branch")
    creator = relationship("User", foreign_keys=[created_by])


class RoomInventoryHold(Base):
    """Giữ phòng tạm, chưa commit vào reserved_rooms."""
    __tablename__ = "room_inventory_holds"

    id = Column(BIGINT, primary_key=True)
    booking_id = Column(BIGINT, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)
    room_type_id = Column(Integer, ForeignKey("hotel_room_types.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    quantity = Column(Integer, default=1, nullable=False)
    hold_type = Column(String(20), default="MANUAL", nullable=False)
    expire_at = Column(DateTime(timezone=True), nullable=False, index=True)
    released = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    booking = relationship("Booking")
    branch = relationship("Branch")
    room_type = relationship("HotelRoomType")


class RoomInventoryLog(Base):
    """Audit trail cho mọi thay đổi inventory."""
    __tablename__ = "room_inventory_logs"

    id = Column(BIGINT, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)
    room_type_id = Column(Integer, ForeignKey("hotel_room_types.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    change_type = Column(String(30), nullable=False, index=True)
    delta = Column(Integer, nullable=False)
    field_changed = Column(String(20), nullable=False)
    ref_type = Column(String(20), nullable=True)
    ref_id = Column(BIGINT, nullable=True, index=True)
    note = Column(Text, nullable=True)
    created_by = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    branch = relationship("Branch")
    room_type = relationship("HotelRoomType")
    creator = relationship("User", foreign_keys=[created_by])

class OTAParsingLog(Base):
    """Log lịch sử đọc mail & parse của AI"""
    __tablename__ = "ota_parsing_logs"

    id = Column(BIGINT, primary_key=True)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    email_subject = Column(String(500))
    email_sender = Column(String(255))
    email_message_id = Column(String(255), unique=True, index=True, nullable=True)  # Unique email ID for deduplication

    status = Column(SQLAlchemyEnum(OTAParsingStatus, native_enum=True), index=True)
    error_message = Column(Text)
    error_traceback = Column(Text, nullable=True)  # Full stack trace for debugging

    raw_content = Column(Text)  # Nội dung email HTML
    extracted_data = Column(JSONB, nullable=True)  # Data extracted by AI

    retry_count = Column(Integer, default=0)  # Number of retry attempts
    last_retry_at = Column(DateTime(timezone=True), nullable=True)  # Last retry timestamp

    booking_id = Column(BIGINT, ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True, index=True)  # Link to created booking

    # Composite indexes cho query pattern /ota/status:
    #   filter status + ORDER BY received_at DESC LIMIT N
    #   join booking + lấy mới nhất theo booking_id
    __table_args__ = (
        Index("ix_ota_logs_status_received_desc", "status", received_at.desc()),
        Index(
            "ix_ota_logs_booking_received_desc",
            "booking_id", received_at.desc(),
            postgresql_where=booking_id.isnot(None),
        ),
    )

    # Relationship
    booking = relationship("Booking", foreign_keys=[booking_id])




class AppConfig(Base):
    """Lưu cấu hình key-value của ứng dụng (persist qua server restart)."""
    __tablename__ = "app_config"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ====================================================================
# 9. PMS - PROPERTY MANAGEMENT SYSTEM (Quản lý bán phòng)
# ====================================================================

# Cached Decimal defaults (dùng làm default= trong Column để tránh NameError)
_DECIMAL_50000 = Decimal("50000")
_DECIMAL_0     = Decimal("0")


class HotelRoomType(Base):
    """Loại phòng & bảng giá (Admin cấu hình)"""
    __tablename__ = "hotel_room_types"

    id              = Column(Integer, primary_key=True)
    branch_id       = Column(Integer, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)
    name            = Column(String(100), nullable=False)          # VD: "Standard", "VIP", "Suite"
    description     = Column(Text, nullable=True)
    price_per_night = Column(NUMERIC(15, 2), default=0, nullable=False)  # Giá qua đêm
    price_per_hour  = Column(NUMERIC(15, 2), default=0, nullable=False)  # Giá thuê giờ
    price_next_hour = Column(NUMERIC(15, 2), default=0, nullable=False)  # Giá mỗi giờ tiếp theo
    promo_start_time = Column(Time, nullable=True)                       # Giờ bắt đầu giá ưu đãi
    promo_end_time = Column(Time, nullable=True)                         # Giờ kết thúc giá ưu đãi
    promo_discount_amount = Column(NUMERIC(15, 2), default=0, nullable=False)  # Số tiền giảm giá ưu đãi ban đêm
    promo_discount_percent = Column(Float, default=0, nullable=False)    # Legacy: % giảm giá cũ, không dùng cho cấu hình mới
    min_hours       = Column(Integer, default=1)                   # Tối thiểu bao nhiêu giờ
    max_guests      = Column(Integer, default=2)
    is_active       = Column(Boolean, default=True)
    sort_order      = Column(Integer, default=0)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    # --- Khung giờ chuẩn (Standard Time Frame) ---
    standard_checkin_time  = Column(Time, nullable=True)                         # Mặc định 14:00
    standard_checkout_time = Column(Time, nullable=True)                         # Mặc định 12:00

    # --- Phụ thu early / late (VNĐ / giờ) ---
    early_checkin_fee_per_hour  = Column(NUMERIC(15, 2), default=_DECIMAL_50000)
    late_checkout_fee_per_hour  = Column(NUMERIC(15, 2), default=_DECIMAL_50000)

    # --- Hybrid pricing config ---
    grace_minutes       = Column(Integer, default=10)     # Dư > N phút → làm tròn +1h
    day_threshold_hours = Column(Integer, default=8)     # >= N giờ → tính ngày
    hourly_to_daily_threshold = Column(Integer, default=8)

    # --- Night short-stay config ---
    night_short_stay_enabled = Column(Boolean, default=False)
    night_short_stay_start = Column(Time, nullable=True)
    night_short_stay_end = Column(Time, nullable=True)
    night_short_stay_max_hours = Column(Integer, default=8)
    night_short_stay_price = Column(NUMERIC(15, 2), nullable=True)
    night_audit_hour = Column(Integer, nullable=True)

    branch = relationship("Branch")
    rooms  = relationship("HotelRoom", back_populates="room_type_obj")


class RoomCondition(str, enum.Enum):
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"
    CLEANING = "CLEANING"
    MAINTENANCE = "MAINTENANCE"


class HotelRoom(Base):
    """Phòng khách sạn (Admin cấu hình)"""
    __tablename__ = "hotel_rooms"

    id             = Column(Integer, primary_key=True)
    branch_id      = Column(Integer, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)
    room_type_id   = Column(Integer, ForeignKey("hotel_room_types.id", ondelete="SET NULL"), nullable=True)
    floor          = Column(Integer, nullable=False, index=True)    # Tầng
    room_number    = Column(String(20), nullable=False)             # Số phòng e.g. "101"
    notes          = Column(Text, nullable=True)
    condition      = Column(SQLAlchemyEnum(RoomCondition, name="roomcondition", native_enum=True), default=RoomCondition.CLEAN, nullable=False, index=True)
    is_active      = Column(Boolean, default=True)
    sort_order     = Column(Integer, default=0)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    housekeeping_status = Column(String(50), default="CLEAN")

    branch        = relationship("Branch")
    room_type_obj = relationship("HotelRoomType", back_populates="rooms")
    stays         = relationship("HotelStay", back_populates="room", order_by="HotelStay.check_in_at.desc()")

    __table_args__ = (
        Index("uq_hotel_room_branch_number", "branch_id", "room_number", unique=True),
        Index("ix_room_branch_floor", "branch_id", "floor"),
    )


class HotelStayStatus(str, enum.Enum):
    ACTIVE      = "ACTIVE"         # Đang lưu trú
    CHECKED_OUT = "CHECKED_OUT"    # Đã trả phòng
    CANCELLED   = "CANCELLED"      # Huỷ


class StayType(str, enum.Enum):
    NIGHT       = "NIGHT"        # Qua đêm (legacy)
    HOUR        = "HOUR"         # Theo giờ (legacy)
    DAY_USE     = "DAY_USE"      # Day use (legacy)
    WEEKLY      = "WEEKLY"       # Theo tuần (legacy)
    AUTO        = "AUTO"         # Mặc định — hệ thống tự tính (giờ → ngày)
    FORCE_HOURLY    = "FORCE_HOURLY"    # Luôn tính giờ (khách deal riêng / OTA)
    FORCE_DAILY     = "FORCE_DAILY"     # Luôn tính ngày (công ty ký hợp đồng)
    FORCE_OVERNIGHT = "FORCE_OVERNIGHT" # Qua đêm sớm (vào trước 00:00, spec v3)


class HotelStay(Base):
    """Lượt lưu trú (một lần check-in/check-out)"""
    __tablename__ = "hotel_stays"

    id           = Column(BIGINT, primary_key=True)
    room_id      = Column(Integer, ForeignKey("hotel_rooms.id", ondelete="RESTRICT"), nullable=False, index=True)
    branch_id    = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    stay_type    = Column(SQLAlchemyEnum(StayType, name="staytype", native_enum=True), default=StayType.NIGHT, nullable=False)
    pricing_mode_final   = Column(String(20), nullable=True)  # HOURLY_CHARGE | ROOM_CHARGE | FORCE_DAILY — settled at checkout only
    pricing_mode_initial = Column(String(20), nullable=True)  # HOURLY | NIGHT | AUTO — locked at check-in
    pricing_locked       = Column(Boolean, default=False)      # TRUE = pricing locked at check-in
    check_in_at          = Column(DateTime(timezone=True), nullable=False, index=True)
    original_check_in_at = Column(DateTime(timezone=True), nullable=True)  # Mốc check-in gốc, không đổi khi chuyển phòng
    billing_start_at     = Column(DateTime(timezone=True), nullable=True)   # Mốc tính giá hiện tại, reset sau mỗi lần chuyển phòng
    check_out_at = Column(DateTime(timezone=True), nullable=True)       # Null khi đang ở
    status       = Column(
        SQLAlchemyEnum(HotelStayStatus, name="hotelstaystatus", native_enum=True),
        default=HotelStayStatus.ACTIVE, nullable=False, index=True
    )
    total_price  = Column(NUMERIC(15, 2), default=0)
    deposit      = Column(NUMERIC(15, 2), default=0)
    deposit_type = Column(String(50), nullable=True) # Chi nhánh, Công ty, OTA, UNC, Quẹt thẻ
    deposit_meta = Column(JSONB, nullable=True)     # Lưu beneficiary, oa channel, invoice code...
    discount     = Column(NUMERIC(15, 2), default=0)
    extra_charge = Column(NUMERIC(15, 2), default=0)
    notes        = Column(Text, nullable=True)

    # Vehicle info - gắn với lượt lưu trú, không phải khách
    vehicle      = Column(String(100), nullable=True)  # Biển số xe (Đà Nẵng: 43A-123.45)

    # Invoicing info
    require_invoice = Column(Boolean, default=False)
    tax_code        = Column(String(50), nullable=True)
    tax_contact     = Column(String(255), nullable=True)
    company_name    = Column(String(255), nullable=True)
    company_address = Column(Text, nullable=True)

    created_by   = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at   = Column(DateTime(timezone=True), nullable=True)  # Soft delete
    version      = Column(Integer, default=1, nullable=False)  # Optimistic locking

    # Composite indexes for common queries
    __table_args__ = (
        Index("ix_stay_room_status", "room_id", "status"),
        Index("ix_stay_branch_status", "branch_id", "status"),
        Index("ix_hotel_stays_version", "version"),
        # Partial indexes — chỉ stays ACTIVE. Dùng cho:
        #   /api/pms/rooms Q2 (fetch active stays theo room_ids)
        #   _get_occupied_rooms_for_dates (range query)
        Index(
            "ix_stay_active_branch_room",
            "branch_id", "room_id",
            postgresql_where=status == HotelStayStatus.ACTIVE,
        ),
        Index(
            "ix_stay_active_branch_dates",
            "branch_id", "check_in_at", "check_out_at",
            postgresql_where=status == HotelStayStatus.ACTIVE,
        ),
    )

    room       = relationship("HotelRoom", back_populates="stays")
    branch     = relationship("Branch")
    creator    = relationship("User", foreign_keys=[created_by])
    guests     = relationship("HotelGuest", back_populates="stay", cascade="all, delete-orphan",
                              order_by="HotelGuest.is_primary.desc()")

    # Folio (financial ledger)
    folios = relationship("Folio", back_populates="stay", cascade="all, delete-orphan")


# ====================================================================
# 9b. FOLIO / BILLING (Tài chính lượt lưu trú)
# ====================================================================

class FolioStatus(str, enum.Enum):
    OPEN   = "OPEN"    # Đang mở — chưa thanh toán xong
    DEBT   = "DEBT"    # Checkout rồi nhưng còn nợ (AR)
    CLOSED = "CLOSED"  # Đã đóng — balance = 0, không thêm dòng mới


class Folio(Base):
    """Sổ tài chính cho 1 lượt lưu trú. Tách biệt hoàn toàn khỏi HotelStay."""
    __tablename__ = "folios"

    id           = Column(BIGINT, primary_key=True)
    stay_id      = Column(BIGINT, ForeignKey("hotel_stays.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id    = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)

    folio_code   = Column(String(50), unique=True, nullable=False, index=True)  # FOL-YYMMDD-XXXX
    status       = Column(
        SQLAlchemyEnum(FolioStatus, name="folio_status", native_enum=True),
        default=FolioStatus.OPEN, nullable=False, index=True
    )

    # Cache balance — tính lại từ SUM(folio_transactions.amount) mỗi khi có dòng mới
    total_charge   = Column(NUMERIC(15, 2), default=0, nullable=False)   # SUM(amount > 0, loại trừ REFUND)
    total_discount = Column(NUMERIC(15, 2), default=0, nullable=False)   # SUM(abs(discount transactions))
    total_paid     = Column(NUMERIC(15, 2), default=0, nullable=False)   # SUM(abs(payment transactions))
    balance        = Column(NUMERIC(15, 2), default=0, nullable=False)   # (total_charge - total_discount) - total_paid

    currency     = Column(String(10), default="VND")
    notes        = Column(Text)
    invoice_name = Column(String(255), nullable=True)
    invoice_tax_code = Column(String(50), nullable=True)
    invoice_contact = Column(String(255), nullable=True)
    invoice_address = Column(Text, nullable=True)

    opened_at    = Column(DateTime(timezone=True), server_default=func.now())
    closed_at    = Column(DateTime(timezone=True), nullable=True)

    created_by   = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # ── Debt tracking ──────────────────────────────────────────────────────────
    debt_amount  = Column(NUMERIC(15, 2), default=Decimal("0"), nullable=False)
    debt_status  = Column(String(20), default="none")  # none | pending | partial | settled
    debt_note    = Column(Text, nullable=True)
    debt_settled_by = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    debt_settled_at = Column(DateTime(timezone=True), nullable=True)

    # ── Refund tracking ─────────────────────────────────────────────────────────
    refund_amount = Column(NUMERIC(15, 2), default=Decimal("0"), nullable=False)
    refund_status = Column(String(20), default="none")  # none | pending | approved | refunded | cancelled
    refund_note   = Column(Text, nullable=True)
    refund_by     = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    refund_at     = Column(DateTime(timezone=True), nullable=True)

    # ── Relationships ────────────────────────────────────────────────────────────
    debt_settler = relationship("User", foreign_keys=[debt_settled_by])
    refund_actor = relationship("User", foreign_keys=[refund_by])
    debt_records = relationship("DebtRecord", back_populates="folio", cascade="all, delete-orphan")
    refund_records = relationship("RefundRecord", back_populates="folio", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_folio_branch_status", "branch_id", "status"),
        Index("ix_folio_opened", "opened_at"),
    )

    stay      = relationship("HotelStay", back_populates="folios")
    branch    = relationship("Branch")
    creator   = relationship("User", foreign_keys=[created_by])
    transactions = relationship("FolioTransaction", back_populates="folio",
                               cascade="all, delete-orphan",
                               order_by="FolioTransaction.created_at")
    payments  = relationship("Payment", back_populates="folio",
                             cascade="all, delete-orphan",
                             order_by="Payment.paid_at.desc()")

    def recalculate_balance(self) -> None:
        """Tính lại balance từ tất cả transactions."""
        charges = sum(t.amount for t in self.transactions if t.amount > 0)
        payments = sum(abs(t.amount) for t in self.transactions if t.amount < 0)
        self.total_charge = charges
        self.total_paid   = payments
        self.balance      = charges - payments

class FolioTransactionType(str, enum.Enum):
    # Charge (+)
    ROOM_CHARGE       = "ROOM_CHARGE"        # Tiền phòng
    HOURLY_CHARGE     = "HOURLY_CHARGE"      # Tiền phòng theo giờ
    SERVICE_CHARGE     = "SERVICE_CHARGE"      # Dịch vụ chung (minibar, laundry...)
    MINIBAR_CHARGE    = "MINIBAR_CHARGE"      # Mini bar
    SURCHARGE         = "SURCHARGE"           # Phụ thu (quá giờ, vượt người, late checkout...)
    LATE_CHECKOUT_FEE = "LATE_CHECKOUT_FEE"   # Phí trả phòng muộn
    EARLY_CHECKIN_FEE = "EARLY_CHECKIN_FEE"  # Phí nhận phòng sớm
    EXTRA_GUEST_FEE   = "EXTRA_GUEST_FEE"     # Phí vượt số người
    # Discount (-)
    DISCOUNT_MANUAL   = "DISCOUNT_MANUAL"     # Giảm giá tay
    PROMOTION         = "PROMOTION"            # Khuyến mãi
    OTA_COMMISSION    = "OTA_COMMISSION"      # Phí OTA
    # Payment (-)
    PAYMENT           = "PAYMENT"              # Thanh toán
    DEPOSIT_USED      = "DEPOSIT_USED"        # Cọc được sử dụng
    # Refund (+)
    REFUND            = "REFUND"               # Hoàn tiền
    DEBT_PAYMENT      = "DEBT_PAYMENT"         # Thanh toán công nợ
    REFUND_PAYMENT    = "REFUND_PAYMENT"        # Thanh toán hoàn tiền


class FolioTransactionCategory(str, enum.Enum):
    ROOM     = "ROOM"     # Tiền phòng
    SERVICE  = "SERVICE"  # Dịch vụ bán thêm (minibar, laundry)
    SURCHARGE= "SURCHARGE"# Phụ thu / Phí phát sinh (quá giờ, vượt người)
    PAYMENT  = "PAYMENT"  # Thanh toán
    DISCOUNT = "DISCOUNT" # Giảm giá
    REFUND   = "REFUND"   # Hoàn tiền
    OTHER    = "OTHER"    # Khác


class FolioTransaction(Base):
    """
    Một dòng tiền trong folio.
    ⚠️  KHÔNG update — chỉ INSERT. Muốn void → thêm dòng ngược (+/-).
    """
    __tablename__ = "folio_transactions"

    id               = Column(BIGINT, primary_key=True)
    folio_id         = Column(BIGINT, ForeignKey("folios.id", ondelete="CASCADE"), nullable=False, index=True)
    stay_id          = Column(BIGINT, ForeignKey("hotel_stays.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id        = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)

    transaction_type  = Column(
        SQLAlchemyEnum(FolioTransactionType, name="folio_tx_type", native_enum=True),
        nullable=False, index=True
    )
    category          = Column(
        SQLAlchemyEnum(FolioTransactionCategory, name="folio_tx_category", native_enum=True),
        nullable=False, index=True
    )
    description      = Column(Text, nullable=True)

    # Amount: (+) charge, (-) payment/discount/refund
    amount           = Column(NUMERIC(15, 2), nullable=False)
    quantity         = Column(NUMERIC(10, 2), default=1)
    unit_price       = Column(NUMERIC(15, 2), nullable=True)

    currency         = Column(String(10), default="VND")

    # Reference to external entity (room_charge, minibar, service...)
    reference_id     = Column(BIGINT, nullable=True, index=True)
    reference_type   = Column(String(50), nullable=True)  # room_charge / minibar_item / service / ...

    # Void flag — dòng bị hủy
    is_voided        = Column(Boolean, default=False)
    void_reason      = Column(Text, nullable=True)
    void_by          = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    void_at         = Column(DateTime(timezone=True), nullable=True)

    # Reverse link to ShiftReportTransaction (nếu dòng này là payment đã sync)
    shift_transaction_id = Column(BIGINT, ForeignKey("shift_report_transactions.id", ondelete="SET NULL"), nullable=True, index=True)

    # Audit
    created_at       = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    created_by       = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        Index("ix_ftfolio_created", "folio_id", "created_at"),
        Index("ix_ftstay_created", "stay_id", "created_at"),
        Index("ix_fttype_created", "transaction_type", "created_at"),
        Index("ix_ftcategory", "category"),
    )

    folio     = relationship("Folio", back_populates="transactions")
    stay      = relationship("HotelStay")
    branch    = relationship("Branch")
    creator   = relationship("User", foreign_keys=[created_by])
    voider    = relationship("User", foreign_keys=[void_by])

    # Payments allocated to this transaction
    allocations = relationship("PaymentAllocation", back_populates="transaction",
                               cascade="all, delete-orphan")

    # Link đến ShiftReportTransaction (nếu là payment đã đồng bộ)
    shift_transaction = relationship("ShiftReportTransaction", foreign_keys=[shift_transaction_id])


# ── Debt & Refund Record Models ──────────────────────────────────────────────

class DebtRecord(Base):
    """Bản ghi công nợ — theo dõi từng lần ghi nhận nợ tại checkout."""
    __tablename__ = "debt_records"

    id             = Column(BIGINT, primary_key=True)
    folio_id       = Column(BIGINT, ForeignKey("folios.id", ondelete="CASCADE"), nullable=False, index=True)
    stay_id        = Column(BIGINT, ForeignKey("hotel_stays.id", ondelete="RESTRICT"), nullable=False, index=True)
    branch_id      = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False)

    debt_amount    = Column(NUMERIC(15, 2), default=Decimal("0"), nullable=False)
    paid_amount    = Column(NUMERIC(15, 2), default=Decimal("0"), nullable=False)
    remaining_amount = Column(NUMERIC(15, 2), default=Decimal("0"), nullable=False)

    status         = Column(String(20), default="pending", nullable=False)
    note           = Column(Text, nullable=True)

    created_by     = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    settled_by     = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    settled_at     = Column(DateTime(timezone=True), nullable=True)
    updated_at     = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    settlement_tx_id = Column(BIGINT, ForeignKey("folio_transactions.id"), nullable=True)

    folio   = relationship("Folio", back_populates="debt_records")
    stay    = relationship("HotelStay")
    branch  = relationship("Branch")
    creator = relationship("User", foreign_keys=[created_by])
    settler = relationship("User", foreign_keys=[settled_by])

    __table_args__ = (
        Index("idx_debt_records_status", "status"),
    )


class RefundRecord(Base):
    """Bản ghi hoàn tiền — theo dõi từng lần hoàn tiền dư tại checkout."""
    __tablename__ = "refund_records"

    id             = Column(BIGINT, primary_key=True)
    folio_id       = Column(BIGINT, ForeignKey("folios.id", ondelete="CASCADE"), nullable=False, index=True)
    stay_id        = Column(BIGINT, ForeignKey("hotel_stays.id", ondelete="RESTRICT"), nullable=False, index=True)
    branch_id      = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False)

    refund_amount  = Column(NUMERIC(15, 2), default=Decimal("0"), nullable=False)
    refund_method  = Column(String(30), default="CASH")
    refund_account = Column(String(100), nullable=True)
    status         = Column(String(20), default="pending", nullable=False)
    note           = Column(Text, nullable=True)

    created_by     = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    settled_by     = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    settled_at     = Column(DateTime(timezone=True), nullable=True)
    updated_at     = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    refund_tx_id   = Column(BIGINT, ForeignKey("folio_transactions.id"), nullable=True)

    folio   = relationship("Folio", back_populates="refund_records")
    stay    = relationship("HotelStay")
    branch  = relationship("Branch")
    creator = relationship("User", foreign_keys=[created_by])
    settler = relationship("User", foreign_keys=[settled_by])


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"  # Chờ xử lý (chuyển khoản chờ confirm)
    SUCCESS = "SUCCESS"  # Thành công
    FAILED  = "FAILED"   # Thất bại
    REFUNDED = "REFUNDED"  # Đã hoàn


class PaymentMethod(str, enum.Enum):
    CASH         = "CASH"           # Tiền mặt
    CARD         = "CARD"           # Thẻ (quẹt / chuyển khoản)
    OTA          = "OTA"            # OTA (Booking.com, Agoda...)
    COMPANY      = "COMPANY"         # Công ty (ncđ)
    BRANCH       = "BRANCH"          # Tài khoản chi nhánh
    OTHER        = "OTHER"          # Khác


class Payment(Base):
    """Một lần thanh toán thực tế (1 payment có thể khớp nhiều FolioTransaction qua PaymentAllocation)."""
    __tablename__ = "payments"

    id               = Column(BIGINT, primary_key=True)
    folio_id         = Column(BIGINT, ForeignKey("folios.id", ondelete="CASCADE"), nullable=False, index=True)
    stay_id          = Column(BIGINT, ForeignKey("hotel_stays.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id        = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)

    amount           = Column(NUMERIC(15, 2), nullable=False)
    method           = Column(
        SQLAlchemyEnum(PaymentMethod, name="payment_method", native_enum=True),
        nullable=False, index=True
    )
    status           = Column(
        SQLAlchemyEnum(PaymentStatus, name="payment_status", native_enum=True),
        default=PaymentStatus.SUCCESS, nullable=False, index=True
    )
    currency         = Column(String(10), default="VND")

    # Mã giao dịch (số bill, mã UNC, mã OTA...)
    transaction_code  = Column(String(100), nullable=True, index=True)

    # Metadata thanh toán
    meta             = Column(JSONB, nullable=True)  # {ota_booking_id, card_last4, bank...}

    # Refund tracking
    is_refunded      = Column(Boolean, default=False)
    refunded_amount  = Column(NUMERIC(15, 2), default=0)
    refund_reason    = Column(Text, nullable=True)
    refunded_by      = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    refunded_at     = Column(DateTime(timezone=True), nullable=True)

    # Audit
    paid_at          = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    created_by       = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        Index("ix_pay_folio", "folio_id"),
        Index("ix_pay_stay", "stay_id"),
        Index("ix_pay_method_status", "method", "status"),
        Index("ix_pay_paid_at", "paid_at"),
    )

    folio      = relationship("Folio", back_populates="payments")
    stay       = relationship("HotelStay")
    branch     = relationship("Branch")
    creator    = relationship("User", foreign_keys=[created_by])
    refunder   = relationship("User", foreign_keys=[refunded_by])

    allocations = relationship("PaymentAllocation", back_populates="payment",
                              cascade="all, delete-orphan")

    @property
    def allocated_amount(self) -> float:
        return sum(a.amount for a in self.allocations)

    @property
    def unallocated_amount(self) -> float:
        return float(self.amount or 0) - self.allocated_amount


class PaymentAllocation(Base):
    """Liên kết payment ↔ folio_transaction (split bill: 1 payment → nhiều charges)."""
    __tablename__ = "payment_allocations"

    id                    = Column(BIGINT, primary_key=True)
    payment_id            = Column(BIGINT, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True)
    folio_transaction_id  = Column(BIGINT, ForeignKey("folio_transactions.id", ondelete="CASCADE"), nullable=False, index=True)

    # Amount allocated từ payment này vào transaction này
    amount                = Column(NUMERIC(15, 2), nullable=False)

    created_at            = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_alloc_payment", "payment_id"),
        Index("ix_alloc_transaction", "folio_transaction_id"),
        Index("uq_alloc_payment_transaction", "payment_id", "folio_transaction_id", unique=True),
    )

    payment     = relationship("Payment", back_populates="allocations")
    transaction = relationship("FolioTransaction", back_populates="allocations")


class HotelGuest(Base):
    """Thông tin khách lưu trú trong 1 lượt ở"""
    __tablename__ = "hotel_guests"

    id          = Column(BIGINT, primary_key=True)
    stay_id     = Column(BIGINT, ForeignKey("hotel_stays.id", ondelete="CASCADE"), nullable=False, index=True)
    full_name   = Column(String(255), nullable=False)
    cccd        = Column(String(20), nullable=True, index=True)  # Số giấy tờ - có index để tìm kiếm nhanh
    birth_date  = Column(Date, nullable=True)
    gender      = Column(String(10), nullable=True)      # "Nam" / "Nữ" / "Khác"
    phone       = Column(String(20), nullable=True)
    
    # Address info — luôn lưu địa bàn MỚI (sau 1/7/2025)
    address       = Column(Text, nullable=True)
    address_type  = Column(String(10), nullable=True) # "new" | "old"
    city          = Column(String(100), nullable=True)   # Tỉnh/TP mới (display name)
    district      = Column(String(100), nullable=True)   # Quận/Huyện mới (sau chuyển đổi)
    ward          = Column(String(100), nullable=True)   # Phường/Xã mới (sau chuyển đổi)
    # Lưu địa bàn CŨ để tham khảo (chỉ khi người dùng chọn địa bàn cũ lúc checkin)
    old_city      = Column(String(100), nullable=True)   # Tỉnh/TP cũ
    old_district  = Column(String(100), nullable=True)   # Quận/Huyện cũ
    old_ward      = Column(String(100), nullable=True)   # Phường/Xã cũ
    
    # Other info
    id_expire    = Column(Date, nullable=True)
    id_type      = Column(String(20), nullable=True)    # cccd, cmnd, passport, visa, gplx
    notes        = Column(Text, nullable=True)
    tax_code    = Column(String(50), nullable=True)      # Mã số thuế (bắt buộc khi xuất hoá đơn)
    invoice_contact = Column(String(255), nullable=True)  # Liên hệ gửi hoá đơn (bắt buộc khi xuất hoá đơn)
    company_name    = Column(String(255), nullable=True)
    company_address = Column(Text, nullable=True)
    nationality  = Column(String(100), nullable=True)     # Quốc tịch (VD: "VNM - Việt Nam") - cũng có trong Guest
    guest_id     = Column(BIGINT, ForeignKey("guests.id", ondelete="SET NULL"), index=True)
    is_primary  = Column(Boolean, default=False)          # Khách đặt phòng chính
    check_in_at  = Column(DateTime(timezone=True), nullable=True)
    check_out_at = Column(DateTime(timezone=True), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    stay = relationship("HotelStay", back_populates="guests")
    guest = relationship("Guest", back_populates="hotel_guests")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])

    # Composite indexes for guest queries
    __table_args__ = (
        Index("ix_hotel_guests_guest_stay", "guest_id", "stay_id"),
        Index("ix_hotel_guests_guest_id_desc", "guest_id", id.desc()),
        Index("ix_hotel_guests_cccd_active", "cccd",
              postgresql_where=(cccd != None)),
    )


# ====================================================================
# 10. GUEST MODULE (CRM CORE - PMS 2026)
# ====================================================================

class Guest(Base):
    """Master Guest - Thông tin khách hàng độc lập với lượt lưu trú"""
    __tablename__ = "guests"

    id = Column(BIGINT, primary_key=True)
    full_name = Column(String(255), nullable=False)
    normalized_name = Column(String(255))  # Tên không dấu, lowercase để search
    phone = Column(String(20), index=True)
    email = Column(String(255), index=True)
    cccd = Column(String(20), index=True)  # CCCD/Passport
    date_of_birth = Column(Date)
    gender = Column(String(10))  # Nam / Nữ / Khác
    nationality = Column(String(100))
    id_expire = Column(Date, nullable=True)  # Ngày hết hạn CCCD/CMND/Passport — luôn cập nhật mới nhất từ hotel_guests
    default_address = Column(Text)
    tax_code = Column(String(50), nullable=True)
    invoice_contact = Column(String(255), nullable=True)
    company_name = Column(String(255), nullable=True)
    company_address = Column(Text, nullable=True)
    first_seen_at = Column(DateTime(timezone=True))
    last_seen_at = Column(DateTime(timezone=True))
    total_stays = Column(Integer, default=0)
    total_spent = Column(NUMERIC(15, 2), default=0)
    is_blacklisted = Column(Boolean, default=False)
    tags = Column(JSONB, server_default='[]', default=[])  # ['VIP', 'OTA', 'CORP']
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # Soft delete
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Unique constraint: cccd không trùng (partial - chỉ khi có giá trị)
    __table_args__ = (
        Index("uq_guest_cccd_not_null", "cccd", unique=True,
              postgresql_where=(cccd != None)),
        Index("ix_guests_deleted", "deleted_at",
              postgresql_where=(deleted_at != None)),
        Index("ix_guests_active_last_seen", last_seen_at.desc(), "id",
              postgresql_where=(deleted_at == None)),
        Index("ix_guests_active_blacklist_last_seen", "is_blacklisted", last_seen_at.desc(), "id",
              postgresql_where=(deleted_at == None)),
        Index("ix_guests_active_normalized_name_pattern", "normalized_name",
              postgresql_ops={"normalized_name": "text_pattern_ops"},
              postgresql_where=(deleted_at == None)),
        Index("ix_guests_active_full_name_pattern", "full_name",
              postgresql_ops={"full_name": "text_pattern_ops"},
              postgresql_where=(deleted_at == None)),
        Index("ix_guests_active_full_name_trgm", "full_name",
              postgresql_using="gin",
              postgresql_ops={"full_name": "gin_trgm_ops"},
              postgresql_where=(deleted_at == None)),
        Index("ix_guests_active_phone_pattern", "phone",
              postgresql_ops={"phone": "text_pattern_ops"},
              postgresql_where=(deleted_at == None)),
        Index("ix_guests_active_email_pattern", "email",
              postgresql_ops={"email": "text_pattern_ops"},
              postgresql_where=(deleted_at == None)),
        Index("ix_guests_active_cccd_pattern", "cccd",
              postgresql_ops={"cccd": "text_pattern_ops"},
              postgresql_where=((deleted_at == None) & (cccd != None))),
    )

    # Relationships
    identities = relationship("GuestIdentity", back_populates="guest", cascade="all, delete-orphan")
    profile = relationship("GuestProfile", back_populates="guest", uselist=False, cascade="all, delete-orphan")
    preferences = relationship("GuestPreference", back_populates="guest", cascade="all, delete-orphan")
    interactions = relationship("GuestInteraction", back_populates="guest", cascade="all, delete-orphan")
    activities = relationship("GuestActivity", back_populates="guest", cascade="all, delete-orphan")
    hotel_guests = relationship("HotelGuest", back_populates="guest")
    bookings = relationship("Booking", back_populates="guest")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class GuestIdentity(Base):
    """Định danh khách (phone/email/cccd) - Chống trùng lặp"""
    __tablename__ = "guest_identities"

    id = Column(BIGINT, primary_key=True)
    guest_id = Column(BIGINT, ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    identity_type = Column(String(50), nullable=False)  # phone / email / cccd
    identity_value = Column(String(255), nullable=False)
    normalized_value = Column(String(255), index=True)  # Chuẩn hóa: lowercase email, số điện thoại không +84
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Unique constraint: identity_type + normalized_value
    __table_args__ = (
        Index("uq_guest_identity_type_norm", "identity_type", "normalized_value", unique=True),
    )

    guest = relationship("Guest", back_populates="identities")


class GuestProfile(Base):
    """Dữ liệu tổng hợp về khách (Aggregate)"""
    __tablename__ = "guest_profiles"

    guest_id = Column(BIGINT, ForeignKey("guests.id", ondelete="CASCADE"), primary_key=True)
    avg_stay_duration = Column(Float, default=0)  # Số đêm TB
    favorite_room_type = Column(String(100))  # Loại phòng hay ở nhất
    last_room_number = Column(String(20))  # Phòng gần nhất
    preferred_payment = Column(String(50))  # Thanh toán ưa thích
    risk_score = Column(Float, default=0)  # Điểm rủi ro
    lifetime_value = Column(NUMERIC(15, 2), default=0)  # Giá trị trọn đời
    last_review_score = Column(Float)  # Điểm review gần nhất
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    guest = relationship("Guest", back_populates="profile")


class GuestPreference(Base):
    """Sở thích khách (hút thuốc, giường, tầng...)"""
    __tablename__ = "guest_preferences"

    id = Column(BIGINT, primary_key=True)
    guest_id = Column(BIGINT, ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    preference_type = Column(String(50), nullable=False)  # smoking / bed / floor / pillow / breakfast
    preference_value = Column(String(255))  # non-smoking / king-bed / high-floor
    source = Column(String(20), default="manual")  # manual / AI / booking
    confidence_score = Column(Float, default=1.0)  # 0-1
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_guest_preference_type", "guest_id", "preference_type", unique=True),
    )

    guest = relationship("Guest", back_populates="preferences")


class GuestInteraction(Base):
    """Tương tác với khách (gọi điện, chat, email, khiếu nại, khen ngợi)"""
    __tablename__ = "guest_interactions"

    id = Column(BIGINT, primary_key=True)
    guest_id = Column(BIGINT, ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    interaction_type = Column(String(50), nullable=False)  # call / chat / email / complaint / compliment
    content = Column(Text)
    staff_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    guest = relationship("Guest", back_populates="interactions")
    staff = relationship("User")


class GuestActivity(Base):
    """Hoạt động của khách (Timeline)"""
    __tablename__ = "guest_activities"

    id = Column(BIGINT, primary_key=True)
    guest_id = Column(BIGINT, ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    activity_type = Column(String(50), nullable=False)  # CHECK_IN, CHECK_OUT, PAYMENT_RECEIVED...
    activity_group = Column(String(50))  # stay, booking, payment, service, experience, system
    title = Column(String(255))  # Tiêu đề hiển thị
    description = Column(Text)  # Mô tả chi tiết
    stay_id = Column(BIGINT, ForeignKey("hotel_stays.id", ondelete="SET NULL"), index=True)
    booking_id = Column(BIGINT, ForeignKey("bookings.id", ondelete="SET NULL"), index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"))
    amount = Column(NUMERIC(15, 2))  # Số tiền (nếu liên quan)
    currency = Column(String(10), default="VND")
    actor_type = Column(String(20))  # system / user / guest
    actor_id = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), index=True)  # user_id nếu có
    source = Column(String(50))  # pms / ota / api / ai
    extra_data = Column(JSONB)  # Dữ liệu mở rộng
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Composite index for timeline queries
    __table_args__ = (
        Index("ix_guest_activities_guest_created", "guest_id", created_at.desc()),
        Index("ix_guest_activities_blacklist_guest_created", "guest_id", created_at.desc(),
              postgresql_where=(activity_type == "BLACKLISTED")),
    )

    guest = relationship("Guest", back_populates="activities")
    stay = relationship("HotelStay")
    booking = relationship("Booking")
    branch = relationship("Branch")


# ====================================================================
# 11. GUEST CRM - MEMBERSHIP & ANALYTICS (Phân loại khách hàng)
# ====================================================================

class MemberTier(str, enum.Enum):
    """Bậc thành viên - tự động cập nhật dựa trên total_spent"""
    BASIC = "BASIC"           # Khách thường
    SILVER = "SILVER"         # Khách Bạc
    GOLD = "GOLD"             # Khách Vàng
    PLATINUM = "PLATINUM"     # Khách Bạch Kim
    VIP = "VIP"               # Khách VIP


class CrmMembershipSetting(Base):
    """Cấu hình quy tắc tích điểm, lên hạng và quyền lợi CRM."""
    __tablename__ = "crm_membership_settings"

    id = Column(Integer, primary_key=True)
    points_per_1000_vnd = Column(NUMERIC(10, 2), nullable=False, default=1)
    tiers = Column(JSONB, nullable=False, server_default='[]', default=[])
    updated_by = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    updater = relationship("User", foreign_keys=[updated_by])


class GuestMembership(Base):
    """Bậc thành viên của khách - tự động tính và cập nhật"""
    __tablename__ = "guest_memberships"

    id = Column(BIGINT, primary_key=True)
    guest_id = Column(BIGINT, ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    
    tier = Column(SQLAlchemyEnum(MemberTier, name="membertier", native_enum=True), default=MemberTier.BASIC)
    tier_updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Thống kê tích lũy
    total_stays = Column(Integer, default=0)
    total_nights = Column(Integer, default=0)
    total_spent = Column(NUMERIC(15, 2), default=0)
    total_deposit = Column(NUMERIC(15, 2), default=0)
    total_debt = Column(NUMERIC(15, 2), default=0)  # Tổng nợ chưa trả
    total_refund = Column(NUMERIC(15, 2), default=0)
    
    # Điểm thưởng (loyalty points)
    loyalty_points = Column(Integer, default=0)
    points_redeemed = Column(Integer, default=0)
    points_balance = Column(Integer, default=0)  # loyalty_points - points_redeemed
    
    # Preferences
    favorite_branch_id = Column(Integer, ForeignKey("branches.id", ondelete="SET NULL"))
    favorite_room_type = Column(String(100))
    preferred_payment_method = Column(String(50))
    
    # Notes
    membership_note = Column(Text)
    
    # Auto-updated
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    guest = relationship("Guest", back_populates="membership")
    favorite_branch = relationship("Branch")

    __table_args__ = (
        Index("ix_guest_membership_tier", "tier"),
        Index("ix_guest_membership_tier_guest", "tier", "guest_id"),
        Index("ix_guest_membership_spent", "total_spent"),
    )


class GuestStaySummary(Base):
    """Tổng hợp lưu trú - Mỗi lần ở tạo 1 record để query nhanh"""
    __tablename__ = "guest_stay_summaries"

    id = Column(BIGINT, primary_key=True)
    guest_id = Column(BIGINT, ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    stay_id = Column(BIGINT, ForeignKey("hotel_stays.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False)

    # Room info
    room_number = Column(String(20))
    room_type_name = Column(String(100))
    floor = Column(Integer)

    # Dates
    check_in_at = Column(DateTime(timezone=True), nullable=False)
    check_out_at = Column(DateTime(timezone=True))
    nights = Column(Integer, default=0)  # Số đêm ở

    # Pricing
    total_charge = Column(NUMERIC(15, 2), default=0)
    discount = Column(NUMERIC(15, 2), default=0)
    deposit = Column(NUMERIC(15, 2), default=0)
    deposit_type = Column(String(50))
    deposit_paid = Column(NUMERIC(15, 2), default=0)
    final_amount = Column(NUMERIC(15, 2), default=0)  # Thực trả cuối cùng
    debt_amount = Column(NUMERIC(15, 2), default=0)

    # Stay type
    stay_type = Column(String(20))  # NIGHT / HOUR / DAY_USE / AUTO
    pricing_mode = Column(String(20))  # HOURLY / NIGHT / DAY_USE

    # Guest count
    guest_count = Column(Integer, default=1)

    # Status
    status = Column(String(20))  # ACTIVE / CHECKED_OUT / CANCELLED
    checkout_summary = Column(String(50))  # normal / debt / refund

    # Payment methods used in this stay
    payment_methods = Column(JSONB, default=[])  # ["CASH", "CARD"]

    # Vehicle
    vehicle = Column(String(100))

    # Source
    source = Column(String(50))  # pms / ota / walkin

    # For debt tracking
    debt_status = Column(String(20))  # none / pending / partial / settled

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    guest = relationship("Guest", back_populates="stay_summaries")
    stay = relationship("HotelStay")
    branch = relationship("Branch")

    __table_args__ = (
        Index("ix_guest_stay_summary_guest_date", "guest_id", check_in_at.desc()),
        Index("ix_guest_stay_summary_branch", "branch_id"),
        Index("ix_guest_stay_summary_guest_debt", "guest_id", "debt_status",
              postgresql_where=(debt_amount > 0)),
        Index("ix_guest_stay_summary_debt_status_guest", "debt_status", "guest_id",
              postgresql_where=(debt_amount > 0)),
        Index("uq_guest_stay_unique", "guest_id", "stay_id", unique=True),
    )


class GuestServiceUsage(Base):
    """Theo dõi dịch vụ sử dụng của khách"""
    __tablename__ = "guest_service_usages"

    id = Column(BIGINT, primary_key=True)
    guest_id = Column(BIGINT, ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    stay_id = Column(BIGINT, ForeignKey("hotel_stays.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False)

    # Service info
    service_category = Column(String(50), nullable=False)  # MINIBAR / LAUNDRY / RESTAURANT / SPA / ROOM_SERVICE / OTHER
    service_name = Column(String(255), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)

    # Usage details
    quantity = Column(NUMERIC(10, 2), default=1)
    unit_price = Column(NUMERIC(15, 2), default=0)
    total_amount = Column(NUMERIC(15, 2), default=0)
    currency = Column(String(10), default="VND")

    # Room & time
    room_number = Column(String(20))
    used_at = Column(DateTime(timezone=True), nullable=False)

    # Reference
    folio_transaction_id = Column(BIGINT, ForeignKey("folio_transactions.id", ondelete="SET NULL"), nullable=True)
    stock_movement_id = Column(BIGINT, ForeignKey("stock_movements.id", ondelete="SET NULL"), nullable=True)

    # Who created
    created_by = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    guest = relationship("Guest", back_populates="service_usages")
    stay = relationship("HotelStay")
    branch = relationship("Branch")
    product = relationship("Product")

    __table_args__ = (
        Index("ix_guest_service_usage_guest_date", "guest_id", "used_at"),
        Index("ix_guest_service_usage_category", "service_category"),
        Index("ix_guest_service_usage_stay", "stay_id"),
    )


class GuestPaymentSummary(Base):
    """Tổng hợp thanh toán - Mỗi lần thanh toán tạo 1 record"""
    __tablename__ = "guest_payment_summaries"

    id = Column(BIGINT, primary_key=True)
    guest_id = Column(BIGINT, ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    stay_id = Column(BIGINT, ForeignKey("hotel_stays.id", ondelete="CASCADE"), nullable=False, index=True)
    folio_id = Column(BIGINT, ForeignKey("folios.id", ondelete="SET NULL"), nullable=True)
    payment_id = Column(BIGINT, ForeignKey("payments.id", ondelete="SET NULL"), nullable=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False)

    # Payment info
    amount = Column(NUMERIC(15, 2), nullable=False)
    payment_type = Column(String(50), nullable=False)  # DEPOSIT / PAYMENT / DEBT_PAYMENT / REFUND
    payment_method = Column(String(50), nullable=False)  # CASH / CARD / BANK_TRANSFER / OTA / COMPANY
    transaction_code = Column(String(100))

    # Room info
    room_number = Column(String(20))

    # Time
    paid_at = Column(DateTime(timezone=True), nullable=False)

    # Status
    is_voided = Column(Boolean, default=False)
    void_reason = Column(Text)

    # Notes
    notes = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    guest = relationship("Guest", back_populates="payment_summaries")
    stay = relationship("HotelStay")
    branch = relationship("Branch")
    folio = relationship("Folio")

    __table_args__ = (
        Index("ix_guest_payment_summary_guest_date", "guest_id", "paid_at"),
        Index("ix_guest_payment_summary_method", "payment_method"),
        Index("ix_guest_payment_summary_stay", "stay_id"),
    )


class GuestLoyaltyTransaction(Base):
    """Ghi nhận lịch sử tích và tiêu điểm của khách hàng"""
    __tablename__ = "guest_loyalty_transactions"

    id = Column(BIGINT, primary_key=True)
    guest_id = Column(BIGINT, ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    stay_id = Column(BIGINT, ForeignKey("hotel_stays.id", ondelete="SET NULL"), nullable=True, index=True)
    
    transaction_type = Column(String(50), nullable=False, index=True) # EARN / REDEEM / ADJUSTMENT
    points = Column(Integer, nullable=False) # positive for EARN, negative for REDEEM
    reason = Column(Text)
    
    created_by = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    guest = relationship("Guest", back_populates="loyalty_transactions")
    stay = relationship("HotelStay")


class GuestStayMapping(Base):
    """
    Bảng trung gian lưu quan hệ khách cùng ở.
    Mỗi lần checkout, tất cả khách trong cùng stay sẽ được ghi nhận vào bảng này.
    Dùng để truy vấn "ai từng ở với ai".
    """
    __tablename__ = "guest_stay_mappings"

    id = Column(BIGINT, primary_key=True)
    guest_id = Column(BIGINT, ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True)
    stay_id = Column(BIGINT, ForeignKey("hotel_stays.id", ondelete="CASCADE"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False)

    # Thông tin phòng tại thời điểm checkout
    room_number = Column(String(20), nullable=True)

    # Thời gian lưu trú
    check_in_at = Column(DateTime(timezone=True), nullable=True)
    check_out_at = Column(DateTime(timezone=True), nullable=True)

    # Là khách chính trong lần ở này không
    is_primary = Column(Boolean, default=False)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_guest_stay_mapping_unique", "guest_id", "stay_id", unique=True),
        Index("ix_guest_stay_mapping_guest", "guest_id"),
        Index("ix_guest_stay_mapping_stay", "stay_id"),
        Index("ix_guest_stay_mapping_guest_checkin", "guest_id", check_in_at.desc()),
        Index("ix_guest_stay_mapping_stay_guest", "stay_id", "guest_id"),
    )

    guest = relationship("Guest", back_populates="stay_mappings")
    stay = relationship("HotelStay")
    branch = relationship("Branch")


# ====================================================================
# GUEST RELATIONSHIP UPDATES
# ====================================================================

# Add new relationships to Guest model
Guest.membership = relationship("GuestMembership", back_populates="guest", uselist=False, cascade="all, delete-orphan")
Guest.stay_summaries = relationship("GuestStaySummary", back_populates="guest", cascade="all, delete-orphan")
Guest.service_usages = relationship("GuestServiceUsage", back_populates="guest", cascade="all, delete-orphan")
Guest.payment_summaries = relationship("GuestPaymentSummary", back_populates="guest", cascade="all, delete-orphan")
Guest.loyalty_transactions = relationship("GuestLoyaltyTransaction", back_populates="guest", cascade="all, delete-orphan")
Guest.stay_mappings = relationship("GuestStayMapping", back_populates="guest", cascade="all, delete-orphan")


# ====================================================================
# HANDBOOK (CẨM NANG)
# ====================================================================

class HandbookEntry(Base):
    """Tình huống và hướng xử lý trong cẩm nang lễ tân."""
    __tablename__ = "handbook_entries"

    id            = Column(BIGINT, primary_key=True)
    situation     = Column(Text, nullable=False)
    solution      = Column(Text, nullable=False)
    severity      = Column(String(20), nullable=False, default="normal", index=True)
    # severity: 'urgent' | 'serious' | 'normal' | 'tip'
    category      = Column(String(50), nullable=False, default="general", index=True)
    # category: 'general' | 'checkin' | 'ota' | 'security' | 'technical' | 'regulation' | 'surcharge'
    shared_by     = Column(String(100), nullable=True)
    is_approved   = Column(Boolean, default=False, nullable=False, index=True)
    created_by    = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    creator = relationship("User", foreign_keys=[created_by])
