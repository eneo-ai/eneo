from __future__ import annotations

from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_telemetry import (
    build_assistant_message_metadata,
    build_planner_telemetry,
    summarize_session_telemetry,
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
