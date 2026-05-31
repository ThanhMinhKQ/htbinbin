"""
Nguồn chân lý DUY NHẤT cho phân quyền (access control).

Tách bạch 2 khái niệm:
- access_level: cấp quyền CỐ ĐỊNH (OWNER > ADMIN > MANAGER > STAFF) — quyết định
  "được làm gì". Mọi gate quyền phải đi qua module này.
- code (role_code cũ): vai trò nghiệp vụ (letan/buongphong/ktv/...) — quyết định
  "nghiệp vụ nào áp dụng". KHÔNG dùng access_level để suy ra nghiệp vụ và ngược lại.

Các hàm nhận vào HOẶC session-dict (request.session["user"]) HOẶC User ORM object.
"""
from typing import Union, Optional

# Thứ hạng cấp quyền — số lớn hơn = quyền cao hơn
_RANK = {"STAFF": 0, "MANAGER": 1, "ADMIN": 2, "OWNER": 3}

# Fallback khi chỉ có code/role (session cũ chưa có access_level, hoặc giá trị lạ).
# Bao gồm cả các role "chết" (manager/giamdoc/superadmin/dieuhanh) từng xuất hiện
# trong các hardcoded set cũ, để mọi session cũ vẫn resolve hợp lý.
_LEGACY_ROLE_TO_LEVEL = {
    "boss": "OWNER",
    "giamdoc": "OWNER",
    "admin": "ADMIN",
    "superadmin": "ADMIN",
    "quanly": "MANAGER",
    "manager": "MANAGER",
    "dieuhanh": "MANAGER",
    "letan": "STAFF",
    "buongphong": "STAFF",
    "baove": "STAFF",
    "ktv": "STAFF",
    "khac": "STAFF",
}

_DEFAULT_LEVEL = "STAFF"


def access_level_of(user: Union[dict, object, None]) -> str:
    """
    Trả về access_level chuẩn hoá (OWNER/ADMIN/MANAGER/STAFF) của user.

    Ưu tiên access_level tường minh; nếu không có thì map từ code/role nghiệp vụ.
    Chấp nhận session-dict hoặc User ORM. None → STAFF (an toàn nhất).
    """
    if user is None:
        return _DEFAULT_LEVEL

    # Session-dict (request.session["user"])
    if isinstance(user, dict):
        lvl = (user.get("access_level") or "").upper()
        if lvl in _RANK:
            return lvl
        return _LEGACY_ROLE_TO_LEVEL.get((user.get("role") or "").lower(), _DEFAULT_LEVEL)

    # User ORM object
    dept = getattr(user, "department", None)
    if dept is not None:
        lvl_raw = getattr(dept, "access_level", None)
        if lvl_raw is not None:
            lvl = lvl_raw.value if hasattr(lvl_raw, "value") else str(lvl_raw)
            lvl = lvl.upper()
            if lvl in _RANK:
                return lvl
        code = (getattr(dept, "code", None) or "").lower()
        if code:
            return _LEGACY_ROLE_TO_LEVEL.get(code, _DEFAULT_LEVEL)
    return _DEFAULT_LEVEL


def has_access(user: Union[dict, object, None], min_level: str) -> bool:
    """True nếu cấp quyền của user >= min_level."""
    return _RANK.get(access_level_of(user), 0) >= _RANK.get(min_level.upper(), 99)


def is_owner(user: Union[dict, object, None]) -> bool:
    return access_level_of(user) == "OWNER"


def is_admin(user: Union[dict, object, None]) -> bool:
    """ADMIN trở lên (gồm OWNER)."""
    return has_access(user, "ADMIN")


def is_manager(user: Union[dict, object, None]) -> bool:
    """MANAGER trở lên (gồm ADMIN, OWNER)."""
    return has_access(user, "MANAGER")


def can_view_all_branches(user: Union[dict, object, None]) -> bool:
    """Được xem dữ liệu toàn hệ thống (không bị ghim 1 chi nhánh)."""
    return has_access(user, "MANAGER")


def functional_code(user: Union[dict, object, None]) -> str:
    """
    Vai trò NGHIỆP VỤ (letan/buongphong/ktv/quanly/...), KHÔNG phải cấp quyền.
    Dùng cho các logic đặc thù theo công việc (letan ghim chi nhánh, calendar KTV/QL...).
    """
    if user is None:
        return ""
    if isinstance(user, dict):
        return (user.get("role") or "").lower()
    dept = getattr(user, "department", None)
    if dept is not None:
        return (getattr(dept, "code", None) or "").lower()
    return ""
