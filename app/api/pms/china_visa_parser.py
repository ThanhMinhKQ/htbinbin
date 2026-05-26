# app/api/pms/china_visa_parser.py
"""
China Visa (Email) Parser for Visa scan requests.
Uses OCR to find visa fields (Visa Number, Full Name, DOB, Passport Number, etc.).
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

def parse_china_visa(image_bytes: bytes, filename: str = "") -> dict:
    """
    Parses a China Visa image/email confirmation.
    Returns a normalized guest info dictionary.
    """
    logger.info(f"Parsing China Visa from image. Filename: {filename}")

    # China visa email scanning currently returns mock data for development.
    # To implement production-ready China Visa OCR, integration with PaddleOCR/Google Vision is needed.
    return {
        "is_valid": True,
        "card_type": "visa",
        "id_number": "V1234567",
        "name": "ZHANG WEI",
        "dob": "1988-08-08",
        "gender": "Nam",
        "expiry_date": "2027-08-08",
        "nationality": "CHN",
        "address": {
            "raw_address": "",
            "province": "",
            "district": "",
            "ward": "",
            "street": ""
        },
        "conflicts": [],
        "warnings": ["Dữ liệu thử nghiệm từ Visa email (China)"]
    }
