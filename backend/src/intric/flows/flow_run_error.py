from __future__ import annotations

from typing import Annotated, Literal, TypeAlias, cast
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    WithJsonSchema,
)

from intric.flows.enums import FlowRunLifecycleSource
from intric.flows.flow_api_error_code import (
    FLOW_RUN_TERMINAL_ERROR_CODES,
    FlowApiErrorCode,
)

FlowRunErrorJson: TypeAlias = dict[str, object]

_MAX_STEP_DESCRIPTION_LENGTH = 256
_MAX_MESSAGE_LENGTH = 4096
_MESSAGE_TRUNCATION_SUFFIX = "... [truncated]"
_INVALID_PERSISTED_ERROR_MESSAGE = "Persisted flow run error payload is invalid."
_CODE_DESCRIPTION = "Stable machine-readable run error code."
_TERMINAL_ERROR_CODE_VALUES = tuple(
    sorted(code.value for code in FLOW_RUN_TERMINAL_ERROR_CODES)
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
    return cast(FlowRunErrorJson, error.model_dump(mode="json", exclude_none=True))


def parse_flow_run_error(value: object) -> FlowRunError | None:
    if value is None:
        return None
    if isinstance(value, FlowRunError):
        return value
    try:
        return FlowRunError.model_validate(value)
    except ValidationError:
        return FlowRunError(
            code=FlowApiErrorCode.RUN_ERROR_PAYLOAD_INVALID,
            message=_INVALID_PERSISTED_ERROR_MESSAGE,
        )


def _bound_message(message: str) -> str:
    if len(message) <= _MAX_MESSAGE_LENGTH:
        return message
    budget = _MAX_MESSAGE_LENGTH - len(_MESSAGE_TRUNCATION_SUFFIX)
    if budget <= 0:
        return _MESSAGE_TRUNCATION_SUFFIX[:_MAX_MESSAGE_LENGTH]
    return f"{message[:budget]}{_MESSAGE_TRUNCATION_SUFFIX}"
