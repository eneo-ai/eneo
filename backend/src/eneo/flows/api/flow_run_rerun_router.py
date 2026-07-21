from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Path,
    Request,
    status,
)

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_api_common import (
    FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE,
    FLOW_RUN_FORBIDDEN_DESCRIPTION,
    audit_actor_kwargs,
    commit_flow_runtime_write_before_response,
    error_response,
)
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_models import (
    FlowRunStepRerunRequest,
    FlowRunStepRerunResponse,
)
from eneo.flows.api.flow_runtime_paths import (
    FLOW_RUN_STEP_RERUN_PATH,
)
from eneo.flows.application.flow_dispatch import (
    dispatch_flow_run_recoverably_after_commit,
)
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_step_inputs import FlowRunStepInputFiles
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.server.dependencies.container import (
    get_container_for_explicit_transaction,
)

router = APIRouter()

_FLOW_RUN_STEP_RERUN_DESCRIPTION = (
    """
Request a rerun for one completed step in an existing flow run.

The endpoint returns `202 Accepted` for both a newly accepted rerun and an idempotent
replay of the same rerun request. Use the response `status` to track the rerun operation
lifecycle. On replay, the nested `run` is the current persisted run state, so
`run.revision` can be newer than the submitted `expected_run_revision`.

Rerun is a run lifecycle mutation. Human callers follow the existing flow management
policy; service-key principals may rerun only their own runs under stable service
principal ownership.

"""
    + FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE
    + """
    """
)
_FLOW_RUN_RERUN_REASON_REQUIRED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Rerun reason is required.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_RERUN_REASON_REQUIRED.value,
}

_FLOW_RUN_RERUN_REASON_TOO_LONG_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Rerun reason must be at most 1024 characters.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_RERUN_REASON_TOO_LONG.value,
    "context": {"max_length": 1024},
}

_FLOW_RUN_RERUN_STALE_REVISION_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Flow run revision is stale.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_RERUN_STALE_REVISION.value,
    "context": {
        "expected_run_revision": 4,
        "current_run_revision": 5,
    },
}

_FLOW_RUN_RERUN_INVALID_TRANSITION_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Flow run is not eligible for rerun.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_RERUN_INVALID_TRANSITION.value,
    "context": {"status": "running"},
}

_FLOW_RUN_RERUN_STEP_NOT_FOUND_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Rerun step is not in the published flow snapshot.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_RERUN_STEP_NOT_FOUND.value,
}

_FLOW_RUN_RERUN_STEP_INCOMPLETE_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Rerun step has no completed current result.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_RERUN_STEP_INCOMPLETE.value,
    "context": {"step_ids": ["3a6610d2-8b8b-4837-b260-8e66d2155405"]},
}

_FLOW_RUN_RERUN_STEP_INPUTS_INVALID_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Rerun step_inputs may only target the rerun root step.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_RERUN_STEP_INPUTS_INVALID.value,
    "context": {"step_ids": ["7b8d0f64-3ae6-4b7b-a018-795f85e0d78a"]},
}
_FLOW_RUN_RERUN_ERROR_EXAMPLES: dict[str, dict[str, object]] = {
    FlowApiErrorCode.RUN_RERUN_REASON_REQUIRED.value: {
        "summary": "Rerun request did not include a non-empty reason.",
        "value": _FLOW_RUN_RERUN_REASON_REQUIRED_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.RUN_RERUN_REASON_TOO_LONG.value: {
        "summary": "Rerun reason exceeded the accepted length.",
        "value": _FLOW_RUN_RERUN_REASON_TOO_LONG_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.RUN_RERUN_STALE_REVISION.value: {
        "summary": "Run revision changed before rerun acceptance.",
        "value": _FLOW_RUN_RERUN_STALE_REVISION_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.RUN_RERUN_INVALID_TRANSITION.value: {
        "summary": "Run status cannot accept a step rerun.",
        "value": _FLOW_RUN_RERUN_INVALID_TRANSITION_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.RUN_RERUN_STEP_NOT_FOUND.value: {
        "summary": "Selected step is absent from the published snapshot.",
        "value": _FLOW_RUN_RERUN_STEP_NOT_FOUND_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.RUN_RERUN_STEP_INCOMPLETE.value: {
        "summary": "Selected step or downstream graph has no completed current result.",
        "value": _FLOW_RUN_RERUN_STEP_INCOMPLETE_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.RUN_RERUN_STEP_INPUTS_INVALID.value: {
        "summary": "Rerun file overrides targeted a downstream step.",
        "value": _FLOW_RUN_RERUN_STEP_INPUTS_INVALID_ERROR_EXAMPLE,
    },
}


@router.post(
    FLOW_RUN_STEP_RERUN_PATH,
    response_model=FlowRunStepRerunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="rerun_flow_run_step",
    summary="Rerun flow run step",
    description=_FLOW_RUN_STEP_RERUN_DESCRIPTION,
    responses={
        400: error_response(
            description=(
                "Rerun request is invalid. Representative machine-readable codes "
                "include `flow_run_rerun_reason_required`, "
                "`flow_run_rerun_reason_too_long`, "
                "`flow_run_rerun_stale_revision`, "
                "`flow_run_rerun_invalid_transition`, "
                "`flow_run_rerun_step_not_found`, "
                "`flow_run_rerun_step_incomplete`, and "
                "`flow_run_rerun_step_inputs_invalid`. A corrupt published snapshot "
                "returns `flow_definition_checksum_mismatch`. If the request includes "
                "`input_payload_json` or `step_inputs`, rerun can also return "
                "the shared run input and runtime-file validation codes used by "
                "create-run, such as `flow_run_reserved_input_payload_key`, "
                "`flow_run_input_payload_too_large`, `flow_run_file_not_bound_to_flow`, "
                "`flow_run_file_not_accessible`, `flow_run_runtime_input_disabled`, "
                "`flow_run_step_input_max_files_exceeded`, "
                "`flow_run_step_input_file_too_large`, and "
                "`flow_run_step_input_mimetype_rejected`."
            ),
            examples=_FLOW_RUN_RERUN_ERROR_EXAMPLES,
        ),
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="You do not have permission to rerun flows.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_tenant_permission",
            context={"auth_layer": "tenant_role"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
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
    container: Container = Depends(
        get_container_for_explicit_transaction(with_user=True)
    ),
):
    dispatch_run = None
    completed_run_view = None
    async with commit_flow_runtime_write_before_response(container):
        await flow_access_context.enforce_flow_scope(
            request,
            container,
            flow_id=id,
            required_access=FlowApiAction.RERUN,
            allow_service_key_principals=True,
        )
        user = container.user()
        actor_kwargs = audit_actor_kwargs(user)
        rerun_service = container.flow_run_rerun_service()
        result = await rerun_service.rerun_step(
            flow_id=id,
            run_id=run_id,
            rerun_step_id=step_id,
            expected_run_revision=rerun_in.expected_run_revision,
            reason=rerun_in.reason,
            input_payload_json=rerun_in.input_payload_json,
            step_inputs=(
                {
                    input_step_id: FlowRunStepInputFiles(
                        file_ids=tuple(step_input.file_ids)
                    )
                    for input_step_id, step_input in rerun_in.step_inputs.items()
                }
                if rerun_in.step_inputs is not None
                else None
            ),
        )
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            actor_id=actor_kwargs["actor_id"],
            actor_type=actor_kwargs["actor_type"],
            actor_api_key_id=actor_kwargs["actor_api_key_id"],
            action=ActionType.FLOW_RUN_RERUN_REQUESTED,
            entity_type=EntityType.FLOW_RUN,
            entity_id=result.run.id,
            description=(
                f"Requested rerun for flow run {result.run.id} step {step_id}"
            ),
            metadata=AuditMetadata.standard(
                actor=user,
                target=result.run,
                extra={
                    "flow_id": str(id),
                    "rerun_operation_id": str(result.operation.id),
                    "rerun_step_id": str(step_id),
                    "rerun_created": result.created,
                },
            ),
        )
        if result.created:
            dispatch_run = result.run
        elif result.run.status is FlowRunStatus.COMPLETED:
            completed_run_view = await container.flow_run_service().enrich_run_with_result_files_and_token_usage(
                run=result.run,
            )
    if dispatch_run is not None:
        background_tasks.add_task(
            dispatch_flow_run_recoverably_after_commit,
            run_id=dispatch_run.id,
            tenant_id=dispatch_run.tenant_id,
            expected_revision=dispatch_run.revision,
        )
    return FlowAssembler().to_rerun_response(
        operation=result.operation,
        run=(completed_run_view.run if completed_run_view is not None else result.run),
        invalidated_steps=result.invalidated_steps,
        result_files=(
            completed_run_view.result_files if completed_run_view is not None else ()
        ),
        token_usage=(
            completed_run_view.token_usage if completed_run_view is not None else None
        ),
        final_output=(
            completed_run_view.final_output if completed_run_view is not None else None
        ),
    )


__all__ = ["router"]
