# app/api/pms/pms_checkout.py
"""
PMS Check-out API - Unified Checkout Orchestration

Key endpoints:
- GET  /api/pms/checkout/{stay_id}/info      → preview checkout (no DB changes)
- GET  /api/pms/checkout/{stay_id}/preview   → detailed preview with folio merge
- POST /api/pms/checkout/{stay_id}           → atomic checkout (full transaction)
- POST /api/pms/checkout/{stay_id}/recheckin → reopen checked-out stay
"""
from __future__ import annotations

from datetime import time
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from ...core.config import logger
from ...core.utils import VN_TZ
from ...db.models import (
    DebtRecord, Folio, FolioStatus, FolioTransaction, FolioTransactionCategory, FolioTransactionType,
    HotelGuest, HotelRoom, HotelStay, HotelStayStatus, RefundRecord,
)
from ...db.session import TaskSessionLocal, get_db
from ...services.checkout_service import execute_checkout, preview_checkout
from ...services.folio_service import get_folio_financial_totals, mark_transaction_void
from ...services.pricing_service import money, get_engine_config
from .guest_activity import log_checkout
from .pms_helpers import _now_vn, _require_login
from ...services.guest_crm_integration import on_checkout_complete

router = APIRouter()


def _run_checkout_side_effects(
    stay_id: int,
    user_id: Optional[int],
    final_total: str,
    discount: str,
    extra_charge: str,
    deposit_amount: str,
    breakdown: Optional[list],
    folio_id: Optional[int],
) -> None:
    """Ghi log và CRM sau checkout bằng DB session riêng để response không bị chờ."""
    db = TaskSessionLocal()
    try:
        stay = db.query(HotelStay).options(selectinload(HotelStay.room)).filter(HotelStay.id == stay_id).first()
        if not stay:
            return

        all_guests = db.query(HotelGuest).filter(
            HotelGuest.stay_id == stay_id,
            HotelGuest.guest_id.isnot(None),
        ).all()
        guest_count = len(all_guests)

        for i, hg in enumerate(all_guests):
            if hg.guest_id:
                try:
                    log_checkout(
                        db=db,
                        stay=stay,
                        hotel_guest=hg,
                        final_price=float(final_total),
                        discount=float(discount),
                        extra_charge=float(extra_charge),
                        deposit=float(deposit_amount),
                        actor_id=user_id,
                        guest_count=guest_count,
                        skip_stats_update=(i > 0),
                        pricing_breakdown=breakdown,
                    )
                except Exception as log_err:
                    logger.warning(f"[Checkout] log_checkout failed for guest {hg.guest_id}: {log_err}")

        if folio_id:
            try:
                on_checkout_complete(
                    db=db,
                    stay_id=stay_id,
                    folio_id=folio_id,
                    user_id=user_id,
                )
                logger.info(f"[CRM] Checkout CRM integration completed for stay {stay_id}")
            except Exception as crm_err:
                logger.warning(f"[CRM] Checkout CRM integration failed: {crm_err}")

        db.commit()
    except Exception as err:
        db.rollback()
        logger.warning(f"[Checkout] background side effects failed for stay {stay_id}: {err}")
    finally:
        db.close()


@router.get("/api/pms/checkout/{stay_id}/info", tags=["PMS"])
def api_checkout_info(
    request: Request,
    stay_id: int,
    discount: str = Query(default="0"),
    extra_charge: str = Query(default="0"),
    db: Session = Depends(get_db),
):
    """
    Preview checkout — tính trước balance và breakdown.
    Dùng cho UI hiển thị trước khi checkout.
    """
    _require_login(request)
    now = _now_vn()

    try:
        calc_discount = money(discount)
        calc_extra = money(extra_charge)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Số tiền không hợp lệ: {exc}")

    try:
        result = preview_checkout(
            db=db,
            stay_id=stay_id,
            discount=calc_discount,
            extra_charge=calc_extra,
            now=now,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # Tính dead_zone — khoảng 12:00–14:00 (giữa std_out và std_in của hạng phòng hiện tại)
    stay = db.query(HotelStay).options(
        selectinload(HotelStay.room).selectinload(HotelRoom.room_type_obj)
    ).filter(HotelStay.id == stay_id).first()
    dead_zone = False
    if stay and stay.room and stay.room.room_type_obj:
        rt = stay.room.room_type_obj
        std_in = rt.standard_checkin_time or time(14, 0)
        std_out = rt.standard_checkout_time or time(12, 0)
        now_vn_time = now.astimezone(VN_TZ).time() if now.tzinfo else now.time()
        dead_zone = std_out <= now_vn_time < std_in
    result["dead_zone"] = dead_zone

    return JSONResponse(result)


@router.get("/api/pms/checkout/{stay_id}/preview", tags=["PMS"])
def api_checkout_preview(
    request: Request,
    stay_id: int,
    discount: str = Query(default="0"),
    extra_charge: str = Query(default="0"),
    include_transactions: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """
    Checkout preview — kết hợp pricing + folio state.
    Trả về đầy đủ thông tin để UI render Payment tab.
    Dùng cho rdLoadPayment — fetch một lần duy nhất.
    """
    _require_login(request)
    now = _now_vn()

    try:
        calc_discount = money(discount)
        calc_extra = money(extra_charge)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Số tiền không hợp lệ: {exc}")

    try:
        result = preview_checkout(
            db=db,
            stay_id=stay_id,
            discount=calc_discount,
            extra_charge=calc_extra,
            now=now,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # Lấy thêm Folio transactions để UI render ledger
    folio_query = db.query(Folio)
    if include_transactions:
        folio_query = folio_query.options(selectinload(Folio.transactions))
    folios_raw = (
        folio_query
        .filter(Folio.stay_id == stay_id)
        .order_by(Folio.id.asc())
        .all()
    )

    result["folios"] = [
        {
            "id": f.id,
            "folio_code": f.folio_code,
            "status": f.status.value if f.status else "OPEN",
            "total_charge": float(f.total_charge or Decimal("0")),
            "total_discount": float(f.total_discount or Decimal("0")),
            "net_charge": float((f.total_charge or Decimal("0")) - (f.total_discount or Decimal("0"))),
            "total_paid": float(f.total_paid or Decimal("0")),
            "balance": float(f.balance or Decimal("0")),
            "transactions": [
                {
                    "id": tx.id,
                    "type": tx.transaction_type.value if tx.transaction_type else "UNKNOWN",
                    "category": tx.category.value if tx.category else "UNKNOWN",
                    "description": tx.description,
                    "amount": float(tx.amount),
                    "is_voided": tx.is_voided,
                    "created_at": tx.created_at.isoformat() if tx.created_at else None,
                }
                for tx in sorted(f.transactions, key=lambda t: t.created_at or 0)
            ] if include_transactions else [],
        }
        for f in folios_raw
    ]

    return JSONResponse(result)


@router.get("/api/pms/checkout/transfer-targets", tags=["PMS"])
def api_checkout_transfer_targets(
    request: Request,
    source_stay_id: int = Query(...),
    q: str = Query(default=""),
    limit: int = Query(default=12, ge=1, le=30),
    db: Session = Depends(get_db),
):
    _require_login(request)

    source = db.query(HotelStay).filter(HotelStay.id == source_stay_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú nguồn")

    term = (q or "").strip()
    query = (
        db.query(HotelStay, HotelRoom, HotelGuest, Folio)
        .join(HotelRoom, HotelRoom.id == HotelStay.room_id)
        .outerjoin(HotelGuest, (HotelGuest.stay_id == HotelStay.id) & (HotelGuest.is_primary == True))
        .join(Folio, Folio.stay_id == HotelStay.id)
        .filter(
            HotelStay.id != source_stay_id,
            HotelStay.branch_id == source.branch_id,
            HotelStay.status == HotelStayStatus.ACTIVE,
            Folio.status.in_([FolioStatus.OPEN, FolioStatus.DEBT]),
        )
        .order_by(HotelRoom.room_number.asc(), HotelStay.id.desc())
    )
    if term:
        like = f"%{term}%"
        query = query.filter(or_(
            HotelRoom.room_number.ilike(like),
            HotelGuest.full_name.ilike(like),
            HotelGuest.phone.ilike(like),
            Folio.folio_code.ilike(like),
        ))

    rows = query.limit(limit).all()
    seen = set()
    items = []
    for stay, room, guest, folio in rows:
        if stay.id in seen:
            continue
        seen.add(stay.id)
        room_balance = float(folio.balance or Decimal("0"))
        if stay.status == HotelStayStatus.ACTIVE:
            try:
                preview = preview_checkout(db=db, stay_id=stay.id, now=_now_vn())
                room_balance = float(preview.get("projected_balance", room_balance) or 0)
            except Exception:
                pass
        items.append({
            "stay_id": stay.id,
            "room_id": room.id if room else None,
            "room_number": room.room_number if room else "—",
            "guest_name": guest.full_name if guest else "Khách lưu trú",
            "guest_phone": guest.phone if guest else None,
            "folio_id": folio.id,
            "folio_code": folio.folio_code,
            "balance": room_balance,
            "check_in_at": stay.check_in_at.isoformat() if stay.check_in_at else None,
        })
    return JSONResponse({"items": items})


@router.post("/api/pms/checkout/{source_stay_id}/transfer-bill", tags=["PMS"])
def api_checkout_transfer_bill(
    request: Request,
    source_stay_id: int,
    target_stay_id: int = Query(...),
    amount: Optional[str] = Query(default=None),
    note: str = Query(default=""),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if source_stay_id == target_stay_id:
        raise HTTPException(status_code=400, detail="Không thể gộp hoá đơn vào cùng phòng")

    try:
        with db.begin():
            source_stay = (
                db.query(HotelStay)
                .options(selectinload(HotelStay.room))
                .filter(HotelStay.id == source_stay_id)
                .with_for_update()
                .first()
            )
            target_stay = (
                db.query(HotelStay)
                .options(selectinload(HotelStay.room))
                .filter(HotelStay.id == target_stay_id)
                .with_for_update()
                .first()
            )
            if not source_stay or not target_stay:
                raise HTTPException(status_code=404, detail="Không tìm thấy phòng nguồn hoặc phòng nhận")
            if source_stay.branch_id != target_stay.branch_id:
                raise HTTPException(status_code=400, detail="Chỉ gộp hoá đơn trong cùng chi nhánh")
            if target_stay.status != HotelStayStatus.ACTIVE:
                raise HTTPException(status_code=400, detail="Phòng nhận phải đang lưu trú")

            source_folio = (
                db.query(Folio)
                .filter(Folio.stay_id == source_stay_id, Folio.status.in_([FolioStatus.OPEN, FolioStatus.DEBT]))
                .order_by(Folio.id.asc())
                .with_for_update()
                .first()
            )
            target_folio = (
                db.query(Folio)
                .filter(Folio.stay_id == target_stay_id, Folio.status.in_([FolioStatus.OPEN, FolioStatus.DEBT]))
                .order_by(Folio.id.asc())
                .with_for_update()
                .first()
            )
            if not source_folio:
                raise HTTPException(status_code=400, detail="Phòng nguồn không có hoá đơn mở để gộp")
            if not target_folio:
                raise HTTPException(status_code=400, detail="Phòng nhận không có hoá đơn mở")

            from ...services.folio_service import rebalance_folio
            rebalance_folio(db, source_folio)
            rebalance_folio(db, target_folio)
            source_balance = money(source_folio.balance or Decimal("0"))
            if source_stay.status == HotelStayStatus.ACTIVE:
                preview = preview_checkout(db=db, stay_id=source_stay_id, now=_now_vn())
                source_balance = money(preview.get("projected_balance", source_balance))
            if source_balance <= Decimal("0"):
                raise HTTPException(status_code=400, detail="Phòng nguồn không còn số tiền cần gộp")

            transfer_amount = money(amount) if amount else source_balance
            if transfer_amount <= Decimal("0"):
                raise HTTPException(status_code=400, detail="Số tiền gộp phải lớn hơn 0")
            if transfer_amount > source_balance:
                raise HTTPException(status_code=400, detail="Số tiền gộp vượt quá số còn phải thanh toán")

            source_room = source_stay.room.room_number if source_stay.room else "—"
            target_room = target_stay.room.room_number if target_stay.room else "—"
            clean_note = (note or "").strip()
            suffix = f" — {clean_note}" if clean_note else ""

            source_tx = FolioTransaction(
                folio_id=source_folio.id,
                stay_id=source_stay.id,
                branch_id=source_stay.branch_id,
                transaction_type=FolioTransactionType.DISCOUNT_MANUAL,
                category=FolioTransactionCategory.DISCOUNT,
                description=f"Gộp hoá đơn sang phòng {target_room}{suffix}",
                amount=money(-transfer_amount),
                quantity=Decimal("1"),
                unit_price=money(transfer_amount),
                reference_id=target_stay.id,
                reference_type="room_bill_transfer",
                created_by=user.get("id"),
            )
            target_tx = FolioTransaction(
                folio_id=target_folio.id,
                stay_id=target_stay.id,
                branch_id=target_stay.branch_id,
                transaction_type=FolioTransactionType.SURCHARGE,
                category=FolioTransactionCategory.SURCHARGE,
                description=f"Nhận gộp hoá đơn từ phòng {source_room}{suffix}",
                amount=transfer_amount,
                quantity=Decimal("1"),
                unit_price=money(transfer_amount),
                reference_id=source_stay.id,
                reference_type="room_bill_transfer",
                created_by=user.get("id"),
            )
            db.add_all([source_tx, target_tx])
            db.flush()
            rebalance_folio(db, source_folio)
            rebalance_folio(db, target_folio)

        return JSONResponse({
            "status": "success",
            "message": f"Đã gộp {float(transfer_amount):,.0f}đ từ phòng {source_room} sang phòng {target_room}",
            "source": {
                "stay_id": source_stay.id,
                "room_number": source_room,
                "folio_id": source_folio.id,
                "balance": float(source_folio.balance or Decimal("0")),
                "transaction_id": source_tx.id,
            },
            "target": {
                "stay_id": target_stay.id,
                "room_number": target_room,
                "folio_id": target_folio.id,
                "balance": float(target_folio.balance or Decimal("0")),
                "transaction_id": target_tx.id,
            },
            "amount": float(transfer_amount),
        })
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[Checkout Transfer] source_stay_id={source_stay_id} target_stay_id={target_stay_id}: {exc}")
        raise HTTPException(status_code=400, detail=f"Không thể gộp hoá đơn: {exc}")


@router.post("/api/pms/checkout/transfer/{tx_id}/undo", tags=["PMS"])
def api_checkout_undo_transfer(
    request: Request,
    tx_id: int,
    reason: str = Query(default="Hủy gộp hoá đơn"),
    db: Session = Depends(get_db),
):
    """
    Hủy gộp hoá đơn — void cả 2 giao dịch paired (source DISCOUNT + target SURCHARGE).
    Gọi từ phòng nhận khi muốn hoàn tác thao tác gộp.
    """
    user = _require_login(request)
    actor_id = user.get("id")

    try:
        with db.begin():
            tx_a = db.query(FolioTransaction).filter(
                FolioTransaction.id == tx_id,
                FolioTransaction.reference_type == "room_bill_transfer",
            ).with_for_update().first()
            if not tx_a:
                raise HTTPException(status_code=404, detail="Giao dịch không tìm thấy hoặc không phải giao dịch gộp")
            if tx_a.is_voided:
                raise HTTPException(status_code=400, detail="Giao dịch đã bị hủy trước đó")

            folio_a = db.query(Folio).filter(Folio.id == tx_a.folio_id).with_for_update().first()
            if folio_a and folio_a.status == FolioStatus.CLOSED:
                raise HTTPException(status_code=400, detail="Folio đã đóng, không thể hủy gộp")

            tx_b = db.query(FolioTransaction).filter(
                FolioTransaction.stay_id == tx_a.reference_id,
                FolioTransaction.reference_type == "room_bill_transfer",
                FolioTransaction.reference_id == tx_a.stay_id,
                FolioTransaction.is_voided == False,
            ).with_for_update().first()

            if tx_b:
                folio_b = db.query(Folio).filter(Folio.id == tx_b.folio_id).with_for_update().first()
                if folio_b and folio_b.status == FolioStatus.CLOSED:
                    raise HTTPException(status_code=400, detail="Folio phòng nguồn đã đóng, không thể hủy gộp")

            mark_transaction_void(db, tx_a, reason, actor_id)
            if tx_b:
                mark_transaction_void(db, tx_b, reason, actor_id)
            db.flush()

        voided_ids = [tx_a.id] + ([tx_b.id] if tx_b else [])
        return JSONResponse({
            "status": "success",
            "message": "Đã hủy gộp hoá đơn",
            "voided_tx_ids": voided_ids,
        })
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[Undo Transfer] tx_id={tx_id}: {exc}")
        raise HTTPException(status_code=400, detail=f"Không thể hủy gộp: {exc}")


@router.get("/api/pms/checkout/{stay_id}/preview-checked-out", tags=["PMS"])
def api_checkout_preview_checked_out(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
):
    """
    Preview cho checked-out stays — tính balance nhanh từ cache + SQL aggregate.

    KHÔNG gọi pricing engine — chỉ đọc dữ liệu đã ghi nhận tại thời điểm checkout.
    Loại trừ REFUND/REFUND_PAYMENT khỏi charges (đồng bộ với rebalance_folio).
    """
    _require_login(request)

    stay = db.query(HotelStay).filter(HotelStay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")
    if stay.status == HotelStayStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Stay đang active, dùng /preview thay thế")

    folios = (
        db.query(Folio)
        .filter(Folio.stay_id == stay_id)
        .order_by(Folio.id.asc())
        .all()
    )
    folio_totals = get_folio_financial_totals(db, [f.id for f in folios])

    total_room_charge = sum((folio_totals[f.id]["room_charge"] for f in folios), Decimal("0"))
    total_service_charge = sum((folio_totals[f.id]["service_charge"] for f in folios), Decimal("0"))
    total_surcharge = sum((folio_totals[f.id]["surcharge"] for f in folios), Decimal("0"))
    total_discount = sum((folio_totals[f.id]["discount"] for f in folios), Decimal("0"))
    total_payment = sum((folio_totals[f.id]["payment"] for f in folios), Decimal("0"))
    total_deposit_used = sum((folio_totals[f.id]["deposit_used"] for f in folios), Decimal("0"))

    # Import pricing engine
    from ...services.pricing_service import calculate_full_charge, MODE_TO_STAY_TYPE
    
    room = db.query(HotelRoom).options(selectinload(HotelRoom.room_type_obj)).filter(HotelRoom.id == stay.room_id).first()
    rt = room.room_type_obj if room else None
    
    # Folio đã checkout là nguồn chuẩn. Pricing engine chỉ fallback cho dữ liệu cũ
    # thiếu dòng tiền phòng trong ledger, không được ghi đè phát sinh đã lưu.
    breakdown = []
    if rt and stay.check_in_at and stay.check_out_at and total_room_charge <= Decimal("0"):
        _pricing_total, breakdown = calculate_full_charge(
            MODE_TO_STAY_TYPE.get(stay.pricing_mode_initial or "AUTO", "AUTO"),
            rt,
            stay.check_in_at,
            stay.check_out_at,
        )
        for item in breakdown:
            if item.get("type") in ("ROOM_CHARGE", "HOURLY_CHARGE"):
                total_room_charge += money(item.get("amount", 0))
            else:
                total_surcharge += money(item.get("amount", 0))

    total_charge = money(total_room_charge + total_service_charge + total_surcharge)
    net_charge = money(total_charge - total_discount)
    total_paid = money(total_payment + total_deposit_used)
    projected_balance = money(net_charge - total_paid)

    return JSONResponse({
        "stay_id": stay_id,
        "is_checked_out": True,
        "room_number": room.room_number if room else None,
        "check_in_at": stay.check_in_at.isoformat() if stay.check_in_at else None,
        "check_out_at": stay.check_out_at.isoformat() if stay.check_out_at else None,
        # Charges breakdown (từ pricing engine)
        "room_charge": float(total_room_charge),
        "existing_charges": float(total_service_charge + total_surcharge),
        "existing_service_charges": float(total_service_charge),
        "existing_surcharge_charges": float(total_surcharge),
        "existing_discounts": float(total_discount),
        "extra_charge": 0.0,
        "discount": 0.0,
        # Totals
        "total_charge": float(total_charge),
        "net_charge": float(net_charge),
        "deposit_used": float(total_deposit_used),
        "effective_paid": float(total_payment),
        "total_paid": float(total_paid),
        "projected_balance": float(projected_balance),
        "final_total": float(net_charge),
        "breakdown": [
            {**b, "amount": float(money(b.get("amount", 0)))}
            for b in breakdown
        ],
        "folio_summary": [
            {
                "id": f.id,
                "folio_code": f.folio_code,
                "balance": float(f.balance or Decimal("0")),
                "total_charge": float(f.total_charge or Decimal("0")),
                "total_discount": float(f.total_discount or Decimal("0")),
                "net_charge": float((f.total_charge or Decimal("0")) - (f.total_discount or Decimal("0"))),
                "total_paid": float(f.total_paid or Decimal("0")),
                "effective_paid": float(total_payment),
                "deposit_used": float(total_deposit_used),
                "status": f.status.value if f.status else "OPEN",
            }
            for f in folios
        ],
        "folios": [
            {
                "id": f.id,
                "folio_code": f.folio_code,
                "status": f.status.value if f.status else "OPEN",
                "total_charge": float(f.total_charge or Decimal("0")),
                "total_discount": float(f.total_discount or Decimal("0")),
                "net_charge": float((f.total_charge or Decimal("0")) - (f.total_discount or Decimal("0"))),
                "total_paid": float(f.total_paid or Decimal("0")),
                "balance": float(f.balance or Decimal("0")),
                "transactions": [],
            }
            for f in folios
        ],
        "transactions": [],
        "needs_payment": projected_balance > 0,
        "needs_refund": projected_balance < 0,
    })


@router.post("/api/pms/checkout/{stay_id}", tags=["PMS"])
def api_checkout(
    request: Request,
    background_tasks: BackgroundTasks,
    stay_id: int,
    discount: Optional[str] = Query(default=None),
    extra_charge: Optional[str] = Query(default=None),
    refund_method: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Atomic Checkout — Tất cả trong một transaction.
    
    Luồng:
    1. Preview (recalculate) balance
    2. Post all charges to Folio
    3. Apply discount/extra_charge
    4. Rebalance Folio
    5. Handle debt/refund automatically
    6. Close Folio
    7. Checkout Stay
    """
    user = _require_login(request)

    try:
        now = _now_vn()
        try:
            calc_discount = money(discount) if discount else Decimal("0")
            calc_extra = money(extra_charge) if extra_charge else Decimal("0")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Số tiền không hợp lệ: {exc}")

        # Bước 1: Execute checkout (tính tiền, post charges, close folio)
        # execute_checkout dùng flush() - commit NGAY sau để user nhận response nhanh
        result = execute_checkout(
            db=db,
            stay_id=stay_id,
            discount=calc_discount,
            extra_charge=calc_extra,
            user_id=user.get("id"),
            now=now,
            refund_method=refund_method,
        )

        stay = result["stay"]
        room = result["room"]
        final_total = result["final_total"]

        deposit_amount = money(stay.deposit or Decimal("0"))
        breakdown = result.get("breakdown")
        folio_id = result["folios"][0].id if result.get("folios") else None

        # COMMIT NGAY - checkout hoàn tất
        db.commit()

        background_tasks.add_task(
            _run_checkout_side_effects,
            stay_id=stay_id,
            user_id=user.get("id"),
            final_total=str(final_total),
            discount=str(calc_discount),
            extra_charge=str(calc_extra),
            deposit_amount=str(deposit_amount),
            breakdown=breakdown,
            folio_id=folio_id,
        )

        # Response
        status_msg = "debt_status"
        if result["status"] == "checked_out_success":
            status_msg = "success"
        elif result["status"] == "checked_out_with_refund":
            status_msg = "refund"

        return JSONResponse({
            "status": status_msg,
            "debt_status": result.get("status"),
            "debt_amount": float(result.get("debt", Decimal("0"))),
            "refund_amount": float(result.get("refund", Decimal("0"))),
            "message": f"Check-out thành công! Phòng {room.room_number if room else '—'}",
            "stay_id": stay.id,
            "room_number": room.room_number if room else "—",
            "check_in_at": stay.check_in_at.isoformat(),
            "check_out_at": now.isoformat(),
            "total_price": float(final_total),
            "deposit": float(stay.deposit) if stay.deposit else 0.0,
            "discount": float(calc_discount),
            "extra_charge": float(calc_extra),
            "amount_due": float(money(final_total - money(stay.deposit or Decimal("0")))),
        })

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        logger.error(f"PMS Checkout Error (stay_id={stay_id}):\n{err_msg}")
        return JSONResponse(
            status_code=400,
            content={"detail": f"Lỗi hệ thống khi trả phòng: {str(e)}"},
        )


# ─────────────────────────── Re-checkin API ────────────────────────────────

@router.post("/api/pms/checkout/{stay_id}/recheckin", tags=["PMS"])
def api_recheckin(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
):
    """
    Nhận phòng lại (re-checkin) — mở lại stay đã checkout.
    Ràng buộc:
    1. Stay phải ở trạng thái CHECKED_OUT
    2. Checkout chưa quá 10 phút
    3. Phòng phải trống (không có stay ACTIVE nào trên phòng đó)
    """
    user = _require_login(request)
    now = _now_vn()

    stay = (
        db.query(HotelStay)
        .options(selectinload(HotelStay.room))
        .filter(HotelStay.id == stay_id)
        .first()
    )
    if not stay:
        raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú")

    if stay.status != HotelStayStatus.CHECKED_OUT:
        raise HTTPException(status_code=400, detail="Lưu trú chưa checkout, không thể nhận lại")

    if not stay.check_out_at:
        raise HTTPException(status_code=400, detail="Thiếu thời điểm checkout")

    elapsed = (now - stay.check_out_at).total_seconds()
    LIMIT_SECONDS = 10 * 60
    if elapsed > LIMIT_SECONDS:
        mins = int(elapsed // 60)
        raise HTTPException(
            status_code=400,
            detail=f"Đã quá thời hạn nhận phòng lại ({mins} phút > 10 phút cho phép)"
        )

    room = stay.room
    if room:
        active_on_room = (
            db.query(HotelStay)
            .filter(
                HotelStay.room_id == room.id,
                HotelStay.status == HotelStayStatus.ACTIVE,
            )
            .first()
        )
        if active_on_room:
            raise HTTPException(
                status_code=400,
                detail=f"Phòng {room.room_number} đã có khách khác. Không thể nhận phòng lại."
            )

    try:
        with db.begin():
            stay.status = HotelStayStatus.ACTIVE
            stay.check_out_at = None
            stay.total_price = None
            stay.discount = None
            stay.extra_charge = None
            stay.pricing_mode_final = None

            db.query(HotelGuest).filter(
                HotelGuest.stay_id == stay_id,
            ).update({"check_out_at": None}, synchronize_session=False)

            checkout_tx_types = [
                FolioTransactionType.ROOM_CHARGE,
                FolioTransactionType.HOURLY_CHARGE,
                FolioTransactionType.EARLY_CHECKIN_FEE,
                FolioTransactionType.LATE_CHECKOUT_FEE,
                FolioTransactionType.REFUND,
            ]
            db.query(FolioTransaction).filter(
                FolioTransaction.stay_id == stay_id,
                FolioTransaction.transaction_type.in_(checkout_tx_types),
            ).delete(synchronize_session=False)

            db.query(DebtRecord).filter(
                DebtRecord.stay_id == stay_id,
                DebtRecord.status == "pending",
            ).delete(synchronize_session=False)

            from ...services.folio_service import rebalance_folio

            folios = (
                db.query(Folio)
                .filter(Folio.stay_id == stay_id)
                .all()
            )
            for folio in folios:
                folio.status = FolioStatus.OPEN
                folio.closed_at = None
                folio.debt_amount = None
                folio.debt_status = None
                folio.debt_note = None
                folio.refund_amount = None
                folio.refund_status = None
                folio.refund_note = None
                rebalance_folio(db, folio)

        room_number = room.room_number if room else "—"
        return JSONResponse({
            "status": "success",
            "message": f"Nhận phòng lại thành công! Phòng {room_number}",
            "stay_id": stay_id,
            "room_number": room_number,
        })

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"PMS Re-checkin Error (stay_id={stay_id}):\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {str(e)}")


# ─────────────────────────── Debt Record APIs ────────────────────────────────

@router.post("/api/pms/checkout/{stay_id}/debt-record", tags=["PMS"])
def api_create_debt_record(
    request: Request,
    stay_id: int,
    debt_amount: str = Query(...),
    note: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Ghi nhận công nợ cho một stay đã checkout."""
    user = _require_login(request)
    now = _now_vn()

    try:
        amount = money(debt_amount)
    except Exception:
        raise HTTPException(status_code=400, detail="Số tiền không hợp lệ")

    if amount <= Decimal("0"):
        raise HTTPException(status_code=400, detail="Số tiền nợ phải lớn hơn 0")

    folio = (
        db.query(Folio)
        .filter(Folio.stay_id == stay_id)
        .order_by(Folio.id.desc())
        .first()
    )
    if not folio:
        raise HTTPException(status_code=404, detail="Không tìm thấy folio")

    with db.begin():
        dr = DebtRecord(
            folio_id=folio.id,
            stay_id=stay_id,
            branch_id=folio.branch_id,
            debt_amount=amount,
            paid_amount=Decimal("0"),
            remaining_amount=amount,
            status="pending",
            note=note or None,
            created_by=user.get("id"),
        )
        db.add(dr)

        folio.debt_amount = amount
        folio.debt_status = "pending"
        folio.debt_note = note or None

    db.refresh(dr)

    return JSONResponse({
        "id": dr.id,
        "debt_amount": float(dr.debt_amount),
        "remaining_amount": float(dr.remaining_amount),
        "status": dr.status,
        "note": dr.note,
        "created_at": dr.created_at.isoformat() if dr.created_at else None,
        "message": "Ghi nhận công nợ thành công",
    })


@router.post("/api/pms/checkout/debt/{debt_record_id}/settle", tags=["PMS"])
def api_settle_debt(
    request: Request,
    debt_record_id: int,
    amount: str = Query(...),
    method: str = Query(default="CASH"),
    note: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Thanh toán công nợ (toàn bộ hoặc một phần)."""
    user = _require_login(request)
    now = _now_vn()

    try:
        pay_amount = money(amount)
    except Exception:
        raise HTTPException(status_code=400, detail="Số tiền không hợp lệ")

    if pay_amount <= Decimal("0"):
        raise HTTPException(status_code=400, detail="Số tiền phải lớn hơn 0")

    dr = (
        db.query(DebtRecord)
        .filter(DebtRecord.id == debt_record_id, DebtRecord.status != "settled")
        .first()
    )
    if not dr:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi nợ hoặc đã thanh toán xong")

    if pay_amount > dr.remaining_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Số tiền ({pay_amount}) vượt quá số còn lại ({dr.remaining_amount})"
        )

    folio = db.query(Folio).filter(Folio.id == dr.folio_id).first()

    with db.begin():
        tx = FolioTransaction(
            folio_id=folio.id,
            stay_id=dr.stay_id,
            branch_id=folio.branch_id,
            transaction_type=FolioTransactionType.DEBT_PAYMENT,
            category=FolioTransactionCategory.PAYMENT,
            description=f"Thanh toán công nợ ({method})" + (f": {note}" if note else ""),
            amount=money(-pay_amount),
            quantity=Decimal("1"),
            unit_price=pay_amount,
            reference_type="debt_record",
            reference_id=dr.id,
            created_by=user.get("id"),
        )
        db.add(tx)
        db.flush()

        dr.paid_amount = money(dr.paid_amount + pay_amount)
        dr.remaining_amount = money(dr.remaining_amount - pay_amount)
        dr.status = "settled" if dr.remaining_amount <= Decimal("0") else "partial"
        dr.settled_by = user.get("id")
        dr.settled_at = now
        dr.settlement_tx_id = tx.id

        from ...services.folio_service import rebalance_folio
        rebalance_folio(db, folio)

        folio.debt_amount = dr.remaining_amount
        folio.debt_status = dr.status
        if dr.remaining_amount <= Decimal("0"):
            folio.debt_status = "settled"
            folio.debt_amount = Decimal("0")
            if folio.balance >= Decimal("0"):
                folio.status = FolioStatus.CLOSED
                folio.closed_at = now

    db.refresh(dr)

    return JSONResponse({
        "id": dr.id,
        "paid_amount": float(pay_amount),
        "remaining_amount": float(dr.remaining_amount),
        "status": dr.status,
        "message": "Thanh toán công nợ thành công",
    })


# ─────────────────────────── Refund APIs ─────────────────────────────────────

@router.post("/api/pms/checkout/overpayment/{folio_id}/refund", tags=["PMS"])
def api_create_refund(
    request: Request,
    folio_id: int,
    amount: str = Query(...),
    method: str = Query(default="CASH"),
    account: str = Query(default=""),
    note: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Tạo yêu cầu hoàn tiền cho folio có balance < 0 (dư tiền)."""
    user = _require_login(request)
    now = _now_vn()

    try:
        refund_amt = money(amount)
    except Exception:
        raise HTTPException(status_code=400, detail="Số tiền không hợp lệ")

    if refund_amt <= Decimal("0"):
        raise HTTPException(status_code=400, detail="Số tiền hoàn phải lớn hơn 0")

    folio = (
        db.query(Folio)
        .filter(Folio.id == folio_id)
        .first()
    )
    if not folio:
        raise HTTPException(status_code=404, detail="Không tìm thấy folio")

    balance = money(folio.balance or Decimal("0"))
    if balance >= Decimal("0"):
        raise HTTPException(status_code=400, detail="Folio không có dư tiền để hoàn")

    max_refund = money(abs(balance))
    if refund_amt > max_refund:
        raise HTTPException(
            status_code=400,
            detail=f"Số tiền hoàn ({refund_amt}) vượt quá số dư ({max_refund})"
        )

    with db.begin():
        rr = RefundRecord(
            folio_id=folio_id,
            stay_id=folio.stay_id,
            branch_id=folio.branch_id,
            refund_amount=refund_amt,
            refund_method=method,
            refund_account=account or None,
            note=note or None,
            created_by=user.get("id"),
        )
        db.add(rr)

        folio.refund_status = "pending"
        folio.refund_note = note or None

    db.refresh(rr)

    return JSONResponse({
        "id": rr.id,
        "refund_amount": float(rr.refund_amount),
        "refund_method": rr.refund_method,
        "refund_account": rr.refund_account,
        "status": rr.status,
        "note": rr.note,
        "created_at": rr.created_at.isoformat() if rr.created_at else None,
        "message": "Yêu cầu hoàn tiền đã được tạo, chờ duyệt",
    })


@router.post("/api/pms/checkout/refund/{refund_record_id}/approve", tags=["PMS"])
def api_approve_refund(
    request: Request,
    refund_record_id: int,
    note: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Duyệt và thực hiện hoàn tiền."""
    user = _require_login(request)
    now = _now_vn()

    rr = (
        db.query(RefundRecord)
        .filter(RefundRecord.id == refund_record_id, RefundRecord.refund_amount > Decimal("0"))
        .first()
    )
    if not rr:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi hoàn tiền")

    folio = db.query(Folio).filter(Folio.id == rr.folio_id).first()
    if not folio:
        raise HTTPException(status_code=404, detail="Không tìm thấy folio")

    with db.begin():
        tx = FolioTransaction(
            folio_id=folio.id,
            stay_id=rr.stay_id,
            branch_id=folio.branch_id,
            transaction_type=FolioTransactionType.REFUND_PAYMENT,
            category=FolioTransactionCategory.REFUND,
            description="Hoàn tiền dư" + (f": {note}" if note else ""),
            amount=rr.refund_amount,
            quantity=Decimal("1"),
            unit_price=rr.refund_amount,
            reference_type="refund_record",
            reference_id=rr.id,
            created_by=user.get("id"),
        )
        db.add(tx)
        db.flush()

        rr.settled_by = user.get("id")
        rr.settled_at = now
        rr.refund_tx_id = tx.id

        from ...services.folio_service import rebalance_folio
        rebalance_folio(db, folio)

        folio.refund_amount = money(folio.refund_amount + rr.refund_amount)
        folio.refund_status = "refunded"
        folio.refund_note = note or folio.refund_note

        if money(folio.balance) >= Decimal("0"):
            folio.status = FolioStatus.CLOSED
            folio.closed_at = now

        # ── Post sổ giao ca cho khoản hoàn tiền dư (refund-aware theo quỹ) ──
        try:
            from ...db.models import (
                ShiftReportTransaction, ShiftReportStatus, TransactionType, Branch, HotelStay, HotelRoom
            )
            from ...services.shift_report_service import (
                _generate_shift_code, build_shift_transaction_info, normalize_shift_payment_method,
            )
            branch = db.query(Branch).filter(Branch.id == folio.branch_id).first() if folio.branch_id else None
            if branch:
                refund_pm = normalize_shift_payment_method(rr.refund_method)
                room_number = None
                if folio.stay_id:
                    _stay = db.query(HotelStay).options(selectinload(HotelStay.room)).filter(HotelStay.id == folio.stay_id).first()
                    room_number = _stay.room.room_number if _stay and _stay.room else None
                shift_tx = ShiftReportTransaction(
                    transaction_code=_generate_shift_code(db, branch.branch_code or "XX"),
                    transaction_type=TransactionType.CASH_EXPENSE,  # tiền ra; quỹ quyết định bởi payment_method
                    amount=rr.refund_amount,
                    room_number=room_number,
                    transaction_info=build_shift_transaction_info(
                        "Hoàn tiền",
                        room_number=room_number,
                        folio_code=folio.folio_code,
                        amount=rr.refund_amount,
                        method=refund_pm,
                        reason=note or "Hoàn tiền dư",
                    ),
                    branch_id=branch.id,
                    recorder_id=user.get("id"),
                    created_datetime=now,
                    status=ShiftReportStatus.PENDING,
                    stay_id=folio.stay_id,
                    folio_id=folio.id,
                    folio_transaction_id=tx.id,
                    payment_method=refund_pm,
                    is_auto_posted=True,
                )
                db.add(shift_tx)
                db.flush()
                logger.info(f"[SHIFT_SYNC] REFUND(approve): shift_tx={shift_tx.id} folio={folio.id} method={refund_pm.value} amount={rr.refund_amount}")
        except Exception as e:
            logger.error(f"[SHIFT_SYNC] approve refund post failed: {e}", exc_info=True)

    db.refresh(rr)

    return JSONResponse({
        "id": rr.id,
        "refund_amount": float(rr.refund_amount),
        "status": "refunded",
        "message": "Hoàn tiền thành công",
        "new_balance": float(folio.balance),
    })


@router.post("/api/pms/checkout/refund/{refund_record_id}/cancel", tags=["PMS"])
def api_cancel_refund(
    request: Request,
    refund_record_id: int,
    reason: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Hủy yêu cầu hoàn tiền."""
    user = _require_login(request)

    rr = db.query(RefundRecord).filter(RefundRecord.id == refund_record_id).first()
    if not rr:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi hoàn tiền")

    with db.begin():
        rr.refund_status = "cancelled"
        rr.note = (rr.note or "") + (f" [Hủy: {reason}]" if reason else " [Hủy]")

        folio = db.query(Folio).filter(Folio.id == rr.folio_id).first()
        if folio:
            folio.refund_status = "cancelled"
            folio.refund_note = None

    return JSONResponse({"message": "Đã hủy yêu cầu hoàn tiền"})
