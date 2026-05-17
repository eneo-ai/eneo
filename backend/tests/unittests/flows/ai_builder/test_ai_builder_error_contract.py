from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_error_contract import (
    AI_BUILDER_ERROR_REGISTRY,
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    AIBuilderPublicError,
    build_ai_builder_error,
    build_ai_builder_error_event,
)
from intric.main.exceptions import ErrorCodes


def test_error_registry_has_entry_for_every_error_code_enum_member() -> None:
    assert set(AI_BUILDER_ERROR_REGISTRY) == set(AIBuilderErrorCode)


def test_error_event_serializes_to_public_v1_schema() -> None:
    event = build_ai_builder_error_event(
        message="The AI planner failed. Please try again.",
        code=AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR,
        phase=AIBuilderErrorPhase.PLANNER,
        request_id="req-ai-builder-1",
        context={"retryable": True, "model": "gpt-5.4"},
    )

    assert event["event"] == "error"
    payload = json.loads(event["data"])
    assert payload == {
        "schema_version": 1,
        "code": "planner_upstream_error",
        "category": "upstream",
        "message": "The AI planner failed. Please try again.",
        "phase": "planner",
        "intric_error_code": int(ErrorCodes.INTERNAL_SERVER_ERROR),
        "request_id": "req-ai-builder-1",
        "context": {"retryable": True, "model": "gpt-5.4"},
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
    "context",
    [
        {"nested": {"value": "not public"}},
        {"items": ["not", "public"]},
        {"too_long": "x" * 257},
        {f"k{i}": i for i in range(11)},
    ],
)
def test_error_context_rejects_nested_or_oversized_values(
    context: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AIBuilderPublicError(
            message="Invalid context",
            code=AIBuilderErrorCode.BAD_REQUEST,
            category=AI_BUILDER_ERROR_REGISTRY[
                AIBuilderErrorCode.BAD_REQUEST
            ].category,
            phase=AIBuilderErrorPhase.ROUTER,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            request_id="req-context",
            context=context,
        )


def test_build_ai_builder_error_sanitizes_internal_context() -> None:
    error = build_ai_builder_error(
        message="Flow revision changed while applying the plan.",
        code=AIBuilderErrorCode.STALE_REVISION,
        request_id="req-stale",
        context={
            "expected_revision": 3,
            "current_revision": 4,
            "internal_payload": {"private": "not exported"},
            "long": "x" * 300,
        },
    )

    assert error.context == {
        "expected_revision": 3,
        "current_revision": 4,
        "long": "x" * 256,
    }
