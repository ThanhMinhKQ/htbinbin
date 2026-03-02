"""
OTA Dashboard - Pydantic Schemas (Request/Response models)
Tách riêng khỏi api layer để tuân thủ kiến trúc FastAPI chuẩn.
"""

from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class OTAStats(BaseModel):
    total_bookings: int
    total_logs: int
    success_count: int
    failed_count: int
    success_rate: float
    bookings_today: int
    bookings_this_week: int
    bookings_this_month: int

    class Config:
        from_attributes = True


class BookingResponse(BaseModel):
    id: int
    external_id: str
    booking_source: str
    guest_name: str
    guest_phone: Optional[str] = None
    checkin_code: Optional[str] = None
    check_in: Optional[str]
    check_out: Optional[str]
    room_type: Optional[str]
    num_guests: int
    num_adults: Optional[int] = None
    num_children: Optional[int] = None
    total_price: float
    currency: str
    branch_name: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class LogResponse(BaseModel):
    id: int
    email_subject: str
    email_sender: str
    status: str
    error_message: Optional[str]
    received_at: datetime
    retry_count: Optional[int] = 0
    last_retry_at: Optional[datetime] = None
    booking_id: Optional[int] = None

    class Config:
        from_attributes = True


class OTADistribution(BaseModel):
    ota_name: str
    count: int
    percentage: float


class FailedEmailResponse(BaseModel):
    id: int
    email_subject: str
    email_sender: str
    error_message: Optional[str]
    error_traceback: Optional[str]
    received_at: datetime
    retry_count: int
    last_retry_at: Optional[datetime]

    class Config:
        from_attributes = True


class EmailDetailResponse(BaseModel):
    id: int
    email_subject: str
    email_sender: str
    email_message_id: Optional[str]
    received_at: datetime
    status: str
    error_message: Optional[str]
    error_traceback: Optional[str]
    raw_content: Optional[str]
    extracted_data: Optional[Dict[str, Any]]
    retry_count: int
    last_retry_at: Optional[datetime]
    booking_id: Optional[int]
    booking: Optional[Dict[str, Any]]


class TimelineStats(BaseModel):
    period: str
    days: int
    timeline: List[Dict[str, Any]]
    booking_timeline: Dict[str, Any]


class HealthStatus(BaseModel):
    is_healthy: bool
    last_success_at: Optional[datetime]
    logs_today: int
    recent_failures_24h: int
    warnings: List[str]
    gemini_api_configured: bool
