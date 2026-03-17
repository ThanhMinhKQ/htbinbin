# app/api/pms/pms_checkout.py
"""
PMS Check-out API - Handle guest check-out
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload

from ...db.models import Branch, HotelRoom, HotelStay, HotelStayStatus
from ...db.session import get_db
from ...core.config import logger
from .pms_helpers import _require_login, _is_admin, _active_branch, _now_vn, _calc_price

router = APIRouter()


# ─────────────────────────── API: Check-out ───────────────────────────

@router.post("/api/pms/checkout/{stay_id}", tags=["PMS"])
async def api_checkout(
    request: Request,
    stay_id: int,
    final_price: Optional[float] = Query(default=None),
    discount: Optional[float] = Query(default=None),
    extra_charge: Optional[float] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Check-out: Cập nhật trạng thái stay, tính tiền cuối cùng
    """
    user = _require_login(request)
    branch_name = _active_branch(request)

    try:
        # Get stay
        stay = (
            db.query(HotelStay)
            .options(
                joinedload(HotelStay.room).joinedload(HotelRoom.room_type_obj)
            )
            .filter(HotelStay.id == stay_id, HotelStay.status == HotelStayStatus.ACTIVE)
            .first()
        )
        if not stay:
            raise HTTPException(status_code=404, detail="Không tìm thấy lưu trú hoặc đã trả phòng")

        # Calculate final price
        room = stay.room
        rt = room.room_type_obj if room else None
        now = _now_vn()

        # Calculation logic
        calc_discount = float(discount or 0)
        calc_extra = float(extra_charge or 0)

        # If no final_price provided, calculate based on actual stay time
        if final_price is None:
            if not rt:
                 raise HTTPException(status_code=400, detail="Thiếu thông tin loại phòng để tính tiền")
            final_price = _calc_price(stay.stay_type, rt, stay.check_in_at, now)
        
        # Ensure final_price is float for math
        try:
            final_price = float(final_price)
        except (TypeError, ValueError):
            final_price = 0.0

        # Apply discounts and extra charges
        final_total = final_price - calc_discount + calc_extra
        if final_total < 0:
            final_total = 0

        # Update stay
        stay.check_out_at = now
        stay.status = HotelStayStatus.CHECKED_OUT
        stay.total_price = final_total
        stay.discount = calc_discount
        stay.extra_charge = calc_extra

        # Mark all guests as checked out if needed (Optional depending on business logic)
        # For now we just update the stay status
        
        db.commit()

        return JSONResponse({
            "status": "success",
            "message": f"Check-out thành công! Phòng {room.room_number if room else '—'}",
            "stay_id": stay.id,
            "room_number": room.room_number if room else "—",
            "check_in_at": stay.check_in_at.isoformat(),
            "check_out_at": now.isoformat(),
            "total_price": float(final_total),
            "deposit": float(stay.deposit) if stay.deposit else 0.0,
            "discount": calc_discount,
            "extra_charge": calc_extra,
            "amount_due": float(final_total) - float(stay.deposit or 0),
        })
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        db.rollback()
        err_msg = traceback.format_exc()
        logger.error(f"PMS Checkout Error (stay_id={stay_id}):\n{err_msg}")
        # Return proper JSON error instead of raw text
        return JSONResponse(
            status_code=400, 
            content={"detail": f"Lỗi hệ thống khi trả phòng: {str(e)}"}
        )