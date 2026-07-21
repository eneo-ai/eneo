from __future__ import annotations

from fastapi import APIRouter

from eneo.flows.api.flow_run_evidence_router import router as evidence_router
from eneo.flows.api.flow_run_lifecycle_router import router as lifecycle_router
from eneo.flows.api.flow_run_rerun_router import router as rerun_router
from eneo.flows.api.flow_run_review_router import router as review_router
from eneo.flows.api.flow_run_steps_router import router as steps_router

router = APIRouter()
router.include_router(lifecycle_router)
router.include_router(review_router)
router.include_router(rerun_router)
router.include_router(evidence_router)
router.include_router(steps_router)

__all__ = ["router"]
