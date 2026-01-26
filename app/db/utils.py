from sqlalchemy.orm import Session
from sqlalchemy import text, inspect
from ..core.config import logger, BRANCHES, ROLE_MAP, BRANCH_COORDINATES
from ..db.models import User, Branch, Department

# Import the `employees` list from the `employees` module
from ..services.user_service import sync_employees_from_source
from ..employees import employees

def reset_all_sequences(db: Session):
    """
    Hàm này đồng bộ lại tất cả các 'sequence' (bộ đếm ID tự tăng) trong database PostgreSQL.
    Nó sẽ đặt giá trị tiếp theo của sequence bằng ID lớn nhất hiện có trong bảng + 1.
    - Mục đích: Tránh lỗi xung đột Primary Key (khóa chính) sau khi thêm dữ liệu thủ công hoặc khôi phục database.
    - Lưu ý: Hàm này được thiết kế riêng cho PostgreSQL.
    """
    # Kiểm tra xem dialect của database có phải là postgresql không
    if db.bind.dialect.name != 'postgresql':
        logger.warning("Sequence reset is only implemented for PostgreSQL. Skipping.")
        return

    logger.info("Checking and resetting database sequences...")
    # Sử dụng kết nối hiện có của session để tránh tạo thêm kết nối mới
    connection = db.connection()
    inspector = inspect(connection)

    try:
        # Câu query để tìm tất cả các sequence và bảng tương ứng trong schema 'public'
        sequences_query = text("""
            SELECT c.relname AS seq_name, t.relname AS table_name
            FROM pg_class c
            JOIN pg_depend d ON d.objid = c.oid
            JOIN pg_class t ON t.oid = d.refobjid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
            WHERE c.relkind = 'S' AND d.refclassid = 'pg_class'::regclass AND t.relnamespace = 'public'::regnamespace
        """)
        sequences = connection.execute(sequences_query).fetchall()

        for seq_name, table_name in sequences:
            try:
                # SỬA LỖI: Dùng inspector đã tạo với kết nối có sẵn, không tạo kết nối mới
                if inspector.has_table(table_name, schema='public'):
                    # Lấy ID lớn nhất hiện tại từ bảng
                    max_id_result = connection.execute(text(f'SELECT MAX(id) FROM public."{table_name}"')).scalar()
                    # Giá trị tiếp theo sẽ là max_id + 1. Nếu bảng rỗng (max_id là None), bắt đầu từ 1.
                    next_val = int(max_id_result or 0) + 1

                    # Đặt lại giá trị cho sequence
                    connection.execute(text(f"SELECT setval('public.\"{seq_name}\"', {next_val}, false)"))
                    logger.debug(f"Reset sequence '{seq_name}' for table '{table_name}' to {next_val}.")
                else:
                    # Nếu bảng không tồn tại (sequence "mồ côi"), bỏ qua một cách im lặng để không làm nhiễu log.
                    pass
            except Exception as e:
                # Không cần begin_nested/commit/rollback ở đây, để transaction chính quản lý
                logger.warning(f"Could not reset sequence for table '{table_name}': {e}")
        
        # Commit toàn bộ giao dịch lớn sau khi hoàn tất vòng lặp
        db.commit()
        logger.info("Sequence reset complete.")
    except Exception as e:
        db.rollback()
        logger.error(f"An error occurred during sequence reset: {e}", exc_info=True)


def sync_employees_on_startup(db: Session):
    """
    Kiểm tra và đồng bộ dữ liệu nhân viên từ file `employees.py` vào database khi khởi động.
    Hàm này sẽ thêm mới hoặc cập nhật thông tin nhân viên dựa trên `employee_id`.
    """
    logger.info("Starting employee data synchronization on startup...")
    # Gọi hàm đồng bộ thực tế từ user_service
    # force_delete=False để tránh xóa nhầm nhân viên khi file nguồn có thể bị lỗi
    sync_employees_from_source(db=db, employees_source=employees, force_delete=False)
    logger.info("Employee data synchronization on startup finished.")


def sync_master_data(db: Session):
    """
    Đồng bộ dữ liệu nền (Master Data): Chi nhánh & Phòng ban (Vai trò).
    Đảm bảo các bảng branches và departments có đủ dữ liệu trước khi sync nhân viên.
    """
    logger.info("Starting Master Data synchronization...")
    
    # 1. Đồng bộ DEPARTMENTS (Roles)
    # ROLE_MAP = {"letan": "Lễ tân", ...}
    for code, name in ROLE_MAP.items():
        dept = db.query(Department).filter(Department.role_code == code).first()
        if not dept:
            dept = Department(role_code=code, name=name)
            db.add(dept)
            logger.info(f"[MASTER] Created Department: {code} - {name}")
        else:
            if dept.name != name:
                dept.name = name
                logger.info(f"[MASTER] Updated Department name: {code}")
    
    # 2. Đồng bộ BRANCHES
    # BRANCHES = ["B1", "B2", ...]
    # BRANCH_COORDINATES = {"B1": [lat, lng], ...}
    for code in BRANCHES:
        branch = db.query(Branch).filter(Branch.branch_code == code).first()
        
        # Lấy tọa độ nếu có
        coords = BRANCH_COORDINATES.get(code)
        lat, lng = (coords[0], coords[1]) if coords else (None, None)
        
        if not branch:
            branch = Branch(
                branch_code=code, 
                name=f"Chi nhánh {code}" if code.startswith("B") else code,
                gps_lat=lat,
                gps_lng=lng
            )
            db.add(branch)
            logger.info(f"[MASTER] Created Branch: {code}")
        else:
            # Cập nhật tọa độ nếu chưa có hoặc thay đổi
            update = False
            if lat is not None and (branch.gps_lat != lat or branch.gps_lng != lng):
                branch.gps_lat = lat
                branch.gps_lng = lng
                update = True
                logger.info(f"[MASTER] Updated coordinates for Branch: {code}")
            
    db.commit()
    logger.info("Master Data synchronization finished.")