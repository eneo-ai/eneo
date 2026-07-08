from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Optional, Self, TypeAlias, cast
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from eneo.authentication.auth_models import ApiKeyPermission
from eneo.authentication.principal_types import PrincipalType
from eneo.flows.domain.flow_invariant_exceptions import FlowPersistedIdMissingError
from eneo.flows.enums import (
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
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from eneo.flows.flow_run_error import FlowRunError, parse_flow_run_error

# Flow domain models load persisted JSONB rows before each writer path has a
# strict serializer boundary. Tighten fields one by one at those chokepoints.
FlowPersistedJsonObject: TypeAlias = dict[str, Any]
RuntimeInputExecutionMode: TypeAlias = Literal["single_call", "per_source"]


@dataclass(frozen=True, slots=True)
class RerunStepInputOverride:
    step_id: UUID
    file_ids: tuple[UUID, ...]


def clone_json_object(value: object) -> FlowPersistedJsonObject | None:
    """Shallow-copy a mapping into a string-keyed JSON object."""
    if not isinstance(value, Mapping):
        return None
    cloned: FlowPersistedJsonObject = {}
    for key, item in cast(Mapping[object, object], value).items():
        if isinstance(key, str):
            cloned[key] = item
    return cloned


class FlowStep(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    flow_id: UUID | None = None
    tenant_id: UUID | None = None
    assistant_id: UUID
    step_order: int
    timeout_seconds: int | None = None
    user_description: Optional[str] = None
    input_source: FlowInputSource
    input_type: FlowInputType
    input_contract: FlowPersistedJsonObject | None = None
    output_mode: FlowOutputMode
    output_type: FlowOutputType
    output_contract: FlowPersistedJsonObject | None = None
    input_bindings: FlowPersistedJsonObject | None = None
    output_classification_override: Optional[int] = None
    mcp_policy: FlowMcpPolicy
    input_config: FlowPersistedJsonObject | None = None
    output_config: FlowPersistedJsonObject | None = None
    review_policy: FlowStepReviewPolicy | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

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


class FlowRuntimeInputConfig(BaseModel):
    enabled: StrictBool = False
    required: StrictBool = False
    max_files: StrictInt | None = None
    input_format: FlowRuntimeInputFormat = FlowRuntimeInputFormat.DOCUMENT
    execution_mode: RuntimeInputExecutionMode = "single_call"
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
    metadata_json: FlowPersistedJsonObject | None = None
    data_retention_days: Optional[int] = None
    draft_revision: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def published(self) -> bool:
        return self.published_version is not None

    def require_persisted_id(self) -> UUID:
        if self.id is None:
            raise FlowPersistedIdMissingError()
        return self.id


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
    definition_json: FlowPersistedJsonObject
    created_at: datetime
    updated_at: datetime


class FlowRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    flow_id: UUID
    flow_version: int
    principal_type: PrincipalType | None = None
    principal_user_id: Optional[UUID] = None
    principal_service_id: Optional[UUID] = None
    created_by_api_key_id: Optional[UUID] = None
    runtime_service_permission: ApiKeyPermission | None = None
    tenant_id: UUID
    trace_id: UUID
    revision: int = 1
    status: FlowRunStatus
    cancelled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    input_payload_json: FlowPersistedJsonObject | None = None
    output_payload_json: FlowPersistedJsonObject | None = None
    error: FlowRunError | None = Field(
        default=None,
        validation_alias=AliasChoices("error", "error_json"),
    )
    job_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("error", mode="before")
    @classmethod
    def _parse_persisted_error(cls, value: object) -> FlowRunError | None:
        return parse_flow_run_error(value)


class FlowRunTokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    num_tokens_input: int = Field(ge=0)
    num_tokens_output: int = Field(ge=0)
    num_tokens_total: int = Field(ge=0)

    @classmethod
    def from_counts(
        cls,
        *,
        num_tokens_input: int,
        num_tokens_output: int,
    ) -> Self:
        return cls(
            num_tokens_input=num_tokens_input,
            num_tokens_output=num_tokens_output,
            num_tokens_total=num_tokens_input + num_tokens_output,
        )

    @model_validator(mode="after")
    def _validate_total(self) -> Self:
        expected_total = self.num_tokens_input + self.num_tokens_output
        if self.num_tokens_total != expected_total:
            raise ValueError("num_tokens_total must equal input plus output tokens.")
        return self


class FlowStepResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    flow_run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    step_id: UUID
    step_order: int
    assistant_id: Optional[UUID] = None
    current_attempt_no: Optional[int] = None
    input_payload_json: FlowPersistedJsonObject | None = None
    effective_prompt: Optional[str] = None
    output_payload_json: FlowPersistedJsonObject | None = None
    model_parameters_json: FlowPersistedJsonObject | None = None
    num_tokens_input: Optional[int] = None
    num_tokens_output: Optional[int] = None
    status: FlowStepResultStatus
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    flow_step_execution_hash: Optional[str] = None
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
    step_id: UUID
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
    provenance_json: FlowPersistedJsonObject | None = None
    input_payload_json: FlowPersistedJsonObject | None = None
    output_payload_json: FlowPersistedJsonObject | None = None
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
    input_payload_json: FlowPersistedJsonObject | None = None
    root_step_input_override_requested: bool
    root_step_input_override: RerunStepInputOverride | None
    requested_by_principal_type: PrincipalType
    requested_by_user_id: UUID | None = None
    requested_by_service_id: UUID | None = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _validate_root_step_input_override(self) -> Self:
        if self.root_step_input_override_requested != (
            self.root_step_input_override is not None
        ):
            raise ValueError(
                "root_step_input_override must be present exactly when "
                "root_step_input_override_requested is true."
            )
        if (
            self.root_step_input_override is not None
            and self.root_step_input_override.step_id != self.rerun_step_id
        ):
            raise ValueError(
                "root_step_input_override.step_id must match rerun_step_id."
            )
        return self


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
    original_payload_json: FlowPersistedJsonObject | None = None
    current_payload_json: FlowPersistedJsonObject | None = None
    step_label: str | None = Field(
        default=None,
        description="Snapshot of the reviewed step's user-facing label.",
    )
    review_mode: FlowStepReviewMode = Field(
        description="Snapshot of the review mode configured on the reviewed step.",
    )
    output_type: FlowOutputType = Field(
        description="Snapshot of the reviewed step's output type.",
    )
    output_contract_json: FlowPersistedJsonObject | None = Field(
        default=None,
        description=(
            "Snapshot of FlowStep.output_contract at checkpoint creation. "
            "Null means the reviewed step had no output contract."
        ),
    )
    requester_user_id: UUID | None = None
    requester_service_id: UUID | None = None
    requester_principal_type: PrincipalType
    decided_by_user_id: UUID | None = None
    decided_by_service_id: UUID | None = None
    decided_by_principal_type: PrincipalType | None = None
    next_step_ids_json: list[UUID] | None = None
    resume_idempotency_key: str | None = None
    edited_at: datetime | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    resumed_at: datetime | None = None
    cancelled_at: datetime | None = None
    expires_at: datetime | None = None
    expired_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
