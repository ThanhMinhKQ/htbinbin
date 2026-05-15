# app/api/pms/folio_api.py
"""
Folio / Billing API — Line-by-line financial ledger per stay.
All money changes = INSERT only. Never UPDATE amount on existing rows.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
import logging
import re

logger = logging.getLogger(__name__)

from pydantic import BaseModel
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload

from ...db.models import (
    DebtRecord, Folio, FolioStatus,
    FolioTransaction, FolioTransactionType, FolioTransactionCategory,
    HotelRoom, HotelStay, HotelGuest,
    Payment, PaymentMethod, RefundRecord, User,
)
from ...db.session import get_db
from ...services.folio_service import (
    close_folio_with_balance_check,
    create_charge_transaction,
    create_discount_transaction,
    create_folio,
    create_payment_with_transaction,
    mark_transaction_void,
    merge_folios as merge_folios_service,
    recalculate_all_folios_cache,
    rebalance_folio,
    refund_payment_and_create_transaction,
    transfer_transactions_between_folios,
)
from ...services.guest_crm_service import sync_guest_crm_after_debt_payment
from ...services.pricing_service import money, calculate_full_charge, MODE_TO_STAY_TYPE
from .pms_helpers import _require_login, _now_vn
from fastapi.templating import Jinja2Templates
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/api/pms/folio", tags=["PMS Folio"])


# ─────────────────────────── Helpers ──────────────────────────────

def _get_folio_or_404(db: Session, folio_id: int, *, for_update: bool = False) -> Folio:
    if for_update:
        # Lock folio row trước (không JOIN — PostgreSQL không cho FOR UPDATE trên nullable side)
        locked = db.query(Folio).filter(Folio.id == folio_id).with_for_update().first()
        if not locked:
            raise HTTPException(status_code=404, detail="Folio không tìm thấy")
        # Load relationships sau khi đã lock
        db.refresh(locked)
        return locked
    query = db.query(Folio).options(
        joinedload(Folio.refund_records),
        joinedload(Folio.debt_records),
    ).filter(Folio.id == folio_id)
    folio = query.first()
    if not folio:
        raise HTTPException(status_code=404, detail="Folio không tìm thấy")
    return folio


def _parse_money_query(value: Optional[str], field_name: str) -> Decimal:
    try:
        parsed = money(value)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} không hợp lệ") from exc
    if parsed <= Decimal("0"):
        raise HTTPException(status_code=400, detail=f"{field_name} phải lớn hơn 0")
    return parsed


def _parse_quantity_query(value: Optional[str]) -> Decimal:
    try:
        qty = Decimal(str(value if value is not None else 1))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="quantity không hợp lệ") from exc
    if qty <= Decimal("0"):
        raise HTTPException(status_code=400, detail="quantity phải lớn hơn 0")
    return qty


def _session_user_id(db: Session, user: dict) -> Optional[int]:
    raw_id = user.get("id") or user.get("user_id")
    if raw_id:
        try:
            return int(raw_id)
        except (TypeError, ValueError):
            pass

    code = user.get("code") or user.get("employee_code") or user.get("login_code")
    if code:
        found = db.query(User.id).filter(User.employee_code == code).first()
        if found:
            return int(found[0])
    return None


# ─────────────────────────── Fix Cache ───────────────────────────

@router.post("/fix-cache")
def fix_folio_cache(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Recalculate cache cho tất cả folios (fix dữ liệu cũ).
    """
    _require_login(request)
    result = recalculate_all_folios_cache(db)
    db.commit()
    return JSONResponse({
        "message": f"Đã fix {result['fixed_count']} folios",
        "details": result,
    })

# ─────────────────────────── Folio CRUD ──────────────────────────

@router.get("/{stay_id}")
def get_folio_by_stay(
    request: Request,
    stay_id: int,
    include_transactions: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """
    Lấy danh sách folio của một stay.
    Tự động tạo folio mới nếu chưa có (lazy creation).
    """
    _require_login(request)

    stay = db.query(HotelStay).filter(HotelStay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay không tìm thấy")

    stay_status = stay.status.value if hasattr(stay.status, "value") else stay.status
    include_full_ledger = include_transactions or stay_status == "ACTIVE"
    load_options = [
        joinedload(Folio.refund_records),
        joinedload(Folio.debt_records),
    ]
    if include_full_ledger:
        load_options.append(joinedload(Folio.transactions).joinedload(FolioTransaction.creator))
        load_options.append(joinedload(Folio.transactions).joinedload(FolioTransaction.voider))
        load_options.append(joinedload(Folio.payments).joinedload(Payment.creator))

    folios = db.query(Folio).options(*load_options).filter(Folio.stay_id == stay_id).order_by(Folio.id.asc()).all()
    if not folios:
        first_folio = create_folio(db=db, stay=stay)
        db.commit()
        db.refresh(first_folio)
        folios = [first_folio]

    return JSONResponse({
        "folios": [_folio_to_dict(f, include_transactions=include_full_ledger) for f in folios],
    })

@router.get("/{folio_id}/print")
def print_folio(
    request: Request,
    folio_id: int,
    db: Session = Depends(get_db),
):
    """Render HTML Hóa đơn để In/PDF"""
    user = _require_login(request)
    folio = _get_folio_or_404(db, folio_id)
    stay = db.query(HotelStay).options(
        joinedload(HotelStay.branch),
        joinedload(HotelStay.room).joinedload(HotelRoom.room_type_obj),
    ).filter(HotelStay.id == folio.stay_id).first()

    # Lấy danh sách giao dịch (loại trừ voided)
    txs_all = db.query(FolioTransaction).filter(
        FolioTransaction.folio_id == folio_id,
        FolioTransaction.is_voided == False,
    ).order_by(FolioTransaction.created_at.asc()).all()

    # Phân loại transactions cho hiển thị:
    # - charge_txs: các khoản tính phí (amount > 0, LOẠI TRỪ REFUND)
    # - payment_txs: các khoản thanh toán (PAYMENT, DEPOSIT_USED, DEBT_PAYMENT)
    # - refund_txs: các khoản hoàn tiền
    charge_txs = []
    payment_txs = []
    refund_txs = []
    has_room_charge_tx = False
    for t in txs_all:
        if t.transaction_type in (
            FolioTransactionType.REFUND,
            FolioTransactionType.REFUND_PAYMENT,
        ):
            refund_txs.append(t)
        elif t.amount < 0 and t.transaction_type in (
            FolioTransactionType.PAYMENT,
            FolioTransactionType.DEPOSIT_USED,
            FolioTransactionType.DEBT_PAYMENT,
        ):
            payment_txs.append(t)
        elif t.amount < 0 and t.category == FolioTransactionCategory.DISCOUNT:
            charge_txs.append(t)  # discount nằm trong bảng charge (số âm)
        elif t.amount > 0:
            charge_txs.append(t)  # room, service, surcharge...
            if t.transaction_type in (
                FolioTransactionType.ROOM_CHARGE,
                FolioTransactionType.HOURLY_CHARGE,
                FolioTransactionType.EARLY_CHECKIN_FEE,
                FolioTransactionType.LATE_CHECKOUT_FEE,
            ):
                has_room_charge_tx = True

    # ── Live room-charge preview khi stay còn ACTIVE & folio chưa post tiền phòng ──
    # ROOM_CHARGE chỉ được INSERT vào FolioTransaction lúc execute_checkout(),
    # nên trước checkout bảng "Chi tiết các khoản" sẽ trống. Tính live tại thời điểm in.
    live_charge_total = Decimal("0")
    is_live_preview = False
    stay_status = stay.status.value if stay and hasattr(stay.status, "value") else (stay.status if stay else None)
    if stay and stay_status == "ACTIVE" and not has_room_charge_tx:
        room_type_obj = stay.room.room_type_obj if stay.room else None
        if room_type_obj:
            try:
                effective_mode = stay.pricing_mode_initial or "AUTO"
                effective_stay_type = MODE_TO_STAY_TYPE.get(effective_mode, "AUTO")
                live_total, live_breakdown = calculate_full_charge(
                    effective_stay_type, room_type_obj, stay.check_in_at, _now_vn()
                )
                if live_breakdown:
                    is_live_preview = True
                    for item in live_breakdown:
                        amt = money(item.get("amount", 0))
                        if amt <= 0:
                            continue
                        live_charge_total += amt
                        charge_txs.append({
                            "description": item.get("description") or item.get("type") or "Tiền phòng",
                            "amount": amt,
                            "quantity": item.get("days") or item.get("hours") or 1,
                            "unit_price": None,
                            "created_at": stay.check_in_at,
                            "transaction_type": item.get("type"),
                            "category": "ROOM" if item.get("type") in ("ROOM_CHARGE", "HOURLY_CHARGE") else "SURCHARGE",
                        })
            except Exception as exc:
                logger.warning(f"[folio_print] Live charge preview failed: {exc}")

    # Tính tổng từ FolioTransaction (source of truth)
    discount_total = sum(abs(t.amount) for t in txs_all
                        if t.category == FolioTransactionCategory.DISCOUNT and not t.is_voided)

    # total_charge từ rebalance_folio (đã loại trừ REFUND), cộng thêm live preview nếu có
    charge_total = (folio.total_charge or Decimal("0")) + live_charge_total
    total_net = charge_total - discount_total
    total_paid = folio.total_paid or Decimal("0")
    remaining_balance = total_net - total_paid

    # Tìm thông tin khách hàng Master
    primary_guest = db.query(HotelGuest).filter(HotelGuest.stay_id == stay.id, HotelGuest.is_primary == True).first()
    if not primary_guest:
        primary_guest = db.query(HotelGuest).filter(HotelGuest.stay_id == stay.id).first()
    guest_name = primary_guest.full_name if primary_guest else "Khách Vãng Lai"

    # Session lưu key "name" (xem app/api/users.py). Fallback các key khác để tránh hiển thị "Hệ thống".
    current_user_name = (
        user.get("name")
        or user.get("full_name")
        or user.get("employee_id")
        or user.get("code")
        or "Hệ thống"
    )

    return templates.TemplateResponse(
        "pms/folio_print.html",
        {
            "request": request,
            "folio": folio,
            "stay": stay,
            "txs": charge_txs,           # Chỉ charges + discounts (không có REFUND)
            "payment_txs": payment_txs,   # PAYMENT, DEPOSIT_USED
            "refund_txs": refund_txs,     # REFUND, REFUND_PAYMENT
            "discount_total": discount_total,
            "total_charge": charge_total,
            "total_net": total_net,
            "total_paid": total_paid,
            "remaining_balance": remaining_balance,
            "guest_name": guest_name,
            "current_time": _now_vn().strftime("%d/%m/%Y %H:%M"),
            "current_user_name": current_user_name,
            "is_live_preview": is_live_preview,
        }
    )

@router.post("/stay/{stay_id}/create")
def create_new_folio(
    request: Request,
    stay_id: int,
    notes: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Mở một Folio phụ cho stay"""
    _require_login(request)
    stay = db.query(HotelStay).filter(HotelStay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay không tìm thấy")
        
    new_folio = create_folio(db=db, stay=stay, notes=notes)
    db.commit()
    
    return JSONResponse({
        "message": "Đã mở Folio mới",
        "folio": _folio_to_dict(new_folio)
    })

@router.post("/{folio_id}/transfer")
def transfer_transactions(
    request: Request,
    folio_id: int,
    target_folio_id: int = Query(...),
    tx_ids: str = Query(...), # comma separated
    db: Session = Depends(get_db),
):
    """Chuyển giao dịch sang Folio khác"""
    _require_login(request)

    ids = [int(i.strip()) for i in tx_ids.split(",") if i.strip().isdigit()]
    if not ids:
        raise HTTPException(status_code=400, detail="Không có giao dịch nào được chọn")

    with db.begin():
        source_folio = _get_folio_or_404(db, folio_id, for_update=True)
        target_folio = _get_folio_or_404(db, target_folio_id, for_update=True)

        try:
            transfer_transactions_between_folios(
                db=db,
                source_folio=source_folio,
                target_folio=target_folio,
                tx_ids=ids,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse({"status": "success", "message": "Chuyển giao dịch thành công"})

@router.post("/{target_folio_id}/merge")
def merge_folios(
    request: Request,
    target_folio_id: int,
    source_folio_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Gộp toàn bộ giao dịch và thanh toán từ source sang target, sau đó xoá source. Không thể xoá folio default."""
    _require_login(request)

    with db.begin():
        target_folio = _get_folio_or_404(db, target_folio_id, for_update=True)
        source_folio = _get_folio_or_404(db, source_folio_id, for_update=True)

        try:
            merge_folios_service(db=db, target_folio=target_folio, source_folio=source_folio)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse({"status": "success", "message": "Gộp Hóa đơn thành công"})



def _folio_to_dict(folio: Folio, include_transactions: bool = False) -> dict:
    data = {
        "id": folio.id,
        "stay_id": folio.stay_id,
        "branch_id": folio.branch_id,
        "folio_code": folio.folio_code,
        "status": folio.status.value if folio.status else FolioStatus.OPEN.value,
        "total_charge": float(folio.total_charge or 0),
        "total_discount": float(folio.total_discount or 0),
        "net_charge": float((folio.total_charge or 0) - (folio.total_discount or 0)),
        "total_paid": float(folio.total_paid or 0),
        "balance": float(folio.balance or 0),
        "currency": folio.currency,
        "notes": folio.notes,
        "opened_at": folio.opened_at.isoformat() if folio.opened_at else None,
        "closed_at": folio.closed_at.isoformat() if folio.closed_at else None,
        "created_by": folio.created_by,
        # Debt
        "debt_amount": float(folio.debt_amount or 0),
        "debt_status": folio.debt_status or "none",
        "debt_note": folio.debt_note,
        # Refund
        "refund_amount": float(folio.refund_amount or 0),
        "refund_status": folio.refund_status or "none",
        "refund_note": folio.refund_note,
    }
    # Lấy refund_record_id mới nhất
    if hasattr(folio, 'refund_records') and folio.refund_records:
        latest_rr = max(folio.refund_records, key=lambda r: r.id)
        data["refund_record_id"] = latest_rr.id
    if hasattr(folio, 'debt_records') and folio.debt_records:
        latest_dr = max(folio.debt_records, key=lambda r: r.id)
        data["debt_record_id"] = latest_dr.id
    if include_transactions:
        data["transactions"] = [_tx_to_dict(t) for t in folio.transactions]
        data["payments"] = [_payment_to_dict(p) for p in folio.payments]
    return data


def _user_display_name(user, user_id=None) -> str:
    if user:
        for attr in ("name", "employee_code", "employee_id", "email"):
            val = getattr(user, attr, None)
            if val:
                return str(val)
    return f"User #{user_id}" if user_id else "Hệ thống"


def _tx_to_dict(tx: FolioTransaction) -> dict:
    creator_name = _user_display_name(getattr(tx, "creator", None), tx.created_by)
    voider_name = _user_display_name(getattr(tx, "voider", None), tx.void_by)
    
    return {
        "id": tx.id,
        "folio_id": tx.folio_id,
        "transaction_type": tx.transaction_type.value if tx.transaction_type else None,
        "category": tx.category.value if tx.category else None,
        "description": tx.description,
        "amount": float(tx.amount or 0),
        "quantity": float(tx.quantity or 1),
        "unit_price": float(tx.unit_price) if tx.unit_price else None,
        "currency": tx.currency,
        "reference_id": tx.reference_id,
        "reference_type": tx.reference_type,
        "is_voided": tx.is_voided,
        "void_reason": tx.void_reason,
        "void_by": tx.void_by,
        "void_by_name": voider_name,
        "void_at": tx.void_at.isoformat() if tx.void_at else None,
        "created_at": tx.created_at.isoformat() if tx.created_at else None,
        "created_by": tx.created_by,
        "created_by_name": creator_name,
    }


def _payment_to_dict(p: Payment) -> dict:
    creator_name = _user_display_name(getattr(p, "creator", None), p.created_by)
        
    return {
        "id": p.id,
        "folio_id": p.folio_id,
        "amount": float(p.amount or 0),
        "method": p.method.value if p.method else None,
        "status": p.status.value if p.status else None,
        "transaction_code": p.transaction_code,
        "meta": p.meta,
        "is_refunded": p.is_refunded,
        "refunded_amount": float(p.refunded_amount or 0),
        "refund_reason": p.refund_reason,
        "paid_at": p.paid_at.isoformat() if p.paid_at else None,
        "created_by": p.created_by,
        "created_by_name": creator_name,
        "allocated_amount": p.allocated_amount,
        "unallocated_amount": p.unallocated_amount,
    }


# ─────────────────────────── Charges ──────────────────────────────

@router.post("/{folio_id}/charge")
def add_charge(
    request: Request,
    folio_id: int,
    transaction_type: str = Query(...),
    description: str = Query(""),
    amount: str = Query(...),
    quantity: Optional[str] = Query(default="1"),
    unit_price: Optional[str] = Query(default=None),
    reference_id: Optional[int] = Query(default=None),
    reference_type: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Thêm một dòng charge vào folio (Decimal-safe)."""
    user = _require_login(request)
    actor_id = _session_user_id(db, user)

    charge_amount = _parse_money_query(amount, "amount")
    charge_qty = _parse_quantity_query(quantity)
    parsed_unit_price = None
    if unit_price is not None and str(unit_price).strip() != "":
        parsed_unit_price = _parse_money_query(unit_price, "unit_price")

    try:
        tx_type = FolioTransactionType(transaction_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"transaction_type không hợp lệ: {transaction_type}",
        )

    with db.begin():
        folio = _get_folio_or_404(db, folio_id, for_update=True)
        if folio.status == FolioStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Folio đã đóng, không thể thêm charge")

        tx = create_charge_transaction(
            db=db,
            folio=folio,
            tx_type=tx_type,
            description=description,
            amount=charge_amount,
            created_by=actor_id,
            quantity=charge_qty,
            unit_price=parsed_unit_price,
            reference_id=reference_id,
            reference_type=reference_type,
        )
        db.flush()

    return JSONResponse({
        "transaction": _tx_to_dict(tx),
        "folio": _folio_to_dict(folio),
    })


@router.post("/{folio_id}/charges-batch")
def add_charges_batch(
    request: Request,
    folio_id: int,
    payload: List[dict] = Body(...),
    db: Session = Depends(get_db),
):
    """Batch: thêm nhiều charge cùng lúc trong 1 transaction (1 round-trip thay vì N)."""
    user = _require_login(request)
    actor_id = _session_user_id(db, user)

    if not payload or not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="Payload phải là danh sách charges")

    with db.begin():
        folio = _get_folio_or_404(db, folio_id, for_update=True)
        if folio.status == FolioStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Folio đã đóng, không thể thêm charge")

        transactions = []
        for item in payload:
            charge_amount = _parse_money_query(str(item.get("amount", "0")), "amount")
            charge_qty = _parse_quantity_query(str(item.get("quantity", "1")))
            parsed_unit_price = None
            raw_up = item.get("unit_price")
            if raw_up is not None and str(raw_up).strip() != "":
                parsed_unit_price = _parse_money_query(str(raw_up), "unit_price")

            try:
                tx_type = FolioTransactionType(item.get("transaction_type", "SERVICE_CHARGE"))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"transaction_type không hợp lệ: {item.get('transaction_type')}")

            tx = create_charge_transaction(
                db=db,
                folio=folio,
                tx_type=tx_type,
                description=item.get("description", ""),
                amount=charge_amount,
                created_by=actor_id,
                quantity=charge_qty,
                unit_price=parsed_unit_price,
                reference_id=item.get("reference_id"),
                reference_type=item.get("reference_type"),
                skip_rebalance=True,
            )
            transactions.append(tx)
        rebalance_folio(db, folio)
        db.flush()

    return JSONResponse({
        "transactions": [_tx_to_dict(tx) for tx in transactions],
        "folio": _folio_to_dict(folio),
        "count": len(transactions),
    })


@router.post("/{folio_id}/discount")
def add_discount(
    request: Request,
    folio_id: int,
    transaction_type: str = Query(default="DISCOUNT_MANUAL"),
    description: str = Query(""),
    amount: str = Query(...),
    db: Session = Depends(get_db),
):
    """Thêm một dòng discount (amount âm) vào folio (Decimal-safe)."""
    user = _require_login(request)
    actor_id = _session_user_id(db, user)
    discount_amount = _parse_money_query(amount, "amount")

    try:
        tx_type = FolioTransactionType(transaction_type)
    except ValueError:
        tx_type = FolioTransactionType.DISCOUNT_MANUAL

    with db.begin():
        folio = _get_folio_or_404(db, folio_id, for_update=True)
        if folio.status == FolioStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Folio đã đóng, không thể thêm discount")

        tx = create_discount_transaction(
            db=db,
            folio=folio,
            tx_type=tx_type,
            description=description,
            amount=discount_amount,
            created_by=actor_id,
        )
        db.flush()

    db.refresh(tx)
    db.refresh(folio)
    return JSONResponse({
        "transaction": _tx_to_dict(tx),
        "folio": _folio_to_dict(folio),
    })


# ─────────────────────────── Void Transaction ──────────────────────

@router.post("/{folio_id}/void/{tx_id}")
def void_transaction(
    request: Request,
    folio_id: int,
    tx_id: int,
    reason: str = Query(""),
    db: Session = Depends(get_db),
):
    """Void một dòng transaction — không xóa, chỉ đánh dấu is_voided=True."""
    user = _require_login(request)
    actor_id = _session_user_id(db, user)

    with db.begin():
        folio = _get_folio_or_404(db, folio_id, for_update=True)
        if folio.status == FolioStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Folio đã đóng, không thể void")

        tx = db.query(FolioTransaction).filter(
            FolioTransaction.id == tx_id,
            FolioTransaction.folio_id == folio_id,
        ).with_for_update().first()
        if not tx:
            raise HTTPException(status_code=404, detail="Transaction không tìm thấy")
        if tx.is_voided:
            raise HTTPException(status_code=400, detail="Transaction đã bị void trước đó")

        # ── Inventory Reversal: Hoàn kho nếu transaction liên kết kho ──
        inventory_reversed = False
        if tx.reference_type == "inventory" and tx.reference_id:
            try:
                from ...db.models import StockMovement, InventoryLevel, TransactionTypeWMS
                from ...core.utils import VN_TZ
                from datetime import datetime

                original_movement = db.query(StockMovement).filter(
                    StockMovement.id == tx.reference_id,
                    StockMovement.transaction_type == TransactionTypeWMS.EXPORT_SERVICE,
                ).first()

                if original_movement:
                    qty_to_return = abs(original_movement.quantity_change)
                    inv_level = db.query(InventoryLevel).filter(
                        InventoryLevel.warehouse_id == original_movement.warehouse_id,
                        InventoryLevel.product_id == original_movement.product_id,
                    ).with_for_update().first()

                    if inv_level:
                        new_balance = inv_level.quantity + qty_to_return
                        inv_level.quantity = new_balance

                        reversal = StockMovement(
                            warehouse_id=original_movement.warehouse_id,
                            product_id=original_movement.product_id,
                            transaction_type=TransactionTypeWMS.VOID_SERVICE,
                            quantity_change=qty_to_return,
                            balance_after=new_balance,
                            ref_ticket_type="void_service",
                            ref_ticket_id=folio.id,
                            created_at=datetime.now(VN_TZ),
                            actor_id=actor_id,
                        )
                        db.add(reversal)
                        inventory_reversed = True
                        logger.info(f"[Void] Hoàn kho: product#{original_movement.product_id} +{qty_to_return}")
            except Exception as e:
                logger.error(f"[Void] Lỗi hoàn kho: {e}")

        mark_transaction_void(db, tx, reason, actor_id)
        db.flush()

    # Kiểm tra xem có ShiftReport cascade không
    cascade_shift = False
    if tx.shift_transaction_id:
        cascade_shift = True

    db.refresh(tx)
    db.refresh(folio)
    return JSONResponse({
        "transaction": _tx_to_dict(tx),
        "folio": _folio_to_dict(folio),
        "cascade_shift_voided": cascade_shift,
        "inventory_reversed": inventory_reversed,
    })


# ─────────────────────────── Partial Refund ───────────────────────────

@router.post("/{folio_id}/partial-refund/{tx_id}")
def partial_refund_transaction(
    request: Request,
    folio_id: int,
    tx_id: int,
    refund_qty: int = Query(..., ge=1),
    reason: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Hoàn trả 1 phần dịch vụ: giảm quantity + tạo REFUND transaction (audit trail)."""
    user = _require_login(request)
    actor_id = _session_user_id(db, user)

    with db.begin():
        folio = _get_folio_or_404(db, folio_id, for_update=True)
        if folio.status == FolioStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Folio đã đóng")

        tx = db.query(FolioTransaction).filter(
            FolioTransaction.id == tx_id,
            FolioTransaction.folio_id == folio_id,
        ).with_for_update().first()
        if not tx:
            raise HTTPException(status_code=404, detail="Transaction không tìm thấy")
        if tx.is_voided:
            raise HTTPException(status_code=400, detail="Transaction đã bị void")
        if tx.amount <= 0:
            raise HTTPException(status_code=400, detail="Chỉ hoàn trả được charge (amount > 0)")

        current_qty = int(tx.quantity or 1)
        if refund_qty > current_qty:
            raise HTTPException(status_code=400, detail=f"Số lượng hoàn trả ({refund_qty}) vượt quá số lượng hiện tại ({current_qty})")

        # Tính refund amount
        if tx.unit_price and tx.unit_price > 0:
            unit_price = tx.unit_price
        else:
            unit_price = tx.amount / Decimal(str(current_qty))
        refund_amount = unit_price * Decimal(str(refund_qty))

        # Nếu hoàn trả toàn bộ → void luôn
        if refund_qty >= current_qty:
            from ...services.folio_service import mark_transaction_void
            # Inventory reversal (copy logic từ void_transaction)
            inventory_reversed = False
            if tx.reference_type == "inventory" and tx.reference_id:
                try:
                    from ...db.models import StockMovement, InventoryLevel, TransactionTypeWMS
                    from datetime import datetime
                    original_movement = db.query(StockMovement).filter(
                        StockMovement.id == tx.reference_id,
                        StockMovement.transaction_type == TransactionTypeWMS.EXPORT_SERVICE,
                    ).first()
                    if original_movement:
                        qty_to_return = abs(original_movement.quantity_change)
                        inv_level = db.query(InventoryLevel).filter(
                            InventoryLevel.warehouse_id == original_movement.warehouse_id,
                            InventoryLevel.product_id == original_movement.product_id,
                        ).with_for_update().first()
                        if inv_level:
                            new_balance = inv_level.quantity + qty_to_return
                            inv_level.quantity = new_balance
                            reversal = StockMovement(
                                warehouse_id=original_movement.warehouse_id,
                                product_id=original_movement.product_id,
                                transaction_type=TransactionTypeWMS.VOID_SERVICE,
                                quantity_change=qty_to_return,
                                balance_after=new_balance,
                                ref_ticket_type="partial_refund",
                                ref_ticket_id=folio.id,
                                created_at=datetime.now(VN_TZ),
                                actor_id=actor_id,
                            )
                            db.add(reversal)
                            inventory_reversed = True
                except Exception as e:
                    logger.error(f"[PartialRefund] Lỗi hoàn kho full: {e}")
            mark_transaction_void(db, tx, reason or "Hoàn trả toàn bộ", actor_id)
            rebalance_folio(db, folio)
            db.flush()
            db.refresh(tx)
            db.refresh(folio)
            return JSONResponse({
                "transaction": _tx_to_dict(tx),
                "refund_transaction": None,
                "folio": _folio_to_dict(folio),
                "voided": True,
                "inventory_reversed": inventory_reversed,
            })

        # Partial refund: giảm quantity + amount trên tx gốc
        tx.quantity = Decimal(str(current_qty - refund_qty))
        tx.amount = tx.amount - refund_amount

        # Tạo refund transaction (audit trail)
        base_desc = (tx.description or 'dịch vụ').strip()
        base_desc = re.sub(r"\s*x\s*\d+$", "", base_desc, flags=re.IGNORECASE).strip()
        refund_desc = f"Hoàn trả {refund_qty}x {base_desc}"
        if reason:
            refund_desc += f" ({reason})"
        refund_tx = FolioTransaction(
            folio_id=folio.id,
            stay_id=folio.stay_id,
            branch_id=folio.branch_id,
            transaction_type=FolioTransactionType.REFUND,
            category=FolioTransactionCategory.DISCOUNT,
            description=refund_desc,
            amount=-refund_amount,
            quantity=Decimal(str(refund_qty)),
            unit_price=unit_price,
            reference_id=tx.id,
            reference_type="partial_refund",
            created_by=actor_id,
        )
        db.add(refund_tx)

        # Hoàn kho partial nếu inventory-linked
        inventory_reversed = False
        if tx.reference_type == "inventory" and tx.reference_id:
            try:
                from ...db.models import StockMovement, InventoryLevel, TransactionTypeWMS
                from datetime import datetime
                original_movement = db.query(StockMovement).filter(
                    StockMovement.id == tx.reference_id,
                    StockMovement.transaction_type == TransactionTypeWMS.EXPORT_SERVICE,
                ).first()
                if original_movement:
                    inv_level = db.query(InventoryLevel).filter(
                        InventoryLevel.warehouse_id == original_movement.warehouse_id,
                        InventoryLevel.product_id == original_movement.product_id,
                    ).with_for_update().first()
                    if inv_level:
                        new_balance = inv_level.quantity + Decimal(str(refund_qty))
                        inv_level.quantity = new_balance
                        reversal = StockMovement(
                            warehouse_id=original_movement.warehouse_id,
                            product_id=original_movement.product_id,
                            transaction_type=TransactionTypeWMS.VOID_SERVICE,
                            quantity_change=Decimal(str(refund_qty)),
                            balance_after=new_balance,
                            ref_ticket_type="partial_refund",
                            ref_ticket_id=folio.id,
                            created_at=datetime.now(VN_TZ),
                            actor_id=actor_id,
                        )
                        db.add(reversal)
                        inventory_reversed = True
            except Exception as e:
                logger.error(f"[PartialRefund] Lỗi hoàn kho partial: {e}")

        rebalance_folio(db, folio)
        db.flush()

    db.refresh(tx)
    db.refresh(refund_tx)
    db.refresh(folio)
    return JSONResponse({
        "transaction": _tx_to_dict(tx),
        "refund_transaction": _tx_to_dict(refund_tx),
        "folio": _folio_to_dict(folio),
        "voided": False,
        "inventory_reversed": inventory_reversed,
        "refund_qty": refund_qty,
        "refund_amount": float(refund_amount),
    })


# ─────────────────────────── Payments ───────────────────────────────

@router.post("/{folio_id}/payment")
def add_payment(
    request: Request,
    folio_id: int,
    amount: str = Query(...),
    method: str = Query(default="CASH"),
    transaction_code: str = Query(default=""),
    meta: str = Query(default="{}"),
    db: Session = Depends(get_db),
):
    """Tạo payment + folio transaction PAYMENT (Decimal-safe) + đồng bộ ShiftReport."""
    import json
    from ...db.models import ShiftReportTransaction, ShiftReportStatus, Branch
    from ...services.shift_report_service import (
        _generate_shift_code,
        build_shift_transaction_info,
        normalize_shift_payment_method,
        shift_transaction_type_for_method,
    )
    from ...core.utils import VN_TZ

    user = _require_login(request)
    payment_amount = _parse_money_query(amount, "amount")

    try:
        meta_payload = json.loads(meta) if meta and meta != "{}" else None
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="meta không phải JSON hợp lệ") from exc

    try:
        pay_method = PaymentMethod(method)
    except ValueError:
        pay_method = PaymentMethod.CASH

    with db.begin():
        folio = _get_folio_or_404(db, folio_id, for_update=True)
        stay_with_room = db.query(HotelStay).options(
            joinedload(HotelStay.room),
            joinedload(HotelStay.guests)
        ).filter(HotelStay.id == folio.stay_id).first()
        room_number = stay_with_room.room.room_number if stay_with_room and stay_with_room.room else folio.folio_code
        guest_name = stay_with_room.guests[0].full_name if (stay_with_room and stay_with_room.guests) else "N/A"

        shift_tx = None

        # Nếu folio đang đóng → chỉ cho phép thu nợ (balance > 0)
        if folio.status == FolioStatus.CLOSED:
            rebalance_folio(db, folio)
            if folio.balance > Decimal("0"):
                # Còn nợ → mở lại ở trạng thái DEBT để thu nợ
                folio.status = FolioStatus.DEBT
                folio.closed_at = None
                db.flush()
            else:
                # Balance <= 0 → đã tất toán hoặc khách dư → không cho thanh toán thêm
                raise HTTPException(status_code=400, detail="Folio đã đóng, không thể thanh toán")

        # Xác định là thanh toán thường hay thu nợ (đã chuyển sang status DEBT)
        is_debt = folio.status == FolioStatus.DEBT or folio.debt_status != 'none'
        prefix = "Thu công nợ" if is_debt else "Thanh toán"
        
        # Tạo Payment + FolioTransaction
        payment, tx = create_payment_with_transaction(
            db=db,
            folio=folio,
            amount=payment_amount,
            method=pay_method,
            created_by=user.get("id"),
            transaction_code=transaction_code or None,
            meta=meta_payload,
            tx_type=FolioTransactionType.PAYMENT,
            description_prefix=prefix,
        )
        db.flush()

        # ── Đồng bộ sang ShiftReport ──
        try:
            chi_nhanh_code = None
            active_branch = request.session.get("active_branch")
            if active_branch:
                chi_nhanh_code = active_branch
            elif user.get("branch"):
                chi_nhanh_code = user.get("branch")

            if chi_nhanh_code:
                branch = db.query(Branch).filter(Branch.branch_code == chi_nhanh_code).first()
                if branch:
                    method_key = pay_method.value if hasattr(pay_method, "value") else str(pay_method)
                    shift_pay_method = normalize_shift_payment_method(method_key)
                    shift_tx_type = shift_transaction_type_for_method(shift_pay_method)
                    transaction_code_val = _generate_shift_code(db, branch.branch_code or "XX")
                    source = "Thu công nợ" if is_debt else "Thanh toán"
                    user_note = meta_payload.get("note") if meta_payload else None
                    transaction_info = build_shift_transaction_info(
                        source,
                        room_number=room_number,
                        folio_code=folio.folio_code,
                        guest_name=guest_name,
                        amount=payment_amount,
                        method=shift_pay_method,
                        reason=user_note,
                    )

                    shift_tx = ShiftReportTransaction(
                        transaction_code=transaction_code_val,
                        transaction_type=shift_tx_type,
                        amount=int(payment_amount),
                        room_number=room_number,
                        transaction_info=transaction_info,
                        branch_id=branch.id,
                        recorder_id=user.get("id"),
                        created_datetime=datetime.now(VN_TZ),
                        status=ShiftReportStatus.PENDING,
                        stay_id=folio.stay_id,
                        folio_id=folio.id,
                        folio_transaction_id=tx.id,
                        payment_method=shift_pay_method,
                        is_auto_posted=True,
                    )
                    db.add(shift_tx)
                    db.flush()
                    tx.shift_transaction_id = shift_tx.id
                    logger.info(f"[SHIFT_SYNC] SUCCESS: created shift_tx id={shift_tx.id}, code={shift_tx.transaction_code}, folio_id={folio.id}, amount={payment_amount}")

                    # ── Cập nhật bản ghi DEBT cũ ──
                    from ...services.shift_report_service import update_debt_shift_record
                    rebalance_folio(db, folio)
                    update_debt_shift_record(
                        db=db,
                        folio_id=folio.id,
                        new_balance=Decimal(str(folio.balance or 0)),
                        room_number=room_number,
                    )
        except Exception as e:
            logger.error(f"[SHIFT_SYNC] FAILED to create shift transaction: {e}", exc_info=True)
            shift_tx = None

        if is_debt:
            try:
                rebalance_folio(db, folio)
                sync_guest_crm_after_debt_payment(db, folio, payment=payment, tx=tx)
            except Exception as e:
                logger.error(f"[CRM_DEBT_SYNC] FAILED for folio_id={folio.id}: {e}", exc_info=True)

    db.refresh(payment)
    db.refresh(tx)
    db.refresh(folio)
    if shift_tx:
        db.refresh(shift_tx)

    return JSONResponse({
        "payment": _payment_to_dict(payment),
        "transaction": _tx_to_dict(tx),
        "folio": _folio_to_dict(folio),
        "shift_transaction": {
            "id": shift_tx.id if shift_tx else None,
            "transaction_code": shift_tx.transaction_code if shift_tx else None,
        } if shift_tx else None,
    })


# ─────────────────────────── Payment + Shift Sync ──────────────────────
class PMSPaymentWithShiftPayload(BaseModel):
    amount: str  # Decimal string
    method: str = "CASH"
    transaction_code: str = ""
    meta: str = "{}"
    note: str = ""
    room_number: Optional[str] = ""
    chi_nhanh: Optional[str] = None


@router.post("/{folio_id}/payment-with-shift")
def add_payment_with_shift_report(
    request: Request,
    folio_id: int,
    payload: PMSPaymentWithShiftPayload,
    db: Session = Depends(get_db),
):
    """
    Tạo thanh toán trên Folio + tự động đồng bộ sang ShiftReport.
    atomic trong 1 transaction — đảm bảo cả 2 đều được tạo hoặc không cái nào.
    """
    import json
    from ...db.models import ShiftReportTransaction, ShiftReportStatus, Branch
    from ...core.utils import VN_TZ
    from ...services.shift_report_service import (
        _generate_shift_code,
        build_shift_transaction_info,
        normalize_shift_payment_method,
        shift_transaction_type_for_method,
        update_debt_shift_record,
    )

    user = _require_login(request)
    payment_amount = _parse_money_query(payload.amount, "amount")

    try:
        meta_payload = json.loads(payload.meta) if payload.meta and payload.meta != "{}" else None
    except json.JSONDecodeError:
        meta_payload = None

    try:
        pay_method = PaymentMethod(payload.method)
    except ValueError:
        pay_method = PaymentMethod.CASH

    with db.begin():
        folio = _get_folio_or_404(db, folio_id, for_update=True)
        stay_with_room = db.query(HotelStay).options(
            joinedload(HotelStay.room),
            joinedload(HotelStay.guests)
        ).filter(HotelStay.id == folio.stay_id).first()
        room_number = payload.room_number or (stay_with_room.room.room_number if stay_with_room and stay_with_room.room else folio.folio_code)
        guest_name = stay_with_room.guests[0].full_name if (stay_with_room and stay_with_room.guests) else "N/A"

        shift_tx = None

        # Nếu folio đang đóng → chỉ cho phép thu nợ (balance > 0)
        if folio.status == FolioStatus.CLOSED:
            rebalance_folio(db, folio)
            if folio.balance > Decimal("0"):
                # Còn nợ → mở lại ở trạng thái DEBT để thu nợ
                folio.status = FolioStatus.DEBT
                folio.closed_at = None
                db.flush()
            else:
                # Balance <= 0 → đã tất toán hoặc khách dư → không cho thanh toán thêm
                raise HTTPException(status_code=400, detail="Folio đã đóng, không thể thanh toán")

        # Xác định là thanh toán thường hay thu nợ
        is_debt = folio.status == FolioStatus.DEBT or folio.debt_status != 'none'
        prefix = "Thu công nợ" if is_debt else "Thanh toán"

        # 1. Tạo Payment + FolioTransaction
        payment, tx = create_payment_with_transaction(
            db=db,
            folio=folio,
            amount=payment_amount,
            method=pay_method,
            created_by=user.get("id"),
            transaction_code=payload.transaction_code or None,
            meta=meta_payload,
            tx_type=FolioTransactionType.PAYMENT,
            description_prefix=prefix,
        )
        db.flush()

        # 2. Đồng bộ sang ShiftReport (cùng transaction)
        try:
            chi_nhanh_code = payload.chi_nhanh
            if not chi_nhanh_code:
                active_branch = request.session.get("active_branch")
                chi_nhanh_code = active_branch or user.get("branch")

            if chi_nhanh_code:
                branch = db.query(Branch).filter(Branch.branch_code == chi_nhanh_code).first()
                if branch:
                    method_key = pay_method.value if hasattr(pay_method, "value") else str(pay_method)
                    shift_pay_method = normalize_shift_payment_method(method_key)
                    shift_tx_type = shift_transaction_type_for_method(shift_pay_method)

                    transaction_code = _generate_shift_code(db, branch.branch_code)
                    source = "Thu công nợ" if is_debt else "Thanh toán"
                    transaction_info = build_shift_transaction_info(
                        source,
                        room_number=room_number,
                        folio_code=folio.folio_code,
                        guest_name=guest_name,
                        amount=payment_amount,
                        method=shift_pay_method,
                        reason=payload.note,
                    )

                    shift_tx = ShiftReportTransaction(
                        transaction_code=transaction_code,
                        transaction_type=shift_tx_type,
                        amount=int(payment_amount),
                        room_number=room_number,
                        transaction_info=transaction_info,
                        branch_id=branch.id,
                        recorder_id=user.get("id"),
                        created_datetime=datetime.now(VN_TZ),
                        status=ShiftReportStatus.PENDING,
                        stay_id=folio.stay_id,
                        folio_id=folio.id,
                        folio_transaction_id=tx.id,
                        payment_method=shift_pay_method,
                        is_auto_posted=True,
                    )
                    db.add(shift_tx)
                    db.flush()

                    tx.shift_transaction_id = shift_tx.id
                    logger.info(f"[SHIFT_SYNC] SUCCESS: created shift_tx id={shift_tx.id}, code={shift_tx.transaction_code}, folio_id={folio.id}, amount={payment_amount}")

                    # ── Cập nhật bản ghi DEBT cũ ──
                    from ...services.shift_report_service import update_debt_shift_record
                    rebalance_folio(db, folio)
                    update_debt_shift_record(
                        db=db,
                        folio_id=folio.id,
                        new_balance=Decimal(str(folio.balance or 0)),
                        room_number=room_number,
                    )
        except Exception as e:
            logger.error(f"[SHIFT_SYNC] FAILED to create shift transaction: {e}", exc_info=True)
            shift_tx = None

        if is_debt:
            try:
                rebalance_folio(db, folio)
                sync_guest_crm_after_debt_payment(db, folio, payment=payment, tx=tx)
            except Exception as e:
                logger.error(f"[CRM_DEBT_SYNC] FAILED for folio_id={folio.id}: {e}", exc_info=True)

    db.refresh(payment)
    db.refresh(tx)
    db.refresh(folio)
    if shift_tx:
        db.refresh(shift_tx)

    return JSONResponse({
        "payment": _payment_to_dict(payment),
        "transaction": _tx_to_dict(tx),
        "folio": _folio_to_dict(folio),
        "shift_transaction": {
            "id": shift_tx.id if shift_tx else None,
            "transaction_code": shift_tx.transaction_code if shift_tx else None,
            "status": "synced" if shift_tx else "failed",
        },
    })


@router.post("/{folio_id}/deposit")
def record_deposit(
    request: Request,
    folio_id: int,
    amount: str = Query(...),
    deposit_type: str = Query(default="CASH"),
    transaction_code: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Ghi nhận cọc tại check-in (Decimal-safe)."""
    user = _require_login(request)
    deposit_amount = _parse_money_query(amount, "amount")

    try:
        pay_method = PaymentMethod(deposit_type)
    except ValueError:
        pay_method = PaymentMethod.CASH

    with db.begin():
        folio = _get_folio_or_404(db, folio_id, for_update=True)
        if folio.status == FolioStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Folio đã đóng, không thể ghi nhận cọc")

        payment, tx = create_payment_with_transaction(
            db=db,
            folio=folio,
            amount=deposit_amount,
            method=pay_method,
            created_by=user.get("id"),
            transaction_code=transaction_code or None,
            meta={"source": "checkin_deposit"},
            tx_type=FolioTransactionType.DEPOSIT_USED,
            description_prefix="Cọc",
        )
        db.flush()

    db.refresh(payment)
    db.refresh(tx)
    db.refresh(folio)
    return JSONResponse({
        "payment": _payment_to_dict(payment),
        "transaction": _tx_to_dict(tx),
        "folio": _folio_to_dict(folio),
    })


@router.post("/{folio_id}/refund/{payment_id}")
def refund_payment(
    request: Request,
    folio_id: int,
    payment_id: int,
    amount: str = Query(...),
    reason: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Hoàn tiền một payment đã thu (Decimal-safe)."""
    from ...db.models import ShiftReportTransaction, ShiftReportStatus, Branch
    from ...services.shift_report_service import (
        _generate_shift_code,
        build_shift_transaction_info,
        normalize_shift_payment_method,
        shift_transaction_type_for_method,
    )
    from ...core.utils import VN_TZ

    user = _require_login(request)
    requested_amount = _parse_money_query(amount, "amount")

    with db.begin():
        folio = _get_folio_or_404(db, folio_id, for_update=True)
        payment = db.query(Payment).filter(
            Payment.id == payment_id,
            Payment.folio_id == folio_id,
        ).with_for_update().first()
        if not payment:
            raise HTTPException(status_code=404, detail="Payment không tìm thấy")
        if payment.is_refunded:
            raise HTTPException(status_code=400, detail="Payment đã được hoàn trước đó")

        try:
            tx, _ = refund_payment_and_create_transaction(
                db=db,
                folio=folio,
                payment=payment,
                requested_amount=requested_amount,
                reason=reason,
                user_id=user.get("id"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.flush()

        # ── Đồng bộ hoàn tiền sang ShiftReport với loại CASH_EXPENSE ──
        shift_tx = None
        try:
            chi_nhanh_code = None
            active_branch = request.session.get("active_branch")
            if active_branch:
                chi_nhanh_code = active_branch
            elif user.get("branch"):
                chi_nhanh_code = user.get("branch")

            if chi_nhanh_code:
                branch = db.query(Branch).filter(Branch.branch_code == chi_nhanh_code).first()
                if branch:
                    stay_with_room = db.query(HotelStay).options(
                        joinedload(HotelStay.room),
                        joinedload(HotelStay.guests)
                    ).filter(HotelStay.id == folio.stay_id).first()
                    room_number = stay_with_room.room.room_number if stay_with_room and stay_with_room.room else folio.folio_code
                    guest_name = stay_with_room.guests[0].full_name if (stay_with_room and stay_with_room.guests) else "N/A"

                    original_method = payment.method.value if getattr(payment, "method", None) else "CASH"
                    shift_pay_method = normalize_shift_payment_method(original_method)
                    transaction_code = _generate_shift_code(db, branch.branch_code or "XX")
                    transaction_info = build_shift_transaction_info(
                        "Hoàn tiền",
                        room_number=room_number,
                        folio_code=folio.folio_code,
                        guest_name=guest_name,
                        amount=requested_amount,
                        method=shift_pay_method,
                        reason=reason,
                    )

                    shift_tx = ShiftReportTransaction(
                        transaction_code=transaction_code,
                        transaction_type=shift_transaction_type_for_method(shift_pay_method, is_refund=True),
                        amount=int(requested_amount),
                        room_number=room_number,
                        transaction_info=transaction_info,
                        branch_id=branch.id,
                        recorder_id=user.get("id"),
                        created_datetime=datetime.now(VN_TZ),
                        status=ShiftReportStatus.PENDING,
                        stay_id=folio.stay_id,
                        folio_id=folio.id,
                        folio_transaction_id=tx.id,
                        payment_method=shift_pay_method,
                        is_auto_posted=True,
                    )
                    db.add(shift_tx)
                    db.flush()
                    tx.shift_transaction_id = shift_tx.id
                    logger.info(f"[SHIFT_SYNC] REFUND: created shift_tx id={shift_tx.id}, code={shift_tx.transaction_code}, folio_id={folio.id}, amount={requested_amount}")
        except Exception as e:
            logger.error(f"[SHIFT_SYNC] REFUND FAILED: {e}", exc_info=True)
            shift_tx = None

    db.refresh(tx)
    db.refresh(payment)
    db.refresh(folio)

    return JSONResponse({
        "payment": _payment_to_dict(payment),
        "transaction": _tx_to_dict(tx),
        "folio": _folio_to_dict(folio),
        "shift_transaction": {
            "id": shift_tx.id if shift_tx else None,
            "transaction_code": shift_tx.transaction_code if shift_tx else None,
            "status": "synced" if shift_tx else "failed",
        } if shift_tx else None,
    })


# ─────────────────────────── Close Folio ──────────────────────────

@router.post("/{folio_id}/close")
def close_folio(
    request: Request,
    folio_id: int,
    db: Session = Depends(get_db),
):
    """
    Đóng folio. Balance phải = 0 (hoặc <= 0 sau khi trừ cọc).
    """
    _require_login(request)

    with db.begin():
        folio = _get_folio_or_404(db, folio_id, for_update=True)
        if folio.status == FolioStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Folio đã đóng trước đó")

        rebalance_folio(db, folio)
        try:
            close_folio_with_balance_check(folio)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        db.flush()

    db.refresh(folio)
    return JSONResponse({
        "folio": _folio_to_dict(folio),
        "message": "Folio đã đóng thành công"
    })


# ─────────────────────────── Full Folio ───────────────────────────

@router.get("/{folio_id}/full")
def get_folio_full(
    request: Request,
    folio_id: int,
    db: Session = Depends(get_db),
):
    """
    Lấy full folio: transactions + payments + allocations.
    """
    _require_login(request)

    folio = db.query(Folio).filter(Folio.id == folio_id).first()
    if not folio:
        raise HTTPException(status_code=404, detail="Folio không tìm thấy")

    # Eager load
    db.refresh(folio, ["transactions", "payments"])

    return JSONResponse({
        "folio": _folio_to_dict(folio, include_transactions=True),
    })


# ─────────────────────────── Balance Real-time ───────────────────────────

@router.get("/{folio_id}/balance")
def get_folio_balance(
    request: Request,
    folio_id: int,
    db: Session = Depends(get_db),
):
    """
    Lấy balance REAL-TIME từ DB (tính lại mỗi lần gọi).
    Backend là nguồn duy nhất cho số liệu tài chính.
    """
    _require_login(request)

    folio = db.query(Folio).filter(Folio.id == folio_id).first()
    if not folio:
        raise HTTPException(status_code=404, detail="Folio không tìm thấy")

    # Tính balance trực tiếp từ DB (real-time)
    result = rebalance_folio(db, folio)
    db.commit()

    return JSONResponse({
        "folio_id": folio_id,
        "folio_code": folio.folio_code,
        **result,
    })


# ─────────────────────────── Fix Cache ───────────────────────────

@router.post("/fix-cache")
def fix_folio_cache(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Recalculate cache cho tất cả folios (fix dữ liệu cũ).
    """
    _require_login(request)
    result = recalculate_all_folios_cache(db)
    db.commit()
    return JSONResponse({
        "message": f"Đã fix {result['fixed_count']} folios",
        "details": result,
    })
