# app/api/pms/pms_stays.py
"""
PMS Stays API - Stay management (detail, update, transfer)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, time
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request, Query
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from sqlalchemy import and_, func, or_, union
from sqlalchemy.sql import literal_column
from sqlalchemy.orm import Session, joinedload

from ...db.models import (
    Branch,
    DebtRecord,
    Folio,
    FolioStatus,
    Guest,
    HotelRoom,
    HotelRoomType,
    HotelStay,
    HotelStayStatus,
    HotelGuest,
    Booking,
    RefundRecord,
    FolioTransaction,
    FolioTransactionType as FTT,
    FolioTransactionCategory as FTC,
)
from ...db.session import get_db
from ...services.pricing_service import calculate_room_price, calculate_full_charge, detect_pricing_mode_from_breakdown, MODE_TO_STAY_TYPE, money
from ...services.room_inventory_service import InventoryService, iter_stay_dates, _stay_occupies_date
from .pms_helpers import (
    _require_login, _is_admin, _active_branch, _now_vn,
    _get_occupied_rooms_for_dates, _room_to_dict, VN_TZ
)
from .vn_address import convert_old_to_new_sync
from .guest_activity import log_room_change, log_guest_added_to_stay, log_guest_edited

router = APIRouter()
logger = logging.getLogger(__name__)


# ── API: Stay History ──────────────────────────────────────────────────────
# NOTE: Must be defined BEFORE /api/pms/stays/{stay_id} to avoid path conflict

@router.get("/api/pms/stays/{stay_id}/pricing-preview", tags=["PMS"])
def api_stay_pricing_preview(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
):
    """
    Tính giá dự kiến cho tab Phòng.
    • Hourly / AUTO → dùng thời điểm hiện tại (now) làm check_out
    • Có check_out_at dự kiến → dùng check_out_at
    Luôn dùng PricingEngine (time-slicing) qua calculate_full_charge.
    """
    user = _require_login(request)

    stay = (
        db.query(HotelStay)
        .options(joinedload(HotelStay.room).joinedload(HotelRoom.room_type_obj))
        .filter(HotelStay.id == stay_id)
        .first()
    )
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")

    room = stay.room
    rt = room.room_type_obj if room else None
    if not rt:
        raise HTTPException(status_code=400, detail="Thiếu thông tin loại phòng")

    now = _now_vn()

    # ── Xác định check_out tính giá ──────────────────────────────
    # Nếu check_out_at đã qua (nhỏ hơn now) → dùng now (tính giá đến thời điểm hiện tại)
    # Nếu không (ACTIVE) → dùng thời điểm hiện tại (live tính giờ)
    if stay.check_out_at and stay.check_out_at >= now:
        end_time = stay.check_out_at
    else:
        end_time = now

    # ── Xác định pricing mode ──────────────────────────────────────
    # Đã checkout → dùng pricing_mode_final nếu có, không thì AUTO
    if stay.status == HotelStayStatus.CHECKED_OUT and stay.pricing_mode_final:
        effective_mode = stay.pricing_mode_final
    else:
        effective_mode = stay.pricing_mode_initial or "AUTO"


    # ── Tính giá qua PricingEngine ───────────────────────────────
    pms_mode = "AUTO" if effective_mode == "OTA_MANUAL" else effective_mode
    total, breakdown = calculate_full_charge(
        pms_mode, rt, stay.check_in_at, end_time
    )
    pricing_mode = detect_pricing_mode_from_breakdown(breakdown) or effective_mode
    pms_reference_total = total
    ota_actual_total = None
    is_ota_manual = effective_mode == "OTA_MANUAL" and stay.total_price and stay.total_price > 0
    if is_ota_manual:
        ota_actual_total = money(stay.total_price)
        total = ota_actual_total

    # ── Tính projected_balance từ Folio hiện tại ────────────────
    # projected_balance = (room_charge + folio_charges) - discounts - effective_paid
    folios = (
        db.query(Folio)
        .options(joinedload(Folio.transactions))
        .filter(Folio.stay_id == stay_id)
        .all()
    )

    effective_paid = Decimal("0")
    deposit_used = Decimal("0")
    existing_service_charges = Decimal("0")
    existing_surcharge_charges = Decimal("0")
    existing_discounts = Decimal("0")
    for folio in folios:
        for tx in folio.transactions:
            if tx.is_voided:
                continue
            if tx.amount < 0:
                amt = abs(tx.amount)
                if tx.transaction_type == FTT.DEPOSIT_USED:
                    deposit_used += amt
                effective_paid += amt
            elif tx.category == FTC.DISCOUNT:
                existing_discounts += abs(tx.amount)
            elif tx.category == FTC.SERVICE:
                existing_service_charges += tx.amount
            elif tx.category == FTC.SURCHARGE or tx.category == FTC.OTHER:
                existing_surcharge_charges += tx.amount
            else:
                existing_service_charges += tx.amount

    total_charges = existing_service_charges + existing_surcharge_charges
    projected_balance = total + total_charges - existing_discounts - effective_paid

    return JSONResponse({
        "total": float(total),
        "room_charge": float(total),
        "breakdown": [
            {**b, "amount": float(b.get("amount", 0))}
            for b in breakdown
        ],
        "mode": pricing_mode,
        "end_time": end_time.isoformat() if end_time else None,
        "projected_balance": round(float(projected_balance), 2),
        "deposit_used": round(float(deposit_used), 2),
        "effective_paid": round(float(effective_paid), 2),
        "existing_charges": round(float(total_charges), 2),
        "existing_service_charges": round(float(existing_service_charges), 2),
        "existing_surcharge_charges": round(float(existing_surcharge_charges), 2),
        "existing_discounts": round(float(existing_discounts), 2),
        "ota_price_mode": "manual_channel_total" if is_ota_manual else None,
        "ota_actual_total": float(ota_actual_total) if ota_actual_total is not None else None,
        "pms_reference_total": float(pms_reference_total) if is_ota_manual else None,
        "ota_price_delta": float(ota_actual_total - pms_reference_total) if ota_actual_total is not None else None,
    })


@router.get("/api/pms/stays/history", tags=["PMS"])
def api_stays_history(
    request: Request,
    summary_filter: str = Query(
        default="all",
        description="all | debt | refund | paid",
    ),
    debt_status: str = Query(default=None),
    refund_status: str = Query(default=None),
    branch_id: Optional[int] = Query(default=None),
    date_from: str = Query(default=None),
    date_to: str = Query(default=None),
    date_field: str = Query(default="check_in", description="check_in | check_out | created"),
    search: str = Query(default=None, description="Search by guest name or CCCD"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Lấy lịch sử lưu trú (đã checkout).
    
    - Lọc theo ngày: date_field = 'check_in' (mặc định) | 'check_out' | 'created'
    - Search: tìm theo tên khách hoặc số CCCD
    - Stats: đếm theo debt/refund/paid trong khoảng date đã lọc
    """
    _require_login(request)
    branch_code = _active_branch(request)
    branch_id_from_session = None
    if branch_code and branch_code not in ("HỆ THỐNG", "Chưa phân bổ"):
        branch_obj = db.query(Branch).filter(Branch.branch_code == branch_code).first()
        branch_id_from_session = branch_obj.id if branch_obj else None
    effective_branch = branch_id or branch_id_from_session

    # Xác định trường ngày để lọc
    date_field_map = {
        "check_in": HotelStay.check_in_at,
        "check_out": HotelStay.check_out_at,
        "created": HotelStay.created_at,
    }
    date_filter_field = date_field_map.get(date_field, HotelStay.check_in_at)

    latest_folio_sq = (
        db.query(Folio.stay_id, func.max(Folio.id).label("mx"))
        .group_by(Folio.stay_id)
        .subquery()
    )

    q = (
        db.query(HotelStay)
        .options(
            joinedload(HotelStay.room).joinedload(HotelRoom.room_type_obj),
            joinedload(HotelStay.guests),
        )
        .outerjoin(latest_folio_sq, latest_folio_sq.c.stay_id == HotelStay.id)
        .outerjoin(Folio, Folio.id == latest_folio_sq.c.mx)
        .filter(HotelStay.status != HotelStayStatus.ACTIVE)
    )

    # Search by guest name or CCCD — dùng exists() để tránh DuplicateAlias khi distinct()
    if search and len(search.strip()) >= 2:
        search_term = f"%{search.strip()}%"
        guest_subq = (
            db.query(HotelGuest.id)
            .filter(
                HotelGuest.stay_id == HotelStay.id,
                or_(
                    HotelGuest.full_name.ilike(search_term),
                    HotelGuest.cccd.ilike(search_term),
                )
            )
            .exists()
            .correlate(HotelStay)
        )
        q = q.filter(guest_subq)

    if effective_branch:
        q = q.filter(HotelStay.branch_id == effective_branch)

    if date_from:
        try:
            df = VN_TZ.localize(datetime.fromisoformat(date_from))
            q = q.filter(date_filter_field >= df)
        except Exception:
            pass

    if date_to:
        try:
            dt = VN_TZ.localize(datetime.fromisoformat(date_to + " 23:59:59"))
            q = q.filter(date_filter_field <= dt)
        except Exception:
            pass

    sf = (summary_filter or "all").lower()
    if sf == "debt":
        q = q.filter(
            and_(
                Folio.id.isnot(None),
                Folio.debt_status.isnot(None),
                Folio.debt_status.notin_(["none", "settled"]),
            )
        )
    elif sf == "refund":
        # refund = đã hoàn tiền: balance < -0.5 (tính từ FolioTransaction — đúng như summary_status)
        # Không dùng Folio.balance vì có thể stale; dùng subquery tính từ transactions
        refund_balance_subq = (
            db.query(
                FolioTransaction.folio_id,
                func.coalesce(func.sum(
                    func.abs(FolioTransaction.amount)
                ), 0).label("net")
            )
            .filter(
                FolioTransaction.folio_id == Folio.id,
                FolioTransaction.is_voided == False,
                FolioTransaction.amount < 0,
                FolioTransaction.transaction_type.in_([FTT.PAYMENT, FTT.DEPOSIT_USED])
            )
            .group_by(FolioTransaction.folio_id)
            .subquery()
        )
        refund_charge_subq = (
            db.query(
                FolioTransaction.folio_id,
                func.coalesce(func.sum(FolioTransaction.amount), 0).label("chg")
            )
            .filter(
                FolioTransaction.folio_id == Folio.id,
                FolioTransaction.is_voided == False,
                FolioTransaction.amount > 0,
                FolioTransaction.transaction_type.notin_([FTT.REFUND, FTT.REFUND_PAYMENT])
            )
            .group_by(FolioTransaction.folio_id)
            .subquery()
        )
        refund_disc_subq = (
            db.query(
                FolioTransaction.folio_id,
                func.coalesce(func.sum(func.abs(FolioTransaction.amount)), 0).label("disc")
            )
            .filter(
                FolioTransaction.folio_id == Folio.id,
                FolioTransaction.is_voided == False,
                FolioTransaction.category == FTC.DISCOUNT
            )
            .group_by(FolioTransaction.folio_id)
            .subquery()
        )
        q = q.outerjoin(
            refund_balance_subq,
            Folio.id == refund_balance_subq.c.folio_id
        ).outerjoin(
            refund_charge_subq,
            Folio.id == refund_charge_subq.c.folio_id
        ).outerjoin(
            refund_disc_subq,
            Folio.id == refund_disc_subq.c.folio_id
        ).filter(
            Folio.id.isnot(None),
            func.coalesce(refund_charge_subq.c.chg, 0)
            - func.coalesce(refund_disc_subq.c.disc, 0)
            - func.coalesce(refund_balance_subq.c.net, 0)
            < -0.5
        )
    elif sf == "paid":
        q = q.filter(
            or_(
                Folio.id.is_(None),
                and_(
                    or_(Folio.debt_status.is_(None), Folio.debt_status.in_(["none", "settled"])),
                    or_(
                        Folio.refund_status.is_(None),
                        Folio.refund_status.notin_(["pending", "approved"]),
                    ),
                    or_(Folio.balance.is_(None), Folio.balance >= -0.5),
                ),
            )
        )

    if sf == "all" and debt_status and debt_status != "none":
        q = q.filter(Folio.debt_status == debt_status)
    if sf == "all" and refund_status and refund_status != "none":
        q = q.filter(Folio.refund_status == refund_status)

    # Apply search filter for stats query — dùng exists() để tránh DuplicateAlias
    if search and len(search.strip()) >= 2:
        search_term = f"%{search.strip()}%"
        guest_subq = (
            db.query(HotelGuest.id)
            .filter(
                HotelGuest.stay_id == HotelStay.id,
                or_(
                    HotelGuest.full_name.ilike(search_term),
                    HotelGuest.cccd.ilike(search_term),
                )
            )
            .exists()
            .correlate(HotelStay)
        )
        q = q.filter(guest_subq)

    total = q.order_by(None).count()
    q = q.order_by(date_filter_field.desc())

    # Stats: all 4 counts in a SINGLE efficient query
    stats = {}
    base_q = (
        db.query(HotelStay)
        .outerjoin(latest_folio_sq, latest_folio_sq.c.stay_id == HotelStay.id)
        .outerjoin(Folio, Folio.id == latest_folio_sq.c.mx)
        .filter(HotelStay.status != HotelStayStatus.ACTIVE)
    )
    if effective_branch:
        base_q = base_q.filter(HotelStay.branch_id == effective_branch)
    if date_from:
        try:
            df = VN_TZ.localize(datetime.fromisoformat(date_from))
            base_q = base_q.filter(HotelStay.check_out_at >= df)
        except Exception:
            pass
    if date_to:
        try:
            dt = VN_TZ.localize(datetime.fromisoformat(date_to))
            base_q = base_q.filter(HotelStay.check_out_at <= dt)
        except Exception:
            pass

    # Gộp 4 query COUNT(*) thành 1 query UNION ALL để giảm database round-trip
    debt_q     = base_q.filter(
        Folio.id.isnot(None),
        Folio.debt_status.notin_(["none", "settled"]),
    ).with_entities(literal_column("'debt'").label("bucket"), func.count(HotelStay.id).label("cnt"))

    # refund_q: tính balance thực từ transactions như summary_status
    refund_bal_subq_s = (
        db.query(
            FolioTransaction.folio_id,
            func.coalesce(func.sum(
                func.abs(FolioTransaction.amount)
            ), 0).label("net")
        )
        .filter(
            FolioTransaction.folio_id == Folio.id,
            FolioTransaction.is_voided == False,
            FolioTransaction.amount < 0,
            FolioTransaction.transaction_type.in_([FTT.PAYMENT, FTT.DEPOSIT_USED])
        )
        .group_by(FolioTransaction.folio_id)
        .subquery()
    )
    refund_chg_subq_s = (
        db.query(
            FolioTransaction.folio_id,
            func.coalesce(func.sum(FolioTransaction.amount), 0).label("chg")
        )
        .filter(
            FolioTransaction.folio_id == Folio.id,
            FolioTransaction.is_voided == False,
            FolioTransaction.amount > 0,
            FolioTransaction.transaction_type.notin_([FTT.REFUND, FTT.REFUND_PAYMENT])
        )
        .group_by(FolioTransaction.folio_id)
        .subquery()
    )
    refund_disc_subq_s = (
        db.query(
            FolioTransaction.folio_id,
            func.coalesce(func.sum(func.abs(FolioTransaction.amount)), 0).label("disc")
        )
        .filter(
            FolioTransaction.folio_id == Folio.id,
            FolioTransaction.is_voided == False,
            FolioTransaction.category == FTC.DISCOUNT
        )
        .group_by(FolioTransaction.folio_id)
        .subquery()
    )
    refund_q = (
        base_q
        .outerjoin(refund_bal_subq_s, Folio.id == refund_bal_subq_s.c.folio_id)
        .outerjoin(refund_chg_subq_s, Folio.id == refund_chg_subq_s.c.folio_id)
        .outerjoin(refund_disc_subq_s, Folio.id == refund_disc_subq_s.c.folio_id)
        .filter(
            func.coalesce(refund_chg_subq_s.c.chg, 0)
            - func.coalesce(refund_disc_subq_s.c.disc, 0)
            - func.coalesce(refund_bal_subq_s.c.net, 0)
            < -0.5
        )
        .with_entities(literal_column("'refund'").label("bucket"), func.count(HotelStay.id).label("cnt"))
    )

    no_folio_q = base_q.filter(Folio.id.is_(None)).with_entities(
        literal_column("'paid'").label("bucket"), func.count(HotelStay.id).label("cnt")
    )

    settled_q  = base_q.filter(
        Folio.id.isnot(None),
        Folio.debt_status.in_(["none", "settled"]),
        or_(
            Folio.refund_status.is_(None),
            Folio.refund_status.notin_(["pending", "approved"]),
        ),
        or_(Folio.balance.is_(None), Folio.balance >= -0.5)
    ).with_entities(literal_column("'paid'").label("bucket"), func.count(HotelStay.id).label("cnt"))

    stats_total_q = (
        base_q.with_entities(func.count(HotelStay.id).label("total"))
    )
    stats["total"] = int(stats_total_q.scalar() or 0)

    # Gộp debt + refund + paid vào 1 query
    union_q = union(debt_q, refund_q, no_folio_q, settled_q).alias("stats")
    bucket_counts = db.query(
        union_q.c.bucket,
        func.sum(union_q.c.cnt).label("total")
    ).group_by(union_q.c.bucket).all()

    for bucket, cnt in bucket_counts:
        if bucket == "debt":
            stats["debt"] = int(cnt) if cnt else 0
        elif bucket == "refund":
            stats["refund"] = int(cnt) if cnt else 0
        elif bucket == "paid":
            stats["paid"] = int(cnt) if cnt else 0

    # Default fallback nếu chưa có giá trị
    stats.setdefault("debt", 0)
    stats.setdefault("refund", 0)
    stats.setdefault("paid", 0)
    # Ensure all stats are Python int for JSON serialization
    stats["total"] = int(stats.get("total", 0))
    stats["debt"] = int(stats.get("debt", 0))
    stats["refund"] = int(stats.get("refund", 0))
    stats["paid"] = int(stats.get("paid", 0))

    stays = q.offset((page - 1) * page_size).limit(page_size).all()

    # ── Batch queries: eliminate N+1 ─────────────────────────────────────
    stay_ids = [s.id for s in stays]

    # Batch: latest folio per stay
    folio_map: dict = {}
    if stay_ids:
        folio_latest_sq = (
            db.query(Folio.stay_id, func.max(Folio.id).label("mx"))
            .filter(Folio.stay_id.in_(stay_ids))
            .group_by(Folio.stay_id)
            .subquery()
        )
        folios_batch = (
            db.query(Folio)
            .options(joinedload(Folio.transactions))
            .join(folio_latest_sq, Folio.id == folio_latest_sq.c.mx)
            .all()
        )
        folio_map = {f.stay_id: f for f in folios_batch}

    # Batch: latest debt_record per stay
    debt_map: dict = {}
    if stay_ids:
        debt_latest_sq = (
            db.query(DebtRecord.stay_id, func.max(DebtRecord.id).label("mx"))
            .filter(DebtRecord.stay_id.in_(stay_ids))
            .group_by(DebtRecord.stay_id)
            .subquery()
        )
        debts_batch = (
            db.query(DebtRecord)
            .join(debt_latest_sq, DebtRecord.id == debt_latest_sq.c.mx)
            .all()
        )
        debt_map = {d.stay_id: d for d in debts_batch}

    # Batch: latest refund_record per stay
    refund_map: dict = {}
    if stay_ids:
        refund_latest_sq = (
            db.query(RefundRecord.stay_id, func.max(RefundRecord.id).label("mx"))
            .filter(RefundRecord.stay_id.in_(stay_ids))
            .group_by(RefundRecord.stay_id)
            .subquery()
        )
        refunds_batch = (
            db.query(RefundRecord)
            .join(refund_latest_sq, RefundRecord.id == refund_latest_sq.c.mx)
            .all()
        )
        refund_map = {r.stay_id: r for r in refunds_batch}

    # Batch: guests per stay (ensure guests are loaded correctly after pagination)
    guests_map: dict = {}
    if stay_ids:
        guests_batch = (
            db.query(HotelGuest)
            .filter(HotelGuest.stay_id.in_(stay_ids))
            .order_by(HotelGuest.is_primary.desc())
            .all()
        )
        for g in guests_batch:
            if g.stay_id not in guests_map:
                guests_map[g.stay_id] = []
            guests_map[g.stay_id].append(g)

    # ── Build results using dict lookups ──────────────────────────────────
    results = []
    for stay in stays:
        folio = folio_map.get(stay.id)
        debt_record = debt_map.get(stay.id)
        refund_record = refund_map.get(stay.id)
        guests_list = guests_map.get(stay.id, [])

        # Số dư còn lại = tổng charge - tổng paid (bao gồm deposit + payment)
        # Tính trực tiếp từ transactions để bỏ qua REFUND/REFUND_PAYMENT
        balance_remaining = 0.0
        if folio and folio.transactions:
            real_charge = sum(
                float(tx.amount) for tx in folio.transactions
                if not tx.is_voided and tx.amount > 0 and tx.transaction_type not in (FTT.REFUND, FTT.REFUND_PAYMENT)
            )
            real_disc = sum(
                abs(float(tx.amount)) for tx in folio.transactions
                if not tx.is_voided and tx.category == FTC.DISCOUNT
            )
            real_paid = sum(
                abs(float(tx.amount)) for tx in folio.transactions
                if not tx.is_voided and tx.amount < 0 and tx.transaction_type in (FTT.PAYMENT, FTT.DEPOSIT_USED)
            )
            balance_remaining = (real_charge - real_disc) - real_paid
        elif folio:
            balance_remaining = float(folio.balance) if folio.balance else 0

        # summary_status: phân loại hiển thị
        if folio:
            if balance_remaining > 0.5:
                summary = "debt"
            elif balance_remaining < -0.5:
                summary = "refund"
            else:
                summary = "paid"
        else:
            summary = "paid"

        # deposit_used: tổng tiền cọc đã thanh toán
        deposit_used = 0.0
        if folio:
            deposit_used = float(sum(
                abs(tx.amount)
                for tx in folio.transactions
                if not tx.is_voided
                and tx.transaction_type == FTT.DEPOSIT_USED
            ))

        # Lấy khách đại diện (ưu tiên người có is_primary=True, nếu không lấy người đầu tiên)
        primary_guest = next((g for g in guests_list if g.is_primary), None)
        if not primary_guest and guests_list:
            primary_guest = guests_list[0]
            
        guest_name = primary_guest.full_name if primary_guest else "—"
        guest_count = len(guests_list)

        is_hourly = False
        if stay.pricing_mode_final in ("HOURLY_CHARGE", "HOURLY") or stay.pricing_mode_initial in ("HOURLY_CHARGE", "HOURLY"):
            is_hourly = True
        elif folio and getattr(folio, "transactions", None):
            if any(tx.transaction_type == FTT.HOURLY_CHARGE for tx in folio.transactions if not tx.is_voided):
                is_hourly = True
                
        results.append({
            "stay_id": stay.id,
            "room_number": stay.room.room_number if stay.room else "—",
            "room_floor": stay.room.floor if stay.room else None,
            "room_type_name": stay.room.room_type_obj.name if stay.room and stay.room.room_type_obj else "—",
            "guest_name": guest_name,
            "guest_gender": primary_guest.gender if primary_guest else None,
            "guest_count": guest_count,
            "max_guests": (
                stay.room.room_type_obj.max_guests
                if stay.room and stay.room.room_type_obj
                else 2
            ),
            "guests": [
                {
                    "id": g.id,
                    "full_name": g.full_name,
                    "gender": g.gender,
                    "birth_date": g.birth_date.isoformat() if g.birth_date else None,
                }
                for g in guests_list
            ],
            "check_in_at": stay.check_in_at.isoformat() if stay.check_in_at else None,
            "check_out_at": stay.check_out_at.isoformat() if stay.check_out_at else None,
            "total_price": float(stay.total_price) if stay.total_price else (float(folio.total_charge) if folio and folio.total_charge else 0),
            "pricing_mode": "HOURLY" if is_hourly else None,
            "deposit": float(stay.deposit) if stay.deposit else 0,
            "deposit_used": deposit_used,
            "balance_remaining": balance_remaining,
            "status": stay.status.value if stay.status else None,
            "summary_status": summary,
            "folio": {
                "id": folio.id if folio else None,
                "balance": float(folio.balance) if folio and folio.balance else 0,
                "debt_amount": float(folio.debt_amount) if folio and folio.debt_amount else 0,
                "debt_status": folio.debt_status if folio else None,
                "debt_note": folio.debt_note if folio else None,
                "refund_amount": float(folio.refund_amount) if folio and folio.refund_amount else 0,
                "refund_status": folio.refund_status if folio else None,
                "refund_note": folio.refund_note if folio else None,
            } if folio else None,
            "debt_record": {
                "id": debt_record.id,
                "debt_amount": float(debt_record.debt_amount),
                "paid_amount": float(debt_record.paid_amount),
                "remaining_amount": float(debt_record.remaining_amount),
                "status": debt_record.status,
                "note": debt_record.note,
                "created_at": debt_record.created_at.isoformat() if debt_record.created_at else None,
                "settled_at": debt_record.settled_at.isoformat() if debt_record.settled_at else None,
            } if debt_record else None,
            "refund_record": {
                "id": refund_record.id,
                "refund_amount": float(refund_record.refund_amount),
                "refund_method": refund_record.refund_method,
                "refund_account": refund_record.refund_account,
                "status": refund_record.status,
                "note": refund_record.note,
                "created_at": refund_record.created_at.isoformat() if refund_record.created_at else None,
                "settled_at": refund_record.settled_at.isoformat() if refund_record.settled_at else None,
            } if refund_record else None,
        })

    return JSONResponse({
        "items": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0,
        "stats": stats,
    })


# ─────────────────────────── API: Stay Detail ───────────────────────────

@router.get("/api/pms/stays/{stay_id}", tags=["PMS"])
def api_get_stay(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
):
    """Lấy chi tiết lưu trú"""
    user = _require_login(request)

    stay = (
        db.query(HotelStay)
        .options(
            joinedload(HotelStay.room).joinedload(HotelRoom.room_type_obj),
            joinedload(HotelStay.guests),
        )
        .filter(HotelStay.id == stay_id)
        .first()
    )
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")

    room = stay.room
    rt = room.room_type_obj if room else None

    # Lấy branch_code để gửi shift report
    branch_code = ""
    if room and room.branch_id:
        from ...db.models import Branch
        branch_row = db.query(Branch.branch_code).filter(Branch.id == room.branch_id).scalar()
        branch_code = branch_row or ""

    # Lấy folio mới nhất để tính debt_summary cho checked-out stays
    debt_summary = None
    effective_total_price = float(stay.total_price) if stay.total_price else 0
    if stay.status != HotelStayStatus.ACTIVE:
        latest_folio_sq = (
            db.query(Folio.id)
            .filter(Folio.stay_id == stay_id)
            .order_by(Folio.id.desc())
            .limit(1)
            .subquery()
        )
        folio = db.query(Folio).filter(Folio.id == latest_folio_sq).first()
        if folio:
            # ── QUAN TRỌNG: Tính balance từ FolioTransaction (source of truth)
            # KHÔNG dùng folio.balance vì nó có thể stale (folio.total_charge = 0)
            # Logic giống preview-checked-out: loại trừ REFUND/REFUND_PAYMENT

            # Charges (loại trừ REFUND/REFUND_PAYMENT)
            real_charge = db.query(
                func.coalesce(func.sum(FolioTransaction.amount), 0)
            ).filter(
                FolioTransaction.folio_id == folio.id,
                FolioTransaction.amount > 0,
                FolioTransaction.is_voided == False,
                FolioTransaction.transaction_type.notin_([FTT.REFUND, FTT.REFUND_PAYMENT]),
            ).scalar() or Decimal("0")

            # Discounts (category=DISCOUNT, amount < 0)
            real_disc = db.query(
                func.coalesce(func.sum(func.abs(FolioTransaction.amount)), 0)
            ).filter(
                FolioTransaction.folio_id == folio.id,
                FolioTransaction.is_voided == False,
                FolioTransaction.category == FTC.DISCOUNT,
            ).scalar() or Decimal("0")

            # Payments (PAYMENT + DEPOSIT_USED)
            real_paid = db.query(
                func.coalesce(func.sum(func.abs(FolioTransaction.amount)), 0)
            ).filter(
                FolioTransaction.folio_id == folio.id,
                FolioTransaction.amount < 0,
                FolioTransaction.is_voided == False,
                FolioTransaction.transaction_type.in_([FTT.PAYMENT, FTT.DEPOSIT_USED]),
            ).scalar() or Decimal("0")

            net_charge = real_charge - real_disc
            real_balance = float(net_charge - real_paid)

            if real_balance > 0.5:  # threshold nhỏ tránh floating point
                debt_summary = "debt"
            elif real_balance < -0.5:
                debt_summary = "refund"
            else:
                debt_summary = "paid"

            # Tổng tiền: ưu tiên stay.total_price (snapshot tại thời điểm checkout, đã trừ discount)
            # Chỉ fallback về folio.total_charge khi stay.total_price chưa có
            if stay.total_price and stay.total_price > 0:
                effective_total_price = float(stay.total_price)
            elif folio and folio.total_charge:
                effective_total_price = float(folio.total_charge)
            else:
                effective_total_price = 0

    return JSONResponse({
        "id": stay.id,
        "branch_id": stay.branch_id if hasattr(stay, 'branch_id') else (room.branch_id if room else None),
        "branch_code": branch_code,
        "room_id": stay.room_id,
        "room_type_id": rt.id if rt else None,
        "room_number": room.room_number if room else "—",
        "room_type": rt.name if rt else "—",
        "max_guests": rt.max_guests if rt else 2,
        "stay_type": stay.stay_type,
        "pricing_mode_initial": stay.pricing_mode_initial,
        "pricing_mode_final": stay.pricing_mode_final,
        "check_in_at": stay.check_in_at.isoformat() if stay.check_in_at else None,
        "check_out_at": stay.check_out_at.isoformat() if stay.check_out_at else None,
        "is_checked_out": stay.status != HotelStayStatus.ACTIVE,
        "total_price": effective_total_price,
        "debt_summary": debt_summary,  # debt | refund | paid — cho badge UI
        "deposit": float(stay.deposit) if stay.deposit else 0,
        "extra_charge": float(getattr(stay, 'extra_charge', 0) or 0),
        "notes": stay.notes,
        "status": stay.status.value if stay.status else "unknown",
        "price_per_night": float(rt.price_per_night) if rt and rt.price_per_night else 0,
        "price_per_hour": float(rt.price_per_hour) if rt and rt.price_per_hour else 0,
        "price_next_hour": float(rt.price_next_hour) if rt and rt.price_next_hour else 0,
        "min_hours": rt.min_hours if rt else 1,
        "require_invoice": stay.require_invoice if hasattr(stay, 'require_invoice') else False,
        "tax_code": stay.tax_code if hasattr(stay, 'tax_code') else None,
        "tax_contact": stay.tax_contact if hasattr(stay, 'tax_contact') else None,
        "vehicle": stay.vehicle if hasattr(stay, 'vehicle') else None,
        "guests": [
            {
                "id": g.id,
                "crm_guest_id": g.guest_id,
                "full_name": g.full_name,
                "cccd": g.cccd,
                "gender": g.gender,
                "phone": g.phone,
                "birth_date": g.birth_date.isoformat() if g.birth_date else None,
                "is_primary": g.is_primary,
                "notes": g.notes,
                "address": g.address,
                "address_type": g.address_type,
                "city": g.city,
                "district": g.district,
                "ward": g.ward,
                "old_city": getattr(g, 'old_city', None),
                "old_district": getattr(g, 'old_district', None),
                "old_ward": getattr(g, 'old_ward', None),
                "id_expire": g.id_expire.isoformat() if g.id_expire else None,
                "id_type": g.id_type,
                "tax_code": g.tax_code,
                "invoice_contact": g.invoice_contact,
                "nationality": g.nationality,
                "check_in_at": g.check_in_at.isoformat() if g.check_in_at else None,
                "check_out_at": g.check_out_at.isoformat() if g.check_out_at else None,
            }
            for g in stay.guests  # Trả tất cả guests
        ],
    })


class UpdateStayRequest(BaseModel):
    check_in_at: Optional[str] = None
    check_out_at: Optional[str] = None
    stay_type: Optional[str] = None
    deposit: Optional[float] = None
    notes: Optional[str] = None
    tax_code: Optional[str] = None
    tax_contact: Optional[str] = None


@router.put("/api/pms/stays/{stay_id}", tags=["PMS"])
def api_update_stay(
    request: Request,
    stay_id: int,
    body: UpdateStayRequest = Body(...),
    db: Session = Depends(get_db),
):
    """Cập nhật thông tin lưu trú"""
    logger.info(f"[UPDATE_STAY] stay_id={stay_id}, check_in_at={body.check_in_at}, check_out_at={body.check_out_at}")
    
    user = _require_login(request)

    stay = db.query(HotelStay).filter(HotelStay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")

    body_fields = body.model_fields_set if hasattr(body, "model_fields_set") else body.__fields_set__
    has_notes_field = "notes" in body_fields
    is_notes_only_update = (
        has_notes_field
        and body.check_in_at is None
        and body.check_out_at is None
        and body.stay_type is None
        and body.deposit is None
        and body.tax_code is None
        and body.tax_contact is None
    )
    if stay.status != HotelStayStatus.ACTIVE and not is_notes_only_update:
        raise HTTPException(status_code=400, detail="Chỉ có thể cập nhật lưu trú đang hoạt động")

    check_in_at = body.check_in_at
    check_out_at = body.check_out_at
    stay_type = body.stay_type
    deposit = body.deposit
    notes = body.notes
    tax_code = body.tax_code
    tax_contact = body.tax_contact
    old_check_in_at = stay.check_in_at
    old_check_out_at = stay.check_out_at
    old_room_type_id = stay.room.room_type_id if stay.room else None

    # Parse check_in_at
    if check_in_at and check_in_at.strip():
        try:
            ci_str = check_in_at.strip()
            if len(ci_str) == 16:
                ci_str += ':00'
            stay.check_in_at = VN_TZ.localize(datetime.fromisoformat(ci_str))
        except ValueError as e:
            logger.error(f"[UPDATE_STAY] check_in_at parse error: {e}, value={check_in_at}")
            raise HTTPException(status_code=400, detail=f"Check-in datetime không hợp lệ: {check_in_at}")

    # Parse check_out_at
    if check_out_at and check_out_at.strip():
        try:
            co_str = check_out_at.strip()
            if len(co_str) == 16:
                co_str += ':00'
            stay.check_out_at = VN_TZ.localize(datetime.fromisoformat(co_str))
        except ValueError as e:
            logger.error(f"[UPDATE_STAY] check_out_at parse error: {e}, value={check_out_at}")
            raise HTTPException(status_code=400, detail=f"Check-out datetime không hợp lệ: {check_out_at}")

    if stay.check_out_at and stay.check_out_at <= stay.check_in_at:
        raise HTTPException(status_code=400, detail="Giờ trả phòng phải sau giờ nhận phòng")

    if (check_in_at or check_out_at) and stay.room_id and stay.check_out_at:
        search_start = stay.check_in_at.date()
        search_end = max(stay.check_out_at.date() + timedelta(days=1), search_start + timedelta(days=1))
        assigned_bookings = db.query(Booking).filter(
            Booking.branch_id == stay.branch_id,
            Booking.assigned_room_id == stay.room_id,
            Booking.reservation_status == "CONFIRMED",
            Booking.check_out > search_start,
            Booking.check_in < search_end,
            or_(Booking.stay_id.is_(None), Booking.stay_id != stay.id),
        ).order_by(Booking.check_in, Booking.id).all()

        for booking in assigned_bookings:
            conflict_days = [
                target_date
                for target_date in iter_stay_dates(booking.check_in, booking.check_out)
                if _stay_occupies_date(stay.check_in_at, stay.check_out_at, target_date)
            ]
            if not conflict_days:
                continue
            room_number = stay.room.room_number if stay.room else str(stay.room_id)
            booking_code = booking.external_id or f"#{booking.id}"
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Không thể gia hạn phòng {room_number} vì đã có booking {booking_code} "
                    f"({booking.guest_name}) được gán phòng này từ "
                    f"{booking.check_in.strftime('%d/%m/%Y')} đến {booking.check_out.strftime('%d/%m/%Y')}. "
                    "Vui lòng đổi phòng cho booking đó hoặc chuyển khách đang ở sang phòng khác trước khi gia hạn."
                ),
            )

    if stay_type:
        stay.stay_type = stay_type
        # Cập nhật description của CHECK_IN activity cho đúng tiếng Việt
        from ...db.models import GuestActivity
        stay_type_vn = "Phòng giờ" if stay_type.upper() in ("HOUR", "HOURLY", "FORCE_HOURLY") else "Qua đêm"
        room_number = stay.room.room_number if stay.room else ""
        checkin_act = db.query(GuestActivity).filter(
            GuestActivity.stay_id == stay.id,
            GuestActivity.activity_type == "CHECK_IN",
        ).first()
        if checkin_act:
            checkin_act.description = f"Nhận phòng {stay_type_vn}" + (f" - Phòng {room_number}" if room_number else "")

    if deposit is not None:
        stay.deposit = deposit

    if has_notes_field:
        stay.notes = notes.strip() if notes and notes.strip() else None

    if tax_code is not None:
        stay.tax_code = tax_code

    if tax_contact is not None:
        stay.tax_contact = tax_contact

    if check_in_at or check_out_at or stay_type:
        stay.total_price = calculate_room_price(stay.stay_type, stay.room.room_type_obj, stay.check_in_at, stay.check_out_at)

    if (check_in_at or check_out_at) and old_room_type_id:
        affected_start = min(old_check_in_at.date(), stay.check_in_at.date())
        old_end = old_check_out_at.date() if old_check_out_at else _now_vn().date() + timedelta(days=1)
        new_end = stay.check_out_at.date() if stay.check_out_at else _now_vn().date() + timedelta(days=1)
        affected_end = max(old_end, new_end, affected_start + timedelta(days=1))
        inventory = InventoryService(db)
        current = affected_start
        while current < affected_end:
            inventory.get_or_create_inventory(stay.branch_id, old_room_type_id, current, refresh_counts=True)
            current += timedelta(days=1)

    db.commit()

    return JSONResponse({
        "message": "Cập nhật thành công",
        "stay_id": stay.id,
        "total_price": float(stay.total_price),
        "check_out_at": stay.check_out_at.isoformat() if stay.check_out_at else None
    })


# ─────────────────────────── API: Stay Transfer ───────────────────────────

@router.put("/api/pms/stays/{stay_id}/transfer", tags=["PMS"])
def api_transfer_stay(
    request: Request,
    stay_id: int,
    new_room_id: int = Form(...),
    transfer_charge: Optional[float] = Form(None),
    transfer_note: str = Form(""),
    db: Session = Depends(get_db),
):
    """Chuyển phòng — snapshot tiền phòng cũ vào folio, reset check_in_at"""
    user = _require_login(request)
    branch_name = _active_branch(request)

    # Get current stay
    stay = (
        db.query(HotelStay)
        .options(joinedload(HotelStay.room).joinedload(HotelRoom.room_type_obj))
        .filter(HotelStay.id == stay_id, HotelStay.status == HotelStayStatus.ACTIVE)
        .first()
    )
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")

    # Get new room
    new_room = (
        db.query(HotelRoom)
        .options(joinedload(HotelRoom.room_type_obj))
        .filter(HotelRoom.id == new_room_id, HotelRoom.is_active == True)
        .first()
    )
    if not new_room:
        raise HTTPException(status_code=404, detail="Không tìm thấy phòng mới")

    # Check new room not occupied (ACTIVE stay in same branch)
    already_occupied = db.query(HotelStay.room_id).filter(
        HotelStay.branch_id == stay.branch_id,
        HotelStay.status == HotelStayStatus.ACTIVE,
        HotelStay.room_id == new_room_id,
    ).first()
    if already_occupied:
        raise HTTPException(status_code=400, detail="Phòng mới đã có người đặt")

    now = _now_vn()
    old_room = stay.room
    old_room_number = old_room.room_number
    old_rt = old_room.room_type_obj
    old_type_name = old_rt.name if old_rt else "—"

    # ── OTA stays: không áp dụng segment billing ──────────────────────────────
    is_ota = stay.pricing_mode_initial == "OTA_MANUAL"

    # ── Tính tiền phòng cũ + xác định mốc billing_start_at theo nghiệp vụ ──
    segment_amount = money(0)
    segment_desc = ""
    extra_fee_amount = money(0)
    extra_fee_desc = ""
    new_billing_start = now
    is_dead_zone = False

    if not is_ota:
        effective_mode = MODE_TO_STAY_TYPE.get(stay.pricing_mode_initial or "AUTO", "AUTO")
        billing_from = stay.billing_start_at if stay.billing_start_at else stay.check_in_at

        # Convert sang VN timezone
        billing_from_vn = billing_from.astimezone(VN_TZ) if billing_from.tzinfo else VN_TZ.localize(billing_from)
        transfer_time_vn = now.astimezone(VN_TZ) if now.tzinfo else VN_TZ.localize(now)

        # std_in / std_out của hạng phòng cũ (mặc định 14:00 / 12:00)
        std_in_time = old_rt.standard_checkin_time if old_rt and old_rt.standard_checkin_time else time(14, 0)
        std_out_time = old_rt.standard_checkout_time if old_rt and old_rt.standard_checkout_time else time(12, 0)

        # Tìm next_std_out (std_out đầu tiên > billing_from)
        std_out_same_day = VN_TZ.localize(datetime.combine(billing_from_vn.date(), std_out_time))
        if billing_from_vn >= std_out_same_day:
            next_std_out = std_out_same_day + timedelta(days=1)
        else:
            next_std_out = std_out_same_day

        # Forward để tìm last_completed_std_out (std_out gần nhất ≤ transfer_time)
        last_completed_std_out = None
        while next_std_out <= transfer_time_vn:
            last_completed_std_out = next_std_out
            next_std_out = next_std_out + timedelta(days=1)

        # std_in của ngày transfer_time
        std_in_today = VN_TZ.localize(datetime.combine(transfer_time_vn.date(), std_in_time))

        # Phân loại kịch bản
        if last_completed_std_out is None:
            # Chưa qua std_out nào → cùng hotel day với lần transfer trước
            # KHÔNG ghi segment (tránh double charge), giữ nguyên billing_start_at
            # Khi checkout sẽ tính 1 đêm với giá phòng cuối cùng
            segment_end = None
            new_billing_start = billing_from  # giữ nguyên
            is_dead_zone = False
        elif transfer_time_vn >= std_in_today:
            # Kịch bản C: đã vào hotel day mới (sau std_in của ngày transfer)
            segment_end = last_completed_std_out
            new_billing_start = std_in_today
            is_dead_zone = False
        else:
            # transfer_time < std_in_today
            # std_in sau last_completed_std_out (cùng ngày)
            std_in_after_last = VN_TZ.localize(datetime.combine(
                last_completed_std_out.date(), std_in_time
            ))
            if transfer_time_vn >= std_in_after_last:
                # Kịch bản A: trong hotel day chưa kết thúc, đã qua std_in
                segment_end = next_std_out
                new_billing_start = next_std_out
                is_dead_zone = False
            else:
                # Kịch bản B: dead zone (giữa std_out và std_in)
                segment_end = last_completed_std_out
                new_billing_start = std_in_after_last
                is_dead_zone = True

        # Tính tiền phòng cũ từ billing_from → segment_end (chỉ khi có segment)
        if segment_end is not None:
            old_charge_raw, _ = calculate_full_charge(effective_mode, old_rt, billing_from, segment_end)
            segment_amount = money(old_charge_raw)

            segment_end_vn = segment_end.astimezone(VN_TZ) if segment_end.tzinfo else VN_TZ.localize(segment_end)
            segment_desc = (
                f"Tiền phòng {old_room_number} ({old_type_name}) — "
                f"{billing_from_vn.strftime('%H:%M %d/%m')} → {segment_end_vn.strftime('%H:%M %d/%m')}"
            )

        # Phí chuyển phòng — chỉ áp dụng khi KHÔNG phải dead zone
        if not is_dead_zone and transfer_charge is not None and transfer_charge > 0:
            extra_fee_amount = money(transfer_charge)
            extra_fee_desc = (
                f"Phí chuyển phòng ({old_room_number} → {new_room.room_number})"
            )
            if transfer_note:
                extra_fee_desc += f" | {transfer_note}"

    # ── Ghi FolioTransaction ──────────────────────────────────────────────────
    folio = None
    if segment_amount > 0 or extra_fee_amount > 0:
        folio = db.query(Folio).filter(
            Folio.stay_id == stay_id,
            Folio.status != "CLOSED",
        ).first()

    if folio and segment_amount > 0:
        db.add(FolioTransaction(
            folio_id=folio.id,
            stay_id=stay_id,
            branch_id=stay.branch_id,
            transaction_type=FTT.ROOM_CHARGE,
            category=FTC.ROOM,
            description=segment_desc,
            amount=segment_amount,
            quantity=1,
            unit_price=segment_amount,
            reference_type="room_transfer_segment",
            reference_id=stay_id,
            created_by=user.get("id"),
        ))

    if folio and extra_fee_amount > 0:
        db.add(FolioTransaction(
            folio_id=folio.id,
            stay_id=stay_id,
            branch_id=stay.branch_id,
            transaction_type=FTT.SURCHARGE,
            category=FTC.SURCHARGE,
            description=extra_fee_desc,
            amount=extra_fee_amount,
            quantity=1,
            unit_price=extra_fee_amount,
            reference_type="room_transfer_fee",
            reference_id=stay_id,
            created_by=user.get("id"),
        ))

    if folio and (segment_amount > 0 or extra_fee_amount > 0):
        db.flush()
        folio.recalculate_balance()

    # ── Cập nhật stay ──────────────────────────────────────────────────────────
    # Lưu mốc check-in gốc lần đầu chuyển phòng (không ghi đè nếu đã có)
    if not is_ota and stay.original_check_in_at is None:
        stay.original_check_in_at = stay.check_in_at

    stay.room_id = new_room_id
    if not is_ota:
        stay.billing_start_at = new_billing_start  # mốc tính giá phòng mới (now hoặc std_checkout nếu đã trả đủ)

    # ── Guest Activity Logging ─────────────────────────────────────────────────
    primary_guest = db.query(HotelGuest).filter(
        HotelGuest.stay_id == stay_id,
        HotelGuest.is_primary == True
    ).first()
    if primary_guest and primary_guest.guest_id:
        log_room_change(
            db, stay, primary_guest,
            from_room=old_room_number,
            to_room=new_room.room_number,
            actor_id=user.get("id")
        )

    db.commit()

    return JSONResponse({
        "message": f"Chuyển phòng thành công từ {old_room_number} sang {new_room.room_number}",
        "stay_id": stay.id,
        "old_room": old_room_number,
        "new_room": new_room.room_number,
        "segment_charge": float(segment_amount),
        "extra_fee": float(extra_fee_amount),
        "is_dead_zone": is_dead_zone,
    })


# ─────────────────────────── API: Guest Management ───────────────────────────

@router.post("/api/pms/stays/{stay_id}/guests", tags=["PMS"])
def api_add_guest_to_stay(
    request: Request,
    stay_id: int,
    full_name: str = Form(...),
    cccd: str = Form(""),
    gender: str = Form(""),
    birth_date: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
    id_type: str = Form("cccd"),
    id_expire: str = Form(""),
    address: str = Form(""),
    address_type: str = Form("new"),
    city: str = Form(""),
    district: str = Form(""),
    ward: str = Form(""),
    nationality: str = Form("VNM - Việt Nam"),
    # Old-address tracking fields (sent by frontend when address_type='old')
    old_city: str = Form(""),
    old_district: str = Form(""),
    old_ward: str = Form(""),
    # Converted new values from client-side (fallback to server-side conversion if empty)
    new_city: str = Form(""),
    new_ward: str = Form(""),
    tax_code: str = Form(""),
    invoice_contact: str = Form(""),
    company_name: str = Form(""),
    company_address: str = Form(""),
    db: Session = Depends(get_db),
):
    """Thêm khách vào lưu trú"""
    user = _require_login(request)

    stay = (
        db.query(HotelStay)
        .options(joinedload(HotelStay.guests), joinedload(HotelStay.room).joinedload(HotelRoom.room_type_obj))
        .filter(HotelStay.id == stay_id, HotelStay.status == HotelStayStatus.ACTIVE)
        .first()
    )
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")

    # Ensure guest CCCD is not active in another room
    if cccd and len(cccd.strip()) >= 3:
        active_guest = (
            db.query(HotelGuest.cccd, HotelRoom.room_number)
            .join(HotelStay, HotelGuest.stay_id == HotelStay.id)
            .join(HotelRoom, HotelStay.room_id == HotelRoom.id)
            .filter(
                HotelGuest.cccd == cccd.strip(),
                HotelStay.status == HotelStayStatus.ACTIVE,
                HotelGuest.check_out_at == None
            ).first()
        )
        if active_guest:
            raise HTTPException(status_code=400, detail=f"Khách hàng có số giấy tờ {active_guest.cccd} đang lưu trú tại phòng {active_guest.room_number}. Không thể thêm.")

    # Parse birth date
    birth = None
    if birth_date:
        try:
            birth = datetime.strptime(birth_date, "%Y-%m-%d").date()
        except:
            pass

    # Parse id_expire
    id_exp = None
    if id_expire:
        try:
            id_exp = datetime.strptime(id_expire, "%Y-%m-%d").date()
        except:
            pass

    # ── Address resolution (same logic as checkin) ────────────────────────────
    _city_s = city.strip()
    _ward_s = ward.strip()
    _dist_s = district.strip()
    _addr_s = address.strip()

    old_city_v, old_district_v, old_ward_v = None, None, None
    new_city_v, new_ward_v = None, None
    new_district_v = None

    if address_type == "old" and _ward_s:
        old_city_v     = old_city.strip() or _city_s
        old_district_v = old_district.strip() or _dist_s
        old_ward_v     = old_ward.strip() or _ward_s
        # Prefer client-side conversion results; fallback to server-side
        if not new_city.strip() or not new_ward.strip():
            conv = convert_old_to_new_sync(old_ward_v, old_city_v, old_district_v)
        if new_city.strip():
            new_city_v = new_city.strip()
        else:
            new_city_v = conv.get("new_province", old_city_v)
        if new_ward.strip():
            new_ward_v = new_ward.strip()
        else:
            new_ward_v = conv.get("new_ward", old_ward_v)
    else:
        new_city_v     = _city_s
        new_ward_v     = _ward_s
        new_district_v = _dist_s

    # Resolve Guest master
    guest_master = None
    if cccd and len(cccd.strip()) >= 3:
        guest_master = db.query(Guest).filter(Guest.cccd == cccd.strip()).first()
        if guest_master:
            guest_master.full_name = full_name
            guest_master.phone = phone
            guest_master.gender = gender
            guest_master.nationality = nationality or guest_master.nationality
            guest_master.id_expire = id_exp  # always update with latest from this stay
            guest_master.updated_by = user.get("id")
            # Lưu full formatted address (địa bàn mới)
            _parts = [p for p in [_addr_s, new_ward_v, new_district_v, new_city_v] if p]
            if _parts:
                guest_master.default_address = ", ".join(_parts)
            guest_master.last_seen_at = _now_vn()
        else:
            guest_master = Guest(
                full_name=full_name,
                cccd=cccd.strip(),
                phone=phone,
                gender=gender,
                nationality=nationality,
                id_expire=id_exp,
                default_address=", ".join([p for p in [_addr_s, new_ward_v, new_district_v, new_city_v] if p]) or None,
                first_seen_at=_now_vn(),
                last_seen_at=_now_vn(),
                total_stays=1,
                created_by=user.get("id"),
                updated_by=user.get("id"),
            )
            db.add(guest_master)
        db.flush()

    # Create guest
    guest = HotelGuest(
        stay_id=stay_id,
        guest_id=guest_master.id if guest_master else None,
        full_name=full_name,
        cccd=cccd,
        gender=gender,
        birth_date=birth,
        phone=phone,
        notes=notes,
        id_type=id_type,
        id_expire=id_exp,
        address=_addr_s,
        address_type=address_type,
        city=new_city_v,
        district=new_district_v,
        ward=new_ward_v,
        nationality=nationality,
        old_city=old_city_v,
        old_district=old_district_v,
        old_ward=old_ward_v,
        tax_code=tax_code or None,
        invoice_contact=invoice_contact or None,
        company_name=company_name or None,
        company_address=company_address or None,
        is_primary=False,
        check_in_at=_now_vn(),
        created_by=user.get("id"),
    )
    db.add(guest)
    db.flush()

    # Sync invoice info lên Guest master
    if tax_code and guest.guest_id:
        guest_master = db.query(Guest).filter(Guest.id == guest.guest_id).first()
        if guest_master:
            guest_master.tax_code = tax_code
            guest_master.invoice_contact = invoice_contact or None
            guest_master.company_name = company_name or None
            guest_master.company_address = company_address or None

    log_guest_added_to_stay(db, stay, guest, actor_id=user.get("id"))
    db.commit()

    return JSONResponse({
        "message": f"Thêm khách {full_name} thành công",
        "guest_id": guest.id,
    })


@router.delete("/api/pms/stays/{stay_id}/guests/{guest_id}", tags=["PMS"])
def api_remove_guest_from_stay(
    request: Request,
    stay_id: int,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """Xóa khách khỏi lưu trú"""
    user = _require_login(request)

    guest = db.query(HotelGuest).filter(
        HotelGuest.id == guest_id,
        HotelGuest.stay_id == stay_id
    ).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    if guest.is_primary:
        raise HTTPException(status_code=400, detail="Không thể xóa khách chính")

    guest_name = guest.full_name
    db.delete(guest)
    db.commit()

    return JSONResponse({
        "message": f"Xóa khách {guest_name} thành công",
    })


# ─────────────────────────── API: Guest Search by CCCD ───────────────────────────

@router.get("/api/pms/guests/search", tags=["PMS"])
def api_search_guest(
    request: Request,
    cccd: str = Query(..., description="Số giấy tờ cần tìm kiếm"),
    db: Session = Depends(get_db),
):
    """Tìm kiếm khách hàng theo số giấy tờ (CCCD/CMND/Passport)"""
    user = _require_login(request)
    
    if not cccd or len(cccd.strip()) < 3:
        return JSONResponse({"guests": [], "message": "Cần nhập ít nhất 3 ký tự để tìm kiếm"})
    
    raw_guests = (
        db.query(HotelGuest)
        .filter(HotelGuest.cccd.ilike(f"%{cccd.strip()}%"))
        .order_by(HotelGuest.created_at.desc())
        .limit(50)
        .all()
    )
    
    unique_guests = {}
    for g in raw_guests:
        if g.cccd:
            key = g.cccd.strip().upper()
            if key not in unique_guests:
                unique_guests[key] = g
                if len(unique_guests) >= 10:
                    break
                    
    guests = list(unique_guests.values())
    
    return JSONResponse({
        "guests": [
            {
                "id": g.id,
                "full_name": g.full_name,
                "cccd": g.cccd,
                "gender": g.gender,
                "phone": g.phone,
                "birth_date": g.birth_date.isoformat() if g.birth_date else None,
                "id_expire": g.id_expire.isoformat() if g.id_expire else None,
                "address": g.address,
                "address_type": g.address_type if hasattr(g, 'address_type') else None,
                "city": g.city,
                "district": g.district,
                "ward": g.ward,
                "old_city": getattr(g, 'old_city', None),
                "old_district": getattr(g, 'old_district', None),
                "old_ward": getattr(g, 'old_ward', None),
                "notes": g.notes,
                "nationality": getattr(g, 'nationality', 'VNM - Việt Nam'),
                "tax_code": getattr(g, 'tax_code', None),
                "invoice_contact": getattr(g, 'invoice_contact', None),
                "company_name": getattr(g, 'company_name', None),
                "company_address": getattr(g, 'company_address', None),
                "id_type": g.id_type,
                "last_stay": None
            }
            for g in guests
        ]
    })


@router.get("/api/pms/guests/check-cccd", tags=["PMS"])
def api_check_cccd_exists(
    request: Request,
    cccd: str = Query(..., description="Số giấy tờ cần kiểm tra"),
    exclude_stay_id: Optional[int] = Query(None, description="ID stay để loại trừ (khi update)"),
    db: Session = Depends(get_db),
):
    """Kiểm tra xem số giấy tờ đã tồn tại chưa"""
    user = _require_login(request)
    
    if not cccd or len(cccd.strip()) < 3:
        return JSONResponse({"exists": False, "guest": None})
    
    query = db.query(HotelGuest).filter(HotelGuest.cccd.ilike(f"%{cccd.strip()}%"))
    
    if exclude_stay_id:
        query = query.filter(HotelGuest.stay_id != exclude_stay_id)
    
    guest = query.first()
    
    if guest:
        return JSONResponse({
            "exists": True,
            "guest": {
                "id": guest.id,
                "full_name": guest.full_name,
                "cccd": guest.cccd,
                "gender": guest.gender,
                "phone": guest.phone,
                "birth_date": guest.birth_date.isoformat() if guest.birth_date else None,
                "id_expire": guest.id_expire.isoformat() if guest.id_expire else None,
                "address": guest.address,
                "address_type": guest.address_type if hasattr(guest, 'address_type') else None,
                "city": guest.city,
                "district": guest.district,
                "ward": guest.ward,
                "old_city": getattr(guest, 'old_city', None),
                "old_district": getattr(guest, 'old_district', None),
                "old_ward": getattr(guest, 'old_ward', None),
                "notes": guest.notes,
                "nationality": getattr(guest, 'nationality', 'VNM - Việt Nam'),
                "tax_code": getattr(guest, 'tax_code', None),
                "invoice_contact": getattr(guest, 'invoice_contact', None),
                "company_name": getattr(guest, 'company_name', None),
                "company_address": getattr(guest, 'company_address', None),
                "id_type": guest.id_type,
            }
        })
    
    return JSONResponse({"exists": False, "guest": None})


@router.get("/api/pms/guests/check-active-cccd", tags=["PMS"])
def api_check_active_cccd(
    request: Request,
    cccd: str = Query(..., description="Số giấy tờ cần kiểm tra"),
    exclude_stay_id: Optional[int] = Query(None, description="ID stay để loại trừ"),
    db: Session = Depends(get_db),
):
    """Kiểm tra xem số giấy tờ có đang ở phòng ACTIVE hay không"""
    user = _require_login(request)
    if not cccd or len(cccd.strip()) < 3:
        return JSONResponse({"is_active": False})
    
    cccd_stripped = cccd.strip()
    logger.info(f"[check-active-cccd] Searching for CCCD: {cccd_stripped}, exclude_stay_id: {exclude_stay_id}")
    
    # First check with exact match
    query = (
        db.query(HotelGuest.cccd, HotelRoom.room_number, HotelStay.status, HotelGuest.check_out_at, Branch.name.label("branch_name"))
        .join(HotelStay, HotelGuest.stay_id == HotelStay.id)
        .join(HotelRoom, HotelStay.room_id == HotelRoom.id)
        .join(Branch, HotelRoom.branch_id == Branch.id)
        .filter(
            HotelGuest.cccd == cccd_stripped,
            HotelStay.status == HotelStayStatus.ACTIVE,
            HotelGuest.check_out_at == None
        )
    )
    if exclude_stay_id:
        query = query.filter(HotelStay.id != exclude_stay_id)

    active_guest = query.first()
    logger.info(f"[check-active-cccd] Exact match result: {active_guest}")
    if active_guest:
        return JSONResponse({
            "is_active": True,
            "room_number": active_guest.room_number,
            "cccd": active_guest.cccd,
            "branch_name": active_guest.branch_name
        })

    # Also check with LIKE for partial match
    query_like = (
        db.query(HotelGuest.cccd, HotelRoom.room_number, HotelStay.status, HotelGuest.check_out_at, Branch.name.label("branch_name"))
        .join(HotelStay, HotelGuest.stay_id == HotelStay.id)
        .join(HotelRoom, HotelStay.room_id == HotelRoom.id)
        .join(Branch, HotelRoom.branch_id == Branch.id)
        .filter(
            HotelGuest.cccd.ilike(f"%{cccd_stripped}%"),
            HotelStay.status == HotelStayStatus.ACTIVE,
            HotelGuest.check_out_at == None
        )
    )
    if exclude_stay_id:
        query_like = query_like.filter(HotelStay.id != exclude_stay_id)

    active_guest_like = query_like.first()
    logger.info(f"[check-active-cccd] LIKE match result: {active_guest_like}")
    if active_guest_like:
        return JSONResponse({
            "is_active": True,
            "room_number": active_guest_like.room_number,
            "cccd": active_guest_like.cccd,
            "branch_name": active_guest_like.branch_name
        })

    return JSONResponse({"is_active": False})

# ─────────────────────────── API: Get/Update/Delete Guest by ID ───────────────────────────

@router.get("/api/pms/guests/{guest_id}", tags=["PMS"])
def api_get_guest(
    request: Request,
    guest_id: int,
    db: Session = Depends(get_db),
):
    """Lấy thông tin khách"""
    user = _require_login(request)

    guest = db.query(HotelGuest).filter(HotelGuest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    return JSONResponse({
        "id": guest.id,
        "full_name": guest.full_name,
        "cccd": guest.cccd,
        "gender": guest.gender,
        "phone": guest.phone,
        "birth_date": guest.birth_date.isoformat() if guest.birth_date else None,
        "is_primary": guest.is_primary,
    })


@router.put("/api/pms/guests/{guest_id}", tags=["PMS"])
async def api_update_guest(
    request: Request,
    guest_id: int,
    full_name: Optional[str] = Form(None),
    cccd: Optional[str] = Form(None),
    gender: Optional[str] = Form(None),
    birth_date: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    id_type: Optional[str] = Form(None),
    id_expire: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    address_type: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    district: Optional[str] = Form(None),
    ward: Optional[str] = Form(None),
    old_city: Optional[str] = Form(None),
    old_district: Optional[str] = Form(None),
    old_ward: Optional[str] = Form(None),
    nationality: Optional[str] = Form(None),
    tax_code: Optional[str] = Form(None),
    invoice_contact: Optional[str] = Form(None),
    company_name: Optional[str] = Form(None),
    company_address: Optional[str] = Form(None),
    check_out_at: Optional[str] = Form(None),
    vehicle: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Cập nhật thông tin khách hoặc checkout khách"""
    user = _require_login(request)

    # Support JSON body for check_out_at (from frontend checkout)
    body = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = await request.json()
        except:
            pass

    guest = db.query(HotelGuest).filter(HotelGuest.id == guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Không tìm thấy khách")

    # ── Capture original values before update (for timeline diff) ──────────
    _orig = {
        "full_name": guest.full_name,
        "cccd": guest.cccd,
        "gender": guest.gender,
        "birth_date": str(guest.birth_date) if guest.birth_date else None,
        "phone": guest.phone,
        "notes": guest.notes,
        "id_type": guest.id_type,
        "id_expire": str(guest.id_expire) if guest.id_expire else None,
        "address": guest.address,
        "city": guest.city,
        "district": guest.district,
        "ward": guest.ward,
        "nationality": guest.nationality,
        "tax_code": guest.tax_code,
        "invoice_contact": guest.invoice_contact,
    }

    if full_name is not None:
        guest.full_name = full_name
    if cccd is not None:
        new_cccd = cccd.strip()
        if new_cccd and len(new_cccd) >= 3 and new_cccd != (guest.cccd and guest.cccd.strip()):
            active_guest = (
                db.query(HotelGuest.cccd, HotelRoom.room_number)
                .join(HotelStay, HotelGuest.stay_id == HotelStay.id)
                .join(HotelRoom, HotelStay.room_id == HotelRoom.id)
                .filter(
                    HotelGuest.cccd == new_cccd,
                    HotelStay.status == HotelStayStatus.ACTIVE,
                    HotelGuest.check_out_at == None
                ).first()
            )
            if active_guest:
                raise HTTPException(status_code=400, detail=f"Khách hàng có số giấy tờ {active_guest.cccd} đang lưu trú tại phòng {active_guest.room_number}. Không thể cập nhật.")
        guest.cccd = cccd
    if gender is not None:
        guest.gender = gender
    if birth_date is not None:
        if birth_date:
            try:
                guest.birth_date = datetime.strptime(birth_date, "%Y-%m-%d").date()
            except:
                pass
        else:
            guest.birth_date = None
    if phone is not None:
        guest.phone = phone
    if notes is not None:
        guest.notes = notes
    if id_type is not None:
        guest.id_type = id_type
    if id_expire is not None:
        if id_expire:
            try:
                guest.id_expire = datetime.strptime(id_expire, "%Y-%m-%d").date()
            except:
                pass
        else:
            guest.id_expire = None
    if address is not None:
        guest.address = address
    if address_type is not None:
        guest.address_type = address_type
    if city is not None:
        guest.city = city
    if district is not None:
        guest.district = district
    if ward is not None:
        guest.ward = ward
    # old_* chỉ ghi khi mode='old' VÀ có giá trị; xóa khi mode='new'
    # (để DB luôn nhất quán: địa bàn nào thì lưu địa bàn đó)
    if address_type == "old":
        if old_city is not None and old_city:
            guest.old_city = old_city
        if old_district is not None and old_district:
            guest.old_district = old_district
        if old_ward is not None and old_ward:
            guest.old_ward = old_ward
    elif address_type == "new":
        guest.old_city = None
        guest.old_district = None
        guest.old_ward = None
    if nationality is not None:
        guest.nationality = nationality
    if tax_code is not None:
        guest.tax_code = tax_code if tax_code else None
    if invoice_contact is not None:
        guest.invoice_contact = invoice_contact if invoice_contact else None

    # Vehicle (from Form or JSON body)
    veh_val = body.get("vehicle") if body else None
    if veh_val is None and vehicle is not None:
        veh_val = vehicle
    if veh_val is not None:
        guest.vehicle = veh_val.strip() if veh_val else None

    # Guest check-out: always use server-side VN time — ignore client timestamp to avoid TZ bugs
    co_val = body.get("check_out_at") if body else None
    if co_val is None and check_out_at is not None:
        co_val = check_out_at
    if co_val is not None and str(co_val).strip():
        guest.check_out_at = _now_vn()
    elif co_val is not None:
        guest.check_out_at = None

    guest.updated_by = user.get("id")

    # Sync changed fields back to master Guest record
    if guest.guest_id:
        master = db.query(Guest).filter(Guest.id == guest.guest_id).first()
        if master:
            if full_name is not None:
                master.full_name = full_name
            if cccd is not None:
                master.cccd = cccd
            if gender is not None:
                master.gender = gender
            if birth_date is not None:
                master.date_of_birth = guest.birth_date
            if phone is not None:
                master.phone = phone
            if nationality is not None:
                master.nationality = nationality
            if id_expire is not None:
                master.id_expire = guest.id_expire
            if address is not None or city is not None or ward is not None:
                _addr = address if address is not None else (guest.address or "")
                _city = city if city is not None else (guest.city or "")
                _ward = ward if ward is not None else (guest.ward or "")
                _dist = guest.district or ""
                _parts = [p for p in [_addr, _ward, _dist, _city] if p]
                master.default_address = ", ".join(_parts)
            master.updated_by = user.get("id")

    # ── Build changes dict for timeline ──────────────────────────────────────
    # Read final values from guest object (already updated above)
    _new_vals = {
        "full_name": guest.full_name,
        "cccd": guest.cccd,
        "gender": guest.gender,
        "birth_date": str(guest.birth_date) if guest.birth_date else None,
        "phone": guest.phone,
        "notes": guest.notes,
        "id_type": guest.id_type,
        "id_expire": str(guest.id_expire) if guest.id_expire else None,
        "address": guest.address,
        "city": guest.city,
        "district": guest.district,
        "ward": guest.ward,
        "nationality": guest.nationality,
        "tax_code": guest.tax_code,
        "invoice_contact": guest.invoice_contact,
    }
    _changes = {
        k: {"old": _orig[k], "new": _new_vals[k]}
        for k in _orig
        if _orig[k] != _new_vals[k]
    }

    if _changes:
        log_guest_edited(db, guest, _changes, actor_id=user.get("id"))

    db.commit()

    return JSONResponse({
        "message": "Cập nhật thành công",
        "guest_id": guest.id,
        "check_out_at": guest.check_out_at.isoformat() if guest.check_out_at else None,
    })
