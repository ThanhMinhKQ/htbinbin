from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Union

from pydantic import BaseModel
from sqlalchemy.orm import Session

from models import Task as TaskModel
from database import Base, engine

# Định nghĩa múi giờ Việt Nam (UTC+7) để sử dụng nhất quán
VN_TZ = timezone(timedelta(hours=7))


# === Khởi tạo DB (tạo bảng nếu chưa có) ===
def init_db() -> None:
    """Tạo bảng trong database nếu chưa tồn tại."""
    Base.metadata.create_all(bind=engine)


# === Lấy thống kê công việc ===
def get_task_stats(
    db: Session, role: str, chi_nhanh: Optional[str] = None, user: Optional[str] = None
) -> Dict[str, int]:
    """
    Lấy thống kê số lượng công việc theo trạng thái, tuỳ thuộc vào role.
    """
    query = db.query(TaskModel)

    if role == "letan" and chi_nhanh:
        query = query.filter(
            TaskModel.chi_nhanh == chi_nhanh,
            TaskModel.trang_thai != "Đã xoá"
        )
    elif role == "ktv":
        query = query.filter(TaskModel.trang_thai != "Đã xoá")
    elif role == "quanly":
        pass  # full access

    stats = {"total": 0, "pending": 0, "completed": 0, "overdue": 0}

    for task in query.yield_per(50):  # tránh load toàn bộ vào RAM nếu bảng lớn
        stats["total"] += 1
        if task.trang_thai == "Đang chờ":
            stats["pending"] += 1
        elif task.trang_thai == "Hoàn thành":
            stats["completed"] += 1
        elif task.trang_thai == "Quá hạn":
            stats["overdue"] += 1

    return stats


# === Mô hình công việc cho JSON/UI ===
class Task(BaseModel):
    id: int
    chi_nhanh: str
    phong: str
    mo_ta: str
    ngay_tao: str
    han_hoan_thanh: Union[str, datetime]
    trang_thai: str
    nguoi_tao: str
    nguoi_thuc_hien: str = ""
    ngay_hoan_thanh: str = ""
    ghi_chu: str = ""


# === CÁC HÀM XỬ LÝ THỜI GIAN ĐÃ SỬA LẠI ===

def format_datetime_display(value: Optional[datetime], with_time: bool = False) -> str:
    """
    Định dạng đối tượng datetime để hiển thị ra UI theo giờ Việt Nam.
    Hàm này sẽ chuyển đổi datetime về múi giờ Việt Nam trước khi định dạng.
    """
    if not isinstance(value, datetime):
        return ""

    # Nếu datetime từ DB không có múi giờ (naive), giả định nó là UTC
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    # Chuyển đổi datetime về múi giờ Việt Nam để hiển thị chính xác
    dt_vn = value.astimezone(VN_TZ)
    
    # Định dạng theo yêu cầu
    if with_time:
        return dt_vn.strftime("%d/%m/%Y %H:%M")
    else:
        return dt_vn.strftime("%d/%m/%Y")


def parse_datetime_input(dt_str: str) -> Optional[datetime]:
    """
    Phân tích chuỗi ngày tháng từ form (ví dụ: '2025-12-31' hoặc '31/12/2025')
    và trả về một đối tượng datetime có múi giờ, là thời điểm cuối ngày hôm đó theo giờ Việt Nam.
    """
    if not dt_str:
        return None
    
    dt_naive = None
    # Thử các định dạng phổ biến từ input date và flatpickr
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            dt_naive = datetime.strptime(dt_str, fmt)
            break
        except ValueError:
            continue
            
    if dt_naive is None:
        raise ValueError(f"❌ Chuỗi ngày '{dt_str}' không khớp định dạng YYYY-MM-DD hoặc DD/MM/YYYY.")

    # Mặc định hạn chót là cuối ngày (23:59:59) để bao gồm cả ngày đó.
    dt_naive = dt_naive.replace(hour=23, minute=59, second=59, microsecond=0)
    
    # Gán múi giờ Việt Nam cho đối tượng datetime để nó trở thành "timezone-aware"
    return dt_naive.replace(tzinfo=VN_TZ)


def is_overdue(task: Union[Task, TaskModel]) -> bool:
    """
    Kiểm tra xem công việc có quá hạn không bằng cách so sánh với thời gian hiện tại
    ở múi giờ Việt Nam.
    """
    if getattr(task, "trang_thai", "") in ["Hoàn thành", "Đã xoá"]:
        return False

    han = getattr(task, "han_hoan_thanh", None)
    if not han:
        return False

    if not isinstance(han, datetime):
        return False

    # Lấy thời gian hiện tại có nhận biết múi giờ Việt Nam
    now_vn = datetime.now(VN_TZ)

    # Đảm bảo `han` là timezone-aware trước khi so sánh.
    if han.tzinfo is None:
        han = han.replace(tzinfo=timezone.utc)

    return han < now_vn