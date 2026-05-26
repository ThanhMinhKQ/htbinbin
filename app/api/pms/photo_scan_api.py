# app/api/pms/photo_scan_api.py
"""
Photo Scan API for Passport and Visa document scanning.
Accepts photo uploads and returns parsed guest information.
"""
from __future__ import annotations
import logging

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from .pms_helpers import _require_login
from .mrz_parser import parse_mrz_from_image
from .china_visa_parser import parse_china_visa

logger = logging.getLogger(__name__)

router = APIRouter()

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
