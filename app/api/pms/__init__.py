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
from .vn_address import router as vn_address_router
from .guest_activities_api import router as guest_activities_router
from .cccd_scan_api import router as cccd_scan_router
from .photo_scan_api import router as photo_scan_router
from .guest_document_api import router as guest_document_router
from .folio_api import router as folio_router
from .inventory_integration import router as inventory_integration_router
from .reservation_api import router as reservation_router
from .pms_export import router as dklt_export_router

__all__ = [
    "pages_router",
    "rooms_router",
    "checkin_router",
    "checkout_router",
    "stays_router",
    "admin_router",
    "vn_address_router",
    "guest_activities_router",
    "cccd_scan_router",
    "photo_scan_router",
    "guest_document_router",
    "folio_router",
    "inventory_integration_router",
    "reservation_router",
    "dklt_export_router",
]
