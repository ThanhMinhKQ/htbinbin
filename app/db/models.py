# app/db/models.py
import enum
from sqlalchemy import (
    Column, String, Integer, DateTime, Text, Date, Boolean, Float, Time,
    Enum as SQLAlchemyEnum, ForeignKey, BIGINT, NUMERIC, Index, func,
    CheckConstraint
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
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default='Đang chờ', index=True)

    due_date = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at = Column(DateTime(timezone=True))
    notes = Column(Text)

    branch = relationship("Branch")
    department = relationship("Department")  # Thêm relationship
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
    supplier_name = Column(String(255))

    creator_id = Column(BIGINT, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    total_amount = Column(NUMERIC(15, 2), default=0)
    notes = Column(Text)
    version = Column(Integer, default=1, nullable=False)  # Optimistic locking

    items = relationship("InventoryReceiptItem", back_populates="receipt", cascade="all, delete-orphan")
    images = relationship("ImportImage", back_populates="receipt", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[creator_id])

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

    # Composite indexes + constraints
    __table_args__ = (
        Index("ix_booking_guest_checkin", "guest_id", "check_in"),
        Index("ix_booking_dates", "check_in", "check_out"),
        Index("uq_booking_source_external", "booking_source", "external_id", unique=True,
              postgresql_where=(external_id != None)),
        Index("ix_bookings_version", "version"),
        CheckConstraint("check_out > check_in", name="check_booking_dates"),
    )

    branch = relationship("Branch")
    guest = relationship("Guest", back_populates="bookings")
    source_booking = relationship("Booking", remote_side="Booking.id", foreign_keys=[source_booking_id])
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])

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
    promo_discount_percent = Column(Float, default=0, nullable=False)    # % giảm giá ưu đãi ban đêm
    min_hours       = Column(Integer, default=1)                   # Tối thiểu bao nhiêu giờ
    max_guests      = Column(Integer, default=2)
    is_active       = Column(Boolean, default=True)
    sort_order      = Column(Integer, default=0)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    branch = relationship("Branch")
    rooms  = relationship("HotelRoom", back_populates="room_type_obj")


class HotelRoom(Base):
    """Phòng khách sạn (Admin cấu hình)"""
    __tablename__ = "hotel_rooms"

    id             = Column(Integer, primary_key=True)
    branch_id      = Column(Integer, ForeignKey("branches.id", ondelete="CASCADE"), nullable=False, index=True)
    room_type_id   = Column(Integer, ForeignKey("hotel_room_types.id", ondelete="SET NULL"), nullable=True)
    floor          = Column(Integer, nullable=False, index=True)    # Tầng
    room_number    = Column(String(20), nullable=False)             # Số phòng e.g. "101"
    notes          = Column(Text, nullable=True)
    is_active      = Column(Boolean, default=True)
    sort_order     = Column(Integer, default=0)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

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
    NIGHT = "NIGHT"    # Qua đêm
    HOUR = "HOUR"      # Theo giờ
    DAY_USE = "DAY_USE"  # Day use
    WEEKLY = "WEEKLY"  # Theo tuần


class HotelStay(Base):
    """Lượt lưu trú (một lần check-in/check-out)"""
    __tablename__ = "hotel_stays"

    id           = Column(BIGINT, primary_key=True)
    room_id      = Column(Integer, ForeignKey("hotel_rooms.id", ondelete="RESTRICT"), nullable=False, index=True)
    branch_id    = Column(Integer, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True)
    stay_type    = Column(SQLAlchemyEnum(StayType, name="staytype", native_enum=True), default=StayType.NIGHT, nullable=False)
    check_in_at  = Column(DateTime(timezone=True), nullable=False, index=True)
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

    created_by   = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at   = Column(DateTime(timezone=True), nullable=True)  # Soft delete
    version      = Column(Integer, default=1, nullable=False)  # Optimistic locking

    # Composite indexes for common queries
    __table_args__ = (
        Index("ix_stay_room_status", "room_id", "status"),
        Index("ix_stay_branch_status", "branch_id", "status"),
        Index("ix_hotel_stays_version", "version"),
    )

    room       = relationship("HotelRoom", back_populates="stays")
    branch     = relationship("Branch")
    creator    = relationship("User", foreign_keys=[created_by])
    guests     = relationship("HotelGuest", back_populates="stay", cascade="all, delete-orphan",
                              order_by="HotelGuest.is_primary.desc()")


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
    nationality  = Column(String(100), nullable=True)     # Quốc tịch (VD: "VNM - Việt Nam") - cũng có trong Guest
    guest_id     = Column(BIGINT, ForeignKey("guests.id", ondelete="SET NULL"), index=True)
    is_primary  = Column(Boolean, default=False)          # Khách đặt phòng chính
    check_in_at  = Column(DateTime(timezone=True), nullable=True)
    check_out_at = Column(DateTime(timezone=True), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(BIGINT, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    stay = relationship("HotelStay", back_populates="guests")
    guest = relationship("Guest", back_populates="hotel_guests")
    creator = relationship("User")

    # Composite indexes for guest queries
    __table_args__ = (
        Index("ix_hotel_guests_guest_stay", "guest_id", "stay_id"),
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
    default_address = Column(Text)
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
        Index("ix_guest_activities_guest_created", "guest_id", "created_at"),
    )

    guest = relationship("Guest", back_populates="activities")
    stay = relationship("HotelStay")
    booking = relationship("Booking")
    branch = relationship("Branch")