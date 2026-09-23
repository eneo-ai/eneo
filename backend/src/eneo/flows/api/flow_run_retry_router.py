from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, Response
from fastapi.responses import JSONResponse

from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_api_common import (
    commit_flow_runtime_write_before_response,
    error_response,
)
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_models import FLOW_RUN_RETRY_PUBLIC_EXAMPLE, FlowRunRetryPublic
from eneo.flows.api.flow_runtime_paths import FLOW_RUN_RETRY_PATH
from eneo.flows.application.flow_dispatch import (
    dispatch_flow_run_recoverably_after_commit,
)
from eneo.flows.application.flow_run_retry_service import FlowRunRetryService
from eneo.flows.domain.flow_run_exceptions import FlowRunConcurrencyLimitReachedError
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.main.models import GeneralError
from eneo.server.dependencies.container import get_container_for_explicit_transaction

router = APIRouter()


@router.post(
    FLOW_RUN_RETRY_PATH,
    response_model=FlowRunRetryPublic,
    status_code=201,
    operation_id="retry_flow_run_from_failed_step",
    summary="Retry a failed run from its first unfinished step",
    description="""
Create a child run that reuses the contiguous completed prefix of a failed run.
The source must belong to the same principal and use the current published version.
Only inline outputs can be imported, and any prefix review checkpoint must be approved.
The server selects the first unfinished step; earlier steps do not execute again.
The child preserves the source's semantic inputs, file selections, label and purpose.
Only new provider calls contribute to the child's usage.

Idempotency-Key is required. Repeating an accepted request with the same key returns
the same child (200). Creation, imported results and the required audit commit before
dispatch. The source run remains unchanged and can expire under its retention policy;
shared input files remain available while the child references them.
""",
    responses={
        200: {
            "model": FlowRunRetryPublic,
            "description": "Idempotent replay.",
            "content": {
                "application/json": {
                    "example": {**FLOW_RUN_RETRY_PUBLIC_EXAMPLE, "created": False}
                }
            },
        },
        400: error_response(
            description="Invalid or conflicting idempotency key, input limit or changed publication.",
            message="Invalid or conflicting idempotency key, input limit or changed publication.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
            code=FlowApiErrorCode.RUN_INVALID_IDEMPOTENCY_KEY,
        ),
        403: error_response(
            description="Run access and the source principal are required.",
            message="Run access and the source principal are required.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code=FlowApiErrorCode.RUN_ACCESS_DENIED,
        ),
        404: error_response(
            description="The source flow or run is unavailable in tenant scope.",
            message="The source flow or run is unavailable in tenant scope.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
        409: error_response(
            description="Source is not failed, its version is stale, or its prefix cannot be reused.",
            message="Source is not failed, its version is stale, or its prefix cannot be reused.",
            eneo_error_code=ErrorCodes.CONFLICT,
            code=FlowApiErrorCode.RUN_RETRY_SOURCE_NOT_FAILED,
            context={"status": "completed"},
        ),
        429: error_response(
            description="Tenant concurrent-run capacity is exhausted.",
            message="Tenant concurrent-run capacity is exhausted.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
            code=FlowApiErrorCode.RUN_CONCURRENCY_LIMIT_REACHED,
        ),
        503: error_response(
            description="Required audit failed; no retry run was accepted.",
            message="Required audit failed; no retry run was accepted.",
            eneo_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
            code=FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED,
        ),
    },
)
async def retry_flow_run_from_failed_step(
    id: UUID,
    run_id: UUID,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    container: Container = Depends(
        get_container_for_explicit_transaction(
            with_user=True, with_module_user=True, with_upload_admission=True
        )
    ),
) -> FlowRunRetryPublic | JSONResponse:
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
            result = await FlowRunRetryService(
                user=container.user(),
                run_service=container.flow_run_service(),
                access_policy=container.flow_run_access_policy(),
                run_repo=container.flow_run_repo(),
                flow_repo=container.flow_repo(),
                checkpoint_repo=container.flow_run_review_checkpoint_repo(),
                audit_service=container.audit_service(),
            ).retry_from_failed_step(
                flow_id=id, run_id=run_id, idempotency_key=idempotency_key
            )
            public = FlowRunRetryPublic(
                run=FlowAssembler().to_run_public(result.run_result.run),
                created=result.run_result.created,
                source_run_id=result.source_run_id,
                first_executed_step_order=result.first_executed_step_order,
                reused_step_orders=list(result.reused_step_orders),
            )
    except FlowRunConcurrencyLimitReachedError:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "60"},
            content=GeneralError(
                message="Concurrent flow run limit reached for this tenant.",
                eneo_error_code=ErrorCodes.BAD_REQUEST,
                code=FlowApiErrorCode.RUN_CONCURRENCY_LIMIT_REACHED.value,
            ).model_dump(mode="json"),
        )
    if result.run_result.created:
        background_tasks.add_task(
            dispatch_flow_run_recoverably_after_commit,
            run_id=result.run_result.run.id,
            tenant_id=result.run_result.run.tenant_id,
            expected_revision=result.run_result.run.revision,
        )
    else:
        response.status_code = 200
    return public
