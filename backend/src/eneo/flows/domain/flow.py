from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Self, TypeAlias, cast
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from eneo.authentication.auth_models import ApiKeyPermission
from eneo.authentication.principal_types import PrincipalType
from eneo.flows.domain.flow_invariant_exceptions import FlowPersistedIdMissingError
from eneo.flows.domain.flow_run_retention_policy import FlowRunRetentionProjection
from eneo.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
    FlowRunReviewCheckpointState,
    FlowRunStatus,
    FlowRuntimeInputFormat,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    FlowTemplateAssetStatus,
    flow_output_mode_uses_completion_model,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from eneo.flows.flow_run_error import (
    FlowRunDispatchError,
    FlowRunError,
    parse_flow_run_dispatch_error,
    parse_flow_run_error,
)

# Flow domain models load persisted JSONB rows before each writer path has a
# strict serializer boundary. Tighten fields one by one at those chokepoints.
FlowPersistedJsonObject: TypeAlias = dict[str, Any]
RuntimeInputExecutionMode: TypeAlias = Literal["single_call", "per_source"]
FlowStepRetrievalPolicyMode: TypeAlias = Literal["best_effort", "fail_closed"]
FLOW_STEP_RETRIEVAL_POLICY_KEY = "retrieval_policy"


class FlowStepRetrievalPolicy(BaseModel):
    """Versioned policy embedded in the existing per-step output config JSON."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[1]
    mode: FlowStepRetrievalPolicyMode

    @field_validator("version", mode="before")
    @classmethod
    def _validate_version_is_integer(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("version must be the integer 1.")
        return value


def parse_flow_step_retrieval_policy(
    output_config: object,
    *,
    output_mode: FlowOutputMode | str | None = None,
) -> FlowStepRetrievalPolicy | None:
    if not isinstance(output_config, Mapping):
        return None
    raw_output_config = cast(Mapping[object, object], output_config)
    if FLOW_STEP_RETRIEVAL_POLICY_KEY not in raw_output_config:
        return None
    raw_policy: object = raw_output_config[FLOW_STEP_RETRIEVAL_POLICY_KEY]
    try:
        policy = FlowStepRetrievalPolicy.model_validate(raw_policy)
    except ValidationError as exc:
        raise ValueError("output_config.retrieval_policy is invalid.") from exc
    if output_mode is not None and not flow_output_mode_uses_completion_model(
        output_mode
    ):
        raise ValueError(
            "output_config.retrieval_policy is supported only for "
            "retrieval-plus-completion output modes ('pass_through', 'http_post')."
        )
    return policy


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

    @field_validator("output_config")
    @classmethod
    def _validate_retrieval_policy(
        cls, value: FlowPersistedJsonObject | None
    ) -> FlowPersistedJsonObject | None:
        parse_flow_step_retrieval_policy(value)
        return value


class FlowRuntimeInputConfig(BaseModel):
    enabled: StrictBool = False
    required: StrictBool = False
    max_files: Annotated[StrictInt, Field(gt=0)] | None = None
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
    run_history_retention: FlowRunRetentionProjection | None = None
    draft_revision: int = 0
    # Sparse list projection of `steps` (see `_derived_step_projection` in
    # infrastructure/flow_repo.py). Not auto-derived from `steps` — a
    # transient `model_copy(update={"steps": ...})` elsewhere must not be
    # trusted for these three fields until the repository recomputes them.
    step_count: int = 0
    input_type: FlowRuntimeInputFormat | None = None
    output_type: FlowOutputType | None = None
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
    dispatch_pending_since: Optional[datetime] = None
    dispatch_attempt_count: int = Field(default=0, ge=0)
    dispatch_last_attempt_at: Optional[datetime] = None
    dispatch_last_error: FlowRunDispatchError | None = None
    dispatch_next_attempt_at: Optional[datetime] = None
    dispatched_at: Optional[datetime] = None
    dispatch_exhausted_at: Optional[datetime] = None
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

    @field_validator("dispatch_last_error", mode="before")
    @classmethod
    def _parse_persisted_dispatch_error(
        cls, value: object
    ) -> FlowRunDispatchError | None:
        return parse_flow_run_dispatch_error(value)


class FlowRunTokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    num_tokens_input: int = Field(ge=0)
    num_tokens_output: int = Field(ge=0)
    num_tokens_total: int = Field(ge=0)
    input_completeness: Literal["complete", "incomplete"]
    output_completeness: Literal["complete", "incomplete"]

    @classmethod
    def from_counts(
        cls,
        *,
        num_tokens_input: int,
        num_tokens_output: int,
        input_completeness: Literal["complete", "incomplete"],
        output_completeness: Literal["complete", "incomplete"],
    ) -> Self:
        return cls(
            num_tokens_input=num_tokens_input,
            num_tokens_output=num_tokens_output,
            num_tokens_total=num_tokens_input + num_tokens_output,
            input_completeness=input_completeness,
            output_completeness=output_completeness,
        )

    @classmethod
    def from_provider_calls(
        cls,
        calls: Iterable["FlowProviderCallTokenUsage"],
    ) -> Self | None:
        contributing_calls = tuple(call for call in calls if call.status != "rejected")
        if not contributing_calls:
            return None
        return cls.from_counts(
            num_tokens_input=sum(
                call.num_tokens_input or 0 for call in contributing_calls
            ),
            num_tokens_output=sum(
                call.num_tokens_output or 0 for call in contributing_calls
            ),
            input_completeness=(
                "incomplete"
                if any(
                    call.status in {"started", "outcome_unknown"}
                    or call.input_source == "not_reported"
                    for call in contributing_calls
                )
                else "complete"
            ),
            output_completeness=(
                "incomplete"
                if any(
                    call.status in {"started", "outcome_unknown"}
                    or call.output_source == "not_reported"
                    for call in contributing_calls
                )
                else "complete"
            ),
        )

    @classmethod
    def combine(cls, usages: Iterable["FlowRunTokenUsage"]) -> Self | None:
        items = tuple(usages)
        if not items:
            return None
        return cls.from_counts(
            num_tokens_input=sum(item.num_tokens_input for item in items),
            num_tokens_output=sum(item.num_tokens_output for item in items),
            input_completeness=(
                "incomplete"
                if any(item.input_completeness == "incomplete" for item in items)
                else "complete"
            ),
            output_completeness=(
                "incomplete"
                if any(item.output_completeness == "incomplete" for item in items)
                else "complete"
            ),
        )

    @model_validator(mode="after")
    def _validate_total(self) -> Self:
        expected_total = self.num_tokens_input + self.num_tokens_output
        if self.num_tokens_total != expected_total:
            raise ValueError("num_tokens_total must equal input plus output tokens.")
        return self


class FlowRunTranscriptionUsage(BaseModel):
    """Audio a run sent to a transcription provider, across every attempt.

    A rejected request was answered and refused, so it contributes nothing. A
    request whose outcome is unknown may still have been charged, so it is left
    out of the total and marks it incomplete: the number is a lower bound, never
    a claim about what was billed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    audio_seconds: float = Field(ge=0)
    completeness: Literal["complete", "incomplete"]
    # Length of the audio the run's transcription steps read, as those steps
    # measured it. Distinct from ``audio_seconds``: a diarize-mode run sends the
    # same recording to two providers and counts it twice there.
    recording_seconds: float | None = Field(default=None, ge=0)

    def with_recording_seconds(self, seconds: float | None) -> Self:
        if seconds is None:
            return self
        return self.model_copy(update={"recording_seconds": round(seconds, 3)})

    @classmethod
    def from_counts(
        cls,
        *,
        audio_seconds: float,
        completeness: Literal["complete", "incomplete"],
    ) -> Self:
        return cls(audio_seconds=round(audio_seconds, 3), completeness=completeness)

    @classmethod
    def combine(cls, usages: Iterable["FlowRunTranscriptionUsage"]) -> Self | None:
        items = tuple(usages)
        if not items:
            return None
        return cls.from_counts(
            audio_seconds=sum(item.audio_seconds for item in items),
            completeness=(
                "incomplete"
                if any(item.completeness == "incomplete" for item in items)
                else "complete"
            ),
        )


@dataclass(frozen=True, slots=True)
class FlowProviderCallTokenUsage:
    status: Literal["started", "completed", "rejected", "outcome_unknown"]
    num_tokens_input: int | None
    num_tokens_output: int | None
    input_source: (
        Literal["provider", "estimated", "mixed", "not_reported", "not_applicable"]
        | None
    )
    output_source: (
        Literal["provider", "estimated", "mixed", "not_reported", "not_applicable"]
        | None
    )


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
    dispatch_task_id: Optional[str] = None
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
