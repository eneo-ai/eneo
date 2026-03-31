from __future__ import annotations

from fastapi import APIRouter

from intric.flows.api.flow_run_evidence_router import (
    export_flow_run_evidence_alias,
    get_flow_run_evidence_alias,
    router as evidence_router,
)
from intric.flows.api.flow_run_execution_router import (
    cancel_flow_run_alias,
    create_flow_run,
    get_flow_run_alias,
    list_flow_runs_alias,
    redispatch_flow_run_alias,
    router as execution_router,
)
from intric.flows.api.flow_run_steps_router import (
    generate_flow_run_artifact_signed_url,
    get_flow_graph,
    list_flow_run_steps,
    router as steps_router,
)

router = APIRouter()
router.include_router(execution_router)
router.include_router(evidence_router)
router.include_router(steps_router)

__all__ = [
    "router",
    "create_flow_run",
    "list_flow_runs_alias",
    "get_flow_run_alias",
    "cancel_flow_run_alias",
    "redispatch_flow_run_alias",
    "get_flow_run_evidence_alias",
    "export_flow_run_evidence_alias",
    "list_flow_run_steps",
    "get_flow_graph",
    "generate_flow_run_artifact_signed_url",
]
