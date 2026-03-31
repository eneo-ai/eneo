from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Request, status

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.flows.api import flow_router_common as common
from intric.flows.api.flow_api_common import error_response
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.api.flow_models import (
    FlowRunCreateRequest,
    FlowRunPublic,
    FlowRunRedispatchResponse,
)
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes
from intric.main.models import PaginatedResponse
from intric.server.dependencies.container import get_container

router = APIRouter()


@router.post(
    "/{id}/runs/",
    response_model=FlowRunPublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_flow_run",
    summary="Create flow run",
    description="""
    Create a new run for a published flow.

    Generic consumer sequence:
    1. Inspect `GET /api/v1/flows/{id}/run-contract/` to understand the published form fields,
       required runtime step inputs, and version pinning requirements.
    2. Upload any required files via `POST /api/v1/flows/{id}/files/` or the relevant
       `.../steps/{step_id}/runtime-files/` endpoint.
    3. Submit the returned uploaded files as `file_ids`, together with any optional `step_inputs`
       and structured
       `input_payload_json` fields in this run request.
    4. Poll `GET /api/v1/flows/{id}/runs/{run_id}/` and `.../steps/` for progress and outputs.
    """,
    responses={
        400: error_response(
            description=(
                "Flow cannot be run in its current state or request payload is invalid. "
                "Representative machine-readable codes include: flow_not_published, "
                "flow_run_input_payload_too_large, flow_run_concurrency_limit_reached, "
                "flow_input_required_field_missing, flow_input_invalid_number."
            ),
            message="Flow must be published before creating runs.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="flow_not_published",
        ),
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow not found in tenant scope.",
            message="Flow not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def create_flow_run(
    id: Annotated[UUID, Path(description="Identifier of the published flow that should be executed.")],
    request: Request,
    run_in: FlowRunCreateRequest,
    background_tasks: BackgroundTasks,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access="run",
    )
    assembler = FlowAssembler()
    run_service = container.flow_run_service()
    user = container.user()
    run = await run_service.create_run(
        flow_id=id,
        input_payload_json=run_in.input_payload_json,
        expected_flow_version=run_in.expected_flow_version,
        step_inputs=(
            {
                step_id: step_input.model_dump(mode="python")
                for step_id, step_input in run_in.step_inputs.items()
            }
            if run_in.step_inputs is not None
            else None
        ),
        file_ids=run_in.file_ids,
    )

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_RUN_CREATED,
        entity_type=EntityType.FLOW_RUN,
        entity_id=run.id,
        description=f"Created flow run for flow {id}",
        metadata=AuditMetadata.standard(actor=user, target=run),
    )
    background_tasks.add_task(
        common.dispatch_flow_run_after_commit,
        run_id=run.id,
        flow_id=id,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )
    return assembler.to_run_public(run)


@router.get(
    "/{id}/runs/",
    response_model=PaginatedResponse[FlowRunPublic],
    status_code=status.HTTP_200_OK,
    operation_id="list_flow_runs_alias",
    summary="List flow runs (flow-first)",
    description="""
    List runs for a specific flow.

    This is a flow-first alias for run listing to keep runtime orchestration under `/flows/{id}`.
    The `count` field in the paginated response reports the number of items returned in the
    current page, not the total number of matching runs across all pages.
    """,
    responses={
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow not found in tenant scope.",
            message="Flow not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def list_flow_runs_alias(
    id: Annotated[UUID, Path(description="Identifier of the flow whose runs should be listed.")],
    request: Request,
    limit: int = Query(default=50, ge=1, le=200, description="Maximum number of runs to return."),
    offset: int = Query(default=0, ge=0, description="Number of runs to skip before returning results."),
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access="view",
        require_flow_lookup_without_scope=True,
    )
    runs = await container.flow_run_service().list_runs(
        flow_id=id,
        limit=limit,
        offset=offset,
    )
    assembler = FlowAssembler()
    return {"count": len(runs), "items": [assembler.to_run_public(item) for item in runs]}


@router.get(
    "/{id}/runs/{run_id}/",
    response_model=FlowRunPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_run_alias",
    summary="Get flow run (flow-first)",
    description="""
    Get one run for a flow using flow-first routing.

    Use this endpoint for run status and top-level output payload when building consumer apps.
    """,
    responses={
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def get_flow_run_alias(
    id: Annotated[UUID, Path(description="Identifier of the flow that owns the requested run.")],
    run_id: Annotated[UUID, Path(description="Identifier of the run to return.")],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access="view",
    )
    run = await container.flow_run_service().get_run(run_id=run_id, flow_id=id)
    return FlowAssembler().to_run_public(run)


@router.post(
    "/{id}/runs/{run_id}/cancel/",
    response_model=FlowRunPublic,
    status_code=status.HTTP_200_OK,
    operation_id="cancel_flow_run_alias",
    summary="Cancel flow run (flow-first)",
    description="""
Cancel a flow run if it is not already terminal.

This is the canonical run control endpoint for flow consumers.
    """,
    responses={
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def cancel_flow_run_alias(
    id: Annotated[UUID, Path(description="Identifier of the flow that owns the run to cancel.")],
    run_id: Annotated[UUID, Path(description="Identifier of the run to cancel.")],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access="run",
    )
    user = container.user()
    run_service = container.flow_run_service()
    await run_service.get_run(run_id=run_id, flow_id=id)
    run = await run_service.cancel_run(run_id=run_id)

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_RUN_CANCELLED,
        entity_type=EntityType.FLOW_RUN,
        entity_id=run.id,
        description=f"Cancelled flow run {run.id}",
        metadata=AuditMetadata.standard(actor=user, target=run),
    )
    return FlowAssembler().to_run_public(run)


@router.post(
    "/{id}/runs/{run_id}/redispatch/",
    response_model=FlowRunRedispatchResponse,
    status_code=status.HTTP_200_OK,
    operation_id="redispatch_flow_run_alias",
    summary="Redispatch stale queued run (flow-first)",
    description="""
    Attempt to redispatch a stale queued run.

    Returns the refreshed run payload together with `redispatched_count`, which indicates
    whether dispatch was re-triggered for this request.
    """,
    responses={
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def redispatch_flow_run_alias(
    id: Annotated[UUID, Path(description="Identifier of the flow that owns the stale queued run.")],
    run_id: Annotated[UUID, Path(description="Identifier of the run to redispatch if it is still queued.")],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access="run",
    )
    user = container.user()
    run_service = container.flow_run_service()
    run = await run_service.get_run(run_id=run_id, flow_id=id)

    redispatched = await run_service.redispatch_stale_queued_runs(
        flow_id=id,
        run_id=run.id,
        limit=1,
        execution_backend=container.flow_execution_backend(),
    )
    refreshed = await run_service.get_run(run_id=run_id, flow_id=id)

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_RUN_REDISPATCHED,
        entity_type=EntityType.FLOW_RUN,
        entity_id=refreshed.id,
        description=f"Redispatch requested for flow run {refreshed.id} (dispatch_count={redispatched})",
        metadata=AuditMetadata.standard(actor=user, target=refreshed),
    )
    return {
        "run": FlowAssembler().to_run_public(refreshed),
        "redispatched_count": redispatched,
    }
