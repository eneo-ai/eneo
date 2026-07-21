from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Final
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    Path,
    Request,
    status,
)

from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_api_common import (
    FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE,
    FLOW_RUN_FORBIDDEN_DESCRIPTION,
    FLOW_RUN_SERVICE_KEY_REVIEW_CLAUSE,
    commit_flow_runtime_write_before_response,
    error_response,
)
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_models import (
    FLOW_RUN_REVIEW_CHECKPOINT_APPROVED_RESPONSE_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_EDITED_RESPONSE_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_REJECTED_RESPONSE_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_RESUME_RESPONSE_EXAMPLE,
    FlowRunReviewCheckpointApproveRequest,
    FlowRunReviewCheckpointEditRequest,
    FlowRunReviewCheckpointPublic,
    FlowRunReviewCheckpointRejectRequest,
    FlowRunReviewCheckpointResumeRequest,
    FlowRunReviewCheckpointResumeResponse,
)
from eneo.flows.api.flow_runtime_paths import (
    FLOW_REVIEW_ACTIVE_PATH,
    FLOW_REVIEW_APPROVE_PATH,
    FLOW_REVIEW_CHECKPOINT_PATH,
    FLOW_REVIEW_REJECT_PATH,
    FLOW_REVIEW_RESUME_PATH,
)
from eneo.flows.api.flow_service_principal_actor_read_model import (
    FlowServicePrincipalActorPresenter,
)
from eneo.flows.application.flow_dispatch import (
    dispatch_flow_run_recoverably_after_commit,
)
from eneo.flows.domain.flow import FlowRunReviewCheckpoint, FlowRunStatus
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.server.dependencies.container import (
    get_container,
    get_container_for_explicit_transaction,
)

router = APIRouter()

_FLOW_REVIEW_RESUME_IDEMPOTENCY_HEADER_DESCRIPTION = (
    "Required caller-supplied idempotency key for review resume retries."
)
_FLOW_REVIEW_RESUME_IDEMPOTENCY_HEADER_PARAMETER: Final[Mapping[str, object]] = {
    "name": "Idempotency-Key",
    "in": "header",
    "required": True,
    "schema": {"type": "string"},
    "description": _FLOW_REVIEW_RESUME_IDEMPOTENCY_HEADER_DESCRIPTION,
}
_FLOW_RUN_REVIEW_ACTIVE_DESCRIPTION = (
    """
Return the active human review checkpoint for a paused run.

The endpoint returns `null` with `200 OK` when the run has no active checkpoint.
Consumer sequence for human-in-the-loop apps:
1. Poll the run until `status` is `awaiting_review`.
2. Call this endpoint and render the returned `current_payload_json`.
3. Use `step_label`, `review_mode`, `output_type`, and `output_contract` to choose the
   review UI without reading the mutable flow draft.

`output_contract` is the reviewed step's JSON Schema-style output contract when one exists.
It may be `null` for unstructured text/document steps.

Treat `expires_at` as the review submission deadline. Edit, approve, or reject requests
after this timestamp return `400` with code `flow_review_expired`; this endpoint may
briefly show the checkpoint until the background reconciler marks the run cancelled.
When approval happens before `expires_at`, resume remains valid after the deadline because
the human decision is already persisted.

Current visibility follows run-detail visibility: service-key principals can read only
checkpoints for runs they own, while human callers follow the existing flow view policy.

"""
    + FLOW_RUN_SERVICE_KEY_REVIEW_CLAUSE
    + """
    """
)

_FLOW_RUN_REVIEW_EDIT_DESCRIPTION = (
    """
Edit the current payload for a human review checkpoint.

The request uses `expected_checkpoint_revision` as the checkpoint compare token. On success,
the checkpoint payload and the current step-result projection are updated together. Use the
revision returned from the active-checkpoint response; if another reviewer changed the checkpoint
first, the API returns `400` with code `flow_review_stale_revision` and the client should refetch.

Send the full corrected `current_payload_json`, not a patch. For structured steps, keep the same
top-level payload shape returned by the active checkpoint unless the UI deliberately changes it.
When the checkpoint has an `output_contract`, edited structured payloads are validated before any
checkpoint, step-result projection, or audit state is persisted. Contract failures return `400`
with code `typed_io_contract_violation` and context fields `checkpoint_id`, `step_id`,
`step_order`, and `payload_field`.

The edit must be submitted before the checkpoint `expires_at` deadline. Late edits return
`400` with code `flow_review_expired`.

Service-key principals may edit checkpoints only for runs they own (key must have
`resource_permissions.flows = write`). Human callers follow the same flow review permission
policy used by the approve and reject endpoints.

"""
    + FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE
    + """
    """
)

_FLOW_RUN_REVIEW_EDIT_CONTRACT_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint step 1 output: 'summary' is a required property",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
    "context": {
        "checkpoint_id": "7f4f6d62-0e2b-4682-9fa4-f046c3df1b15",
        "step_id": "3a6610d2-8b8b-4837-b260-8e66d2155405",
        "step_order": 1,
        "payload_field": "structured",
    },
}

_FLOW_RUN_REVIEW_STALE_REVISION_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint revision is stale.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_STALE_REVISION.value,
    "context": {
        "checkpoint_id": "7f4f6d62-0e2b-4682-9fa4-f046c3df1b15",
        "expected_checkpoint_revision": 2,
        "current_checkpoint_revision": 3,
    },
}

_FLOW_RUN_REVIEW_EXPIRED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint has expired.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_EXPIRED.value,
    "context": {
        "checkpoint_id": "7f4f6d62-0e2b-4682-9fa4-f046c3df1b15",
        "state": "awaiting_review",
        "expires_at": "2026-05-14T09:30:00Z",
    },
}

_FLOW_RUN_REVIEW_NOT_ACTIVE_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint is not active for this operation.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_NOT_ACTIVE.value,
    "context": {"state": "resumed"},
}

_FLOW_RUN_REVIEW_RESUME_NOT_ACTIVE_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Flow run is not awaiting review.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_NOT_ACTIVE.value,
    "context": {"status": "cancelled"},
}

_FLOW_RUN_REVIEW_STEP_RESULT_NOT_FOUND_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Current step result projection was not found for review edit.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_STEP_RESULT_NOT_FOUND.value,
}

_FLOW_RUN_REVIEW_REJECT_REASON_REQUIRED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review rejection reason is required.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_REJECT_REASON_REQUIRED.value,
}

_FLOW_RUN_REVIEW_REJECT_REASON_TOO_LONG_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review rejection reason must be at most 1024 characters.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_REJECT_REASON_TOO_LONG.value,
    "context": {"max_length": 1024},
}

_FLOW_RUN_REVIEW_IDEMPOTENCY_KEY_REQUIRED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review resume requires an Idempotency-Key header.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_IDEMPOTENCY_KEY_REQUIRED.value,
}

_FLOW_RUN_INVALID_IDEMPOTENCY_KEY_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Idempotency key must be between 1 and 255 characters.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_INVALID_IDEMPOTENCY_KEY.value,
    "context": {"max_length": 255},
}

_FLOW_RUN_REVIEW_NOT_APPROVED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint must be approved before resume.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_NOT_APPROVED.value,
    "context": {"state": "awaiting_review"},
}

_FLOW_RUN_REVIEW_ALREADY_RESUMED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint has already been resumed.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_ALREADY_RESUMED.value,
}

_FLOW_RUN_REVIEW_REJECTED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint was rejected.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_REJECTED.value,
}

_FLOW_RUN_REVIEW_CANCELLED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint was cancelled.",
    "eneo_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_CANCELLED.value,
}
_FLOW_RUN_REVIEW_STALE_AND_EXPIRED_ERROR_EXAMPLES: dict[str, dict[str, object]] = {
    FlowApiErrorCode.REVIEW_STALE_REVISION.value: {
        "summary": "Checkpoint revision changed before this request.",
        "value": _FLOW_RUN_REVIEW_STALE_REVISION_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.REVIEW_EXPIRED.value: {
        "summary": "Checkpoint expired before review completion.",
        "value": _FLOW_RUN_REVIEW_EXPIRED_ERROR_EXAMPLE,
    },
}

_FLOW_RUN_REVIEW_EDIT_ERROR_EXAMPLES: dict[str, dict[str, object]] = {
    FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value: {
        "summary": "Edited payload violates the step output contract.",
        "value": _FLOW_RUN_REVIEW_EDIT_CONTRACT_ERROR_EXAMPLE,
    },
    **_FLOW_RUN_REVIEW_STALE_AND_EXPIRED_ERROR_EXAMPLES,
    FlowApiErrorCode.REVIEW_NOT_ACTIVE.value: {
        "summary": "Checkpoint state no longer accepts edits.",
        "value": _FLOW_RUN_REVIEW_NOT_ACTIVE_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.REVIEW_STEP_RESULT_NOT_FOUND.value: {
        "summary": "Reviewed step output is no longer available.",
        "value": _FLOW_RUN_REVIEW_STEP_RESULT_NOT_FOUND_ERROR_EXAMPLE,
    },
}

_FLOW_RUN_REVIEW_APPROVE_ERROR_EXAMPLES: dict[str, dict[str, object]] = {
    **_FLOW_RUN_REVIEW_STALE_AND_EXPIRED_ERROR_EXAMPLES,
    FlowApiErrorCode.REVIEW_NOT_ACTIVE.value: {
        "summary": "Checkpoint state no longer accepts approval.",
        "value": _FLOW_RUN_REVIEW_NOT_ACTIVE_ERROR_EXAMPLE,
    },
}

_FLOW_RUN_REVIEW_REJECT_ERROR_EXAMPLES: dict[str, dict[str, object]] = {
    **_FLOW_RUN_REVIEW_STALE_AND_EXPIRED_ERROR_EXAMPLES,
    FlowApiErrorCode.REVIEW_NOT_ACTIVE.value: {
        "summary": "Checkpoint state no longer accepts rejection.",
        "value": _FLOW_RUN_REVIEW_NOT_ACTIVE_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.REVIEW_REJECT_REASON_REQUIRED.value: {
        "summary": "Reject request did not include a non-empty reason.",
        "value": _FLOW_RUN_REVIEW_REJECT_REASON_REQUIRED_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.REVIEW_REJECT_REASON_TOO_LONG.value: {
        "summary": "Reject reason exceeded the accepted length.",
        "value": _FLOW_RUN_REVIEW_REJECT_REASON_TOO_LONG_ERROR_EXAMPLE,
    },
}

_FLOW_RUN_REVIEW_RESUME_ERROR_EXAMPLES: dict[str, dict[str, object]] = {
    FlowApiErrorCode.REVIEW_IDEMPOTENCY_KEY_REQUIRED.value: {
        "summary": "Resume request did not include a retry key.",
        "value": _FLOW_RUN_REVIEW_IDEMPOTENCY_KEY_REQUIRED_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.RUN_INVALID_IDEMPOTENCY_KEY.value: {
        "summary": "Resume retry key exceeded the accepted length.",
        "value": _FLOW_RUN_INVALID_IDEMPOTENCY_KEY_ERROR_EXAMPLE,
    },
    **_FLOW_RUN_REVIEW_STALE_AND_EXPIRED_ERROR_EXAMPLES,
    FlowApiErrorCode.REVIEW_NOT_ACTIVE.value: {
        "summary": "Run or checkpoint state no longer accepts resume.",
        "value": _FLOW_RUN_REVIEW_RESUME_NOT_ACTIVE_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.REVIEW_NOT_APPROVED.value: {
        "summary": "Checkpoint has not been approved yet.",
        "value": _FLOW_RUN_REVIEW_NOT_APPROVED_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.REVIEW_ALREADY_RESUMED.value: {
        "summary": "Checkpoint was already resumed with another retry key.",
        "value": _FLOW_RUN_REVIEW_ALREADY_RESUMED_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.REVIEW_REJECTED.value: {
        "summary": "Rejected checkpoint cannot be resumed.",
        "value": _FLOW_RUN_REVIEW_REJECTED_ERROR_EXAMPLE,
    },
    FlowApiErrorCode.REVIEW_CANCELLED.value: {
        "summary": "Cancelled checkpoint cannot be resumed.",
        "value": _FLOW_RUN_REVIEW_CANCELLED_ERROR_EXAMPLE,
    },
}
_FLOW_RUN_REVIEW_APPROVE_DESCRIPTION = (
    """
Approve the current payload for a human review checkpoint.

Approval advances the checkpoint revision. Resume is a separate command so clients can make
the decision durable before dispatching more runtime work. Use the latest checkpoint `revision`;
stale approvals return `400` with code `flow_review_stale_revision`.

The approval must be submitted before the checkpoint `expires_at` deadline. After approval
is persisted, resume remains valid even if the original deadline has passed.

Service-key principals may approve checkpoints only for runs they own (key must have
`resource_permissions.flows = write`).

"""
    + FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE
    + """
    """
)

_FLOW_RUN_REVIEW_REJECT_DESCRIPTION = (
    """
Reject a human review checkpoint and cancel the run.

The rejection reason is written to lifecycle audit metadata and the run is terminalized with
`cancelled` status using the `review_rejected` lifecycle source.

The rejection must be submitted before the checkpoint `expires_at` deadline. Late rejections
return `400` with code `flow_review_expired`.

Service-key principals may reject checkpoints only for runs they own (key must have
`resource_permissions.flows = write`).

"""
    + FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE
    + """
    """
)

_FLOW_RUN_REVIEW_RESUME_DESCRIPTION = (
    """
Resume a run after an approved human review checkpoint.

Use the `Idempotency-Key` header for retries. Replaying the same key returns the current
checkpoint and run without dispatching another worker task. A successful response is
`202 Accepted`: poll the run and step endpoints after this call to observe resumed execution.

Resume uses the approved checkpoint revision. It can run after the original `expires_at`
deadline only when approval was already persisted before expiry; already expired checkpoints
return `400` with code `flow_review_expired`.

Service-key principals may resume approved checkpoints only for runs they own (key must have
`resource_permissions.flows = write`).

"""
    + FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE
    + """
    """
)


@router.get(
    FLOW_REVIEW_ACTIVE_PATH,
    response_model=FlowRunReviewCheckpointPublic | None,
    status_code=status.HTTP_200_OK,
    operation_id="get_active_flow_run_review_checkpoint",
    summary="Get active flow run review checkpoint",
    description=_FLOW_RUN_REVIEW_ACTIVE_DESCRIPTION,
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
async def get_active_flow_run_review_checkpoint(
    id: Annotated[
        UUID, Path(description="Identifier of the flow that owns the requested run.")
    ],
    run_id: Annotated[UUID, Path(description="Identifier of the run to inspect.")],
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
    checkpoint = await container.flow_run_review_checkpoint_service().get_active_review_checkpoint(
        flow_id=id,
        run_id=run_id,
    )
    if checkpoint is None:
        return None
    return await _present_review_checkpoint(container=container, checkpoint=checkpoint)


@router.patch(
    FLOW_REVIEW_CHECKPOINT_PATH,
    response_model=FlowRunReviewCheckpointPublic,
    status_code=status.HTTP_200_OK,
    operation_id="edit_flow_run_review_checkpoint",
    summary="Edit flow run review checkpoint",
    description=_FLOW_RUN_REVIEW_EDIT_DESCRIPTION,
    responses={
        200: {
            "description": (
                "Checkpoint edited. Use the returned `revision` for the next "
                "approve, reject, or edit request. If you later approve it, use "
                "the post-approval revision for resume."
            ),
            "content": {
                "application/json": {
                    "example": FLOW_RUN_REVIEW_CHECKPOINT_EDITED_RESPONSE_EXAMPLE,
                }
            },
        },
        400: error_response(
            description=(
                "Review edit failed. Representative machine-readable codes include "
                "`typed_io_contract_violation`, `flow_review_stale_revision`, "
                "`flow_review_expired`, `flow_review_not_active`, and "
                "`flow_review_step_result_not_found`. Contract validation errors "
                "include context.checkpoint_id, context.step_id, "
                "context.step_order, and context.payload_field."
            ),
            examples=_FLOW_RUN_REVIEW_EDIT_ERROR_EXAMPLES,
        ),
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="You do not have permission to review flows.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_tenant_permission",
            context={"auth_layer": "tenant_role"},
        ),
        404: error_response(
            description="Run or checkpoint not found for this flow and tenant.",
            message="Review checkpoint not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code=FlowApiErrorCode.REVIEW_CHECKPOINT_NOT_FOUND.value,
        ),
    },
)
async def edit_flow_run_review_checkpoint(
    id: Annotated[UUID, Path(description="Identifier of the flow that owns the run.")],
    run_id: Annotated[UUID, Path(description="Identifier of the run to mutate.")],
    checkpoint_id: Annotated[
        UUID, Path(description="Identifier of the review checkpoint to edit.")
    ],
    request: Request,
    review_in: FlowRunReviewCheckpointEditRequest,
    container: Container = Depends(
        get_container_for_explicit_transaction(with_user=True)
    ),
):
    async with commit_flow_runtime_write_before_response(container):
        await flow_access_context.enforce_flow_scope(
            request,
            container,
            flow_id=id,
            required_access=FlowApiAction.REVIEW,
            allow_service_key_principals=True,
        )
        checkpoint = (
            await container.flow_run_review_checkpoint_service().edit_review_checkpoint(
                flow_id=id,
                run_id=run_id,
                checkpoint_id=checkpoint_id,
                expected_checkpoint_revision=review_in.expected_checkpoint_revision,
                current_payload_json=review_in.current_payload_json,
            )
        )
        response = await _present_review_checkpoint(
            container=container, checkpoint=checkpoint
        )
    return response


@router.post(
    FLOW_REVIEW_APPROVE_PATH,
    response_model=FlowRunReviewCheckpointPublic,
    status_code=status.HTTP_200_OK,
    operation_id="approve_flow_run_review_checkpoint",
    summary="Approve flow run review checkpoint",
    description=_FLOW_RUN_REVIEW_APPROVE_DESCRIPTION,
    responses={
        200: {
            "description": (
                "Checkpoint approved. Use the returned `revision` when calling "
                "the resume endpoint. The example shows an edit-before-approve "
                "path; direct approval without an edit normally returns `edited_at` "
                "as null and revision 2."
            ),
            "content": {
                "application/json": {
                    "example": FLOW_RUN_REVIEW_CHECKPOINT_APPROVED_RESPONSE_EXAMPLE,
                }
            },
        },
        400: error_response(
            description=(
                "Review approval failed. Representative machine-readable codes include "
                "`flow_review_stale_revision`, `flow_review_expired`, and "
                "`flow_review_not_active`."
            ),
            examples=_FLOW_RUN_REVIEW_APPROVE_ERROR_EXAMPLES,
        ),
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="You do not have permission to review flows.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_tenant_permission",
            context={"auth_layer": "tenant_role"},
        ),
        404: error_response(
            description="Run or checkpoint not found for this flow and tenant.",
            message="Review checkpoint not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code=FlowApiErrorCode.REVIEW_CHECKPOINT_NOT_FOUND.value,
        ),
    },
)
async def approve_flow_run_review_checkpoint(
    id: Annotated[UUID, Path(description="Identifier of the flow that owns the run.")],
    run_id: Annotated[UUID, Path(description="Identifier of the run to mutate.")],
    checkpoint_id: Annotated[
        UUID, Path(description="Identifier of the review checkpoint to approve.")
    ],
    request: Request,
    review_in: FlowRunReviewCheckpointApproveRequest,
    container: Container = Depends(
        get_container_for_explicit_transaction(with_user=True)
    ),
):
    async with commit_flow_runtime_write_before_response(container):
        await flow_access_context.enforce_flow_scope(
            request,
            container,
            flow_id=id,
            required_access=FlowApiAction.REVIEW,
            allow_service_key_principals=True,
        )
        checkpoint = await container.flow_run_review_checkpoint_service().approve_review_checkpoint(
            flow_id=id,
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            expected_checkpoint_revision=review_in.expected_checkpoint_revision,
        )
        response = await _present_review_checkpoint(
            container=container, checkpoint=checkpoint
        )
    return response


@router.post(
    FLOW_REVIEW_REJECT_PATH,
    response_model=FlowRunReviewCheckpointPublic,
    status_code=status.HTTP_200_OK,
    operation_id="reject_flow_run_review_checkpoint",
    summary="Reject flow run review checkpoint",
    description=_FLOW_RUN_REVIEW_REJECT_DESCRIPTION,
    responses={
        200: {
            "description": (
                "Checkpoint rejected and the run cancelled. The returned checkpoint "
                "is terminal and cannot be resumed. The example shows an "
                "edit-before-reject path; direct rejection without an edit normally "
                "returns `edited_at` as null and revision 2."
            ),
            "content": {
                "application/json": {
                    "example": FLOW_RUN_REVIEW_CHECKPOINT_REJECTED_RESPONSE_EXAMPLE,
                }
            },
        },
        400: error_response(
            description=(
                "Review rejection failed. Representative machine-readable codes include "
                "`flow_review_stale_revision`, `flow_review_expired`, "
                "`flow_review_not_active`, `flow_review_reject_reason_required`, "
                "and `flow_review_reject_reason_too_long`."
            ),
            examples=_FLOW_RUN_REVIEW_REJECT_ERROR_EXAMPLES,
        ),
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="You do not have permission to review flows.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_tenant_permission",
            context={"auth_layer": "tenant_role"},
        ),
        404: error_response(
            description="Run or checkpoint not found for this flow and tenant.",
            message="Review checkpoint not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code=FlowApiErrorCode.REVIEW_CHECKPOINT_NOT_FOUND.value,
        ),
    },
)
async def reject_flow_run_review_checkpoint(
    id: Annotated[UUID, Path(description="Identifier of the flow that owns the run.")],
    run_id: Annotated[UUID, Path(description="Identifier of the run to mutate.")],
    checkpoint_id: Annotated[
        UUID, Path(description="Identifier of the review checkpoint to reject.")
    ],
    request: Request,
    review_in: FlowRunReviewCheckpointRejectRequest,
    container: Container = Depends(
        get_container_for_explicit_transaction(with_user=True)
    ),
):
    async with commit_flow_runtime_write_before_response(container):
        await flow_access_context.enforce_flow_scope(
            request,
            container,
            flow_id=id,
            required_access=FlowApiAction.REVIEW,
            allow_service_key_principals=True,
        )
        checkpoint = await container.flow_run_review_checkpoint_service().reject_review_checkpoint(
            flow_id=id,
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            expected_checkpoint_revision=review_in.expected_checkpoint_revision,
            reason=review_in.reason,
        )
        response = await _present_review_checkpoint(
            container=container, checkpoint=checkpoint
        )
    return response


@router.post(
    FLOW_REVIEW_RESUME_PATH,
    response_model=FlowRunReviewCheckpointResumeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="resume_flow_run_review_checkpoint",
    openapi_extra={
        "parameters": [_FLOW_REVIEW_RESUME_IDEMPOTENCY_HEADER_PARAMETER],
    },
    summary="Resume flow run review checkpoint",
    description=_FLOW_RUN_REVIEW_RESUME_DESCRIPTION,
    responses={
        202: {
            "description": (
                "Resume accepted. Poll the returned run until it reaches a terminal "
                "status, and use the returned checkpoint revision for idempotent "
                "retry reconciliation."
            ),
            "content": {
                "application/json": {
                    "example": FLOW_RUN_REVIEW_CHECKPOINT_RESUME_RESPONSE_EXAMPLE,
                }
            },
        },
        400: error_response(
            description=(
                "Review resume failed. Representative machine-readable codes include "
                "`flow_review_idempotency_key_required`, "
                "`flow_run_invalid_idempotency_key`, `flow_review_stale_revision`, "
                "`flow_review_expired`, `flow_review_not_active`, "
                "`flow_review_not_approved`, `flow_review_already_resumed`, "
                "`flow_review_rejected`, and `flow_review_cancelled`."
            ),
            examples=_FLOW_RUN_REVIEW_RESUME_ERROR_EXAMPLES,
        ),
        403: error_response(
            description=FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="You do not have permission to resume flows.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_tenant_permission",
            context={"auth_layer": "tenant_role"},
        ),
        404: error_response(
            description="Run or checkpoint not found for this flow and tenant.",
            message="Review checkpoint not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code=FlowApiErrorCode.REVIEW_CHECKPOINT_NOT_FOUND.value,
        ),
    },
)
async def resume_flow_run_review_checkpoint(
    id: Annotated[UUID, Path(description="Identifier of the flow that owns the run.")],
    run_id: Annotated[UUID, Path(description="Identifier of the run to resume.")],
    checkpoint_id: Annotated[
        UUID, Path(description="Identifier of the approved review checkpoint.")
    ],
    request: Request,
    review_in: FlowRunReviewCheckpointResumeRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            include_in_schema=False,
            description=_FLOW_REVIEW_RESUME_IDEMPOTENCY_HEADER_DESCRIPTION,
        ),
    ] = None,
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
            required_access=FlowApiAction.RESUME,
            allow_service_key_principals=True,
        )
        review_service = container.flow_run_review_checkpoint_service()
        result = await review_service.resume_review_checkpoint(
            flow_id=id,
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            expected_checkpoint_revision=review_in.expected_checkpoint_revision,
            idempotency_key=idempotency_key,
        )
        if result.accepted:
            dispatch_run = result.run
        elif result.run.status is FlowRunStatus.COMPLETED:
            completed_run_view = await container.flow_run_service().enrich_run_with_result_files_and_token_usage(
                run=result.run,
            )
        checkpoint = await _present_review_checkpoint(
            container=container,
            checkpoint=result.checkpoint,
        )
    if dispatch_run is not None:
        background_tasks.add_task(
            dispatch_flow_run_recoverably_after_commit,
            run_id=dispatch_run.id,
            tenant_id=dispatch_run.tenant_id,
            expected_revision=dispatch_run.revision,
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
        else assembler.to_run_public(result.run)
    )
    return FlowRunReviewCheckpointResumeResponse(
        checkpoint=checkpoint,
        run=public_run,
    )


async def _present_review_checkpoint(
    *,
    container: Container,
    checkpoint: FlowRunReviewCheckpoint,
) -> FlowRunReviewCheckpointPublic:
    presenter = FlowServicePrincipalActorPresenter(
        api_key_repo=container.api_key_v2_repo(),
        tenant_id=container.user().tenant_id,
    )
    return await presenter.present_review_checkpoint(checkpoint)


__all__ = ["router"]
