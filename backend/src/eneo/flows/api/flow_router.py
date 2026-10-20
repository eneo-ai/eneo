"""REST surface for flows.

Authoring happens through the loopback ``flows`` MCP tools, so this router
only reads flows, exposes the hidden authoring assistant and carries the
run side of the API (runs, status, steps, cancel, review checkpoints) that
external consumers integrate against.
"""

from __future__ import annotations

from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response

from eneo.authentication.auth_dependencies import require_user_for_creation
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.flows.api.dependencies import require_flows_enabled
from eneo.flows.flow_models import (
    FlowAuthoringAssistantPublic,
    FlowConversationBindRequest,
    FlowCreateRequest,
    FlowPublic,
    FlowRevisionPublic,
    FlowRevisionSummaryPublic,
    FlowRunContractPublic,
    FlowRunCreateRequest,
    FlowRunPublic,
    FlowRunReviewCheckpointApproveRequest,
    FlowRunReviewCheckpointEditRequest,
    FlowRunReviewCheckpointPublic,
    FlowRunReviewCheckpointRejectRequest,
    FlowRunReviewCheckpointResumeRequest,
    FlowRunReviewCheckpointResumeResponse,
    FlowRunStepPublic,
    FlowRunSummaryPublic,
    FlowSparsePublic,
)
from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter(dependencies=[Depends(require_flows_enabled)])

_Container = Annotated[Container, Depends(get_container(with_user=True))]
_READ_REASON = "FlowService enforces space membership and flow read permission."
_RUN_REASON = (
    "FlowRunService enforces flow read permission; runs resolve only "
    "through their own flow."
)
_REVIEW_REASON = (
    "FlowRunService enforces flow read permission and checkpoint revision CAS."
)
MAX_RUN_PAGE = 100
MAX_REVISION_PAGE = 100


# --- Flows ---


@router.get(
    "/",
    response_model=PaginatedResponse[FlowSparsePublic],
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_READ_REASON,
)
async def list_flows(
    container: _Container, space_id: UUID
) -> PaginatedResponse[FlowSparsePublic]:
    flows = await container.flow_service().list_flows(space_id)
    return PaginatedResponse(items=flows)


@router.post(
    "/",
    response_model=FlowPublic,
    status_code=201,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="FlowService enforces flow create permission in the space.",
)
async def create_flow(
    request: FlowCreateRequest,
    container: _Container,
    _user_for_creation: None = Depends(require_user_for_creation),
) -> FlowPublic:
    """Start a flow as an empty draft; its chat fills it in afterwards."""
    return await container.flow_service().create_draft(
        space_id=request.space_id, name=request.name
    )


@router.get(
    "/authoring-assistant/",
    response_model=FlowAuthoringAssistantPublic,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="FlowAuthoringAssistantService requires flow create permission.",
)
async def get_authoring_assistant(
    container: _Container, space_id: UUID
) -> FlowAuthoringAssistantPublic:
    return await container.flow_authoring_assistant_service().get_or_create(space_id)


@router.get(
    "/{id}/",
    response_model=FlowPublic,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_READ_REASON,
)
async def get_flow(id: UUID, container: _Container) -> FlowPublic:
    return await container.flow_service().get_flow(id)


@router.delete(
    "/{id}/",
    status_code=204,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="FlowService enforces flow delete permission in the space.",
)
async def delete_flow(id: UUID, container: _Container) -> Response:
    await container.flow_service().delete_flow(id)
    return Response(status_code=204)


@router.post(
    "/{id}/conversation/",
    response_model=FlowPublic,
    responses=responses.get_responses([400, 403, 404, 409]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=(
        "FlowService enforces flow edit permission and that the session is the "
        "caller's own flows chat."
    ),
)
async def bind_conversation(
    id: UUID, request: FlowConversationBindRequest, container: _Container
) -> FlowPublic:
    """Bind the flow to the chat that authors it (409 when bound elsewhere)."""
    return await container.flow_service().bind_conversation(id, request.session_id)


@router.get(
    "/{id}/run-contract/",
    response_model=FlowRunContractPublic,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_READ_REASON,
)
async def get_run_contract(id: UUID, container: _Container) -> FlowRunContractPublic:
    return await container.flow_service().get_run_contract(id)


# --- Revisions ---


@router.get(
    "/{id}/revisions/",
    response_model=PaginatedResponse[FlowRevisionSummaryPublic],
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_READ_REASON,
)
async def list_revisions(
    id: UUID,
    container: _Container,
    limit: Annotated[int, Query(ge=1, le=MAX_REVISION_PAGE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[FlowRevisionSummaryPublic]:
    """The flow's history, newest first: every save, with what it changed."""
    revisions, _total = await container.flow_service().list_revisions(
        id, limit=limit, offset=offset
    )
    return PaginatedResponse(items=revisions)


@router.get(
    "/{id}/revisions/{revision}/",
    response_model=FlowRevisionPublic,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_READ_REASON,
)
async def get_revision(
    id: UUID, revision: int, container: _Container
) -> FlowRevisionPublic:
    return await container.flow_service().get_revision(id, revision)


@router.post(
    "/{id}/revisions/{revision}/restore/",
    response_model=FlowPublic,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="FlowService enforces flow edit permission in the space.",
)
async def restore_revision(
    id: UUID, revision: int, container: _Container
) -> FlowPublic:
    """Make the revision the draft again; the restore is a new revision."""
    return await container.flow_service().restore_revision(id, revision)


# --- Runs ---


@router.post(
    "/{id}/runs/",
    response_model=FlowRunPublic,
    status_code=201,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def create_run(
    id: UUID,
    request: FlowRunCreateRequest,
    container: _Container,
    idempotency_key: Annotated[
        Optional[str], Header(alias="Idempotency-Key", max_length=200)
    ] = None,
) -> FlowRunPublic:
    return await container.flow_run_service().create_run(
        id,
        values=request.values,
        files=request.files,
        run_label=request.run_label,
        expected_flow_version=request.expected_flow_version,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/{id}/runs/",
    response_model=PaginatedResponse[FlowRunSummaryPublic],
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def list_runs(
    id: UUID,
    container: _Container,
    limit: Annotated[int, Query(ge=1, le=MAX_RUN_PAGE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[FlowRunSummaryPublic]:
    runs, _total = await container.flow_run_service().list_runs(
        id, limit=limit, offset=offset
    )
    return PaginatedResponse(items=runs)


@router.get(
    "/{id}/runs/{run_id}/",
    response_model=FlowRunPublic,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def get_run(id: UUID, run_id: UUID, container: _Container) -> FlowRunPublic:
    return await container.flow_run_service().get_run(run_id, flow_id=id)


@router.get(
    "/{id}/runs/{run_id}/status/",
    response_model=FlowRunSummaryPublic,
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def get_run_status(
    id: UUID, run_id: UUID, container: _Container
) -> FlowRunSummaryPublic:
    return await container.flow_run_service().get_run_summary(run_id, flow_id=id)


@router.get(
    "/{id}/runs/{run_id}/steps/",
    response_model=list[FlowRunStepPublic],
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_RUN_REASON,
)
async def get_run_steps(
    id: UUID, run_id: UUID, container: _Container
) -> list[FlowRunStepPublic]:
    return await container.flow_run_service().get_run_steps(run_id, flow_id=id)


@router.post(
    "/{id}/runs/{run_id}/cancel/",
    response_model=FlowRunPublic,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="FlowRunService allows cancel for the run owner or a flow editor.",
)
async def cancel_run(id: UUID, run_id: UUID, container: _Container) -> FlowRunPublic:
    return await container.flow_run_service().cancel_run(run_id, flow_id=id)


# --- Review checkpoints ---


@router.get(
    "/{id}/runs/{run_id}/review-checkpoints/active/",
    response_model=Optional[FlowRunReviewCheckpointPublic],
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_REVIEW_REASON,
)
async def get_active_checkpoint(
    id: UUID, run_id: UUID, container: _Container
) -> Optional[FlowRunReviewCheckpointPublic]:
    return await container.flow_run_service().get_active_checkpoint(run_id, flow_id=id)


@router.patch(
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/",
    response_model=FlowRunReviewCheckpointPublic,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_REVIEW_REASON,
)
async def edit_checkpoint(
    id: UUID,
    run_id: UUID,
    checkpoint_id: UUID,
    request: FlowRunReviewCheckpointEditRequest,
    container: _Container,
) -> FlowRunReviewCheckpointPublic:
    return await container.flow_run_service().edit_checkpoint(
        run_id,
        checkpoint_id,
        expected_revision=request.expected_checkpoint_revision,
        current_payload_json=request.current_payload_json,
        flow_id=id,
    )


@router.post(
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/",
    response_model=FlowRunReviewCheckpointResumeResponse,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_REVIEW_REASON,
)
async def approve_checkpoint(
    id: UUID,
    run_id: UUID,
    checkpoint_id: UUID,
    request: FlowRunReviewCheckpointApproveRequest,
    container: _Container,
) -> FlowRunReviewCheckpointResumeResponse:
    return await container.flow_run_service().approve_checkpoint(
        run_id,
        checkpoint_id,
        expected_revision=request.expected_checkpoint_revision,
        flow_id=id,
        resume=False,
    )


@router.post(
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/",
    response_model=FlowRunReviewCheckpointPublic,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_REVIEW_REASON,
)
async def reject_checkpoint(
    id: UUID,
    run_id: UUID,
    checkpoint_id: UUID,
    request: FlowRunReviewCheckpointRejectRequest,
    container: _Container,
) -> FlowRunReviewCheckpointPublic:
    return await container.flow_run_service().reject_checkpoint(
        run_id,
        checkpoint_id,
        expected_revision=request.expected_checkpoint_revision,
        reason=request.reason,
        flow_id=id,
    )


@router.post(
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/",
    response_model=FlowRunReviewCheckpointResumeResponse,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_REVIEW_REASON,
)
async def resume_checkpoint(
    id: UUID,
    run_id: UUID,
    checkpoint_id: UUID,
    request: FlowRunReviewCheckpointResumeRequest,
    container: _Container,
) -> FlowRunReviewCheckpointResumeResponse:
    return await container.flow_run_service().resume_checkpoint(
        run_id,
        checkpoint_id,
        expected_revision=request.expected_checkpoint_revision,
        flow_id=id,
    )


@router.post(
    "/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve-and-continue/",
    response_model=FlowRunReviewCheckpointResumeResponse,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_REVIEW_REASON,
)
async def approve_and_continue(
    id: UUID,
    run_id: UUID,
    checkpoint_id: UUID,
    request: FlowRunReviewCheckpointApproveRequest,
    container: _Container,
) -> FlowRunReviewCheckpointResumeResponse:
    return await container.flow_run_service().approve_checkpoint(
        run_id,
        checkpoint_id,
        expected_revision=request.expected_checkpoint_revision,
        flow_id=id,
        resume=True,
    )
