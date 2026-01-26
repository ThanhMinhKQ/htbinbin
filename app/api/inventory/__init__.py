from fastapi import APIRouter
from .overview import router as overview_router
from .master_data import router as master_data_router
from .imports import router as imports_router
from .exports import router as exports_router
from .ui import router as ui_router

router = APIRouter()
router_ui = APIRouter()

# API Router
router.include_router(overview_router, tags=["Inventory Overview"])
router.include_router(master_data_router, tags=["Inventory Master Data"])
router.include_router(imports_router, tags=["Inventory Imports"])
router.include_router(exports_router, tags=["Inventory Exports"])

# UI Router
router_ui.include_router(ui_router)
