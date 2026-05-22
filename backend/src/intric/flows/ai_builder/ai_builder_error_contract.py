from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, TypeAlias, TypeGuard, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from intric.main.exceptions import (
    BadRequestException,
    ErrorCodes,
    NotFoundException,
    UnauthorizedException,
)

JsonScalar: TypeAlias = str | int | float | bool | None

_MAX_DETAILS_KEYS = 10
_MAX_DETAILS_STRING_LENGTH = 256
_MAX_DETAILS_JSON_BYTES = 1024
_MAX_MESSAGE_LENGTH = 4096
_MAX_REQUEST_ID_LENGTH = 128
_DIAGNOSTIC_CONTEXT_STRING_LENGTH = 256


class AIBuilderErrorCode(StrEnum):
    ARCHITECTURE_CRITIC_INVARIANT_FAILED = "architecture_critic_invariant_failed"
    ARCHITECTURE_MATERIALIZATION_FAILED = "architecture_materialization_failed"
    AI_BUILDER_PLAN_RESOURCE_BINDING_UNAVAILABLE = (
        "ai_builder_plan_resource_binding_unavailable"
    )
    AI_BUILDER_PLAN_RESOURCE_BINDINGS_MISSING = (
        "ai_builder_plan_resource_bindings_missing"
    )
    BAD_REQUEST = "bad_request"
    BUILDER_ATTACHMENT_UNAVAILABLE = "builder_attachment_unavailable"
    EDIT_SESSION_FLOW_REQUIRED = "edit_session_flow_required"
    FLOW_IS_PUBLISHED = "flow_is_published"
    FLOW_SPACE_MISMATCH = "flow_space_mismatch"
    INVALID_AI_BUILDER_SETTINGS = "invalid_ai_builder_settings"
    INSUFFICIENT_SCOPE = "insufficient_scope"
    INSUFFICIENT_SPACE_PERMISSION = "insufficient_space_permission"
    INVALID_EXISTING_STEP_REF = "invalid_existing_step_ref"
    INVALID_PLAN_STEP_REF = "invalid_plan_step_ref"
    INVALID_PLAN_STATUS = "invalid_plan_status"
    INVALID_QUESTION_PAYLOAD = "invalid_question_payload"
    INVALID_SESSION_TRANSITION = "invalid_session_transition"
    MODEL_NOT_AVAILABLE = "model_not_available"
    NOT_FOUND = "not_found"
    NO_PLANNER_MODEL_AVAILABLE = "no_planner_model_available"
    PLAN_NOT_PROPOSED = "plan_not_proposed"
    PLAN_SESSION_MISMATCH = "plan_session_mismatch"
    PLANNING_STATE_VERSION_MISMATCH = "planning_state_version_mismatch"
    PLANNER_BUDGET_MISSING = "planner_budget_missing"
    PLANNER_MODEL_MISSING_CONTEXT_WINDOW = "planner_model_missing_context_window"
    PLANNER_MODEL_MISSING_OUTPUT_TOKENS = "planner_model_missing_output_tokens"
    PLANNER_INVALID_REPAIR_RESPONSE = "planner_invalid_repair_response"
    PLANNER_OUTPUT_TOO_LONG = "planner_output_too_long"
    PLANNER_PARSE_ERROR = "planner_parse_error"
    PLANNER_REJECTED = "planner_rejected"
    PLANNER_STREAM_FAILED = "planner_stream_failed"
    PLANNER_UPSTREAM_ERROR = "planner_upstream_error"
    PROPOSAL_TOOL_MISSING = "proposal_tool_missing"
    QUESTION_RECOVERY_EXHAUSTED = "question_recovery_exhausted"
    QUESTION_RECOVERY_UNAVAILABLE = "question_recovery_unavailable"
    REQUIREMENTS_INCOMPLETE = "requirements_incomplete"
    REQUIREMENTS_NOT_CONFIRMED = "requirements_not_confirmed"
    SELF_CORRECTION_INVALID_PAYLOAD = "self_correction_invalid_payload"
    SELF_CORRECTION_INVALID_PLAN = "self_correction_invalid_plan"
    SELF_CORRECTION_QUALITY_FAILURE = "self_correction_quality_failure"
    SESSION_CREATOR_REQUIRED = "session_creator_required"
    SESSION_MESSAGE_IN_PROGRESS = "session_message_in_progress"
    SESSION_LATEST_PLAN_UPDATE_CONFLICT = "session_latest_plan_update_conflict"
    SESSION_SEND_IN_PROGRESS = "session_send_in_progress"
    SESSION_SEND_LEASE_LOST = "session_send_lease_lost"
    STALE_PLAN_REVISION = "stale_plan_revision"
    STALE_REVISION = "stale_revision"
    TRANSCRIPTION_MODEL_REQUIRED = "transcription_model_required"
    UNSUPPORTED_REVISION_TYPE = "unsupported_revision_type"


class AIBuilderErrorCategory(StrEnum):
    BAD_REQUEST = "bad_request"
    CONFLICT = "conflict"
    INTERNAL = "internal"
    NOT_FOUND = "not_found"
    SOFT_BLOCK = "soft_block"
    UNAUTHORIZED = "unauthorized"
    UPSTREAM = "upstream"


class AIBuilderErrorPhase(StrEnum):
    PLANNER = "planner"
    PROPOSAL = "proposal"
    QUESTION = "question"
    QUESTION_RECOVERY = "question_recovery"
    REQUIREMENTS = "requirements"
    ROUTER = "router"
    SELF_CORRECTION = "self_correction"


class AIBuilderBadRequestException(BadRequestException):
    """AI Builder bad-request exception with code narrowed to AIBuilderErrorCode."""

    code: AIBuilderErrorCode

    def __init__(
        self,
        message: str = "",
        *,
        code: AIBuilderErrorCode,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, code=code.value, context=context)
        self.code = code


class AIBuilderNotFoundException(NotFoundException):
    """AI Builder not-found exception with code narrowed to AIBuilderErrorCode."""

    code: AIBuilderErrorCode

    def __init__(
        self,
        message: str = "",
        *,
        code: AIBuilderErrorCode,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, code=code.value, context=context)
        self.code = code


class AIBuilderUnauthorizedException(UnauthorizedException):
    """AI Builder unauthorized exception with code narrowed to AIBuilderErrorCode."""

    code: AIBuilderErrorCode

    def __init__(
        self,
        message: str = "",
        *,
        code: AIBuilderErrorCode,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, code=code.value, context=context)
        self.code = code


_DIAGNOSTIC_STRING_KEYS = frozenset(
    {
        "session_id",
        "plan_id",
        "flow_id",
        "space_id",
        "target_kind",
        "plan_step_ref",
        "model",
        "outcome_kind",
    }
)
_DIAGNOSTIC_ENUM_FIELDS = MappingProxyType(
    {
        "error_code": AIBuilderErrorCode,
        "error_category": AIBuilderErrorCategory,
        "error_phase": AIBuilderErrorPhase,
    }
)


@dataclass(frozen=True)
class AIBuilderErrorRegistryEntry:
    category: AIBuilderErrorCategory
    http_status: int
    intric_error_code: ErrorCodes
    default_phase: AIBuilderErrorPhase


def _entry(
    *,
    category: AIBuilderErrorCategory,
    http_status: int,
    intric_error_code: ErrorCodes,
    default_phase: AIBuilderErrorPhase = AIBuilderErrorPhase.ROUTER,
) -> AIBuilderErrorRegistryEntry:
    return AIBuilderErrorRegistryEntry(
        category=category,
        http_status=http_status,
        intric_error_code=intric_error_code,
        default_phase=default_phase,
    )


_AIBuilderErrorRegistry: TypeAlias = Mapping[
    AIBuilderErrorCode, AIBuilderErrorRegistryEntry
]

AI_BUILDER_ERROR_REGISTRY: _AIBuilderErrorRegistry = MappingProxyType(
    {
        AIBuilderErrorCode.ARCHITECTURE_CRITIC_INVARIANT_FAILED: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.PROPOSAL,
        ),
        AIBuilderErrorCode.ARCHITECTURE_MATERIALIZATION_FAILED: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.PROPOSAL,
        ),
        AIBuilderErrorCode.AI_BUILDER_PLAN_RESOURCE_BINDING_UNAVAILABLE: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.AI_BUILDER_PLAN_RESOURCE_BINDINGS_MISSING: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.BAD_REQUEST: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.BUILDER_ATTACHMENT_UNAVAILABLE: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.EDIT_SESSION_FLOW_REQUIRED: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.FLOW_IS_PUBLISHED: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.FLOW_SPACE_MISMATCH: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.INVALID_AI_BUILDER_SETTINGS: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.INSUFFICIENT_SCOPE: _entry(
            category=AIBuilderErrorCategory.UNAUTHORIZED,
            http_status=403,
            intric_error_code=ErrorCodes.UNAUTHORIZED,
        ),
        AIBuilderErrorCode.INSUFFICIENT_SPACE_PERMISSION: _entry(
            category=AIBuilderErrorCategory.UNAUTHORIZED,
            http_status=403,
            intric_error_code=ErrorCodes.UNAUTHORIZED,
        ),
        AIBuilderErrorCode.INVALID_EXISTING_STEP_REF: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.INVALID_PLAN_STEP_REF: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.INVALID_PLAN_STATUS: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.QUESTION,
        ),
        AIBuilderErrorCode.INVALID_SESSION_TRANSITION: _entry(
            category=AIBuilderErrorCategory.CONFLICT,
            http_status=409,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.MODEL_NOT_AVAILABLE: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.NOT_FOUND: _entry(
            category=AIBuilderErrorCategory.NOT_FOUND,
            http_status=404,
            intric_error_code=ErrorCodes.NOT_FOUND,
        ),
        AIBuilderErrorCode.NO_PLANNER_MODEL_AVAILABLE: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.PLAN_NOT_PROPOSED: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.PLAN_SESSION_MISMATCH: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.PLANNER_BUDGET_MISSING: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.PLANNER,
        ),
        AIBuilderErrorCode.PLANNER_MODEL_MISSING_CONTEXT_WINDOW: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.PLANNER,
        ),
        AIBuilderErrorCode.PLANNER_MODEL_MISSING_OUTPUT_TOKENS: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.PLANNER,
        ),
        AIBuilderErrorCode.PLANNING_STATE_VERSION_MISMATCH: _entry(
            category=AIBuilderErrorCategory.CONFLICT,
            http_status=409,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.PLANNER,
        ),
        AIBuilderErrorCode.PLANNER_INVALID_REPAIR_RESPONSE: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.SELF_CORRECTION,
        ),
        AIBuilderErrorCode.PLANNER_OUTPUT_TOO_LONG: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.PLANNER,
        ),
        AIBuilderErrorCode.PLANNER_PARSE_ERROR: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.PLANNER,
        ),
        AIBuilderErrorCode.PLANNER_REJECTED: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.PLANNER,
        ),
        AIBuilderErrorCode.PLANNER_STREAM_FAILED: _entry(
            category=AIBuilderErrorCategory.INTERNAL,
            http_status=500,
            intric_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
            default_phase=AIBuilderErrorPhase.PLANNER,
        ),
        AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR: _entry(
            category=AIBuilderErrorCategory.UPSTREAM,
            http_status=502,
            intric_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
            default_phase=AIBuilderErrorPhase.PLANNER,
        ),
        AIBuilderErrorCode.PROPOSAL_TOOL_MISSING: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.PROPOSAL,
        ),
        AIBuilderErrorCode.QUESTION_RECOVERY_EXHAUSTED: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.QUESTION_RECOVERY,
        ),
        AIBuilderErrorCode.QUESTION_RECOVERY_UNAVAILABLE: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.QUESTION_RECOVERY,
        ),
        AIBuilderErrorCode.REQUIREMENTS_INCOMPLETE: _entry(
            category=AIBuilderErrorCategory.SOFT_BLOCK,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.REQUIREMENTS,
        ),
        AIBuilderErrorCode.REQUIREMENTS_NOT_CONFIRMED: _entry(
            category=AIBuilderErrorCategory.SOFT_BLOCK,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.REQUIREMENTS,
        ),
        AIBuilderErrorCode.SELF_CORRECTION_INVALID_PAYLOAD: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.SELF_CORRECTION,
        ),
        AIBuilderErrorCode.SELF_CORRECTION_INVALID_PLAN: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.SELF_CORRECTION,
        ),
        AIBuilderErrorCode.SELF_CORRECTION_QUALITY_FAILURE: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.SELF_CORRECTION,
        ),
        AIBuilderErrorCode.SESSION_CREATOR_REQUIRED: _entry(
            category=AIBuilderErrorCategory.UNAUTHORIZED,
            http_status=403,
            intric_error_code=ErrorCodes.UNAUTHORIZED,
        ),
        AIBuilderErrorCode.SESSION_MESSAGE_IN_PROGRESS: _entry(
            category=AIBuilderErrorCategory.CONFLICT,
            http_status=409,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.SESSION_LATEST_PLAN_UPDATE_CONFLICT: _entry(
            category=AIBuilderErrorCategory.CONFLICT,
            http_status=409,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.SESSION_SEND_IN_PROGRESS: _entry(
            category=AIBuilderErrorCategory.CONFLICT,
            http_status=409,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.SESSION_SEND_LEASE_LOST: _entry(
            category=AIBuilderErrorCategory.CONFLICT,
            http_status=409,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            default_phase=AIBuilderErrorPhase.PLANNER,
        ),
        AIBuilderErrorCode.STALE_PLAN_REVISION: _entry(
            category=AIBuilderErrorCategory.CONFLICT,
            http_status=409,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.STALE_REVISION: _entry(
            category=AIBuilderErrorCategory.CONFLICT,
            http_status=409,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.TRANSCRIPTION_MODEL_REQUIRED: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
        AIBuilderErrorCode.UNSUPPORTED_REVISION_TYPE: _entry(
            category=AIBuilderErrorCategory.BAD_REQUEST,
            http_status=400,
            intric_error_code=ErrorCodes.BAD_REQUEST,
        ),
    }
)


class AIBuilderDiagnosticContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str | None = Field(
        default=None, max_length=_DIAGNOSTIC_CONTEXT_STRING_LENGTH
    )
    plan_id: str | None = Field(
        default=None, max_length=_DIAGNOSTIC_CONTEXT_STRING_LENGTH
    )
    request_id: str | None = Field(default=None, max_length=_MAX_REQUEST_ID_LENGTH)
    flow_id: str | None = Field(
        default=None, max_length=_DIAGNOSTIC_CONTEXT_STRING_LENGTH
    )
    space_id: str | None = Field(
        default=None, max_length=_DIAGNOSTIC_CONTEXT_STRING_LENGTH
    )
    target_kind: str | None = Field(
        default=None, max_length=_DIAGNOSTIC_CONTEXT_STRING_LENGTH
    )
    plan_step_ref: str | None = Field(
        default=None, max_length=_DIAGNOSTIC_CONTEXT_STRING_LENGTH
    )
    error_code: AIBuilderErrorCode | None = None
    error_category: AIBuilderErrorCategory | None = None
    error_phase: AIBuilderErrorPhase | None = None
    model: str | None = Field(
        default=None, max_length=_DIAGNOSTIC_CONTEXT_STRING_LENGTH
    )
    outcome_kind: str | None = Field(
        default=None, max_length=_DIAGNOSTIC_CONTEXT_STRING_LENGTH
    )


_DIAGNOSTIC_CONTEXT_KEYS = frozenset(AIBuilderDiagnosticContext.model_fields)


class AIBuilderPublicError(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        json_schema_extra={
            "description": (
                "Canonical public AI Builder error. Clients should branch on "
                "`code` and `category`, not on the human-readable message."
            )
        },
    )

    schema_version: Literal[2] = Field(
        default=2,
        description="Schema version for the AI Builder error contract.",
    )
    code: AIBuilderErrorCode = Field(
        description="Stable machine-readable AI Builder error code.",
    )
    category: AIBuilderErrorCategory = Field(
        description="Stable UI and control-flow category for the error.",
    )
    message: str = Field(
        min_length=1,
        max_length=_MAX_MESSAGE_LENGTH,
        description=(
            "Human-readable message for users, logs and support. This text is "
            "not a stable client contract."
        ),
    )
    phase: AIBuilderErrorPhase = Field(
        description="AI Builder lifecycle phase that produced the error.",
    )
    intric_error_code: ErrorCodes = Field(
        description="Numeric Eneo error category retained for existing clients.",
    )
    request_id: str = Field(
        min_length=1,
        max_length=_MAX_REQUEST_ID_LENGTH,
        description="Request or correlation id that produced the error.",
    )
    diagnostic_context: AIBuilderDiagnosticContext | None = Field(
        default=None,
        description=(
            "Small correlation bundle for finding the session, plan, request, "
            "phase, model or step involved in the error."
        ),
    )
    details: dict[str, JsonScalar] | None = Field(
        default=None,
        description="Small bounded scalar per-error details safe for API clients.",
    )

    @field_validator("details")
    @classmethod
    def validate_details(
        cls, value: dict[str, JsonScalar] | None
    ) -> dict[str, JsonScalar] | None:
        if value is None:
            return None
        if len(value) > _MAX_DETAILS_KEYS:
            raise ValueError(f"details must have at most {_MAX_DETAILS_KEYS} keys")
        for details_value in value.values():
            if isinstance(details_value, str):
                if len(details_value) > _MAX_DETAILS_STRING_LENGTH:
                    raise ValueError(
                        "details string values must have at most "
                        f"{_MAX_DETAILS_STRING_LENGTH} characters"
                    )
            elif not _is_json_scalar(details_value):
                raise ValueError("details values must be scalar JSON values")
        payload_size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        if payload_size > _MAX_DETAILS_JSON_BYTES:
            raise ValueError(
                f"details JSON must be at most {_MAX_DETAILS_JSON_BYTES} bytes"
            )
        return value


class AIBuilderErrorEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["error"] = "error"
    data: AIBuilderPublicError


def coerce_ai_builder_error_code(
    value: str | AIBuilderErrorCode | None,
    *,
    default: AIBuilderErrorCode = AIBuilderErrorCode.BAD_REQUEST,
) -> AIBuilderErrorCode:
    if isinstance(value, AIBuilderErrorCode):
        return value
    if value is None:
        return default
    try:
        return AIBuilderErrorCode(value)
    except ValueError:
        return default


def normalize_ai_builder_error_details(
    details: Mapping[str, object] | None,
) -> dict[str, JsonScalar] | None:
    if details is None:
        return None

    normalized: dict[str, JsonScalar] = {}
    for key, value in details.items():
        if len(normalized) >= _MAX_DETAILS_KEYS:
            break
        if not key:
            continue
        if not _is_json_scalar(value):
            continue
        if isinstance(value, str):
            normalized[key] = value[:_MAX_DETAILS_STRING_LENGTH]
        else:
            normalized[key] = value

    if not normalized:
        return None

    while normalized:
        payload_size = len(json.dumps(normalized, ensure_ascii=False).encode("utf-8"))
        if payload_size <= _MAX_DETAILS_JSON_BYTES:
            return normalized
        normalized.pop(next(reversed(normalized)))

    return None


def normalize_ai_builder_diagnostic_context(
    diagnostic_context: Mapping[str, object] | AIBuilderDiagnosticContext | None,
) -> AIBuilderDiagnosticContext | None:
    if diagnostic_context is None:
        return None
    if isinstance(diagnostic_context, AIBuilderDiagnosticContext):
        data = diagnostic_context.model_dump(exclude_none=True)
    else:
        data = {
            key: value
            for key, value in diagnostic_context.items()
            if key in _DIAGNOSTIC_CONTEXT_KEYS and value is not None
        }
    normalized: dict[str, object] = {}
    for key, value in data.items():
        if key == "request_id":
            if isinstance(value, str) and value:
                normalized[key] = value[:_MAX_REQUEST_ID_LENGTH]
            continue
        if key in _DIAGNOSTIC_STRING_KEYS:
            if isinstance(value, str) and value:
                normalized[key] = value[:_DIAGNOSTIC_CONTEXT_STRING_LENGTH]
            continue
        expected_enum = _DIAGNOSTIC_ENUM_FIELDS.get(key)
        if expected_enum is None:
            continue
        if isinstance(value, expected_enum):
            normalized[key] = value
            continue
        if isinstance(value, str):
            try:
                normalized[key] = expected_enum(value)
            except ValueError:
                continue

    if not normalized:
        return None
    context = AIBuilderDiagnosticContext.model_validate(normalized)
    if not context.model_dump(exclude_none=True):
        return None
    return context


def split_ai_builder_error_context(
    context: Mapping[str, object] | None,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    if context is None:
        return None, None

    diagnostic_context = {
        key: value for key, value in context.items() if key in _DIAGNOSTIC_CONTEXT_KEYS
    }
    details = {
        key: value
        for key, value in context.items()
        if key not in _DIAGNOSTIC_CONTEXT_KEYS
    }
    return diagnostic_context or None, details or None


def build_ai_builder_error(
    *,
    message: str,
    code: AIBuilderErrorCode,
    phase: AIBuilderErrorPhase | None = None,
    request_id: str | None = None,
    diagnostic_context: Mapping[str, object] | AIBuilderDiagnosticContext | None = None,
    details: Mapping[str, object] | None = None,
) -> AIBuilderPublicError:
    """Build the public error and own canonical diagnostic error fields."""

    registry_entry = AI_BUILDER_ERROR_REGISTRY[code]
    resolved_phase = phase or registry_entry.default_phase
    resolved_request_id = request_id or str(uuid4())
    diagnostic_data: dict[str, object] = {}
    if diagnostic_context is not None:
        if isinstance(diagnostic_context, AIBuilderDiagnosticContext):
            diagnostic_data.update(diagnostic_context.model_dump(exclude_none=True))
        else:
            diagnostic_data.update(diagnostic_context)
    diagnostic_data.update(
        {
            "request_id": resolved_request_id,
            "error_code": code.value,
            "error_category": registry_entry.category.value,
            "error_phase": resolved_phase.value,
        }
    )
    return AIBuilderPublicError(
        code=code,
        category=registry_entry.category,
        message=message,
        phase=resolved_phase,
        intric_error_code=registry_entry.intric_error_code,
        request_id=resolved_request_id,
        diagnostic_context=normalize_ai_builder_diagnostic_context(diagnostic_data),
        details=normalize_ai_builder_error_details(details),
    )


def build_ai_builder_error_event(
    *,
    message: str,
    code: AIBuilderErrorCode,
    phase: AIBuilderErrorPhase | None = None,
    request_id: str | None = None,
    diagnostic_context: Mapping[str, object] | AIBuilderDiagnosticContext | None = None,
    details: Mapping[str, object] | None = None,
) -> dict[str, str]:
    payload = build_ai_builder_error(
        message=message,
        code=code,
        phase=phase,
        request_id=request_id,
        diagnostic_context=diagnostic_context,
        details=details,
    )
    event = AIBuilderErrorEvent(data=payload)
    return {
        "event": event.event,
        "data": event.data.model_dump_json(exclude_none=True),
    }


def ai_builder_error_example(
    *,
    message: str,
    code: AIBuilderErrorCode,
    request_id: str = "req_01HZYXEXAMPLE",
    diagnostic_context: Mapping[str, object] | AIBuilderDiagnosticContext | None = None,
    details: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return cast(
        dict[str, object],
        build_ai_builder_error(
            message=message,
            code=code,
            request_id=request_id,
            diagnostic_context=diagnostic_context,
            details=details,
        ).model_dump(mode="json", exclude_none=True),
    )


def _is_json_scalar(value: object) -> TypeGuard[JsonScalar]:
    return value is None or isinstance(value, str | int | float | bool)


__all__ = [
    "AI_BUILDER_ERROR_REGISTRY",
    "AIBuilderDiagnosticContext",
    "AIBuilderErrorCategory",
    "AIBuilderErrorCode",
    "AIBuilderErrorEvent",
    "AIBuilderErrorPhase",
    "AIBuilderErrorRegistryEntry",
    "AIBuilderPublicError",
    "JsonScalar",
    "ai_builder_error_example",
    "build_ai_builder_error",
    "build_ai_builder_error_event",
    "coerce_ai_builder_error_code",
    "normalize_ai_builder_diagnostic_context",
    "normalize_ai_builder_error_details",
    "split_ai_builder_error_context",
]
