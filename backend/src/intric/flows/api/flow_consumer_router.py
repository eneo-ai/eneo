from fastapi import APIRouter

from intric.flows.api.flow_run_evidence_router import (
    export_flow_run_evidence_alias,
    get_flow_run_evidence_alias,
)
from intric.flows.api.flow_run_execution_router import (
    cancel_flow_run_alias,
    create_flow_run,
    get_flow_run_alias,
    list_flow_runs_alias,
    redispatch_flow_run_alias,
)
from intric.flows.api.flow_run_router import router as flow_run_router
from intric.flows.api.flow_run_steps_router import (
    generate_flow_run_artifact_signed_url,
    get_flow_graph,
    list_flow_run_steps,
)
from intric.flows.api.flow_upload_router import (
    get_flow_input_policy,
    get_flow_run_contract,
    router as flow_upload_router,
    upload_flow_file,
    upload_flow_runtime_file,
)

router = APIRouter()
router.include_router(flow_upload_router)
router.include_router(flow_run_router)

__all__ = [
    "router",
    "create_flow_run",
    "get_flow_run_contract",
    "get_flow_input_policy",
    "upload_flow_file",
    "upload_flow_runtime_file",
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
