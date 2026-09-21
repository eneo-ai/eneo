from __future__ import annotations

from fastapi import APIRouter

from eneo.flows.api.flow_run_evidence_router import router as evidence_router
from eneo.flows.api.flow_run_lifecycle_router import router as lifecycle_router
from eneo.flows.api.flow_run_retry_router import router as retry_router
from eneo.flows.api.flow_run_review_router import router as review_router
from eneo.flows.api.flow_run_steps_router import router as steps_router
from eneo.flows.api.flow_run_transcript_corrections_router import (
    router as transcript_corrections_router,
)
from eneo.flows.api.flow_run_transcript_words_router import (
    router as transcript_words_router,
)
from eneo.flows.api.flow_transcript_regeneration_router import (
    router as regeneration_router,
)
from eneo.flows.api.flow_transcript_source_router import (
    router as transcript_source_router,
)

router = APIRouter()
router.include_router(lifecycle_router)
router.include_router(review_router)
router.include_router(evidence_router)
router.include_router(steps_router)
router.include_router(transcript_corrections_router)
router.include_router(transcript_words_router)
router.include_router(transcript_source_router)
router.include_router(regeneration_router)
router.include_router(retry_router)

__all__ = ["router"]
