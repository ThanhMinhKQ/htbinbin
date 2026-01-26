from sqlalchemy.orm import Session
from ..db.models import User, Branch, Department
from ..core.config import logger

def sync_employees_from_source(db: Session, employees_source: list[dict], force_delete: bool = False):
    """
    Đồng bộ nhân viên từ file nguồn vào DB.
    - Cập nhật thông tin cơ bản.
    - Cập nhật trạng thái is_active dựa trên file config.
    """
    logger.info("[SYNC] Bắt đầu quá trình đồng bộ nhân viên...")

    # 1. Cache dữ liệu tham chiếu
    branch_map = {b.branch_code: b.id for b in db.query(Branch).all()}
    department_map = {d.role_code: d.id for d in db.query(Department).all()}
    
    # 2. Lấy danh sách nhân viên hiện có
    existing_users_dict = {user.employee_id: user for user in db.query(User).all()}
    
    updated_count = 0
    created_count = 0

    # 3. Duyệt qua file nguồn (Single Source of Truth)
    for emp in employees_source:
        employee_id = emp.get("employee_id", "").strip()
        if not employee_id:
            continue

        # Lấy thông tin
        branch_code = emp.get("branch")
        role_code = emp.get("role")
        
        # Mặc định là True nếu không khai báo is_active
        is_active_status = emp.get("is_active", True) 

        branch_id = branch_map.get(branch_code)
        department_id = department_map.get(role_code)

        # Skip nếu sai branch/role code (để tránh lỗi DB)
        if not branch_id or not department_id:
            logger.warning(f"[SYNC] Bỏ qua {emp.get('name')} do sai mã Branch/Role")
            continue

        existing_user = existing_users_dict.get(employee_id)
        
        if existing_user:
            # --- CẬP NHẬT USER CŨ ---
            changed = False
            
            # Logic check thay đổi
            if existing_user.employee_code != emp.get("code"): 
                existing_user.employee_code = emp.get("code"); changed = True
            
            if existing_user.name != emp.get("name"): 
                existing_user.name = emp.get("name"); changed = True
            
            if existing_user.main_branch_id != branch_id: 
                existing_user.main_branch_id = branch_id; changed = True
            
            if existing_user.department_id != department_id: 
                existing_user.department_id = department_id; changed = True
            
            if existing_user.shift != emp.get("shift"): 
                existing_user.shift = emp.get("shift"); changed = True
                
            # [MỚI] Cập nhật trạng thái is_active
            if existing_user.is_active != is_active_status:
                existing_user.is_active = is_active_status
                changed = True
                logger.info(f"[SYNC] Thay đổi trạng thái {existing_user.name}: {'Active' if is_active_status else 'Inactive'}")

            # Password
            new_password = emp.get("password")
            if new_password and existing_user.password != new_password:
                existing_user.password = new_password
                changed = True
            
            if changed:
                updated_count += 1
        else:
            # --- TẠO USER MỚI ---
            new_user = User(
                employee_id=employee_id,
                employee_code=emp.get("code"),
                name=emp.get("name"),
                password=emp.get("password", "123456"),
                main_branch_id=branch_id,
                department_id=department_id,
                shift=emp.get("shift"),
                is_active=is_active_status # [MỚI] Set trạng thái ngay khi tạo
            )
            db.add(new_user)
            created_count += 1
            logger.info(f"[SYNC] Thêm mới: {emp.get('name')}")

    db.commit()
    logger.info(f"[SYNC] Hoàn tất. Thêm mới: {created_count}, Cập nhật: {updated_count}.")