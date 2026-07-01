from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Annotated, Final, cast
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
from intric.audit.domain.constants import MAX_ERROR_MESSAGE_LENGTH
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome
from intric.database.database import AsyncSession
from intric.flows.api import flow_access_context
from intric.flows.api.flow_api_common import audit_actor_kwargs, error_response
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.api.flow_models import (
    FLOW_RUN_REVIEW_CHECKPOINT_APPROVED_RESPONSE_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_EDITED_RESPONSE_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_REJECTED_RESPONSE_EXAMPLE,
    FLOW_RUN_REVIEW_CHECKPOINT_RESUME_RESPONSE_EXAMPLE,
    PAGINATED_FLOW_RUN_RESPONSE_EXAMPLE,
    FlowRunCreateRequest,
    FlowRunPublic,
    FlowRunRedispatchResponse,
    FlowRunReviewCheckpointApproveRequest,
    FlowRunReviewCheckpointEditRequest,
    FlowRunReviewCheckpointPublic,
    FlowRunReviewCheckpointRejectRequest,
    FlowRunReviewCheckpointResumeRequest,
    FlowRunReviewCheckpointResumeResponse,
    FlowRunStepRerunRequest,
    FlowRunStepRerunResponse,
)
from intric.flows.api.flow_run_status_capability_models import (
    FlowRunStatusCapabilitiesPublic,
    flow_run_status_capabilities_public,
)
from intric.flows.api.flow_runtime_paths import (
    FLOW_REVIEW_ACTIVE_PATH,
    FLOW_REVIEW_APPROVE_PATH,
    FLOW_REVIEW_CHECKPOINT_PATH,
    FLOW_REVIEW_REJECT_PATH,
    FLOW_REVIEW_RESUME_PATH,
    FLOW_RUN_CANCEL_PATH,
    FLOW_RUN_PATH,
    FLOW_RUN_REDISPATCH_PATH,
    FLOW_RUN_STATUS_CAPABILITIES_PATH,
    FLOW_RUN_STEP_RERUN_PATH,
    FLOW_RUNS_PATH,
)
from intric.flows.api.flow_service_principal_actor_read_model import (
    FlowServicePrincipalActorPresenter,
)
from intric.flows.application.flow_dispatch import (
    dispatch_flow_run_recoverably_after_commit,
)
from intric.flows.application.stale_queued_redispatch import (
    StaleQueuedRedispatchDispatchError,
)
from intric.flows.domain.flow import FlowRunReviewCheckpoint
from intric.flows.flow_access_policy import FlowApiAction
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.flow_run_dispatch_request import FlowRunDispatchRequest
from intric.flows.flow_run_step_inputs import FlowRunStepInputFiles
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes
from intric.main.models import OffsetPaginatedResponse
from intric.server.dependencies.container import (
    get_container,
    get_container_for_explicit_transaction,
)

router = APIRouter()

_FLOW_RUN_FORBIDDEN_DESCRIPTION = (
    "Forbidden. Caller scope, tenant or space permission, and run visibility are "
    "evaluated before returning Flow runtime data. Machine-readable codes include "
    "`insufficient_scope`, `flow_run_access_denied`, and "
    "`flow_service_key_principal_not_supported`."
)

_FLOW_RUN_IDEMPOTENCY_HEADER_DESCRIPTION = (
    "Optional caller-supplied idempotency key. Reusing the same key with the same "
    "request payload returns the existing run payload. Reusing the same key with a "
    "different payload returns `400` with code `flow_run_idempotency_conflict`. "
    "Replay is available while the matching run row is retained; clients should keep "
    "the returned run id as the durable polling handle."
)

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

_FLOW_RUN_SERVICE_KEY_REVIEW_CLAUSE = (
    "Service-key human-review clients should use a service-owned `sk_` key with "
    "`resource_permissions.flows = write`; inspect `steps_requiring_review`, "
    "then expect review checkpoints to pause at `awaiting_review` rather than "
    "auto-approve, and use the same key to mutate only checkpoints for runs it "
    "created."
)

_FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE = (
    "Successful runtime mutations are committed before the response is returned, "
    "so clients can immediately use the returned id or revision in the next "
    "poll/edit/approve/resume request."
)

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
  staleness; a queued run that is not stale returns `redispatched_count: 0`.
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
    4. Poll `GET /api/v1/flows/{id}/runs/{run_id}/` and `.../steps/` for progress and outputs.

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
    + _FLOW_RUN_SERVICE_KEY_REVIEW_CLAUSE
    + """
    """
)

_FLOW_RUN_STATUS_DESCRIPTION = """
    Get one run for a specific flow.

    Use this endpoint for run status and top-level output payload when building consumer apps.
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
    + _FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE
    + """
    """
)

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
    + _FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE
    + """
    """
)

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
    + _FLOW_RUN_SERVICE_KEY_REVIEW_CLAUSE
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
    + _FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE
    + """
    """
)

_FLOW_RUN_REVIEW_EDIT_CONTRACT_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint step 1 output: 'summary' is a required property",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
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
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_STALE_REVISION.value,
    "context": {
        "checkpoint_id": "7f4f6d62-0e2b-4682-9fa4-f046c3df1b15",
        "expected_checkpoint_revision": 2,
        "current_checkpoint_revision": 3,
    },
}

_FLOW_RUN_REVIEW_EXPIRED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint has expired.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_EXPIRED.value,
    "context": {
        "checkpoint_id": "7f4f6d62-0e2b-4682-9fa4-f046c3df1b15",
        "state": "awaiting_review",
        "expires_at": "2026-05-14T09:30:00Z",
    },
}

_FLOW_RUN_REVIEW_NOT_ACTIVE_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint is not active for this operation.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_NOT_ACTIVE.value,
    "context": {"state": "resumed"},
}

_FLOW_RUN_REVIEW_RESUME_NOT_ACTIVE_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Flow run is not awaiting review.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_NOT_ACTIVE.value,
    "context": {"status": "cancelled"},
}

_FLOW_RUN_REVIEW_STEP_RESULT_NOT_FOUND_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Current step result projection was not found for review edit.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_STEP_RESULT_NOT_FOUND.value,
}

_FLOW_RUN_REVIEW_REJECT_REASON_REQUIRED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review rejection reason is required.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_REJECT_REASON_REQUIRED.value,
}

_FLOW_RUN_REVIEW_REJECT_REASON_TOO_LONG_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review rejection reason must be at most 1024 characters.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_REJECT_REASON_TOO_LONG.value,
    "context": {"max_length": 1024},
}

_FLOW_RUN_REVIEW_IDEMPOTENCY_KEY_REQUIRED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review resume requires an Idempotency-Key header.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_IDEMPOTENCY_KEY_REQUIRED.value,
}

_FLOW_RUN_INVALID_IDEMPOTENCY_KEY_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Idempotency key must be between 1 and 255 characters.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_INVALID_IDEMPOTENCY_KEY.value,
    "context": {"max_length": 255},
}

_FLOW_RUN_REVIEW_NOT_APPROVED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint must be approved before resume.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_NOT_APPROVED.value,
    "context": {"state": "awaiting_review"},
}

_FLOW_RUN_REVIEW_ALREADY_RESUMED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint has already been resumed.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_ALREADY_RESUMED.value,
}

_FLOW_RUN_REVIEW_REJECTED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint was rejected.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_REJECTED.value,
}

_FLOW_RUN_REVIEW_CANCELLED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Review checkpoint was cancelled.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.REVIEW_CANCELLED.value,
}

_FLOW_RUN_RERUN_REASON_REQUIRED_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Rerun reason is required.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_RERUN_REASON_REQUIRED.value,
}

_FLOW_RUN_RERUN_REASON_TOO_LONG_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Rerun reason must be at most 1024 characters.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_RERUN_REASON_TOO_LONG.value,
    "context": {"max_length": 1024},
}

_FLOW_RUN_RERUN_STALE_REVISION_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Flow run revision is stale.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_RERUN_STALE_REVISION.value,
    "context": {
        "expected_run_revision": 4,
        "current_run_revision": 5,
    },
}

_FLOW_RUN_RERUN_INVALID_TRANSITION_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Flow run is not eligible for rerun.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_RERUN_INVALID_TRANSITION.value,
    "context": {"status": "running"},
}

_FLOW_RUN_RERUN_STEP_NOT_FOUND_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Rerun step is not in the published flow snapshot.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_RERUN_STEP_NOT_FOUND.value,
}

_FLOW_RUN_RERUN_STEP_INCOMPLETE_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Rerun step has no completed current result.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_RERUN_STEP_INCOMPLETE.value,
    "context": {"step_ids": ["3a6610d2-8b8b-4837-b260-8e66d2155405"]},
}

_FLOW_RUN_RERUN_STEP_INPUTS_INVALID_ERROR_EXAMPLE: dict[str, object] = {
    "message": "Rerun step_inputs may only target the rerun root step.",
    "intric_error_code": int(ErrorCodes.BAD_REQUEST),
    "code": FlowApiErrorCode.RUN_RERUN_STEP_INPUTS_INVALID.value,
    "context": {"step_ids": ["7b8d0f64-3ae6-4b7b-a018-795f85e0d78a"]},
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
    + _FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE
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
    + _FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE
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
    + _FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE
    + """
    """
)


@asynccontextmanager
async def _commit_flow_runtime_write_before_response(
    container: Container,
) -> AsyncGenerator[None, None]:
    session = cast(AsyncSession, container.session())
    async with session.begin():
        yield


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
            intric_error_code=ErrorCodes.AUTHENTICATION_ERROR,
            code="authentication_error",
        ),
        403: error_response(
            description=_FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
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
                "`flow_not_published`, `flow_run_top_level_file_ids_not_supported`, "
                "`flow_run_idempotency_conflict`, and "
                "`flow_run_required_step_input_missing`. Runtime step-input errors "
                "include context.step_ids so clients can highlight the missing "
                "required upload controls."
            ),
            message="Flow must be published before creating runs.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code=FlowApiErrorCode.FLOW_NOT_PUBLISHED,
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
    container: Container = Depends(
        get_container_for_explicit_transaction(with_user=True)
    ),
) -> FlowRunPublic:
    assembler = FlowAssembler()
    dispatch_request: FlowRunDispatchRequest | None = None
    async with _commit_flow_runtime_write_before_response(container):
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
                    step_id: FlowRunStepInputFiles(file_ids=tuple(step_input.file_ids))
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
            dispatch_request = run_service.build_dispatch_request(run)

    if dispatch_request is not None:
        background_tasks.add_task(
            dispatch_flow_run_recoverably_after_commit,
            request=dispatch_request,
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
            description=_FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="You do not have permission to review flows.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_tenant_permission",
            context={"auth_layer": "tenant_role"},
        ),
        404: error_response(
            description="Run or checkpoint not found for this flow and tenant.",
            message="Review checkpoint not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
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
    async with _commit_flow_runtime_write_before_response(container):
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
            description=_FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="You do not have permission to review flows.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_tenant_permission",
            context={"auth_layer": "tenant_role"},
        ),
        404: error_response(
            description="Run or checkpoint not found for this flow and tenant.",
            message="Review checkpoint not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
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
    async with _commit_flow_runtime_write_before_response(container):
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
            description=_FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="You do not have permission to review flows.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_tenant_permission",
            context={"auth_layer": "tenant_role"},
        ),
        404: error_response(
            description="Run or checkpoint not found for this flow and tenant.",
            message="Review checkpoint not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
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
    async with _commit_flow_runtime_write_before_response(container):
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
            description=_FLOW_RUN_FORBIDDEN_DESCRIPTION,
            message="You do not have permission to resume flows.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_tenant_permission",
            context={"auth_layer": "tenant_role"},
        ),
        404: error_response(
            description="Run or checkpoint not found for this flow and tenant.",
            message="Review checkpoint not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
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
    dispatch_request = None
    async with _commit_flow_runtime_write_before_response(container):
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
            run_service = container.flow_run_service()
            dispatch_request = run_service.build_dispatch_request(result.run)
        checkpoint = await _present_review_checkpoint(
            container=container,
            checkpoint=result.checkpoint,
        )
    if dispatch_request is not None:
        background_tasks.add_task(
            dispatch_flow_run_recoverably_after_commit,
            request=dispatch_request,
        )
    return FlowRunReviewCheckpointResumeResponse(
        checkpoint=checkpoint,
        run=FlowAssembler().to_run_public(result.run),
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


@router.post(
    FLOW_RUN_CANCEL_PATH,
    response_model=FlowRunPublic,
    status_code=status.HTTP_200_OK,
    operation_id="cancel_flow_run",
    summary="Cancel flow run",
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
    async with _commit_flow_runtime_write_before_response(container):
        await flow_access_context.enforce_flow_scope(
            request,
            container,
            flow_id=id,
            required_access=FlowApiAction.RUN,
            allow_service_key_principals=True,
        )
        run_service = container.flow_run_service()
        run = await run_service.cancel_run(run_id=run_id, flow_id=id)
    return FlowAssembler().to_run_public(run)


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
                "`flow_run_rerun_step_inputs_invalid`. If the request includes "
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
    container: Container = Depends(
        get_container_for_explicit_transaction(with_user=True)
    ),
):
    dispatch_request = None
    async with _commit_flow_runtime_write_before_response(container):
        await flow_access_context.enforce_flow_scope(
            request,
            container,
            flow_id=id,
            required_access=FlowApiAction.RERUN,
            allow_service_key_principals=True,
        )
        user = container.user()
        actor_kwargs = audit_actor_kwargs(user)
        run_service = container.flow_run_service()
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
            dispatch_request = run_service.build_dispatch_request(result.run)
    if dispatch_request is not None:
        background_tasks.add_task(
            dispatch_flow_run_recoverably_after_commit,
            request=dispatch_request,
        )
    return FlowAssembler().to_rerun_response(
        operation=result.operation,
        run=result.run,
        invalidated_steps=result.invalidated_steps,
    )


@router.post(
    FLOW_RUN_REDISPATCH_PATH,
    response_model=FlowRunRedispatchResponse,
    status_code=status.HTTP_200_OK,
    operation_id="redispatch_flow_run",
    summary="Redispatch stale queued run",
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
async def redispatch_flow_run(
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
    try:
        result = await run_service.redispatch_run(
            flow_id=id,
            run_id=run_id,
            execution_backend=container.flow_execution_backend(),
        )
    except StaleQueuedRedispatchDispatchError as exc:
        failed_run = exc.run
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
            error_message=str(exc)[:MAX_ERROR_MESSAGE_LENGTH],
        )
        raise

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=actor_kwargs["actor_id"],
        actor_type=actor_kwargs["actor_type"],
        actor_api_key_id=actor_kwargs["actor_api_key_id"],
        action=ActionType.FLOW_RUN_REDISPATCHED,
        entity_type=EntityType.FLOW_RUN,
        entity_id=result.run.id,
        description=f"Redispatch requested for flow run {result.run.id} (dispatch_count={result.redispatched_count})",
        metadata=AuditMetadata.standard(actor=user, target=result.run),
    )
    return FlowRunRedispatchResponse(
        run=FlowAssembler().to_run_public(result.run),
        redispatched_count=result.redispatched_count,
    )


__all__ = ["router"]
