from __future__ import annotations

from typing import Annotated, Final
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
from fastapi.responses import JSONResponse

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.constants import MAX_ERROR_MESSAGE_LENGTH
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_api_common import (
    FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE,
    FLOW_RUN_FORBIDDEN_DESCRIPTION,
    FLOW_RUN_SERVICE_KEY_REVIEW_CLAUSE,
    audit_actor_kwargs,
    commit_flow_runtime_write_before_response,
    error_response,
)
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_models import (
    PAGINATED_FLOW_RUN_RESPONSE_EXAMPLE,
    FlowRunCreateRequest,
    FlowRunPublic,
    FlowRunRedispatchResponse,
)
from eneo.flows.api.flow_run_status_capability_models import (
    FlowRunStatusCapabilitiesPublic,
    flow_run_status_capabilities_public,
)
from eneo.flows.api.flow_runtime_paths import (
    FLOW_RUN_CANCEL_PATH,
    FLOW_RUN_PATH,
    FLOW_RUN_REDISPATCH_PATH,
    FLOW_RUN_STATUS_CAPABILITIES_PATH,
    FLOW_RUNS_PATH,
)
from eneo.flows.application.flow_dispatch import (
    FlowRunDispatchAccepted,
    FlowRunDispatchFailed,
    dispatch_flow_run_recoverably_after_commit,
)
from eneo.flows.domain.flow import FlowRun, FlowRunStatus
from eneo.flows.domain.flow_run_exceptions import FlowRunConcurrencyLimitReachedError
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_step_inputs import FlowRunStepInputFiles
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes, InternalServerException
from eneo.main.models import GeneralError, OffsetPaginatedResponse
from eneo.server.dependencies.container import (
    get_container,
    get_container_for_explicit_transaction,
)
from eneo.server.exception_handlers import extract_request_id

router = APIRouter()

_FLOW_RUN_IDEMPOTENCY_HEADER_DESCRIPTION = (
    "Optional caller-supplied idempotency key. Reusing the same key with the same "
    "request payload returns the existing run payload. Reusing the same key with a "
    "different payload returns `400` with code `flow_run_idempotency_conflict`. "
    "Replay is available while the matching run row is retained; clients should keep "
    "the returned run id as the durable polling handle."
)

_FLOW_RUN_CONCURRENCY_RETRY_AFTER_SECONDS: Final[int] = 60
_FLOW_RUN_STATUS_CAPABILITIES_DESCRIPTION = """
Return the canonical Flow run status capability table.

Use this endpoint when building run-history, polling, cancellation, redispatch, and
human-review UI logic. The response describes what each `FlowRun.status` value means
operationally, so clients do not need to hard-code status groups.

Important semantics:
- `should_poll` is true for `queued`, `running`, and `awaiting_review`.
- `is_terminal` is true for `completed`, `failed`, and `cancelled`.
- `is_cancellable` tells clients when the cancel endpoint is a valid action.
- `can_request_redispatch` is true for `queued`, but redispatch remains server-gated by
  `dispatch_next_attempt_at`; a queued run that is not due returns
  `redispatched_count: 0`.
- `filter_order` is the recommended status filter order for run-history UIs.

The table is flow-agnostic and stable across tenants. Fetch it once at application startup
or generate equivalent constants from this OpenAPI schema.
"""

_FLOW_RUN_CREATE_DESCRIPTION = (
    """
    Create a new run for a published flow.

    The returned run id is committed before this endpoint returns `201 Created`, so clients can
    immediately poll `GET /api/v1/flows/{id}/runs/{run_id}/` with the id from the response.

    Generic consumer sequence:
    1. Inspect `GET /api/v1/flows/{id}/run-contract/` to understand the published form fields,
       required runtime step inputs, and version pinning requirements.
    2. Upload required files via `.../steps/{step_id}/runtime-files/` using step ids
       from the run contract before creating the run. A returned file id may be
       reused under each compatible `step_inputs[step_id].file_ids` entry for
       the same Flow.
    3. Submit the returned uploaded files through `step_inputs[step_id].file_ids`,
       together with any structured `input_payload_json` fields in this run request.
    4. Poll `GET /api/v1/flows/{id}/runs/{run_id}/` for the typed terminal `result`,
       and use `.../steps/` for detailed step progress and evidence.

    Request bodies reject unknown JSON fields. The removed top-level `file_ids` field returns
    `400` with code `flow_run_top_level_file_ids_not_supported`; use
    `step_inputs[step_id].file_ids` instead.

    `Idempotency-Key` is optional but recommended for retried writes. Reusing the same key with
    the same request payload returns the existing run payload. Reusing the same key with a
    different payload returns `400` with code `flow_run_idempotency_conflict`. Replay does not
    enqueue another run; it returns the current retained run row. Replay lasts while the
    matching run row is retained; clients should keep the returned run id as the durable
    polling handle.

    Service-key principals may create published-flow runs in v1. Draft ownership and AI Builder
    flows still require a user principal.

    """
    + FLOW_RUN_SERVICE_KEY_REVIEW_CLAUSE
    + """
    """
)

_FLOW_RUN_STATUS_DESCRIPTION = """
    Get one run for a specific flow.

    Use this endpoint for run status and the typed top-level `result` when building consumer apps.
    `result` is null until the run completes successfully, then discriminates inline text,
    authored structured JSON, current artifact metadata, or successful outbound delivery.
    Structured values and contracts are interpreted with this run's pinned `flow_version`.
    Current runtime visibility is policy-based: callers always see their own runs, tenant admins
    can inspect runs across the tenant, same-space admins and owners can inspect run metadata for
    flows in their space, and service-key principals can inspect only their own runs.
    """

_FLOW_RUN_LIST_DESCRIPTION = """
    List runs for a specific flow.

    Use this endpoint to list runs under `/flows/{id}`.
    The `count` field in the paginated response reports the number of items returned in the
    current page, not the total number of matching runs across all pages. `has_more` reports
    whether another page exists after this offset window.

    Each item uses the same typed `result` projection as the single-run endpoint. Historical
    completed runs are interpreted with their own pinned `flow_version`; incomplete runs return
    `result: null`.

    Current runtime visibility is policy-based: callers always list their own runs, tenant admins
    can list runs across the tenant, same-space admins and owners can list run metadata for flows
    in their space, and service-key principals can list only their own runs.
    """

_FLOW_RUN_CANCEL_DESCRIPTION = (
    """
Cancel a flow run if it is not already terminal.

This is the canonical run control endpoint for flow consumers. Current runtime lifecycle control
is policy-based: callers can cancel their own runs, tenant admins can cancel runs across the
tenant, same-space admins and owners can cancel runs for flows in their space, and service-key
principals can cancel only their own runs.

"""
    + FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE
    + """
    """
)


@router.get(
    FLOW_RUN_STATUS_CAPABILITIES_PATH,
    response_model=FlowRunStatusCapabilitiesPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_run_status_capabilities",
    summary="Get flow run status capabilities",
    description=_FLOW_RUN_STATUS_CAPABILITIES_DESCRIPTION,
    responses={
        401: error_response(
            description="Authentication is required to inspect Flow run capabilities.",
            message="Unauthenticated.",
            eneo_error_code=ErrorCodes.AUTHENTICATION_ERROR,
            code="authentication_error",
        ),
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
    },
)
async def get_flow_run_status_capabilities(
    _container: Container = Depends(get_container(with_user=True)),
) -> FlowRunStatusCapabilitiesPublic:
    return flow_run_status_capabilities_public()


@router.post(
    FLOW_RUNS_PATH,
    response_model=FlowRunPublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_flow_run",
    summary="Create flow run",
    description=_FLOW_RUN_CREATE_DESCRIPTION,
    responses={
        400: error_response(
            description=(
                "Flow cannot be run in its current state or the request payload is "
                "invalid. Machine-readable codes include "
                "`flow_not_published`, `flow_definition_checksum_mismatch`, "
                "`flow_run_top_level_file_ids_not_supported`, "
                "`flow_run_idempotency_conflict`, and "
                "`flow_run_required_step_input_missing`. Runtime step-input errors "
                "include context.step_ids so clients can highlight the missing "
                "required upload controls."
            ),
            message="Flow must be published before creating runs.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
            code=FlowApiErrorCode.FLOW_NOT_PUBLISHED,
        ),
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow not found in tenant scope.",
            message="Flow not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
        429: {
            **error_response(
                description=(
                    "The tenant already has the maximum number of active Flow runs. "
                    "Wait for capacity, then submit the logical run again."
                ),
                message="Concurrent flow run limit reached for this tenant.",
                eneo_error_code=ErrorCodes.BAD_REQUEST,
                code=FlowApiErrorCode.RUN_CONCURRENCY_LIMIT_REACHED,
                context={
                    "max_concurrent_runs": 4,
                    "retry_after_seconds": _FLOW_RUN_CONCURRENCY_RETRY_AFTER_SECONDS,
                },
            ),
            "headers": {
                "Retry-After": {
                    "description": "Suggested delay before submitting a new run.",
                    "schema": {
                        "type": "integer",
                        "example": _FLOW_RUN_CONCURRENCY_RETRY_AFTER_SECONDS,
                    },
                }
            },
        },
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
    container: Container = Depends(
        get_container_for_explicit_transaction(with_user=True)
    ),
) -> FlowRunPublic | JSONResponse:
    assembler = FlowAssembler()
    dispatch_run: FlowRun | None = None
    completed_replay_view = None
    try:
        async with commit_flow_runtime_write_before_response(container):
            await flow_access_context.enforce_flow_scope(
                request,
                container,
                flow_id=id,
                required_access=FlowApiAction.RUN,
                allow_service_key_principals=True,
                require_published_for_service_key=True,
            )
            run_service = container.flow_run_service()
            user = container.user()
            actor_kwargs = audit_actor_kwargs(user)
            create_result = await run_service.create_run(
                flow_id=id,
                input_payload_json=run_in.input_payload_json,
                expected_flow_version=run_in.expected_flow_version,
                step_inputs=(
                    {
                        step_id: FlowRunStepInputFiles(
                            file_ids=tuple(step_input.file_ids)
                        )
                        for step_id, step_input in run_in.step_inputs.items()
                    }
                    if run_in.step_inputs is not None
                    else None
                ),
                idempotency_key=idempotency_key,
            )
            run = create_result.run
            if create_result.created:
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
                dispatch_run = run
            elif run.status is FlowRunStatus.COMPLETED:
                completed_replay_view = (
                    await run_service.enrich_run_with_result_files_and_token_usage(
                        run=run,
                    )
                )
    except FlowRunConcurrencyLimitReachedError as exc:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(_FLOW_RUN_CONCURRENCY_RETRY_AFTER_SECONDS)},
            content=GeneralError(
                message="Concurrent flow run limit reached for this tenant.",
                eneo_error_code=ErrorCodes.BAD_REQUEST,
                code=FlowApiErrorCode.RUN_CONCURRENCY_LIMIT_REACHED.value,
                context={
                    "max_concurrent_runs": exc.max_concurrent_runs,
                    "retry_after_seconds": _FLOW_RUN_CONCURRENCY_RETRY_AFTER_SECONDS,
                },
                request_id=extract_request_id(request),
            ).model_dump(mode="json", exclude_none=True),
        )

    if dispatch_run is not None:
        background_tasks.add_task(
            dispatch_flow_run_recoverably_after_commit,
            run_id=dispatch_run.id,
            tenant_id=dispatch_run.tenant_id,
            expected_revision=dispatch_run.revision,
        )
    if completed_replay_view is not None:
        return assembler.to_run_public(
            completed_replay_view.run,
            result_files=completed_replay_view.result_files,
            token_usage=completed_replay_view.token_usage,
            final_output=completed_replay_view.final_output,
        )
    return assembler.to_run_public(run)


@router.get(
    FLOW_RUNS_PATH,
    response_model=OffsetPaginatedResponse[FlowRunPublic],
    status_code=status.HTTP_200_OK,
    operation_id="list_flow_runs",
    summary="List flow runs",
    description=_FLOW_RUN_LIST_DESCRIPTION,
    responses={
        200: {
            "description": (
                "Flow run page. `items` contains the returned page only; "
                "`count` is the number of returned runs and `has_more` tells "
                "clients whether to request the next offset window."
            ),
            "content": {
                "application/json": {
                    "example": PAGINATED_FLOW_RUN_RESPONSE_EXAMPLE,
                }
            },
        },
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow not found in tenant scope.",
            message="Flow not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def list_flow_runs(
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
    statuses: Annotated[
        list[FlowRunStatus] | None,
        Query(
            alias="status",
            description=(
                "Filter runs by one or more status values. Repeat `status=` "
                "to request multiple statuses."
            ),
        ),
    ] = None,
    container: Container = Depends(get_container(with_user=True)),
):
    await flow_access_context.enforce_flow_scope(
        request,
        container,
        flow_id=id,
        required_access=FlowApiAction.VIEW,
        allow_service_key_principals=True,
    )
    run_service = container.flow_run_service()
    page = await run_service.list_runs_with_result_files_and_token_usage(
        flow_id=id,
        statuses=statuses,
        limit=limit,
        offset=offset,
    )
    assembler = FlowAssembler()
    return {
        "count": len(page.items),
        "items": [
            assembler.to_run_public(
                item.run,
                result_files=item.result_files,
                token_usage=item.token_usage,
                final_output=item.final_output,
            )
            for item in page.items
        ],
        "has_more": page.has_more,
    }


@router.get(
    FLOW_RUN_PATH,
    response_model=FlowRunPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_run",
    summary="Get flow run",
    description=_FLOW_RUN_STATUS_DESCRIPTION,
    responses={
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def get_flow_run(
    id: Annotated[
        UUID, Path(description="Identifier of the flow that owns the requested run.")
    ],
    run_id: Annotated[UUID, Path(description="Identifier of the run to return.")],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await flow_access_context.enforce_flow_scope(
        request,
        container,
        flow_id=id,
        required_access=FlowApiAction.VIEW,
        allow_service_key_principals=True,
    )
    run_service = container.flow_run_service()
    run_view = await run_service.get_run_with_result_files_and_token_usage(
        run_id=run_id,
        flow_id=id,
    )
    return FlowAssembler().to_run_public(
        run_view.run,
        result_files=run_view.result_files,
        token_usage=run_view.token_usage,
        final_output=run_view.final_output,
    )


@router.post(
    FLOW_RUN_CANCEL_PATH,
    response_model=FlowRunPublic,
    status_code=status.HTTP_200_OK,
    operation_id="cancel_flow_run",
    summary="Cancel flow run",
    description=_FLOW_RUN_CANCEL_DESCRIPTION,
    responses={
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def cancel_flow_run(
    id: Annotated[
        UUID, Path(description="Identifier of the flow that owns the run to cancel.")
    ],
    run_id: Annotated[UUID, Path(description="Identifier of the run to cancel.")],
    request: Request,
    container: Container = Depends(
        get_container_for_explicit_transaction(with_user=True)
    ),
):
    completed_run_view = None
    async with commit_flow_runtime_write_before_response(container):
        await flow_access_context.enforce_flow_scope(
            request,
            container,
            flow_id=id,
            required_access=FlowApiAction.RUN,
            allow_service_key_principals=True,
        )
        run_service = container.flow_run_service()
        run = await run_service.cancel_run(run_id=run_id, flow_id=id)
        if run.status is FlowRunStatus.COMPLETED:
            completed_run_view = (
                await run_service.enrich_run_with_result_files_and_token_usage(
                    run=run,
                )
            )
    if completed_run_view is not None:
        return FlowAssembler().to_run_public(
            completed_run_view.run,
            result_files=completed_run_view.result_files,
            token_usage=completed_run_view.token_usage,
            final_output=completed_run_view.final_output,
        )
    return FlowAssembler().to_run_public(run)


@router.post(
    FLOW_RUN_REDISPATCH_PATH,
    response_model=FlowRunRedispatchResponse,
    status_code=status.HTTP_200_OK,
    operation_id="redispatch_flow_run",
    summary="Redispatch due queued run",
    description="""
    Attempt to dispatch a queued run whose durable next-at clock is due.

    Returns the refreshed run payload together with `redispatched_count`, which indicates
    whether dispatch was re-triggered for this request.

    Service-key principals may redispatch only their own queued runs in v1.
    """,
    responses={
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def redispatch_flow_run(
    id: Annotated[
        UUID, Path(description="Identifier of the flow that owns the stale queued run.")
    ],
    run_id: Annotated[
        UUID,
        Path(description="Identifier of the queued run to dispatch if it is due."),
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await flow_access_context.enforce_flow_scope(
        request,
        container,
        flow_id=id,
        required_access=FlowApiAction.RUN,
        allow_service_key_principals=True,
    )
    user = container.user()
    actor_kwargs = audit_actor_kwargs(user)
    run_service = container.flow_run_service()
    run = await run_service.get_run(run_id=run_id, flow_id=id)
    dispatch_result = await dispatch_flow_run_recoverably_after_commit(
        run_id=run.id,
        tenant_id=run.tenant_id,
        expected_revision=run.revision,
    )
    if isinstance(dispatch_result, FlowRunDispatchFailed):
        failed_run = dispatch_result.run
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            actor_id=actor_kwargs["actor_id"],
            actor_type=actor_kwargs["actor_type"],
            actor_api_key_id=actor_kwargs["actor_api_key_id"],
            action=ActionType.FLOW_RUN_REDISPATCHED,
            entity_type=EntityType.FLOW_RUN,
            entity_id=failed_run.id,
            description=f"Redispatch failed for flow run {failed_run.id}",
            metadata=AuditMetadata.standard(actor=user, target=failed_run),
            outcome=Outcome.FAILURE,
            error_message=("Flow run dispatch failed; retry state was recorded.")[
                :MAX_ERROR_MESSAGE_LENGTH
            ],
        )
        raise InternalServerException from None

    run = dispatch_result.run
    redispatched_count = int(isinstance(dispatch_result, FlowRunDispatchAccepted))
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=actor_kwargs["actor_id"],
        actor_type=actor_kwargs["actor_type"],
        actor_api_key_id=actor_kwargs["actor_api_key_id"],
        action=ActionType.FLOW_RUN_REDISPATCHED,
        entity_type=EntityType.FLOW_RUN,
        entity_id=run.id,
        description=f"Redispatch requested for flow run {run.id} (dispatch_count={redispatched_count})",
        metadata=AuditMetadata.standard(actor=user, target=run),
    )
    completed_run_view = (
        await run_service.enrich_run_with_result_files_and_token_usage(run=run)
        if run.status is FlowRunStatus.COMPLETED
        else None
    )
    assembler = FlowAssembler()
    public_run = (
        assembler.to_run_public(
            completed_run_view.run,
            result_files=completed_run_view.result_files,
            token_usage=completed_run_view.token_usage,
            final_output=completed_run_view.final_output,
        )
        if completed_run_view is not None
        else assembler.to_run_public(run)
    )
    return FlowRunRedispatchResponse(
        run=public_run,
        redispatched_count=redispatched_count,
    )


__all__ = ["router"]
