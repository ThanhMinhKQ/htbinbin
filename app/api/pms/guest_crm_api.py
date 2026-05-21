# app/api/pms/guest_crm_api.py
"""
Guest CRM API - Guest Relationship Management Endpoints
API quản lý thông tin khách hàng, phân loại thành viên, xem lịch sử
"""
from __future__ import annotations

import base64
from datetime import date, datetime
from decimal import Decimal
import json
import time
import unicodedata
from typing import Any, Optional, List
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func, or_, and_
from sqlalchemy.exc import IntegrityError

from ...db.models import (
    Guest, GuestMembership, GuestStaySummary, GuestServiceUsage,
    GuestPaymentSummary, GuestActivity, HotelStay, HotelGuest,
    HotelRoom, HotelRoomType, Folio, FolioTransaction, Payment, Branch, MemberTier,
    GuestIdentity, GuestPreference, User,
    HotelStayStatus,
)
from ...db.session import get_db
from ...services.guest_crm_service import (
    get_guest_comprehensive_profile,
    get_guest_stay_summaries,
    get_guest_service_usages,
    get_guest_service_stats,
    get_guest_payment_history,
    get_guest_payment_stats,
    update_membership_stats,
    create_stay_summary,
    create_service_usage_from_folio_transaction,
    create_payment_summary,
    calculate_tier,
    get_tier_benefits,
    get_membership_settings,
    save_membership_settings,
    get_membership_thresholds,
    get_guest_risk_flags,
)
from .pms_helpers import _require_login, _active_branch, _now_vn, _is_manager
from .guest_activity import ActivityType, ActivityGroup, ActorType, Source, log_activity, get_guest_timeline, get_guest_stats
from ...core.utils import VN_TZ

router = APIRouter()
_CRM_STATS_CACHE: dict[tuple, tuple[float, dict]] = {}
_CRM_STATS_TTL_SECONDS = 30.0
_CRM_SEARCH_CACHE: dict[tuple, tuple[float, dict]] = {}
_CRM_SEARCH_STATS_TTL_SECONDS = 30.0


class GuestBlacklistPayload(BaseModel):
    is_blacklisted: bool
    reason: Optional[str] = None


class GuestCreatePayload(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    phone: Optional[str] = None
    email: Optional[str] = None
    cccd: Optional[str] = None
    id_type: Optional[str] = None
    date_of_birth: Optional[Any] = None
    birth_date: Optional[Any] = None
    gender: Optional[str] = None
    nationality: Optional[str] = None
    id_expire: Optional[Any] = None
    cccd_expire_date: Optional[Any] = None
    default_address: Optional[str] = None
    address: Optional[str] = None
    address_type: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    ward: Optional[str] = None
    new_city: Optional[str] = None
    new_ward: Optional[str] = None
    old_city: Optional[str] = None
    old_district: Optional[str] = None
    old_ward: Optional[str] = None
    notes: Optional[str] = None
    is_blacklisted: bool = False
    blacklist_reason: Optional[str] = None
    tax_code: Optional[str] = None
    invoice_contact: Optional[str] = None
    company_name: Optional[str] = None
    company_address: Optional[str] = None


class GuestInvoicePayload(BaseModel):
    tax_code: Optional[str] = None
    invoice_contact: Optional[str] = None
    company_name: Optional[str] = None
    company_address: Optional[str] = None


class CrmMembershipTierPayload(BaseModel):
    tier: str
    display_name: str
    threshold: float = 0
    points_multiplier: float = 1
    discount_percent: float = 0
    benefits: dict = Field(default_factory=dict)


class CrmMembershipSettingsPayload(BaseModel):
    points_per_1000_vnd: float
    tiers: List[CrmMembershipTierPayload]


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _duration_payload(check_in_at, check_out_at):
    if not check_in_at:
        return {
            "duration_minutes": 0,
            "duration_hours": 0,
            "duration_display": "-",
        }

    end_at = check_out_at or _now_vn()
    minutes = max(0, int((end_at - check_in_at).total_seconds() // 60))
    hours = round(minutes / 60, 1)
    days = minutes // 1440
    rem_hours = (minutes % 1440) // 60
    rem_minutes = minutes % 60

    if days > 0:
        parts = [f"{days} ngày"]
        if rem_hours:
            parts.append(f"{rem_hours} giờ")
        if rem_minutes and days == 0:
            parts.append(f"{rem_minutes} phút")
    elif rem_hours > 0:
        parts = [f"{rem_hours} giờ"]
        if rem_minutes:
            parts.append(f"{rem_minutes} phút")
    else:
        parts = [f"{rem_minutes} phút"]

    return {
        "duration_minutes": minutes,
        "duration_hours": hours,
        "duration_display": " ".join(parts),
    }


def _activity_payload(a: GuestActivity) -> dict:
    return {
        "id": a.id,
        "type": "activity",
        "activity_type": a.activity_type,
        "activity_group": a.activity_group,
        "title": a.title,
        "description": a.description,
        "stay_id": a.stay_id,
        "branch_id": a.branch_id,
        "amount": float(a.amount) if a.amount else None,
        "currency": a.currency,
        "actor_type": a.actor_type,
        "source": a.source,
        "extra_data": a.extra_data,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _payment_transaction_code(db: Session, payment: GuestPaymentSummary) -> Optional[str]:
    if payment.transaction_code:
        return payment.transaction_code
    if payment.payment_id:
        p = db.query(Payment).filter(Payment.id == payment.payment_id).first()
        if p and p.transaction_code:
            return p.transaction_code
    if payment.folio_id:
        tx = db.query(FolioTransaction).filter(
            FolioTransaction.folio_id == payment.folio_id,
            FolioTransaction.reference_type.in_(["payment", "payment_refund"]),
            FolioTransaction.reference_id == payment.payment_id,
        ).order_by(FolioTransaction.created_at.desc()).first() if payment.payment_id else None
        if tx and tx.shift_transaction:
            return tx.shift_transaction.transaction_code
    return None


def _stay_transfer_settlement_payload(db: Session, stay_id: int) -> Optional[dict]:
    tx = db.query(FolioTransaction).filter(
        FolioTransaction.stay_id == stay_id,
        FolioTransaction.reference_type == "room_bill_transfer",
        FolioTransaction.amount < 0,
        FolioTransaction.is_voided == False,
    ).order_by(FolioTransaction.created_at.desc()).first()
    if not tx:
        return None

    target_stay = db.query(HotelStay).filter(HotelStay.id == tx.reference_id).first() if tx.reference_id else None
    target_room = None
    if target_stay and target_stay.room_id:
        target_room = db.query(HotelRoom).filter(HotelRoom.id == target_stay.room_id).first()
    actor = db.query(User).filter(User.id == tx.created_by).first() if tx.created_by else None

    return {
        "type": "room_bill_transfer",
        "amount": float(abs(tx.amount or Decimal("0"))),
        "source_stay_id": stay_id,
        "target_stay_id": target_stay.id if target_stay else tx.reference_id,
        "target_room_number": target_room.room_number if target_room else None,
        "settled_by_user_id": actor.id if actor else tx.created_by,
        "settled_by_name": actor.name if actor else None,
        "settled_at": tx.created_at.isoformat() if tx.created_at else None,
        "description": tx.description,
    }


def _active_branch_id(request: Request, db: Session) -> Optional[int]:
    branch_code = _active_branch(request)
    if not branch_code:
        return None
    branch = db.query(Branch).filter(Branch.branch_code == branch_code).first()
    return branch.id if branch else None


def _json_cache_get(cache: dict[tuple, tuple[float, dict]], key: tuple, ttl_seconds: float) -> Optional[dict]:
    cached = cache.get(key)
    if not cached:
        return None
    cached_at, payload = cached
    if (time.time() - cached_at) >= ttl_seconds:
        cache.pop(key, None)
        return None
    return payload


def _json_cache_set(cache: dict[tuple, tuple[float, dict]], key: tuple, payload: dict, max_items: int = 128) -> None:
    cache[key] = (time.time(), payload)
    if len(cache) > max_items:
        oldest = min(cache.items(), key=lambda kv: kv[1][0])[0]
        cache.pop(oldest, None)


def _clear_crm_caches() -> None:
    _CRM_STATS_CACHE.clear()
    _CRM_SEARCH_CACHE.clear()


def _clean_guest_text(value: Any, max_len: Optional[int] = None, *, lower: bool = False) -> Optional[str]:
    if value is None:
        return None
    clean = str(value).strip()
    if not clean:
        return None
    if lower:
        clean = clean.lower()
    if max_len and len(clean) > max_len:
        clean = clean[:max_len]
    return clean


def _normalize_guest_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = unicodedata.normalize("NFD", value)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("Đ", "D").replace("đ", "d")
    return " ".join(text.lower().split())


def _parse_guest_date(value: Any, field_label: str) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_label} không hợp lệ")


def _sync_guest_identities(db: Session, guest: Guest) -> None:
    identities = {
        "phone": _clean_guest_text(guest.phone, 20),
        "email": _clean_guest_text(guest.email, 255, lower=True),
        "cccd": _clean_guest_text(guest.cccd, 20),
    }
    current_rows = db.query(GuestIdentity).filter(GuestIdentity.guest_id == guest.id).all()
    current_by_type = {row.identity_type: row for row in current_rows}

    for identity_type, value in identities.items():
        row = current_by_type.get(identity_type)
        if not value:
            if row:
                db.delete(row)
            continue

        conflict = db.query(GuestIdentity).filter(
            GuestIdentity.identity_type == identity_type,
            GuestIdentity.normalized_value == value,
            GuestIdentity.guest_id != guest.id,
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail=f"{identity_type.upper()} đã thuộc về khách khác")

        if row:
            row.identity_value = value
            row.normalized_value = value
            row.is_primary = True
        else:
            db.add(GuestIdentity(
                guest_id=guest.id,
                identity_type=identity_type,
                identity_value=value,
                normalized_value=value,
                is_primary=True,
            ))


def _compose_guest_address(payload: GuestCreatePayload) -> Optional[str]:
    detail = _clean_guest_text(payload.address)
    mode = _clean_guest_text(payload.address_type, 10)
    if mode == "old":
        parts = [
            detail,
            _clean_guest_text(payload.old_ward, 100),
            _clean_guest_text(payload.old_district, 100),
            _clean_guest_text(payload.old_city, 100),
        ]
    else:
        parts = [
            detail,
            _clean_guest_text(payload.ward or payload.new_ward, 100),
            _clean_guest_text(payload.city or payload.new_city, 100),
        ]
    composed = ", ".join(part for part in parts if part)
    return composed or detail


def _apply_guest_core_fields(db: Session, guest: Guest, payload: GuestCreatePayload, user_id: Optional[int], *, is_create: bool) -> None:
    fields = payload.model_fields_set

    if is_create or "full_name" in fields:
        full_name = _clean_guest_text(payload.full_name, 255)
        if not full_name:
            raise HTTPException(status_code=400, detail="Tên khách không được để trống")
        guest.full_name = full_name
        guest.normalized_name = _normalize_guest_name(full_name)

    if is_create or "phone" in fields:
        guest.phone = _clean_guest_text(payload.phone, 20)
    if is_create or "email" in fields:
        guest.email = _clean_guest_text(payload.email, 255, lower=True)
    if is_create or "cccd" in fields:
        cccd = _clean_guest_text(payload.cccd, 20)
        if cccd:
            existing = db.query(Guest).filter(
                Guest.cccd == cccd,
                Guest.deleted_at.is_(None),
                Guest.id != guest.id,
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="Số CCCD/giấy tờ đã tồn tại trong CRM")
        guest.cccd = cccd
    if is_create or "date_of_birth" in fields or "birth_date" in fields:
        raw_birth = payload.date_of_birth if payload.date_of_birth is not None else payload.birth_date
        guest.date_of_birth = _parse_guest_date(raw_birth, "Ngày sinh")
    if is_create or "gender" in fields:
        guest.gender = _clean_guest_text(payload.gender, 10)
    if is_create or "nationality" in fields:
        guest.nationality = _clean_guest_text(payload.nationality, 100)
    if is_create or "id_expire" in fields or "cccd_expire_date" in fields:
        raw_expire = payload.id_expire if payload.id_expire is not None else payload.cccd_expire_date
        guest.id_expire = _parse_guest_date(raw_expire, "Hạn CCCD/giấy tờ")
    if is_create or "default_address" in fields or "address" in fields:
        raw_address = payload.default_address if payload.default_address is not None else _compose_guest_address(payload)
        guest.default_address = _clean_guest_text(raw_address)

    # Invoice fields
    if is_create or "tax_code" in fields:
        guest.tax_code = _clean_guest_text(payload.tax_code, 50)
    if is_create or "invoice_contact" in fields:
        guest.invoice_contact = _clean_guest_text(payload.invoice_contact, 255)
    if is_create or "company_name" in fields:
        guest.company_name = _clean_guest_text(payload.company_name, 255)
    if is_create or "company_address" in fields:
        guest.company_address = _clean_guest_text(payload.company_address)

    guest.updated_by = user_id
    if guest.id is None:
        db.flush()
    _sync_guest_identities(db, guest)


def _set_guest_blacklist_state(guest: Guest, is_blacklisted: bool) -> None:
    guest.is_blacklisted = is_blacklisted
    tags = list(guest.tags or [])
    if is_blacklisted and "BLACKLIST" not in tags:
        tags.append("BLACKLIST")
    if not is_blacklisted:
        tags = [t for t in tags if t != "BLACKLIST"]
    guest.tags = tags


def _guest_management_payload(db: Session, guest: Guest) -> dict:
    return {
        "id": guest.id,
        "full_name": guest.full_name,
        "phone": guest.phone,
        "email": guest.email,
        "cccd": guest.cccd,
        "date_of_birth": guest.date_of_birth.isoformat() if guest.date_of_birth else None,
        "gender": guest.gender,
        "nationality": guest.nationality,
        "id_expire": guest.id_expire.isoformat() if guest.id_expire else None,
        "cccd_expire_date": guest.id_expire.isoformat() if guest.id_expire else None,
        "default_address": guest.default_address,
        "address": guest.default_address,
        "is_blacklisted": bool(guest.is_blacklisted),
        "tags": guest.tags or [],
        "risk_flags": get_guest_risk_flags(db, guest.id),
    }


def _encode_guest_cursor(guest: Guest) -> str:
    payload = {
        "last_seen_at": guest.last_seen_at.isoformat() if guest.last_seen_at else None,
        "id": int(guest.id),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_guest_cursor(cursor: Optional[str]) -> Optional[dict]:
    if not cursor:
        return None
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        guest_id = int(payload["id"])
        last_seen_raw = payload.get("last_seen_at")
        last_seen_at = datetime.fromisoformat(last_seen_raw) if last_seen_raw else None
        return {"id": guest_id, "last_seen_at": last_seen_at}
    except Exception:
        return None


def _apply_guest_cursor(query, cursor_data: Optional[dict]):
    if not cursor_data:
        return query

    cursor_id = cursor_data["id"]
    cursor_last_seen = cursor_data["last_seen_at"]
    if cursor_last_seen is None:
        return query.filter(
            Guest.last_seen_at.is_(None),
            Guest.id > cursor_id,
        )

    return query.filter(or_(
        Guest.last_seen_at < cursor_last_seen,
        and_(Guest.last_seen_at == cursor_last_seen, Guest.id > cursor_id),
        Guest.last_seen_at.is_(None),
    ))


# ====================================================================
# GUEST SEARCH & LIST
# ====================================================================

@router.get("/api/pms/crm/guests/search", tags=["PMS - CRM"])
def api_search_guests(
    request: Request,
    q: Optional[str] = Query(default=None, description="Tìm theo tên, CCCD, SĐT, email"),
    cccd: Optional[str] = Query(default=None),
    phone: Optional[str] = Query(default=None),
    branch_id: Optional[int] = Query(default=None),
    tier: Optional[str] = Query(default=None),
    blacklist: Optional[bool] = Query(default=None),
    debt: Optional[str] = Query(default=None),
    include_total: bool = Query(default=True),
    cursor: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Tìm kiếm khách hàng
    """
    user = _require_login(request)

    q_clean = q.strip().lower() if q else ""

    # Base query
    query = db.query(Guest)

    # Search conditions
    if cccd:
        query = query.filter(Guest.cccd.like(f"{cccd.strip()}%"))
    elif phone:
        query = query.filter(Guest.phone.like(f"{phone.strip()}%"))
    elif q_clean:
        prefix = f"{q_clean}%"
        search_filters = [
            Guest.normalized_name.like(prefix),
            Guest.cccd.like(prefix),
            Guest.phone.like(prefix),
            Guest.email.like(prefix),
            Guest.full_name.ilike(prefix),
        ]
        # For short tokens, keep strict prefix search so PostgreSQL can use
        # text-pattern indexes. For more intentional queries, allow fuzzy name
        # contains to preserve current operator expectations.
        if len(q_clean) >= 3:
            search_filters.append(Guest.full_name.ilike(f"%{q_clean}%"))
        query = query.filter(or_(*search_filters))

    if blacklist is not None:
        query = query.filter(Guest.is_blacklisted == blacklist)

    if debt in ("unpaid", "paid"):
        debt_exists = db.query(GuestStaySummary.id).filter(
            GuestStaySummary.guest_id == Guest.id,
            GuestStaySummary.debt_amount > 0,
            GuestStaySummary.debt_status.in_(["pending", "partial"]),
        ).exists()
        if debt == "unpaid":
            query = query.filter(debt_exists)
        else:
            query = query.filter(~debt_exists)

    if tier:
        membership_exists = db.query(GuestMembership.id).filter(
            GuestMembership.guest_id == Guest.id,
            GuestMembership.tier == tier,
        ).exists()
        query = query.filter(membership_exists)

    # Exclude deleted
    query = query.filter(Guest.deleted_at.is_(None))

    # Order by last seen
    query = query.order_by(Guest.last_seen_at.desc().nullslast(), Guest.id.asc())

    cursor_data = _decode_guest_cursor(cursor)
    if cursor and not cursor_data:
        raise HTTPException(status_code=400, detail="Cursor không hợp lệ")
    if cursor_data:
        query = _apply_guest_cursor(query, cursor_data)

    total = query.order_by(None).count() if include_total else None

    # Paginate
    fetch_size = page_size if include_total else page_size + 1
    if cursor_data:
        guests = query.limit(fetch_size).all()
    else:
        guests = query.offset((page - 1) * page_size).limit(fetch_size).all()

    has_next = False
    if not include_total and len(guests) > page_size:
        has_next = True
        guests = guests[:page_size]
    elif include_total and total is not None:
        has_next = page * page_size < total

    next_cursor = _encode_guest_cursor(guests[-1]) if has_next and guests else None

    if not guests:
        return JSONResponse({
            "guests": [],
            "items": [],  # Backward compatibility
            "total": total,
            "total_exact": include_total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if include_total and total else 0,
            "has_next": False,
            "next_cursor": None,
        })

    # Batch load memberships
    guest_ids = [g.id for g in guests]
    memberships = db.query(GuestMembership).filter(
        GuestMembership.guest_id.in_(guest_ids)
    ).all()
    membership_map = {m.guest_id: m for m in memberships}
    tier_names = _tier_display_names(db)

    # Batch load most recent HotelGuest address data for each guest
    # Use subquery to get the most recent HotelGuest per guest_id
    recent_hotel_guest_subq = (
        db.query(
            HotelGuest.guest_id,
            func.max(HotelGuest.id).label('max_hg_id')
        )
        .filter(
            HotelGuest.guest_id.in_(guest_ids),
            HotelGuest.guest_id.isnot(None)
        )
        .group_by(HotelGuest.guest_id)
        .subquery()
    )

    recent_hotel_guests = (
        db.query(HotelGuest)
        .join(
            recent_hotel_guest_subq,
            and_(
                HotelGuest.guest_id == recent_hotel_guest_subq.c.guest_id,
                HotelGuest.id == recent_hotel_guest_subq.c.max_hg_id
            )
        )
        .all()
    )
    hotel_guest_map = {hg.guest_id: hg for hg in recent_hotel_guests}

    debt_rows = db.query(
        GuestStaySummary.guest_id,
        func.coalesce(func.sum(GuestStaySummary.debt_amount), 0).label("debt_total"),
    ).filter(
        GuestStaySummary.guest_id.in_(guest_ids),
        GuestStaySummary.debt_amount > 0,
        GuestStaySummary.debt_status.in_(["pending", "partial"]),
    ).group_by(GuestStaySummary.guest_id).all()
    debt_map = {row.guest_id: row.debt_total or Decimal("0") for row in debt_rows}

    blacklist_activity_rows = []
    if blacklist:
        blacklist_activity_rows = db.query(
            GuestActivity,
            User.name.label("actor_name"),
            Branch.name.label("branch_name"),
        ).outerjoin(
            User, User.id == GuestActivity.actor_id
        ).outerjoin(
            Branch, Branch.id == GuestActivity.branch_id
        ).filter(
            GuestActivity.guest_id.in_(guest_ids),
            GuestActivity.activity_type == "BLACKLISTED",
        ).order_by(GuestActivity.created_at.desc()).all()

    blacklist_info_map = {}
    for activity, actor_name, branch_name in blacklist_activity_rows:
        if activity.guest_id in blacklist_info_map:
            continue
        extra_data = activity.extra_data if isinstance(activity.extra_data, dict) else {}
        blacklist_info_map[activity.guest_id] = {
            "reason": activity.description,
            "actor_name": actor_name,
            "branch_name": branch_name,
            "created_at": activity.created_at.isoformat() if activity.created_at else None,
            "form": extra_data.get("form") if isinstance(extra_data.get("form"), dict) else None,
        }

    # Batch load last stays from denormalized summary, no HotelStay/HotelRoom join.
    last_stay_subq = (
        db.query(
            GuestStaySummary.guest_id,
            func.max(GuestStaySummary.check_in_at).label("max_checkin"),
        )
        .filter(
            GuestStaySummary.guest_id.in_(guest_ids),
            GuestStaySummary.status != HotelStayStatus.ACTIVE.value,
        )
        .group_by(GuestStaySummary.guest_id)
        .subquery()
    )

    last_stays = (
        db.query(GuestStaySummary)
        .join(
            last_stay_subq,
            and_(
                GuestStaySummary.guest_id == last_stay_subq.c.guest_id,
                GuestStaySummary.check_in_at == last_stay_subq.c.max_checkin,
            )
        )
        .all()
    )
    stay_map = {}
    for summary in last_stays:
        if summary.guest_id not in stay_map:
            stay_map[summary.guest_id] = summary

    # Batch load branches
    branch_map = {}
    branch_ids = list({s.branch_id for s in last_stays if s.branch_id})
    if branch_ids:
        branches = db.query(Branch).filter(Branch.id.in_(branch_ids)).all()
        branch_map = {b.id: b.name for b in branches}

    # Build response
    results = []
    for g in guests:
        membership = membership_map.get(g.id)
        last_stay_data = stay_map.get(g.id)
        hg = hotel_guest_map.get(g.id)  # Most recent HotelGuest record

        last_branch = branch_map.get(last_stay_data.branch_id) if last_stay_data else None

        results.append({
            "id": g.id,
            "full_name": g.full_name,
            "phone": g.phone,
            "email": g.email,
            "cccd": g.cccd,
            "date_of_birth": g.date_of_birth.isoformat() if g.date_of_birth else None,
            "birth_date": g.date_of_birth.isoformat() if g.date_of_birth else None,  # Alias for checkin form
            "gender": g.gender,
            "nationality": g.nationality,
            "id_expire": g.id_expire.isoformat() if g.id_expire else None,
            "id_type": getattr(hg, 'id_type', None) if hg else None,  # From most recent HotelGuest
            "default_address": g.default_address,
            # Address fields from most recent HotelGuest (for checkin form)
            "address": getattr(hg, 'address', None) if hg else None,
            "city": getattr(hg, 'city', None) if hg else None,
            "district": getattr(hg, 'district', None) if hg else None,
            "ward": getattr(hg, 'ward', None) if hg else None,
            "address_type": getattr(hg, 'address_type', None) if hg else None,
            "old_city": getattr(hg, 'old_city', None) if hg else None,
            "old_district": getattr(hg, 'old_district', None) if hg else None,
            "old_ward": getattr(hg, 'old_ward', None) if hg else None,
            "notes": getattr(hg, 'notes', None) if hg else None,
            "tax_code": getattr(hg, 'tax_code', None) if hg else None,
            "invoice_contact": getattr(hg, 'invoice_contact', None) if hg else None,
            "company_name": getattr(hg, 'company_name', None) if hg else None,
            "company_address": getattr(hg, 'company_address', None) if hg else None,
            "is_blacklisted": g.is_blacklisted,
            "blacklist_info": blacklist_info_map.get(g.id),
            "edit_guest": {
                "hotel_guest_id": hg.id,
                "stay_id": hg.stay_id,
            } if hg else None,
            "has_unpaid_debt": debt_map.get(g.id, Decimal("0")) > 0,
            "unpaid_debt_amount": float(debt_map.get(g.id, Decimal("0"))),
            "risk_flags": {
                "is_blacklisted": bool(g.is_blacklisted),
                "has_unpaid_debt": debt_map.get(g.id, Decimal("0")) > 0,
                "unpaid_debt_amount": float(debt_map.get(g.id, Decimal("0"))),
                "warnings": [
                    *([{
                        "type": "blacklist",
                        "level": "danger",
                        "message": "Khách đang nằm trong danh sách đen.",
                    }] if g.is_blacklisted else []),
                    *([{
                        "type": "debt",
                        "level": "warning",
                        "amount": float(debt_map.get(g.id, Decimal("0"))),
                        "message": f"Khách còn nợ {float(debt_map.get(g.id, Decimal('0'))):,.0f}đ chưa thanh toán.",
                    }] if debt_map.get(g.id, Decimal("0")) > 0 else []),
                ],
            },
            "last_seen_at": g.last_seen_at.isoformat() if g.last_seen_at else None,
            "total_stays": membership.total_stays if membership and membership.total_stays is not None else (g.total_stays or 0),
            "tier": membership.tier.value if membership else MemberTier.BASIC.value,
            "tier_display": tier_names.get(membership.tier.value if membership else MemberTier.BASIC.value, MemberTier.BASIC.value),
            "total_spent": float(membership.total_spent) if membership else 0,
            "loyalty_points": membership.points_balance if membership else 0,
            "last_stay": {
                "room_number": last_stay_data.room_number,
                "branch_name": last_branch,
                "check_in": last_stay_data.check_in_at.isoformat() if last_stay_data and last_stay_data.check_in_at else None,
            } if last_stay_data else None,
        })

    return JSONResponse({
        "guests": results,
        "items": results,  # Backward compatibility
        "total": total,
        "total_exact": include_total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if include_total and total else 0,
        "has_next": has_next,
        "next_cursor": next_cursor,
    })


@router.post("/api/pms/crm/guests", tags=["PMS - CRM"])
def api_create_crm_guest(
    request: Request,
    payload: GuestCreatePayload,
    db: Session = Depends(get_db),
):
    """Tạo hồ sơ khách thủ công trong CRM, có thể đưa thẳng vào blacklist."""
    user = _require_login(request)
    now = _now_vn()
    branch_id = _active_branch_id(request, db)

    guest = Guest(
        first_seen_at=now,
        last_seen_at=now,
        created_by=user.get("id"),
        updated_by=user.get("id"),
    )
    db.add(guest)

    try:
        _apply_guest_core_fields(db, guest, payload, user.get("id"), is_create=True)
        _set_guest_blacklist_state(guest, bool(payload.is_blacklisted))
        manual_form = payload.model_dump(mode="json", exclude_none=True)

        log_activity(
            db=db,
            guest_id=guest.id,
            activity_type=ActivityType.PROFILE_UPDATED,
            activity_group=ActivityGroup.SYSTEM,
            title="Tạo hồ sơ khách thủ công",
            description="Tạo hồ sơ khách từ trang CRM",
            branch_id=branch_id,
            actor_type=ActorType.USER,
            actor_id=user.get("id"),
            source=Source.PMS,
            extra_data={"manual": True, "form": manual_form},
        )

        if payload.is_blacklisted:
            log_activity(
                db=db,
                guest_id=guest.id,
                activity_type=ActivityType.BLACKLISTED,
                activity_group=ActivityGroup.SYSTEM,
                title="Đưa vào danh sách đen",
                description=payload.blacklist_reason or "Khách được thêm thủ công vào danh sách đen",
                branch_id=branch_id,
                actor_type=ActorType.USER,
                actor_id=user.get("id"),
                source=Source.PMS,
                extra_data={"is_blacklisted": True, "reason": payload.blacklist_reason, "manual": True, "form": manual_form},
            )

        db.commit()
        _clear_crm_caches()
        db.refresh(guest)
        return JSONResponse({"guest": _guest_management_payload(db, guest)}, status_code=201)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Thông tin định danh khách đã tồn tại")


@router.patch("/api/pms/crm/guests/{guest_id}", tags=["PMS - CRM"])
def api_update_crm_guest(
    request: Request,
    guest_id: int,
    payload: GuestCreatePayload,
    db: Session = Depends(get_db),
):
    """Cập nhật hồ sơ CRM thủ công cho khách chưa có bản ghi lưu trú."""
    user = _require_login(request)
    branch_id = _active_branch_id(request, db)

    guest = db.query(Guest).filter(Guest.id == guest_id, Guest.deleted_at.is_(None)).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    previous_blacklist = bool(guest.is_blacklisted)
    try:
        _apply_guest_core_fields(db, guest, payload, user.get("id"), is_create=False)
        if "is_blacklisted" in payload.model_fields_set:
            _set_guest_blacklist_state(guest, bool(payload.is_blacklisted))

        update_form = payload.model_dump(mode="json", exclude_none=True)
        log_activity(
            db=db,
            guest_id=guest.id,
            activity_type=ActivityType.PROFILE_UPDATED,
            activity_group=ActivityGroup.SYSTEM,
            title="Cập nhật hồ sơ CRM",
            description="Cập nhật thông tin khách từ danh sách đen",
            branch_id=branch_id,
            actor_type=ActorType.USER,
            actor_id=user.get("id"),
            source=Source.PMS,
            extra_data={"manual": True, "form": update_form},
        )

        if payload.is_blacklisted and (payload.blacklist_reason or not previous_blacklist):
            log_activity(
                db=db,
                guest_id=guest.id,
                activity_type=ActivityType.BLACKLISTED,
                activity_group=ActivityGroup.SYSTEM,
                title="Cập nhật danh sách đen",
                description=payload.blacklist_reason or "Khách được giữ trong danh sách đen",
                branch_id=branch_id,
                actor_type=ActorType.USER,
                actor_id=user.get("id"),
                source=Source.PMS,
                extra_data={"is_blacklisted": True, "reason": payload.blacklist_reason, "manual": True, "form": update_form},
            )

        db.commit()
        _clear_crm_caches()
        db.refresh(guest)
        return JSONResponse({"guest": _guest_management_payload(db, guest)})
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Thông tin định danh khách đã tồn tại")


@router.delete("/api/pms/crm/guests/{guest_id}", tags=["PMS - CRM"])
def api_delete_crm_guest(
    request: Request,
    guest_id: int,
    reason: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Xóa mềm hồ sơ khách khỏi CRM."""
    user = _require_login(request)
    branch_id = _active_branch_id(request, db)

    guest = db.query(Guest).filter(Guest.id == guest_id, Guest.deleted_at.is_(None)).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    guest.deleted_at = _now_vn()
    guest.updated_by = user.get("id")
    log_activity(
        db=db,
        guest_id=guest.id,
        activity_type=ActivityType.PROFILE_UPDATED,
        activity_group=ActivityGroup.SYSTEM,
        title="Xóa hồ sơ khách",
        description=reason or "Hồ sơ khách được xóa khỏi danh sách CRM",
        branch_id=branch_id,
        actor_type=ActorType.USER,
        actor_id=user.get("id"),
        source=Source.PMS,
        extra_data={"deleted": True, "reason": reason},
    )

    db.commit()
    _clear_crm_caches()
    return JSONResponse({"status": "success", "guest_id": guest_id})


@router.get("/api/pms/crm/guests/{guest_id}", tags=["PMS - CRM"])
def api_get_guest(
    request: Request,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """
    Lấy thông tin chi tiết khách hàng
    """
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    profile = get_guest_comprehensive_profile(
        db=db,
        guest_id=guest_id,
        include_stays=True,
        include_services=True,
        include_payments=True,
        include_activities=True,
    )

    return JSONResponse(profile)


@router.get("/api/pms/crm/guests/{guest_id}/profile", tags=["PMS - CRM"])
def api_get_guest_profile(
    request: Request,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """
    Lấy profile tóm tắt của khách
    """
    user = _require_login(request)

    # Single query: guest + membership + preferences
    guest = (
        db.query(Guest)
        .options(
            joinedload(Guest.membership),
            joinedload(Guest.profile),
            selectinload(Guest.preferences),
        )
        .filter(Guest.id == guest_id)
        .first()
    )
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    membership = guest.membership
    guest_profile = guest.profile
    preferences = guest.preferences or []

    # Use membership cached stats when available, else query GuestStaySummary once
    if membership and membership.total_stays:
        total_stays = membership.total_stays or 0
        total_nights = membership.total_nights or 0
        total_spent = Decimal(str(membership.total_spent or 0))
        total_debt = Decimal(str(membership.total_debt or 0))
    else:
        stats_q = db.query(
            func.count(GuestStaySummary.id).label('total_stays'),
            func.coalesce(func.sum(GuestStaySummary.nights), 0).label('total_nights'),
            func.coalesce(func.sum(
                func.coalesce(GuestStaySummary.final_amount, 0) - func.coalesce(GuestStaySummary.debt_amount, 0)
            ), 0).label('total_spent'),
            func.coalesce(func.sum(GuestStaySummary.debt_amount), 0).label('total_debt'),
        ).filter(GuestStaySummary.guest_id == guest_id).first()
        total_stays = stats_q.total_stays or 0
        total_nights = stats_q.total_nights or 0
        total_spent = stats_q.total_spent or Decimal("0")
        total_debt = stats_q.total_debt or Decimal("0")

    # Build risk flags from already-loaded guest data (avoid re-query)
    debt_total = db.query(
        func.coalesce(func.sum(GuestStaySummary.debt_amount), 0)
    ).filter(
        GuestStaySummary.guest_id == guest_id,
        GuestStaySummary.debt_amount > 0,
        GuestStaySummary.debt_status.in_(["pending", "partial"]),
    ).scalar() or Decimal("0")

    warnings = []
    if guest.is_blacklisted:
        warnings.append({"type": "blacklist", "level": "danger", "message": "Khách đang nằm trong danh sách đen."})
    if debt_total > 0:
        warnings.append({"type": "debt", "level": "warning", "amount": float(debt_total),
                         "message": f"Khách còn nợ {float(debt_total):,.0f}đ chưa thanh toán."})
    risk_flags = {
        "guest_id": guest_id,
        "is_blacklisted": bool(guest.is_blacklisted),
        "has_unpaid_debt": debt_total > 0,
        "unpaid_debt_amount": float(debt_total),
        "warnings": warnings,
    }

    blacklist_info = None
    if guest.is_blacklisted:
        blacklist_row = db.query(
            GuestActivity,
            User.name.label("actor_name"),
            Branch.name.label("branch_name"),
        ).outerjoin(
            User, User.id == GuestActivity.actor_id
        ).outerjoin(
            Branch, Branch.id == GuestActivity.branch_id
        ).filter(
            GuestActivity.guest_id == guest_id,
            GuestActivity.activity_type == "BLACKLISTED",
        ).order_by(GuestActivity.created_at.desc()).first()
        if blacklist_row:
            activity, actor_name, branch_name = blacklist_row
            extra_data = activity.extra_data if isinstance(activity.extra_data, dict) else {}
            blacklist_info = {
                "reason": activity.description,
                "actor_name": actor_name,
                "branch_name": branch_name,
                "created_at": activity.created_at.isoformat() if activity.created_at else None,
                "form": extra_data.get("form") if isinstance(extra_data.get("form"), dict) else None,
            }

    avg_per_stay = float(total_spent) / total_stays if total_stays > 0 else 0

    # Calculate current tier from points_balance
    current_points = float(membership.points_balance) if membership and membership.points_balance else 0
    current_tier = calculate_tier(Decimal(str(current_points)), db)
    
    # Get benefits for current tier
    benefits = get_tier_benefits(current_tier, db)
    thresholds = get_membership_thresholds(db)
    tier_names = _tier_display_names(db)

    # Build complete tier journey
    tier_order = list(MemberTier)
    current_idx = tier_order.index(current_tier)
    
    # All tiers for journey display
    all_tiers = []
    for i, tier in enumerate(tier_order):
        threshold = float(thresholds[tier])
        tier_points = current_points if tier == current_tier else (threshold if threshold > 0 else 0)
        
        # Progress within this tier (0-100%)
        if i < len(tier_order) - 1:
            next_threshold = float(thresholds[tier_order[i + 1]])
            tier_range = next_threshold - threshold
            if tier_range > 0:
                tier_progress = min(100, max(0, (current_points - threshold) / tier_range * 100))
            else:
                tier_progress = 100
        else:
            tier_progress = 100  # VIP is max
        
        all_tiers.append({
            "tier": tier.value,
            "tier_display": tier_names.get(tier.value, tier.value),
            "threshold": threshold,
            "threshold_display": f"{threshold:,.0f}" if threshold > 0 else "0",
            "is_current": tier == current_tier,
            "is_unlocked": current_points >= threshold,
            "progress_percent": tier_progress,
        })

    # Next tier info (for current tier)
    next_tier = tier_order[current_idx + 1] if current_idx < len(tier_order) - 1 else None
    next_tier_info = None
    if next_tier:
        next_threshold = float(thresholds[next_tier])
        remaining = next_threshold - current_points
        progress_percent = min(100, max(0, (current_points / next_threshold) * 100)) if next_threshold > 0 else 0
        next_tier_info = {
            "tier": next_tier.value,
            "tier_display": tier_names.get(next_tier.value, next_tier.value),
            "threshold": next_threshold,
            "threshold_display": f"{next_threshold:,.0f}",
            "remaining": max(0, remaining),
            "remaining_display": f"{max(0, remaining):,.0f}",
            "progress_percent": progress_percent,
        }

    # Preferences and favorites. Prefer stored membership fields, then derive from history.
    favorite_branch_id = membership.favorite_branch_id if membership else None
    favorite_room_type = membership.favorite_room_type if membership else None
    preferred_payment_method = membership.preferred_payment_method if membership else None

    if not favorite_room_type and guest_profile:
        favorite_room_type = guest_profile.favorite_room_type
    if not preferred_payment_method and guest_profile:
        preferred_payment_method = guest_profile.preferred_payment

    # Gộp 3 query favorite thành 1 query duy nhất nếu cần
    if not favorite_branch_id or not favorite_room_type:
        stay_agg = db.query(
            GuestStaySummary.branch_id,
            Branch.name.label("branch_name"),
            GuestStaySummary.room_type_name,
            func.count(GuestStaySummary.id).label("cnt"),
        ).join(
            Branch,
            Branch.id == GuestStaySummary.branch_id,
        ).filter(
            GuestStaySummary.guest_id == guest_id,
        ).group_by(
            GuestStaySummary.branch_id,
            Branch.name,
            GuestStaySummary.room_type_name,
        ).order_by(func.count(GuestStaySummary.id).desc()).all()

        if not favorite_branch_id and stay_agg:
            favorite_branch_id = stay_agg[0].branch_id
        if not favorite_room_type and stay_agg:
            room_rows = [r for r in stay_agg if r.room_type_name]
            if room_rows:
                favorite_room_type = room_rows[0].room_type_name
    else:
        stay_agg = []

    if not preferred_payment_method:
        payment_row = db.query(
            GuestPaymentSummary.payment_method,
            func.count(GuestPaymentSummary.id).label("payment_count"),
        ).filter(
            GuestPaymentSummary.guest_id == guest_id,
            GuestPaymentSummary.payment_method.isnot(None),
            GuestPaymentSummary.is_voided == False,
        ).group_by(GuestPaymentSummary.payment_method).order_by(func.count(GuestPaymentSummary.id).desc()).first()
        preferred_payment_method = payment_row.payment_method if payment_row else None

    favorite_branch_name = None
    if favorite_branch_id:
        favorite_branch_name = next(
            (r.branch_name for r in stay_agg if r.branch_id == favorite_branch_id and r.branch_name),
            None,
        )
        if not favorite_branch_name:
            favorite_branch = db.query(Branch).filter(Branch.id == favorite_branch_id).first()
            favorite_branch_name = favorite_branch.name if favorite_branch else None

    stay_pref_rows = db.query(
        GuestStaySummary.branch_id,
        Branch.name.label("branch_name"),
        GuestStaySummary.room_type_name,
        GuestStaySummary.floor,
        GuestStaySummary.stay_type,
        GuestStaySummary.pricing_mode,
        GuestStaySummary.vehicle,
        func.count(GuestStaySummary.id).label("cnt"),
    ).join(
        Branch,
        Branch.id == GuestStaySummary.branch_id,
    ).filter(
        GuestStaySummary.guest_id == guest_id,
    ).group_by(
        GuestStaySummary.branch_id,
        Branch.name,
        GuestStaySummary.room_type_name,
        GuestStaySummary.floor,
        GuestStaySummary.stay_type,
        GuestStaySummary.pricing_mode,
        GuestStaySummary.vehicle,
    ).all()

    preference_map = {
        pref.preference_type: {
            "type": pref.preference_type,
            "value": pref.preference_value,
            "source": pref.source,
            "confidence_score": pref.confidence_score,
        }
        for pref in preferences
        if pref.preference_type
    }

    derived_candidates = {}
    for row in sorted(stay_pref_rows, key=lambda r: r.cnt or 0, reverse=True):
        for pref_type, value in {
            "floor": row.floor,
            "stay_type": row.stay_type,
            "pricing_mode": row.pricing_mode,
            "vehicle": row.vehicle,
        }.items():
            if value is not None and pref_type not in derived_candidates:
                derived_candidates[pref_type] = value

    for pref_type, value in derived_candidates.items():
        if value is not None and pref_type not in preference_map:
            preference_map[pref_type] = {
                "type": pref_type,
                "value": value,
                "source": "history",
                "confidence_score": None,
            }

    preference_order = ["branch", "room", "payment", "floor", "stay_type", "pricing_mode", "vehicle"]
    profile_preferences = sorted(
        preference_map.values(),
        key=lambda pref: (
            preference_order.index(pref["type"]) if pref["type"] in preference_order else len(preference_order),
            pref["type"],
        ),
    )

    # preferences already loaded via selectinload above

    # Get all tiers for journey visualization
    tier_journey = all_tiers

    return JSONResponse({
        "guest": {
            "id": guest.id,
            "full_name": guest.full_name,
            "phone": guest.phone,
            "email": guest.email,
            "cccd": guest.cccd,
            "cccd_expire_date": guest.id_expire.isoformat() if guest.id_expire else None,
            "date_of_birth": guest.date_of_birth.isoformat() if guest.date_of_birth else None,
            "gender": guest.gender,
            "nationality": guest.nationality,
            "address": guest.default_address,
            "default_address": guest.default_address,
            "first_seen_at": guest.first_seen_at.isoformat() if guest.first_seen_at else None,
            "last_seen_at": guest.last_seen_at.isoformat() if guest.last_seen_at else None,
            "is_blacklisted": guest.is_blacklisted,
            "has_unpaid_debt": risk_flags["has_unpaid_debt"],
            "unpaid_debt_amount": risk_flags["unpaid_debt_amount"],
            "risk_flags": risk_flags,
            "blacklist_info": blacklist_info,
            "tags": guest.tags or [],
        },
        "stats": {
            "total_stays": total_stays,
            "total_nights": int(total_nights) if total_nights else 0,
            "total_spent": float(total_spent),
            "total_spent_display": f"{float(total_spent):,.0f}",
            "avg_per_stay": round(avg_per_stay, 0),
            "avg_per_stay_display": f"{round(avg_per_stay, 0):,.0f}",
            "total_paid": float(total_spent),
            "total_debt": float(total_debt),
            "unpaid_debt": risk_flags["unpaid_debt_amount"],
        },
        "membership": {
            "tier": current_tier.value,
            "tier_display": tier_names.get(current_tier.value, current_tier.value),
            "total_spent": float(membership.total_spent or Decimal("0")) if membership else float(total_spent),
            "total_stays": total_stays,
            "total_nights": int(total_nights) if total_nights else 0,
            "total_debt": float(total_debt),
            "loyalty_points": int(current_points),
            "loyalty_points_display": f"{int(current_points):,}",
            "tier_updated_at": membership.tier_updated_at.isoformat() if membership and membership.tier_updated_at else None,
            "benefits": benefits,
            "next_tier": next_tier_info,
            "tier_journey": tier_journey,
            "favorite_branch": favorite_branch_name,
            "favorite_room_type": favorite_room_type,
            "preferred_payment_method": preferred_payment_method,
        },
        "profile": {
            "favorite": {
                "branch": favorite_branch_name,
                "room_type": favorite_room_type,
                "payment_method": preferred_payment_method,
            },
            "preferences": profile_preferences,
            "notes": None,  # Can be extended later
        },
    })


# ====================================================================
# GUEST STAY HISTORIES
# ====================================================================

@router.get("/api/pms/crm/guests/{guest_id}/co-guests", tags=["PMS - CRM"])
def api_get_guest_co_guests(
    request: Request,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """
    Lấy danh sách khách cùng ở với khách này dựa trên GuestStayMapping.
    Trả về thông tin về các khách đã từng ở cùng phòng với khách này.
    """
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    from ...db.models import GuestStayMapping
    # Get all stay_ids where this guest stayed
    my_mappings = db.query(GuestStayMapping.stay_id).filter(
        GuestStayMapping.guest_id == guest_id
    ).all()
    stay_ids = [m.stay_id for m in my_mappings]

    if not stay_ids:
        return JSONResponse({
            "guest_id": guest_id,
            "guest_name": guest.full_name,
            "co_guests": [],
            "total_co_guests": 0,
        })

    # Find all other guests who stayed in these same stays
    co_guest_records = (
        db.query(
            GuestStayMapping.guest_id,
            GuestStayMapping.stay_id,
            GuestStayMapping.room_number,
            GuestStayMapping.check_in_at,
            GuestStayMapping.check_out_at,
            GuestStayMapping.is_primary,
            Guest.full_name,
            Guest.phone,
            Guest.cccd,
        )
        .join(Guest, Guest.id == GuestStayMapping.guest_id)
        .filter(GuestStayMapping.stay_id.in_(stay_ids))
        .filter(GuestStayMapping.guest_id != guest_id)
        .filter(Guest.deleted_at.is_(None))
        .order_by(GuestStayMapping.check_in_at.desc())
        .all()
    )

    # Group by co-guest and count how many times they stayed together
    co_guest_map = {}
    for record in co_guest_records:
        cg_id = record.guest_id
        if cg_id not in co_guest_map:
            co_guest_map[cg_id] = {
                "guest_id": cg_id,
                "full_name": record.full_name,
                "phone": record.phone,
                "cccd": record.cccd,
                "stay_count": 0,
                "stays": [],
            }
        co_guest_map[cg_id]["stay_count"] += 1
        co_guest_map[cg_id]["stays"].append({
            "stay_id": record.stay_id,
            "room_number": record.room_number,
            "check_in_at": record.check_in_at.isoformat() if record.check_in_at else None,
            "check_out_at": record.check_out_at.isoformat() if record.check_out_at else None,
        })

    # Get membership info for co-guests
    co_guest_ids = list(co_guest_map.keys())
    memberships = db.query(GuestMembership).filter(
        GuestMembership.guest_id.in_(co_guest_ids)
    ).all()
    membership_map = {m.guest_id: m for m in memberships}

    results = []
    for cg_id, data in co_guest_map.items():
        membership = membership_map.get(cg_id)
        results.append({
            "guest_id": data["guest_id"],
            "full_name": data["full_name"],
            "phone": data["phone"],
            "cccd": data["cccd"],
            "tier": membership.tier.value if membership else "BASIC",
            "tier_display": _tier_display_name(membership.tier if membership else MemberTier.BASIC, db),
            "total_stays": membership.total_stays if membership else 0,
            "total_spent": float(membership.total_spent) if membership else 0,
            "stay_count": data["stay_count"],
            "stays": data["stays"],
        })

    # Sort by stay_count descending (most frequently stayed together)
    results.sort(key=lambda x: x["stay_count"], reverse=True)

    return JSONResponse({
        "guest_id": guest_id,
        "guest_name": guest.full_name,
        "co_guests": results,
        "total_co_guests": len(results),
    })


@router.get("/api/pms/crm/guests/{guest_id}/stays", tags=["PMS - CRM"])
def api_get_guest_stays(
    request: Request,
    guest_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    branch_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Lấy lịch sử lưu trú của khách (ưu tiên GuestStaySummary, fallback về HotelStay)
    """
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    # Try GuestStaySummary first
    q = db.query(GuestStaySummary).filter(GuestStaySummary.guest_id == guest_id)
    if branch_id:
        q = q.filter(GuestStaySummary.branch_id == branch_id)

    total = q.count()
    summaries = q.order_by(GuestStaySummary.check_in_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    # If no summary data, fallback to HotelStay
    if total == 0:
        stay_q = db.query(HotelStay).join(
            HotelGuest, HotelGuest.stay_id == HotelStay.id
        ).filter(HotelGuest.guest_id == guest_id)
        
        total = stay_q.count()
        stays = stay_q.order_by(HotelStay.check_in_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()

        # Get branch and room data
        branch_ids = list(set(s.branch_id for s in stays if s.branch_id))
        branch_map = {b.id: b.name for b in db.query(Branch).filter(Branch.id.in_(branch_ids)).all()} if branch_ids else {}
        
        room_ids = list(set(s.room_id for s in stays if s.room_id))
        room_map = {r.id: r.room_number for r in db.query(HotelRoom).filter(HotelRoom.id.in_(room_ids)).all()} if room_ids else {}

        results = []
        for s in stays:
            duration = _duration_payload(s.check_in_at, s.check_out_at)
            activities = db.query(GuestActivity).filter(
                GuestActivity.guest_id == guest_id,
                GuestActivity.stay_id == s.id,
            ).order_by(GuestActivity.created_at.desc()).limit(20).all()
            results.append({
                "id": s.id,
                "stay_id": s.id,
                "room_number": room_map.get(s.room_id),
                "room_type_name": None,
                "floor": None,
                "branch_id": s.branch_id,
                "branch_name": branch_map.get(s.branch_id),
                "check_in_at": s.check_in_at.isoformat() if s.check_in_at else None,
                "check_out_at": s.check_out_at.isoformat() if s.check_out_at else None,
                **duration,
                "nights": (s.check_out_at - s.check_in_at).days if s.check_in_at and s.check_out_at else 0,
                "total_charge": 0,
                "discount": 0,
                "deposit": 0,
                "final_amount": 0,
                "debt_amount": 0,
                "stay_type": s.stay_type.value if s.stay_type else None,
                "pricing_mode": None,
                "guest_count": 1,
                "status": s.status.value if s.status else None,
                "checkout_summary": "normal" if s.status != HotelStayStatus.ACTIVE else None,
                "payment_methods": [],
                "vehicle": None,
                "source": "pms",
                "debt_status": "none",
                "activities": [_activity_payload(a) for a in activities],
            })
        
        return JSONResponse({
            "guest_id": guest_id,
            "guest_name": guest.full_name,
            "items": results,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total else 0,
        })

    # Original logic for when we have summary data
    branch_ids = list(set(s.branch_id for s in summaries if s.branch_id))
    branches = db.query(Branch).filter(Branch.id.in_(branch_ids)).all() if branch_ids else []
    branch_map = {b.id: b.name for b in branches}

    # Batch load all activities for all stays in one query (avoid N+1)
    stay_ids = [s.stay_id for s in summaries if s.stay_id]
    all_activities = db.query(GuestActivity).filter(
        GuestActivity.guest_id == guest_id,
        GuestActivity.stay_id.in_(stay_ids),
    ).order_by(GuestActivity.created_at.desc()).all() if stay_ids else []
    activities_by_stay: dict = {}
    for a in all_activities:
        activities_by_stay.setdefault(a.stay_id, []).append(a)

    results = []
    for s in summaries:
        duration = _duration_payload(s.check_in_at, s.check_out_at)
        activities = activities_by_stay.get(s.stay_id, [])[:20]
        results.append({
            "id": s.id,
            "stay_id": s.stay_id,
            "room_number": s.room_number,
            "room_type_name": s.room_type_name,
            "floor": s.floor,
            "branch_id": s.branch_id,
            "branch_name": branch_map.get(s.branch_id),
            "check_in_at": s.check_in_at.isoformat() if s.check_in_at else None,
            "check_out_at": s.check_out_at.isoformat() if s.check_out_at else None,
            **duration,
            "nights": s.nights,
            "total_charge": float(s.total_charge) if s.total_charge else 0,
            "discount": float(s.discount) if s.discount else 0,
            "deposit": float(s.deposit) if s.deposit else 0,
            "final_amount": float(s.final_amount) if s.final_amount else 0,
            "debt_amount": float(s.debt_amount) if s.debt_amount else 0,
            "stay_type": s.stay_type,
            "pricing_mode": s.pricing_mode,
            "guest_count": s.guest_count,
            "status": s.status,
            "checkout_summary": s.checkout_summary,
            "payment_methods": s.payment_methods or [],
            "vehicle": s.vehicle,
            "source": s.source,
            "debt_status": s.debt_status,
            "activities": [_activity_payload(a) for a in activities],
        })

    return JSONResponse({
        "guest_id": guest_id,
        "guest_name": guest.full_name,
        "items": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    })


@router.get("/api/pms/crm/guests/{guest_id}/stays/{stay_id}/detail", tags=["PMS - CRM"])
def api_get_guest_stay_detail(
    request: Request,
    guest_id: int,
    stay_id: int,
    db: Session = Depends(get_db),
):
    """
    Lấy chi tiết một lần lưu trú cụ thể
    """
    user = _require_login(request)

    # Get summary
    summary = db.query(GuestStaySummary).filter(
        GuestStaySummary.guest_id == guest_id,
        GuestStaySummary.stay_id == stay_id,
    ).first()

    if not summary:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")

    # Get related data
    stay = db.query(HotelStay).filter(HotelStay.id == stay_id).first()
    branch = db.query(Branch).filter(Branch.id == summary.branch_id).first() if summary.branch_id else None

    # Get service usages for this stay
    services = db.query(GuestServiceUsage).filter(
        GuestServiceUsage.guest_id == guest_id,
        GuestServiceUsage.stay_id == stay_id,
    ).order_by(GuestServiceUsage.used_at).all()

    # Get payments for this stay
    payments = db.query(GuestPaymentSummary).filter(
        GuestPaymentSummary.guest_id == guest_id,
        GuestPaymentSummary.stay_id == stay_id,
    ).order_by(GuestPaymentSummary.paid_at).all()

    # Get activities for this stay
    activities = db.query(GuestActivity).filter(
        GuestActivity.guest_id == guest_id,
        GuestActivity.stay_id == stay_id,
    ).order_by(GuestActivity.created_at).all()

    return JSONResponse({
        "summary": {
            "id": summary.id,
            "stay_id": summary.stay_id,
            "room_number": summary.room_number,
            "room_type_name": summary.room_type_name,
            "floor": summary.floor,
            "branch_name": branch.name if branch else None,
            "check_in_at": summary.check_in_at.isoformat() if summary.check_in_at else None,
            "check_out_at": summary.check_out_at.isoformat() if summary.check_out_at else None,
            **_duration_payload(summary.check_in_at, summary.check_out_at),
            "nights": summary.nights,
            "total_charge": float(summary.total_charge) if summary.total_charge else 0,
            "discount": float(summary.discount) if summary.discount else 0,
            "deposit": float(summary.deposit) if summary.deposit else 0,
            "final_amount": float(summary.final_amount) if summary.final_amount else 0,
            "debt_amount": float(summary.debt_amount) if summary.debt_amount else 0,
            "stay_type": summary.stay_type,
            "pricing_mode": summary.pricing_mode,
            "guest_count": summary.guest_count,
            "status": summary.status,
            "payment_methods": summary.payment_methods or [],
            "vehicle": summary.vehicle,
            "source": summary.source,
            "debt_status": summary.debt_status,
        },
        "services": [
            {
                "id": s.id,
                "category": s.service_category,
                "name": s.service_name,
                "quantity": float(s.quantity) if s.quantity else 1,
                "unit_price": float(s.unit_price) if s.unit_price else 0,
                "total_amount": float(s.total_amount) if s.total_amount else 0,
                "room_number": s.room_number,
                "used_at": s.used_at.isoformat() if s.used_at else None,
            }
            for s in services
        ],
        "payments": [
            {
                "id": p.id,
                "type": p.payment_type,
                "method": p.payment_method,
                "amount": float(p.amount) if p.amount else 0,
                "transaction_code": _payment_transaction_code(db, p),
                "room_number": p.room_number,
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
                "is_voided": p.is_voided,
            }
            for p in payments
        ],
        "activities": [_activity_payload(a) for a in activities],
    })


# ====================================================================
# GUEST SERVICE USAGE
# ====================================================================

@router.get("/api/pms/crm/guests/{guest_id}/services", tags=["PMS - CRM"])
def api_get_guest_services(
    request: Request,
    guest_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Lấy lịch sử sử dụng dịch vụ
    """
    user = _require_login(request)

    # Verify guest
    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    q = db.query(GuestServiceUsage).filter(GuestServiceUsage.guest_id == guest_id)

    if category:
        q = q.filter(GuestServiceUsage.service_category == category)

    if date_from:
        try:
            df = VN_TZ.localize(datetime.fromisoformat(date_from))
            q = q.filter(GuestServiceUsage.used_at >= df)
        except:
            pass

    if date_to:
        try:
            dt = VN_TZ.localize(datetime.fromisoformat(date_to + " 23:59:59"))
            q = q.filter(GuestServiceUsage.used_at <= dt)
        except:
            pass

    total = q.count()
    usages = q.order_by(GuestServiceUsage.used_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    # Get stats
    stats = get_guest_service_stats(db, guest_id)

    # Batch fetch branches
    branch_ids = list(set(s.branch_id for s in usages if s.branch_id))
    branch_map = {}
    if branch_ids:
        branches = db.query(Branch).filter(Branch.id.in_(branch_ids)).all()
        branch_map = {b.id: b.name for b in branches}

    results = []
    for s in usages:
        results.append({
            "id": s.id,
            "stay_id": s.stay_id,
            "category": s.service_category,
            "name": s.service_name,
            "quantity": float(s.quantity) if s.quantity else 1,
            "unit_price": float(s.unit_price) if s.unit_price else 0,
            "total_amount": float(s.total_amount) if s.total_amount else 0,
            "room_number": s.room_number,
            "branch_name": branch_map.get(s.branch_id),
            "used_at": s.used_at.isoformat() if s.used_at else None,
        })

    return JSONResponse({
        "guest_id": guest_id,
        "guest_name": guest.full_name,
        "items": results,
        "stats": stats,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    })


# ====================================================================
# GUEST PAYMENT HISTORY
# ====================================================================

@router.get("/api/pms/crm/guests/{guest_id}/payments", tags=["PMS - CRM"])
def api_get_guest_payments(
    request: Request,
    guest_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    method: Optional[str] = Query(default=None),
    payment_type: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Lấy lịch sử thanh toán
    """
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    q = db.query(GuestPaymentSummary).filter(GuestPaymentSummary.guest_id == guest_id)

    if method:
        q = q.filter(GuestPaymentSummary.payment_method == method)

    if payment_type:
        q = q.filter(GuestPaymentSummary.payment_type == payment_type)

    total = q.count()
    payments = q.order_by(GuestPaymentSummary.paid_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    # Get stats
    stats = get_guest_payment_stats(db, guest_id)
    debt_q = db.query(
        func.coalesce(func.sum(GuestStaySummary.debt_amount), 0).label("total_debt")
    ).filter(
        GuestStaySummary.guest_id == guest_id,
        GuestStaySummary.debt_amount > 0,
    ).first()
    stats["total_debt"] = float(debt_q.total_debt or 0)

    results = []
    for p in payments:
        branch = db.query(Branch).filter(Branch.id == p.branch_id).first()
        results.append({
            "id": p.id,
            "stay_id": p.stay_id,
            "folio_id": p.folio_id,
            "payment_id": p.payment_id,
            "type": p.payment_type,
            "method": p.payment_method,
            "amount": float(p.amount) if p.amount else 0,
            "transaction_code": _payment_transaction_code(db, p),
            "room_number": p.room_number,
            "branch_name": branch.name if branch else None,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "is_voided": p.is_voided,
            "void_reason": p.void_reason,
        })

    return JSONResponse({
        "guest_id": guest_id,
        "guest_name": guest.full_name,
        "items": results,
        "stats": stats,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    })


# ====================================================================
# GUEST TIMELINE (Activities)
# ====================================================================

@router.get("/api/pms/crm/guests/{guest_id}/timeline", tags=["PMS - CRM"])
def api_get_guest_timeline_full(
    request: Request,
    guest_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    group: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Lấy timeline đầy đủ (hoạt động, thanh toán, dịch vụ)
    """
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    # Get activities
    q = db.query(GuestActivity).filter(GuestActivity.guest_id == guest_id)
    if group:
        q = q.filter(GuestActivity.activity_group == group)

    activities = q.order_by(GuestActivity.created_at.desc()).offset(offset).limit(limit).all()

    # Stats
    stats = get_guest_stats(db, guest_id)

    results = []
    for a in activities:
        results.append(_activity_payload(a))

    return JSONResponse({
        "guest_id": guest_id,
        "guest_name": guest.full_name,
        "items": results,
        "stats": stats,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "count": len(results),
        },
    })


# ====================================================================
# MEMBERSHIP MANAGEMENT
# ====================================================================

@router.get("/api/pms/memberships/tiers", tags=["PMS - CRM"])
def api_get_membership_tiers(request: Request, db: Session = Depends(get_db)):
    """
    Lấy danh sách bậc thành viên và quyền lợi
    """
    user = _require_login(request)

    tiers = []
    thresholds = get_membership_thresholds(db)
    for tier in MemberTier:
        threshold = float(thresholds.get(tier, Decimal("0")))
        tiers.append({
            "tier": tier.value,
            "tier_display": _tier_display_name(tier, db),
            "threshold": threshold,
            "threshold_display": f"{threshold:,.0f} điểm" if threshold > 0 else "Miễn phí",
            "benefits": get_tier_benefits(tier, db),
        })

    return JSONResponse({"tiers": tiers})


@router.get("/api/pms/crm/settings/membership", tags=["PMS - CRM"])
def api_get_crm_membership_settings(request: Request, db: Session = Depends(get_db)):
    _require_login(request)
    return JSONResponse(get_membership_settings(db))


@router.put("/api/pms/crm/settings/membership", tags=["PMS - CRM"])
def api_update_crm_membership_settings(
    request: Request,
    payload: CrmMembershipSettingsPayload,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if not _is_manager(user):
        raise HTTPException(status_code=403, detail="Bạn không có quyền cập nhật thiết lập CRM")
    try:
        settings = save_membership_settings(db, payload.model_dump(), user_id=user.get("id"))
        db.commit()
        _clear_crm_caches()
        return JSONResponse({"status": "success", "settings": settings})
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/pms/crm/guests/{guest_id}/membership", tags=["PMS - CRM"])
def api_get_guest_membership(
    request: Request,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """
    Lấy thông tin thành viên của khách
    """
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    membership = db.query(GuestMembership).filter(
        GuestMembership.guest_id == guest_id
    ).first()

    if not membership:
        return JSONResponse({
            "guest_id": guest_id,
            "membership": None,
            "message": "Khách chưa có thông tin thành viên",
        })

    total_spent = db.query(
        func.coalesce(func.sum(
            func.coalesce(GuestStaySummary.final_amount, 0) - func.coalesce(GuestStaySummary.debt_amount, 0)
        ), 0)
    ).filter(
        GuestStaySummary.guest_id == guest_id
    ).scalar() or Decimal("0")

    # Calculate tier dựa trên điểm thưởng
    current_tier = calculate_tier(membership.points_balance or Decimal("0"), db)
    current_points = membership.points_balance or 0

    # Progress to next tier
    tier_order = list(MemberTier)
    current_idx = tier_order.index(current_tier)
    next_tier = tier_order[current_idx + 1] if current_idx < len(tier_order) - 1 else None

    next_tier_info = None
    if next_tier and current_tier != MemberTier.VIP:
        threshold = float(get_membership_thresholds(db)[next_tier])
        remaining = threshold - current_points
        next_tier_info = {
            "tier": next_tier.value,
            "tier_display": _tier_display_name(next_tier, db),
            "threshold": threshold,
            "remaining": max(0, remaining),
            "progress_percent": min(100, (current_points / threshold) * 100) if threshold > 0 else 100,
        }

    return JSONResponse({
        "guest_id": guest_id,
        "guest_name": guest.full_name,
        "membership": {
            "tier": membership.tier.value,
            "tier_display": _tier_display_name(membership.tier, db),
            "total_stays": membership.total_stays,
            "total_nights": membership.total_nights,
            "total_spent": float(membership.total_spent or Decimal("0")),
            "total_deposit": float(membership.total_deposit) if membership.total_deposit else 0,
            "total_debt": float(membership.total_debt) if membership.total_debt else 0,
            "loyalty_points": membership.loyalty_points,
            "points_balance": membership.points_balance or 0,
            "points_redeemed": membership.points_redeemed,
            "favorite_branch": membership.favorite_branch.name if membership.favorite_branch else None,
            "favorite_room_type": membership.favorite_room_type,
            "preferred_payment_method": membership.preferred_payment_method,
            "tier_updated_at": membership.tier_updated_at.isoformat() if membership.tier_updated_at else None,
            "benefits": get_tier_benefits(membership.tier, db),
        },
        "next_tier": next_tier_info,
        "current_points": current_points,
    })


@router.patch("/api/pms/crm/guests/{guest_id}/blacklist", tags=["PMS - CRM"])
def api_update_guest_blacklist(
    request: Request,
    guest_id: int,
    payload: GuestBlacklistPayload,
    db: Session = Depends(get_db),
):
    """Đánh dấu hoặc gỡ khách khỏi danh sách đen."""
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id, Guest.deleted_at.is_(None)).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    guest.is_blacklisted = payload.is_blacklisted
    guest.updated_by = user.get("id")
    branch_id = _active_branch_id(request, db)

    tags = list(guest.tags or [])
    if payload.is_blacklisted and "BLACKLIST" not in tags:
        tags.append("BLACKLIST")
    if not payload.is_blacklisted:
        tags = [t for t in tags if t != "BLACKLIST"]
    guest.tags = tags

    log_activity(
        db=db,
        guest_id=guest.id,
        activity_type="BLACKLISTED" if payload.is_blacklisted else "PROFILE_UPDATED",
        activity_group=ActivityGroup.SYSTEM,
        title="Đưa vào danh sách đen" if payload.is_blacklisted else "Gỡ khỏi danh sách đen",
        description=payload.reason or ("Khách được đưa vào danh sách đen" if payload.is_blacklisted else "Khách được gỡ khỏi danh sách đen"),
        branch_id=branch_id,
        actor_type=ActorType.USER,
        actor_id=user.get("id"),
        source=Source.PMS,
        extra_data={"is_blacklisted": payload.is_blacklisted, "reason": payload.reason},
    )

    db.commit()
    _clear_crm_caches()
    return JSONResponse({
        "guest_id": guest.id,
        "is_blacklisted": guest.is_blacklisted,
        "risk_flags": get_guest_risk_flags(db, guest.id),
    })


# ====================================================================
# GUEST LIST BY TIER
# ====================================================================

@router.get("/api/pms/crm/guests/tier/{tier}", tags=["PMS - CRM"])
def api_get_guests_by_tier(
    request: Request,
    tier: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Lấy danh sách khách theo bậc thành viên
    """
    user = _require_login(request)

    try:
        tier_enum = MemberTier(tier)
    except ValueError:
        raise HTTPException(status_code=400, detail="Bậc thành viên không hợp lệ")

    # Get guest IDs with this tier
    subq = db.query(GuestMembership.guest_id).filter(
        GuestMembership.tier == tier_enum
    ).subquery()

    q = db.query(Guest).filter(Guest.id.in_(subq), Guest.deleted_at.is_(None))
    total = q.count()

    guests = q.order_by(Guest.last_seen_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    results = []
    for g in guests:
        membership = db.query(GuestMembership).filter(
            GuestMembership.guest_id == g.id
        ).first()

        results.append({
            "id": g.id,
            "full_name": g.full_name,
            "phone": g.phone,
            "cccd": g.cccd,
            "nationality": g.nationality,
            "is_blacklisted": g.is_blacklisted,
            "last_seen_at": g.last_seen_at.isoformat() if g.last_seen_at else None,
            "total_stays": membership.total_stays if membership else 0,
            "total_spent": float(membership.total_spent) if membership else 0,
            "loyalty_points": membership.points_balance if membership else 0,
        })

    return JSONResponse({
        "tier": tier,
        "tier_display": _tier_display_name(tier_enum, db),
        "items": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
    })


# ====================================================================
# ANALYTICS & REPORTS
# ====================================================================

@router.get("/api/pms/crm/stats", tags=["PMS - CRM"])
def api_crm_stats(
    request: Request,
    q: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Thống kê CRM dashboard - alias cho /stats/overview
    """
    user = _require_login(request)

    q_clean = q.strip().lower() if q else ""
    cache_key = ("stats", q_clean)
    cached = _json_cache_get(_CRM_SEARCH_CACHE, cache_key, _CRM_SEARCH_STATS_TTL_SECONDS)
    if cached:
        return JSONResponse(cached)

    # Search filter
    guest_filter = []
    if q_clean:
        search_filters = [
            Guest.normalized_name.like(f"{q_clean}%"),
            Guest.phone.like(f"{q_clean}%"),
            Guest.cccd.like(f"{q_clean}%"),
            Guest.email.like(f"{q_clean}%"),
            Guest.full_name.ilike(f"{q_clean}%"),
        ]
        if len(q_clean) >= 3:
            search_filters.append(Guest.full_name.ilike(f"%{q_clean}%"))
        guest_filter = [or_(*search_filters)]

    total_guests_q = db.query(func.count(Guest.id)).filter(Guest.deleted_at.is_(None))
    if guest_filter:
        total_guests_q = total_guests_q.filter(*guest_filter)
    total_guests = total_guests_q.scalar() or 0

    # Guests by tier and loyalty totals from membership aggregate table.
    membership_stats = db.query(
        GuestMembership.tier,
        func.count(GuestMembership.id).label("count"),
        func.coalesce(func.sum(GuestMembership.points_balance), 0).label("total_points"),
        func.coalesce(func.sum(GuestMembership.total_stays), 0).label("total_stays"),
        func.coalesce(func.sum(GuestMembership.total_nights), 0).label("total_nights"),
        func.coalesce(func.sum(GuestMembership.total_spent), 0).label("total_revenue"),
    ).join(
        Guest, Guest.id == GuestMembership.guest_id
    ).filter(
        Guest.deleted_at.is_(None)
    )
    if guest_filter:
        membership_stats = membership_stats.filter(*guest_filter)
    membership_rows = membership_stats.group_by(GuestMembership.tier).all()

    tier_counts = {tier.value: 0 for tier in MemberTier}
    total_points = 0
    total_stays = 0
    total_nights = 0
    total_revenue = Decimal("0")
    for row in membership_rows:
        tier_key = row.tier.value if hasattr(row.tier, "value") else str(row.tier)
        tier_counts[tier_key] = row.count or 0
        total_points += row.total_points or 0
        total_stays += row.total_stays or 0
        total_nights += row.total_nights or 0
        total_revenue += row.total_revenue or Decimal("0")

    # Historical behavior: this endpoint has no date window, so "new" equals
    # current filtered guest count. Avoid a second identical COUNT(*).
    new_guests = total_guests

    avg_points = round(float(total_points) / total_guests, 0) if total_guests > 0 else 0
    avg_per_stay = float(total_revenue) / total_stays if total_stays > 0 else 0

    payload = {
        "total_guests": total_guests,
        "tier_distribution": tier_counts,
        "total_stays": int(total_stays),
        "total_revenue": float(total_revenue),
        "total_nights": int(total_nights) if total_nights else 0,
        "avg_per_stay": round(avg_per_stay, 0),
        "new_guests": new_guests,
        "repeat_guests": 0,
        "total_points": int(total_points),
        "avg_points": int(avg_points),
        "vip_count": tier_counts.get(MemberTier.VIP.value, 0),
    }
    _json_cache_set(_CRM_SEARCH_CACHE, cache_key, payload)
    return JSONResponse(payload)


@router.get("/api/pms/crm/stats/overview", tags=["PMS - CRM"])
def api_crm_overview_stats(
    request: Request,
    branch_id: Optional[int] = Query(default=None),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Thống kê tổng quan CRM
    """
    user = _require_login(request)

    cache_key = (branch_id, date_from or "", date_to or "")
    now_ts = time.time()
    cached = _CRM_STATS_CACHE.get(cache_key)
    if cached and (now_ts - cached[0]) < _CRM_STATS_TTL_SECONDS:
        return JSONResponse(cached[1])

    # Base filters
    filter_args = []
    if branch_id:
        filter_args.append(GuestStaySummary.branch_id == branch_id)
    if date_from:
        try:
            df = VN_TZ.localize(datetime.fromisoformat(date_from))
            filter_args.append(GuestStaySummary.check_in_at >= df)
        except:
            pass
    if date_to:
        try:
            dt = VN_TZ.localize(datetime.fromisoformat(date_to + " 23:59:59"))
            filter_args.append(GuestStaySummary.check_in_at <= dt)
        except:
            pass

    # Total guests
    total_guests = db.query(func.count(Guest.id)).filter(
        Guest.deleted_at.is_(None)
    ).scalar() or 0

    # Guests by tier
    membership_rows = db.query(
        GuestMembership.tier,
        func.count(GuestMembership.id).label("count"),
    ).join(
        Guest, Guest.id == GuestMembership.guest_id
    ).filter(
        Guest.deleted_at.is_(None)
    ).group_by(GuestMembership.tier).all()
    tier_counts = {tier.value: 0 for tier in MemberTier}
    for row in membership_rows:
        tier_key = row.tier.value if hasattr(row.tier, "value") else str(row.tier)
        tier_counts[tier_key] = row.count or 0

    # Total stays & revenue
    aggregate_row = db.query(
        func.count(GuestStaySummary.id).label("total_stays"),
        func.coalesce(func.sum(
            func.coalesce(GuestStaySummary.final_amount, 0) - func.coalesce(GuestStaySummary.debt_amount, 0)
        ), 0).label("total_revenue"),
        func.coalesce(func.sum(GuestStaySummary.nights), 0).label("total_nights"),
    ).filter(*filter_args).first() if filter_args else db.query(
        func.count(GuestStaySummary.id).label("total_stays"),
        func.coalesce(func.sum(
            func.coalesce(GuestStaySummary.final_amount, 0) - func.coalesce(GuestStaySummary.debt_amount, 0)
        ), 0).label("total_revenue"),
        func.coalesce(func.sum(GuestStaySummary.nights), 0).label("total_nights"),
    ).first()

    total_stays = aggregate_row.total_stays or 0
    total_revenue = aggregate_row.total_revenue or Decimal("0")
    total_nights = aggregate_row.total_nights or 0

    # Average
    avg_per_stay = float(total_revenue) / total_stays if total_stays > 0 else 0
    avg_per_night = float(total_revenue) / total_nights if total_nights > 0 else 0

    # New guests this period
    new_guests = db.query(func.count(Guest.id))
    if date_from:
        try:
            df = VN_TZ.localize(datetime.fromisoformat(date_from))
            new_guests = new_guests.filter(Guest.created_at >= df)
        except:
            pass
    if date_to:
        try:
            dt = VN_TZ.localize(datetime.fromisoformat(date_to + " 23:59:59"))
            new_guests = new_guests.filter(Guest.created_at <= dt)
        except:
            pass
    new_guests = new_guests.scalar() or 0

    # Repeat guests (more than 1 stay). Reuse membership aggregate instead of grouping
    # the full stay summary table on every dashboard load.
    repeat_guests = db.query(func.count(GuestMembership.id)).join(
        Guest, Guest.id == GuestMembership.guest_id
    ).filter(
        Guest.deleted_at.is_(None),
        GuestMembership.total_stays > 1,
    ).scalar() or 0

    payload = {
        "total_guests": total_guests,
        "tier_distribution": tier_counts,
        "total_stays": total_stays,
        "total_revenue": float(total_revenue),
        "total_nights": int(total_nights) if total_nights else 0,
        "avg_per_stay": round(avg_per_stay, 0),
        "avg_per_night": round(avg_per_night, 0),
        "new_guests": new_guests,
        "repeat_guests": repeat_guests,
    }
    _CRM_STATS_CACHE[cache_key] = (now_ts, payload)
    if len(_CRM_STATS_CACHE) > 64:
        oldest = min(_CRM_STATS_CACHE.items(), key=lambda kv: kv[1][0])[0]
        _CRM_STATS_CACHE.pop(oldest, None)
    return JSONResponse(payload)


@router.post("/api/pms/crm/admin/rebuild-memberships", tags=["PMS - CRM - Admin"])
def api_crm_rebuild_memberships(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Tính lại toàn bộ stats và tier cho tất cả thành viên dựa trên lịch sử (dành cho Admin).
    """
    user = _require_login(request)
    
    # Ở đây có thể add thêm check quyền admin: if not user.get("is_admin"): raise ...

    try:
        from ...services.guest_crm_service import recalculate_all_memberships, batch_create_stay_summaries
        
        # 1. Create missing stay summaries from past completed stays
        summaries_result = batch_create_stay_summaries(db)
        
        # 2. Recalculate stats based on all stay summaries
        result = recalculate_all_memberships(db)
        _clear_crm_caches()
        
        return JSONResponse({
            "status": "success",
            "message": f"Đã tính toán lại dữ liệu cho {result.get('memberships_updated', 0)} khách hàng. Tạo mới {summaries_result.get('total_created', 0)} lịch sử lưu trú.",
            "data": {
                "memberships": result,
                "summaries": summaries_result
            },
        })
    except Exception as e:
        import traceback
        return JSONResponse(
            status_code=500,
            content={"detail": f"Lỗi tính toán: {str(e)}\n{traceback.format_exc()}"}
        )

# ====================================================================
# GUEST INVOICE INFO & HISTORY
# ====================================================================

@router.get("/api/pms/crm/guests/{guest_id}/invoice", tags=["PMS - CRM"])
def api_get_guest_invoice(
    request: Request,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """Lấy thông tin xuất hoá đơn của khách."""
    _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id, Guest.deleted_at.is_(None)).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    # Invoice info stored on Guest master
    invoice_info = {
        "tax_code": guest.tax_code or "",
        "invoice_contact": guest.invoice_contact or "",
        "company_name": guest.company_name or "",
        "company_address": guest.company_address or "",
    }

    return JSONResponse({
        "guest_id": guest_id,
        "invoice_info": invoice_info,
    })


@router.patch("/api/pms/crm/guests/{guest_id}/invoice", tags=["PMS - CRM"])
def api_update_guest_invoice(
    request: Request,
    guest_id: int,
    payload: GuestInvoicePayload,
    db: Session = Depends(get_db),
):
    """Cập nhật thông tin xuất hoá đơn trên hồ sơ khách."""
    user = _require_login(request)

    guest = db.query(Guest).filter(Guest.id == guest_id, Guest.deleted_at.is_(None)).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    fields = payload.model_fields_set
    if "tax_code" in fields:
        guest.tax_code = _clean_guest_text(payload.tax_code, 50)
    if "invoice_contact" in fields:
        guest.invoice_contact = _clean_guest_text(payload.invoice_contact, 255)
    if "company_name" in fields:
        guest.company_name = _clean_guest_text(payload.company_name, 255)
    if "company_address" in fields:
        guest.company_address = _clean_guest_text(payload.company_address)

    guest.updated_by = user.get("id")
    db.commit()
    _clear_crm_caches()

    return JSONResponse({
        "guest_id": guest_id,
        "invoice_info": {
            "tax_code": guest.tax_code or "",
            "invoice_contact": guest.invoice_contact or "",
            "company_name": guest.company_name or "",
            "company_address": guest.company_address or "",
        },
    })


# ====================================================================
# HELPER FUNCTIONS
# ====================================================================

def _tier_display_names(db: Optional[Session] = None) -> dict:
    settings = get_membership_settings(db) if db else {"tiers": []}
    names = {
        MemberTier.BASIC.value: "Khách thường",
        MemberTier.SILVER.value: "Thành viên Bạc",
        MemberTier.GOLD.value: "Thành viên Vàng",
        MemberTier.PLATINUM.value: "Thành viên Bạch Kim",
        MemberTier.VIP.value: "Khách VIP",
    }
    for item in settings.get("tiers", []):
        tier_value = item.get("tier")
        if tier_value:
            names[tier_value] = item.get("display_name") or tier_value
    return names


def _tier_display_name(tier: MemberTier, db: Optional[Session] = None) -> str:
    """Lấy tên hiển thị của tier"""
    tier_value = tier.value if hasattr(tier, "value") else str(tier)
    return _tier_display_names(db).get(tier_value, tier_value)
