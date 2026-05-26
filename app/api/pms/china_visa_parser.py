# app/api/pms/china_visa_parser.py
"""
China Visa (Email) Parser for Visa scan requests.
Visa OCR is currently not supported; returns honest errors instead of mock data.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def parse_china_visa(image_bytes: bytes, filename: str = "") -> dict:
    """
    Parses a China Visa image/email confirmation.
    Returns an error indicating Visa OCR is currently unsupported.
    """
    logger.info("China visa OCR requested. Filename: %s", filename)
    return {
        "is_valid": False,
        "card_type": "visa",
        "error": "Chức năng nhận diện Visa từ ảnh chưa hỗ trợ dữ liệu thật. Vui lòng nhập thông tin Visa thủ công.",
        "confidence": 0.0,
    }
