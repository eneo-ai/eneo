from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_error_contract import (
    _MAX_DETAILS_JSON_BYTES,  # pyright: ignore[reportPrivateUsage]
    _MAX_DETAILS_KEYS,  # pyright: ignore[reportPrivateUsage]
    AI_BUILDER_ERROR_REGISTRY,
    AIBuilderBadRequestException,
    AIBuilderDiagnosticContext,
    AIBuilderErrorCode,
    AIBuilderErrorEvent,
    AIBuilderErrorPhase,
    AIBuilderNotFoundException,
    AIBuilderPublicError,
    AIBuilderUnauthorizedException,
    build_ai_builder_error,
    build_ai_builder_error_event,
    split_ai_builder_error_context,
    with_ai_builder_call_evidence,
)
from eneo.flows.ai_builder.ai_builder_events import encode_ai_builder_stream_event
from eneo.main.exceptions import ErrorCodes


def test_error_registry_has_entry_for_every_error_code_enum_member() -> None:
    assert set(AI_BUILDER_ERROR_REGISTRY) == set(AIBuilderErrorCode)


def test_planning_state_payload_too_large_is_a_planner_bad_request() -> None:
    code = AIBuilderErrorCode("planning_state_payload_too_large")
    entry = AI_BUILDER_ERROR_REGISTRY[code]

    assert entry.category.value == "bad_request"
    assert entry.default_phase is AIBuilderErrorPhase.PLANNER


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
    event = encode_ai_builder_stream_event(
        build_ai_builder_error_event(
            message="The AI planner failed. Please try again.",
            code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
            phase=AIBuilderErrorPhase.PLANNER,
            request_id="req-ai-builder-1",
            diagnostic_context={"model": "gpt-5.4"},
            details={"retryable": True},
        )
    )

    assert event["event"] == "error"
    payload = json.loads(event["data"])
    assert payload == {
        "schema_version": 2,
        "code": "planner_upstream_error",
        "category": "upstream",
        "message": "The AI planner failed. Please try again.",
        "phase": "planner",
        "eneo_error_code": int(ErrorCodes.INTERNAL_SERVER_ERROR),
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
        assert round_tripped.eneo_error_code is registry_entry.eneo_error_code


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
            eneo_error_code=ErrorCodes.BAD_REQUEST,
            request_id="req-context",
            details=details,
        )


# The turn's call evidence in the priority order the telemetry owns.
_CALL_EVIDENCE: dict[str, object] = {
    "last_response_finish_reason": "content_filter",
    "last_call_output_cap_tokens": 10**9,
    "token_usage_source": "litellm_estimate",
    "calls_without_usage": 99,
    "turn_reasoning_tokens": 10**14,
    "turn_completion_tokens": 10**14,
    "turn_prompt_tokens": 10**14,
    "llm_calls": 99,
}


def _error_with_details(details: dict[str, object]) -> AIBuilderErrorEvent:
    return build_ai_builder_error_event(
        message="The AI planner failed.",
        code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
        request_id="req-evidence",
        details=details,
    )


def _json_size(details: dict[str, object]) -> int:
    return len(json.dumps(details, ensure_ascii=False).encode("utf-8"))


def test_the_persisted_details_bound_is_ten_keys_and_1024_bytes() -> None:
    # Older builds validate a persisted error against this exact bound, so call
    # evidence has to fit inside it; widening it makes their session reads fail.
    assert (_MAX_DETAILS_KEYS, _MAX_DETAILS_JSON_BYTES) == (10, 1024)


def _public_error_with_details(details: dict[str, object]) -> AIBuilderPublicError:
    return AIBuilderPublicError(
        message="Sized details",
        code=AIBuilderErrorCode.BAD_REQUEST,
        category=AI_BUILDER_ERROR_REGISTRY[AIBuilderErrorCode.BAD_REQUEST].category,
        phase=AIBuilderErrorPhase.ROUTER,
        eneo_error_code=ErrorCodes.BAD_REQUEST,
        request_id="req-sized",
        details=details,
    )


def _details_of_json_size(size: int) -> dict[str, object]:
    details: dict[str, object] = {f"k{i}": "x" * 200 for i in range(4)}
    # `, "k4": ""` adds ten bytes around the padding.
    details["k4"] = "y" * (size - _json_size(details) - 10)
    assert _json_size(details) == size
    return details


def test_error_details_are_bounded_at_1024_bytes() -> None:
    assert _public_error_with_details(_details_of_json_size(1024)).details

    with pytest.raises(ValidationError, match="1024 bytes"):
        _public_error_with_details(_details_of_json_size(1025))


@pytest.mark.parametrize("own_key_count", [0, 1, 2, 3, 5, 9, 10])
def test_call_evidence_fills_the_capacity_the_own_details_leave(
    own_key_count: int,
) -> None:
    own = {f"own_{i}": i for i in range(own_key_count)}
    event = _error_with_details(own)
    room = _MAX_DETAILS_KEYS - own_key_count
    kept = dict(list(_CALL_EVIDENCE.items())[:room])

    enriched = with_ai_builder_call_evidence(event, _CALL_EVIDENCE)

    assert enriched.data.details == ({**own, **kept} or None)
    assert list(enriched.data.details or {}) == [*own, *kept]
    if not kept:
        assert enriched is event
    # The enriched error still fits the bound older builds validate against.
    assert (
        AIBuilderPublicError.model_validate(enriched.data.model_dump(mode="json"))
        == enriched.data
    )


def test_call_evidence_stops_at_the_first_key_the_byte_bound_cannot_hold() -> None:
    own = {f"own_{i}": "x" * 250 for i in range(3)}
    event = _error_with_details(own)
    assert event.data.details == own
    fitting: dict[str, object] = {}
    for key, value in _CALL_EVIDENCE.items():
        if _json_size({**own, **fitting, key: value}) > _MAX_DETAILS_JSON_BYTES:
            break
        fitting[key] = value
    # The bytes, not the ten keys, are what stops the evidence.
    assert 0 < len(fitting) < _MAX_DETAILS_KEYS - len(own)

    enriched = with_ai_builder_call_evidence(event, _CALL_EVIDENCE)

    assert enriched.data.details == {**own, **fitting}


def test_call_evidence_never_overwrites_an_own_detail_key() -> None:
    own = {"llm_calls": "own value", "retry_scope": "new_turn"}

    enriched = with_ai_builder_call_evidence(_error_with_details(own), _CALL_EVIDENCE)

    assert enriched.data.details is not None
    assert enriched.data.details["llm_calls"] == "own value"
    assert list(enriched.data.details)[:2] == ["llm_calls", "retry_scope"]
    assert {
        key: value for key, value in enriched.data.details.items() if key not in own
    } == {key: value for key, value in _CALL_EVIDENCE.items() if key not in own}


def test_an_unserialisable_count_is_dropped_never_raised() -> None:
    too_many_digits = 10**4300
    evidence = {**_CALL_EVIDENCE, "turn_prompt_tokens": too_many_digits}

    enriched = with_ai_builder_call_evidence(_error_with_details({}), evidence)

    assert enriched.data.details == {
        key: value for key, value in evidence.items() if key != "turn_prompt_tokens"
    }
    assert _error_with_details({"own": too_many_digits, "kept": 1}).data.details == {
        "kept": 1
    }


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
