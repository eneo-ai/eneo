from fastapi import APIRouter

from intric.flows.api.flow_run_router import router as flow_run_router
from intric.flows.api.flow_upload_router import router as flow_upload_router

router = APIRouter()
router.include_router(flow_upload_router)
router.include_router(flow_run_router)

__all__ = ["router"]
