from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, TypeAlias, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eneo.json_types import JsonObject

FLOW_STEP_ATTEMPT_INPUT_SCHEMA_VERSION: Literal["flow-step-attempt-input.v1"] = (
    "flow-step-attempt-input.v1"
)
FLOW_STEP_ATTEMPT_INPUT_MARKER_SCHEMA_VERSION: Literal[
    "flow-step-attempt-input-marker.v1"
] = "flow-step-attempt-input-marker.v1"


class _FlowStepAttemptInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


MappedExecutionMode: TypeAlias = Literal["per_item", "per_source_reader"]


class FlowStepAttemptMappedAdmission(_FlowStepAttemptInputModel):
    version: Literal[1] = 1
    execution_mode: MappedExecutionMode
    prospective_provider_calls: int = Field(ge=1)
    estimated_input_tokens: int = Field(ge=0)
    per_call_estimated_input_tokens: tuple[int, ...]
    max_estimated_input_tokens: int | None = Field(default=None, ge=1)
    policy_source: Literal["configured", "unset"]
    knowledge_included: Literal[False] = False

    @model_validator(mode="after")
    def _estimates_are_coherent(self) -> FlowStepAttemptMappedAdmission:
        if len(self.per_call_estimated_input_tokens) != self.prospective_provider_calls:
            raise ValueError(
                "mapped admission call count must match per-call estimates"
            )
        if any(value < 0 for value in self.per_call_estimated_input_tokens):
            raise ValueError("mapped admission estimates cannot be negative")
        if sum(self.per_call_estimated_input_tokens) != self.estimated_input_tokens:
            raise ValueError("mapped admission total must equal per-call estimates")
        if (self.max_estimated_input_tokens is None) != (self.policy_source == "unset"):
            raise ValueError("mapped admission policy source must match its ceiling")
        return self


class FlowStepAttemptStart(_FlowStepAttemptInputModel):
    requested_model: str | None = None
    provider: str | None = None
    resolved_timeout_seconds: int = Field(ge=1)
    input_text_length: int = Field(ge=0)
    input_tokens_estimate: int | None = Field(default=None, ge=0)
    mapped_admission: FlowStepAttemptMappedAdmission | None = None


class FlowStepAttemptCompletionConfiguration(_FlowStepAttemptInputModel):
    preferred_model_parameters: JsonObject
    capability_fallback_model_parameters: JsonObject | None = None


class FlowStepAttemptExecutionInput(_FlowStepAttemptInputModel):
    question: str
    effective_prompt: str
    assistant_context_version: int = Field(ge=1)


class FlowStepAttemptInput(_FlowStepAttemptInputModel):
    schema_version: Literal["flow-step-attempt-input.v1"] = (
        FLOW_STEP_ATTEMPT_INPUT_SCHEMA_VERSION
    )
    start: FlowStepAttemptStart | None = None
    resolved_input: JsonObject | None = None
    completion_configuration: FlowStepAttemptCompletionConfiguration | None = None
    execution_inputs: tuple[FlowStepAttemptExecutionInput, ...] | None = None

    @model_validator(mode="after")
    def _contains_attempt_input_evidence(self) -> FlowStepAttemptInput:
        if (
            self.start is None
            and self.resolved_input is None
            and self.completion_configuration is None
            and self.execution_inputs is None
        ):
            raise ValueError("attempt input must contain at least one tracked field")
        if self.execution_inputs is not None and not self.execution_inputs:
            raise ValueError("tracked execution inputs cannot be empty")
        if (self.completion_configuration is None) != (self.execution_inputs is None):
            raise ValueError(
                "completion configuration and execution inputs must be tracked together"
            )
        return self

    def to_payload(self) -> JsonObject:
        return cast(
            JsonObject,
            self.model_dump(mode="json", exclude_none=True),
        )


FlowStepAttemptInputParseStatus: TypeAlias = Literal[
    "not_tracked", "tracked", "corrupt"
]
FlowStepAttemptInputCorruptionCode: TypeAlias = Literal[
    "flow_step_attempt_input_invalid_type",
    "flow_step_attempt_input_schema_version_missing",
    "flow_step_attempt_input_schema_version_unsupported",
    "flow_step_attempt_input_unknown_top_level_keys",
    "flow_step_attempt_input_invalid_payload",
]


class FlowStepAttemptInputCorruptionMarker(_FlowStepAttemptInputModel):
    schema_version: Literal["flow-step-attempt-input-marker.v1"] = (
        FLOW_STEP_ATTEMPT_INPUT_MARKER_SCHEMA_VERSION
    )
    status: Literal["corrupt"] = "corrupt"
    error_code: FlowStepAttemptInputCorruptionCode
    message: str
    raw_value_type: str | None = None
    persisted_schema_version: str | None = None
    unknown_keys: tuple[str, ...] | None = None

    def to_payload(self) -> JsonObject:
        return cast(
            JsonObject,
            self.model_dump(mode="json", exclude_none=True),
        )


@dataclass(frozen=True, slots=True)
class FlowStepAttemptInputParseResult:
    status: FlowStepAttemptInputParseStatus
    attempt_input: FlowStepAttemptInput | None = None
    marker: FlowStepAttemptInputCorruptionMarker | None = None

    def __post_init__(self) -> None:
        if self.status == "tracked" and (
            self.attempt_input is None or self.marker is not None
        ):
            raise ValueError("Tracked attempt input requires an input envelope.")
        if self.status == "corrupt" and (
            self.marker is None or self.attempt_input is not None
        ):
            raise ValueError("Corrupt attempt input requires a corruption marker.")
        if self.status == "not_tracked" and (
            self.attempt_input is not None or self.marker is not None
        ):
            raise ValueError("Untracked attempt input cannot carry a value.")

    def to_export_payload(self) -> JsonObject | None:
        if self.attempt_input is not None:
            return self.attempt_input.to_payload()
        if self.marker is not None:
            return self.marker.to_payload()
        return None


class FlowStepAttemptInputWriteError(RuntimeError):
    def __init__(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        tenant_id: UUID,
        error_code: FlowStepAttemptInputCorruptionCode,
    ) -> None:
        self.run_id = run_id
        self.step_id = step_id
        self.attempt_no = attempt_no
        self.tenant_id = tenant_id
        self.error_code = error_code
        super().__init__(
            "Attempt input cannot be updated because persisted input is corrupt "
            f"(run_id={run_id}, step_id={step_id}, attempt_no={attempt_no}, "
            f"tenant_id={tenant_id}, error_code={error_code})."
        )


class FlowStepAttemptInputConflictError(RuntimeError):
    def __init__(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        tenant_id: UUID,
        field: str,
    ) -> None:
        self.run_id = run_id
        self.step_id = step_id
        self.attempt_no = attempt_no
        self.tenant_id = tenant_id
        self.field = field
        super().__init__(
            "Attempt input cannot change after it is recorded "
            f"(run_id={run_id}, step_id={step_id}, attempt_no={attempt_no}, "
            f"tenant_id={tenant_id}, field={field})."
        )


def parse_flow_step_attempt_input(raw: object) -> FlowStepAttemptInputParseResult:
    if raw is None:
        return FlowStepAttemptInputParseResult(status="not_tracked")
    if not isinstance(raw, dict):
        return _corrupt_attempt_input(
            error_code="flow_step_attempt_input_invalid_type",
            message="Attempt input must be a JSON object.",
            raw_value_type=type(raw).__name__,
        )

    raw_payload = cast(dict[str, object], raw)
    schema_version = raw_payload.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version:
        return _corrupt_attempt_input(
            error_code="flow_step_attempt_input_schema_version_missing",
            message="Attempt input is missing schema_version.",
        )
    if schema_version != FLOW_STEP_ATTEMPT_INPUT_SCHEMA_VERSION:
        return _corrupt_attempt_input(
            error_code="flow_step_attempt_input_schema_version_unsupported",
            message="Attempt input schema_version is not supported.",
            persisted_schema_version=schema_version,
        )

    unknown_keys = tuple(
        sorted(set(raw_payload) - set(FlowStepAttemptInput.model_fields))
    )
    if unknown_keys:
        return _corrupt_attempt_input(
            error_code="flow_step_attempt_input_unknown_top_level_keys",
            message="Attempt input contains unknown top-level keys.",
            persisted_schema_version=schema_version,
            unknown_keys=unknown_keys,
        )

    try:
        attempt_input = FlowStepAttemptInput.model_validate_json(
            json.dumps(raw_payload),
            strict=True,
        )
    except (TypeError, ValueError, ValidationError):
        return _corrupt_attempt_input(
            error_code="flow_step_attempt_input_invalid_payload",
            message="Attempt input failed current schema validation.",
            persisted_schema_version=schema_version,
        )
    return FlowStepAttemptInputParseResult(
        status="tracked",
        attempt_input=attempt_input,
    )


def merge_flow_step_attempt_input(
    raw_existing: object,
    incoming: FlowStepAttemptInput,
    *,
    run_id: UUID,
    step_id: UUID,
    attempt_no: int,
    tenant_id: UUID,
) -> FlowStepAttemptInput:
    parsed = parse_flow_step_attempt_input(raw_existing)
    if parsed.status == "corrupt":
        assert parsed.marker is not None
        raise FlowStepAttemptInputWriteError(
            run_id=run_id,
            step_id=step_id,
            attempt_no=attempt_no,
            tenant_id=tenant_id,
            error_code=parsed.marker.error_code,
        )
    if parsed.attempt_input is None:
        return incoming

    existing = parsed.attempt_input
    updates: dict[str, object] = {}
    for field in (
        "start",
        "resolved_input",
        "completion_configuration",
        "execution_inputs",
    ):
        existing_value = getattr(existing, field)
        incoming_value = getattr(incoming, field)
        if incoming_value is None:
            continue
        if existing_value is not None and existing_value != incoming_value:
            raise FlowStepAttemptInputConflictError(
                run_id=run_id,
                step_id=step_id,
                attempt_no=attempt_no,
                tenant_id=tenant_id,
                field=field,
            )
        updates[field] = incoming_value
    if not updates:
        return existing
    return existing.model_copy(update=updates)


def _corrupt_attempt_input(
    *,
    error_code: FlowStepAttemptInputCorruptionCode,
    message: str,
    raw_value_type: str | None = None,
    persisted_schema_version: str | None = None,
    unknown_keys: tuple[str, ...] | None = None,
) -> FlowStepAttemptInputParseResult:
    return FlowStepAttemptInputParseResult(
        status="corrupt",
        marker=FlowStepAttemptInputCorruptionMarker(
            error_code=error_code,
            message=message,
            raw_value_type=raw_value_type,
            persisted_schema_version=persisted_schema_version,
            unknown_keys=unknown_keys,
        ),
    )
