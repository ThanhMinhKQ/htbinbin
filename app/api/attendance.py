from fastapi import APIRouter, Request, Depends, BackgroundTasks, HTTPException, Form, Query, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
import os
import re
import html
import uuid
import shutil
from typing import Optional, List
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urlparse
from pydantic import BaseModel # <-- THÊM IMPORT
from math import sin, cos, sqrt, atan2, radians # <-- THÊM IMPORT

from ..db.session import get_db
from ..db.models import (
    User, AttendanceRecord, ServiceRecord, Branch, Department, AttendanceLog,
    ShiftNotification, ShiftNotificationRead,
)
from ..core.security import (
    get_active_branch,
    get_branch_code,
    get_csrf_token,
    require_checked_in_user,
    validate_csrf,
)
from ..core.utils import get_current_work_shift, VN_TZ, format_datetime_display, _get_log_shift_for_user
# SỬA DÒNG DƯỚI ĐỂ IMPORT TỌA ĐỘ
from ..core.config import logger, ROLE_MAP, BRANCHES, BRANCH_COORDINATES
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import cast, Date, select, or_, and_, func
from sqlalchemy.orm import joinedload

from fastapi.templating import Jinja2Templates
from app.services.storage import validate_upload, upload_to_supabase

router = APIRouter()

# Xác định đường dẫn tuyệt đối đến thư mục gốc của project 'app'
APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Tạo đường dẫn tuyệt đối đến thư mục templates
templates = Jinja2Templates(directory=os.path.join(APP_ROOT, "templates"))

# === BẮT ĐẦU CODE THÊM MỚI ===

def haversine(lat1, lon1, lat2, lon2):
    """
    Tính khoảng cách (km) giữa 2 điểm GPS bằng công thức Haversine.
    """
    R = 6371  # Bán kính Trái Đất (km)
    
    # Chuyển đổi độ sang radians
    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)
    
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    
    # Công thức Haversine
    a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    
    distance = R * c
    return distance

# Model Pydantic để nhận dữ liệu từ frontend
class GpsPayload(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None

class BranchSelectPayload(BaseModel):
    branch: str

class ShiftNotificationPayload(BaseModel):
    title: str
    body: str
    priority: str = "normal"
    is_active: bool = True
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
    schedule_shift: Optional[str] = None
    min_read_seconds: int = 5
    audience_roles: List[str] = []
    branch_ids: List[int] = []

class ShiftNotificationBulkPayload(BaseModel):
    ids: List[int] = []

# === KẾT THÚC CODE THÊM MỚI ===

_NOTIFICATION_ALLOWED_TAGS = {
    "p", "br", "div", "span", "strong", "b", "em", "i", "u", "s",
    "ul", "ol", "li", "blockquote", "a", "img", "h1", "h2", "h3",
    "pre", "code", "font", "svg", "path",
}
_NOTIFICATION_VOID_TAGS = {"br", "img"}
_NOTIFICATION_DROP_TAGS = {"script", "style", "iframe", "object", "embed"}

def _notification_url_allowed(value: str, image: bool = False) -> bool:
    val = (value or "").strip()
    if val.startswith("/uploads/"):
        return True
    parsed = urlparse(val)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return True
    if not image and parsed.scheme in {"mailto", "tel"}:
        return True
    if image and val.startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/gif;base64,", "data:image/webp;base64,")):
        return True
    return False

class _NotificationHtmlSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.drop_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _NOTIFICATION_DROP_TAGS:
            self.drop_depth += 1
            return
        if self.drop_depth:
            return
        if tag not in _NOTIFICATION_ALLOWED_TAGS:
            return
        clean_attrs = []
        attr_map = {str(k).lower(): str(v or "") for k, v in attrs}
        if tag == "a":
            href = attr_map.get("href", "").strip()
            if _notification_url_allowed(href):
                clean_attrs.extend([
                    ("href", href),
                    ("target", "_blank"),
                    ("rel", "noopener noreferrer"),
                ])
                if "class" in attr_map:
                    clean_attrs.append(("class", attr_map["class"]))
                if "download" in attr_map:
                    clean_attrs.append(("download", attr_map["download"]))
        elif tag == "img":
            src = attr_map.get("src", "").strip()
            if not _notification_url_allowed(src, image=True):
                return
            clean_attrs.extend([
                ("src", src),
                ("alt", attr_map.get("alt", "")[:180]),
                ("loading", "lazy"),
                ("referrerpolicy", "no-referrer"),
            ])
            if "class" in attr_map:
                clean_attrs.append(("class", attr_map["class"]))
            if "style" in attr_map:
                clean_attrs.append(("style", attr_map["style"]))
        elif tag == "font":
            color = attr_map.get("color", "").strip()[:32]
            if re.fullmatch(r"#[0-9a-fA-F]{3,8}|[a-zA-Z]+", color or ""):
                clean_attrs.append(("color", color))
        elif tag == "svg":
            clean_attrs.extend([
                ("viewbox", attr_map.get("viewbox", "0 0 24 24")),
                ("fill", attr_map.get("fill", "none")),
                ("stroke", attr_map.get("stroke", "currentColor")),
                ("stroke-width", attr_map.get("stroke-width", "2")),
            ])
            if "class" in attr_map:
                clean_attrs.append(("class", attr_map["class"]))
        elif tag == "path":
            if "d" in attr_map:
                clean_attrs.append(("d", attr_map["d"]))

        if tag in {"p", "div", "h1", "h2", "h3", "blockquote"}:
            style = attr_map.get("style", "")
            align_match = re.search(r"text-align\s*:\s*(left|center|right|justify)", style, flags=re.IGNORECASE)
            if align_match:
                clean_attrs.append(("style", f"text-align: {align_match.group(1).lower()}"))
            # Allow text color/background color styles commonly used in rich editor
            color_match = re.search(r"color\s*:\s*([^;]+)", style, flags=re.IGNORECASE)
            bg_match = re.search(r"background-color\s*:\s*([^;]+)", style, flags=re.IGNORECASE)
            existing_styles = []
            if align_match:
                existing_styles.append(f"text-align: {align_match.group(1).lower()}")
            if color_match:
                existing_styles.append(f"color: {color_match.group(1).strip()}")
            if bg_match:
                existing_styles.append(f"background-color: {bg_match.group(1).strip()}")
            if existing_styles:
                clean_attrs.append(("style", "; ".join(existing_styles)))

        rendered_attrs = "".join(
            f' {name}="{html.escape(value, quote=True)}"'
            for name, value in clean_attrs
            if value
        )
        self.parts.append(f"<{tag}{rendered_attrs}>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _NOTIFICATION_DROP_TAGS and self.drop_depth:
            self.drop_depth -= 1
            return
        if self.drop_depth:
            return
        if tag in _NOTIFICATION_ALLOWED_TAGS and tag not in _NOTIFICATION_VOID_TAGS:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self.drop_depth:
            return
        self.parts.append(html.escape(data))

    def handle_entityref(self, name):
        if self.drop_depth:
            return
        self.parts.append(f"&{name};")

    def handle_charref(self, name):
        if self.drop_depth:
            return
        self.parts.append(f"&#{name};")

def _sanitize_notification_body(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if not re.search(r"</?[a-zA-Z][\s\S]*>", raw):
        return html.escape(raw).replace("\n", "<br>")
    sanitizer = _NotificationHtmlSanitizer()
    sanitizer.feed(raw)
    sanitizer.close()
    cleaned = "".join(sanitizer.parts).strip()
    if not cleaned and raw:
        cleaned = html.escape(raw).replace("\n", "<br>")
    return cleaned

def _notification_body_has_content(value: str) -> bool:
    if not value:
        return False
    text = re.sub(r"<[^>]+>", "", value).replace("&nbsp;", " ").strip()
    return bool(text or re.search(r"<img\b", value, flags=re.IGNORECASE))

_NOTIFICATION_MANAGE_ROLES = {"admin", "boss", "quanly", "manager"}
_NOTIFICATION_VIEW_ROLES = _NOTIFICATION_MANAGE_ROLES | {"letan"}

def _notification_can_manage(user: Optional[dict]) -> bool:
    return (user or {}).get("role", "").lower() in _NOTIFICATION_MANAGE_ROLES

def _notification_branch_sort_key(branch: Branch):
    code = (branch.branch_code or "").strip()
    name = (branch.name or "").strip()
    number_match = re.search(r"\d+", code) or re.search(r"\d+", name)
    if number_match:
        return (0, int(number_match.group()), code.lower(), name.lower())
    return (1, code.lower(), name.lower())

def _notification_admin_required(request: Request):
    user = request.session.get("user")
    if not _notification_can_manage(user):
        raise HTTPException(status_code=403, detail="Không có quyền quản lý thông báo.")
    return user

def _notification_view_required(request: Request):
    user = request.session.get("user")
    role = (user or {}).get("role", "").lower()
    if role not in _NOTIFICATION_VIEW_ROLES:
        raise HTTPException(status_code=403, detail="Không có quyền xem thông báo.")
    return user

def _parse_notification_dt(value: Optional[str]):
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Thời gian thông báo không hợp lệ.") from exc
    if dt.tzinfo is None:
        return VN_TZ.localize(dt)
    return dt.astimezone(VN_TZ)

def _notification_shift_context(request: Request, db: Session):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Phiên làm việc hết hạn.")
    work_date, shift_name = get_current_work_shift()
    shift = _get_log_shift_for_user((user_data.get("role") or "").lower(), shift_name)
    attendance_log = db.query(AttendanceLog).filter(
        AttendanceLog.user_id == user_data["id"],
        AttendanceLog.work_date == work_date,
        AttendanceLog.shift == shift,
        AttendanceLog.checked_in == True,
    ).first()
    return user_data, work_date, shift, attendance_log

def _iso(dt):
    return dt.isoformat() if dt else None

def _notification_as_vn_datetime(value: Optional[datetime]):
    if not value:
        return None
    if value.tzinfo is None:
        value = VN_TZ.localize(value)
    return value.astimezone(VN_TZ)

def _notification_as_vn_date(value: Optional[datetime]):
    value = _notification_as_vn_datetime(value)
    return value.date() if value else None

def _shift_notification_is_active_now(item: ShiftNotification, now_vn: datetime) -> bool:
    starts_at = _notification_as_vn_datetime(item.starts_at)
    ends_at = _notification_as_vn_datetime(item.ends_at)
    return bool(
        item.is_active
        and (starts_at is None or starts_at <= now_vn)
        and (ends_at is None or ends_at >= now_vn)
    )

def _shift_notification_status(item: ShiftNotification, now_vn: datetime) -> str:
    starts_at = _notification_as_vn_datetime(item.starts_at)
    ends_at = _notification_as_vn_datetime(item.ends_at)
    if not item.is_active:
        return "inactive"
    if ends_at and ends_at < now_vn:
        return "expired"
    if starts_at and starts_at > now_vn:
        return "scheduled"
    return "active"

def _serialize_shift_notification(
    item: ShiftNotification,
    read_ids: Optional[set[int]] = None,
    read_counts: Optional[dict[int, int]] = None,
):
    return {
        "id": item.id,
        "title": item.title,
        "body": item.body,
        "priority": item.priority,
        "is_active": item.is_active,
        "starts_at": _iso(item.starts_at),
        "ends_at": _iso(item.ends_at),
        "schedule_shift": item.schedule_shift,
        "min_read_seconds": item.min_read_seconds or 5,
        "audience_roles": item.audience_roles or [],
        "branch_ids": item.branch_ids or [],
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
        "status": _shift_notification_status(item, datetime.now(VN_TZ)),
        "read_count": int((read_counts or {}).get(item.id, 0)),
        "read": item.id in read_ids if read_ids is not None else False,
    }

def _notification_matches_user(item: ShiftNotification, user_data: dict, branch_id: Optional[int], shift: str) -> bool:
    if item.schedule_shift and item.schedule_shift != "ALL" and item.schedule_shift != shift:
        return False
    roles = item.audience_roles or []
    if roles and (user_data.get("role") or "").lower() not in {str(r).lower() for r in roles}:
        return False
    branch_ids = item.branch_ids or []
    if branch_ids and branch_id not in {int(b) for b in branch_ids if str(b).isdigit()}:
        return False
    return True

def _notification_session_read_key(user_data: dict, work_date, shift: str) -> str:
    return f"shift_notification_reads:{user_data.get('id')}:{work_date.isoformat()}:{shift}"

def _notification_session_read_ids(request: Request, user_data: dict, work_date, shift: str) -> set[int]:
    raw_ids = request.session.get(_notification_session_read_key(user_data, work_date, shift), [])
    return {int(item_id) for item_id in raw_ids if str(item_id).isdigit()}

def _mark_notification_session_read(request: Request, user_data: dict, work_date, shift: str, notification_id: int) -> set[int]:
    key = _notification_session_read_key(user_data, work_date, shift)
    read_ids = _notification_session_read_ids(request, user_data, work_date, shift)
    read_ids.add(int(notification_id))
    request.session[key] = sorted(read_ids)
    return read_ids

@router.get("/", response_class=HTMLResponse)
def attendance_ui(request: Request, db: Session = Depends(get_db)):
    user_data = request.session.get("user") or request.session.get("pending_user")
    if not user_data:
        return RedirectResponse("/login", status_code=303)
    
    # ... (Logic lấy active_branch giữ nguyên) ...
    active_branch = get_active_branch(request, db, user_data) or ""
    
    csrf_token = get_csrf_token(request)

    response = templates.TemplateResponse(request, "attendance.html", {
        "request": request,
        "branch_id": active_branch, 
        "csrf_token": csrf_token,
        "user": user_data,
        "login_code": user_data.get("code", ""),
        "role": user_data.get("role", ""),
        "token": request.query_params.get("token", ""),
    })
    
    # Các header chặn cache này vẫn giữ nguyên là rất tốt
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@router.get("/notifications", response_class=HTMLResponse)
def attendance_notifications_page(request: Request, db: Session = Depends(get_db)):
    user_data = _notification_view_required(request)
    can_manage = _notification_can_manage(user_data)
    if can_manage:
        branches = sorted(db.query(Branch).all(), key=_notification_branch_sort_key)
    else:
        active_branch_code = get_active_branch(request, db, user_data) or user_data.get("branch")
        branches = []
        if active_branch_code:
            branch = db.query(Branch).filter(Branch.branch_code == active_branch_code).first()
            if branch:
                branches = [branch]
    response = templates.TemplateResponse(request, "attendance_notifications.html", {
        "request": request,
        "user": user_data,
        "active_page": "shift-notifications",
        "branches": branches,
        "can_manage_shift_notifications": can_manage,
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response

@router.get("/api/shift-notifications", response_class=JSONResponse)
def list_shift_notifications(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=5, le=100),
    q: str = "",
    status: str = "",
    priority: str = "",
    shift: str = "",
    role: str = "",
    branch_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    user_data = _notification_view_required(request)
    can_manage = _notification_can_manage(user_data)
    active_branch = None
    current_shift = ""
    if not can_manage:
        active_branch_code = get_active_branch(request, db, user_data) or user_data.get("branch")
        active_branch = db.query(Branch).filter(Branch.branch_code == active_branch_code).first() if active_branch_code else None
        _work_date, shift_name = get_current_work_shift()
        current_shift = _get_log_shift_for_user((user_data.get("role") or "").lower(), shift_name)
    now_vn = datetime.now(VN_TZ)
    today = now_vn.date()
    items = db.query(ShiftNotification).filter(
        ShiftNotification.deleted_at.is_(None)
    ).order_by(ShiftNotification.created_at.desc(), ShiftNotification.id.desc()).all()
    if not can_manage:
        items = [
            item for item in items
            if item.is_active
            and _notification_matches_user(item, user_data, active_branch.id if active_branch else None, current_shift)
        ]
    read_counts = {
        notification_id: int(count)
        for notification_id, count in db.query(
            ShiftNotificationRead.notification_id,
            func.count(ShiftNotificationRead.id),
        ).join(ShiftNotification, ShiftNotification.id == ShiftNotificationRead.notification_id)
        .filter(ShiftNotification.deleted_at.is_(None))
        .group_by(ShiftNotificationRead.notification_id)
        .all()
    }

    stats = {
        "total": len(items),
        "active": sum(1 for item in items if _shift_notification_is_active_now(item, now_vn)),
        "expired": sum(
            1 for item in items
            if _notification_as_vn_datetime(item.ends_at) and _notification_as_vn_datetime(item.ends_at) < now_vn
        ),
        "today": sum(1 for item in items if _notification_as_vn_date(item.created_at) == today),
        "acknowledged": sum(read_counts.get(item.id, 0) for item in items),
    }

    q_norm = (q or "").strip().lower()
    status_norm = (status or "").strip().lower()
    priority_norm = (priority or "").strip().lower()
    shift_norm = (shift or "").strip()
    role_norm = (role or "").strip().lower()

    def matches(item: ShiftNotification) -> bool:
        if q_norm and q_norm not in (item.title or "").lower() and q_norm not in (item.body or "").lower():
            return False
        if priority_norm and (item.priority or "").lower() != priority_norm:
            return False
        if shift_norm and (item.schedule_shift or "") != shift_norm:
            return False
        if role_norm:
            roles = {str(r).lower() for r in (item.audience_roles or [])}
            if roles and role_norm not in roles:
                return False
        if branch_id:
            branch_ids = {int(b) for b in (item.branch_ids or []) if str(b).isdigit()}
            if branch_ids and branch_id not in branch_ids:
                return False
        if status_norm:
            current_status = _shift_notification_status(item, now_vn)
            if status_norm == "today":
                return _notification_as_vn_date(item.created_at) == today
            if status_norm == "expired":
                ends_at = _notification_as_vn_datetime(item.ends_at)
                return bool(ends_at and ends_at < now_vn)
            if current_status != status_norm:
                return False
        return True

    filtered_items = [item for item in items if matches(item)]
    total = len(filtered_items)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    paged_items = filtered_items[start:start + per_page]
    return {
        "items": [_serialize_shift_notification(item, read_counts=read_counts) for item in paged_items],
        "stats": stats,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }

@router.post("/api/shift-notifications", response_class=JSONResponse)
def create_shift_notification(payload: ShiftNotificationPayload, request: Request, db: Session = Depends(get_db)):
    user_data = _notification_admin_required(request)
    title = payload.title.strip()
    body = _sanitize_notification_body(payload.body)
    if not title or not _notification_body_has_content(body):
        raise HTTPException(status_code=400, detail="Tiêu đề và nội dung là bắt buộc.")
    item = ShiftNotification(
        title=title,
        body=body,
        priority=(payload.priority or "normal").strip() or "normal",
        is_active=payload.is_active,
        starts_at=_parse_notification_dt(payload.starts_at),
        ends_at=_parse_notification_dt(payload.ends_at),
        schedule_shift=(payload.schedule_shift or None),
        min_read_seconds=max(1, int(payload.min_read_seconds or 5)),
        audience_roles=[r.lower() for r in (payload.audience_roles or []) if r],
        branch_ids=[int(b) for b in (payload.branch_ids or [])],
        created_by_id=user_data.get("id"),
        updated_by_id=user_data.get("id"),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"status": "success", "item": _serialize_shift_notification(item)}

@router.put("/api/shift-notifications/{notification_id}", response_class=JSONResponse)
def update_shift_notification(notification_id: int, payload: ShiftNotificationPayload, request: Request, db: Session = Depends(get_db)):
    user_data = _notification_admin_required(request)
    item = db.query(ShiftNotification).filter(
        ShiftNotification.id == notification_id,
        ShiftNotification.deleted_at.is_(None),
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy thông báo.")
    title = payload.title.strip()
    body = _sanitize_notification_body(payload.body)
    if not title or not _notification_body_has_content(body):
        raise HTTPException(status_code=400, detail="Tiêu đề và nội dung là bắt buộc.")
    item.title = title
    item.body = body
    item.priority = (payload.priority or "normal").strip() or "normal"
    item.is_active = payload.is_active
    item.starts_at = _parse_notification_dt(payload.starts_at)
    item.ends_at = _parse_notification_dt(payload.ends_at)
    item.schedule_shift = payload.schedule_shift or None
    item.min_read_seconds = max(1, int(payload.min_read_seconds or 5))
    item.audience_roles = [r.lower() for r in (payload.audience_roles or []) if r]
    item.branch_ids = [int(b) for b in (payload.branch_ids or [])]
    item.updated_by_id = user_data.get("id")
    item.updated_at = datetime.now(VN_TZ)
    db.commit()
    db.refresh(item)
    return {"status": "success", "item": _serialize_shift_notification(item)}

@router.delete("/api/shift-notifications/{notification_id}", response_class=JSONResponse)
def delete_shift_notification(notification_id: int, request: Request, db: Session = Depends(get_db)):
    user_data = _notification_admin_required(request)
    item = db.query(ShiftNotification).filter(
        ShiftNotification.id == notification_id,
        ShiftNotification.deleted_at.is_(None),
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy thông báo.")
    item.deleted_at = datetime.now(VN_TZ)
    item.updated_by_id = user_data.get("id")
    db.commit()
    return {"status": "success"}

@router.post("/api/shift-notifications/bulk-delete", response_class=JSONResponse)
def bulk_delete_shift_notifications(payload: ShiftNotificationBulkPayload, request: Request, db: Session = Depends(get_db)):
    user_data = _notification_admin_required(request)
    ids = sorted({int(item_id) for item_id in (payload.ids or []) if item_id})
    if not ids:
        raise HTTPException(status_code=400, detail="Chưa chọn thông báo để xoá.")
    items = db.query(ShiftNotification).filter(
        ShiftNotification.id.in_(ids),
        ShiftNotification.deleted_at.is_(None),
    ).all()
    now_vn = datetime.now(VN_TZ)
    for item in items:
        item.deleted_at = now_vn
        item.updated_by_id = user_data.get("id")
    db.commit()
    return {"status": "success", "deleted": len(items)}

@router.post("/api/shift-notifications/upload", response_class=JSONResponse)
async def upload_shift_notification_file(
    request: Request,
    file: UploadFile = File(...),
):
    _notification_admin_required(request)

    content_length = request.headers.get("content-length")
    validate_upload(file, int(content_length) if content_length else None)

    res = await upload_to_supabase(file)
    return {
        "status": "success",
        **res
    }

@router.get("/api/shift-notifications/pending", response_class=JSONResponse)
def pending_shift_notifications(request: Request, db: Session = Depends(get_db)):
    user_data, work_date, shift, _attendance_log = _notification_shift_context(request, db)
    active_branch_code = get_active_branch(request, db, user_data) or user_data.get("branch")
    active_branch = db.query(Branch).filter(Branch.branch_code == active_branch_code).first() if active_branch_code else None
    now_vn = datetime.now(VN_TZ)
    read_ids = _notification_session_read_ids(request, user_data, work_date, shift)
    candidates = db.query(ShiftNotification).filter(
        ShiftNotification.deleted_at.is_(None),
        ShiftNotification.is_active == True,
        or_(ShiftNotification.starts_at.is_(None), ShiftNotification.starts_at <= now_vn),
        or_(ShiftNotification.ends_at.is_(None), ShiftNotification.ends_at >= now_vn),
    ).order_by(ShiftNotification.priority.desc(), ShiftNotification.created_at.asc()).all()
    pending = [
        item for item in candidates
        if item.id not in read_ids and _notification_matches_user(item, user_data, active_branch.id if active_branch else None, shift)
    ]
    return {
        "work_date": work_date.isoformat(),
        "shift": shift,
        "items": [_serialize_shift_notification(item, read_ids) for item in pending],
    }

@router.post("/api/shift-notifications/{notification_id}/ack", response_class=JSONResponse)
def ack_shift_notification(notification_id: int, request: Request, db: Session = Depends(get_db)):
    user_data, work_date, shift, attendance_log = _notification_shift_context(request, db)
    item = db.query(ShiftNotification).filter(
        ShiftNotification.id == notification_id,
        ShiftNotification.deleted_at.is_(None),
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy thông báo.")
    _mark_notification_session_read(request, user_data, work_date, shift, item.id)
    existing = db.query(ShiftNotificationRead).filter(
        ShiftNotificationRead.notification_id == item.id,
        ShiftNotificationRead.user_id == user_data["id"],
        ShiftNotificationRead.work_date == work_date,
        ShiftNotificationRead.shift == shift,
    ).first()
    if existing:
        return {"status": "success", "already_read": True}
    db.add(ShiftNotificationRead(
        notification_id=item.id,
        user_id=user_data["id"],
        attendance_log_id=attendance_log.id if attendance_log else None,
        work_date=work_date,
        shift=shift,
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return {"status": "success"}

# === API DETECT-BRANCH ĐÃ SỬA LẠI HOÀN CHỈNH ===
@router.post("/api/detect-branch") # <-- SỬA TỪ @app VÀ BỎ /attendance
async def detect_branch(
    request: Request,
    payload: GpsPayload, # <-- Dùng Pydantic model
    db: Session = Depends(get_db)
):
    special_roles = ["quanly", "ktv", "boss", "admin"]

    user_data = request.session.get("user") or request.session.get("pending_user")
    user_in_db = None
    if user_data:
        # TỐI ƯU: Load sẵn main_branch để dùng
        user_in_db = db.query(User).options(
            joinedload(User.main_branch),
            joinedload(User.last_active_branch)
        ).filter(User.employee_code == user_data["code"]).first()

    # ===============================
    # 1. Role đặc biệt → bỏ qua GPS
    # ===============================
    if user_data and user_data.get("role") in special_roles:
        if user_in_db and user_in_db.main_branch:
            # SỬA LỖI LOGIC: Dùng main_branch.branch_code
            main_branch_code = user_in_db.main_branch.branch_code
            request.session["active_branch"] = main_branch_code
            user_in_db.last_active_branch = user_in_db.main_branch
            db.commit()
            return {"branch": main_branch_code, "distance_km": 0}

        return JSONResponse(
            {"error": "Không thể lấy chi nhánh chính. Vui lòng liên hệ quản trị."},
            status_code=400,
        )

    # ===============================
    # 2. Role thường → dùng GPS
    # ===============================
    lat, lng = payload.lat, payload.lng # <-- Lấy từ payload
    if lat is None or lng is None:
        # Nếu không có GPS, thử fallback về chi nhánh đã lưu
        if user_in_db and user_in_db.last_active_branch:
             branch_code = get_branch_code(user_in_db.last_active_branch)
             if branch_code:
                 request.session["active_branch"] = branch_code
                 return {"branch": branch_code, "distance_km": 0}
        
        # Nếu không có gì cả, báo lỗi
        return JSONResponse(
            {"error": "Bạn vui lòng mở định vị (GPS) trên điện thoại để lấy vị trí."},
            status_code=400,
        )

    # Tìm chi nhánh trong bán kính 200m — đọc từ DB thay vì BRANCH_COORDINATES hardcode
    nearby_branches = []
    all_branches = db.query(Branch).filter(
        Branch.gps_lat.isnot(None),
        Branch.gps_lng.isnot(None)
    ).all()
    for branch_obj in all_branches:
        dist = haversine(lat, lng, float(branch_obj.gps_lat), float(branch_obj.gps_lng))
        if dist <= 0.2:
            nearby_branches.append((branch_obj.branch_code, dist))

    if not nearby_branches:
        return JSONResponse(
            {"error": "Bạn đang ở quá xa khách sạn (ngoài 200m). Vui lòng điểm danh tại khách sạn."},
            status_code=403,
        )

    if len(nearby_branches) > 1:
        choices = [
            {"branch": b, "distance_km": round(d, 3)}
            for b, d in sorted(nearby_branches, key=lambda x: x[1])
        ]
        return {"choices": choices}

    chosen_branch, min_distance = nearby_branches[0]

    request.session["active_branch"] = chosen_branch
    if user_in_db:
        branch_obj = db.query(Branch).filter(Branch.branch_code == chosen_branch).first()
        if branch_obj:
            user_in_db.last_active_branch = branch_obj
            db.commit()

    return {"branch": chosen_branch, "distance_km": round(min_distance, 3)}

# === API SELECT-BRANCH BỊ THIẾU ===
@router.post("/api/select-branch")
async def select_branch(
    payload: BranchSelectPayload,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    API được gọi khi Lễ tân tự chọn 1 chi nhánh từ popup.
    Lưu lựa chọn này vào session và database.
    """
    user_data = request.session.get("user") or request.session.get("pending_user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Phiên làm việc hết hạn.")

    chosen_branch = payload.branch
    
    # Kiểm tra xem chi nhánh có hợp lệ không
    branch_obj = db.query(Branch).filter(Branch.branch_code == chosen_branch).first()
    if not branch_obj:
        raise HTTPException(status_code=400, detail="Chi nhánh không hợp lệ.")

    # Lưu vào session
    request.session["active_branch"] = chosen_branch
    
    # Lưu vào DB
    user_in_db = db.query(User).filter(User.employee_code == user_data["code"]).first()
    if user_in_db:
        branch_obj = db.query(Branch).filter(Branch.branch_code == chosen_branch).first()
        if branch_obj:
            user_in_db.last_active_branch = branch_obj
            db.commit()

    return {"status": "success", "branch": chosen_branch}


# attendance.py

@router.get("/api/employees/by-branch/{branch_code}", response_class=JSONResponse)
def get_employees_by_branch(branch_code: str, db: Session = Depends(get_db), request: Request = None):
    try:
        session_user = request.session.get("user") or request.session.get("pending_user")
        if not session_user:
             raise HTTPException(status_code=403, detail="Không có quyền truy cập.")

        branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()
        if not branch:
            return JSONResponse(status_code=404, content={"detail": "Không tìm thấy chi nhánh."})

        # === [GOOGLE ENGINEER FIX] ===
        # Lấy tên ca làm việc từ utility (đang trả về "Ca ngày" hoặc "Ca đêm")
        _, shift_name = get_current_work_shift()
        
        # Chuẩn hóa chuỗi về chữ thường để so sánh an toàn
        # convert "Ca ngày" -> "ca ngày", "Ca đêm" -> "ca đêm"
        shift_lower = str(shift_name).lower()

        # Logic: Nếu chuỗi chứa chữ "ngày" hoặc "day" -> Là Ca Sáng (CS)
        # Ngược lại (chứa "đêm", "night",...) -> Là Ca Tối (CT)
        if "ngày" in shift_lower or "day" in shift_lower:
            current_shift_code = "CS"
        else:
            current_shift_code = "CT"

        # Debug (nếu cần): print(f"Shift Name: {shift_name} -> Code: {current_shift_code}")

        # Bắt đầu query cơ bản
        query = db.query(User).options(
            joinedload(User.department),
            joinedload(User.main_branch)
        ).filter(User.is_active == True)

        user_role = session_user.get("role")

        # ================= LOGIC PHÂN QUYỀN HIỂN THỊ =================

        # 1. LỄ TÂN
        if user_role == "letan":
            letan_dept_id = db.query(Department.id).filter(Department.role_code == 'letan').scalar()
            buongphong_dept_id = db.query(Department.id).filter(Department.role_code == 'buongphong').scalar()
            baove_dept_id = db.query(Department.id).filter(Department.role_code == 'baove').scalar()

            filter_logic = or_(
                User.id == session_user["id"],
                and_(
                    User.main_branch_id == branch.id,
                    User.shift == current_shift_code, # Đã sửa đúng: "Ca ngày" -> CS
                    User.department_id.in_([buongphong_dept_id, baove_dept_id])
                )
            )
            query = query.filter(filter_logic)

        # 2. QUẢN LÝ & KTV
        elif user_role in ["quanly", "ktv"]:
            query = query.filter(User.id == session_user["id"])

        # 3. ADMIN & BOSS
        elif user_role in ["admin", "boss"]:
            query = query.filter(User.main_branch_id == branch.id)
        
        # 4. Mặc định
        else:
            query = query.filter(User.id == session_user["id"])

        # =============================================================

        employees = query.order_by(User.name).all()

        employee_list = [
            {
                "code": emp.employee_code, 
                "name": emp.name, 
                "department": emp.department.name if emp.department else '', 
                "branch": emp.main_branch.branch_code if emp.main_branch else ''
            }
            for emp in employees
        ]
        return JSONResponse(content=employee_list)

    except Exception as e:
        logger.error(f"Lỗi khi lấy danh sách nhân viên: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": f"Lỗi server: {str(e)}"})

# ... (API /api/employees/search giữ nguyên như file của bạn) ...
@router.get("/api/employees/search", response_class=JSONResponse)
def search_employees(
    q: str = "",
    request: Request = None,
    branch_code: Optional[str] = None, 
    only_bp: bool = False,
    login_code: Optional[str] = None,
    context: Optional[str] = None,
    role_filter: Optional[str] = None,
    db: Session = Depends(get_db)
):
    if not q and context not in ['reporter_search', 'all_users_search']:
        return JSONResponse(content=[], status_code=400)
    if len(q) < 2 and context not in ['reporter_search', 'all_users_search']:
        return JSONResponse(content=[])

    search_pattern = f"%{q}%"
    session_user = request.session.get("user") if request else None

    base_query = db.query(User).options(
        joinedload(User.department),
        joinedload(User.main_branch)
    ).filter(User.is_active == True)

    if session_user and session_user.get("role") not in ["admin", "boss"] and context == "results_filter":
        checker_id = session_user.get("id")
        att_codes_q = db.query(AttendanceRecord.employee_code_snapshot).filter(AttendanceRecord.checker_id == checker_id).distinct()
        svc_codes_q = db.query(ServiceRecord.employee_code_snapshot).filter(ServiceRecord.checker_id == checker_id).distinct()
        related_codes = {row[0] for row in att_codes_q.all()}
        related_codes.update({row[0] for row in svc_codes_q.all()})
        related_codes.add(session_user.get("code")) 
        if not related_codes:
             return JSONResponse(content=[])
        query = base_query.filter(
            User.employee_code.in_(list(related_codes)),
            or_(
                User.employee_code.ilike(search_pattern),
                User.name.ilike(search_pattern)
            )
        )
        employees = query.limit(50).all()
    elif context == 'reporter_search':
        query = base_query.join(User.department).filter(
            ~Department.role_code.in_(['admin', 'boss'])
        ).filter(
            or_(
                User.employee_code.ilike(search_pattern),
                User.name.ilike(search_pattern)
            )
        )
        employees = query.limit(20).all()
        employee_list = [{"code": emp.employee_code, "name": emp.name} for emp in employees]
        return JSONResponse(content=employee_list)
    elif context == 'all_users_search':
        query = base_query.filter(
            or_(
                User.employee_code.ilike(search_pattern),
                User.name.ilike(search_pattern)
            )
        )
        employees = query.limit(20).all()
        employee_list = [{"code": emp.employee_code, "name": emp.name} for emp in employees]
        return JSONResponse(content=employee_list)
    else:
        query = base_query.filter(
            or_(
                User.employee_code == q.upper(),
                User.employee_code.ilike(search_pattern),
                User.name.ilike(search_pattern)
            )
        )
        if branch_code and not only_bp:
            query = query.join(User.main_branch).filter(Branch.branch_code == branch_code)
        if role_filter:
            query = query.join(User.department).filter(Department.role_code == role_filter)
        employees = query.limit(50).all()
        if only_bp:
            employees = [emp for emp in employees if "BP" in (emp.employee_code or "").upper()]
        
        is_admin_or_boss = session_user and session_user.get("role") in ["admin", "boss"]
        if not is_admin_or_boss:
            letan_dept_id = db.query(Department.id).filter(Department.role_code == 'letan').scalar()
            filtered_employees = []
            for emp in employees:
                if emp.department_id == letan_dept_id:
                    if login_code and emp.employee_code == login_code:
                        filtered_employees.append(emp)
                else:
                    filtered_employees.append(emp)
            employees = filtered_employees

    employee_list = [
        {
            "code": emp.employee_code,
            "name": emp.name,
            "department": emp.department.role_code if emp.department else '',
            "branch": emp.main_branch.branch_code if emp.main_branch else ''
        }
        for emp in employees[:20]
    ]
    return JSONResponse(content=employee_list)


# ... (API /checkin_bulk giữ nguyên như file của bạn) ...
#
@router.post("/checkin_bulk")
async def attendance_checkin_bulk(
    request: Request,
    db: Session = Depends(get_db)
):
    validate_csrf(request)
    session_user = request.session.get("user") or request.session.get("pending_user")
    if not session_user:
        raise HTTPException(status_code=403, detail="Không có quyền điểm danh.")
    
    checker = db.query(User).filter(User.employee_code == session_user["code"]).first()
    if not checker:
        raise HTTPException(status_code=403, detail="Không tìm thấy người dùng thực hiện điểm danh.")

    try:
        raw_data = await request.json()
        if not isinstance(raw_data, list) or not raw_data:
            return {"status": "success", "inserted": 0}

        # --- XỬ LÝ CHI NHÁNH ---
        branch_code_from_payload = raw_data[0].get("chi_nhanh_lam")
        branch_obj = db.query(Branch).filter(Branch.branch_code == branch_code_from_payload).first()
        if not branch_obj:
             # Fallback: Nếu lỗi chi nhánh, lấy chi nhánh chính của người chấm
             branch_id_lam = checker.main_branch_id 
        else:
             branch_id_lam = branch_obj.id
        
        # --- CHUẨN BỊ DỮ LIỆU ---
        employee_codes = {rec.get("ma_nv") for rec in raw_data if rec.get("ma_nv")}
        employees_in_db = db.query(User).options(
            joinedload(User.main_branch), 
            joinedload(User.department)
        ).filter(User.employee_code.in_(employee_codes)).all()
        employee_map = {emp.employee_code: emp for emp in employees_in_db}
        
        new_records = []
        now_vn = datetime.now(VN_TZ)
        
        # --- LỌC TRÙNG LẶP (DUPLICATE) ---
        target_user_ids = [employee_map[rec.get("ma_nv")].id for rec in raw_data if rec.get("ma_nv") in employee_map]
        recent_records = db.query(AttendanceRecord.user_id).filter(
            AttendanceRecord.user_id.in_(target_user_ids),
            AttendanceRecord.attendance_datetime >= (now_vn - timedelta(minutes=2))
        ).all()
        recently_checked_ids = {r[0] for r in recent_records}

        # Danh sách ID những người thực sự được insert đợt này
        inserted_user_ids = set()

        for rec in raw_data:
            ma_nv = rec.get("ma_nv")
            employee_snapshot = employee_map.get(ma_nv)
            if not employee_snapshot: continue

            # Nếu vừa chấm xong -> Bỏ qua
            if employee_snapshot.id in recently_checked_ids: continue 

            new_records.append(AttendanceRecord(
                user_id=employee_snapshot.id,
                checker_id=checker.id,
                branch_id=branch_id_lam,
                employee_code_snapshot=employee_snapshot.employee_code,
                employee_name_snapshot=employee_snapshot.name,
                role_snapshot=employee_snapshot.department.name if employee_snapshot.department else None,
                main_branch_snapshot=employee_snapshot.main_branch.branch_code if employee_snapshot.main_branch else None,
                attendance_datetime=now_vn,
                work_units=float(rec.get("so_cong_nv", 1.0)),
                is_overtime=bool(rec.get("la_tang_ca", False)),
                notes=rec.get("ghi_chu", "")
            ))
            recently_checked_ids.add(employee_snapshot.id)
            inserted_user_ids.add(employee_snapshot.id)

        # === [FIX QUAN TRỌNG] TỰ ĐỘNG THÊM VÉ CHO CHECKER (QL01/KTV) NẾU THIẾU ===
        # Nếu đang ở chế độ chờ (pending) VÀ bản thân Checker chưa có trong danh sách vừa tạo
        is_pending = request.session.get("pending_user")
        if is_pending and (checker.id not in inserted_user_ids) and (checker.id not in recently_checked_ids):
             self_record = AttendanceRecord(
                user_id=checker.id,
                checker_id=checker.id,
                branch_id=branch_id_lam,
                employee_code_snapshot=checker.employee_code,
                employee_name_snapshot=checker.name,
                role_snapshot=checker.department.name if checker.department else None,
                main_branch_snapshot=checker.main_branch.branch_code if checker.main_branch else None,
                attendance_datetime=now_vn,
                work_units=1.0,
                is_overtime=False,
                notes="Tự động điểm danh (Checker)"
            )
             new_records.append(self_record)
             inserted_user_ids.add(checker.id) # Đánh dấu đã có vé

        if new_records:
            db.add_all(new_records)
            db.commit()
        
        # === [XỬ LÝ TRẠNG THÁI ĐĂNG NHẬP] ===
        if request.session.get("pending_user"):
            token = raw_data[0].get("token")
            log = None
            
            # 1. Tìm Log bằng Token (nếu quét QR)
            if token:
                 log = db.query(AttendanceLog).filter(AttendanceLog.token == token).first()
            
            # 2. [FIX CHÍNH] Tìm Log bằng User ID + Ngày (nếu đăng nhập Pass/Token null)
            # Đây là lý do QL01 bị lỗi ở code cũ: Token null -> không tìm thấy log -> DB vẫn False
            if not log:
                work_date, _ = get_current_work_shift()
                log = db.query(AttendanceLog).filter(
                    AttendanceLog.user_id == checker.id,
                    AttendanceLog.work_date == work_date
                ).first()

            # Cập nhật trạng thái check-in trong DB
            if log and not log.checked_in:
                log.checked_in = True
                db.commit() # Lưu vào DB để lần sau đăng nhập lại hệ thống biết là "Đã check-in"
            
            # Chuyển Session từ Pending -> User chính thức
            request.session["user"] = session_user
            request.session.pop("pending_user", None)

            return {
                "status": "success",
                "inserted": len(new_records),
                "redirect_to": "/pms"
            }

        return {"status": "success", "inserted": len(new_records)}

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Lỗi khi lưu điểm danh: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi khi lưu điểm danh vào cơ sở dữ liệu.")

# ... (API /api/last-checked-in-bp giữ nguyên như file của bạn) ...
@router.get("/api/last-checked-in-bp", response_class=JSONResponse)
def get_last_checked_in_bp(request: Request, db: Session = Depends(get_db)):
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=403, detail="Không có quyền truy cập.")

    checker_id = user_data.get("id")
    work_date, _ = get_current_work_shift()

    buong_phong_dept = db.query(Department).filter(Department.role_code == 'buongphong').first()
    if not buong_phong_dept:
        return JSONResponse(content=[])

    recent_records = db.query(
        AttendanceRecord.employee_code_snapshot,
        AttendanceRecord.employee_name_snapshot,
        AttendanceRecord.main_branch_snapshot
    ).join(User, AttendanceRecord.user_id == User.id
    ).filter(
        AttendanceRecord.checker_id == checker_id,
        User.department_id == buong_phong_dept.id,
        cast(AttendanceRecord.attendance_datetime, Date) == work_date
    ).distinct().all()

    employee_list = [
        {
            "code": rec.employee_code_snapshot,
            "name": rec.employee_name_snapshot,
            "branch": rec.main_branch_snapshot,
            "so_phong": "", "so_luong": "", "dich_vu": "", "ghi_chu": ""
        }
        for rec in recent_records
    ]
    return JSONResponse(content=employee_list)
