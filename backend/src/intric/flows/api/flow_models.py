from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.config import JsonDict

from intric.authentication.principal_types import PrincipalType
from intric.flows.enums import (
    FLOW_RUN_STATUS_CAPABILITIES,
    FLOW_RUN_STATUS_FILTER_ORDER,
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
    FlowTemplateAssetStatus,
    RerunDependencyKind,
)
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
from intric.flows.flow_run_error import FlowRunError
from intric.flows.flow_run_evidence_export_manifest import EvidenceExportManifest
from intric.flows.flow_run_evidence_export_summary import EvidenceExportSummary
from intric.flows.flow_run_step_result_file import FlowRunStepResultFile
from intric.main.exceptions import BadRequestException
from intric.main.models import NOT_PROVIDED, NotProvided, partial_model

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
    "metadata_json": {"category": "hr"},
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

FLOW_RUNTIME_PUBLIC_EXAMPLE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000001",
    "space_id": "00000000-0000-0000-0000-000000000020",
    "name": "Employee Review Summary",
    "description": "Transcribe a review conversation and return a PDF summary.",
    "published_version": 3,
    "created_at": "2026-03-17T09:30:00Z",
    "updated_at": "2026-03-17T10:00:00Z",
    "runtime_paths": {
        "run_contract": "/api/v1/flows/00000000-0000-0000-0000-000000000001/run-contract/",
        "graph": "/api/v1/flows/00000000-0000-0000-0000-000000000001/graph/",
        "upload_flow_file": "/api/v1/flows/00000000-0000-0000-0000-000000000001/files/",
        "upload_step_runtime_file_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/steps/{step_id}/runtime-files/",
        "create_run": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/",
        "list_runs": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/",
        "review_checkpoints": {
            "active_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/{run_id}/review-checkpoints/active/",
            "edit_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/{run_id}/review-checkpoints/{checkpoint_id}/",
            "approve_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/",
            "reject_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/",
            "resume_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/",
        },
        "get_graph_for_run_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/graph/?run_id={run_id}",
        "get_run_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/{run_id}/",
        "list_steps_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/{run_id}/steps/",
        "evidence_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/{run_id}/evidence/",
        "artifact_signed_url_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/{run_id}/artifacts/{file_id}/signed-url/",
    },
}


def _flow_run_status_capabilities_public_example() -> JsonDict:
    return {
        "statuses": [
            {
                "status": capability.status.value,
                "is_active": capability.is_active,
                "should_poll": capability.should_poll,
                "is_terminal": capability.is_terminal,
                "is_cancellable": capability.is_cancellable,
                "is_awaiting_review": capability.is_awaiting_review,
                "can_request_redispatch": capability.can_request_redispatch,
            }
            for capability in FLOW_RUN_STATUS_CAPABILITIES.values()
        ],
        "filter_order": [status.value for status in FLOW_RUN_STATUS_FILTER_ORDER],
    }


FLOW_RUN_STATUS_CAPABILITIES_PUBLIC_EXAMPLE = (
    _flow_run_status_capabilities_public_example()
)

FLOW_RUN_PUBLIC_EXAMPLE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000301",
    "flow_id": "00000000-0000-0000-0000-000000000001",
    "flow_version": 3,
    "user_id": "00000000-0000-0000-0000-000000000030",
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
            }
        ]
    },
    "output_payload_json": {"text": "Hello and welcome to the annual review..."},
    "result_files": [],
    "current_attempt_no": 1,
    "num_tokens_input": 0,
    "num_tokens_output": 0,
    "error_message": None,
    "diagnostics": [
        {"code": "runtime_input_consumed", "message": "Uploaded audio file was used."}
    ],
    "started_at": "2026-03-17T10:05:05Z",
    "finished_at": "2026-03-17T10:05:30Z",
    "created_at": "2026-03-17T10:05:05Z",
    "updated_at": "2026-03-17T10:05:30Z",
}

FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE: dict[str, Any] = {
    "asset_id": "00000000-0000-0000-0000-000000000601",
    "file_id": "00000000-0000-0000-0000-000000000602",
    "file_name": "ibic-template.docx",
    "placeholders": [
        {"name": "brukare_namn", "location": "body", "preview": "{{ brukare_namn }}"},
        {"name": "handlaggare", "location": "header", "preview": "{{ handlaggare }}"},
    ],
    "extracted_text_preview": "IBIC plan template with placeholders.",
    "status": "ready",
}

FLOW_TEMPLATE_ASSET_PUBLIC_EXAMPLE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000601",
    "flow_id": "00000000-0000-0000-0000-000000000001",
    "file_id": "00000000-0000-0000-0000-000000000602",
    "name": "ibic-template.docx",
    "checksum": "sha256:abc123",
    "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "placeholders": ["brukare_namn", "handlaggare"],
    "status": "ready",
    "last_updated_by_name": "Case Worker Admin",
    "can_edit": True,
    "can_download": True,
    "can_select": True,
    "can_inspect": True,
    "created_at": "2026-03-17T09:40:00Z",
    "updated_at": "2026-03-17T09:45:00Z",
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
    "step_snapshot_available": True,
    "output_contract": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
    },
    "next_step_ids": ["00000000-0000-0000-0000-000000000102"],
    "requester_user_id": "00000000-0000-0000-0000-000000000030",
    "requester_principal_type": "user",
    "decided_by_user_id": None,
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

GRAPH_RESPONSE_EXAMPLE: dict[str, Any] = {
    "nodes": [
        {"id": "step-1", "label": "Transcribe uploaded audio", "type": "step"},
        {"id": "step-2", "label": "Create PDF summary", "type": "step"},
    ],
    "edges": [
        {"source": "step-1", "target": "step-2"},
    ],
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

HTTP_TEST_REQUEST_EXAMPLE: dict[str, Any] = {
    "direction": "output",
    "method": "POST",
    "config": {
        "url": "https://webhook.example.com/eneo/flow-output",
        "auth": {"mode": "none"},
        "timeout_seconds": 10,
        "body": {
            "mode": "json_template",
            "template": '{"event":"flow.test","status":"ok"}',
        },
        "custom_headers": [{"name": "X-Eneo-Test", "value": "true", "secret": False}],
        "response_format": "json",
    },
    "test_variables": {},
}

HTTP_TEST_RESPONSE_EXAMPLE: dict[str, Any] = {
    "success": True,
    "status_code": 200,
    "duration_ms": 128.4,
    "response_preview": '{"ok":true}',
    "request_preview": {
        "method": "POST",
        "url": "https://webhook.example.com/eneo/flow-output",
        "headers": {"X-Eneo-Test": "true"},
        "body_preview": '{"event":"flow.test","status":"ok"}',
    },
    "error_code": None,
    "error_message": None,
}


class FlowStepCreateRequest(BaseModel):
    model_config = ConfigDict(
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
        }
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
        }
    )

    space_id: UUID
    name: str
    description: str | None = None
    steps: list[FlowStepCreateRequest]
    metadata_json: dict[str, Any] | None = None
    data_retention_days: int | None = None


@partial_model
class FlowUpdateRequest(BaseModel):
    model_config = ConfigDict(
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
                "metadata_json": {"category": "municipality-intake"},
                "data_retention_days": 30,
            }
        }
    )

    name: str
    description: str | None
    steps: list[FlowStepUpdateRequest]
    metadata_json: dict[str, Any] | None | NotProvided = Field(default=NOT_PROVIDED)
    data_retention_days: int | None | NotProvided = Field(default=NOT_PROVIDED)


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
    data_retention_days: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FlowPublic(FlowSparsePublic):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": FLOW_PUBLIC_EXAMPLE},
    )

    steps: list[FlowStepPublic]


class FlowReviewCheckpointRuntimePathsPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    active_template: str = Field(
        description=(
            "GET template for the active review checkpoint on a run. Replace "
            "`{run_id}` with the run id returned by create_run."
        )
    )
    edit_template: str = Field(
        description=(
            "PATCH template for submitting a full corrected checkpoint payload. "
            "Replace `{run_id}` and `{checkpoint_id}` with values returned by "
            "create_run and active checkpoint polling. Send "
            "`expected_checkpoint_revision` plus the full corrected "
            "`current_payload_json` field from the active checkpoint response."
        )
    )
    approve_template: str = Field(
        description=(
            "POST template for approving a checkpoint. Replace `{run_id}` and "
            "`{checkpoint_id}` with values returned by create_run and active "
            "checkpoint polling, and send `expected_checkpoint_revision` from "
            "the latest checkpoint response."
        )
    )
    reject_template: str = Field(
        description=(
            "POST template for rejecting a checkpoint. Replace `{run_id}` and "
            "`{checkpoint_id}` with values returned by create_run and active "
            "checkpoint polling, then send `expected_checkpoint_revision` and a "
            "rejection reason."
        )
    )
    resume_template: str = Field(
        description=(
            "POST template for resuming a run after checkpoint approval. Replace "
            "`{run_id}` and `{checkpoint_id}` with values returned by create_run "
            "and active checkpoint polling, then send the approved checkpoint "
            "`expected_checkpoint_revision`."
        )
    )


class FlowRuntimePathsPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_contract: str = Field(
        description=(
            "GET path for the published run contract. Call this before creating a "
            "run to discover required inputs, review checkpoints, final output "
            "delivery, and the published version to pin."
        )
    )
    graph: str = Field(
        description=(
            "GET path for the published flow graph. Add the optional `run_id` query "
            "parameter after run creation to enrich the graph with runtime state."
        )
    )
    upload_flow_file: str = Field(
        description=(
            "POST path for uploading flow-level runtime files before run creation. "
            "Send `multipart/form-data` with the binary file in the `upload_file` "
            "field; use the returned file id in the create-run payload."
        )
    )
    upload_step_runtime_file_template: str = Field(
        description=(
            "POST template for uploading files for a specific runtime step. Replace "
            "`{step_id}` with a step id from the run contract, then send "
            "`multipart/form-data` with the binary file in the `upload_file` field. "
            "Use the returned file id in `step_inputs[step_id].file_ids`."
        )
    )
    create_run: str = Field(
        description=(
            "POST path for creating a run. The returned run id is committed before "
            "`201 Created` is returned, so clients can immediately poll "
            "`get_run_template`."
        )
    )
    list_runs: str = Field(
        description=(
            "GET path for listing visible runs for this flow. Service keys list only "
            "runs created by the same key."
        )
    )
    review_checkpoints: FlowReviewCheckpointRuntimePathsPublic = Field(
        description=(
            "Review checkpoint path templates for human-in-loop clients. These "
            "templates let web apps discover active checkpoint, edit, approve, "
            "reject, and resume URLs before a run reaches awaiting_review."
        )
    )
    get_graph_for_run_template: str = Field(
        description=(
            "GET template for the run-enriched graph. Replace `{run_id}` with the "
            "id returned by create_run."
        )
    )
    get_run_template: str = Field(
        description=(
            "GET template for polling run status and top-level output. Replace "
            "`{run_id}` with the id returned by create_run."
        )
    )
    list_steps_template: str = Field(
        description=(
            "GET template for inspecting ordered step outputs and result files. "
            "Replace `{run_id}` with the id returned by create_run."
        )
    )
    evidence_template: str = Field(
        description=(
            "GET template for rich run evidence. Service keys need explicit "
            "`resource_permissions.flow_evidence` and can inspect only their own "
            "runs."
        )
    )
    artifact_signed_url_template: str = Field(
        description=(
            "POST template for generating a signed artifact download URL. Replace "
            "`{run_id}` and `{file_id}` with values from run or step result files "
            "and send a SignedURLRequest body."
        )
    )


class FlowRuntimePublic(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": FLOW_RUNTIME_PUBLIC_EXAMPLE},
    )

    id: UUID
    space_id: UUID
    name: str
    description: str | None = None
    published_version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    runtime_paths: FlowRuntimePathsPublic


class StepRunInput(BaseModel):
    file_ids: list[UUID] = Field(
        default_factory=lambda: cast(list[UUID], []),
        description=(
            "Uploaded file ids to attach to this specific step. Use the step ids "
            "from `GET /api/v1/flows/{id}/run-contract/` rather than sending all "
            "files to the first step."
        ),
    )


class FlowRunCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "expected_flow_version": 7,
                "input_payload_json": {
                    "text": "optional context for downstream prompt steps"
                },
                "step_inputs": {
                    "00000000-0000-0000-0000-000000000003": {
                        "file_ids": ["00000000-0000-0000-0000-000000000004"]
                    }
                },
            }
        }
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
                code="flow_run_top_level_file_ids_not_supported",
                context={
                    "invalid_field": "file_ids",
                    "expected_field": "step_inputs[step_id].file_ids",
                    "contract_endpoint": "/api/v1/flows/{id}/run-contract/",
                },
            )
        return cast(object, data)


class FlowAssistantCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"name": "Flow Step Assistant"}}
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


class FlowRunStatusCapabilityPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: FlowRunStatus = Field(
        description="Flow run status value this capability row describes."
    )
    is_active: bool = Field(
        description=(
            "True for statuses where the worker is expected to continue execution "
            "without waiting for human review."
        )
    )
    should_poll: bool = Field(
        description=(
            "True for statuses where client applications should continue polling "
            "for the next run state. Includes `awaiting_review` so review UIs can "
            "detect edits, approvals, expiries, and resumes."
        )
    )
    is_terminal: bool = Field(
        description=(
            "True when the run lifecycle is complete and normal polling can stop."
        )
    )
    is_cancellable: bool = Field(
        description=(
            "True when the cancel endpoint "
            "`POST /flows/{id}/runs/{run_id}/cancel/` is valid."
        )
    )
    is_awaiting_review: bool = Field(
        description=(
            "True only for `awaiting_review`, where clients should load the active "
            "review checkpoint before resuming the run."
        )
    )
    can_request_redispatch: bool = Field(
        description=(
            "True when clients may show a redispatch action for this status. "
            "Redispatch is still server-gated by staleness; a queued run that is "
            "not stale returns `redispatched_count: 0`."
        )
    )


class FlowRunStatusCapabilitiesPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_RUN_STATUS_CAPABILITIES_PUBLIC_EXAMPLE}
    )

    statuses: list[FlowRunStatusCapabilityPublic] = Field(
        description=(
            "Canonical status capability table. API consumers should branch on "
            "these booleans instead of hard-coding status groups."
        )
    )
    filter_order: list[FlowRunStatus] = Field(
        description=(
            "Recommended status filter order for run-history UIs. Contains every "
            "FlowRunStatus exactly once."
        )
    )


def flow_run_status_capabilities_public() -> FlowRunStatusCapabilitiesPublic:
    return FlowRunStatusCapabilitiesPublic(
        statuses=[
            FlowRunStatusCapabilityPublic.model_validate(capability)
            for capability in FLOW_RUN_STATUS_CAPABILITIES.values()
        ],
        filter_order=list(FLOW_RUN_STATUS_FILTER_ORDER),
    )


class FlowRunPublic(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_extra={"example": FLOW_RUN_PUBLIC_EXAMPLE}
    )

    id: UUID
    flow_id: UUID
    flow_version: int
    principal_type: PrincipalType | None = None
    user_id: UUID | None = None
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
            "Immutable snapshot of the reviewed step label. Null when the step had "
            "no label or for legacy checkpoints created before step snapshots."
        ),
    )
    review_mode: FlowStepReviewMode | None = Field(
        default=None,
        description=(
            "Immutable snapshot of the reviewed step's review mode. Null only for "
            "legacy checkpoints created before step snapshots."
        ),
    )
    output_type: FlowOutputType | None = Field(
        default=None,
        description=(
            "Immutable snapshot of the reviewed step's output type. Null only for "
            "legacy checkpoints created before step snapshots."
        ),
    )
    step_snapshot_available: bool = Field(
        default=False,
        description=(
            "True when this checkpoint includes immutable step metadata needed by "
            "external review UIs. False only for legacy checkpoints created before "
            "step snapshots were persisted."
        ),
    )
    output_contract: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Immutable snapshot of the reviewed step's output contract. Null means "
            "the step had no output contract, or this is a legacy checkpoint where "
            "`step_snapshot_available` is false."
        ),
    )
    next_step_ids: list[UUID] | None = None
    requester_user_id: UUID | None = None
    requester_principal_type: PrincipalType
    decided_by_user_id: UUID | None = None
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
    output_payload_json: dict[str, Any] | None = None
    current_attempt_no: int | None = None
    result_files: list[FlowRunStepResultFile] = Field(
        default_factory=lambda: cast(list[FlowRunStepResultFile], [])
    )
    effective_prompt: str | None = None
    model_parameters_json: dict[str, Any] | None = None
    num_tokens_input: int | None = None
    num_tokens_output: int | None = None
    error_message: str | None = None
    flow_step_execution_hash: str | None = None
    diagnostics: list[dict[str, Any]] = Field(
        default_factory=lambda: cast(list[dict[str, Any]], [])
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
        description="Optional inline payload overrides for the rerun root step.",
    )
    step_inputs: dict[UUID, StepRunInput] | None = Field(
        default=None,
        description="Optional file inputs keyed by the rerun root step id.",
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


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    step_order: int | None = None
    input_source: str | None = None
    input_type: str | None = None
    output_type: str | None = None
    output_mode: str | None = None
    mcp_policy: str | None = None
    output_classification_override: int | None = None
    run_status: str | None = None
    num_tokens_input: int | None = None
    num_tokens_output: int | None = None
    error_message: str | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: str | None = None
    source_step_order: int | None = None
    target_step_order: int | None = None
    style: str | None = None
    label: str | None = None


class GraphResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": GRAPH_RESPONSE_EXAMPLE})

    nodes: list[GraphNode]
    edges: list[GraphEdge]


class HttpTestRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": HTTP_TEST_REQUEST_EXAMPLE})

    config: dict[str, Any]
    direction: Literal["input", "output"] = "output"
    method: str = "POST"
    test_variables: dict[str, Any] | None = None


class HttpTestResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": HTTP_TEST_RESPONSE_EXAMPLE})

    success: bool
    status_code: int | None = None
    duration_ms: float = 0.0
    response_preview: str | None = None
    request_preview: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


class FlowTemplatePlaceholderPublic(BaseModel):
    name: str
    location: str
    preview: str | None = None


class FlowTemplateInspectionPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE}
    )

    asset_id: UUID | None = None
    file_id: UUID
    file_name: str
    placeholders: list[FlowTemplatePlaceholderPublic]
    extracted_text_preview: str | None = None
    status: FlowTemplateAssetStatus | None = None


class FlowTemplateAssetPublic(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": FLOW_TEMPLATE_ASSET_PUBLIC_EXAMPLE},
    )

    id: UUID
    flow_id: UUID
    file_id: UUID
    name: str
    checksum: str
    mimetype: str | None = None
    placeholders: list[str] = Field(default_factory=list)
    status: FlowTemplateAssetStatus
    last_updated_by_name: str | None = None
    can_edit: bool = False
    can_download: bool = False
    can_select: bool = False
    can_inspect: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


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
    input_payload_json: dict[str, Any] | None = None
    step_inputs_json: dict[str, Any] | None = None
    requested_by_principal_type: PrincipalType
    requested_by_user_id: UUID
    failure_code: str | None = None
    failure_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


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
    error_code: str | None = None
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
            "Immutable snapshot of the reviewed step label. Null when the step had "
            "no label or for legacy checkpoints created before step snapshots."
        ),
    )
    review_mode: FlowStepReviewMode | None = Field(
        default=None,
        description=(
            "Immutable snapshot of the reviewed step's review mode. Null only for "
            "legacy checkpoints created before step snapshots."
        ),
    )
    output_type: FlowOutputType | None = Field(
        default=None,
        description=(
            "Immutable snapshot of the reviewed step's output type. Null only for "
            "legacy checkpoints created before step snapshots."
        ),
    )
    step_snapshot_available: bool = Field(
        default=False,
        description=(
            "True when this checkpoint includes immutable step metadata needed by "
            "external review UIs. False only for legacy checkpoints created before "
            "step snapshots were persisted."
        ),
    )
    output_contract: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Immutable snapshot of the reviewed step's output contract. Null means "
            "the step had no output contract, or this is a legacy checkpoint where "
            "`step_snapshot_available` is false."
        ),
    )
    decision: Literal["approved", "rejected", "cancelled"] | None = None
    next_step_ids: list[UUID] | None = None
    resume_key_present: bool
    # Evidence is tenant/run-authorized, so reviewer IDs follow run ownership exposure.
    requester_user_id: UUID | None = None
    requester_principal_type: PrincipalType
    decided_by_user_id: UUID | None = None
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
                "schema_version": "flow-evidence-export.v5",
                "generated_at": "2026-03-31T12:00:00Z",
                "content_hash": "8f434346648f6b96df89dda901c5176b10a6d83961fca71d1af7bc2f617f4a66",
                "manifest": {
                    "schema_version": "flow-evidence-export.v5",
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
                                "legacy_prompt_binding_used": False,
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
                        }
                    ],
                },
                "summary_typed": {
                    "status": "completed",
                    "trace_id": "52907745-7678-40a8-9d1c-18af6b1a9fd8",
                    "steps_count": 1,
                    "completed_steps": 1,
                    "failed_steps": 0,
                    "attempts_count": 1,
                    "artifacts_count": 1,
                    "duration_ms": 5240,
                    "models_used": ["gpt-4.1-mini"],
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
                            "artifact_names": ["case-summary.pdf"],
                            "result_output_kind": "mixed",
                            "output_summary": {
                                "preview": "Decision support generated.",
                                "truncated": False,
                                "byte_size": 27,
                                "sha256": "69c2b1d5990f8f1cd6c9eaf0d6f20bc6f3ddc31a58496a49f4158a709c27a53d",
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

    schema_version: str
    generated_at: datetime
    content_hash: str
    manifest: EvidenceExportManifest
    summary: dict[str, Any]
    summary_typed: EvidenceExportSummary = Field(
        description=(
            "Typed additive read-model for API consumers. It mirrors stable "
            "summary fields and adds per-step review impact while legacy "
            "summary remains available."
        )
    )
    redaction: dict[str, Any]
    bundle: dict[str, Any] = Field(
        description=(
            "Open evidence object preserved exactly as hashed; use "
            "FlowRunEvidenceResponse for the typed read-model endpoint."
        )
    )
