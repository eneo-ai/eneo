from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from eneo.flows.ai_builder.ai_builder_api_models import SessionTelemetrySummary
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_telemetry import (
    _empty_session_telemetry,
    build_assistant_message_metadata,
    build_planner_telemetry,
    summarize_session_telemetry,
)
from eneo.flows.ai_builder.ai_builder_tool_names import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]
_FRONTEND_TELEMETRY_CONTRACT = (
    _REPO_ROOT
    / "frontend/apps/web/src/lib/features/flows/ai-builder/__fixtures__"
    / "sessionTelemetrySummary.json"
)


def test_summarize_session_telemetry_aggregates_planner_metadata_without_snapshot() -> (
    None
):
    conversation = [
        ConversationMessage(
            role="assistant",
            content="I need one more detail.",
            tool_calls=[
                {
                    "id": "call_question",
                    "name": "ask_structured_question",
                    "arguments": {"question_id": "final_output_mode"},
                }
            ],
            metadata={
                "planner_telemetry": {
                    "request_id": "req-1",
                    "model": "openai/gpt-4",
                    "finish_reason": "tool_calls",
                    "prompt_tokens": 10,
                    "completion_tokens": 3,
                    "total_tokens": 13,
                    "tool_call_count": 1,
                    "used_auxiliary_llm": False,
                }
            },
        )
    ]

    summary = summarize_session_telemetry(conversation)

    assert summary is not None
    assert summary["planner_request_count"] == 1
    assert summary["clarification_question_count"] == 1
    assert summary["prompt_tokens_total"] == 10
    assert summary["completion_tokens_total"] == 3
    assert summary["total_tokens_total"] == 13
    assert summary["tool_call_count_total"] == 1
    assert summary["last_request_id"] == "req-1"


def test_session_telemetry_api_model_covers_aggregator_keys() -> None:
    summary_keys = set(_empty_session_telemetry())

    assert summary_keys <= set(SessionTelemetrySummary.model_fields)


def test_session_telemetry_frontend_contract_fixture_matches_api_model() -> None:
    payload = json.loads(_FRONTEND_TELEMETRY_CONTRACT.read_text())

    assert set(payload) == set(SessionTelemetrySummary.model_fields)
    validated = SessionTelemetrySummary.model_validate(payload)
    assert validated.model_dump(mode="json") == payload


def test_build_assistant_message_metadata_advances_existing_session_summary() -> None:
    existing_conversation = [
        ConversationMessage(
            role="assistant",
            content="Previous turn.",
            metadata={
                "session_telemetry": {
                    "planner_request_count": 1,
                    "clarification_question_count": 1,
                    "prompt_tokens_total": 10,
                    "completion_tokens_total": 3,
                    "total_tokens_total": 13,
                    "tool_call_count_total": 1,
                    "auxiliary_llm_call_count": 0,
                    "last_request_id": "req-1",
                    "last_model": "openai/gpt-4",
                    "last_finish_reason": "tool_calls",
                }
            },
        )
    ]

    planner_telemetry = build_planner_telemetry(
        request_id="req-2",
        model="openai/gpt-5.4",
        finish_reason="stop",
        prompt_tokens=20,
        completion_tokens=5,
        total_tokens=25,
        tool_call_count=0,
        used_auxiliary_llm=True,
    )

    metadata = build_assistant_message_metadata(
        existing_conversation,
        planner_telemetry=planner_telemetry,
    )

    assert metadata is not None
    session_telemetry = metadata["session_telemetry"]
    assert session_telemetry["planner_request_count"] == 2
    assert session_telemetry["clarification_question_count"] == 1
    assert session_telemetry["prompt_tokens_total"] == 30
    assert session_telemetry["completion_tokens_total"] == 8
    assert session_telemetry["total_tokens_total"] == 38
    assert session_telemetry["auxiliary_llm_call_count"] == 1
    assert session_telemetry["last_request_id"] == "req-2"
    assert session_telemetry["last_model"] == "openai/gpt-5.4"


def _planner_telemetry(
    *,
    outcome_kind: str = "dispatched",
    wall_clock_ms: int = 120,
    llm_calls_made: int = 1,
    repair_attempts: int = 0,
    architecture_commit_populated: bool = False,
    prompt_tokens: int = 40,
    completion_tokens: int = 8,
    total_tokens: int = 48,
    finish_reason: str = "stop",
    request_id: str | None = "req-turn",
    model: str = "openai/gpt-5.4",
    token_usage_source: str | None = "provider",
    token_usage_estimated: bool = False,
) -> dict[str, object]:
    return build_planner_telemetry(
        request_id=request_id,
        model=model,
        finish_reason=finish_reason,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        tool_call_count=0,
        used_auxiliary_llm=False,
        token_usage_source=token_usage_source,
        token_usage_estimated=token_usage_estimated,
        outcome_kind=outcome_kind,
        wall_clock_ms=wall_clock_ms,
        llm_calls_made=llm_calls_made,
        repair_attempts=repair_attempts,
        architecture_commit_populated=architecture_commit_populated,
    )


def test_build_planner_telemetry_renders_per_turn_fields() -> None:
    rendered = build_planner_telemetry(
        request_id="req-turn",
        model="openai/gpt-5.4",
        finish_reason="stop",
        prompt_tokens=40,
        completion_tokens=8,
        total_tokens=48,
        tool_call_count=3,
        used_auxiliary_llm=True,
        token_usage_source="provider",
        token_usage_estimated=False,
        outcome_kind="dispatched",
        wall_clock_ms=210,
        llm_calls_made=2,
        repair_attempts=1,
        architecture_commit_populated=True,
    )

    assert rendered["request_id"] == "req-turn"
    assert rendered["model"] == "openai/gpt-5.4"
    assert rendered["finish_reason"] == "stop"
    assert rendered["prompt_tokens"] == 40
    assert rendered["completion_tokens"] == 8
    assert rendered["total_tokens"] == 48
    assert rendered["token_usage_source"] == "provider"
    assert rendered["token_usage_estimated"] is False
    assert rendered["tool_call_count"] == 3
    assert rendered["used_auxiliary_llm"] is True
    assert rendered["outcome_kind"] == "dispatched"
    assert rendered["wall_clock_ms"] == 210
    assert rendered["llm_calls_made"] == 2
    assert rendered["repair_attempts"] == 1
    assert rendered["architecture_commit_populated"] is True


def test_build_planner_telemetry_defaults_aux_and_tool_call_count() -> None:
    rendered = _planner_telemetry(outcome_kind="rejected")

    assert rendered["used_auxiliary_llm"] is False
    assert rendered["tool_call_count"] == 0
    assert rendered["outcome_kind"] == "rejected"
    assert rendered["architecture_commit_populated"] is False


def test_session_summary_counts_legacy_name_only_tool_call() -> None:
    summary = summarize_session_telemetry(
        [
            {
                "role": "assistant",
                "content": "Legacy question.",
                "tool_calls": [{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}],
                "metadata": {"planner_telemetry": _planner_telemetry()},
            }
        ]
    )

    assert summary is not None
    assert summary["clarification_question_count"] == 1


def test_session_summary_counts_legacy_tool_call_with_malformed_arguments() -> None:
    summary = summarize_session_telemetry(
        [
            {
                "role": "assistant",
                "content": "Legacy question.",
                "tool_calls": [
                    {
                        "id": "call_bad_args",
                        "name": ASK_STRUCTURED_QUESTION_TOOL_NAME,
                        "arguments": "{not json",
                    }
                ],
                "metadata": {"planner_telemetry": _planner_telemetry()},
            }
        ]
    )

    assert summary is not None
    assert summary["clarification_question_count"] == 1


def test_active_turn_compact_tool_call_counts_clarification_question() -> None:
    metadata = build_assistant_message_metadata(
        [],
        planner_telemetry=_planner_telemetry(),
        tool_calls=[{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}],
    )

    assert metadata is not None
    assert metadata["session_telemetry"]["clarification_question_count"] == 1


def test_active_turn_runtime_tool_call_names_are_counted_exactly() -> None:
    ask_tool_call = SimpleNamespace(
        function=SimpleNamespace(name=ASK_STRUCTURED_QUESTION_TOOL_NAME)
    )
    other_tool_call = SimpleNamespace(function=SimpleNamespace(name="propose_flow"))

    metadata = build_assistant_message_metadata(
        [],
        planner_telemetry=_planner_telemetry(),
        tool_calls=[ask_tool_call, other_tool_call, object(), {"name": "other_tool"}],
    )

    assert metadata is not None
    assert metadata["session_telemetry"]["clarification_question_count"] == 1


def test_session_summary_accumulates_per_turn_fields_from_turn_telemetry() -> None:
    first_turn = _planner_telemetry(
        outcome_kind="dispatched",
        wall_clock_ms=100,
        llm_calls_made=1,
        repair_attempts=0,
        architecture_commit_populated=True,
        request_id="req-1",
    )
    second_turn = _planner_telemetry(
        outcome_kind="rejected",
        wall_clock_ms=250,
        llm_calls_made=3,
        repair_attempts=2,
        architecture_commit_populated=False,
        request_id="req-2",
        token_usage_source="litellm_estimate",
        token_usage_estimated=True,
    )

    conversation = [
        ConversationMessage(
            role="assistant",
            content="First turn.",
            metadata={"planner_telemetry": first_turn},
        ),
        ConversationMessage(
            role="assistant",
            content="Second turn.",
            metadata={"planner_telemetry": second_turn},
        ),
    ]

    summary = summarize_session_telemetry(conversation)

    assert summary is not None
    assert summary["planner_request_count"] == 2
    assert summary["architecture_commit_count"] == 1
    assert summary["repair_attempts_total"] == 2
    assert summary["wall_clock_ms_total"] == 350
    assert summary["llm_calls_made_total"] == 4
    assert summary["token_usage_estimated"] is True
    assert summary["last_outcome_kind"] == "rejected"
    assert summary["last_request_id"] == "req-2"
    assert summary["last_token_usage_source"] == "litellm_estimate"
    assert summary["last_token_usage_estimated"] is True


def test_session_summary_rehydrates_per_turn_fields_from_snapshot() -> None:
    snapshot = {
        "planner_request_count": 4,
        "clarification_question_count": 1,
        "prompt_tokens_total": 200,
        "completion_tokens_total": 50,
        "total_tokens_total": 250,
        "tool_call_count_total": 5,
        "auxiliary_llm_call_count": 1,
        "architecture_commit_count": 1,
        "repair_attempts_total": 3,
        "wall_clock_ms_total": 780,
        "llm_calls_made_total": 6,
        "token_usage_estimated": True,
        "last_request_id": "req-last",
        "last_model": "openai/gpt-5.4",
        "last_finish_reason": "stop",
        "last_outcome_kind": "dispatched",
        "last_token_usage_source": "provider",
        "last_token_usage_estimated": False,
    }

    conversation = [
        ConversationMessage(
            role="assistant",
            content="Snapshot turn.",
            metadata={"session_telemetry": snapshot},
        )
    ]

    summary = summarize_session_telemetry(conversation)

    assert summary is not None
    assert summary["architecture_commit_count"] == 1
    assert summary["repair_attempts_total"] == 3
    assert summary["wall_clock_ms_total"] == 780
    assert summary["llm_calls_made_total"] == 6
    assert summary["token_usage_estimated"] is True
    assert summary["last_outcome_kind"] == "dispatched"
    assert summary["last_token_usage_source"] == "provider"
    assert summary["last_token_usage_estimated"] is False


def test_session_summary_sanitizes_missing_per_turn_fields_to_zero() -> None:
    legacy_snapshot = {
        "planner_request_count": 1,
        "clarification_question_count": 0,
        "prompt_tokens_total": 10,
        "completion_tokens_total": 3,
        "total_tokens_total": 13,
        "tool_call_count_total": 0,
        "auxiliary_llm_call_count": 0,
        "last_request_id": "req-legacy",
        "last_model": "openai/gpt-4",
        "last_finish_reason": "stop",
    }

    conversation = [
        ConversationMessage(
            role="assistant",
            content="Legacy snapshot.",
            metadata={"session_telemetry": legacy_snapshot},
        )
    ]

    summary = summarize_session_telemetry(conversation)

    assert summary is not None
    assert summary["architecture_commit_count"] == 0
    assert summary["repair_attempts_total"] == 0
    assert summary["wall_clock_ms_total"] == 0
    assert summary["llm_calls_made_total"] == 0
    assert summary["token_usage_estimated"] is False
    assert summary["last_outcome_kind"] is None
    assert summary["last_token_usage_source"] is None
    assert summary["last_token_usage_estimated"] is False


def test_session_summary_clamps_negative_additive_deltas_per_turn() -> None:
    """Per-turn planner telemetry with negative deltas must not decrement totals.

    A malformed `planner_telemetry` dict (wire corruption, legacy helper
    bug, synthetic fixture) with `prompt_tokens=-50`, `wall_clock_ms=-100`,
    etc. would otherwise subtract from the in-memory summary on
    accumulation. The rehydration clamp fires only on snapshot load —
    this test locks the additive path.
    """
    corrupt_turn = {
        "request_id": "req-corrupt",
        "model": "openai/gpt-5.4",
        "finish_reason": "stop",
        "prompt_tokens": -50,
        "completion_tokens": -10,
        "total_tokens": -60,
        "tool_call_count": -3,
        "used_auxiliary_llm": False,
        "outcome_kind": "dispatched",
        "wall_clock_ms": -100,
        "llm_calls_made": -2,
        "repair_attempts": -1,
        "architecture_commit_populated": False,
    }
    clean_turn = _planner_telemetry(
        outcome_kind="dispatched",
        wall_clock_ms=80,
        llm_calls_made=1,
        repair_attempts=0,
        prompt_tokens=30,
        completion_tokens=5,
        total_tokens=35,
        request_id="req-clean",
    )

    conversation = [
        ConversationMessage(
            role="assistant",
            content="Corrupt turn.",
            metadata={"planner_telemetry": corrupt_turn},
        ),
        ConversationMessage(
            role="assistant",
            content="Clean turn.",
            metadata={"planner_telemetry": clean_turn},
        ),
    ]

    summary = summarize_session_telemetry(conversation)

    assert summary is not None
    # Corrupt turn contributed zero to every cumulative counter.
    assert summary["planner_request_count"] == 2
    assert summary["prompt_tokens_total"] == 30
    assert summary["completion_tokens_total"] == 5
    assert summary["total_tokens_total"] == 35
    assert summary["tool_call_count_total"] == 0
    assert summary["wall_clock_ms_total"] == 80
    assert summary["llm_calls_made_total"] == 1
    assert summary["repair_attempts_total"] == 0


def test_session_summary_clamps_negative_counters_on_rehydration() -> None:
    """Corrupted snapshots with negative counts must clamp to 0, not pollute.

    If a prior write produced a `-1` (bug, race, or partial write), the
    aggregator would otherwise continue accumulating from the polluted base.
    """
    corrupted_snapshot = {
        "planner_request_count": -5,
        "clarification_question_count": -1,
        "prompt_tokens_total": -100,
        "completion_tokens_total": -3,
        "total_tokens_total": -10,
        "tool_call_count_total": -2,
        "auxiliary_llm_call_count": -1,
        "architecture_commit_count": -1,
        "repair_attempts_total": -7,
        "wall_clock_ms_total": -500,
        "llm_calls_made_total": -3,
        "last_request_id": "req-corrupted",
        "last_model": "openai/gpt-4",
        "last_finish_reason": "stop",
        "last_outcome_kind": "dispatched",
    }

    conversation = [
        ConversationMessage(
            role="assistant",
            content="Corrupted snapshot.",
            metadata={"session_telemetry": corrupted_snapshot},
        )
    ]

    summary = summarize_session_telemetry(conversation)

    assert summary is not None
    for field in (
        "planner_request_count",
        "clarification_question_count",
        "prompt_tokens_total",
        "completion_tokens_total",
        "total_tokens_total",
        "tool_call_count_total",
        "auxiliary_llm_call_count",
        "architecture_commit_count",
        "repair_attempts_total",
        "wall_clock_ms_total",
        "llm_calls_made_total",
    ):
        assert summary[field] == 0, f"{field} should clamp negative to 0"
    assert summary["last_outcome_kind"] == "dispatched"
    assert summary["last_request_id"] == "req-corrupted"
