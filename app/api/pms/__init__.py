# app/api/pms/__init__.py
"""
PMS API Module - Property Management System
"""
from .pms_pages import router as pages_router
from .pms_rooms import router as rooms_router
from .pms_checkin import router as checkin_router
from .pms_checkout import router as checkout_router
from .pms_stays import router as stays_router
from .pms_admin import router as admin_router

__all__ = [
    "pages_router",
    "rooms_router",
    "checkin_router",
    "checkout_router",
    "stays_router",
    "admin_router",
]
