from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    Path,
    Query,
    Request,
    status,
)

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.flows.api import flow_router_common as common
from intric.flows.api.flow_api_common import audit_actor_kwargs, error_response
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.api.flow_models import (
    FlowRunCreateRequest,
    FlowRunPublic,
    FlowRunRedispatchResponse,
    FlowRunStepRerunRequest,
    FlowRunStepRerunResponse,
)
from intric.flows.application.flow_run_service import FlowRunService
from intric.flows.flow_run_step_result_file import FlowRunStepResultFile
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes
from intric.main.models import OffsetPaginatedResponse
from intric.server.dependencies.container import get_container

router = APIRouter()

_FLOW_RUN_FORBIDDEN_DESCRIPTION = (
    "Forbidden. Machine-readable codes include `insufficient_scope` when the API key "
    "space scope does not match the flow, `insufficient_tenant_permission` or "
    "`insufficient_space_permission` for callers without the required access, "
    "`flow_run_access_denied` when a caller tries to access a run outside the current "
    "visibility policy, and `flow_service_key_principal_not_supported` on flow surfaces "
    "that still require a user principal."
)

_FLOW_RUN_IDEMPOTENCY_HEADER_DESCRIPTION = (
    "Optional caller-supplied idempotency key. Reusing the same key with the same "
    "request payload returns the existing run payload. Reusing the same key with a "
    "different payload returns `400` with code `flow_run_idempotency_conflict`. "
    "Replay is available while the matching run row is retained; clients should keep "
    "the returned run id as the durable polling handle."
)

_FLOW_RUN_CREATE_DESCRIPTION = """
    Create a new run for a published flow.

    Generic consumer sequence:
    1. Inspect `GET /api/v1/flows/{id}/run-contract/` to understand the published form fields,
       required runtime step inputs, and version pinning requirements.
    2. Upload any required files via `POST /api/v1/flows/{id}/files/` or the relevant
       `.../steps/{step_id}/runtime-files/` endpoint.
    3. Submit the returned uploaded files through `step_inputs[step_id].file_ids`,
       together with any structured `input_payload_json` fields in this run request.
    4. Poll `GET /api/v1/flows/{id}/runs/{run_id}/` and `.../steps/` for progress and outputs.

    `Idempotency-Key` is optional but recommended for retried writes. Reusing the same key with
    the same request payload returns the existing run payload. Reusing the same key with a
    different payload returns `400` with code `flow_run_idempotency_conflict`. Replay lasts while
    the matching run row is retained; clients should keep the returned run id as the durable
    polling handle.

    Service-key principals may create published-flow runs in v1. Draft ownership and AI Builder
    flows still require a user principal.
    """

_FLOW_RUN_STATUS_DESCRIPTION = """
    Get one run for a flow using flow-first routing.

    Use this endpoint for run status and top-level output payload when building consumer apps.
    Current runtime visibility is policy-based: callers always see their own runs, tenant admins
    can inspect runs across the tenant, same-space admins and owners can inspect run metadata for
    flows in their space, and service-key principals can inspect only their own runs.
    """

_FLOW_RUN_LIST_DESCRIPTION = """
    List runs for a specific flow.

    This is a flow-first alias for run listing to keep runtime orchestration under `/flows/{id}`.
    The `count` field in the paginated response reports the number of items returned in the
    current page, not the total number of matching runs across all pages. `has_more` reports
    whether another page exists after this offset window.

    Current runtime visibility is policy-based: callers always list their own runs, tenant admins
    can list runs across the tenant, same-space admins and owners can list run metadata for flows
    in their space, and service-key principals can list only their own runs.
    """

_FLOW_RUN_CANCEL_DESCRIPTION = """
Cancel a flow run if it is not already terminal.

This is the canonical run control endpoint for flow consumers. Current runtime lifecycle control
is policy-based: callers can cancel their own runs, tenant admins can cancel runs across the
tenant, same-space admins and owners can cancel runs for flows in their space, and service-key
principals can cancel only their own runs.
    """

_FLOW_RUN_STEP_RERUN_DESCRIPTION = """
Request a rerun for one completed step in an existing flow run.

The endpoint returns `202 Accepted` for both a newly accepted rerun and an idempotent
replay of the same rerun request. Use the response `status` to track the rerun operation
lifecycle. On replay, the nested `run` is the current persisted run state, so
`run.revision` can be newer than the submitted `expected_run_revision`.

Rerun is a run lifecycle mutation and currently requires flow management access.
    """


def _get_flow_run_service(container: Container) -> FlowRunService:
    return container.flow_run_service()


def _result_files_by_run_id(
    result_files: list[FlowRunStepResultFile],
) -> dict[UUID, list[FlowRunStepResultFile]]:
    grouped: dict[UUID, list[FlowRunStepResultFile]] = {}
    for result_file in result_files:
        grouped.setdefault(result_file.flow_run_id, []).append(result_file)
    return grouped


@router.post(
    "/{id}/runs/",
    response_model=FlowRunPublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_flow_run",
    summary="Create flow run",
    description=_FLOW_RUN_CREATE_DESCRIPTION,
    responses={
        400: error_response(
            description=(
                "Flow cannot be run in its current state or request payload is invalid. "
                "Representative machine-readable codes include: flow_not_published, "
                "flow_run_input_payload_too_large, flow_run_concurrency_limit_reached, "
                "flow_input_required_field_missing, flow_input_invalid_number, and "
                "flow_run_idempotency_conflict when an Idempotency-Key is replayed with "
                "different input."
            ),
            message="Flow must be published before creating runs.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="flow_not_published",
        ),
        403: error_response(
            description=_FLOW_RUN_FORBIDDEN_DESCRIPTION,
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
    id: Annotated[
        UUID,
        Path(description="Identifier of the published flow that should be executed."),
    ],
    request: Request,
    run_in: FlowRunCreateRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=_FLOW_RUN_IDEMPOTENCY_HEADER_DESCRIPTION,
        ),
    ] = None,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access=common.FlowApiAction.RUN,
        allow_service_key_principals=True,
        require_published_for_service_key=True,
    )
    assembler = FlowAssembler()
    run_service = _get_flow_run_service(container)
    user = container.user()
    actor_kwargs = audit_actor_kwargs(user)
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
        idempotency_key=idempotency_key,
    )

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=actor_kwargs["actor_id"],
        actor_type=actor_kwargs["actor_type"],
        actor_api_key_id=actor_kwargs["actor_api_key_id"],
        action=ActionType.FLOW_RUN_CREATED,
        entity_type=EntityType.FLOW_RUN,
        entity_id=run.id,
        description=f"Created flow run for flow {id}",
        metadata=AuditMetadata.standard(actor=user, target=run),
    )
    dispatch_request = run_service.build_dispatch_request(run)
    background_tasks.add_task(
        common.dispatch_flow_run_after_commit,
        **dispatch_request,
    )
    return assembler.to_run_public(run)


@router.get(
    "/{id}/runs/",
    response_model=OffsetPaginatedResponse[FlowRunPublic],
    status_code=status.HTTP_200_OK,
    operation_id="list_flow_runs_alias",
    summary="List flow runs (flow-first)",
    description=_FLOW_RUN_LIST_DESCRIPTION,
    responses={
        403: error_response(
            description=_FLOW_RUN_FORBIDDEN_DESCRIPTION,
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
    id: Annotated[
        UUID, Path(description="Identifier of the flow whose runs should be listed.")
    ],
    request: Request,
    limit: int = Query(
        default=50, ge=1, le=200, description="Maximum number of runs to return."
    ),
    offset: int = Query(
        default=0, ge=0, description="Number of runs to skip before returning results."
    ),
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access=common.FlowApiAction.VIEW,
        require_flow_lookup_without_scope=True,
        allow_service_key_principals=True,
    )
    run_service = _get_flow_run_service(container)
    runs = await run_service.list_runs(
        flow_id=id,
        limit=limit + 1,
        offset=offset,
    )
    assembler = FlowAssembler()
    page_items = runs[:limit]
    result_files_by_run_id = _result_files_by_run_id(
        await run_service.list_result_files_for_runs(runs=page_items)
    )
    return {
        "count": len(page_items),
        "items": [
            assembler.to_run_public(
                item,
                result_files=result_files_by_run_id.get(item.id, []),
            )
            for item in page_items
        ],
        "has_more": len(runs) > limit,
    }


@router.get(
    "/{id}/runs/{run_id}/",
    response_model=FlowRunPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_run_alias",
    summary="Get flow run (flow-first)",
    description=_FLOW_RUN_STATUS_DESCRIPTION,
    responses={
        403: error_response(
            description=_FLOW_RUN_FORBIDDEN_DESCRIPTION,
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
    id: Annotated[
        UUID, Path(description="Identifier of the flow that owns the requested run.")
    ],
    run_id: Annotated[UUID, Path(description="Identifier of the run to return.")],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access=common.FlowApiAction.VIEW,
        allow_service_key_principals=True,
    )
    run_service = _get_flow_run_service(container)
    run = await run_service.get_run(run_id=run_id, flow_id=id)
    result_files = await run_service.list_result_files_for_runs(runs=[run])
    return FlowAssembler().to_run_public(run, result_files=result_files)


@router.post(
    "/{id}/runs/{run_id}/cancel/",
    response_model=FlowRunPublic,
    status_code=status.HTTP_200_OK,
    operation_id="cancel_flow_run_alias",
    summary="Cancel flow run (flow-first)",
    description=_FLOW_RUN_CANCEL_DESCRIPTION,
    responses={
        403: error_response(
            description=_FLOW_RUN_FORBIDDEN_DESCRIPTION,
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
    id: Annotated[
        UUID, Path(description="Identifier of the flow that owns the run to cancel.")
    ],
    run_id: Annotated[UUID, Path(description="Identifier of the run to cancel.")],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access=common.FlowApiAction.RUN,
        allow_service_key_principals=True,
    )
    run_service = _get_flow_run_service(container)
    await run_service.get_run(run_id=run_id, flow_id=id)
    run = await run_service.cancel_run(run_id=run_id)
    return FlowAssembler().to_run_public(run)


@router.post(
    "/{id}/runs/{run_id}/steps/{step_id}/rerun/",
    response_model=FlowRunStepRerunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="rerun_flow_run_step",
    summary="Rerun flow run step",
    description=_FLOW_RUN_STEP_RERUN_DESCRIPTION,
    responses={
        400: error_response(
            description=(
                "Rerun request is invalid for the current run state. Representative "
                "machine-readable codes include: flow_run_rerun_stale_revision, "
                "flow_run_rerun_invalid_transition, flow_run_rerun_step_not_found, "
                "flow_run_rerun_step_incomplete, flow_run_rerun_step_inputs_invalid, "
                "flow_run_rerun_reason_required, and flow_run_rerun_reason_too_long."
            ),
            message="Flow run revision is stale.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="flow_run_rerun_stale_revision",
        ),
        403: error_response(
            description=_FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="You do not have permission to rerun flows.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_tenant_permission",
            context={"auth_layer": "tenant_role"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def rerun_flow_run_step(
    id: Annotated[UUID, Path(description="Identifier of the flow that owns the run.")],
    run_id: Annotated[UUID, Path(description="Identifier of the run to mutate.")],
    step_id: Annotated[UUID, Path(description="Identifier of the step to rerun.")],
    request: Request,
    rerun_in: FlowRunStepRerunRequest,
    background_tasks: BackgroundTasks,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access=common.FlowApiAction.RERUN,
    )
    run_service = _get_flow_run_service(container)
    result = await run_service.rerun_step(
        flow_id=id,
        run_id=run_id,
        rerun_step_id=step_id,
        expected_run_revision=rerun_in.expected_run_revision,
        reason=rerun_in.reason,
        input_payload_json=rerun_in.input_payload_json,
        step_inputs=(
            {
                input_step_id: step_input.model_dump(mode="python")
                for input_step_id, step_input in rerun_in.step_inputs.items()
            }
            if rerun_in.step_inputs is not None
            else None
        ),
    )
    if result.created:
        background_tasks.add_task(
            common.dispatch_flow_run_recoverably_after_commit,
            **run_service.build_dispatch_request(result.run),
        )
    return FlowAssembler().to_rerun_response(
        operation=result.operation,
        run=result.run,
        invalidated_steps=result.invalidated_steps,
    )


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

    Service-key principals may redispatch only their own queued runs in v1.
    """,
    responses={
        403: error_response(
            description=_FLOW_RUN_FORBIDDEN_DESCRIPTION,
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
    id: Annotated[
        UUID, Path(description="Identifier of the flow that owns the stale queued run.")
    ],
    run_id: Annotated[
        UUID,
        Path(description="Identifier of the run to redispatch if it is still queued."),
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access=common.FlowApiAction.RUN,
        allow_service_key_principals=True,
    )
    user = container.user()
    actor_kwargs = audit_actor_kwargs(user)
    run_service = _get_flow_run_service(container)
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
        actor_id=actor_kwargs["actor_id"],
        actor_type=actor_kwargs["actor_type"],
        actor_api_key_id=actor_kwargs["actor_api_key_id"],
        action=ActionType.FLOW_RUN_REDISPATCHED,
        entity_type=EntityType.FLOW_RUN,
        entity_id=refreshed.id,
        description=f"Redispatch requested for flow run {refreshed.id} (dispatch_count={redispatched})",
        metadata=AuditMetadata.standard(actor=user, target=refreshed),
    )
    response = FlowRunRedispatchResponse(
        run=FlowAssembler().to_run_public(refreshed),
        redispatched_count=redispatched,
    )
    return {
        "run": response.run,
        "redispatched_count": response.redispatched_count,
    }
