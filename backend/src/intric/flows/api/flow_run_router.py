from __future__ import annotations

from fastapi import APIRouter

from intric.flows.api.flow_run_evidence_router import router as evidence_router
from intric.flows.api.flow_run_execution_router import router as execution_router
from intric.flows.api.flow_run_steps_router import router as steps_router

router = APIRouter()
router.include_router(execution_router)
router.include_router(evidence_router)
router.include_router(steps_router)
