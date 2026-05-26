# app/api/pms/photo_scan_api.py
"""
Photo Scan API for Passport and Visa document scanning.
Accepts photo uploads and returns parsed guest information.
"""
from __future__ import annotations
import logging

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from httpx import TimeoutException

from .pms_helpers import _require_login
from .mrz_parser import parse_mrz_from_image
from .china_visa_parser import parse_china_visa
from .cccd_image_parser import parse_cccd_image

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/api/pms/scan/cccd-photo", tags=["PMS"])
async def api_scan_cccd_photo(
    request: Request,
    front: UploadFile = File(..., description="Ảnh mặt trước CCCD"),
    back: UploadFile = File(None, description="Ảnh mặt sau CCCD (tùy chọn)"),
):
    """
    Tải ảnh mặt trước và mặt sau CCCD lên, phân tích OCR bằng AI vision và trả về structured data.
    """
    _require_login(request)

    if not front or not front.filename:
        return JSONResponse(status_code=400, content={"detail": "Không nhận được tập tin ảnh mặt trước"})

    try:
        front_contents = await front.read()
    except Exception as e:
        logger.error(f"Error reading uploaded front image: {e}")
        return JSONResponse(status_code=400, content={"detail": "Lỗi khi đọc file ảnh mặt trước"})

    if len(front_contents) > 10 * 1024 * 1024:
        return JSONResponse(status_code=400, content={"detail": "Kích thước ảnh mặt trước quá lớn (tối đa 10MB)"})

    back_contents = None
    if back:
        try:
            back_contents = await back.read()
        except Exception as e:
            logger.error(f"Error reading uploaded back image: {e}")
            return JSONResponse(status_code=400, content={"detail": "Lỗi khi đọc file ảnh mặt sau"})

        if not back_contents:
            back_contents = None
        elif len(back_contents) > 10 * 1024 * 1024:
            return JSONResponse(status_code=400, content={"detail": "Kích thước ảnh mặt sau quá lớn (tối đa 10MB)"})

    # Run image parser
    try:
        result = parse_cccd_image(front_contents, back_contents)
    except TimeoutException:
        logger.error("CCCD OCR timeout — Gatecheap server not responding")
        return JSONResponse(status_code=200, content={
            "success": False,
            "error": "Server nhận diện đang quá tải hoặc không phản hồi. Vui lòng thử lại sau 30 giây, hoặc dùng quét mã QR trên CCCD gắn chip."
        })
    except Exception as e:
        logger.error(f"Error parsing CCCD images: {e}")
        err_msg = str(e)
        if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
            return JSONResponse(status_code=200, content={
                "success": False,
                "error": "Server nhận diện đang quá tải hoặc không phản hồi. Vui lòng thử lại sau 30 giây, hoặc dùng quét mã QR trên CCCD gắn chip."
            })
        return JSONResponse(status_code=200, content={
            "success": False,
            "error": f"Lỗi xử lý OCR: {err_msg}"
        })

    if not result.get("is_valid"):
        return JSONResponse({
            "success": False,
            "error": result.get("error", "Không thể phân tích thông tin từ ảnh chụp CCCD")
        })

    return JSONResponse({
        "success": True,
        "data": result,
        "card_type": result.get("card_type"),
        "confidence": result.get("confidence", 0.0),
    })

@router.post("/api/pms/scan/photo", tags=["PMS"])
async def api_scan_photo(
    request: Request,
    image: UploadFile = File(..., description="Ảnh chụp Passport hoặc Visa"),
    doc_type: str = Form(..., description="Loại giấy tờ: passport | visa"),
):
    """
    Tải ảnh Passport hoặc Visa lên, phân tích OCR và trả về structured data.
    """
    _require_login(request)

    # Validate file presence
    if not image or not image.filename:
        return JSONResponse(status_code=400, content={"detail": "Không nhận được tập tin ảnh"})

    # Validate doc_type
    doc_type = doc_type.strip().lower()
    if doc_type not in ("passport", "visa"):
        return JSONResponse(status_code=400, content={"detail": f"Loại giấy tờ '{doc_type}' không hợp lệ"})

    # Read image contents
    try:
        contents = await image.read()
    except Exception as e:
        logger.error(f"Error reading uploaded image file: {e}")
        return JSONResponse(status_code=400, content={"detail": "Lỗi khi đọc file ảnh"})

    # Validate size (max 10MB)
    if len(contents) > 10 * 1024 * 1024:
        return JSONResponse(status_code=400, content={"detail": "Kích thước ảnh quá lớn (tối đa 10MB)"})

    # Route based on doc_type
    if doc_type == "passport":
        result = parse_mrz_from_image(contents, image.filename)
    else:  # visa
        result = parse_china_visa(contents, image.filename)

    if not result.get("is_valid"):
        return JSONResponse({
            "success": False,
            "error": result.get("error", "Không thể phân tích thông tin từ ảnh chụp")
        })

    return JSONResponse({
        "success": True,
        "data": result,
        "card_type": result.get("card_type"),
        "confidence": 1.0,
    })
