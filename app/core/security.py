from fastapi import Request, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Optional
import secrets
import bcrypt

# Import model User để truy vấn
from ..db.models import User, AttendanceLog
from ..db.session import SessionLocal
from .utils import get_current_work_shift
from .config import logger
from .permissions import is_admin

# ====================================================================
# PASSWORD HASHING (bcrypt)
# ====================================================================
# Mật khẩu cũ được lưu plaintext. Để tương thích ngược, verify_password()
# nhận diện cả hash bcrypt lẫn plaintext cũ. Khi user đăng nhập thành công
# bằng mật khẩu plaintext, caller nên gọi hash_password() để nâng cấp
# (rehash-on-login).

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


def is_hashed(value: Optional[str]) -> bool:
    """True nếu chuỗi đã là hash bcrypt (không phải plaintext cũ)."""
    return bool(value) and value.startswith(_BCRYPT_PREFIXES)


def hash_password(plain: str) -> str:
    """Hash mật khẩu bằng bcrypt. bcrypt giới hạn 72 byte nên cắt an toàn."""
    pw_bytes = plain.encode("utf-8")[:72]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, stored: Optional[str]) -> bool:
    """
    So khớp mật khẩu nhập vào với giá trị lưu trong DB.
    - Nếu `stored` là hash bcrypt: dùng bcrypt.checkpw (constant-time).
    - Nếu `stored` là plaintext cũ: so sánh constant-time để tránh timing attack.
    """
    if not stored or plain is None:
        return False
    if is_hashed(stored):
        try:
            return bcrypt.checkpw(plain.encode("utf-8")[:72], stored.encode("utf-8"))
        except (ValueError, TypeError):
            return False
    # Plaintext cũ — so sánh constant-time
    return secrets.compare_digest(plain, stored)


# Hash cố định dùng cho dummy-verify (chống timing attack khi user không tồn tại).
# Tính 1 lần lúc import để mọi lời gọi verify đều tốn thời gian tương đương.
_DUMMY_HASH = bcrypt.hashpw(b"dummy_password_for_timing", bcrypt.gensalt()).decode("utf-8")


def dummy_verify() -> None:
    """
    Chạy một phép bcrypt.checkpw giả để cân bằng thời gian phản hồi.
    Gọi khi user không tồn tại, tránh lộ thông tin qua timing.
    """
    try:
        bcrypt.checkpw(b"dummy_password_for_timing", _DUMMY_HASH.encode("utf-8"))
    except (ValueError, TypeError):
        pass

def get_branch_code(branch_value: Any) -> Optional[str]:
    """
    Chuẩn hóa dữ liệu chi nhánh về branch_code dạng string để dùng an toàn
    trong session, template, và JSON response.
    """
    if isinstance(branch_value, str):
        return branch_value
    return getattr(branch_value, "branch_code", None)

# === HÀM MỚI ĐƯỢC CHUYỂN VÀO ===
def get_active_branch(request: Request, db: Session, user_data: dict) -> Optional[str]:
    """
    Xác định chi nhánh hoạt động của người dùng theo thứ tự ưu tiên:
    1. Chi nhánh từ session (vừa quét GPS trong phiên này).
    2. Chi nhánh hoạt động cuối cùng đã lưu trong DB.
    3. Chi nhánh mặc định của user (fallback).
    """
    # 1. Lấy từ session (ưu tiên cao nhất)
    active_branch = get_branch_code(request.session.get("active_branch"))
    if active_branch:
        return active_branch

    # 2. Lấy từ DB
    user_from_db = db.query(User).filter(User.id == user_data.get("id")).first()
    if user_from_db and user_from_db.last_active_branch:
        return get_branch_code(user_from_db.last_active_branch)

    # 3. Lấy từ chi nhánh mặc định trong session
    return get_branch_code(user_data.get("branch"))

def require_checked_in_user(request: Request):
    user = request.session.get("user")
    if not user:
        return False

    # Admin và Boss luôn được truy cập nếu đã đăng nhập
    if is_admin(user):
        return True

    # Lấy ngày làm việc hiện tại, xử lý cả trường hợp trước 7h sáng
    work_date, _ = get_current_work_shift()
    
    with SessionLocal() as db:
        try:
            # === THAY ĐỔI CHÍNH Ở ĐÂY ===
            # Query theo user_id và work_date
            log = db.query(AttendanceLog).filter(
                AttendanceLog.user_id == user["id"],
                AttendanceLog.work_date == work_date,
                AttendanceLog.checked_in == True
            ).first()

            # Cho phép vào nếu có log đã check-in trong DB hoặc vừa quét QR xong
            if log or request.session.get("after_checkin") == "choose_function":
                return True
        except Exception as e:
            logger.error(f"Lỗi khi kiểm tra trạng thái đăng nhập trong middleware: {e}", exc_info=True)
            return False # An toàn là trên hết, nếu lỗi DB thì không cho vào

    return False

# --- CSRF Token Management ---
def generate_csrf_token():
    return secrets.token_urlsafe(32)

def get_csrf_token(request: Request):
    token = request.session.get("csrf_token")
    if not token:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
    return token

def validate_csrf(request: Request):
    token = request.headers.get("X-CSRF-Token") or request.query_params.get("csrf_token")
    session_token = request.session.get("csrf_token")
    if not session_token or token != session_token:
        raise HTTPException(status_code=403, detail="CSRF token không hợp lệ")
