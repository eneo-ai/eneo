from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    PROVIDER_TOOL_CALL_ID_MAX_LENGTH,
)
from intric.flows.ai_builder.ai_builder_create_outline import (
    parse_outline_flow_arguments,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    MAX_SELF_CORRECTION_RETRIES,
    ForcedToolAfterTextRequest,
    ForcedToolRetryOutcome,
    ProposalSelfCorrectionRequest,
    _build_retry_feedback,
    build_tool_retry_messages,
    retry_forced_tool_after_text,
    run_forced_tool_retry_after_text,
    run_tool_self_correction,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ProposalCompletionRequest,
    ToolProcessingResult,
    ToolRetryConfig,
    ToolRetryInvocation,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from tests.unittests.flows.ai_builder.ai_builder_outline_diagnostic_payloads import (
    expected_root_assumption_strings,
    expected_step_assumption_strings,
    self_correction_outline_with_step_assumptions_payload,
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
            name=PROPOSE_FLOW_TOOL_NAME,
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
        function=SimpleNamespace(name=PROPOSE_FLOW_TOOL_NAME, arguments="{}"),
    )


def _make_turn() -> SessionSendTurn:
    return SessionSendTurn(
        session_id=uuid4(),
        tenant_id=uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=3,
    )


def _make_self_correction_request(
    *,
    repair_completion: Any,
    process_tool_invocation: Callable[
        [ToolRetryInvocation], Awaitable[ToolProcessingResult]
    ],
    self_correction_temperature: float,
    self_correction_bumped_temperature: float,
    max_self_correction_retries: int,
    forced_proposal_temperature: float,
    target_kind: TargetKind,
    request_id: str = "req-self-correction",
    conversation: list[ConversationMessage] | None = None,
    new_messages_start: int = 0,
    error_message: str = "Invalid propose_flow draft.",
    llm_messages: list[dict[str, Any]] | None = None,
    tool_call: Any | None = None,
    tool_schemas: list[dict[str, Any]] | None = None,
    litellm_model: str = "openai/gpt-5.4",
    litellm_kwargs: dict[str, Any] | None = None,
    available_model_refs: set[str] | None = None,
    available_kb_refs: set[str] | None = None,
    max_output_tokens: int = 1024,
    forced_tool_prompt: str = "Call propose_flow.",
) -> ProposalSelfCorrectionRequest:
    return ProposalSelfCorrectionRequest(
        turn=_make_turn(),
        request_id=request_id,
        conversation=[] if conversation is None else conversation,
        new_messages_start=new_messages_start,
        error_message=error_message,
        llm_messages=(
            [{"role": "user", "content": "go"}]
            if llm_messages is None
            else llm_messages
        ),
        tool_call=_original_tool_call() if tool_call is None else tool_call,
        tool_schemas=(
            [{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}]
            if tool_schemas is None
            else tool_schemas
        ),
        litellm_model=litellm_model,
        litellm_kwargs={} if litellm_kwargs is None else litellm_kwargs,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        max_output_tokens=max_output_tokens,
        self_correction_temperature=self_correction_temperature,
        self_correction_bumped_temperature=self_correction_bumped_temperature,
        max_self_correction_retries=max_self_correction_retries,
        repair_completion=repair_completion,
        retry_config=ToolRetryConfig(
            target_tool_name=PROPOSE_FLOW_TOOL_NAME,
            target_kind=target_kind,
            forced_tool_prompt=forced_tool_prompt,
            process_tool_invocation=process_tool_invocation,
        ),
        forced_proposal_temperature=forced_proposal_temperature,
        flow=None,
    )


def test_build_tool_retry_messages_appends_tool_call_and_feedback() -> None:
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(
            name=PROPOSE_FLOW_TOOL_NAME,
            arguments='{"flow_name":"Draft"}',
        ),
    )

    messages = build_tool_retry_messages(
        llm_messages=[{"role": "system", "content": "Prompt"}],
        tool_call=tool_call,
        tool_feedback="Please fix the draft.",
    )

    assert messages[0] == {"role": "system", "content": "Prompt"}
    assert messages[1]["role"] == "assistant"
    assert messages[1]["tool_calls"][0]["function"]["name"] == PROPOSE_FLOW_TOOL_NAME
    assert messages[2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "Please fix the draft.",
    }


def test_build_tool_retry_messages_normalizes_oversized_tool_call_ids() -> None:
    legacy_id = "server_scoped_model_revision:00000000-0000-0000-0000-000000000000"
    assert len(legacy_id) == PROVIDER_TOOL_CALL_ID_MAX_LENGTH + 1
    tool_call = SimpleNamespace(
        id=legacy_id,
        function=SimpleNamespace(
            name=PROPOSE_FLOW_TOOL_NAME,
            arguments='{"flow_name":"Draft"}',
        ),
    )

    messages = build_tool_retry_messages(
        llm_messages=[{"role": "system", "content": "Prompt"}],
        tool_call=tool_call,
        tool_feedback="Please fix the draft.",
    )

    assistant_id = messages[1]["tool_calls"][0]["id"]
    tool_result_id = messages[2]["tool_call_id"]
    assert assistant_id == tool_result_id
    assert assistant_id != legacy_id
    assert len(assistant_id) <= PROVIDER_TOOL_CALL_ID_MAX_LENGTH


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
        tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        turn=turn,
        conversation=[],
        new_messages_start=0,
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        target_tool_name=PROPOSE_FLOW_TOOL_NAME,
        forced_tool_prompt="Call propose_flow.",
        forced_proposal_temperature=0.1,
        call_proposal_completion=AsyncMock(
            return_value=_tool_response(
                tool_name=PROPOSE_FLOW_TOOL_NAME,
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
        tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        turn=_make_turn(),
        conversation=[],
        new_messages_start=0,
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        target_tool_name=PROPOSE_FLOW_TOOL_NAME,
        forced_tool_prompt="Call propose_flow.",
        forced_proposal_temperature=0.1,
        call_proposal_completion=AsyncMock(
            return_value=_tool_response(
                tool_name=PROPOSE_FLOW_TOOL_NAME,
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
async def test_retry_forced_tool_after_text_accepts_diagnostic_json_text_with_step_assumptions() -> (
    None
):
    observed_assumptions: list[str] = []
    call_proposal_completion = AsyncMock()
    payload = self_correction_outline_with_step_assumptions_payload()
    assistant_text = f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"

    async def process_invocation(
        invocation: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        outline = parse_outline_flow_arguments(invocation.arguments)
        observed_assumptions.extend(outline.assumptions)
        return ToolProcessingResult(event={"event": "plan", "data": "{}"})

    result = await retry_forced_tool_after_text(
        correction_messages=[{"role": "system", "content": "Prompt"}],
        assistant_text=assistant_text,
        tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        turn=_make_turn(),
        conversation=[],
        new_messages_start=0,
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        target_tool_name=PROPOSE_FLOW_TOOL_NAME,
        forced_tool_prompt="Call propose_flow.",
        forced_proposal_temperature=0.1,
        call_proposal_completion=call_proposal_completion,
        process_tool_invocation=process_invocation,
        flow=None,
        resource_catalog=None,
    )

    assert result.events == ({"event": "plan", "data": "{}"},)
    assert result.feedback is None
    assert observed_assumptions == [
        *expected_root_assumption_strings(),
        *expected_step_assumption_strings(),
    ]
    call_proposal_completion.assert_not_awaited()


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
        tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        turn=turn,
        conversation=[],
        new_messages_start=0,
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        target_tool_name=PROPOSE_FLOW_TOOL_NAME,
        forced_tool_prompt="Call propose_flow.",
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
        tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        turn=turn,
        conversation=[],
        new_messages_start=0,
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        target_tool_name=PROPOSE_FLOW_TOOL_NAME,
        forced_tool_prompt="Call propose_flow.",
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
        function=SimpleNamespace(name=PROPOSE_FLOW_TOOL_NAME, arguments="{not json"),
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
        tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        turn=turn,
        conversation=[],
        new_messages_start=0,
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        target_tool_name=PROPOSE_FLOW_TOOL_NAME,
        forced_tool_prompt="Call propose_flow.",
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
        tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        turn=turn,
        conversation=[],
        new_messages_start=0,
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        target_tool_name=PROPOSE_FLOW_TOOL_NAME,
        forced_tool_prompt="Call propose_flow.",
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
        target_tool_name=PROPOSE_FLOW_TOOL_NAME,
        target_kind=TargetKind.CREATE,
        feedback="missing field X",
        retry_count=1,
    )
    assert feedback.startswith("CORRECTION STILL INVALID:")
    assert "FINAL CORRECTION ATTEMPT" not in feedback


def test_build_retry_feedback_escalates_to_stronger_preamble_on_second_retry() -> None:
    feedback = _build_retry_feedback(
        target_tool_name=PROPOSE_FLOW_TOOL_NAME,
        target_kind=TargetKind.CREATE,
        feedback="missing field X",
        retry_count=2,
    )
    assert feedback.startswith("FINAL CORRECTION ATTEMPT")
    assert "missing field X" in feedback


def test_build_retry_feedback_keeps_stronger_preamble_on_third_retry() -> None:
    feedback = _build_retry_feedback(
        target_tool_name=PROPOSE_FLOW_TOOL_NAME,
        target_kind=TargetKind.CREATE,
        feedback="missing field X",
        retry_count=3,
    )
    assert feedback.startswith("FINAL CORRECTION ATTEMPT")


def test_build_retry_feedback_keeps_create_outline_rules_out_of_edit_mode() -> None:
    create_feedback = _build_retry_feedback(
        target_tool_name=PROPOSE_FLOW_TOOL_NAME,
        target_kind=TargetKind.CREATE,
        feedback="duplicate name",
        failure_codes=frozenset({"duplicate_step_name"}),
    )
    edit_feedback = _build_retry_feedback(
        target_tool_name=PROPOSE_FLOW_TOOL_NAME,
        target_kind=TargetKind.EDIT,
        feedback="duplicate name",
        failure_codes=frozenset({"duplicate_step_name"}),
    )

    assert (
        "Every steps[] item must be one complete semantic outline step"
        in create_feedback
    )
    assert "Every steps[] name must be unique case-insensitively" in create_feedback
    assert "semantic outline step" not in edit_feedback
    assert "unique case-insensitively" not in edit_feedback
    assert f"Return one complete {PROPOSE_FLOW_TOOL_NAME} call" in edit_feedback


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
        request: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        observed_temperatures.append(request.temperature)
        for msg in reversed(request.messages):
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
    async for event in run_tool_self_correction(
        _make_self_correction_request(
            error_message="original invalid",
            llm_messages=[{"role": "user", "content": "go"}],
            self_correction_temperature=base_temperature,
            self_correction_bumped_temperature=bumped_temperature,
            max_self_correction_retries=max_retries,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.CREATE,
        )
    ):
        events.append(event)

    return observed_temperatures, observed_retry_feedback, events


@pytest.mark.asyncio
async def test_run_tool_self_correction_uses_base_temperature_on_initial_correction() -> (
    None
):
    temps, _, _ = await _run_repair_capturing(
        max_retries=3, base_temperature=0.35, bumped_temperature=0.6
    )
    assert temps[0] == 0.35


@pytest.mark.asyncio
async def test_run_tool_self_correction_bumps_temperature_from_first_retry_onward() -> (
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
@pytest.mark.parametrize("failure_kind", ["parse", "validation", "quality"])
async def test_run_tool_self_correction_rejects_failure_after_normal_budget(
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
    assert events[-1]["event"] == "error"
    payload = json.loads(events[-1]["data"])
    expected_code = (
        "self_correction_invalid_payload"
        if failure_kind == "parse"
        else "self_correction_quality_failure"
        if failure_kind == "quality"
        else "self_correction_invalid_plan"
    )
    assert payload["code"] == expected_code
    assert "still bad" not in payload["message"]


@pytest.mark.asyncio
async def test_run_tool_self_correction_adds_duplicate_name_outline_guidance() -> None:
    _, retry_feedback, _ = await _run_repair_capturing(
        max_retries=1,
        failure_kind="validation",
        failure_codes=frozenset({"duplicate_step_name"}),
    )

    assert len(retry_feedback) == 2
    assert "Every steps[] name must be unique case-insensitively" in retry_feedback[1]


@pytest.mark.asyncio
async def test_run_tool_self_correction_emits_error_event_when_planner_bails_to_conversational_text() -> (
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

    async def call_proposal_completion(
        _: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        return text_response

    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return ToolProcessingResult(feedback="still bad", failure_kind="validation")

    events: list[dict[str, str]] = []
    async for event in run_tool_self_correction(
        _make_self_correction_request(
            error_message="Structured field nesting depth cannot exceed 3.",
            llm_messages=[{"role": "user", "content": "build flow"}],
            self_correction_temperature=0.35,
            self_correction_bumped_temperature=0.6,
            max_self_correction_retries=3,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.CREATE,
        )
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
async def test_run_tool_self_correction_uses_request_id_on_forced_retry_validation_error() -> (
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
    tool_response = _tool_response(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={
            "flow_name": "Invalid",
            "plan_rationale": "Invalid step reference.",
            "steps": [{"name": "Step", "task": "Do work."}],
        },
    )
    responses = [text_response, tool_response]

    async def call_proposal_completion(
        _: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        return responses.pop(0)

    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return ToolProcessingResult(
            feedback="Validation errors:\n1. Invalid step reference 'step_k'.",
            failure_kind="validation",
        )

    events: list[dict[str, str]] = []
    async for event in run_tool_self_correction(
        _make_self_correction_request(
            request_id="req-repair-feedback",
            error_message="Invalid propose_flow draft.",
            llm_messages=[{"role": "user", "content": "build flow"}],
            self_correction_temperature=0.35,
            self_correction_bumped_temperature=0.6,
            max_self_correction_retries=0,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.CREATE,
        )
    ):
        events.append(event)

    assert events[-1]["event"] == "error"
    payload = json.loads(events[-1]["data"])
    assert payload["request_id"] == "req-repair-feedback"
    assert payload["code"] == "self_correction_invalid_plan"
    assert "Invalid step reference" not in payload["message"]


@pytest.mark.asyncio
async def test_run_tool_self_correction_handles_empty_completion_choices() -> None:
    async def call_proposal_completion(
        _: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        return SimpleNamespace(choices=())

    events: list[dict[str, str]] = []
    async for event in run_tool_self_correction(
        _make_self_correction_request(
            request_id="req-empty-choices",
            error_message="Invalid propose_flow draft.",
            llm_messages=[{"role": "user", "content": "build flow"}],
            self_correction_temperature=0.35,
            self_correction_bumped_temperature=0.6,
            max_self_correction_retries=0,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=AsyncMock(),
            target_kind=TargetKind.CREATE,
        )
    ):
        events.append(event)

    assert events[-1]["event"] == "error"
    payload = json.loads(events[-1]["data"])
    assert payload["request_id"] == "req-empty-choices"
    assert payload["code"] == "planner_invalid_repair_response"


@pytest.mark.asyncio
async def test_run_tool_self_correction_rejects_malformed_correction_tool_arguments() -> (
    None
):
    tool_call = SimpleNamespace(
        id="call_invalid_repair",
        function=SimpleNamespace(name=PROPOSE_FLOW_TOOL_NAME, arguments="{not json"),
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=[tool_call])
            )
        ]
    )
    process_invocation = AsyncMock()

    async def call_proposal_completion(
        _: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        return response

    events: list[dict[str, str]] = []
    async for event in run_tool_self_correction(
        _make_self_correction_request(
            request_id="req-malformed-repair",
            error_message="Invalid propose_flow draft.",
            llm_messages=[{"role": "user", "content": "build flow"}],
            self_correction_temperature=0.35,
            self_correction_bumped_temperature=0.6,
            max_self_correction_retries=0,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.CREATE,
        )
    ):
        events.append(event)

    assert events[-1]["event"] == "error"
    payload = json.loads(events[-1]["data"])
    assert payload["request_id"] == "req-malformed-repair"
    assert payload["code"] == "self_correction_invalid_payload"
    process_invocation.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_tool_self_correction_retries_forced_retry_validation_feedback() -> (
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
    invalid_tool_response = _tool_response(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={
            "flow_name": "Invalid repaired flow",
            "plan_rationale": "Repair duplicate names.",
            "steps": [{"name": "Duplicate", "task": "Do the work."}],
        },
    )
    valid_tool_response = _tool_response(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={
            "flow_name": "Valid repaired flow",
            "plan_rationale": "Repair duplicate names.",
            "steps": [{"name": "Unique", "task": "Do the work."}],
        },
    )
    responses = [text_response, invalid_tool_response, valid_tool_response]
    observed_messages: list[list[dict[str, Any]]] = []
    invocation_count = 0

    async def call_proposal_completion(
        request: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        observed_messages.append(request.messages)
        return responses.pop(0)

    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        nonlocal invocation_count
        invocation_count += 1
        if invocation_count == 1:
            return ToolProcessingResult(
                feedback=(
                    "Compiled edit spec validation failed: Duplicate step name "
                    "'Förbered DOCX-innehåll'."
                ),
                failure_kind="validation",
            )
        return ToolProcessingResult(event={"event": "plan", "data": "{}"})

    events: list[dict[str, str]] = []
    async for event in run_tool_self_correction(
        _make_self_correction_request(
            error_message="Invalid propose_flow draft.",
            llm_messages=[{"role": "user", "content": "edit flow"}],
            self_correction_temperature=0.35,
            self_correction_bumped_temperature=0.6,
            max_self_correction_retries=3,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.EDIT,
        )
    ):
        events.append(event)

    assert events[-1] == {"event": "plan", "data": "{}"}
    assert len(observed_messages) == 3
    retry_feedback = observed_messages[2][-1]
    assert retry_feedback["role"] == "user"
    assert "Duplicate step name" in str(retry_feedback["content"])
    assert invocation_count == 2


@pytest.mark.asyncio
async def test_run_tool_self_correction_limits_text_feedback_retry_budget() -> None:
    text_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="Här är en plan med samma fel.",
                    tool_calls=None,
                )
            )
        ]
    )
    invalid_tool_response = _tool_response(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={
            "flow_name": "Invalid repaired flow",
            "plan_rationale": "Still duplicate.",
            "steps": [{"name": "Duplicate", "task": "Do work."}],
        },
    )
    responses = [
        text_response,
        invalid_tool_response,
        text_response,
        invalid_tool_response,
    ]
    observed_messages: list[list[dict[str, Any]]] = []
    invocation_count = 0

    async def call_proposal_completion(
        request: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        observed_messages.append(request.messages)
        return responses.pop(0)

    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        nonlocal invocation_count
        invocation_count += 1
        return ToolProcessingResult(
            feedback="Compiled edit spec validation failed: duplicate step name.",
            failure_kind="validation",
        )

    events: list[dict[str, str]] = []
    async for event in run_tool_self_correction(
        _make_self_correction_request(
            error_message="Invalid propose_flow draft.",
            llm_messages=[{"role": "user", "content": "edit flow"}],
            self_correction_temperature=0.35,
            self_correction_bumped_temperature=0.6,
            max_self_correction_retries=3,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.EDIT,
        )
    ):
        events.append(event)

    assert events[-1]["event"] == "error"
    payload = json.loads(events[-1]["data"])
    assert payload["code"] == "self_correction_invalid_plan"
    assert "duplicate step name" not in payload["message"].casefold()
    assert len(observed_messages) == 4
    assert invocation_count == 2
    retry_feedback = observed_messages[2][-1]
    assert retry_feedback["role"] == "user"
    assert "duplicate step name" in str(retry_feedback["content"])


@pytest.mark.asyncio
async def test_run_tool_self_correction_still_yields_text_for_legitimate_info_request() -> (
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

    async def call_proposal_completion(
        _: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        return text_response

    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return ToolProcessingResult(feedback="still bad", failure_kind="validation")

    events: list[dict[str, str]] = []
    async for event in run_tool_self_correction(
        _make_self_correction_request(
            error_message="original invalid",
            llm_messages=[{"role": "user", "content": "go"}],
            self_correction_temperature=0.35,
            self_correction_bumped_temperature=0.6,
            max_self_correction_retries=3,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.CREATE,
        )
    ):
        events.append(event)

    text_events = [event for event in events if event.get("event") == "text"]
    assert text_events, (
        "Short, question-mark-bearing planner text without action keywords "
        "is a legitimate clarification request and must still surface to the user; "
        f"got events: {events}"
    )


@pytest.mark.asyncio
async def test_run_tool_self_correction_applies_stronger_prompt_on_second_retry() -> (
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


@pytest.mark.asyncio
async def test_forced_tool_repair_architecture_error_uses_sanitized_event_and_telemetry() -> (
    None
):
    tracker = ProposalTurnTelemetry(
        request_id="req-forced-runtime",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )

    async def process_invocation(_: ToolRetryInvocation) -> ToolProcessingResult:
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            detail="invalid skeleton",
        )

    result = await run_forced_tool_retry_after_text(
        ForcedToolAfterTextRequest(
            correction_messages=[{"role": "user", "content": "Build"}],
            assistant_text="Här är planen.",
            tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            turn=_make_turn(),
            conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
            new_messages_start=1,
            available_model_refs=None,
            available_kb_refs=None,
            max_output_tokens=4096,
            retry_config=ToolRetryConfig(
                target_tool_name=PROPOSE_FLOW_TOOL_NAME,
                target_kind=TargetKind.CREATE,
                forced_tool_prompt="Now call propose_flow.",
                process_tool_invocation=process_invocation,
            ),
            forced_proposal_temperature=0.3,
            repair_completion=AsyncMock(
                return_value=_tool_response(
                    tool_name=PROPOSE_FLOW_TOOL_NAME,
                    arguments={
                        "flow_name": "Broken",
                        "plan_rationale": "R",
                        "steps": [],
                    },
                )
            ),
            request_id="req-forced-runtime",
            usage_tracker=tracker,
        )
    )

    assert result.events is not None
    assert [event["event"] for event in result.events] == ["error"]
    payload = json.loads(result.events[0]["data"])
    assert payload["code"] == "architecture_materialization_failed"
    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_failure_kind"] == "architecture"
    assert telemetry["proposal_repair_invocation_count"] == 0


@pytest.mark.asyncio
async def test_self_correction_repair_architecture_error_uses_sanitized_event_and_telemetry() -> (
    None
):
    tracker = ProposalTurnTelemetry(
        request_id="req-self-correction-runtime",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )

    async def process_invocation(_: ToolRetryInvocation) -> ToolProcessingResult:
        raise AIBuilderArchitectureError(
            public_code="architecture_critic_invariant_failed",
            detail="critic invariant failed",
        )

    request = ProposalSelfCorrectionRequest(
        turn=_make_turn(),
        request_id="req-self-correction-runtime",
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        new_messages_start=1,
        error_message="Invalid flow",
        llm_messages=[{"role": "user", "content": "Build"}],
        tool_call=_original_tool_call(),
        tool_schemas=[{"function": {"name": PROPOSE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=4096,
        self_correction_temperature=0.2,
        self_correction_bumped_temperature=0.5,
        max_self_correction_retries=3,
        repair_completion=AsyncMock(
            return_value=_tool_response(
                tool_name=PROPOSE_FLOW_TOOL_NAME,
                arguments={"flow_name": "Broken", "plan_rationale": "R", "steps": []},
            )
        ),
        retry_config=ToolRetryConfig(
            target_tool_name=PROPOSE_FLOW_TOOL_NAME,
            target_kind=TargetKind.CREATE,
            forced_tool_prompt="Now call propose_flow.",
            process_tool_invocation=process_invocation,
        ),
        forced_proposal_temperature=0.3,
        usage_tracker=tracker,
    )

    events = [event async for event in run_tool_self_correction(request)]

    assert [event["event"] for event in events] == ["status", "error"]
    payload = json.loads(events[1]["data"])
    assert payload["code"] == "architecture_critic_invariant_failed"
    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_failure_kind"] == "architecture"
    assert telemetry["proposal_repair_invocation_count"] == 0
