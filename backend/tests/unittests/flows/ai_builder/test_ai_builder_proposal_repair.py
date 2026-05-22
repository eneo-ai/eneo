from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_proposal_processor import (
    MAX_SELF_CORRECTION_RETRIES,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    ForcedToolRetryOutcome,
    _build_retry_feedback,
    request_self_correction,
    retry_forced_tool_after_text,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ToolProcessingFailureKind,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ToolProcessingResult,
    ToolRetryInvocation,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)


def _tool_response(*, tool_name: str, arguments: dict[str, object]) -> SimpleNamespace:
    tool_call = SimpleNamespace(
        id="call_create",
        function=SimpleNamespace(
            name=tool_name,
            arguments=json.dumps(arguments),
        ),
    )
    message = SimpleNamespace(content=None, tool_calls=[tool_call])
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def _bad_tool_response(call_index: int) -> SimpleNamespace:
    tool_call = SimpleNamespace(
        id=f"retry_{call_index}",
        function=SimpleNamespace(
            name="outline_flow",
            arguments=json.dumps(
                {"flow_name": "T", "plan_rationale": "R", "steps": []}
            ),
        ),
    )
    message = SimpleNamespace(content="", tool_calls=[tool_call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _original_tool_call() -> SimpleNamespace:
    return SimpleNamespace(
        id="orig",
        function=SimpleNamespace(name="outline_flow", arguments="{}"),
    )


def _make_turn() -> SessionSendTurn:
    return SessionSendTurn(
        session_id=uuid4(),
        tenant_id=uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=3,
    )


@pytest.mark.asyncio
async def test_retry_forced_tool_after_text_builds_typed_invocation() -> None:
    turn = _make_turn()
    captured_invocation: ToolRetryInvocation | None = None

    async def process_invocation(
        invocation: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        nonlocal captured_invocation
        captured_invocation = invocation
        return ToolProcessingResult(
            event={"event": "plan", "data": "{}"},
        )

    result = await retry_forced_tool_after_text(
        correction_messages=[{"role": "system", "content": "Prompt"}],
        assistant_text="Här är mitt förslag.",
        tool_schemas=[{"function": {"name": "outline_flow"}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        turn=turn,
        conversation=[],
        new_messages_start=0,
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        target_tool_name="outline_flow",
        forced_tool_prompt="Call outline_flow.",
        forced_proposal_temperature=0.1,
        call_proposal_completion=AsyncMock(
            return_value=_tool_response(
                tool_name="outline_flow",
                arguments={"flow_name": "Test", "plan_rationale": "R", "steps": []},
            )
        ),
        process_tool_invocation=process_invocation,
        flow=None,
        resource_catalog=None,
        build_assistant_metadata=lambda: {"planner_telemetry": {"request_id": "req"}},
    )

    assert result.events == ({"event": "plan", "data": "{}"},)
    assert captured_invocation is not None
    assert captured_invocation.turn is turn
    assert captured_invocation.arguments["flow_name"] == "Test"
    assert captured_invocation.flow is None
    assert captured_invocation.resource_catalog is None
    assert captured_invocation.assistant_metadata == {
        "planner_telemetry": {"request_id": "req"}
    }


@pytest.mark.asyncio
async def test_retry_forced_tool_after_text_surfaces_tool_user_message() -> None:
    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return ToolProcessingResult(
            user_message="Det markerade steget använder ingen chattmodell."
        )

    result = await retry_forced_tool_after_text(
        correction_messages=[{"role": "system", "content": "Prompt"}],
        assistant_text="Här är mitt förslag.",
        tool_schemas=[{"function": {"name": "outline_flow"}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        turn=_make_turn(),
        conversation=[],
        new_messages_start=0,
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        target_tool_name="outline_flow",
        forced_tool_prompt="Call outline_flow.",
        forced_proposal_temperature=0.1,
        call_proposal_completion=AsyncMock(
            return_value=_tool_response(
                tool_name="outline_flow",
                arguments={"flow_name": "Test", "plan_rationale": "R", "steps": []},
            )
        ),
        process_tool_invocation=process_invocation,
        flow=None,
        resource_catalog=None,
    )

    assert result.events == (
        {
            "event": "text",
            "data": '{"text":"Det markerade steget använder ingen chattmodell."}',
        },
    )


@pytest.mark.asyncio
async def test_retry_forced_tool_after_text_accepts_json_arguments_returned_as_text() -> (
    None
):
    processed_arguments: dict[str, object] = {}
    call_proposal_completion = AsyncMock()
    turn = _make_turn()

    async def process_invocation(
        invocation: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        processed_arguments.update(invocation.arguments)
        return ToolProcessingResult(event={"event": "plan", "data": "{}"})

    result = await retry_forced_tool_after_text(
        correction_messages=[{"role": "system", "content": "Prompt"}],
        assistant_text=json.dumps(
            {
                "flow_name": "Text JSON outline",
                "plan_rationale": "The model returned JSON as prose.",
                "steps": [{"name": "Analyze", "task": "Analyze the input."}],
            }
        ),
        tool_schemas=[{"function": {"name": "outline_flow"}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        turn=turn,
        conversation=[],
        new_messages_start=0,
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        target_tool_name="outline_flow",
        forced_tool_prompt="Call outline_flow.",
        forced_proposal_temperature=0.1,
        call_proposal_completion=call_proposal_completion,
        process_tool_invocation=process_invocation,
        flow=None,
    )

    assert result.events == ({"event": "plan", "data": "{}"},)
    assert processed_arguments["flow_name"] == "Text JSON outline"
    call_proposal_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_forced_tool_after_text_preserves_json_text_validation_feedback() -> (
    None
):
    call_proposal_completion = AsyncMock()
    turn = _make_turn()

    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return ToolProcessingResult(
            feedback="Validation errors:\n1. Missing required field report_period.",
            failure_kind="validation",
        )

    result = await retry_forced_tool_after_text(
        correction_messages=[{"role": "system", "content": "Prompt"}],
        assistant_text=json.dumps(
            {
                "flow_name": "Invalid text JSON outline",
                "plan_rationale": "The model returned invalid JSON as prose.",
                "steps": [],
            }
        ),
        tool_schemas=[{"function": {"name": "outline_flow"}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        turn=turn,
        conversation=[],
        new_messages_start=0,
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        target_tool_name="outline_flow",
        forced_tool_prompt="Call outline_flow.",
        forced_proposal_temperature=0.1,
        call_proposal_completion=call_proposal_completion,
        process_tool_invocation=process_invocation,
        flow=None,
    )

    assert result.events is None
    assert result.feedback == (
        "Validation errors:\n1. Missing required field report_period."
    )
    assert result.failure_kind == "validation"
    call_proposal_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_forced_tool_after_text_preserves_forced_payload_parse_feedback() -> (
    None
):
    turn = _make_turn()
    tool_call = SimpleNamespace(
        id="call_invalid",
        function=SimpleNamespace(name="outline_flow", arguments="{not json"),
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=[tool_call])
            )
        ]
    )

    result = await retry_forced_tool_after_text(
        correction_messages=[{"role": "system", "content": "Prompt"}],
        assistant_text="Här är mitt förslag.",
        tool_schemas=[{"function": {"name": "outline_flow"}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        turn=turn,
        conversation=[],
        new_messages_start=0,
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        target_tool_name="outline_flow",
        forced_tool_prompt="Call outline_flow.",
        forced_proposal_temperature=0.1,
        call_proposal_completion=AsyncMock(return_value=response),
        process_tool_invocation=AsyncMock(),
        flow=None,
    )

    assert result.events is None
    assert result.feedback is not None
    assert "Invalid tool call arguments:" in result.feedback
    assert "Expecting property name enclosed" in result.feedback
    assert result.failure_kind == "parse"


@pytest.mark.asyncio
async def test_retry_forced_tool_after_text_preserves_information_request_empty_outcome() -> (
    None
):
    call_proposal_completion = AsyncMock()
    turn = _make_turn()

    result = await retry_forced_tool_after_text(
        correction_messages=[{"role": "system", "content": "Prompt"}],
        assistant_text="Vilken modell ska jag använda?",
        tool_schemas=[{"function": {"name": "outline_flow"}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        turn=turn,
        conversation=[],
        new_messages_start=0,
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        target_tool_name="outline_flow",
        forced_tool_prompt="Call outline_flow.",
        forced_proposal_temperature=0.1,
        call_proposal_completion=call_proposal_completion,
        process_tool_invocation=AsyncMock(),
        flow=None,
    )

    assert result == ForcedToolRetryOutcome()
    call_proposal_completion.assert_not_awaited()


def test_max_self_correction_retries_budgets_three_retries() -> None:
    assert MAX_SELF_CORRECTION_RETRIES == 3


def test_build_retry_feedback_uses_standard_preamble_on_first_retry() -> None:
    feedback = _build_retry_feedback(
        target_tool_name="outline_flow",
        feedback="missing field X",
        failure_kind="validation",
        retry_count=1,
    )
    assert feedback.startswith("CORRECTION STILL INVALID:")
    assert "FINAL CORRECTION ATTEMPT" not in feedback


def test_build_retry_feedback_escalates_to_stronger_preamble_on_second_retry() -> None:
    feedback = _build_retry_feedback(
        target_tool_name="outline_flow",
        feedback="missing field X",
        failure_kind="validation",
        retry_count=2,
    )
    assert feedback.startswith("FINAL CORRECTION ATTEMPT")
    assert "missing field X" in feedback


def test_build_retry_feedback_keeps_stronger_preamble_on_third_retry() -> None:
    feedback = _build_retry_feedback(
        target_tool_name="outline_flow",
        feedback="missing field X",
        failure_kind="validation",
        retry_count=3,
    )
    assert feedback.startswith("FINAL CORRECTION ATTEMPT")


async def _run_repair_capturing(
    *,
    max_retries: int,
    failure_kind: str = "validation",
    failure_codes: frozenset[str] = frozenset(),
    base_temperature: float = 0.35,
    bumped_temperature: float = 0.6,
) -> tuple[list[float], list[str], list[dict[str, str]]]:
    observed_temperatures: list[float] = []
    observed_retry_feedback: list[str] = []

    async def call_proposal_completion(
        *,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        max_output_tokens: int,
        temperature: float,
    ) -> SimpleNamespace:
        observed_temperatures.append(temperature)
        for msg in reversed(messages):
            if msg.get("role") == "tool":
                observed_retry_feedback.append(str(msg.get("content", "")))
                break
        return _bad_tool_response(len(observed_temperatures))

    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return ToolProcessingResult(
            feedback="still bad",
            failure_kind=failure_kind,
            failure_codes=failure_codes,
        )

    events: list[dict[str, str]] = []
    async for event in request_self_correction(
        turn=_make_turn(),
        conversation=[],
        new_messages_start=0,
        error_message="original invalid",
        llm_messages=[{"role": "user", "content": "go"}],
        tool_call=_original_tool_call(),
        tool_schemas=[{"function": {"name": "outline_flow"}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        self_correction_temperature=base_temperature,
        self_correction_bumped_temperature=bumped_temperature,
        max_self_correction_retries=max_retries,
        call_proposal_completion=call_proposal_completion,
        process_tool_invocation=process_invocation,
        target_tool_name="outline_flow",
        forced_tool_prompt="Call outline_flow.",
        build_self_correction_error_event=lambda *,
        feedback,
        failure_kind,
        request_id=None: {
            "event": "error",
            "data": feedback or "",
        },
        retry_forced_tool_after_text=AsyncMock(return_value=ForcedToolRetryOutcome()),
        flow=None,
    ):
        events.append(event)

    return observed_temperatures, observed_retry_feedback, events


@pytest.mark.asyncio
async def test_request_self_correction_uses_base_temperature_on_initial_correction() -> (
    None
):
    temps, _, _ = await _run_repair_capturing(
        max_retries=3, base_temperature=0.35, bumped_temperature=0.6
    )
    assert temps[0] == 0.35


@pytest.mark.asyncio
async def test_request_self_correction_bumps_temperature_from_first_retry_onward() -> (
    None
):
    temps, _, _ = await _run_repair_capturing(
        max_retries=3, base_temperature=0.35, bumped_temperature=0.6
    )
    # With max_retries=3 the repair loop performs exactly one initial correction
    # plus three retries before giving up, for four total LLM calls. Keep this
    # pinned so a future refactor cannot silently extend the budget.
    assert temps == [0.35, 0.6, 0.6, 0.6]


@pytest.mark.asyncio
async def test_request_self_correction_grants_one_extra_retry_for_recoverable_parse() -> (
    None
):
    temps, retry_feedback, events = await _run_repair_capturing(
        max_retries=3,
        failure_kind="recoverable_parse",
        base_temperature=0.35,
        bumped_temperature=0.6,
    )

    assert temps == [0.35, 0.6, 0.6, 0.6, 0.6]
    assert len(retry_feedback) == 5
    assert retry_feedback[0].startswith("VALIDATION FAILED")
    assert retry_feedback[1].startswith("CORRECTION STILL INVALID:")
    assert retry_feedback[2].startswith("FINAL CORRECTION ATTEMPT")
    assert retry_feedback[3].startswith("FINAL CORRECTION ATTEMPT")
    assert retry_feedback[4].startswith("FINAL CORRECTION ATTEMPT")
    assert events[-1] == {"event": "error", "data": "still bad"}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["parse", "validation", "quality"])
async def test_request_self_correction_rejects_non_extra_failure_after_normal_budget(
    failure_kind: str,
) -> None:
    temps, retry_feedback, events = await _run_repair_capturing(
        max_retries=3,
        failure_kind=failure_kind,
        base_temperature=0.35,
        bumped_temperature=0.6,
    )

    assert temps == [0.35, 0.6, 0.6, 0.6]
    assert len(retry_feedback) == 4
    assert events[-1] == {"event": "error", "data": "still bad"}


@pytest.mark.asyncio
async def test_request_self_correction_adds_duplicate_name_outline_guidance() -> None:
    _, retry_feedback, _ = await _run_repair_capturing(
        max_retries=1,
        failure_kind="validation",
        failure_codes=frozenset({"duplicate_step_name"}),
    )

    assert len(retry_feedback) == 2
    assert "Every steps[] name must be unique case-insensitively" in retry_feedback[1]


@pytest.mark.asyncio
async def test_request_self_correction_emits_error_event_when_planner_bails_to_conversational_text() -> (
    None
):
    text_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        "Jag försökte skapa flödet men backend-valideringen stoppade mig: "
                        "flera av output_fields överskrider max-nästningsnivån. "
                        "Säg bara 'OK, platta ut JSON-fälten' så bygger jag om planen."
                    ),
                    tool_calls=None,
                )
            )
        ]
    )

    async def call_proposal_completion(**_: Any) -> SimpleNamespace:
        return text_response

    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return ToolProcessingResult(feedback="still bad", failure_kind="validation")

    events: list[dict[str, str]] = []
    async for event in request_self_correction(
        turn=_make_turn(),
        conversation=[],
        new_messages_start=0,
        error_message="Structured field nesting depth cannot exceed 3.",
        llm_messages=[{"role": "user", "content": "build flow"}],
        tool_call=_original_tool_call(),
        tool_schemas=[{"function": {"name": "outline_flow"}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        self_correction_temperature=0.35,
        self_correction_bumped_temperature=0.6,
        max_self_correction_retries=3,
        call_proposal_completion=call_proposal_completion,
        process_tool_invocation=process_invocation,
        target_tool_name="outline_flow",
        forced_tool_prompt="Call outline_flow.",
        build_self_correction_error_event=lambda *,
        feedback,
        failure_kind,
        request_id=None: {
            "event": "error",
            "data": feedback or "",
        },
        retry_forced_tool_after_text=AsyncMock(return_value=ForcedToolRetryOutcome()),
        flow=None,
    ):
        events.append(event)

    text_events = [event for event in events if event.get("event") == "text"]
    error_events = [event for event in events if event.get("event") == "error"]

    assert text_events == [], (
        "Self-correction must not leak conversational bail text to the user; "
        f"found text events: {text_events}"
    )
    assert error_events, (
        "Self-correction must emit an error event when forced-retry cannot recover; "
        f"got events: {events}"
    )
    combined_payload = " ".join(str(event.get("data", "")) for event in error_events)
    assert "Säg bara" not in combined_payload, (
        "The planner's conversational bail must not be surfaced inside the "
        f"error event payload; got: {combined_payload}"
    )
    assert "platta ut JSON-fälten" not in combined_payload, (
        f"The planner's bail phrasing must not reach the user; got: {combined_payload}"
    )


@pytest.mark.asyncio
async def test_request_self_correction_includes_forced_retry_validation_feedback() -> (
    None
):
    text_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="Här är en korrigerad plan.",
                    tool_calls=None,
                )
            )
        ]
    )

    async def call_proposal_completion(**_: Any) -> SimpleNamespace:
        return text_response

    forced_retry = AsyncMock(
        return_value=ForcedToolRetryOutcome(
            feedback="Validation errors:\n1. Invalid step reference 'step_k'.",
            failure_kind="validation",
        )
    )
    observed_request_ids: list[str | None] = []

    def build_self_correction_error_event(
        *,
        feedback: str | None,
        failure_kind: ToolProcessingFailureKind | None,
        request_id: str | None = None,
    ) -> dict[str, str]:
        observed_request_ids.append(request_id)
        return {
            "event": "error",
            "data": feedback or "",
        }

    events: list[dict[str, str]] = []
    async for event in request_self_correction(
        turn=_make_turn(),
        request_id="req-repair-feedback",
        conversation=[],
        new_messages_start=0,
        error_message="Invalid outline_flow draft.",
        llm_messages=[{"role": "user", "content": "build flow"}],
        tool_call=_original_tool_call(),
        tool_schemas=[{"function": {"name": "outline_flow"}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        self_correction_temperature=0.35,
        self_correction_bumped_temperature=0.6,
        max_self_correction_retries=0,
        call_proposal_completion=call_proposal_completion,
        process_tool_invocation=AsyncMock(),
        target_tool_name="outline_flow",
        forced_tool_prompt="Call outline_flow.",
        build_self_correction_error_event=build_self_correction_error_event,
        retry_forced_tool_after_text=forced_retry,
        flow=None,
    ):
        events.append(event)

    assert events[-1] == {
        "event": "error",
        "data": "Validation errors:\n1. Invalid step reference 'step_k'.",
    }
    assert observed_request_ids == ["req-repair-feedback"]
    forced_retry.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_self_correction_retries_forced_retry_validation_feedback() -> (
    None
):
    text_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "plan_rationale": "Try to repair as plain JSON.",
                            "operations": [],
                        }
                    ),
                    tool_calls=None,
                )
            )
        ]
    )
    tool_response = _tool_response(
        tool_name="outline_flow",
        arguments={
            "flow_name": "Valid repaired flow",
            "plan_rationale": "Repair duplicate names.",
            "steps": [{"name": "Unique step", "task": "Do the work."}],
        },
    )
    responses = [text_response, tool_response]
    observed_messages: list[list[dict[str, Any]]] = []

    async def call_proposal_completion(
        *,
        messages: list[dict[str, Any]],
        **_: Any,
    ) -> SimpleNamespace:
        observed_messages.append(messages)
        return responses.pop(0)

    forced_retry = AsyncMock(
        return_value=ForcedToolRetryOutcome(
            feedback="Compiled edit spec validation failed: Duplicate step name 'Förbered DOCX-innehåll'.",
            failure_kind="validation",
        )
    )

    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return ToolProcessingResult(event={"event": "plan", "data": "{}"})

    events: list[dict[str, str]] = []
    async for event in request_self_correction(
        turn=_make_turn(),
        conversation=[],
        new_messages_start=0,
        error_message="Invalid edit_flow draft.",
        llm_messages=[{"role": "user", "content": "edit flow"}],
        tool_call=_original_tool_call(),
        tool_schemas=[{"function": {"name": "outline_flow"}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        self_correction_temperature=0.35,
        self_correction_bumped_temperature=0.6,
        max_self_correction_retries=3,
        call_proposal_completion=call_proposal_completion,
        process_tool_invocation=process_invocation,
        target_tool_name="outline_flow",
        forced_tool_prompt="Call outline_flow.",
        build_self_correction_error_event=lambda *,
        feedback,
        failure_kind,
        request_id=None: {
            "event": "error",
            "data": feedback or "",
        },
        retry_forced_tool_after_text=forced_retry,
        flow=None,
    ):
        events.append(event)

    assert events[-1] == {"event": "plan", "data": "{}"}
    assert len(observed_messages) == 2
    retry_feedback = observed_messages[1][-1]
    assert retry_feedback["role"] == "user"
    assert "Duplicate step name" in str(retry_feedback["content"])
    forced_retry.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_self_correction_limits_text_feedback_retry_budget() -> None:
    text_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "plan_rationale": "Still returning plain JSON.",
                            "operations": [],
                        }
                    ),
                    tool_calls=None,
                )
            )
        ]
    )
    observed_messages: list[list[dict[str, Any]]] = []

    async def call_proposal_completion(
        *,
        messages: list[dict[str, Any]],
        **_: Any,
    ) -> SimpleNamespace:
        observed_messages.append(messages)
        return text_response

    forced_retry = AsyncMock(
        return_value=ForcedToolRetryOutcome(
            feedback="Compiled edit spec validation failed: duplicate step name.",
            failure_kind="validation",
        )
    )

    events: list[dict[str, str]] = []
    async for event in request_self_correction(
        turn=_make_turn(),
        conversation=[],
        new_messages_start=0,
        error_message="Invalid edit_flow draft.",
        llm_messages=[{"role": "user", "content": "edit flow"}],
        tool_call=_original_tool_call(),
        tool_schemas=[{"function": {"name": "outline_flow"}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        self_correction_temperature=0.35,
        self_correction_bumped_temperature=0.6,
        max_self_correction_retries=3,
        call_proposal_completion=call_proposal_completion,
        process_tool_invocation=AsyncMock(),
        target_tool_name="outline_flow",
        forced_tool_prompt="Call outline_flow.",
        build_self_correction_error_event=lambda *,
        feedback,
        failure_kind,
        request_id=None: {
            "event": "error",
            "data": feedback or "",
        },
        retry_forced_tool_after_text=forced_retry,
        flow=None,
    ):
        events.append(event)

    assert events[-1] == {
        "event": "error",
        "data": "Compiled edit spec validation failed: duplicate step name.",
    }
    assert len(observed_messages) == 2
    assert forced_retry.await_count == 2
    retry_feedback = observed_messages[1][-1]
    assert retry_feedback["role"] == "user"
    assert "duplicate step name" in str(retry_feedback["content"])


@pytest.mark.asyncio
async def test_request_self_correction_still_yields_text_for_legitimate_info_request() -> (
    None
):
    info_request_text = "Vilken modell ska jag använda?"
    text_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=info_request_text,
                    tool_calls=None,
                )
            )
        ]
    )

    async def call_proposal_completion(**_: Any) -> SimpleNamespace:
        return text_response

    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return ToolProcessingResult(feedback="still bad", failure_kind="validation")

    events: list[dict[str, str]] = []
    async for event in request_self_correction(
        turn=_make_turn(),
        conversation=[],
        new_messages_start=0,
        error_message="original invalid",
        llm_messages=[{"role": "user", "content": "go"}],
        tool_call=_original_tool_call(),
        tool_schemas=[{"function": {"name": "outline_flow"}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        self_correction_temperature=0.35,
        self_correction_bumped_temperature=0.6,
        max_self_correction_retries=3,
        call_proposal_completion=call_proposal_completion,
        process_tool_invocation=process_invocation,
        target_tool_name="outline_flow",
        forced_tool_prompt="Call outline_flow.",
        build_self_correction_error_event=lambda *,
        feedback,
        failure_kind,
        request_id=None: {
            "event": "error",
            "data": feedback or "",
        },
        retry_forced_tool_after_text=AsyncMock(return_value=ForcedToolRetryOutcome()),
        flow=None,
    ):
        events.append(event)

    text_events = [event for event in events if event.get("event") == "text"]
    assert text_events, (
        "Short, question-mark-bearing planner text without action keywords "
        "is a legitimate clarification request and must still surface to the user; "
        f"got events: {events}"
    )


@pytest.mark.asyncio
async def test_request_self_correction_applies_stronger_prompt_on_second_retry() -> (
    None
):
    _, retry_feedback, _ = await _run_repair_capturing(
        max_retries=3, base_temperature=0.35, bumped_temperature=0.6
    )
    # Feedback strings observed by each repair call (the tool-role retry feedback):
    # [0]: initial correction (from build_tool_retry_messages, VALIDATION FAILED...)
    # [1]: first retry (CORRECTION STILL INVALID — standard preamble)
    # [2]: second retry (FINAL CORRECTION ATTEMPT — stronger)
    # [3]: third retry (FINAL CORRECTION ATTEMPT — stronger)
    assert len(retry_feedback) == 4
    assert retry_feedback[0].startswith("VALIDATION FAILED")
    assert retry_feedback[1].startswith("CORRECTION STILL INVALID:")
    assert retry_feedback[2].startswith("FINAL CORRECTION ATTEMPT")
    assert retry_feedback[3].startswith("FINAL CORRECTION ATTEMPT")
