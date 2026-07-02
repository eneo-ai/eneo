from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal, Self, TypeAlias, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from intric.authentication.auth_models import (
    FlowServicePrincipalActorPublic,
)
from intric.authentication.principal_types import PrincipalType
from intric.data_retention.constants import MAX_RETENTION_DAYS, MIN_RETENTION_DAYS
from intric.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowMcpPolicy,
    FlowOutputMode,
    FlowOutputType,
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
    FlowRunReviewCheckpointState,
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    RerunDependencyKind,
)
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.flow_review_policy import (
    FLOW_STEP_REVIEW_POLICY_DESCRIPTION,
    FlowStepReviewMode,
    FlowStepReviewPolicy,
)
from intric.flows.flow_run_contract_models import (
    FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE as FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE,
)
from intric.flows.flow_run_contract_models import (
    FlowFinalOutputContractPublic as FlowFinalOutputContractPublic,
)
from intric.flows.flow_run_contract_models import (
    FlowOutputDelivery as FlowOutputDelivery,
)
from intric.flows.flow_run_contract_models import (
    FlowReviewStepContractPublic as FlowReviewStepContractPublic,
)
from intric.flows.flow_run_contract_models import (
    FlowRunContractPublic as FlowRunContractPublic,
)
from intric.flows.flow_run_contract_models import (
    FlowRuntimeInputContractPublic as FlowRuntimeInputContractPublic,
)
from intric.flows.flow_run_contract_models import (
    FlowRuntimeUploadPolicyPublic as FlowRuntimeUploadPolicyPublic,
)
from intric.flows.flow_run_contract_models import (
    FlowTemplateReadinessPublic as FlowTemplateReadinessPublic,
)
from intric.flows.flow_run_contract_models import (
    FormFieldPublic as FormFieldPublic,
)
from intric.flows.flow_run_error import FlowRunError, NullablePublicTerminalErrorCode
from intric.flows.flow_run_evidence_export_manifest import EvidenceExportManifest
from intric.flows.flow_run_evidence_export_summary import EvidenceExportSummary
from intric.flows.flow_run_step_result_file import FlowRunStepResultFile
from intric.main.exceptions import BadRequestException
from intric.main.models import NOT_PROVIDED, NotProvided, partial_model

FLOW_DATA_RETENTION_DAYS_DESCRIPTION = (
    "Number of days to retain full Flow run and step history. "
    "Set to null to inherit the space retention policy. "
    f"Valid range: {MIN_RETENTION_DAYS}-{MAX_RETENTION_DAYS} days."
)
FlowDataRetentionDays: TypeAlias = Annotated[
    int,
    Field(strict=True, ge=MIN_RETENTION_DAYS, le=MAX_RETENTION_DAYS),
]


def _validate_public_principal_actor_shape(
    *,
    label: str,
    principal_type: PrincipalType | None,
    user_id: UUID | None,
    service_principal: FlowServicePrincipalActorPublic | None,
    required: bool,
) -> None:
    if principal_type is None:
        if required or user_id is not None or service_principal is not None:
            raise ValueError(f"{label} principal type is required.")
        return

    if principal_type == PrincipalType.USER:
        if user_id is None or service_principal is not None:
            raise ValueError(
                f"{label} user principal requires user id and no service principal."
            )
        return

    if principal_type == PrincipalType.SERVICE_KEY:
        if user_id is not None or service_principal is None:
            raise ValueError(
                f"{label} service principal requires service principal and no user id."
            )
        return

    raise ValueError(f"{label} principal type is unsupported.")


FLOW_STEP_PUBLIC_EXAMPLE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000101",
    "assistant_id": "00000000-0000-0000-0000-000000000201",
    "step_order": 1,
    "user_description": "Transcribe uploaded audio into Swedish text.",
    "input_source": "flow_input",
    "input_type": "audio",
    "output_mode": "transcribe_only",
    "output_type": "text",
    "mcp_policy": "inherit",
    "created_at": "2026-03-17T09:30:00Z",
    "updated_at": "2026-03-17T09:30:00Z",
}

FLOW_SPARSE_PUBLIC_EXAMPLE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000001",
    "tenant_id": "00000000-0000-0000-0000-000000000010",
    "space_id": "00000000-0000-0000-0000-000000000020",
    "name": "Employee Review Summary",
    "description": "Transcribe a review conversation and return a PDF summary.",
    "created_by_user_id": "00000000-0000-0000-0000-000000000030",
    "owner_user_id": "00000000-0000-0000-0000-000000000030",
    "published_version": 3,
    "metadata_json": {"wizard": {"transcription_enabled": True}},
    "data_retention_days": 30,
    "created_at": "2026-03-17T09:30:00Z",
    "updated_at": "2026-03-17T10:00:00Z",
}

FLOW_PUBLIC_EXAMPLE: dict[str, Any] = {
    **FLOW_SPARSE_PUBLIC_EXAMPLE,
    "steps": [
        FLOW_STEP_PUBLIC_EXAMPLE,
        {
            "id": "00000000-0000-0000-0000-000000000102",
            "assistant_id": "00000000-0000-0000-0000-000000000202",
            "step_order": 2,
            "user_description": "Summarize the transcription into a PDF for HR follow-up.",
            "input_source": "previous_step",
            "input_type": "text",
            "output_mode": "pass_through",
            "output_type": "pdf",
            "mcp_policy": "inherit",
            "created_at": "2026-03-17T09:30:00Z",
            "updated_at": "2026-03-17T09:30:00Z",
        },
    ],
}


FLOW_RUN_PUBLIC_EXAMPLE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000301",
    "flow_id": "00000000-0000-0000-0000-000000000001",
    "flow_version": 3,
    "principal_type": None,
    "tenant_id": "00000000-0000-0000-0000-000000000010",
    "trace_id": "00000000-0000-0000-0000-000000000302",
    "revision": 1,
    "status": "queued",
    "cancelled_at": None,
    "started_at": None,
    "finished_at": None,
    "input_payload_json": {"employee_name": "Alex Example"},
    "output_payload_json": None,
    "result_files": [],
    "token_usage": None,
    "error": None,
    "job_id": "00000000-0000-0000-0000-000000000401",
    "created_at": "2026-03-17T10:05:00Z",
    "updated_at": "2026-03-17T10:05:00Z",
}

FLOW_RUN_STEP_PUBLIC_EXAMPLE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000501",
    "flow_run_id": "00000000-0000-0000-0000-000000000301",
    "flow_id": "00000000-0000-0000-0000-000000000001",
    "tenant_id": "00000000-0000-0000-0000-000000000010",
    "step_id": "00000000-0000-0000-0000-000000000101",
    "step_order": 1,
    "assistant_id": "00000000-0000-0000-0000-000000000201",
    "status": "completed",
    "input_payload_json": {
        "diagnostics": [
            {
                "code": "runtime_input_consumed",
                "message": "Uploaded audio file was used.",
                "severity": "info",
            }
        ]
    },
    "runtime_input_file_ids": ["00000000-0000-0000-0000-000000000701"],
    "output_payload_json": {"text": "Hello and welcome to the annual review..."},
    "result_files": [],
    "current_attempt_no": 1,
    "num_tokens_input": 0,
    "num_tokens_output": 0,
    "error_code": None,
    "error_message": None,
    "diagnostics": [
        {
            "code": "runtime_input_consumed",
            "message": "Uploaded audio file was used.",
            "severity": "info",
        }
    ],
    "started_at": "2026-03-17T10:05:05Z",
    "finished_at": "2026-03-17T10:05:30Z",
    "created_at": "2026-03-17T10:05:05Z",
    "updated_at": "2026-03-17T10:05:30Z",
}

FLOW_RUN_REDISPATCH_RESPONSE_EXAMPLE: dict[str, Any] = {
    "run": FLOW_RUN_PUBLIC_EXAMPLE,
    "redispatched_count": 1,
}

FLOW_RUN_STEP_RERUN_REQUEST_EXAMPLE: dict[str, Any] = {
    "expected_run_revision": 7,
    "reason": "The HR reviewer corrected the transcription for step 1.",
    "input_payload_json": {"reviewer_note": "Use the corrected spelling of Alex."},
    "step_inputs": {
        "00000000-0000-0000-0000-000000000101": {
            "file_ids": ["00000000-0000-0000-0000-000000000701"]
        }
    },
}

FLOW_RUN_STEP_RERUN_RESPONSE_EXAMPLE: dict[str, Any] = {
    "operation_id": "00000000-0000-0000-0000-000000000801",
    "run": {
        **FLOW_RUN_PUBLIC_EXAMPLE,
        "revision": 8,
        "status": "queued",
        "output_payload_json": None,
    },
    "rerun_step_id": "00000000-0000-0000-0000-000000000101",
    "new_attempt_no": 2,
    "invalidated_step_ids": [
        "00000000-0000-0000-0000-000000000101",
        "00000000-0000-0000-0000-000000000102",
    ],
    "status": "queued",
}

FLOW_RUN_REVIEW_CHECKPOINT_PUBLIC_EXAMPLE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000901",
    "tenant_id": "00000000-0000-0000-0000-000000000010",
    "flow_id": "00000000-0000-0000-0000-000000000001",
    "flow_run_id": "00000000-0000-0000-0000-000000000301",
    "step_id": "00000000-0000-0000-0000-000000000101",
    "step_order": 1,
    "attempt_no": 1,
    "state": "awaiting_review",
    "revision": 1,
    "schema_version": 1,
    "original_payload_json": {"text": "Draft answer."},
    "current_payload_json": {"text": "Draft answer."},
    "step_label": "Review draft answer",
    "review_mode": "edit",
    "output_type": "json",
    "output_contract": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
    },
    "next_step_ids": ["00000000-0000-0000-0000-000000000102"],
    "requester_user_id": "00000000-0000-0000-0000-000000000030",
    "requester_service_principal": None,
    "requester_principal_type": "user",
    "decided_by_user_id": None,
    "decided_by_service_principal": None,
    "decided_by_principal_type": None,
    "edited_at": None,
    "approved_at": None,
    "rejected_at": None,
    "resumed_at": None,
    "cancelled_at": None,
    "expires_at": "2026-03-31T10:05:30Z",
    "expired_at": None,
    "created_at": "2026-03-17T10:05:30Z",
    "updated_at": "2026-03-17T10:05:30Z",
}

FLOW_RUN_REVIEW_CHECKPOINT_EVIDENCE_EXAMPLE: dict[str, Any] = {
    **FLOW_RUN_REVIEW_CHECKPOINT_PUBLIC_EXAMPLE,
    "state": "resumed",
    "revision": 4,
    "decision": "approved",
    "current_payload_json": {"text": "Edited answer."},
    "resume_key_present": True,
    "edited_at": "2026-03-17T10:06:30Z",
    "approved_at": "2026-03-17T10:07:30Z",
    "resumed_at": "2026-03-17T10:08:00Z",
}

FLOW_RUN_REVIEW_CHECKPOINT_EDIT_REQUEST_EXAMPLE: dict[str, Any] = {
    "expected_checkpoint_revision": 1,
    "current_payload_json": {"text": "Edited answer."},
}

FLOW_RUN_REVIEW_CHECKPOINT_APPROVE_REQUEST_EXAMPLE: dict[str, Any] = {
    "expected_checkpoint_revision": 2,
}

FLOW_RUN_REVIEW_CHECKPOINT_RESUME_REQUEST_EXAMPLE: dict[str, Any] = {
    "expected_checkpoint_revision": 3,
}

FLOW_RUN_REVIEW_CHECKPOINT_REJECT_REQUEST_EXAMPLE: dict[str, Any] = {
    "expected_checkpoint_revision": 2,
    "reason": "The draft cannot be used for this case.",
}

FLOW_RUN_REVIEW_CHECKPOINT_EDITED_RESPONSE_EXAMPLE: dict[str, Any] = {
    **FLOW_RUN_REVIEW_CHECKPOINT_PUBLIC_EXAMPLE,
    "state": "edited",
    "revision": 2,
    "current_payload_json": {"text": "Edited answer."},
    "decided_by_user_id": "00000000-0000-0000-0000-000000000030",
    "decided_by_service_principal": None,
    "decided_by_principal_type": "user",
    "edited_at": "2026-03-17T10:06:30Z",
}

FLOW_RUN_REVIEW_CHECKPOINT_APPROVED_RESPONSE_EXAMPLE: dict[str, Any] = {
    **FLOW_RUN_REVIEW_CHECKPOINT_EDITED_RESPONSE_EXAMPLE,
    "state": "approved",
    "revision": 3,
    "approved_at": "2026-03-17T10:07:30Z",
}

FLOW_RUN_REVIEW_CHECKPOINT_REJECTED_RESPONSE_EXAMPLE: dict[str, Any] = {
    **FLOW_RUN_REVIEW_CHECKPOINT_EDITED_RESPONSE_EXAMPLE,
    "state": "rejected",
    "revision": 3,
    "rejected_at": "2026-03-17T10:07:30Z",
}

FLOW_RUN_REVIEW_CHECKPOINT_RESUME_RESPONSE_EXAMPLE: dict[str, Any] = {
    "checkpoint": {
        **FLOW_RUN_REVIEW_CHECKPOINT_APPROVED_RESPONSE_EXAMPLE,
        "state": "resumed",
        "revision": 4,
        "resumed_at": "2026-03-17T10:08:00Z",
    },
    "run": {
        **FLOW_RUN_PUBLIC_EXAMPLE,
        "status": "queued",
        "revision": 2,
    },
}

PAGINATED_FLOW_SPARSE_RESPONSE_EXAMPLE: dict[str, Any] = {
    "items": [FLOW_SPARSE_PUBLIC_EXAMPLE],
    "has_more": False,
    "count": 1,
}

PAGINATED_FLOW_RUN_RESPONSE_EXAMPLE: dict[str, Any] = {
    "items": [FLOW_RUN_PUBLIC_EXAMPLE],
    "has_more": False,
    "count": 1,
}


class FlowStepCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "assistant_id": "00000000-0000-0000-0000-000000000001",
                "step_order": 1,
                "user_description": "Transcribe incoming audio",
                "input_source": "flow_input",
                "input_type": "audio",
                "output_mode": "transcribe_only",
                "output_type": "text",
                "mcp_policy": "inherit",
            }
        },
    )

    assistant_id: UUID
    step_order: int
    timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        description="Optional per-step LLM timeout override in seconds.",
    )
    user_description: str | None = None
    input_source: FlowInputSource
    input_type: FlowInputType
    input_contract: dict[str, Any] | None = None
    output_mode: FlowOutputMode
    output_type: FlowOutputType
    output_contract: dict[str, Any] | None = None
    input_bindings: dict[str, Any] | None = None
    output_classification_override: int | None = None
    mcp_policy: FlowMcpPolicy
    input_config: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None
    review_policy: FlowStepReviewPolicy | None = Field(
        default=None,
        description=FLOW_STEP_REVIEW_POLICY_DESCRIPTION,
    )

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def _validate_timeout_seconds(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("timeout_seconds must be an integer.")
        if value <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")
        return value


class FlowStepUpdateRequest(FlowStepCreateRequest):
    id: UUID | None = Field(
        default=None,
        description=(
            "Persisted draft step id. Omit for a new step; include it to update, "
            "reorder, or retain an existing draft step."
        ),
    )


class FlowCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "space_id": "00000000-0000-0000-0000-000000000001",
                "name": "Municipality Intake Transcription",
                "description": "Transcribe and summarize citizen audio",
                "steps": [
                    {
                        "assistant_id": "00000000-0000-0000-0000-000000000002",
                        "step_order": 1,
                        "input_source": "flow_input",
                        "input_type": "audio",
                        "output_mode": "transcribe_only",
                        "output_type": "text",
                        "mcp_policy": "inherit",
                    }
                ],
            }
        },
    )

    space_id: UUID
    name: str
    description: str | None = None
    steps: list[FlowStepCreateRequest]
    metadata_json: dict[str, Any] | None = None
    data_retention_days: FlowDataRetentionDays | None = Field(
        default=None,
        description=FLOW_DATA_RETENTION_DAYS_DESCRIPTION,
    )


@partial_model
class FlowUpdateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "name": "Municipality Intake Transcription v2",
                "description": "Transcribe, redact, and summarize citizen audio submissions.",
                "steps": [
                    {
                        "id": "00000000-0000-0000-0000-000000000101",
                        "assistant_id": "00000000-0000-0000-0000-000000000002",
                        "step_order": 1,
                        "user_description": "Transcribe incoming audio",
                        "input_source": "flow_input",
                        "input_type": "audio",
                        "output_mode": "transcribe_only",
                        "output_type": "text",
                        "mcp_policy": "inherit",
                    }
                ],
                "metadata_json": {"wizard": {"transcription_enabled": True}},
                "data_retention_days": 30,
            }
        },
    )

    name: str
    description: str | None
    steps: list[FlowStepUpdateRequest]
    metadata_json: dict[str, Any] | None | NotProvided = Field(default=NOT_PROVIDED)
    data_retention_days: FlowDataRetentionDays | None | NotProvided = Field(
        default=NOT_PROVIDED,
        description=FLOW_DATA_RETENTION_DAYS_DESCRIPTION,
    )


class FlowStepPublic(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_extra={"example": FLOW_STEP_PUBLIC_EXAMPLE}
    )

    id: UUID | None = None
    assistant_id: UUID
    step_order: int
    timeout_seconds: int | None = None
    user_description: str | None = None
    input_source: FlowInputSource
    input_type: FlowInputType
    input_contract: dict[str, Any] | None = None
    output_mode: FlowOutputMode
    output_type: FlowOutputType
    output_contract: dict[str, Any] | None = None
    input_bindings: dict[str, Any] | None = None
    output_classification_override: int | None = None
    mcp_policy: FlowMcpPolicy
    input_config: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None
    review_policy: FlowStepReviewPolicy | None = Field(
        default=None,
        description=FLOW_STEP_REVIEW_POLICY_DESCRIPTION,
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FlowSparsePublic(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": FLOW_SPARSE_PUBLIC_EXAMPLE},
    )

    id: UUID
    tenant_id: UUID
    space_id: UUID
    name: str
    description: str | None = None
    created_by_user_id: UUID | None = None
    owner_user_id: UUID | None = None
    published_version: int | None = None
    metadata_json: dict[str, Any] | None = None
    data_retention_days: FlowDataRetentionDays | None = Field(
        default=None,
        description=FLOW_DATA_RETENTION_DAYS_DESCRIPTION,
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FlowPublic(FlowSparsePublic):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": FLOW_PUBLIC_EXAMPLE},
    )

    steps: list[FlowStepPublic]


class StepRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_ids: list[UUID] = Field(
        default_factory=lambda: cast(list[UUID], []),
        description=(
            "Uploaded file ids to attach to this specific step. Use the step ids "
            "from `GET /api/v1/flows/{id}/run-contract/` rather than sending all "
            "files to the first step. File order is preserved for this step after "
            "duplicate ids are collapsed by first occurrence."
        ),
    )


FLOW_RUN_CREATE_REQUEST_EXAMPLE: dict[str, Any] = {
    "expected_flow_version": 3,
    "input_payload_json": {"employee_name": "Alex Example"},
    "step_inputs": {
        "00000000-0000-0000-0000-000000000101": {
            "file_ids": ["00000000-0000-0000-0000-000000000701"]
        }
    },
}


class FlowRunCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": FLOW_RUN_CREATE_REQUEST_EXAMPLE},
    )

    expected_flow_version: int | None = Field(
        default=None,
        description=(
            "Published flow version the caller prepared against. Send the "
            "`published_flow_version` returned by the run contract to avoid starting "
            "a run after the flow was republished with different inputs."
        ),
    )
    input_payload_json: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Structured form/runtime values for the flow. Field names should come "
            "from `form_fields` in the run contract."
        ),
    )
    step_inputs: dict[UUID, StepRunInput] | None = Field(
        default=None,
        description=(
            "Per-step runtime inputs keyed by step id. This is the supported way to "
            "route uploads to step 3, 5, 8, or any other step that declares runtime "
            "input in the run contract."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def reject_removed_top_level_file_ids(cls, data: object) -> object:
        if isinstance(data, Mapping) and "file_ids" in data:
            raise BadRequestException(
                "Top-level file_ids is no longer supported. Call the run contract endpoint "
                "to find the target step id, then send uploaded files as "
                "step_inputs[step_id].file_ids.",
                code=FlowApiErrorCode.RUN_TOP_LEVEL_FILE_IDS_NOT_SUPPORTED.value,
                context={
                    "invalid_field": "file_ids",
                    "expected_field": "step_inputs[step_id].file_ids",
                    "contract_endpoint": "/api/v1/flows/{id}/run-contract/",
                },
            )
        return cast(object, data)


class FlowAssistantCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"example": {"name": "Flow Step Assistant"}}
    )

    name: str


class FlowRunTokenUsagePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    num_tokens_input: int = Field(
        ge=0,
        description="Provider-reported input tokens consumed by the run.",
    )
    num_tokens_output: int = Field(
        ge=0,
        description="Provider-reported output tokens consumed by the run.",
    )
    num_tokens_total: int = Field(
        ge=0,
        description="Total provider-reported tokens consumed by the run.",
    )


class FlowRunPublic(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_extra={"example": FLOW_RUN_PUBLIC_EXAMPLE}
    )

    id: UUID
    flow_id: UUID
    flow_version: int
    principal_type: PrincipalType | None = None
    tenant_id: UUID
    trace_id: UUID
    revision: int = Field(
        description=(
            "Monotonic run lifecycle compare token. Step-rerun requests use this "
            "value as `expected_run_revision`."
        ),
    )
    status: FlowRunStatus
    cancelled_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    input_payload_json: dict[str, Any] | None = None
    output_payload_json: dict[str, Any] | None = None
    result_files: list[FlowRunStepResultFile] = Field(
        default_factory=lambda: cast(list[FlowRunStepResultFile], [])
    )
    token_usage: FlowRunTokenUsagePublic | None = Field(
        default=None,
        description=(
            "Aggregated provider-reported token usage for model attempts in this "
            "run. Null when the run has not produced token-metered model usage."
        ),
    )
    error: FlowRunError | None = Field(
        default=None,
        description=(
            "Structured terminal run error. API consumers should branch on "
            "`error.code`; null means the run has no terminal run-level error."
        ),
    )
    job_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class FlowRunReviewCheckpointPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_RUN_REVIEW_CHECKPOINT_PUBLIC_EXAMPLE}
    )

    id: UUID
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    step_id: UUID
    step_order: int
    attempt_no: int
    state: FlowRunReviewCheckpointState
    revision: int
    schema_version: int
    original_payload_json: dict[str, Any] | None = None
    current_payload_json: dict[str, Any] | None = None
    step_label: str | None = Field(
        default=None,
        description=(
            "Immutable snapshot of the reviewed step label. Null when the step had no label."
        ),
    )
    review_mode: FlowStepReviewMode = Field(
        description="Immutable snapshot of the reviewed step's review mode.",
    )
    output_type: FlowOutputType = Field(
        description="Immutable snapshot of the reviewed step's output type.",
    )
    output_contract: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Immutable snapshot of the reviewed step's output contract. Null means "
            "the step had no output contract."
        ),
    )
    next_step_ids: list[UUID] | None = None
    requester_user_id: UUID | None = None
    requester_service_principal: FlowServicePrincipalActorPublic | None = None
    requester_principal_type: PrincipalType
    decided_by_user_id: UUID | None = None
    decided_by_service_principal: FlowServicePrincipalActorPublic | None = None
    decided_by_principal_type: PrincipalType | None = None
    edited_at: datetime | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    resumed_at: datetime | None = None
    cancelled_at: datetime | None = None
    expires_at: datetime | None = Field(
        default=None,
        description=(
            "Review submission deadline for this unresolved review checkpoint. "
            "Mutating the checkpoint after this timestamp returns `400` with code "
            "`flow_review_expired`; the active-checkpoint endpoint may briefly show "
            "the checkpoint until the background reconciler cancels the run. "
            "Approved checkpoints can still be resumed after this timestamp because "
            "the human decision was already persisted. Null only for legacy "
            "checkpoints created before review expiry was persisted."
        ),
    )
    expired_at: datetime | None = Field(
        default=None,
        description=(
            "Set when the platform terminalized this unresolved checkpoint because "
            "the review deadline passed. Null while the checkpoint is still active, "
            "approved, rejected, cancelled for another reason, or from legacy data "
            "without persisted expiry state."
        ),
    )
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_principal_actors(self) -> Self:
        _validate_public_principal_actor_shape(
            label="requester",
            principal_type=self.requester_principal_type,
            user_id=self.requester_user_id,
            service_principal=self.requester_service_principal,
            required=True,
        )
        _validate_public_principal_actor_shape(
            label="decider",
            principal_type=self.decided_by_principal_type,
            user_id=self.decided_by_user_id,
            service_principal=self.decided_by_service_principal,
            required=False,
        )
        return self


class FlowRunReviewCheckpointEditRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": FLOW_RUN_REVIEW_CHECKPOINT_EDIT_REQUEST_EXAMPLE},
    )

    expected_checkpoint_revision: int = Field(
        ge=1,
        description=(
            "Checkpoint revision observed by the reviewer. Stale values return "
            "`400` with code `flow_review_stale_revision`."
        ),
    )
    current_payload_json: dict[str, Any] = Field(
        description=(
            "Full corrected payload for the reviewed step. Send the complete payload, "
            "not a JSON Patch document."
        )
    )


class FlowRunReviewCheckpointApproveRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": FLOW_RUN_REVIEW_CHECKPOINT_APPROVE_REQUEST_EXAMPLE
        },
    )

    expected_checkpoint_revision: int = Field(
        ge=1,
        description=(
            "Checkpoint revision observed by the approver. Stale values return "
            "`400` with code `flow_review_stale_revision`."
        ),
    )


class FlowRunReviewCheckpointRejectRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": FLOW_RUN_REVIEW_CHECKPOINT_REJECT_REQUEST_EXAMPLE
        },
    )

    expected_checkpoint_revision: int = Field(
        ge=1,
        description=(
            "Checkpoint revision observed by the reviewer. Stale values return "
            "`400` with code `flow_review_stale_revision`."
        ),
    )
    reason: str = Field(
        description=(
            "Human-readable rejection reason stored with the run audit trail. "
            "Blank reasons return `400` with code `flow_review_reject_reason_required`; "
            "reasons longer than 1024 characters return `400` with code "
            "`flow_review_reject_reason_too_long`."
        ),
    )


class FlowRunReviewCheckpointResumeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": FLOW_RUN_REVIEW_CHECKPOINT_RESUME_REQUEST_EXAMPLE
        },
    )

    expected_checkpoint_revision: int = Field(
        ge=1,
        description=(
            "Approved checkpoint revision to resume from. Use the latest revision "
            "returned by approve or active-checkpoint polling."
        ),
    )


class FlowRunReviewCheckpointResumeResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": FLOW_RUN_REVIEW_CHECKPOINT_RESUME_RESPONSE_EXAMPLE
        }
    )

    checkpoint: FlowRunReviewCheckpointPublic
    run: FlowRunPublic


class FlowStepDiagnosticPublic(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "code": "runtime_input_consumed",
                "message": "Uploaded audio file was used.",
                "severity": "info",
            }
        },
    )

    code: str = Field(description="Stable diagnostic code.")
    message: str = Field(description="Human-readable diagnostic message.")
    severity: Literal["info", "warning", "error"] = Field(
        default="warning",
        description="Diagnostic severity.",
    )


def _empty_runtime_input_file_ids() -> list[UUID]:
    return []


class FlowRunStepPublic(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": FLOW_RUN_STEP_PUBLIC_EXAMPLE},
    )

    id: UUID | None = None
    flow_run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    step_id: UUID
    step_order: int
    assistant_id: UUID | None = None
    status: FlowStepResultStatus
    input_payload_json: dict[str, Any] | None = None
    runtime_input_file_ids: list[UUID] = Field(
        default_factory=_empty_runtime_input_file_ids,
        description=(
            "File ids submitted as runtime input for the current attempt of this step result."
        ),
    )
    output_payload_json: dict[str, Any] | None = None
    current_attempt_no: int | None = None
    result_files: list[FlowRunStepResultFile] = Field(
        default_factory=lambda: cast(list[FlowRunStepResultFile], [])
    )
    effective_prompt: str | None = None
    model_parameters_json: dict[str, Any] | None = None
    num_tokens_input: int | None = None
    num_tokens_output: int | None = None
    error_code: NullablePublicTerminalErrorCode = Field(
        default=None,
        description=(
            "Stable machine-readable step failure code. Clients should branch on "
            "this code when present and treat error_message as technical detail."
        ),
    )
    error_message: str | None = None
    flow_step_execution_hash: str | None = None
    diagnostics: list[FlowStepDiagnosticPublic] = Field(
        default_factory=lambda: cast(list[FlowStepDiagnosticPublic], [])
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class FlowRunRedispatchResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_RUN_REDISPATCH_RESPONSE_EXAMPLE}
    )

    run: FlowRunPublic
    redispatched_count: int


class FlowRunStepRerunRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": FLOW_RUN_STEP_RERUN_REQUEST_EXAMPLE},
    )

    expected_run_revision: int = Field(
        ge=1,
        description="Run revision observed by the caller before requesting the rerun.",
    )
    reason: str = Field(
        min_length=1,
        max_length=1024,
        description="Human-readable reason for accepting the rerun operation.",
    )
    input_payload_json: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional replacement for the run's semantic inline input payload when "
            "the rerun is accepted. Existing orchestration metadata and runtime "
            "transcription cache values are preserved."
        ),
    )
    step_inputs: dict[UUID, StepRunInput] | None = Field(
        default=None,
        description=(
            "Optional file inputs keyed by the rerun root step id. Provided step ids "
            "replace their existing `step_inputs` entry; other step ids are preserved."
        ),
    )


class FlowRunStepRerunResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_RUN_STEP_RERUN_RESPONSE_EXAMPLE}
    )

    operation_id: UUID
    run: FlowRunPublic = Field(
        description=(
            "Current persisted run state. On idempotent replay, `run.revision` may "
            "have advanced past the request's `expected_run_revision`."
        )
    )
    rerun_step_id: UUID
    new_attempt_no: int
    invalidated_step_ids: list[UUID]
    status: FlowRunRerunOperationStatus


class FlowRunDebugIoTypes(BaseModel):
    input: str | None = None
    output: str | None = None


class FlowRunDebugInput(BaseModel):
    source: str | None = None
    type: str | None = None
    contract: dict[str, Any] | None = None
    bindings: dict[str, Any] | None = None
    config: dict[str, Any] | None = None


class FlowRunDebugOutput(BaseModel):
    mode: str | None = None
    type: str | None = None
    contract: dict[str, Any] | None = None
    classification: int | None = None
    config: dict[str, Any] | None = None


class FlowRunDebugMcpServer(BaseModel):
    id: str
    name: str


class FlowRunDebugMcpTool(BaseModel):
    tool_id: str
    server_id: str
    name: str


def _empty_flow_run_debug_mcp_servers() -> list[FlowRunDebugMcpServer]:
    return []


def _empty_flow_run_debug_mcp_tools() -> list[FlowRunDebugMcpTool]:
    return []


class FlowRunDebugMcp(BaseModel):
    policy: str | None = None
    servers: list[FlowRunDebugMcpServer] = Field(
        default_factory=_empty_flow_run_debug_mcp_servers
    )
    tools_enabled: list[FlowRunDebugMcpTool] = Field(
        default_factory=_empty_flow_run_debug_mcp_tools
    )


class FlowRunDebugRagReferenceChunk(BaseModel):
    chunk_no: int = 0
    score: float = 0.0
    snippet: str = ""


class FlowRunDebugRagReference(BaseModel):
    id: str
    id_short: str
    title: str | None = None
    source_title_raw: str | None = None
    display_title: str | None = None
    source_display_name: str | None = None
    source_url: str | None = None
    source_kind: str | None = None
    source_container_kind: str | None = None
    source_container_name: str | None = None
    source_container_name_raw: str | None = None
    source_container_display_name: str | None = None
    source_container_label: str | None = None
    source_container_id: str | None = None
    usage_state: str | None = None
    display_snippet: str | None = None
    display_chunk_no: int | None = None
    display_selection_reason: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    boilerplate_likelihood: float | None = None
    snippet_quality: str | None = None
    matched_chunk_count: int = 0
    best_score: float = 0.0
    chunks: list[FlowRunDebugRagReferenceChunk] = Field(
        default_factory=lambda: cast(list[FlowRunDebugRagReferenceChunk], [])
    )


class FlowRunDebugRagTracking(BaseModel):
    retrieval_tracked: bool = True
    prompt_context_inclusion_tracked: bool = False
    citation_tracked: bool = False
    material_influence_tracked: bool = False
    selection_basis: str | None = None
    note: str | None = None


class FlowRunDebugRagPromptContextGroup(BaseModel):
    source_id: str | None = None
    source_title: str | None = None
    start_chunk: int | None = None
    end_chunk: int | None = None
    chunk_count: int | None = None
    relevance_score: float | None = None


class FlowRunDebugRagPromptContext(BaseModel):
    tracked: bool = True
    version: int | None = None
    selection_basis: str | None = None
    raw_source_count: int | None = None
    raw_chunk_count: int | None = None
    included_source_count: int | None = None
    not_included_source_count: int | None = None
    included_chunk_count: int | None = None
    knowledge_tokens: int | None = None
    truncated_by_token_budget: bool | None = None
    included_source_ids: list[str] = Field(default_factory=list)
    not_included_source_ids: list[str] = Field(default_factory=list)
    included_source_titles: list[str] = Field(default_factory=list)
    included_source_display_names: list[str] = Field(default_factory=list)
    included_groups: list[FlowRunDebugRagPromptContextGroup] = Field(
        default_factory=lambda: cast(list[FlowRunDebugRagPromptContextGroup], [])
    )
    summary: dict[str, Any] | None = None


class FlowRunDebugRag(BaseModel):
    attempted: bool | None = None
    status: str | None = None
    version: int | None = None
    timeout_seconds: int | None = None
    include_info_blobs: bool | None = None
    chunks_retrieved: int | None = None
    raw_chunks_count: int | None = None
    deduped_chunks_count: int | None = None
    unique_sources: int | None = None
    source_ids: list[str] | None = None
    source_ids_short: list[str] | None = None
    error_code: str | None = None
    retrieval_duration_ms: int | None = None
    retrieval_error_type: str | None = None
    references: list[FlowRunDebugRagReference] | None = None
    references_truncated: bool | None = None
    source_names: list[str] | None = None
    source_display_names: list[str] | None = None
    has_named_sources: bool | None = None
    tracking: FlowRunDebugRagTracking | None = None
    prompt_context: FlowRunDebugRagPromptContext | None = None


class FlowRunDebugAttempt(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "attempt_no": 1,
                "status": "completed",
                "duration_ms": 5240,
                "requested_model": "gpt-4.1",
                "response_model": "gpt-4.1-mini",
                "provider": "openai",
                "finish_reason": "stop",
                "provider_response_id": "resp_123",
                "num_tokens_input": 321,
                "num_tokens_output": 118,
                "provenance_json": {
                    "llm": {
                        "model_parameters": {
                            "model_name": "gpt-4.1-mini",
                            "provider": "openai",
                            "temperature": None,
                            "reasoning_effort": None,
                            "verbosity": None,
                            "parameter_semantics": {
                                "temperature": {"mode": "model_default"},
                                "top_p": {"mode": "model_default"},
                                "reasoning_effort": {"mode": "model_default"},
                                "verbosity": {"mode": "model_default"},
                            },
                        }
                    }
                },
            }
        }
    )

    attempt_no: int
    status: str | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    requested_model: str | None = None
    response_model: str | None = None
    provider: str | None = None
    finish_reason: str | None = None
    provider_response_id: str | None = None
    num_tokens_input: int | None = None
    num_tokens_output: int | None = None
    provenance_json: dict[str, Any] | None = None


class FlowRunDebugStep(BaseModel):
    step_id: str | None = None
    step_order: int | None = None
    assistant_id: str | None = None
    io_types: FlowRunDebugIoTypes
    input: FlowRunDebugInput
    output: FlowRunDebugOutput
    mcp: FlowRunDebugMcp
    rag: FlowRunDebugRag | None = None
    attempts: list[FlowRunDebugAttempt] = Field(
        default_factory=lambda: cast(list[FlowRunDebugAttempt], [])
    )


class FlowRunDebugRunSummary(BaseModel):
    steps_count: int
    completed_steps: int
    failed_steps: int
    attempts_count: int
    artifacts_count: int
    duration_ms: int | None = None
    models_used: list[str] = Field(default_factory=list)
    token_usage: FlowRunTokenUsagePublic | None = None


class FlowRunDebugRun(BaseModel):
    run_id: str
    flow_id: str
    flow_version: int
    trace_id: str | None = None
    status: str
    summary: FlowRunDebugRunSummary | None = None


class FlowRunDebugDefinition(BaseModel):
    flow_id: str
    version: int
    checksum: str
    steps_count: int


class FlowRunDebugSecurity(BaseModel):
    redaction_applied: bool
    classification_field: str
    mcp_policy_field: str
    masked_fields_count: int | None = None


class FlowRunDebugExport(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "schema_version": "eneo.flow.debug-export.v2",
                "generated_at": "2026-03-31T12:00:00Z",
                "run": {
                    "run_id": "a8f5f167-f44f-4d5b-9c06-8ef0db6d7f3b",
                    "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
                    "flow_version": 3,
                    "trace_id": "52907745-7678-40a8-9d1c-18af6b1a9fd8",
                    "status": "completed",
                    "summary": {
                        "steps_count": 1,
                        "completed_steps": 1,
                        "failed_steps": 0,
                        "attempts_count": 1,
                        "artifacts_count": 0,
                        "duration_ms": 5240,
                        "models_used": ["gpt-4.1-mini"],
                    },
                },
                "definition": {
                    "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
                    "version": 3,
                    "checksum": "sha256:example",
                    "steps_count": 1,
                },
                "definition_snapshot": {"steps": []},
                "steps": [],
                "security": {
                    "redaction_applied": True,
                    "classification_field": "output_classification_override",
                    "mcp_policy_field": "mcp_policy",
                    "masked_fields_count": 2,
                },
            }
        }
    )

    schema_version: str
    generated_at: datetime
    run: FlowRunDebugRun
    definition: FlowRunDebugDefinition
    definition_snapshot: dict[str, Any]
    steps: list[FlowRunDebugStep]
    security: FlowRunDebugSecurity


FLOW_RUN_DEBUG_EXPORT_EXAMPLE: dict[str, Any] = {
    "schema_version": "eneo.flow.debug-export.v2",
    "generated_at": "2026-03-31T12:00:00Z",
    "run": {
        "run_id": "a8f5f167-f44f-4d5b-9c06-8ef0db6d7f3b",
        "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
        "flow_version": 3,
        "trace_id": "52907745-7678-40a8-9d1c-18af6b1a9fd8",
        "status": "completed",
        "summary": {
            "steps_count": 1,
            "completed_steps": 1,
            "failed_steps": 0,
            "attempts_count": 1,
            "artifacts_count": 0,
            "duration_ms": 5240,
            "models_used": ["gpt-4.1-mini"],
        },
    },
    "definition": {
        "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
        "version": 3,
        "checksum": "sha256:example",
        "steps_count": 1,
    },
    "definition_snapshot": {"steps": []},
    "steps": [],
    "security": {
        "redaction_applied": True,
        "classification_field": "output_classification_override",
        "mcp_policy_field": "mcp_policy",
        "masked_fields_count": 2,
    },
}


FLOW_RUN_RESULT_FILE_EXAMPLE: dict[str, Any] = {
    "flow_run_id": "a8f5f167-f44f-4d5b-9c06-8ef0db6d7f3b",
    "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
    "tenant_id": "1f73af48-76fb-4a26-85ee-17f20b722808",
    "step_result_id": "00000000-0000-0000-0000-000000000401",
    "step_id": "00000000-0000-0000-0000-000000000101",
    "step_order": 1,
    "attempt_no": 1,
    "file_id": "00000000-0000-0000-0000-000000000501",
    "ordinal": 0,
    "source": "declared_artifact",
    "name": "case-summary.pdf",
    "checksum": "artifact-checksum",
    "size": 14012,
    "mimetype": "application/pdf",
    "file_type": "document",
    "availability": "available",
}


class FlowRunRerunStepInputOverridePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    step_id: UUID = Field(
        description="Root step whose runtime input files were explicitly replaced or cleared by the rerun request."
    )
    file_ids: list[UUID] = Field(
        description=(
            "Runtime file IDs stored for the rerun root attempt. An empty list "
            "means the rerun explicitly cleared the root step files."
        )
    )


class FlowRunRerunOperationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    rerun_step_id: UUID
    rerun_step_order: int
    root_attempt_no: int
    root_attempt_id: UUID | None = None
    status: FlowRunRerunOperationStatus
    request_fingerprint: str = Field(
        description=(
            "Stable fingerprint that correlates repeated rerun requests with "
            "the accepted operation and invalidation lineage."
        )
    )
    expected_run_revision: int
    accepted_run_revision: int
    reason: str
    input_payload: dict[str, Any] | None = Field(
        default=None,
        description="Inline rerun input payload recorded at rerun acceptance time.",
    )
    root_step_input_override: FlowRunRerunStepInputOverridePublic | None = Field(
        default=None,
        description=(
            "Root-step runtime file override recorded at rerun acceptance time. "
            "Null means files were inherited from the predecessor attempt."
        ),
    )
    root_step_input_override_requested: bool = Field(
        description=(
            "True when the rerun request explicitly replaced or cleared root "
            "step runtime files; false when the root attempt inherits files "
            "from its predecessor."
        )
    )
    requested_by_principal_type: PrincipalType
    requested_by_user_id: UUID | None = None
    requested_by_service_principal: FlowServicePrincipalActorPublic | None = None
    failure_code: NullablePublicTerminalErrorCode = Field(
        default=None,
        description="Stable machine-readable rerun failure code.",
    )
    failure_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def project_public_payload(cls, value: Any) -> Any:
        payload = _flow_run_rerun_operation_public_payload(
            value,
            field_names=tuple(cls.model_fields),
        )
        if payload is None:
            return value

        if "input_payload" not in payload:
            payload["input_payload"] = payload.get("input_payload_json")

        payload.pop("input_payload_json", None)
        return payload

    @model_validator(mode="after")
    def validate_requested_by_actor(self) -> Self:
        if self.root_step_input_override_requested != (
            self.root_step_input_override is not None
        ):
            raise ValueError(
                "root_step_input_override must be present exactly when "
                "root_step_input_override_requested is true."
            )
        _validate_public_principal_actor_shape(
            label="requested_by",
            principal_type=self.requested_by_principal_type,
            user_id=self.requested_by_user_id,
            service_principal=self.requested_by_service_principal,
            required=True,
        )
        return self


def _flow_run_rerun_operation_public_payload(
    value: Any,
    *,
    field_names: tuple[str, ...],
) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(cast(Mapping[str, Any], value))

    payload = {
        field_name: getattr(value, field_name)
        for field_name in field_names
        if hasattr(value, field_name)
    }
    if hasattr(value, "input_payload_json"):
        payload["input_payload_json"] = getattr(value, "input_payload_json")
    return payload or None


class FlowRunRerunInvalidatedStepPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    operation_id: UUID
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    step_id: UUID
    step_order: int
    invalidation_order: int
    role: FlowRunRerunInvalidationRole
    dependency_sources_json: list[RerunDependencyKind]
    prior_step_result_id: UUID | None = None
    prior_attempt_id: UUID | None = None
    new_attempt_no: int | None = None
    new_attempt_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class FlowStepAttemptPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    flow_run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    step_id: UUID
    step_order: int
    attempt_no: int
    rerun_operation_id: UUID | None = None
    predecessor_attempt_id: UUID | None = None
    superseded_by_attempt_id: UUID | None = None
    celery_task_id: str | None = None
    status: FlowStepAttemptStatus
    error_code: NullablePublicTerminalErrorCode = Field(
        default=None,
        description="Stable machine-readable attempt failure code.",
    )
    error_message: str | None = None
    requested_model: str | None = None
    response_model: str | None = None
    provider: str | None = None
    finish_reason: str | None = None
    provider_response_id: str | None = None
    num_tokens_input: int | None = None
    num_tokens_output: int | None = None
    provenance_json: dict[str, Any] | None = None
    started_at: datetime
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class FlowRunReviewCheckpointEvidencePublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_RUN_REVIEW_CHECKPOINT_EVIDENCE_EXAMPLE}
    )

    id: UUID
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    step_id: UUID
    step_order: int
    attempt_no: int
    state: FlowRunReviewCheckpointState
    revision: int
    schema_version: int
    original_payload_json: dict[str, Any] | None = None
    current_payload_json: dict[str, Any] | None = None
    step_label: str | None = Field(
        default=None,
        description=(
            "Immutable snapshot of the reviewed step label. Null when the step had no label."
        ),
    )
    review_mode: FlowStepReviewMode = Field(
        description="Immutable snapshot of the reviewed step's review mode.",
    )
    output_type: FlowOutputType = Field(
        description="Immutable snapshot of the reviewed step's output type.",
    )
    output_contract: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Immutable snapshot of the reviewed step's output contract. Null means "
            "the step had no output contract."
        ),
    )
    decision: Literal["approved", "rejected", "cancelled"] | None = None
    next_step_ids: list[UUID] | None = None
    resume_key_present: bool
    # Evidence is tenant/run-authorized, so reviewer IDs follow run ownership exposure.
    requester_user_id: UUID | None = None
    requester_service_principal: FlowServicePrincipalActorPublic | None = None
    requester_principal_type: PrincipalType
    decided_by_user_id: UUID | None = None
    decided_by_service_principal: FlowServicePrincipalActorPublic | None = None
    decided_by_principal_type: PrincipalType | None = None
    edited_at: datetime | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    resumed_at: datetime | None = None
    cancelled_at: datetime | None = None
    expires_at: datetime | None = None
    expired_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_principal_actors(self) -> Self:
        _validate_public_principal_actor_shape(
            label="requester",
            principal_type=self.requester_principal_type,
            user_id=self.requester_user_id,
            service_principal=self.requester_service_principal,
            required=True,
        )
        _validate_public_principal_actor_shape(
            label="decider",
            principal_type=self.decided_by_principal_type,
            user_id=self.decided_by_user_id,
            service_principal=self.decided_by_service_principal,
            required=False,
        )
        return self


class FlowRunEvidenceResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "run": FLOW_RUN_PUBLIC_EXAMPLE,
                "definition_snapshot": {"steps": []},
                "step_results": [FLOW_RUN_STEP_PUBLIC_EXAMPLE],
                "step_attempts": [],
                "result_files": [FLOW_RUN_RESULT_FILE_EXAMPLE],
                "rerun_operations": [],
                "rerun_invalidated_steps": [],
                "review_checkpoints": [FLOW_RUN_REVIEW_CHECKPOINT_EVIDENCE_EXAMPLE],
                "debug_export": FLOW_RUN_DEBUG_EXPORT_EXAMPLE,
            }
        }
    )

    run: FlowRunPublic
    definition_snapshot: dict[str, Any]
    step_results: list[FlowRunStepPublic]
    step_attempts: list[FlowStepAttemptPublic]
    result_files: list[FlowRunStepResultFile]
    rerun_operations: list[FlowRunRerunOperationPublic]
    rerun_invalidated_steps: list[FlowRunRerunInvalidatedStepPublic]
    review_checkpoints: list[FlowRunReviewCheckpointEvidencePublic]
    debug_export: FlowRunDebugExport


class FlowRunEvidenceExportResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "schema_version": "flow-evidence-export.v7",
                "generated_at": "2026-03-31T12:00:00Z",
                "content_hash": "8f434346648f6b96df89dda901c5176b10a6d83961fca71d1af7bc2f617f4a66",
                "manifest": {
                    "schema_version": "flow-evidence-export.v7",
                    "provenance_schema_version_min": "flow-attempt-provenance.v1",
                    "provenance_schema_version_current": "flow-attempt-provenance.v1",
                    "provenance_persisted_version_status": "not_tracked",
                    "run_id": "a8f5f167-f44f-4d5b-9c06-8ef0db6d7f3b",
                    "tenant_id": "1f73af48-76fb-4a26-85ee-17f20b722808",
                    "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
                    "trace_id": "52907745-7678-40a8-9d1c-18af6b1a9fd8",
                    "flow_version": 3,
                    "content_hash": "8f434346648f6b96df89dda901c5176b10a6d83961fca71d1af7bc2f617f4a66",
                    "content_hash_input": "redacted",
                    "exported_at": "2026-03-31T12:00:00Z",
                    "exported_by_user_id": "00000000-0000-0000-0000-000000000030",
                    "export_reason": "support_debug",
                    "detail_mode": "redacted",
                    "redaction_applied": True,
                    "masked_fields_count": 2,
                    "redaction_policy_version": "flow-evidence-redaction.v3",
                    "retention_state_summary": {
                        "tracking_state": "not_tracked",
                        "tombstone_count": 0,
                        "retention_purged_count": 0,
                        "artifact_content_purged_count": 0,
                        "redacted_for_deletion_count": 0,
                        "note": (
                            "No retention tombstones are present in this export; "
                            "rows purged before tombstone tracking remain "
                            "indistinguishable from never-tracked evidence."
                        ),
                    },
                    "artifact_availability_summary": {
                        "tracking_state": "tracked",
                        "artifact_count": 1,
                        "available_count": 1,
                        "content_purged_count": 0,
                        "total_size_bytes": 14012,
                        "artifacts": [FLOW_RUN_RESULT_FILE_EXAMPLE],
                        "note": "Artifact availability is derived from result-file rows joined to file metadata.",
                    },
                    "review_checkpoint_summary": {
                        "count": 1,
                        "by_state": {
                            "awaiting_review": 0,
                            "edited": 0,
                            "approved": 0,
                            "rejected": 0,
                            "resumed": 1,
                            "cancelled": 0,
                            "expired": 0,
                        },
                        "any_edited": True,
                        "any_resumed": True,
                        "active_checkpoint_id": None,
                        "active_checkpoint_conflict": False,
                    },
                },
                "summary": {
                    "status": "completed",
                    "trace_id": "52907745-7678-40a8-9d1c-18af6b1a9fd8",
                    "steps_count": 1,
                    "completed_steps": 1,
                    "failed_steps": 0,
                    "attempts_count": 1,
                    "artifacts_count": 1,
                    "artifact_names": ["case-summary.pdf"],
                    "artifact_details": [
                        {
                            "flow_run_id": "a8f5f167-f44f-4d5b-9c06-8ef0db6d7f3b",
                            "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
                            "tenant_id": "1f73af48-76fb-4a26-85ee-17f20b722808",
                            "file_id": "00000000-0000-0000-0000-000000000501",
                            "step_id": "00000000-0000-0000-0000-000000000101",
                            "step_result_id": "00000000-0000-0000-0000-000000000401",
                            "step_order": 1,
                            "attempt_no": 1,
                            "ordinal": 0,
                            "source": "declared_artifact",
                            "name": "case-summary.pdf",
                            "mimetype": "application/pdf",
                            "size": 14012,
                            "checksum": "artifact-checksum",
                            "file_type": "document",
                            "availability": "available",
                        }
                    ],
                    "duration_ms": 5240,
                    "models_used": ["gpt-4.1-mini"],
                    "rag_sources_count": 1,
                    "rag_source_names": ["Municipality policy guide"],
                    "rag_source_display_names": ["Municipality policy guide"],
                    "rag_sources": [
                        {
                            "id": "source-1",
                            "name": "Municipality policy guide",
                            "display_name": "Municipality policy guide",
                            "source_url": "https://example.se/policy-guide",
                            "source_kind": "website",
                            "source_container_kind": "website",
                            "source_container_name": "Municipality knowledge base",
                            "source_container_display_name": "Municipality knowledge base",
                            "source_container_id": "website-1",
                            "usage_state": "inserted_into_prompt",
                        }
                    ],
                    "rag_usage_tracking": {
                        "retrieval_tracked": True,
                        "prompt_context_inclusion_tracked": True,
                        "citation_tracked": False,
                        "material_influence_tracked": False,
                        "selection_basis": "semantic_search_ranked_chunks_grouped_by_source",
                        "note": (
                            "References record retrieved candidates and exact prompt inclusion. "
                            "Citations and material influence are not currently tracked."
                        ),
                    },
                    "citations": {
                        "tracking_mode": "inline_inref_sidecar",
                        "citation_tracked": True,
                        "cited_source_ids": ["source-1"],
                        "cited_source_count": 1,
                        "unknown_citation_ids": [],
                        "uncited_inserted_source_ids": [],
                    },
                    "rerun_lineage": {
                        "operations_count": 0,
                        "queued_operations_count": 0,
                        "running_operations_count": 0,
                        "completed_operations_count": 0,
                        "failed_operations_count": 0,
                        "cancelled_operations_count": 0,
                        "active_operations_count": 0,
                        "terminal_operations_count": 0,
                        "invalidated_steps_count": 0,
                        "completed_replacement_count": 0,
                    },
                    "review_checkpoints": {
                        "count": 1,
                        "by_state": {
                            "awaiting_review": 0,
                            "edited": 0,
                            "approved": 0,
                            "rejected": 0,
                            "resumed": 1,
                            "cancelled": 0,
                            "expired": 0,
                        },
                        "any_edited": True,
                        "any_resumed": True,
                        "active_checkpoint_id": None,
                        "active_checkpoint_conflict": False,
                    },
                    "final_output": {
                        "kind": "mixed",
                        "text_present": True,
                        "text_preview": {
                            "preview": "Decision support generated.",
                            "truncated": False,
                            "byte_size": 27,
                            "sha256": "69c2b1d5990f8f1cd6c9eaf0d6f20bc6f3ddc31a58496a49f4158a709c27a53d",
                        },
                        "structured_present": False,
                        "artifact_count": 1,
                        "artifact_names": ["case-summary.pdf"],
                        "artifact_details": [
                            {
                                "flow_run_id": "a8f5f167-f44f-4d5b-9c06-8ef0db6d7f3b",
                                "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
                                "tenant_id": "1f73af48-76fb-4a26-85ee-17f20b722808",
                                "file_id": "00000000-0000-0000-0000-000000000501",
                                "step_id": "00000000-0000-0000-0000-000000000101",
                                "step_result_id": "00000000-0000-0000-0000-000000000401",
                                "step_order": 1,
                                "attempt_no": 1,
                                "ordinal": 0,
                                "source": "declared_artifact",
                                "name": "case-summary.pdf",
                                "mimetype": "application/pdf",
                                "size": 14012,
                                "checksum": "artifact-checksum",
                                "file_type": "document",
                                "availability": "available",
                            }
                        ],
                    },
                    "step_overview": [
                        {
                            "step_order": 1,
                            "step_id": "step-1",
                            "user_description": "Draft the decision support summary",
                            "status": "completed",
                            "attempts_count": 1,
                            "retries": 0,
                            "duration_ms": 5240,
                            "models_used": ["gpt-4.1-mini"],
                            "knowledge_sources_count": 1,
                            "knowledge_usage_state": "inserted_into_prompt",
                            "knowledge_retrieval": {
                                "status": "success",
                                "attempted": True,
                                "retrieval_duration_ms": 182,
                                "unique_sources": 1,
                                "references_truncated": False,
                                "reference_metadata_status": "success",
                                "retrieval_error_type": None,
                                "error_code": None,
                                "source_names": ["Municipality policy guide"],
                                "source_display_names": ["Municipality policy guide"],
                                "prompt_context": {
                                    "tracked": True,
                                    "included_source_count": 1,
                                    "not_included_source_count": 0,
                                    "included_chunk_count": 2,
                                    "knowledge_tokens": 248,
                                    "truncated_by_token_budget": False,
                                    "included_source_ids": ["source-1"],
                                    "included_source_titles": [
                                        "Municipality policy guide"
                                    ],
                                    "included_source_display_names": [
                                        "Municipality policy guide"
                                    ],
                                    "summary": {
                                        "total_sources": 1,
                                        "total_chunks": 2,
                                        "truncated_by_token_budget": False,
                                        "top_ranked_sources": [
                                            {
                                                "source_id": "source-1",
                                                "display_name": "Municipality policy guide",
                                                "source_kind": "website",
                                                "included_group_count": 1,
                                                "included_chunk_count": 2,
                                                "best_score": 0.91,
                                                "rank": 1,
                                            }
                                        ],
                                    },
                                },
                            },
                            "citations": {
                                "tracking_mode": "inline_inref_sidecar",
                                "citation_tracked": True,
                                "cited_source_ids": ["source-1"],
                                "cited_source_count": 1,
                                "unknown_citation_ids": [],
                                "uncited_inserted_source_ids": [],
                            },
                            "artifact_names": ["case-summary.pdf"],
                            "artifact_details": [
                                {
                                    "flow_run_id": "a8f5f167-f44f-4d5b-9c06-8ef0db6d7f3b",
                                    "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
                                    "tenant_id": "1f73af48-76fb-4a26-85ee-17f20b722808",
                                    "file_id": "00000000-0000-0000-0000-000000000501",
                                    "step_id": "00000000-0000-0000-0000-000000000101",
                                    "step_result_id": "00000000-0000-0000-0000-000000000401",
                                    "step_order": 1,
                                    "attempt_no": 1,
                                    "ordinal": 0,
                                    "source": "declared_artifact",
                                    "name": "case-summary.pdf",
                                    "mimetype": "application/pdf",
                                    "size": 14012,
                                    "checksum": "artifact-checksum",
                                    "file_type": "document",
                                    "availability": "available",
                                }
                            ],
                            "result_output_kind": "mixed",
                            "output_summary": {
                                "preview": "Decision support generated.",
                                "truncated": False,
                                "byte_size": 27,
                                "sha256": "69c2b1d5990f8f1cd6c9eaf0d6f20bc6f3ddc31a58496a49f4158a709c27a53d",
                            },
                            "input_lineage": {
                                "input_source": "previous_step",
                                "used_question_binding": True,
                                "uses_runtime_input": True,
                                "runtime_input_format": "document",
                                "runtime_file_count": 1,
                                "runtime_file_ids": ["file-1"],
                                "runtime_file_names": ["underlag.pdf"],
                                "runtime_file_checksums": ["input-checksum"],
                                "runtime_files": [
                                    {
                                        "id": "file-1",
                                        "name": "underlag.pdf",
                                        "checksum": "input-checksum",
                                        "size": 2048,
                                        "mimetype": "application/pdf",
                                        "file_type": "document",
                                        "text_length": 1024,
                                        "has_text": True,
                                        "has_transcription": False,
                                    }
                                ],
                                "question_binding_references_runtime_input": True,
                                "question_binding_expressions": [
                                    "step_1.output.text",
                                    "step_input.text",
                                ],
                                "upstream_step_orders": [1],
                                "upstream_step_labels": ["Collect the source document"],
                            },
                            "configured_input_type": "text",
                            "configured_output_type": "pdf",
                            "review_impact": {
                                "checkpoint_count": 1,
                                "any_edited": True,
                                "any_resumed": True,
                                "any_output_changed": True,
                                "last_event": {
                                    "checkpoint_id": "00000000-0000-0000-0000-000000000701",
                                    "state": "resumed",
                                    "decision": "approved",
                                    "edited": True,
                                    "resumed": True,
                                    "attempt_no": 1,
                                    "revision": 2,
                                    "output_changed": True,
                                },
                                "events": [
                                    {
                                        "checkpoint_id": "00000000-0000-0000-0000-000000000701",
                                        "state": "resumed",
                                        "decision": "approved",
                                        "edited": True,
                                        "resumed": True,
                                        "attempt_no": 1,
                                        "revision": 2,
                                        "output_changed": True,
                                    }
                                ],
                            },
                        }
                    ],
                },
                "redaction": {
                    "applied": True,
                    "policy_version": "flow-evidence-redaction.v3",
                    "masked_fields_count": 2,
                    "masked_paths": [
                        "bundle.run.input_payload_json.api_key",
                        "bundle.debug_export.definition_snapshot.steps[0].output_config.headers.Authorization",
                    ],
                    "masked_fields": [
                        {
                            "path": "bundle.run.input_payload_json.api_key",
                            "key": "api_key",
                            "reason": "sensitive_key",
                        }
                    ],
                },
                "bundle": {
                    "run": FLOW_RUN_PUBLIC_EXAMPLE,
                    "definition_snapshot": {"steps": []},
                    "step_results": [FLOW_RUN_STEP_PUBLIC_EXAMPLE],
                    "step_attempts": [],
                    "result_files": [FLOW_RUN_RESULT_FILE_EXAMPLE],
                    "review_checkpoints": [FLOW_RUN_REVIEW_CHECKPOINT_EVIDENCE_EXAMPLE],
                    "debug_export": FLOW_RUN_DEBUG_EXPORT_EXAMPLE,
                },
            }
        }
    )

    schema_version: Literal["flow-evidence-export.v7"]
    generated_at: datetime
    content_hash: str
    manifest: EvidenceExportManifest
    summary: EvidenceExportSummary
    redaction: dict[str, Any]
    bundle: dict[str, Any] = Field(
        description=(
            "Open evidence object preserved exactly as hashed; use "
            "FlowRunEvidenceResponse for the typed read-model endpoint."
        )
    )
