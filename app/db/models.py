# app/db/models.py
import enum
from sqlalchemy import (
    Column, String, Integer, DateTime, Text, Date, Boolean, Float, Time,
    Enum as SQLAlchemyEnum, ForeignKey, BIGINT, NUMERIC, Index, func
)
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
    gps_lat = Column(NUMERIC(12, 9))
    gps_lng = Column(NUMERIC(12, 9))
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
    last_active_branch = Column(String, nullable=True)

    # --- Relationships ---
    department = relationship("Department")
    main_branch = relationship("Branch")
    
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
    status = Column(String(50), default='Đang chờ', index=True)
    
    due_date = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at = Column(DateTime(timezone=True))
    notes = Column(Text)

    branch = relationship("Branch")
    author = relationship("User", foreign_keys=[author_id], back_populates="created_tasks")
    assignee = relationship("User", foreign_keys=[assignee_id], back_populates="assigned_tasks")
    deleter = relationship("User", foreign_keys=[deleter_id], back_populates="deleted_tasks")

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
    amount = Column(BIGINT, nullable=False, index=True)
    room_number = Column(String(50), nullable=True, index=True)
    transaction_info = Column(String(255), nullable=True)
    status = Column(SQLAlchemyEnum(ShiftReportStatus, name="shiftreportstatus", native_enum=True), default=ShiftReportStatus.PENDING, index=True)
    
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
    
    pms_revenue = Column(BIGINT, nullable=False, default=0)
    closed_online_revenue = Column(BIGINT, nullable=False, default=0)
    closed_branch_revenue = Column(BIGINT, nullable=False, default=0)
    
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
    min_stock_global = Column(Integer, default=0)
    
    is_active = Column(Boolean, default=True)
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
    actor_id = Column(BIGINT, ForeignKey("users.id"))

    product = relationship("Product")
    warehouse = relationship("Warehouse")
    actor = relationship("User")

# 7.3 Flows (Nhập hàng & Điều chuyển)

# A. Nhập hàng từ NCC
class InventoryReceipt(Base):
    __tablename__ = "inventory_receipts"
    
    id = Column(BIGINT, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    supplier_name = Column(String(255))
    
    creator_id = Column(BIGINT, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    total_amount = Column(NUMERIC(15, 2), default=0)
    notes = Column(Text)

    items = relationship("InventoryReceiptItem", back_populates="receipt", cascade="all, delete-orphan")
    # [FIX] Add cascade delete for images to prevent NotNullViolation on delete
    images = relationship("ImportImage", back_populates="receipt", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[creator_id])

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

    items = relationship("InventoryTransferItem", back_populates="transfer", cascade="all, delete-orphan")
    images = relationship("TransferImage", back_populates="transfer", cascade="all, delete-orphan")
    requester = relationship("User", foreign_keys=[requester_id])
    approver_user = relationship("User", foreign_keys=[approver_id])
    source_warehouse = relationship("Warehouse", foreign_keys=[source_warehouse_id])
    dest_warehouse = relationship("Warehouse", foreign_keys=[dest_warehouse_id])
    
    # Relationship for accessing the parent ticket or children compensation tickets
    related_transfer = relationship("InventoryTransfer", remote_side=[id], backref="compensation_transfers")

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
