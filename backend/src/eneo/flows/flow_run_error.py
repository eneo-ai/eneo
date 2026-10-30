from __future__ import annotations

from collections.abc import Collection, Mapping
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias, cast
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    ValidationError,
    WithJsonSchema,
    computed_field,
    model_validator,
)

from eneo.flows.domain.flow_run_recovery_policy import (
    FlowRunAbandonmentWait,
    flow_run_abandonment_deadline,
)
from eneo.flows.domain.provider_call_evidence_gap import ProviderCallEvidenceGap
from eneo.flows.enums import FlowRunLifecycleSource, FlowStepPhase
from eneo.flows.flow_api_error_code import (
    FLOW_RUN_TERMINAL_ERROR_CODES,
    FLOW_RUN_TERMINAL_ERROR_RETRYABILITY,
    FlowApiErrorCode,
)
from eneo.flows.transcription_config import SpeakerServiceGap
from eneo.mcp_servers.domain.unattended_tool_refusal import UnattendedToolRefusal

FlowRunErrorJson: TypeAlias = dict[str, object]
FlowRunDispatchErrorJson: TypeAlias = dict[str, object]

ContractSide: TypeAlias = Literal["input", "output"]
# Invariant bounds shared with the producer (output_processing.validate_against_contract).
CONTRACT_VIOLATION_POINTER_MAX_LENGTH = 400
CONTRACT_VIOLATION_RULE_MAX_LENGTH = 80
_MAX_STEP_DESCRIPTION_LENGTH = 256
_MAX_MESSAGE_LENGTH = 4096
TRANSCRIPTION_SERVICE_REASON_MAX_LENGTH = 512
TOOL_ERROR_TEXT_MAX_LENGTH = 512
_MESSAGE_TRUNCATION_SUFFIX = "... [truncated]"
_INVALID_PERSISTED_ERROR_MESSAGE = "Persisted flow run error payload is invalid."
_INVALID_PERSISTED_DISPATCH_ERROR_MESSAGE = (
    "Persisted Flow run dispatch error payload is invalid."
)
_CODE_DESCRIPTION = "Stable machine-readable run error code."
_TERMINAL_ERROR_CODE_VALUES = tuple(
    sorted(code.value for code in FLOW_RUN_TERMINAL_ERROR_CODES)
)


class FlowRunDispatchErrorKind(StrEnum):
    INVALID_REQUEST = "invalid_request"
    EXECUTION_BACKEND_FAILURE = "execution_backend_failure"
    INVALID_PERSISTED_ERROR = "invalid_persisted_error"


FlowRunDispatchErrorCode: TypeAlias = Literal[
    FlowApiErrorCode.RUN_DISPATCH_FAILED,
    FlowApiErrorCode.RUN_MISSING_PRINCIPAL,
]

_DISPATCH_ERROR_SHAPES: dict[
    FlowRunDispatchErrorKind,
    tuple[FlowRunDispatchErrorCode, bool, str],
] = {
    FlowRunDispatchErrorKind.INVALID_REQUEST: (
        FlowApiErrorCode.RUN_MISSING_PRINCIPAL,
        False,
        "Flow run dispatch requires a valid execution principal.",
    ),
    FlowRunDispatchErrorKind.EXECUTION_BACKEND_FAILURE: (
        FlowApiErrorCode.RUN_DISPATCH_FAILED,
        True,
        "The execution backend did not accept the Flow run dispatch attempt.",
    ),
    FlowRunDispatchErrorKind.INVALID_PERSISTED_ERROR: (
        FlowApiErrorCode.RUN_DISPATCH_FAILED,
        False,
        _INVALID_PERSISTED_DISPATCH_ERROR_MESSAGE,
    ),
}


class FlowRunDispatchError(BaseModel):
    """Small secret-free diagnosis for the current dispatch epoch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    kind: FlowRunDispatchErrorKind
    code: FlowRunDispatchErrorCode
    retryable: bool = Field(
        description=(
            "Whether internal recovery may retry the current dispatch epoch before "
            "terminalization. This does not automatically start work."
        )
    )
    message: str = Field(
        min_length=1,
        max_length=512,
        description=(
            "Fixed safe diagnosis selected by `kind`; never a raw broker or "
            "provider exception."
        ),
    )

    @model_validator(mode="after")
    def _require_canonical_shape(self) -> FlowRunDispatchError:
        expected_code, expected_retryable, expected_message = _DISPATCH_ERROR_SHAPES[
            self.kind
        ]
        if (
            self.code != expected_code
            or self.retryable is not expected_retryable
            or self.message != expected_message
        ):
            raise ValueError("Flow run dispatch error fields do not match its kind.")
        return self

    @classmethod
    def from_kind(cls, kind: FlowRunDispatchErrorKind) -> FlowRunDispatchError:
        code, retryable, message = _DISPATCH_ERROR_SHAPES[kind]
        return cls(
            kind=kind,
            code=code,
            retryable=retryable,
            message=message,
        )


def _ensure_terminal_run_error_code(code: FlowApiErrorCode) -> FlowApiErrorCode:
    if code not in FLOW_RUN_TERMINAL_ERROR_CODES:
        raise ValueError("Flow run error code must be a terminal run error code.")
    return code


FlowRunTerminalErrorCode: TypeAlias = Annotated[
    FlowApiErrorCode,
    AfterValidator(_ensure_terminal_run_error_code),
    WithJsonSchema(
        {
            "type": "string",
            "enum": list(_TERMINAL_ERROR_CODE_VALUES),
            "description": _CODE_DESCRIPTION,
        }
    ),
]


def _coerce_nullable_public_terminal_error_code(
    value: object,
) -> FlowApiErrorCode | None:
    # Public reads degrade stale persisted codes instead of raising API 500s.
    if value is None:
        return None
    if isinstance(value, FlowApiErrorCode):
        code = value
    elif isinstance(value, str):
        try:
            code = FlowApiErrorCode(value)
        except ValueError:
            return FlowApiErrorCode.RUN_ERROR_PAYLOAD_INVALID
    else:
        return FlowApiErrorCode.RUN_ERROR_PAYLOAD_INVALID
    if code in FLOW_RUN_TERMINAL_ERROR_CODES:
        return code
    return FlowApiErrorCode.RUN_ERROR_PAYLOAD_INVALID


NullablePublicTerminalErrorCode: TypeAlias = Annotated[
    FlowApiErrorCode | None,
    BeforeValidator(_coerce_nullable_public_terminal_error_code),
    WithJsonSchema(
        {
            "anyOf": [
                {
                    "type": "string",
                    "enum": list(_TERMINAL_ERROR_CODE_VALUES),
                },
                {"type": "null"},
            ],
        }
    ),
]


class TranscriptionFailureKind(StrEnum):
    INPUT = "input"
    CAPACITY = "capacity"
    PROVIDER = "provider"
    INTERNAL = "internal"
    CANCELLED = "cancelled"


class FlowRunRecoveryFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: Literal["execution_heartbeat_expired"]
    heartbeat_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def _validate_deadline(self) -> FlowRunRecoveryFacts:
        if self.expires_at <= self.heartbeat_at:
            raise ValueError("Recovery expiry must follow the execution heartbeat.")
        return self


class FlowRunAbandonmentFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    wait: FlowRunAbandonmentWait
    anchor_at: AwareDatetime
    deadline: AwareDatetime
    checkpoint_id: UUID | None = None

    @model_validator(mode="after")
    def _validate_wait(self) -> FlowRunAbandonmentFacts:
        if self.deadline != flow_run_abandonment_deadline(self.anchor_at):
            raise ValueError("Abandonment deadline must follow the shared wait policy.")
        if (self.wait == FlowRunAbandonmentWait.APPROVED_REVIEW) != (
            self.checkpoint_id is not None
        ):
            raise ValueError("Only an approved review wait requires a checkpoint id.")
        return self


class FlowRunContractViolation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    side: ContractSide = Field(
        description=(
            "Whether the step's input contract or its output contract was broken. "
            "`input` also for `typed_io_tool_invalid_arguments`, where the broken "
            "contract is the input schema of the step's tool."
        ),
    )
    schema_rule: str = Field(
        min_length=1,
        max_length=CONTRACT_VIOLATION_RULE_MAX_LENGTH,
        pattern=r"^\$?[A-Za-z][A-Za-z0-9]*$",
        strict=True,
        description="JSON Schema keyword that rejected the value, for example `required` or `type`.",
    )
    json_pointer: str = Field(
        max_length=CONTRACT_VIOLATION_POINTER_MAX_LENGTH,
        pattern=r"^(/([^~/\x00-\x1f]|~[01])*)*$",
        strict=True,
        description=(
            "RFC 6901 pointer into the value the contract checked: the step input or "
            "output, or for `typed_io_tool_invalid_arguments` the arguments object "
            "the step resolved for its tool. For a per-item, section or mapped step a check of one call "
            "points into that call's value, and a failure of the assembled output "
            "points into the complete assembled output. It is the deepest location "
            "the contract declares (properties and array indices), so it can be an "
            "ancestor of the failing object when a key that comes from the data was "
            "cut; the empty string is the whole value. For `required` it names the "
            "object missing the property."
        ),
    )

    @classmethod
    def from_context(
        cls, context: Mapping[str, object]
    ) -> FlowRunContractViolation | None:
        """All three facts from the validator's context, or none (never raises)."""
        try:
            return cls.model_validate(
                {
                    "side": context.get("contract_side"),
                    "schema_rule": context.get("schema_rule"),
                    "json_pointer": context.get("json_pointer"),
                }
            )
        except ValidationError:
            return None


_SPEAKER_SERVICE_GAPS = {gap.value: gap for gap in SpeakerServiceGap}


_TOOL_REFUSALS = {refusal.value: refusal for refusal in UnattendedToolRefusal}


def _known_tool_refusal(value: object) -> UnattendedToolRefusal | None:
    # The enum is the MCP module's. A value it no longer has, in a context or
    # in a stored error, reads as no refusal: the rest of the error is kept.
    return _TOOL_REFUSALS.get(str(value))


class FlowRunErrorDetails(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_violation: FlowRunContractViolation | None = Field(
        default=None,
        description=(
            "Where and which rule a value broke in a step's input or output contract, "
            "or in the approved input schema of the step's tool "
            "(`typed_io_tool_invalid_arguments`). For a per-item, section or mapped step the rule can come from the bound "
            "the platform puts on one call, such as exactly one item. Absent when not "
            "recorded: a pointer longer than 400 characters, a violation found "
            "outside the platform's contract validator, or a run that failed before "
            "this field existed. Never contains the value itself."
        ),
    )

    recovery: FlowRunRecoveryFacts | None = Field(
        default=None,
        description="Execution heartbeat facts used to recover a stalled worker.",
    )
    abandonment: FlowRunAbandonmentFacts | None = Field(
        default=None,
        description="Wait and deadline that caused automatic abandonment; history and files are retained.",
    )

    measured_bytes: int | None = Field(default=None, ge=0, strict=True)
    summarization_rounds: int | None = Field(default=None, ge=0, strict=True)
    summarization_records: int | None = Field(default=None, ge=0, strict=True)
    summarization_bytes: int | None = Field(default=None, ge=0, strict=True)
    ceiling_bytes: int | None = Field(default=None, ge=0, strict=True)
    step_description: str | None = Field(
        default=None,
        min_length=1,
        max_length=_MAX_STEP_DESCRIPTION_LENGTH,
        description=(
            "Human label for the affected step, truncated to a small public "
            "diagnostic budget."
        ),
    )
    provider_call_evidence_gap: ProviderCallEvidenceGap | None = Field(
        default=None,
        description=(
            "Secret-free provider-call facts retained when the local evidence "
            "transaction failed after bounded retries. This describes a local "
            "persistence gap, not an unknown remote outcome."
        ),
    )

    phase: FlowStepPhase | None = Field(
        default=None,
        description="Observed execution phase when the step failed or its budget expired.",
    )
    transcription_failure_kind: TranscriptionFailureKind | None = Field(
        default=None,
        description="Transcription failure category from local preparation or upstream protocol facts. Does not imply that a new run is safe to retry.",
    )
    transcription_service_reason: str | None = Field(
        default=None,
        max_length=TRANSCRIPTION_SERVICE_REASON_MAX_LENGTH,
        description="Bounded human-readable transcription service reason. Never parse this text to classify a failure.",
    )
    tool_refusal: Annotated[
        UnattendedToolRefusal | None, BeforeValidator(_known_tool_refusal)
    ] = Field(
        default=None,
        description=(
            "What refuses the step's tool for the flow's space, for "
            "`typed_io_tool_not_allowed`: a personal space, or else the first "
            "level that says no, in the order instance server, instance tool, "
            "space. Absent for a stored value this version no longer has."
        ),
    )
    tool_call_possible: bool | None = Field(
        default=None,
        description=(
            "Set on an error whose code alone would be retryable: true when the "
            "run ended at or after a step whose input is a tool's answer, or "
            "had completed such a step when its dispatch failed, so a tool may "
            "have been called and may have changed something. `retryable` is "
            "then false."
        ),
    )
    tool_error_text: str | None = Field(
        default=None,
        max_length=TOOL_ERROR_TEXT_MAX_LENGTH,
        description=(
            "The start of the text a tool sent with its own statement that it "
            "failed, for a step whose input is a tool's answer. Never parse this "
            "text to classify a failure."
        ),
    )
    transcription_stage: str | None = Field(
        default=None,
        max_length=128,
        description="Last observed transcription service stage before the interruption.",
    )
    transcription_queue_position: int | None = Field(
        default=None,
        ge=0,
        strict=True,
        description="Last observed transcription queue position, when reported by the service.",
    )
    speaker_service_gap: SpeakerServiceGap | None = Field(
        default=None,
        description=(
            "Why no speaker identification service could label this run's "
            "speakers: the flow chose none (not_chosen), or the service it "
            "chose is no longer usable in the space (picked_unavailable). "
            "Refused before any audio was sent."
        ),
    )
    completed_items: int | None = Field(
        default=None,
        ge=0,
        description="Mapped items completed before the interruption.",
    )
    total_items: int | None = Field(
        default=None, ge=0, description="Total mapped items in this step attempt."
    )
    provider_work_may_have_completed: bool | None = Field(
        default=None,
        description="Whether an interrupted provider request had an unknown outcome. This does not replace retryable.",
    )

    @model_validator(mode="after")
    def _validate_progress(self) -> FlowRunErrorDetails:
        if (
            self.completed_items is not None
            and self.total_items is not None
            and self.completed_items > self.total_items
        ):
            raise ValueError("completed_items must not exceed total_items.")
        return self

    @classmethod
    def from_budget_context(
        cls, context: dict[str, object] | None
    ) -> FlowRunErrorDetails | None:
        if not context:
            return None

        def count(key: str, fallback: str | None = None) -> int | None:
            value = context.get(key, context.get(fallback) if fallback else None)
            return value if type(value) is int and value >= 0 else None

        kind = context.get("transcription_failure_kind")
        reason = context.get("transcription_service_reason")
        tool_error_text = context.get("tool_error_text")

        details = cls(
            contract_violation=FlowRunContractViolation.from_context(context),
            transcription_failure_kind=kind
            if isinstance(kind, TranscriptionFailureKind)
            else None,
            transcription_service_reason=reason[
                :TRANSCRIPTION_SERVICE_REASON_MAX_LENGTH
            ]
            if isinstance(reason, str)
            else None,
            tool_refusal=_known_tool_refusal(context.get("refusal")),
            tool_error_text=tool_error_text[:TOOL_ERROR_TEXT_MAX_LENGTH]
            if isinstance(tool_error_text, str)
            else None,
            measured_bytes=count("measured_bytes", "measured"),
            summarization_rounds=count("summarization_rounds"),
            summarization_records=count("summarization_records"),
            summarization_bytes=count("summarization_bytes"),
            ceiling_bytes=count("ceiling_bytes", "ceiling"),
            completed_items=count("completed_items"),
            total_items=count("total_items"),
            transcription_stage=(
                str(context["transcription_stage"])[:128]
                if isinstance(context.get("transcription_stage"), str)
                else None
            ),
            transcription_queue_position=count("transcription_queue_position"),
            speaker_service_gap=_SPEAKER_SERVICE_GAPS.get(
                str(context.get("speaker_service_gap"))
            ),
        )
        return details if details.model_dump(exclude_none=True) else None

    @classmethod
    def from_bad_request_context(
        cls, context: dict[str, object] | None
    ) -> FlowRunErrorDetails | None:
        if context is None:
            return None

        step_description = context.get("step_description")
        details = cls(
            step_description=step_description[:_MAX_STEP_DESCRIPTION_LENGTH]
            if isinstance(step_description, str) and step_description
            else None,
            tool_refusal=_known_tool_refusal(context.get("refusal")),
        )
        return details if details.model_dump(exclude_none=True) else None


class FlowRunError(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        json_schema_extra={
            "description": (
                "Structured terminal run error. Clients should branch on `code`, "
                "not on the human-readable message."
            ),
            "examples": [
                {
                    "schema_version": 1,
                    "code": FlowApiErrorCode.RUN_ABANDONED.value,
                    "message": "Flow run exceeded its abandonment deadline.",
                    "source": "abandonment_reconciler",
                    "retryable": False,
                    "details": {
                        "abandonment": {
                            "wait": "approved_review",
                            "anchor_at": "2026-08-22T00:00:00Z",
                            "deadline": "2026-09-21T00:00:00Z",
                            "checkpoint_id": "00000000-0000-4000-8000-000000000001",
                        }
                    },
                },
                {
                    "schema_version": 1,
                    "code": FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_FAILED.value,
                    "message": "Step 1: transcription failed for 'meeting.wav'.",
                    "source": "executor_failed",
                    "step_order": 1,
                    "retryable": False,
                    "details": {
                        "phase": "transcription",
                        "transcription_failure_kind": "capacity",
                        "transcription_service_reason": "Transcription capacity is unavailable.",
                        "transcription_stage": "transcribing",
                    },
                },
                {
                    "schema_version": 1,
                    "code": FlowApiErrorCode.RUN_WORKER_STALLED.value,
                    "message": "Flow execution heartbeat expired.",
                    "source": "stale_running_reconciler",
                    "retryable": False,
                    "details": {
                        "recovery": {
                            "reason": "execution_heartbeat_expired",
                            "heartbeat_at": "2026-09-20T18:00:00Z",
                            "expires_at": "2026-09-20T18:03:00Z",
                        }
                    },
                },
            ],
        },
    )

    schema_version: Literal[1] = Field(
        default=1,
        description="Schema version for the structured run error payload.",
    )
    code: FlowRunTerminalErrorCode = Field(description=_CODE_DESCRIPTION)
    message: str = Field(
        min_length=1,
        max_length=_MAX_MESSAGE_LENGTH,
        description=(
            "Human-readable technical detail for logs, support and fallback UI. "
            "This text is not a stable client contract."
        ),
    )
    source: FlowRunLifecycleSource | None = Field(
        default=None,
        description="Flow runtime lifecycle source that terminalized the run.",
    )
    step_id: UUID | None = Field(
        default=None,
        description="Step id when the terminal error is tied to one step.",
    )
    step_order: int | None = Field(
        default=None,
        ge=1,
        description="Step order when the terminal error is tied to one step.",
    )
    details: FlowRunErrorDetails | None = Field(
        default=None,
        description="Small, API-safe context for diagnostics and UI guidance.",
    )

    @model_validator(mode="wrap")
    @classmethod
    def _validate_public_retryability(
        cls,
        value: object,
        handler: ModelWrapValidatorHandler[FlowRunError],
    ) -> FlowRunError:
        if not isinstance(value, Mapping) or "retryable" not in value:
            return handler(value)

        public_fields = cast(Mapping[object, object], value)
        retryable = public_fields["retryable"]
        fields = dict(public_fields)
        del fields["retryable"]
        error = handler(fields)
        if type(retryable) is bool and retryable is error.retryable:
            return error
        return handler(value)

    @computed_field(
        description=(
            "Whether a consumer may submit a new logical run without repeating "
            "provider work that was accepted or an external effect. True only "
            "for a code the platform lists as such, and false for such a code "
            "when `details.tool_call_possible` is true, because a new run "
            "calls the tool again. This does not automatically start work."
        )
    )
    @property
    def retryable(self) -> bool:
        return FLOW_RUN_TERMINAL_ERROR_RETRYABILITY[self.code] and not (
            self.details is not None and self.details.tool_call_possible is True
        )

    @classmethod
    def from_source(
        cls,
        source: FlowRunLifecycleSource,
        *,
        code: FlowApiErrorCode,
        message: str,
        step_id: UUID | None = None,
        step_order: int | None = None,
        details: FlowRunErrorDetails | None = None,
    ) -> FlowRunError:
        return cls(
            code=code,
            message=_bound_message(message),
            source=source,
            step_id=step_id,
            step_order=step_order,
            details=details,
        )


def tool_call_possible(
    *,
    tool_step_orders: Collection[int],
    completed_step_orders: Collection[int],
    failing_step_order: int | None,
) -> bool:
    """Whether a run may have called a tool: one of the tool steps of its
    frozen definition is completed, or is at or before the step it failed at
    (None when it failed before running a step, as on a failed dispatch).

    A completed step counts also when it was imported from the run that a
    retry started from: the tool was called for its answer all the same.
    """
    return any(
        order in completed_step_orders
        or (failing_step_order is not None and order <= failing_step_order)
        for order in tool_step_orders
    )


def after_possible_tool_call(
    details: FlowRunErrorDetails | None, *, code: FlowApiErrorCode
) -> FlowRunErrorDetails | None:
    """``details`` for an error of a run that ended at or after a tool step.

    Only a code whose table entry is retryable gets the fact: for every other
    code ``retryable`` is false already.
    """
    if not FLOW_RUN_TERMINAL_ERROR_RETRYABILITY.get(code, False):
        return details
    return (details or FlowRunErrorDetails()).model_copy(
        update={"tool_call_possible": True}
    )


def dump_flow_run_error(error: FlowRunError | None) -> FlowRunErrorJson | None:
    if error is None:
        return None
    return cast(
        FlowRunErrorJson,
        error.model_dump(mode="json", exclude_none=True, exclude={"retryable"}),
    )


def parse_flow_run_error(value: object) -> FlowRunError | None:
    if value is None:
        return None
    if isinstance(value, FlowRunError):
        return value
    if isinstance(value, Mapping) and "retryable" in value:
        return FlowRunError(
            code=FlowApiErrorCode.RUN_ERROR_PAYLOAD_INVALID,
            message=_INVALID_PERSISTED_ERROR_MESSAGE,
        )
    try:
        return FlowRunError.model_validate(value)
    except ValidationError:
        return FlowRunError(
            code=FlowApiErrorCode.RUN_ERROR_PAYLOAD_INVALID,
            message=_INVALID_PERSISTED_ERROR_MESSAGE,
        )


def dump_flow_run_dispatch_error(
    error: FlowRunDispatchError | None,
) -> FlowRunDispatchErrorJson | None:
    if error is None:
        return None
    return cast(
        FlowRunDispatchErrorJson,
        error.model_dump(mode="json", exclude_none=True),
    )


def parse_flow_run_dispatch_error(value: object) -> FlowRunDispatchError | None:
    if value is None:
        return None
    if isinstance(value, FlowRunDispatchError):
        return value
    try:
        return FlowRunDispatchError.model_validate(value)
    except ValidationError:
        return FlowRunDispatchError.from_kind(
            FlowRunDispatchErrorKind.INVALID_PERSISTED_ERROR
        )


def _bound_message(message: str) -> str:
    if len(message) <= _MAX_MESSAGE_LENGTH:
        return message
    budget = _MAX_MESSAGE_LENGTH - len(_MESSAGE_TRUNCATION_SUFFIX)
    if budget <= 0:
        return _MESSAGE_TRUNCATION_SUFFIX[:_MAX_MESSAGE_LENGTH]
    return f"{message[:budget]}{_MESSAGE_TRUNCATION_SUFFIX}"
