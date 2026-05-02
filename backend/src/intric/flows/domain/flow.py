from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from intric.authentication.principal_types import PrincipalType
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
    FlowRuntimeInputFormat,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    FlowTemplateAssetStatus,
    RerunDependencyKind,
)

JsonObject: TypeAlias = dict[str, Any]
ToolCallMetadata: TypeAlias = dict[str, Any]


class FlowStep(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    flow_id: UUID | None = None
    tenant_id: UUID | None = None
    assistant_id: UUID
    step_order: int
    user_description: Optional[str] = None
    input_source: FlowInputSource
    input_type: FlowInputType
    input_contract: JsonObject | None = None
    output_mode: FlowOutputMode
    output_type: FlowOutputType
    output_contract: JsonObject | None = None
    input_bindings: JsonObject | None = None
    output_classification_override: Optional[int] = None
    mcp_policy: FlowMcpPolicy
    input_config: JsonObject | None = None
    output_config: JsonObject | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FlowRuntimeInputConfig(BaseModel):
    enabled: bool = False
    required: bool = False
    max_files: int | None = None
    input_format: FlowRuntimeInputFormat = FlowRuntimeInputFormat.DOCUMENT
    accepted_mimetypes_override: list[str] | None = None
    label: str | None = None
    description: str | None = None


class FlowTemplateAsset(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    flow_id: UUID
    space_id: UUID
    tenant_id: UUID
    file_id: UUID
    name: str
    checksum: str
    mimetype: str | None = None
    placeholders: list[str] = Field(default_factory=list)
    created_by_user_id: UUID | None = None
    updated_by_user_id: UUID | None = None
    last_updated_by_name: str | None = None
    status: FlowTemplateAssetStatus = FlowTemplateAssetStatus.READY
    can_edit: bool = False
    can_download: bool = False
    can_select: bool = False
    can_inspect: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FlowSparse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    tenant_id: UUID
    space_id: UUID
    name: str
    description: Optional[str] = None
    created_by_user_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None
    published_version: Optional[int] = None
    metadata_json: JsonObject | None = None
    data_retention_days: Optional[int] = None
    draft_revision: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def published(self) -> bool:
        return self.published_version is not None


def _default_flow_steps() -> list[FlowStep]:
    return []


class Flow(FlowSparse):
    steps: list[FlowStep] = Field(default_factory=_default_flow_steps)


class FlowVersion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    flow_id: UUID
    version: int
    tenant_id: UUID
    definition_checksum: str
    definition_json: JsonObject
    created_at: datetime
    updated_at: datetime


class FlowRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    flow_id: UUID
    flow_version: int
    principal_type: PrincipalType | None = None
    principal_user_id: Optional[UUID] = None
    principal_api_key_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    tenant_id: UUID
    trace_id: UUID
    revision: int = 1
    status: FlowRunStatus
    cancelled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    input_payload_json: JsonObject | None = None
    output_payload_json: JsonObject | None = None
    error_message: Optional[str] = None
    job_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class FlowStepResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    flow_run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    step_id: Optional[UUID] = None
    step_order: int
    assistant_id: Optional[UUID] = None
    current_attempt_no: Optional[int] = None
    input_payload_json: JsonObject | None = None
    effective_prompt: Optional[str] = None
    output_payload_json: JsonObject | None = None
    model_parameters_json: JsonObject | None = None
    num_tokens_input: Optional[int] = None
    num_tokens_output: Optional[int] = None
    status: FlowStepResultStatus
    error_message: Optional[str] = None
    flow_step_execution_hash: Optional[str] = None
    tool_calls_metadata: list[ToolCallMetadata] | ToolCallMetadata | None = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class FlowStepAttempt(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    flow_run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    step_id: Optional[UUID] = None
    step_order: int
    attempt_no: int
    rerun_operation_id: Optional[UUID] = None
    predecessor_attempt_id: Optional[UUID] = None
    superseded_by_attempt_id: Optional[UUID] = None
    celery_task_id: Optional[str] = None
    status: FlowStepAttemptStatus
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    requested_model: Optional[str] = None
    response_model: Optional[str] = None
    provider: Optional[str] = None
    finish_reason: Optional[str] = None
    provider_response_id: Optional[str] = None
    num_tokens_input: Optional[int] = None
    num_tokens_output: Optional[int] = None
    provenance_json: JsonObject | None = None
    input_payload_json: JsonObject | None = None
    output_payload_json: JsonObject | None = None
    flow_step_execution_hash: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class FlowRunRerunOperation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    rerun_step_id: UUID
    rerun_step_order: int
    root_attempt_no: int
    root_attempt_id: Optional[UUID] = None
    status: FlowRunRerunOperationStatus
    request_fingerprint: str
    expected_run_revision: int
    accepted_run_revision: int
    reason: str
    input_payload_json: JsonObject | None = None
    step_inputs_json: JsonObject | None = None
    requested_by_principal_type: PrincipalType
    requested_by_user_id: UUID
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class FlowRunRerunInvalidatedStep(BaseModel):
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
    prior_step_result_id: Optional[UUID] = None
    prior_attempt_id: Optional[UUID] = None
    new_attempt_no: Optional[int] = None
    new_attempt_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class FlowRunReviewCheckpoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    step_id: UUID
    step_order: int
    attempt_no: int
    state: FlowRunReviewCheckpointState
    revision: int = 1
    schema_version: int = 1
    original_payload_json: JsonObject | None = None
    current_payload_json: JsonObject | None = None
    requester_user_id: UUID | None = None
    requester_principal_type: PrincipalType
    decided_by_user_id: UUID | None = None
    decided_by_principal_type: PrincipalType | None = None
    next_step_ids_json: list[UUID] | None = None
    resume_idempotency_key: str | None = None
    edited_at: datetime | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    resumed_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
