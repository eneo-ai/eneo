from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_error_contract import (
    AI_BUILDER_ERROR_REGISTRY,
    AIBuilderBadRequestException,
    AIBuilderDiagnosticContext,
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    AIBuilderNotFoundException,
    AIBuilderPublicError,
    AIBuilderUnauthorizedException,
    build_ai_builder_error,
    build_ai_builder_error_event,
    split_ai_builder_error_context,
)
from intric.main.exceptions import ErrorCodes


def test_error_registry_has_entry_for_every_error_code_enum_member() -> None:
    assert set(AI_BUILDER_ERROR_REGISTRY) == set(AIBuilderErrorCode)


def test_typed_public_exceptions_store_enum_error_code() -> None:
    bad_request = AIBuilderBadRequestException(
        "Invalid settings.",
        code=AIBuilderErrorCode.INVALID_AI_BUILDER_SETTINGS,
    )
    not_found = AIBuilderNotFoundException(
        "Missing plan.",
        code=AIBuilderErrorCode.NOT_FOUND,
    )
    unauthorized = AIBuilderUnauthorizedException(
        "Forbidden.",
        code=AIBuilderErrorCode.INSUFFICIENT_SPACE_PERMISSION,
    )

    assert bad_request.code is AIBuilderErrorCode.INVALID_AI_BUILDER_SETTINGS
    assert not_found.code is AIBuilderErrorCode.NOT_FOUND
    assert unauthorized.code is AIBuilderErrorCode.INSUFFICIENT_SPACE_PERMISSION


def test_error_event_serializes_to_public_v2_schema() -> None:
    event = build_ai_builder_error_event(
        message="The AI planner failed. Please try again.",
        code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
        phase=AIBuilderErrorPhase.PLANNER,
        request_id="req-ai-builder-1",
        diagnostic_context={"model": "gpt-5.4"},
        details={"retryable": True},
    )

    assert event["event"] == "error"
    payload = json.loads(event["data"])
    assert payload == {
        "schema_version": 2,
        "code": "planner_upstream_error",
        "category": "upstream",
        "message": "The AI planner failed. Please try again.",
        "phase": "planner",
        "intric_error_code": int(ErrorCodes.INTERNAL_SERVER_ERROR),
        "request_id": "req-ai-builder-1",
        "diagnostic_context": {
            "request_id": "req-ai-builder-1",
            "error_code": "planner_upstream_error",
            "error_category": "upstream",
            "error_phase": "planner",
            "model": "gpt-5.4",
        },
        "details": {"retryable": True},
    }


def test_public_error_round_trips_for_every_registry_entry() -> None:
    for code, registry_entry in AI_BUILDER_ERROR_REGISTRY.items():
        error = build_ai_builder_error(
            message=f"Example for {code.value}",
            code=code,
            request_id=f"req-{code.value}",
        )

        round_tripped = AIBuilderPublicError.model_validate(
            error.model_dump(mode="json")
        )
        assert round_tripped.code is code
        assert round_tripped.category is registry_entry.category
        assert round_tripped.phase is registry_entry.default_phase
        assert round_tripped.intric_error_code is registry_entry.intric_error_code


@pytest.mark.parametrize(
    "details",
    [
        {"nested": {"value": "not public"}},
        {"items": ["not", "public"]},
        {"too_long": "x" * 257},
        {f"k{i}": i for i in range(11)},
    ],
)
def test_error_details_reject_nested_or_oversized_values(
    details: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AIBuilderPublicError(
            message="Invalid details",
            code=AIBuilderErrorCode.BAD_REQUEST,
            category=AI_BUILDER_ERROR_REGISTRY[AIBuilderErrorCode.BAD_REQUEST].category,
            phase=AIBuilderErrorPhase.ROUTER,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            request_id="req-context",
            details=details,
        )


@pytest.mark.parametrize(
    "diagnostic_context",
    [
        {"session_id": {"nested": "not public"}},
        {"session_id": "session-1", "unexpected": "not public"},
    ],
)
def test_diagnostic_context_rejects_nested_or_extra_values(
    diagnostic_context: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AIBuilderDiagnosticContext.model_validate(diagnostic_context)


def test_build_ai_builder_error_sanitizes_invalid_diagnostic_context_values() -> None:
    error = build_ai_builder_error(
        message="The AI planner failed. Please try again.",
        code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
        phase=AIBuilderErrorPhase.PLANNER,
        request_id="req-safe",
        diagnostic_context={
            "session_id": {"nested": "not public"},
            "flow_id": "flow-1",
            "error_code": "not-a-real-code",
            "model": 42,
        },
    )

    assert error.diagnostic_context is not None
    assert error.diagnostic_context.flow_id == "flow-1"
    assert error.diagnostic_context.session_id is None
    assert error.diagnostic_context.model is None
    assert error.diagnostic_context.request_id == "req-safe"
    assert (
        error.diagnostic_context.error_code is AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR
    )


def test_build_ai_builder_error_overwrites_caller_provided_canonical_diagnostics() -> (
    None
):
    error = build_ai_builder_error(
        message="The AI planner failed. Please try again.",
        code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
        phase=AIBuilderErrorPhase.PLANNER,
        request_id="req-canonical",
        diagnostic_context={
            "request_id": "caller-request",
            "error_code": AIBuilderErrorCode.BAD_REQUEST.value,
            "error_category": "bad_request",
            "error_phase": "router",
        },
    )

    assert error.diagnostic_context is not None
    assert error.diagnostic_context.request_id == "req-canonical"
    assert (
        error.diagnostic_context.error_code is AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR
    )
    assert error.diagnostic_context.error_category.value == "upstream"
    assert error.diagnostic_context.error_phase is AIBuilderErrorPhase.PLANNER


def test_build_ai_builder_error_sanitizes_internal_details() -> None:
    error = build_ai_builder_error(
        message="Flow revision changed while applying the plan.",
        code=AIBuilderErrorCode.STALE_REVISION,
        request_id="req-stale",
        details={
            "expected_revision": 3,
            "current_revision": 4,
            "internal_payload": {"private": "not exported"},
            "long": "x" * 300,
        },
    )

    assert error.details == {
        "expected_revision": 3,
        "current_revision": 4,
        "long": "x" * 256,
    }


def test_split_ai_builder_error_context_separates_correlation_from_details() -> None:
    diagnostic_context, details = split_ai_builder_error_context(
        {
            "session_id": "session-1",
            "plan_id": "plan-1",
            "flow_id": "flow-1",
            "published_version": 3,
            "auth_layer": "api_key_scope",
        }
    )

    assert diagnostic_context == {
        "session_id": "session-1",
        "plan_id": "plan-1",
        "flow_id": "flow-1",
    }
    assert details == {
        "published_version": 3,
        "auth_layer": "api_key_scope",
    }
