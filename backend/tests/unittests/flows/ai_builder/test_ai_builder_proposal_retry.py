"""The proposal repair loop: one call budget, closed outcomes, one latest payload."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from litellm.exceptions import RateLimitError

from eneo.flows.ai_builder import (
    ai_builder_proposal_retry as proposal_retry_module,
)
from eneo.flows.ai_builder import (
    ai_builder_proposal_telemetry as proposal_telemetry_module,
)
from eneo.flows.ai_builder.ai_builder_domain_models import TargetKind
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    AIBuilderKnownProviderRejectionException,
    classify_ai_builder_provider_failure,
)
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderStreamEvent
from eneo.flows.ai_builder.ai_builder_events import encode_ai_builder_stream_event
from eneo.flows.ai_builder.ai_builder_proposal_retry import (
    ForcedToolAfterTextRequest,
    ForcedToolRepair,
    ProposalSelfCorrectionRequest,
    missing_tool_call_failure,
    run_forced_tool_retry_after_text,
    run_tool_self_correction,
    terminal_failure_event,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    PROPOSAL_PARSE_JSON_FAILURE_CODE,
    PROPOSAL_TELEMETRY_LOG_KEY,
    ProposalTurnTelemetry,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    MAX_PROPOSAL_PROVIDER_CALLS,
    CorrectableFailure,
    ProposalCallBudget,
    ProposalCallBudgetExhausted,
    ProposalCompleted,
    ProposalCompletionFn,
    ProposalCompletionRequest,
    ProposalMessageGroup,
    SubmissionOutcome,
    TerminalFailure,
    ToolRetryConfig,
    ToolRetryInvocation,
    flatten_proposal_message_groups,
    replace_repair_group,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from tests.unittests.flows.ai_builder.proposal_turn_builders import (
    _make_context,
    _plan_stream_event,
    _proposal_request_budget,
)
from tests.unittests.flows.ai_builder.proposal_turn_test_doubles import _make_usage

ProcessInvocation = Callable[[ToolRetryInvocation], Awaitable[SubmissionOutcome]]


def _wire_events(
    events: list[AIBuilderStreamEvent] | tuple[AIBuilderStreamEvent, ...],
) -> list[dict[str, str]]:
    return [encode_ai_builder_stream_event(event) for event in events]


@contextmanager
def _captured_proposal_telemetry() -> Generator[list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = CaptureHandler()
    old_level = proposal_telemetry_module.logger.level
    proposal_telemetry_module.logger.setLevel(logging.INFO)
    proposal_telemetry_module.logger.addHandler(handler)
    try:
        yield records
    finally:
        proposal_telemetry_module.logger.removeHandler(handler)
        proposal_telemetry_module.logger.setLevel(old_level)


@contextmanager
def _captured_proposal_retry_logs() -> Generator[list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = CaptureHandler()
    old_level = proposal_retry_module.logger.level
    proposal_retry_module.logger.setLevel(logging.WARNING)
    proposal_retry_module.logger.addHandler(handler)
    try:
        yield records
    finally:
        proposal_retry_module.logger.removeHandler(handler)
        proposal_retry_module.logger.setLevel(old_level)


def _failed_turn_payloads(
    records: list[logging.LogRecord],
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for record in records:
        payload = getattr(record, PROPOSAL_TELEMETRY_LOG_KEY, None)
        if not isinstance(payload, dict) or payload.get("operation") != "failed_turn":
            continue
        payloads.append({str(key): value for key, value in payload.items()})
    return payloads


def _tool_response(
    *,
    tool_name: str = PROPOSE_FLOW_TOOL_NAME,
    arguments: dict[str, object] | None = None,
    raw_arguments: str | None = None,
    finish_reason: str = "tool_calls",
    call_id: str = "call_create",
    content: str | None = None,
) -> SimpleNamespace:
    tool_call = SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name=tool_name,
            arguments=(
                raw_arguments
                if raw_arguments is not None
                else json.dumps(arguments or {"flow_name": "T", "steps": []})
            ),
        ),
    )
    message = SimpleNamespace(content=content, tool_calls=[tool_call])
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _text_response(text: str, *, finish_reason: str = "stop") -> SimpleNamespace:
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)]
    )


def _original_tool_call(
    arguments: str = '{"flow_name": "Original"}',
) -> SimpleNamespace:
    return SimpleNamespace(
        id="orig",
        function=SimpleNamespace(name=PROPOSE_FLOW_TOOL_NAME, arguments=arguments),
    )


def _make_turn() -> SessionSendTurn:
    return SessionSendTurn(
        session_id=uuid4(),
        tenant_id=uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=3,
    )


def _completed() -> ProposalCompleted:
    return ProposalCompleted(events=(_plan_stream_event(),))


def _correctable(
    feedback: str = "still bad",
    kind: str = "validation",
    codes: frozenset[str] = frozenset(),
) -> CorrectableFailure:
    return CorrectableFailure(feedback=feedback, kind=kind, codes=codes)  # type: ignore[arg-type]


def _terminal() -> TerminalFailure:
    return TerminalFailure(
        kind="architecture",
        message="The planner could not build a valid flow.",
        code=AIBuilderErrorCode.ARCHITECTURE_MATERIALIZATION_FAILED,
        phase=AIBuilderErrorPhase.PROPOSAL,
        codes=frozenset({"assembly_plan_invariant_failed"}),
    )


def _budgeted(
    repair_completion: ProposalCompletionFn, ctx: Any
) -> ProposalCompletionFn:
    async def boundary_completion(request: ProposalCompletionRequest) -> Any:
        if not request.call_budget.try_start_call():
            raise ProposalCallBudgetExhausted
        if ctx.usage_tracker is not None:
            ctx.usage_tracker.start_attempt(counts_as_repair=request.counts_as_repair)
        return await repair_completion(request)

    return boundary_completion


def _make_self_correction_request(
    *,
    repair_completion: Any,
    process_tool_invocation: ProcessInvocation,
    calls_remaining: int = 3,
    failure: CorrectableFailure | None = None,
    target_kind: TargetKind = TargetKind.CREATE,
    tool_call: Any | None = None,
    usage_tracker: ProposalTurnTelemetry | None = None,
    request_id: str = "req-self-correction",
    llm_messages: list[dict[str, Any]] | None = None,
    forced_tool_prompt: str = "Call propose_flow.",
) -> ProposalSelfCorrectionRequest:
    ctx = _make_context(
        turn=_make_turn(),
        conversation=[],
        llm_messages=(
            [{"role": "user", "content": "go"}]
            if llm_messages is None
            else llm_messages
        ),
        proposal_request_budget=_proposal_request_budget(1024),
        request_id=request_id,
        usage_tracker=usage_tracker,
        # The initial call already spent one; the loop sees only the remainder.
        proposal_call_budget=ProposalCallBudget(
            call_limit=calls_remaining + 1, calls_started=1
        ),
    )
    return ProposalSelfCorrectionRequest(
        ctx=ctx,
        failure=failure or _correctable("original invalid"),
        tool_call=tool_call or _original_tool_call(),
        self_correction_temperature=0.35,
        forced_proposal_temperature=0.1,
        repair_completion=_budgeted(repair_completion, ctx),
        retry_config=ToolRetryConfig(
            forced_tool_prompt=forced_tool_prompt,
            process_tool_invocation=process_tool_invocation,
        ),
    )


def _make_forced_tool_after_text_request(
    *,
    assistant_text: str,
    repair_completion: ProposalCompletionFn,
    process_tool_invocation: ProcessInvocation,
    target_kind: TargetKind = TargetKind.CREATE,
    calls_remaining: int = 2,
    usage_tracker: ProposalTurnTelemetry | None = None,
    forced_tool_prompt: str = "Call propose_flow.",
) -> ForcedToolAfterTextRequest:
    ctx = _make_context(
        turn=_make_turn(),
        conversation=[],
        llm_messages=[{"role": "user", "content": "go"}],
        proposal_request_budget=_proposal_request_budget(1024),
        request_id="req-forced-tool",
        usage_tracker=usage_tracker,
        proposal_call_budget=ProposalCallBudget(
            call_limit=calls_remaining + 1, calls_started=1
        ),
    )
    return ForcedToolAfterTextRequest(
        ctx=ctx,
        correction_message_groups=(
            ProposalMessageGroup(
                messages=({"role": "system", "content": "Prompt"},),
                kind="current_turn",
                protected=True,
            ),
        ),
        assistant_text=assistant_text,
        retry_config=ToolRetryConfig(
            forced_tool_prompt=forced_tool_prompt,
            process_tool_invocation=process_tool_invocation,
        ),
        forced_proposal_temperature=0.1,
        repair_completion=_budgeted(repair_completion, ctx),
    )


async def _collect(request: ProposalSelfCorrectionRequest) -> list[dict[str, str]]:
    return [
        encode_ai_builder_stream_event(event)
        async for event in run_tool_self_correction(request)
    ]


def _process_sequence(
    *outcomes: SubmissionOutcome,
) -> tuple[ProcessInvocation, list[dict[str, Any]]]:
    """Process invocations in order and record the arguments each one saw."""

    seen: list[dict[str, Any]] = []
    queue = list(outcomes)

    async def process(invocation: ToolRetryInvocation) -> SubmissionOutcome:
        seen.append(invocation.arguments)
        return queue.pop(0)

    return process, seen


def test_proposal_call_budget_is_four_calls_per_turn() -> None:
    assert MAX_PROPOSAL_PROVIDER_CALLS == 4


def test_replace_repair_group_keeps_only_the_latest_failed_payload() -> None:
    """The prompt must not grow per attempt: earlier failed payloads never return."""

    base = (
        ProposalMessageGroup(
            messages=({"role": "system", "content": "Prompt"},),
            kind="system",
            protected=True,
        ),
    )
    first = replace_repair_group(base, ({"role": "tool", "content": "first"},))
    second = replace_repair_group(first, ({"role": "tool", "content": "second"},))
    assert [group.kind for group in second] == ["system", "repair"]
    assert second[-1].protected is True
    assert flatten_proposal_message_groups(second)[-1]["content"] == "second"


def test_terminal_failure_event_carries_the_producer_facts() -> None:
    event = terminal_failure_event(_terminal(), request_id="req-1")
    assert event.data.code == AIBuilderErrorCode.ARCHITECTURE_MATERIALIZATION_FAILED
    assert event.data.phase == AIBuilderErrorPhase.PROPOSAL
    assert event.data.request_id == "req-1"


@pytest.mark.asyncio
async def test_one_repair_succeeds_with_exactly_one_more_call() -> None:
    process, seen = _process_sequence(_completed())
    repair = AsyncMock(return_value=_tool_response(arguments={"flow_name": "Fixed"}))

    events = await _collect(
        _make_self_correction_request(
            repair_completion=repair, process_tool_invocation=process
        )
    )

    assert [event["event"] for event in events] == ["status", "plan"]
    assert repair.await_count == 1
    assert seen == [{"flow_name": "Fixed"}]


@pytest.mark.asyncio
async def test_two_repairs_then_success_spends_the_budget_and_no_more() -> None:
    process, seen = _process_sequence(_correctable("still bad"), _completed())
    responses = [
        _tool_response(arguments={"flow_name": "Try 2"}, call_id="r2"),
        _tool_response(arguments={"flow_name": "Try 3"}, call_id="r3"),
    ]
    repair = AsyncMock(side_effect=responses)

    events = await _collect(
        _make_self_correction_request(
            repair_completion=repair, process_tool_invocation=process, calls_remaining=3
        )
    )

    assert [event["event"] for event in events] == ["status", "plan"]
    assert repair.await_count == 2
    assert seen == [{"flow_name": "Try 2"}, {"flow_name": "Try 3"}]


@pytest.mark.asyncio
async def test_each_repair_request_carries_exactly_one_latest_payload() -> None:
    """One assistant/tool pair per request, never the earlier failed payloads."""

    process, _ = _process_sequence(_correctable("bad 2"), _correctable("bad 3"))
    prompts: list[list[dict[str, Any]]] = []

    async def repair(request: ProposalCompletionRequest) -> SimpleNamespace:
        prompts.append(flatten_proposal_message_groups(request.message_groups))
        index = len(prompts)
        return _tool_response(
            arguments={"flow_name": f"Try {index + 1}"}, call_id=f"r{index}"
        )

    await _collect(
        _make_self_correction_request(
            repair_completion=repair, process_tool_invocation=process, calls_remaining=2
        )
    )

    assert len(prompts) == 2
    for prompt in prompts:
        assert [message["role"] for message in prompt] == ["user", "assistant", "tool"]
    assert "Original" in prompts[0][1]["tool_calls"][0]["function"]["arguments"]
    assert "original invalid" in prompts[0][2]["content"]
    assert "Try 2" in prompts[1][1]["tool_calls"][0]["function"]["arguments"]
    assert "bad 2" in prompts[1][2]["content"]
    assert "Original" not in json.dumps(prompts[1])


@pytest.mark.asyncio
async def test_repair_feedback_is_the_producer_text_plus_one_instruction() -> None:
    process, _ = _process_sequence(_completed())
    prompts: list[list[dict[str, Any]]] = []

    async def repair(request: ProposalCompletionRequest) -> SimpleNamespace:
        prompts.append(flatten_proposal_message_groups(request.message_groups))
        return _tool_response()

    await _collect(
        _make_self_correction_request(
            repair_completion=repair,
            process_tool_invocation=process,
            failure=_correctable(
                "steps.1.output_fields: declare `ansvarig` exactly once", "parse"
            ),
        )
    )

    feedback = prompts[0][2]["content"]
    assert feedback.startswith("steps.1.output_fields: declare `ansvarig` exactly once")
    assert f"Return one complete {PROPOSE_FLOW_TOOL_NAME} call." in feedback
    assert "FINAL CORRECTION" not in feedback
    assert "VALIDATION FAILED" not in feedback


@pytest.mark.asyncio
async def test_the_last_correctable_failure_at_the_cap_becomes_a_typed_error() -> None:
    process, _ = _process_sequence(
        _correctable("bad", "quality", frozenset({"empty_steps"}))
    )
    repair = AsyncMock(return_value=_tool_response())
    usage = ProposalTurnTelemetry(
        request_id="req-cap", model="openai/gpt-5.4", target_kind=TargetKind.CREATE
    )

    with _captured_proposal_telemetry() as records:
        events = await _collect(
            _make_self_correction_request(
                repair_completion=repair,
                process_tool_invocation=process,
                calls_remaining=1,
                usage_tracker=usage,
            )
        )

    assert repair.await_count == 1
    assert events[-1]["event"] == "error"
    payload = json.loads(events[-1]["data"])
    assert payload["code"] == "self_correction_quality_failure"
    assert payload["details"]["quality_failure_codes"] == "empty_steps"
    failed = _failed_turn_payloads(records)
    assert [item["final_failure_kind"] for item in failed] == ["repair_quality_failure"]


@pytest.mark.asyncio
async def test_a_terminal_failure_from_a_repair_ends_the_turn_with_zero_extra_calls() -> (
    None
):
    process, _ = _process_sequence(_terminal())
    repair = AsyncMock(return_value=_tool_response())

    events = await _collect(
        _make_self_correction_request(
            repair_completion=repair, process_tool_invocation=process, calls_remaining=3
        )
    )

    assert repair.await_count == 1
    assert events[-1]["event"] == "error"
    assert json.loads(events[-1]["data"])["code"] == (
        "architecture_materialization_failed"
    )


@pytest.mark.asyncio
async def test_an_exhausted_budget_before_the_repair_call_reports_the_last_failure() -> (
    None
):
    process, _ = _process_sequence()
    repair = AsyncMock(return_value=_tool_response())

    events = await _collect(
        _make_self_correction_request(
            repair_completion=repair,
            process_tool_invocation=process,
            calls_remaining=0,
            failure=_correctable("no budget", "parse"),
        )
    )

    repair.assert_not_awaited()
    assert json.loads(events[-1]["data"])["code"] == "self_correction_invalid_payload"


@pytest.mark.asyncio
async def test_malformed_json_from_a_repair_is_correctable_once_more() -> None:
    process, seen = _process_sequence(_completed())
    repair = AsyncMock(
        side_effect=[
            _tool_response(raw_arguments="{not json", call_id="r1"),
            _tool_response(arguments={"flow_name": "Valid"}, call_id="r2"),
        ]
    )
    usage = ProposalTurnTelemetry(
        request_id="req-json", model="openai/gpt-5.4", target_kind=TargetKind.CREATE
    )

    events = await _collect(
        _make_self_correction_request(
            repair_completion=repair,
            process_tool_invocation=process,
            calls_remaining=2,
            usage_tracker=usage,
        )
    )

    assert [event["event"] for event in events] == ["status", "plan"]
    assert seen == [{"flow_name": "Valid"}]
    telemetry = usage.build_planner_telemetry()
    assert PROPOSAL_PARSE_JSON_FAILURE_CODE in json.dumps(telemetry)


@pytest.mark.asyncio
async def test_text_only_repair_gets_one_forced_tool_continuation_then_succeeds() -> (
    None
):
    process, seen = _process_sequence(_completed())
    repair = AsyncMock(
        side_effect=[
            _text_response("Här är planen i ord."),
            _tool_response(arguments={"flow_name": "Forced"}, call_id="forced"),
        ]
    )
    prompts: list[list[dict[str, Any]]] = []
    original_side_effect = repair.side_effect

    async def recording(request: ProposalCompletionRequest) -> SimpleNamespace:
        prompts.append(flatten_proposal_message_groups(request.message_groups))
        return next(original_side_effect)  # type: ignore[arg-type]

    events = await _collect(
        _make_self_correction_request(
            repair_completion=recording,
            process_tool_invocation=process,
            calls_remaining=2,
            forced_tool_prompt="Now call propose_flow.",
        )
    )

    assert [event["event"] for event in events] == ["status", "plan"]
    assert seen == [{"flow_name": "Forced"}]
    assert prompts[1][-1] == {"role": "user", "content": "Now call propose_flow."}
    assert prompts[1][-2] == {"role": "assistant", "content": "Här är planen i ord."}


@pytest.mark.asyncio
async def test_text_only_twice_is_a_terminal_missing_tool_failure() -> None:
    """Prose never becomes an answer: the second miss ends the turn typed."""

    process, seen = _process_sequence()
    repair = AsyncMock(
        side_effect=[
            _text_response("Vilken modell ska jag använda?"),
            _text_response("Jag behöver mer information."),
        ]
    )
    usage = ProposalTurnTelemetry(
        request_id="req-prose", model="openai/gpt-5.4", target_kind=TargetKind.CREATE
    )

    with _captured_proposal_telemetry() as records:
        events = await _collect(
            _make_self_correction_request(
                repair_completion=repair,
                process_tool_invocation=process,
                calls_remaining=3,
                usage_tracker=usage,
            )
        )

    assert repair.await_count == 2
    assert seen == []
    assert [event["event"] for event in events] == ["status", "error"]
    assert json.loads(events[-1]["data"])["code"] == "proposal_tool_missing"
    assert "text" not in [event["event"] for event in events]
    failed = _failed_turn_payloads(records)
    assert [record["final_failure_kind"] for record in failed] == [
        "missing_submission_tool"
    ]
    assert failed[0]["branch"] == "forced_tool_retry_missing_submission"


@pytest.mark.asyncio
async def test_forced_continuation_with_an_invalid_payload_continues_repairing() -> (
    None
):
    process, seen = _process_sequence(_correctable("forced bad"), _completed())
    repair = AsyncMock(
        side_effect=[
            _text_response("Plan i ord."),
            _tool_response(arguments={"flow_name": "Forced"}, call_id="forced"),
            _tool_response(arguments={"flow_name": "Repaired"}, call_id="r3"),
        ]
    )

    events = await _collect(
        _make_self_correction_request(
            repair_completion=repair, process_tool_invocation=process, calls_remaining=3
        )
    )

    assert [event["event"] for event in events] == ["status", "plan"]
    assert seen == [{"flow_name": "Forced"}, {"flow_name": "Repaired"}]
    assert repair.await_count == 3


@pytest.mark.asyncio
async def test_provider_truncation_during_repair_is_terminal() -> None:
    process, _ = _process_sequence()
    repair = AsyncMock(return_value=_text_response("", finish_reason="length"))
    usage = ProposalTurnTelemetry(
        request_id="req-trunc", model="openai/gpt-5.4", target_kind=TargetKind.CREATE
    )

    with _captured_proposal_telemetry() as records:
        events = await _collect(
            _make_self_correction_request(
                repair_completion=repair,
                process_tool_invocation=process,
                calls_remaining=3,
                usage_tracker=usage,
            )
        )

    assert repair.await_count == 1
    assert json.loads(events[-1]["data"])["code"] == "planner_output_too_long"
    failed = _failed_turn_payloads(records)
    assert failed and failed[-1]["final_failure_kind"] == "provider_truncation"


@pytest.mark.asyncio
async def test_a_known_provider_rejection_propagates_without_another_call() -> None:
    process, _ = _process_sequence()
    failure = classify_ai_builder_provider_failure(
        RateLimitError(message="slow down", llm_provider="openai", model="gpt"),
        stage="proposal_completion",
        request_id="req-rate",
    )
    repair = AsyncMock(side_effect=failure.as_exception())

    with pytest.raises(AIBuilderKnownProviderRejectionException):
        await _collect(
            _make_self_correction_request(
                repair_completion=repair, process_tool_invocation=process
            )
        )
    assert repair.await_count == 1


@pytest.mark.asyncio
async def test_an_internal_completion_error_ends_the_turn_and_logs_it() -> None:
    process, _ = _process_sequence()
    repair = AsyncMock(side_effect=RuntimeError("boom"))
    usage = ProposalTurnTelemetry(
        request_id="req-internal", model="openai/gpt-5.4", target_kind=TargetKind.CREATE
    )

    with _captured_proposal_telemetry() as records:
        events = await _collect(
            _make_self_correction_request(
                repair_completion=repair,
                process_tool_invocation=process,
                usage_tracker=usage,
            )
        )

    assert json.loads(events[-1]["data"])["code"] == "planner_upstream_error"
    failed = _failed_turn_payloads(records)
    assert failed and failed[-1]["final_failure_kind"] == "internal_error"


@pytest.mark.asyncio
async def test_repair_logs_carry_only_bounded_classification_never_content() -> None:
    assistant_secret = "MODEL_ASSISTANT_SECRET_bm42"
    feedback_secret = "USER_DERIVED_FEEDBACK_SECRET_bm42"
    process, _ = _process_sequence(
        _correctable(feedback_secret, "quality", frozenset({"empty_steps"}))
    )
    repair = AsyncMock(
        side_effect=[
            _text_response(assistant_secret),
            _tool_response(arguments={"flow_name": "Forced"}, call_id="forced"),
        ]
    )

    with _captured_proposal_retry_logs() as records:
        events = await _collect(
            _make_self_correction_request(
                repair_completion=repair,
                process_tool_invocation=process,
                calls_remaining=2,
            )
        )

    assert events[-1]["event"] == "error"
    logged = "\n".join(
        f"{record.getMessage()} {getattr(record, 'failure_kind', '')}"
        for record in records
    )
    assert assistant_secret not in logged
    assert feedback_secret not in logged
    assert "quality" in logged


@pytest.mark.asyncio
async def test_forced_tool_retry_after_text_returns_the_call_it_came_from() -> None:
    process, seen = _process_sequence(_correctable("forced bad"))
    repair = AsyncMock(
        return_value=_tool_response(arguments={"flow_name": "Forced"}, call_id="forced")
    )

    continuation = await run_forced_tool_retry_after_text(
        _make_forced_tool_after_text_request(
            assistant_text="Här är planen.",
            repair_completion=repair,
            process_tool_invocation=process,
        )
    )

    assert isinstance(continuation, ForcedToolRepair)
    assert continuation.failure.feedback == "forced bad"
    assert continuation.tool_call.id == "forced"
    assert seen == [{"flow_name": "Forced"}]


@pytest.mark.asyncio
async def test_forced_tool_retry_without_budget_or_tool_is_terminal() -> None:
    process, seen = _process_sequence()
    repair = AsyncMock(return_value=_text_response("still prose"))

    no_tool = await run_forced_tool_retry_after_text(
        _make_forced_tool_after_text_request(
            assistant_text="Prose.",
            repair_completion=repair,
            process_tool_invocation=process,
        )
    )
    exhausted = await run_forced_tool_retry_after_text(
        _make_forced_tool_after_text_request(
            assistant_text="Prose.",
            repair_completion=repair,
            process_tool_invocation=process,
            calls_remaining=0,
        )
    )

    assert no_tool == missing_tool_call_failure()
    assert exhausted == missing_tool_call_failure()
    assert repair.await_count == 1
    assert seen == []


@pytest.mark.asyncio
async def test_forced_tool_retry_terminalizes_provider_truncation_in_its_phase() -> (
    None
):
    process, _ = _process_sequence()
    repair = AsyncMock(return_value=_text_response("", finish_reason="length"))

    continuation = await run_forced_tool_retry_after_text(
        _make_forced_tool_after_text_request(
            assistant_text="Prose.",
            repair_completion=repair,
            process_tool_invocation=process,
        )
    )

    assert isinstance(continuation, TerminalFailure)
    assert continuation.code == AIBuilderErrorCode.PLANNER_OUTPUT_TOO_LONG
    assert continuation.phase == AIBuilderErrorPhase.SELF_CORRECTION


@pytest.mark.asyncio
async def test_forced_continuation_local_failure_is_internal_not_missing_tool() -> None:
    """Provider rejections raise typed; anything else here is a local failure."""

    process, seen = _process_sequence()
    repair = AsyncMock(
        side_effect=[_text_response("Först lite text."), RuntimeError("socket reset")]
    )
    usage = ProposalTurnTelemetry(
        request_id="req-upstream", model="openai/gpt-5.4", target_kind=TargetKind.CREATE
    )

    with _captured_proposal_telemetry() as records:
        events = await _collect(
            _make_self_correction_request(
                repair_completion=repair,
                process_tool_invocation=process,
                calls_remaining=3,
                usage_tracker=usage,
            )
        )

    assert repair.await_count == 2
    assert seen == []
    assert [event["event"] for event in events] == ["status", "error"]
    assert json.loads(events[-1]["data"])["code"] == "planner_upstream_error"
    failed = _failed_turn_payloads(records)
    assert [record["final_failure_kind"] for record in failed] == ["internal_error"]
    assert failed[0]["branch"] == "forced_tool_retry_completion_error"


@pytest.mark.asyncio
async def test_forced_continuation_terminal_keeps_its_kind_and_logs_once() -> None:
    """An architecture terminal from the forced call is reported as that, once."""

    architecture = TerminalFailure(
        kind="architecture",
        message="The confirmed requirements cannot be built.",
        code=AIBuilderErrorCode.ARCHITECTURE_MATERIALIZATION_FAILED,
        phase=AIBuilderErrorPhase.PROPOSAL,
        codes=frozenset({"confirmed_form_field_incompatible"}),
    )
    process, seen = _process_sequence(architecture)
    repair = AsyncMock(
        side_effect=[
            _text_response("Först lite text."),
            _tool_response(arguments={"flow_name": "Forced"}, call_id="forced"),
        ]
    )
    usage = ProposalTurnTelemetry(
        request_id="req-forced-terminal",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )

    with _captured_proposal_telemetry() as records:
        events = await _collect(
            _make_self_correction_request(
                repair_completion=repair,
                process_tool_invocation=process,
                calls_remaining=3,
                usage_tracker=usage,
            )
        )

    assert repair.await_count == 2
    assert seen == [{"flow_name": "Forced"}]
    assert [event["event"] for event in events] == ["status", "error"]
    payload = json.loads(events[-1]["data"])
    assert payload["code"] == "architecture_materialization_failed"
    failed = _failed_turn_payloads(records)
    assert [record["final_failure_kind"] for record in failed] == ["architecture"]
    assert failed[0]["branch"] == "forced_tool_retry_invalid_tool_result"


def test_usage_double_records_the_shapes_the_loop_reports() -> None:
    usage = _make_usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    assert usage.total_tokens == 15
