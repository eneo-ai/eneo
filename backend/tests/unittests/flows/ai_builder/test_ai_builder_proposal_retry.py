from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Generator, Iterator
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
from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    PROVIDER_TOOL_CALL_ID_MAX_LENGTH,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderKnownProviderRejectionException,
    classify_ai_builder_provider_failure,
)
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderStreamEvent
from eneo.flows.ai_builder.ai_builder_events import encode_ai_builder_stream_event
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ProposalIntentArgumentError,
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_proposal_retry import (
    ForcedToolAfterTextRequest,
    ForcedToolRetryOutcome,
    ProposalSelfCorrectionRequest,
    build_tool_retry_messages,
    run_forced_tool_retry_after_text,
    run_tool_self_correction,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    PROPOSAL_TELEMETRY_LOG_KEY,
    ProposalTurnTelemetry,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    MAX_PROPOSAL_PROVIDER_CALLS,
    ProposalCallBudget,
    ProposalCompletionFn,
    ProposalCompletionRequest,
    ToolProcessingResult,
    ToolRetryConfig,
    ToolRetryInvocation,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from eneo.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from tests.unittests.flows.ai_builder.ai_builder_intent_diagnostic_payloads import (
    self_correction_intent_with_step_assumptions_payload,
)
from tests.unittests.flows.ai_builder.proposal_turn_builders import (
    _make_context,
    _plan_stream_event,
)
from tests.unittests.flows.ai_builder.proposal_turn_test_doubles import _make_usage


def _wire_events(
    events: list[AIBuilderStreamEvent] | tuple[AIBuilderStreamEvent, ...],
) -> list[dict[str, str]]:
    return [encode_ai_builder_stream_event(event) for event in events]


@contextmanager
def _captured_proposal_telemetry() -> Iterator[list[logging.LogRecord]]:
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


def _single_failed_turn_payload(
    records: list[logging.LogRecord],
) -> dict[str, object]:
    payloads = _failed_turn_payloads(records)
    assert len(payloads) == 1
    return payloads[0]


def _tool_response(
    *,
    tool_name: str,
    arguments: dict[str, object],
    finish_reason: str = "tool_calls",
) -> SimpleNamespace:
    tool_call = SimpleNamespace(
        id="call_create",
        function=SimpleNamespace(
            name=tool_name,
            arguments=json.dumps(arguments),
        ),
    )
    message = SimpleNamespace(content=None, tool_calls=[tool_call])
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _bad_tool_response(call_index: int) -> SimpleNamespace:
    tool_call = SimpleNamespace(
        id=f"retry_{call_index}",
        function=SimpleNamespace(
            name=PROPOSE_FLOW_TOOL_NAME,
            arguments=json.dumps(
                {
                    "flow_name": f"T {call_index}",
                    "plan_rationale": "R",
                    "steps": [],
                }
            ),
        ),
    )
    message = SimpleNamespace(content="", tool_calls=[tool_call])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")]
    )


def _truncated_response(*, message: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="length")]
    )


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
    failure_codes: frozenset[str] = frozenset(),
    llm_messages: list[dict[str, Any]] | None = None,
    tool_call: Any | None = None,
    tool_schemas: list[dict[str, Any]] | None = None,
    litellm_model: str = "openai/gpt-5.4",
    litellm_kwargs: dict[str, Any] | None = None,
    available_model_refs: set[str] | None = None,
    available_kb_refs: set[str] | None = None,
    max_output_tokens: int = 1024,
    forced_tool_prompt: str = "Call propose_flow.",
    usage_tracker: ProposalTurnTelemetry | None = None,
    assistant_metadata: dict[str, Any] | None = None,
) -> ProposalSelfCorrectionRequest:
    return ProposalSelfCorrectionRequest(
        ctx=_make_context(
            turn=_make_turn(),
            conversation=[] if conversation is None else conversation,
            new_messages_start=new_messages_start,
            llm_messages=(
                [{"role": "user", "content": "go"}]
                if llm_messages is None
                else llm_messages
            ),
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
            request_id=request_id,
            usage_tracker=usage_tracker,
            assistant_metadata=assistant_metadata,
            proposal_call_budget=ProposalCallBudget(
                call_limit=max_self_correction_retries + 1
            ),
        ),
        error_message=error_message,
        failure_codes=failure_codes,
        tool_call=_original_tool_call() if tool_call is None else tool_call,
        self_correction_temperature=self_correction_temperature,
        self_correction_bumped_temperature=self_correction_bumped_temperature,
        repair_completion=repair_completion,
        retry_config=ToolRetryConfig(
            target_kind=target_kind,
            forced_tool_prompt=forced_tool_prompt,
            process_tool_invocation=process_tool_invocation,
        ),
        forced_proposal_temperature=forced_proposal_temperature,
        initial_failure_kind="validation",
    )


def _make_forced_tool_after_text_request(
    *,
    assistant_text: str,
    repair_completion: ProposalCompletionFn,
    process_tool_invocation: Callable[
        [ToolRetryInvocation], Awaitable[ToolProcessingResult]
    ],
    forced_proposal_temperature: float,
    target_kind: TargetKind,
    correction_messages: list[dict[str, Any]] | None = None,
    tool_schemas: list[dict[str, Any]] | None = None,
    litellm_model: str = "openai/gpt-5.4",
    litellm_kwargs: dict[str, Any] | None = None,
    turn: SessionSendTurn | None = None,
    conversation: list[ConversationMessage] | None = None,
    new_messages_start: int = 0,
    available_model_refs: set[str] | None = None,
    available_kb_refs: set[str] | None = None,
    max_output_tokens: int = 1024,
    forced_tool_prompt: str = "Call propose_flow.",
    assistant_metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
    usage_tracker: ProposalTurnTelemetry | None = None,
) -> ForcedToolAfterTextRequest:
    resolved_request_id = request_id or (
        usage_tracker.request_id if usage_tracker is not None else "req-forced-tool"
    )
    return ForcedToolAfterTextRequest(
        ctx=_make_context(
            turn=_make_turn() if turn is None else turn,
            conversation=[] if conversation is None else conversation,
            new_messages_start=new_messages_start,
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
            request_id=resolved_request_id,
            usage_tracker=usage_tracker,
            assistant_metadata=assistant_metadata,
        ),
        correction_messages=(
            [{"role": "system", "content": "Prompt"}]
            if correction_messages is None
            else correction_messages
        ),
        assistant_text=assistant_text,
        retry_config=ToolRetryConfig(
            target_kind=target_kind,
            forced_tool_prompt=forced_tool_prompt,
            process_tool_invocation=process_tool_invocation,
        ),
        forced_proposal_temperature=forced_proposal_temperature,
        repair_completion=repair_completion,
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
async def test_run_forced_tool_retry_after_text_builds_typed_invocation() -> None:
    turn = _make_turn()
    captured_invocation: ToolRetryInvocation | None = None

    async def process_invocation(
        invocation: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        nonlocal captured_invocation
        captured_invocation = invocation
        return ToolProcessingResult(
            events=(_plan_stream_event(),),
        )

    result = await run_forced_tool_retry_after_text(
        _make_forced_tool_after_text_request(
            assistant_text="Här är mitt förslag.",
            turn=turn,
            forced_proposal_temperature=0.1,
            repair_completion=AsyncMock(
                return_value=_tool_response(
                    tool_name=PROPOSE_FLOW_TOOL_NAME,
                    arguments={
                        "flow_name": "Test",
                        "plan_rationale": "R",
                        "steps": [],
                    },
                )
            ),
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.CREATE,
            assistant_metadata={"planner_telemetry": {"request_id": "req"}},
        )
    )

    assert result.events is not None
    assert [event.event for event in result.events] == ["plan"]
    assert captured_invocation is not None
    assert captured_invocation.turn is turn
    assert captured_invocation.arguments["flow_name"] == "Test"
    assert captured_invocation.flow is None
    assert captured_invocation.resource_catalog is None
    assert captured_invocation.assistant_metadata == {
        "planner_telemetry": {"request_id": "req"}
    }


@pytest.mark.asyncio
async def test_run_forced_tool_retry_after_text_surfaces_tool_user_message() -> None:
    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return ToolProcessingResult(
            user_message="Det markerade steget använder ingen chattmodell."
        )

    result = await run_forced_tool_retry_after_text(
        _make_forced_tool_after_text_request(
            assistant_text="Här är mitt förslag.",
            forced_proposal_temperature=0.1,
            repair_completion=AsyncMock(
                return_value=_tool_response(
                    tool_name=PROPOSE_FLOW_TOOL_NAME,
                    arguments={
                        "flow_name": "Test",
                        "plan_rationale": "R",
                        "steps": [],
                    },
                )
            ),
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.CREATE,
        )
    )

    assert result.events is not None
    assert _wire_events(result.events) == [
        {
            "event": "text",
            "data": '{"text":"Det markerade steget använder ingen chattmodell."}',
        },
    ]


@pytest.mark.asyncio
async def test_run_forced_tool_retry_after_text_returns_feedback_for_malformed_json_text() -> (
    None
):
    call_proposal_completion = AsyncMock()
    payload = self_correction_intent_with_step_assumptions_payload()
    assistant_text = f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"

    async def process_invocation(
        invocation: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        try:
            parse_create_flow_intent_arguments(invocation.arguments)
        except ProposalIntentArgumentError as error:
            return ToolProcessingResult(
                feedback=f"Invalid propose_flow arguments: {error}",
                failure_kind="parse",
            )
        return ToolProcessingResult(events=(_plan_stream_event(),))

    result = await run_forced_tool_retry_after_text(
        _make_forced_tool_after_text_request(
            assistant_text=assistant_text,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.CREATE,
        )
    )

    assert result.events is None
    assert result.feedback is not None
    assert "steps.1.assumptions" in result.feedback
    assert "extra_forbidden" in result.feedback
    assert result.failure_kind == "parse"
    call_proposal_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_forced_tool_retry_after_text_accepts_json_arguments_returned_as_text() -> (
    None
):
    processed_arguments: dict[str, object] = {}
    call_proposal_completion = AsyncMock()
    turn = _make_turn()

    async def process_invocation(
        invocation: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        processed_arguments.update(invocation.arguments)
        return ToolProcessingResult(events=(_plan_stream_event(),))

    result = await run_forced_tool_retry_after_text(
        _make_forced_tool_after_text_request(
            assistant_text=json.dumps(
                {
                    "flow_name": "Text JSON outline",
                    "plan_rationale": "The model returned JSON as prose.",
                    "steps": [
                        {"name": "Analyze", "instructions": "Analyze the input."}
                    ],
                }
            ),
            turn=turn,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.CREATE,
        )
    )

    assert result.events is not None
    assert [event.event for event in result.events] == ["plan"]
    assert processed_arguments["flow_name"] == "Text JSON outline"
    call_proposal_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_forced_tool_retry_after_text_preserves_json_text_validation_feedback() -> (
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

    result = await run_forced_tool_retry_after_text(
        _make_forced_tool_after_text_request(
            assistant_text=json.dumps(
                {
                    "flow_name": "Invalid text JSON outline",
                    "plan_rationale": "The model returned invalid JSON as prose.",
                    "steps": [],
                }
            ),
            turn=turn,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.CREATE,
        )
    )

    assert result.events is None
    assert result.feedback == (
        "Validation errors:\n1. Missing required field report_period."
    )
    assert result.failure_kind == "validation"
    call_proposal_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_forced_tool_retry_after_text_preserves_forced_payload_parse_feedback() -> (
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
                message=SimpleNamespace(content=None, tool_calls=[tool_call]),
                finish_reason="tool_calls",
            )
        ]
    )

    result = await run_forced_tool_retry_after_text(
        _make_forced_tool_after_text_request(
            assistant_text="Här är mitt förslag.",
            turn=turn,
            forced_proposal_temperature=0.1,
            repair_completion=AsyncMock(return_value=response),
            process_tool_invocation=AsyncMock(),
            target_kind=TargetKind.CREATE,
        )
    )

    assert result.events is None
    assert result.feedback is not None
    assert "Invalid tool call arguments:" in result.feedback
    assert "Expecting property name enclosed" in result.feedback
    assert result.failure_kind == "parse"


@pytest.mark.asyncio
async def test_run_forced_tool_retry_after_text_terminalizes_provider_truncation() -> (
    None
):
    tracker = ProposalTurnTelemetry(
        request_id="req-forced-truncated",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    tool_call = SimpleNamespace(
        id="call_truncated",
        function=SimpleNamespace(
            name=PROPOSE_FLOW_TOOL_NAME,
            arguments="{not json MODEL OUTPUT SECRET",
        ),
    )
    response = _truncated_response(
        message=SimpleNamespace(
            content="MODEL OUTPUT SECRET",
            tool_calls=[tool_call],
        )
    )

    async def call_proposal_completion(
        request: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        tracker.record_response(
            finish_reason="length",
            usage=_make_usage(prompt_tokens=5, completion_tokens=7, total_tokens=12),
            counts_as_repair=request.counts_as_repair,
        )
        return response

    process_invocation = AsyncMock()
    request = _make_forced_tool_after_text_request(
        assistant_text="Här är mitt förslag.",
        forced_proposal_temperature=0.1,
        repair_completion=call_proposal_completion,
        process_tool_invocation=process_invocation,
        target_kind=TargetKind.CREATE,
        usage_tracker=tracker,
        request_id="req-forced-truncated",
        correction_messages=[{"role": "user", "content": "Build flow USER SECRET"}],
    )
    session_id = request.ctx.session_id

    with _captured_proposal_telemetry() as telemetry_records:
        result = await run_forced_tool_retry_after_text(request)

    process_invocation.assert_not_awaited()
    assert result.feedback is None
    assert result.failure_kind is None
    assert result.events is not None
    wire_events = _wire_events(result.events)
    assert [event["event"] for event in wire_events] == ["error"]
    payload = json.loads(wire_events[0]["data"])
    assert payload["code"] == "planner_output_too_long"
    assert payload["phase"] == "self_correction"
    assert payload["request_id"] == "req-forced-truncated"
    failed_payload = _single_failed_turn_payload(telemetry_records)
    assert failed_payload["request_id"] == "req-forced-truncated"
    assert failed_payload["session_id"] == str(session_id)
    assert failed_payload["target_kind"] == "create"
    assert failed_payload["branch"] == "provider_truncation"
    assert failed_payload["repair_attempts"] == 1
    assert failed_payload["llm_calls"] == 1
    assert failed_payload["prompt_tokens"] == 5
    assert failed_payload["completion_tokens"] == 7
    assert failed_payload["total_tokens"] == 12
    assert failed_payload["final_failure_kind"] == "provider_truncation"
    assert failed_payload["final_error_code"] == "planner_output_too_long"
    assert failed_payload["provider_finish_reason"] == "length"
    encoded_payload = json.dumps(failed_payload, default=str)
    assert "USER SECRET" not in encoded_payload
    assert "MODEL OUTPUT SECRET" not in encoded_payload


@pytest.mark.asyncio
async def test_run_forced_tool_retry_after_text_preserves_information_request_empty_outcome() -> (
    None
):
    call_proposal_completion = AsyncMock()
    turn = _make_turn()

    result = await run_forced_tool_retry_after_text(
        _make_forced_tool_after_text_request(
            assistant_text="Vilken modell ska jag använda?",
            turn=turn,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=AsyncMock(),
            target_kind=TargetKind.CREATE,
        )
    )

    assert result == ForcedToolRetryOutcome()
    call_proposal_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_repair_loop_logs_only_bounded_failure_classification() -> None:
    assistant_secret = "MODEL_ASSISTANT_SECRET_bm42"
    json_text_secret = "MODEL_JSON_TEXT_SECRET_bm42"
    feedback_secret = "USER_DERIVED_FEEDBACK_SECRET_bm42"
    failure_codes = frozenset({"empty_steps"})

    text_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=assistant_secret, tool_calls=None),
                finish_reason="stop",
            )
        ]
    )
    forced_tool_response = _tool_response(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={"flow_name": "Invalid", "steps": []},
    )
    failed_repair = ToolProcessingResult(
        feedback=feedback_secret,
        failure_kind="quality",
        failure_codes=failure_codes,
    )

    with _captured_proposal_retry_logs() as records:
        events = [
            event
            async for event in run_tool_self_correction(
                _make_self_correction_request(
                    repair_completion=AsyncMock(
                        side_effect=[text_response, forced_tool_response]
                    ),
                    process_tool_invocation=AsyncMock(return_value=failed_repair),
                    self_correction_temperature=0.35,
                    self_correction_bumped_temperature=0.6,
                    max_self_correction_retries=1,
                    forced_proposal_temperature=0.1,
                    target_kind=TargetKind.CREATE,
                )
            )
        ]
        json_text_outcome = await run_forced_tool_retry_after_text(
            _make_forced_tool_after_text_request(
                assistant_text=json.dumps({"flow_name": json_text_secret, "steps": []}),
                repair_completion=AsyncMock(),
                process_tool_invocation=AsyncMock(return_value=failed_repair),
                forced_proposal_temperature=0.1,
                target_kind=TargetKind.CREATE,
            )
        )

    assert events[-1].event == "error"
    assert json_text_outcome.failure_kind == "quality"
    assert len(records) == 3
    for record in records:
        rendered_message = record.getMessage()
        serialized_args = repr(record.args)
        structured_fields = {
            key: value
            for key, value in record.__dict__.items()
            if key not in {"args", "msg"}
        }
        serialized_structured_fields = json.dumps(structured_fields, default=str)
        for secret in (assistant_secret, json_text_secret, feedback_secret):
            assert secret not in rendered_message
            assert secret not in serialized_args
            assert secret not in serialized_structured_fields

        assert structured_fields["failure_kind"] == "quality"
        assert structured_fields["failure_codes_count"] == 1

    assistant_bail_record = next(
        record
        for record in records
        if record.getMessage().startswith("Self-correction bailed")
    )
    assert assistant_bail_record.__dict__["assistant_text_present"] is True
    assert assistant_bail_record.__dict__["assistant_text_length"] == len(
        assistant_secret
    )

    feedback_records = [
        record for record in records if record is not assistant_bail_record
    ]
    assert all(
        record.__dict__["feedback_present"] is True for record in feedback_records
    )
    assert all(
        record.__dict__["feedback_length"] == len(feedback_secret)
        for record in feedback_records
    )


def test_proposal_provider_call_budget_includes_initial_and_repairs() -> None:
    assert MAX_PROPOSAL_PROVIDER_CALLS == 4


@pytest.mark.asyncio
async def test_forced_fallback_shares_the_self_correction_call_budget() -> None:
    text_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="Här är en korrigerad plan.",
                    tool_calls=None,
                ),
                finish_reason="stop",
            )
        ]
    )
    forced_response = _tool_response(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={"flow_name": "Still invalid", "steps": []},
    )
    repair_completion = AsyncMock(side_effect=[text_response, forced_response])

    events = _wire_events(
        [
            event
            async for event in run_tool_self_correction(
                _make_self_correction_request(
                    repair_completion=repair_completion,
                    process_tool_invocation=AsyncMock(
                        return_value=ToolProcessingResult(
                            feedback="still bad",
                            failure_kind="validation",
                        )
                    ),
                    self_correction_temperature=0.35,
                    self_correction_bumped_temperature=0.6,
                    max_self_correction_retries=0,
                    forced_proposal_temperature=0.1,
                    target_kind=TargetKind.CREATE,
                )
            )
        ]
    )

    assert repair_completion.await_count == 1
    assert events[-1]["event"] == "error"


@pytest.mark.asyncio
async def test_unchanged_candidate_and_failure_stop_before_another_provider_call() -> (
    None
):
    unchanged_response = _tool_response(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={},
    )
    repair_completion = AsyncMock(return_value=unchanged_response)

    events = _wire_events(
        [
            event
            async for event in run_tool_self_correction(
                _make_self_correction_request(
                    repair_completion=repair_completion,
                    process_tool_invocation=AsyncMock(
                        return_value=ToolProcessingResult(
                            feedback="still bad",
                            failure_kind="validation",
                        )
                    ),
                    self_correction_temperature=0.35,
                    self_correction_bumped_temperature=0.6,
                    max_self_correction_retries=3,
                    forced_proposal_temperature=0.1,
                    target_kind=TargetKind.CREATE,
                )
            )
        ]
    )

    assert repair_completion.await_count == 1
    assert events[-1]["event"] == "error"


@pytest.mark.asyncio
async def test_progressing_edit_repair_can_reach_a_valid_candidate() -> None:
    repair_completion = AsyncMock(
        side_effect=[
            _tool_response(
                tool_name=PROPOSE_FLOW_TOOL_NAME,
                arguments={"plan_rationale": "Rename the analysis step."},
            ),
            _tool_response(
                tool_name=PROPOSE_FLOW_TOOL_NAME,
                arguments={
                    "plan_rationale": "Rename the analysis step.",
                    "steps": [
                        {
                            "kind": "modify",
                            "existing_step_ref": "existing_step_1",
                            "name": "Analyze deeply",
                        }
                    ],
                },
            ),
        ]
    )
    process_invocation = AsyncMock(
        side_effect=[
            ToolProcessingResult(
                feedback="The edit needs one concrete operation.",
                failure_kind="validation",
                failure_codes=frozenset({"empty_operations"}),
            ),
            ToolProcessingResult(events=(_plan_stream_event(),)),
        ]
    )

    events = _wire_events(
        [
            event
            async for event in run_tool_self_correction(
                _make_self_correction_request(
                    repair_completion=repair_completion,
                    process_tool_invocation=process_invocation,
                    self_correction_temperature=0.35,
                    self_correction_bumped_temperature=0.6,
                    max_self_correction_retries=3,
                    forced_proposal_temperature=0.1,
                    target_kind=TargetKind.EDIT,
                )
            )
        ]
    )

    assert repair_completion.await_count == 2
    assert process_invocation.await_count == 2
    assert [event["event"] for event in events] == ["status", "plan"]


async def _run_repair_capturing(
    *,
    max_retries: int,
    failure_kind: str = "validation",
    failure_codes: frozenset[str] = frozenset(),
    initial_failure_codes: frozenset[str] = frozenset(),
    base_temperature: float = 0.35,
    bumped_temperature: float = 0.6,
    target_kind: TargetKind = TargetKind.CREATE,
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
            failure_codes=initial_failure_codes,
            llm_messages=[{"role": "user", "content": "go"}],
            self_correction_temperature=base_temperature,
            self_correction_bumped_temperature=bumped_temperature,
            max_self_correction_retries=max_retries,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=process_invocation,
            target_kind=target_kind,
        )
    ):
        events.append(encode_ai_builder_stream_event(event))

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
@pytest.mark.parametrize(
    ("failure_code", "expected_message_part"),
    [
        ("empty_steps", "did not contain any flow steps"),
        ("first_step_invalid_source", "connect the flow input to the first step"),
        ("flow_input_not_first", "connect the flow input to the first step"),
    ],
)
async def test_run_tool_self_correction_selects_terminal_message_from_failure_code(
    failure_code: str,
    expected_message_part: str,
) -> None:
    _, _, events = await _run_repair_capturing(
        max_retries=0,
        failure_kind="validation",
        failure_codes=frozenset({failure_code}),
    )

    payload = json.loads(events[-1]["data"])

    assert expected_message_part in payload["message"]
    assert "still bad" not in payload["message"]


@pytest.mark.asyncio
async def test_run_tool_self_correction_surfaces_bounded_quality_failure_codes() -> (
    None
):
    _, _, events = await _run_repair_capturing(
        max_retries=0,
        failure_kind="quality",
        failure_codes=frozenset(
            {"final_text_step_must_reference_relevant_structured_outputs"}
        ),
    )

    payload = json.loads(events[-1]["data"])

    assert payload["code"] == "self_correction_quality_failure"
    assert payload["details"] == {
        "quality_failure_codes": (
            "final_text_step_must_reference_relevant_structured_outputs"
        ),
    }
    assert "still bad" not in json.dumps(payload["details"])


@pytest.mark.asyncio
async def test_run_tool_self_correction_surfaces_bounded_validation_failure_codes() -> (
    None
):
    _, _, events = await _run_repair_capturing(
        max_retries=0,
        failure_kind="validation",
        failure_codes=frozenset(
            {
                "duplicate_step_name",
                "assembly_explicit_refs_not_supported",
                "assembly_source_file_first_step_requires_json",
                "assembly_step_output_type_mismatch",
            }
        ),
    )

    payload = json.loads(events[-1]["data"])

    assert payload["code"] == "self_correction_invalid_plan"
    assert payload["details"] == {
        "failure_codes": (
            "assembly_explicit_refs_not_supported,"
            "assembly_source_file_first_step_requires_json,"
            "assembly_step_output_type_mismatch"
        ),
        "failure_codes_count": 4,
    }


@pytest.mark.asyncio
async def test_run_tool_self_correction_uses_fallback_for_missing_retry_feedback() -> (
    None
):
    observed_messages: list[list[dict[str, Any]]] = []

    async def call_proposal_completion(
        request: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        observed_messages.append(request.messages)
        return _bad_tool_response(len(observed_messages))

    async def process_invocation(_: ToolRetryInvocation) -> ToolProcessingResult:
        return ToolProcessingResult(failure_kind="validation")

    events: list[dict[str, str]] = []
    async for event in run_tool_self_correction(
        _make_self_correction_request(
            error_message="original invalid",
            llm_messages=[{"role": "user", "content": "go"}],
            self_correction_temperature=0.35,
            self_correction_bumped_temperature=0.6,
            max_self_correction_retries=1,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.CREATE,
        )
    ):
        events.append(encode_ai_builder_stream_event(event))

    assert events[-1]["event"] == "error"
    assert len(observed_messages) == 2
    retry_feedback = observed_messages[1][-1]
    assert retry_feedback["role"] == "tool"
    assert "Invalid tool payload" in str(retry_feedback["content"])


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
                ),
                finish_reason="stop",
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
        events.append(encode_ai_builder_stream_event(event))

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
async def test_run_tool_self_correction_forced_text_quality_failure_surfaces_codes() -> (
    None
):
    text_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="Här är en korrigerad plan.",
                    tool_calls=None,
                ),
                finish_reason="stop",
            )
        ]
    )
    tool_response = _tool_response(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={"flow_name": "T", "plan_rationale": "R", "steps": []},
    )

    call_proposal_completion = AsyncMock(side_effect=[text_response, tool_response])

    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return ToolProcessingResult(
            feedback="still bad",
            failure_kind="quality",
            failure_codes=frozenset(
                {"final_text_step_must_reference_relevant_structured_outputs"}
            ),
        )

    events: list[dict[str, str]] = []
    async for event in run_tool_self_correction(
        _make_self_correction_request(
            error_message="Quality issues.",
            llm_messages=[{"role": "user", "content": "build flow"}],
            self_correction_temperature=0.35,
            self_correction_bumped_temperature=0.6,
            max_self_correction_retries=1,
            forced_proposal_temperature=0.1,
            repair_completion=call_proposal_completion,
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.CREATE,
        )
    ):
        events.append(encode_ai_builder_stream_event(event))

    payload = json.loads(events[-1]["data"])

    assert payload["code"] == "self_correction_quality_failure"
    assert payload["details"] == {
        "quality_failure_codes": (
            "final_text_step_must_reference_relevant_structured_outputs"
        )
    }
    assert "still bad" not in json.dumps(payload["details"])


@pytest.mark.asyncio
async def test_run_tool_self_correction_uses_request_id_on_forced_retry_validation_error() -> (
    None
):
    tracker = ProposalTurnTelemetry(
        request_id="req-repair-feedback",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    text_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="Här är en korrigerad plan.",
                    tool_calls=None,
                ),
                finish_reason="stop",
            )
        ]
    )
    tool_response = _tool_response(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={
            "flow_name": "Invalid",
            "plan_rationale": "Invalid step reference.",
            "steps": [{"name": "Step", "instructions": "Do work."}],
        },
    )
    responses = [text_response, tool_response]

    async def call_proposal_completion(
        request: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        tracker.record_response(
            finish_reason="tool_calls",
            usage=_make_usage(
                prompt_tokens=7,
                completion_tokens=3,
                total_tokens=10,
            ),
            counts_as_repair=request.counts_as_repair,
        )
        return responses.pop(0)

    async def process_invocation(
        _: ToolRetryInvocation,
    ) -> ToolProcessingResult:
        return ToolProcessingResult(
            feedback="Validation errors:\n1. Invalid step reference 'step_k'.",
            failure_kind="validation",
        )

    request = _make_self_correction_request(
        request_id="req-repair-feedback",
        error_message="Invalid propose_flow draft.",
        llm_messages=[{"role": "user", "content": "build flow USER SECRET"}],
        self_correction_temperature=0.35,
        self_correction_bumped_temperature=0.6,
        max_self_correction_retries=1,
        forced_proposal_temperature=0.1,
        repair_completion=call_proposal_completion,
        process_tool_invocation=process_invocation,
        target_kind=TargetKind.CREATE,
        usage_tracker=tracker,
    )
    session_id = request.ctx.session_id

    with _captured_proposal_telemetry() as telemetry_records:
        events = _wire_events(
            [event async for event in run_tool_self_correction(request)]
        )

    assert events[-1]["event"] == "error"
    payload = json.loads(events[-1]["data"])
    assert payload["request_id"] == "req-repair-feedback"
    assert payload["code"] == "self_correction_invalid_plan"
    assert "Invalid step reference" not in payload["message"]
    failed_payload = _single_failed_turn_payload(telemetry_records)
    assert failed_payload["request_id"] == "req-repair-feedback"
    assert failed_payload["session_id"] == str(session_id)
    assert failed_payload["target_kind"] == "create"
    assert failed_payload["branch"] == "self_correction_text_forced_retry_failed"
    assert failed_payload["repair_attempts"] == 2
    assert failed_payload["llm_calls"] == 2
    assert failed_payload["prompt_tokens"] == 14
    assert failed_payload["completion_tokens"] == 6
    assert failed_payload["total_tokens"] == 20
    assert failed_payload["final_failure_kind"] == "invalid_repair_plan"
    assert failed_payload["final_error_code"] == "self_correction_invalid_plan"
    encoded_payload = json.dumps(failed_payload, default=str)
    assert "USER SECRET" not in encoded_payload
    assert "Invalid step reference" not in encoded_payload


@pytest.mark.asyncio
async def test_run_tool_self_correction_internal_completion_error_logs_failed_turn() -> (
    None
):
    tracker = ProposalTurnTelemetry(
        request_id="req-repair-provider-error",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )

    async def call_proposal_completion(
        _: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        raise RuntimeError("provider unavailable")

    request = _make_self_correction_request(
        request_id="req-repair-provider-error",
        error_message="Invalid propose_flow draft.",
        llm_messages=[{"role": "user", "content": "build flow"}],
        self_correction_temperature=0.35,
        self_correction_bumped_temperature=0.6,
        max_self_correction_retries=0,
        forced_proposal_temperature=0.1,
        repair_completion=call_proposal_completion,
        process_tool_invocation=AsyncMock(),
        target_kind=TargetKind.CREATE,
        usage_tracker=tracker,
    )

    with _captured_proposal_telemetry() as telemetry_records:
        events = _wire_events(
            [event async for event in run_tool_self_correction(request)]
        )

    assert events[-1]["event"] == "error"
    payload = json.loads(events[-1]["data"])
    assert payload["code"] == "planner_upstream_error"
    failed_payload = _single_failed_turn_payload(telemetry_records)
    assert failed_payload["branch"] == "self_correction_completion_error"
    assert failed_payload["final_failure_kind"] == "internal_error"
    assert failed_payload["final_error_code"] == "planner_upstream_error"
    assert failed_payload["repair_attempts"] == 1
    assert failed_payload["llm_calls"] == 1


@pytest.mark.asyncio
async def test_run_tool_self_correction_propagates_known_rejection_without_retry() -> (
    None
):
    tracker = ProposalTurnTelemetry(
        request_id="req-repair-rate-limit",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    rejection = classify_ai_builder_provider_failure(
        RateLimitError(
            "sensitive-provider-material",
            model="private-model",
            llm_provider="private-provider",
        ),
        stage="proposal_completion",
        request_id=tracker.request_id,
    ).as_exception()
    repair_completion = AsyncMock(side_effect=rejection)
    request = _make_self_correction_request(
        request_id=tracker.request_id,
        error_message="Invalid propose_flow draft.",
        llm_messages=[{"role": "user", "content": "build flow"}],
        self_correction_temperature=0.35,
        self_correction_bumped_temperature=0.6,
        max_self_correction_retries=2,
        forced_proposal_temperature=0.1,
        repair_completion=repair_completion,
        process_tool_invocation=AsyncMock(),
        target_kind=TargetKind.CREATE,
        usage_tracker=tracker,
    )

    with pytest.raises(AIBuilderKnownProviderRejectionException):
        _ = [event async for event in run_tool_self_correction(request)]

    assert repair_completion.await_count == 1


@pytest.mark.asyncio
async def test_run_tool_self_correction_handles_empty_completion_choices() -> None:
    tracker = ProposalTurnTelemetry(
        request_id="req-empty-choices",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )

    async def call_proposal_completion(
        request: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        tracker.record_response(
            finish_reason=None,
            usage=_make_usage(prompt_tokens=4, completion_tokens=0, total_tokens=4),
            counts_as_repair=request.counts_as_repair,
        )
        return SimpleNamespace(choices=())

    request = _make_self_correction_request(
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
        usage_tracker=tracker,
    )
    with _captured_proposal_telemetry() as telemetry_records:
        events = _wire_events(
            [event async for event in run_tool_self_correction(request)]
        )

    assert events[-1]["event"] == "error"
    payload = json.loads(events[-1]["data"])
    assert payload["request_id"] == "req-empty-choices"
    assert payload["code"] == "planner_invalid_repair_response"
    failed_payload = _single_failed_turn_payload(telemetry_records)
    assert failed_payload["branch"] == "self_correction_empty_completion_choices"
    assert failed_payload["final_failure_kind"] == "invalid_repair_response"
    assert failed_payload["final_error_code"] == "planner_invalid_repair_response"
    assert failed_payload["repair_attempts"] == 1
    assert failed_payload["llm_calls"] == 1


@pytest.mark.asyncio
async def test_run_tool_self_correction_terminalizes_provider_truncation() -> None:
    tracker = ProposalTurnTelemetry(
        request_id="req-repair-truncated",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    tool_call = SimpleNamespace(
        id="call_truncated_repair",
        function=SimpleNamespace(
            name=PROPOSE_FLOW_TOOL_NAME,
            arguments="{not json MODEL OUTPUT SECRET",
        ),
    )
    response = _truncated_response(
        message=SimpleNamespace(
            content="MODEL OUTPUT SECRET",
            tool_calls=[tool_call],
        )
    )

    async def call_proposal_completion(
        request: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        tracker.record_response(
            finish_reason="length",
            usage=_make_usage(prompt_tokens=6, completion_tokens=8, total_tokens=14),
            counts_as_repair=request.counts_as_repair,
        )
        return response

    process_invocation = AsyncMock()
    request = _make_self_correction_request(
        request_id="req-repair-truncated",
        error_message="Invalid propose_flow draft.",
        llm_messages=[{"role": "user", "content": "build flow USER SECRET"}],
        self_correction_temperature=0.35,
        self_correction_bumped_temperature=0.6,
        max_self_correction_retries=0,
        forced_proposal_temperature=0.1,
        repair_completion=call_proposal_completion,
        process_tool_invocation=process_invocation,
        target_kind=TargetKind.CREATE,
        usage_tracker=tracker,
    )
    session_id = request.ctx.session_id

    with _captured_proposal_telemetry() as telemetry_records:
        events = _wire_events(
            [event async for event in run_tool_self_correction(request)]
        )

    process_invocation.assert_not_awaited()
    assert [event["event"] for event in events] == ["status", "error"]
    payload = json.loads(events[-1]["data"])
    assert payload["code"] == "planner_output_too_long"
    assert payload["phase"] == "self_correction"
    assert payload["request_id"] == "req-repair-truncated"
    failed_payload = _single_failed_turn_payload(telemetry_records)
    assert failed_payload["request_id"] == "req-repair-truncated"
    assert failed_payload["session_id"] == str(session_id)
    assert failed_payload["target_kind"] == "create"
    assert failed_payload["branch"] == "provider_truncation"
    assert failed_payload["repair_attempts"] == 1
    assert failed_payload["llm_calls"] == 1
    assert failed_payload["prompt_tokens"] == 6
    assert failed_payload["completion_tokens"] == 8
    assert failed_payload["total_tokens"] == 14
    assert failed_payload["final_failure_kind"] == "provider_truncation"
    assert failed_payload["final_error_code"] == "planner_output_too_long"
    assert failed_payload["provider_finish_reason"] == "length"
    encoded_payload = json.dumps(failed_payload, default=str)
    assert "USER SECRET" not in encoded_payload
    assert "MODEL OUTPUT SECRET" not in encoded_payload


@pytest.mark.asyncio
async def test_run_tool_self_correction_invalid_tool_result_logs_failed_turn() -> None:
    tracker = ProposalTurnTelemetry(
        request_id="req-quality-repair",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )

    async def call_proposal_completion(
        request: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        tracker.record_response(
            finish_reason="tool_calls",
            usage=_make_usage(prompt_tokens=8, completion_tokens=3, total_tokens=11),
            counts_as_repair=request.counts_as_repair,
        )
        return _bad_tool_response(1)

    async def process_invocation(_: ToolRetryInvocation) -> ToolProcessingResult:
        return ToolProcessingResult(feedback="still bad", failure_kind="quality")

    request = _make_self_correction_request(
        request_id="req-quality-repair",
        error_message="Invalid propose_flow draft.",
        llm_messages=[{"role": "user", "content": "build flow"}],
        self_correction_temperature=0.35,
        self_correction_bumped_temperature=0.6,
        max_self_correction_retries=0,
        forced_proposal_temperature=0.1,
        repair_completion=call_proposal_completion,
        process_tool_invocation=process_invocation,
        target_kind=TargetKind.CREATE,
        usage_tracker=tracker,
    )

    with _captured_proposal_telemetry() as telemetry_records:
        events = _wire_events(
            [event async for event in run_tool_self_correction(request)]
        )

    assert events[-1]["event"] == "error"
    payload = json.loads(events[-1]["data"])
    assert payload["code"] == "self_correction_quality_failure"
    failed_payload = _single_failed_turn_payload(telemetry_records)
    assert failed_payload["branch"] == "self_correction_invalid_tool_result"
    assert failed_payload["final_failure_kind"] == "repair_quality_failure"
    assert failed_payload["final_error_code"] == "self_correction_quality_failure"
    assert failed_payload["repair_attempts"] == 1
    assert failed_payload["llm_calls"] == 1


@pytest.mark.asyncio
async def test_run_tool_self_correction_missing_tool_response_logs_failed_turn() -> (
    None
):
    tracker = ProposalTurnTelemetry(
        request_id="req-missing-repair-tool",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="", tool_calls=None),
                finish_reason="stop",
            ),
        ]
    )

    async def call_proposal_completion(
        request: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        tracker.record_response(
            finish_reason="stop",
            usage=_make_usage(prompt_tokens=5, completion_tokens=1, total_tokens=6),
            counts_as_repair=request.counts_as_repair,
        )
        return response

    request = _make_self_correction_request(
        request_id="req-missing-repair-tool",
        error_message="Invalid propose_flow draft.",
        llm_messages=[{"role": "user", "content": "build flow"}],
        self_correction_temperature=0.35,
        self_correction_bumped_temperature=0.6,
        max_self_correction_retries=0,
        forced_proposal_temperature=0.1,
        repair_completion=call_proposal_completion,
        process_tool_invocation=AsyncMock(),
        target_kind=TargetKind.CREATE,
        usage_tracker=tracker,
    )

    with _captured_proposal_telemetry() as telemetry_records:
        events = _wire_events(
            [event async for event in run_tool_self_correction(request)]
        )

    assert events[-1]["event"] == "error"
    payload = json.loads(events[-1]["data"])
    assert payload["code"] == "planner_invalid_repair_response"
    failed_payload = _single_failed_turn_payload(telemetry_records)
    assert failed_payload["branch"] == "self_correction_missing_tool_response"
    assert failed_payload["final_failure_kind"] == "invalid_repair_response"
    assert failed_payload["final_error_code"] == "planner_invalid_repair_response"
    assert failed_payload["provider_finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_run_tool_self_correction_rejects_malformed_correction_tool_arguments() -> (
    None
):
    tracker = ProposalTurnTelemetry(
        request_id="req-malformed-repair",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    tool_call = SimpleNamespace(
        id="call_invalid_repair",
        function=SimpleNamespace(
            name=PROPOSE_FLOW_TOOL_NAME,
            arguments="{not json MODEL OUTPUT SECRET",
        ),
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=[tool_call]),
                finish_reason="tool_calls",
            )
        ]
    )
    process_invocation = AsyncMock()

    async def call_proposal_completion(
        request: ProposalCompletionRequest,
    ) -> SimpleNamespace:
        tracker.record_response(
            finish_reason="tool_calls",
            usage=_make_usage(prompt_tokens=6, completion_tokens=2, total_tokens=8),
            counts_as_repair=request.counts_as_repair,
        )
        return response

    request = _make_self_correction_request(
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
        usage_tracker=tracker,
    )
    with _captured_proposal_telemetry() as telemetry_records:
        events = _wire_events(
            [event async for event in run_tool_self_correction(request)]
        )

    assert events[-1]["event"] == "error"
    payload = json.loads(events[-1]["data"])
    assert payload["request_id"] == "req-malformed-repair"
    assert payload["code"] == "self_correction_invalid_payload"
    process_invocation.assert_not_awaited()
    failed_payload = _single_failed_turn_payload(telemetry_records)
    assert failed_payload["branch"] == "self_correction_malformed_tool_arguments"
    assert failed_payload["final_failure_kind"] == "invalid_repair_payload"
    assert failed_payload["final_error_code"] == "self_correction_invalid_payload"
    assert failed_payload["repair_attempts"] == 1
    assert failed_payload["llm_calls"] == 1
    assert "MODEL OUTPUT SECRET" not in json.dumps(failed_payload, default=str)


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
                ),
                finish_reason="stop",
            )
        ]
    )
    invalid_tool_response = _tool_response(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={
            "flow_name": "Invalid repaired flow",
            "plan_rationale": "Repair duplicate names.",
            "steps": [{"name": "Duplicate", "instructions": "Do the work."}],
        },
    )
    valid_tool_response = _tool_response(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={
            "flow_name": "Valid repaired flow",
            "plan_rationale": "Repair duplicate names.",
            "steps": [{"name": "Unique", "instructions": "Do the work."}],
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
        return ToolProcessingResult(events=(_plan_stream_event(),))

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
        events.append(encode_ai_builder_stream_event(event))

    assert events[-1]["event"] == "plan"
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
                ),
                finish_reason="stop",
            )
        ]
    )
    invalid_tool_response = _tool_response(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={
            "flow_name": "Invalid repaired flow",
            "plan_rationale": "Still duplicate.",
            "steps": [{"name": "Duplicate", "instructions": "Do work."}],
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
        events.append(encode_ai_builder_stream_event(event))

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
                ),
                finish_reason="stop",
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
        events.append(encode_ai_builder_stream_event(event))

    text_events = [event for event in events if event.get("event") == "text"]
    assert text_events, (
        "Short, question-mark-bearing planner text without action keywords "
        "is a legitimate clarification request and must still surface to the user; "
        f"got events: {events}"
    )


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
        _make_forced_tool_after_text_request(
            correction_messages=[{"role": "user", "content": "Build"}],
            assistant_text="Här är planen.",
            conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
            new_messages_start=1,
            max_output_tokens=4096,
            forced_tool_prompt="Now call propose_flow.",
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
            process_tool_invocation=process_invocation,
            target_kind=TargetKind.CREATE,
            request_id="req-forced-runtime",
            usage_tracker=tracker,
        )
    )

    assert result.events is not None
    wire_events = _wire_events(result.events)
    assert [event["event"] for event in wire_events] == ["error"]
    payload = json.loads(wire_events[0]["data"])
    assert payload["code"] == "architecture_materialization_failed"
    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_failure_kind"] == "architecture"
    assert telemetry["proposal_repair_invocation_count"] == 0


@pytest.mark.asyncio
async def test_self_correction_forced_text_architecture_error_uses_sanitized_event_and_telemetry() -> (
    None
):
    tracker = ProposalTurnTelemetry(
        request_id="req-self-correction-forced-text-tracker",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    text_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="Här är den korrigerade planen.",
                    tool_calls=None,
                ),
                finish_reason="stop",
            )
        ]
    )
    tool_response = _tool_response(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        arguments={"flow_name": "Broken", "plan_rationale": "R", "steps": []},
    )
    repair_completion = AsyncMock(side_effect=[text_response, tool_response])

    async def process_invocation(_: ToolRetryInvocation) -> ToolProcessingResult:
        raise AIBuilderArchitectureError(
            public_code="architecture_materialization_failed",
            detail="forced retry materialization failed",
        )

    request = _make_self_correction_request(
        request_id="req-self-correction-forced-text",
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        new_messages_start=1,
        error_message="Invalid flow",
        llm_messages=[{"role": "user", "content": "Build"}],
        self_correction_temperature=0.2,
        self_correction_bumped_temperature=0.5,
        max_self_correction_retries=3,
        forced_proposal_temperature=0.3,
        repair_completion=repair_completion,
        process_tool_invocation=process_invocation,
        target_kind=TargetKind.CREATE,
        usage_tracker=tracker,
    )

    events = _wire_events([event async for event in run_tool_self_correction(request)])

    assert [event["event"] for event in events] == ["status", "error"]
    payload = json.loads(events[1]["data"])
    assert payload["code"] == "architecture_materialization_failed"
    assert payload["request_id"] == "req-self-correction-forced-text"
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

    request = _make_self_correction_request(
        request_id="req-self-correction-runtime",
        conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        new_messages_start=1,
        error_message="Invalid flow",
        llm_messages=[{"role": "user", "content": "Build"}],
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
        process_tool_invocation=process_invocation,
        target_kind=TargetKind.CREATE,
        forced_tool_prompt="Now call propose_flow.",
        forced_proposal_temperature=0.3,
        usage_tracker=tracker,
    )

    events = _wire_events([event async for event in run_tool_self_correction(request)])

    assert [event["event"] for event in events] == ["status", "error"]
    payload = json.loads(events[1]["data"])
    assert payload["code"] == "architecture_critic_invariant_failed"
    telemetry = tracker.build_planner_telemetry()
    assert telemetry["proposal_first_attempt_failure_kind"] == "architecture"
    assert telemetry["proposal_repair_invocation_count"] == 0
