from fastapi import APIRouter
from .overview import router as overview_router
from .master_data import router as master_data_router
from .imports import router as imports_router
from .exports import router as exports_router
from .direct_exports import router as direct_exports_router
from .transfer_images import router as transfer_images_router
from .suppliers import router as suppliers_router
from .stocktake import router as stocktake_router
from .pms_integration import router as pms_router
from .alerts import router as alerts_router
from .audit import router as audit_router
from .ui import router as ui_router

router = APIRouter()
router_ui = APIRouter()

# API Router
router.include_router(overview_router, tags=["Inventory Overview"])
router.include_router(master_data_router, tags=["Inventory Master Data"])
router.include_router(imports_router, tags=["Inventory Imports"])
router.include_router(exports_router, tags=["Inventory Transfers"])
router.include_router(direct_exports_router, tags=["Inventory Direct Exports"])
router.include_router(transfer_images_router, tags=["Inventory Transfer Images"])
router.include_router(suppliers_router, tags=["Inventory Suppliers"])
router.include_router(stocktake_router, tags=["Inventory Stocktake"])
router.include_router(pms_router, tags=["Inventory PMS Integration"])
router.include_router(alerts_router, tags=["Inventory Alerts & Analytics"])
router.include_router(audit_router, tags=["Inventory Audit Trail"])

# UI Router
router_ui.include_router(ui_router)
