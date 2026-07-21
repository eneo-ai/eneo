from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias, cast
from uuid import UUID

from pydantic import (
    AfterValidator,
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

from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import (
    FLOW_RUN_TERMINAL_ERROR_CODES,
    FLOW_RUN_TERMINAL_ERROR_RETRYABILITY,
    FlowApiErrorCode,
)

FlowRunErrorJson: TypeAlias = dict[str, object]
FlowRunDispatchErrorJson: TypeAlias = dict[str, object]

_MAX_STEP_DESCRIPTION_LENGTH = 256
_MAX_MESSAGE_LENGTH = 4096
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


class FlowRunErrorDetails(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step_description: str | None = Field(
        default=None,
        min_length=1,
        max_length=_MAX_STEP_DESCRIPTION_LENGTH,
        description=(
            "Human label for the affected step, truncated to a small public "
            "diagnostic budget."
        ),
    )

    @classmethod
    def from_bad_request_context(
        cls, context: dict[str, object] | None
    ) -> FlowRunErrorDetails | None:
        if context is None:
            return None

        step_description = context.get("step_description")
        if not isinstance(step_description, str) or not step_description:
            return None

        return cls(
            step_description=step_description[:_MAX_STEP_DESCRIPTION_LENGTH],
        )


class FlowRunError(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        json_schema_extra={
            "description": (
                "Structured terminal run error. Clients should branch on `code`, "
                "not on the human-readable message."
            )
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
            "Whether a consumer may safely submit a new logical run after "
            "terminalization. This does not automatically start work."
        )
    )
    @property
    def retryable(self) -> bool:
        return FLOW_RUN_TERMINAL_ERROR_RETRYABILITY[self.code]

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
