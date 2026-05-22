"""Transport contract tests for `AIBuilderPlanner.send_message`.

`send_message` bridges the builder's public SSE surface and the
orchestrator's structured-JSON planner pipeline. This suite pins the
`PlannerTurnResult` outcomes the planner can surface — dispatched
(ask_question / commit_architecture / confirm_requirements),
parse_failed with finish_reason=="length", and rejected — to specific
SSE event sequences.

Every test stubs `_prepare_planner_request` so the test owns the
downstream `PlannerPreparedRequest` shape without re-driving the
discovery runtime, and patches `run_planner_turn` at the planner's
import site to hand back a caller-crafted `PlannerTurnResult`. The
suite is therefore a contract test on the SSE emits alone, not on the
pipeline internals (those are exhaustively covered in
`test_ai_builder_planner_turn.py` and `test_ai_builder_orchestrator_v2.py`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.completion_models.infrastructure.tenant_model_capabilities import (
    StructuredOutputCapabilityDecision,
    StructuredOutputDecisionSource,
    StructuredOutputMode,
)
from intric.flows.ai_builder.ai_builder_action_policy import (
    PlannerActionPolicy,
    build_planner_action_policy,
)
from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    SlotClassificationMetadata,
    slot_classification_metadata_from_result,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderSession,
    SessionStatus,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_event_models import KeyDecisionPayload
from intric.flows.ai_builder.ai_builder_orchestrator import (
    AskQuestionAction,
    AskQuestionPayload,
    CommitArchitectureAction,
    CommitArchitecturePayload,
    ConfirmRequirementsAction,
    ConfirmRequirementsPayload,
    PlannerOutput,
    PlanningStateDelta,
    RejectionReason,
)
from intric.flows.ai_builder.ai_builder_planner import (
    AIBuilderPlanner,
    PlannerPreparedRequest,
)
from intric.flows.ai_builder.ai_builder_planner_turn import (
    PlannerTurnResult,
    TurnTelemetry,
)
from intric.flows.ai_builder.ai_builder_repair import CompletionMetadata
from intric.flows.ai_builder.ai_builder_response_format import (
    build_planner_request_response_format,
)
from intric.flows.ai_builder.ai_builder_server_actions import (
    build_server_planner_output,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
from intric.flows.ai_builder.ai_builder_slot_classifier import (
    ClassifiedSlot,
    SlotClassificationResult,
)
from intric.flows.ai_builder.planning_state import PlanningState


def _make_planner() -> AIBuilderPlanner:
    planner = AIBuilderPlanner(
        user=MagicMock(tenant_id=uuid4()),
        repo=AsyncMock(),
        litellm_client=AsyncMock(),
        planner_temperature=0.1,
        self_correction_temperature=0.1,
        forced_proposal_temperature=0.1,
        quality_retry_warning_codes=set(),
    )
    planner.repo.claim_session_send.return_value = True
    planner.repo.get_session.return_value = BuilderSession(
        id=uuid4(),
        tenant_id=planner.user.tenant_id,
        space_id=uuid4(),
        actor_user_id=uuid4(),
        target_kind=TargetKind.CREATE,
        status=SessionStatus.CHATTING,
        conversation=[],
        planning_state_version=0,
    )
    planner.repo.load_planning_state.return_value = None
    planner.repo.refresh_session_send_lease.return_value = True
    planner.repo.release_session_send.return_value = None
    return planner


def _make_prepared_request(
    *,
    should_emit_forced_followup: bool = False,
    slot_classification_metadata: SlotClassificationMetadata | None = None,
) -> PlannerPreparedRequest:
    return PlannerPreparedRequest(
        requirements_state=SimpleNamespace(latest_summary=None, confirmed=False),
        ui_language="en",
        discovery_block_message=None,
        llm_messages=[{"role": "system", "content": "system"}],
        should_emit_forced_followup=should_emit_forced_followup,
        base_planning_state_version=0,
        slot_classification_metadata=slot_classification_metadata,
    )


def _slot_classification_metadata() -> SlotClassificationMetadata:
    metadata = slot_classification_metadata_from_result(
        SlotClassificationResult(
            slots=(
                ClassifiedSlot(
                    slot_name="terminal_output",
                    value="structured_text",
                    confidence="high",
                    reason="user requested a readable report",
                ),
            )
        ),
        prompt_hash="a" * 64,
    )
    assert metadata is not None
    return metadata


def _make_turn(*, base_version: int = 0) -> SessionSendTurn:
    return SessionSendTurn(
        session_id=uuid4(),
        tenant_id=uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=base_version,
    )


def _turn_telemetry(outcome_kind: str, *, populated: bool = False) -> TurnTelemetry:
    return TurnTelemetry(
        request_id=None,
        model="openai/gpt-4o-mini",
        outcome_kind=outcome_kind,  # type: ignore[arg-type]
        wall_clock_ms=5,
        llm_calls_made=1,
        repair_attempts=0,
        architecture_commit_populated=populated,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        finish_reason=None,
    )


def _dispatched_result(
    *,
    action_kind: str,
    planner_output: PlannerOutput,
    populated: bool = False,
) -> PlannerTurnResult:
    return PlannerTurnResult(
        kind="dispatched",
        accepted_output=planner_output,
        dispatch_result=SimpleNamespace(
            action_kind=action_kind,
            new_planning_state_version=1,
        ),  # type: ignore[arg-type]
        turn_telemetry=_turn_telemetry("dispatched", populated=populated),
        llm_calls_made=1,
    )


def _planner_output(action_obj: Any) -> PlannerOutput:
    return PlannerOutput(
        planning_state_delta=PlanningStateDelta(base_planning_state_version=0),
        planner_action=action_obj,
    )


async def _collect_events(
    planner: AIBuilderPlanner, **kwargs: Any
) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    async for event in planner.send_message(**kwargs):
        events.append(event)
    return events


def _send_kwargs() -> dict[str, Any]:
    return {
        "session_id": uuid4(),
        "message": "Build a summarizer",
        "litellm_model": "openai/gpt-4o-mini",
        "litellm_kwargs": {},
        "available_models": None,
        "available_kbs": None,
        "flow": None,
        "assistant_snapshots": None,
        "attachment_files": None,
        "max_input_tokens": 4096,
        "max_output_tokens": 1024,
        "budget_policy": AIBuilderBudgetPolicy(
            conversation_safety_buffer_tokens=128,
            minimum_conversation_budget_tokens=256,
            unknown_model_context_window_tokens=8192,
        ),
    }


def _structured_decision(
    mode: StructuredOutputMode,
) -> StructuredOutputCapabilityDecision:
    if mode is StructuredOutputMode.JSON_OBJECT:
        return StructuredOutputCapabilityDecision(
            mode=mode,
            source=StructuredOutputDecisionSource.LITELLM_RESPONSE_FORMAT,
            supports_response_schema=False,
            supports_response_format=True,
        )
    if mode is StructuredOutputMode.STRICT_JSON_SCHEMA:
        return StructuredOutputCapabilityDecision(
            mode=mode,
            source=StructuredOutputDecisionSource.LITELLM_RESPONSE_SCHEMA,
            supports_response_schema=True,
            supports_response_format=True,
        )
    return StructuredOutputCapabilityDecision(
        mode=mode,
        source=StructuredOutputDecisionSource.NO_PROVIDER_SUPPORT,
        supports_response_schema=False,
        supports_response_format=False,
    )


@contextmanager
def _patched_send(
    turn_result: PlannerTurnResult | Callable[..., Any],
) -> Iterator[dict[str, AsyncMock]]:
    """Return a context manager patching `run_planner_turn` at the planner's import site.

    Each test hand-crafts the `PlannerTurnResult` it wants the planner
    to receive so the SSE assertions exercise only the branching
    inside `send_message`, not the orchestrator pipeline.
    """
    run_mock = (
        AsyncMock(side_effect=turn_result)
        if callable(turn_result) and not isinstance(turn_result, PlannerTurnResult)
        else AsyncMock(return_value=turn_result)
    )
    with patch(
        "intric.flows.ai_builder.ai_builder_planner.run_planner_turn",
        new=run_mock,
    ):
        yield {"run_planner_turn": run_mock}


@pytest.mark.asyncio
async def test_send_message_dispatched_ask_question_emits_text_plus_done() -> None:
    """`dispatched` + `ask_question` → text SSE with the prompt, then done.

    The orchestrator v2 `AskQuestionPayload` is a thin
    ``{question_id, slot_name, prompt}`` record, not a full
    structured-question payload. `send_message` surfaces the prompt
    via `text` so the client's existing text renderer keeps working
    while the structured-question adapter is a follow-up change.
    """
    planner = _make_planner()
    prepared = _make_prepared_request()
    action = AskQuestionAction(
        kind="ask_question",
        payload=AskQuestionPayload(
            question_id="primary_runtime_input",
            slot_name="primary_runtime_input",
            prompt="Vad ska flödet ta emot som input?",
        ),
    )
    output = _planner_output(action)
    turn_result = _dispatched_result(action_kind="ask_question", planner_output=output)

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        _patched_send(turn_result),
    ):
        events = await _collect_events(planner, **_send_kwargs())

    assert [event["event"] for event in events] == ["text", "done"]
    assert json.loads(events[0]["data"])["text"] == "Vad ska flödet ta emot som input?"


@pytest.mark.asyncio
async def test_send_message_downgrades_strict_capability_to_json_object_for_planner_output() -> (
    None
):
    planner = _make_planner()
    prepared = _make_prepared_request()
    output = _planner_output(
        AskQuestionAction(
            kind="ask_question",
            payload=AskQuestionPayload(
                question_id="primary_runtime_input",
                slot_name="primary_runtime_input",
                prompt="Input?",
            ),
        )
    )
    turn_result = _dispatched_result(action_kind="ask_question", planner_output=output)
    send_kwargs = _send_kwargs()
    send_kwargs["structured_output_decision"] = _structured_decision(
        StructuredOutputMode.STRICT_JSON_SCHEMA
    )

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        _patched_send(turn_result) as patched,
    ):
        await _collect_events(planner, **send_kwargs)

    call_kwargs = patched["run_planner_turn"].await_args.kwargs
    assert call_kwargs["litellm_kwargs"]["response_format"] == {"type": "json_object"}
    assert call_kwargs["litellm_kwargs"]["drop_params"] is True


@pytest.mark.asyncio
async def test_send_message_omits_response_format_when_provider_has_no_support() -> (
    None
):
    planner = _make_planner()
    prepared = _make_prepared_request()
    output = _planner_output(
        AskQuestionAction(
            kind="ask_question",
            payload=AskQuestionPayload(
                question_id="primary_runtime_input",
                slot_name="primary_runtime_input",
                prompt="Input?",
            ),
        )
    )
    turn_result = _dispatched_result(action_kind="ask_question", planner_output=output)
    send_kwargs = _send_kwargs()
    send_kwargs["structured_output_decision"] = _structured_decision(
        StructuredOutputMode.PROMPT_WITH_PYDANTIC_VALIDATION
    )

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        _patched_send(turn_result) as patched,
    ):
        await _collect_events(planner, **send_kwargs)

    call_kwargs = patched["run_planner_turn"].await_args.kwargs
    assert "response_format" not in call_kwargs["litellm_kwargs"]
    assert call_kwargs["litellm_kwargs"]["drop_params"] is True


@pytest.mark.asyncio
async def test_send_message_reuses_one_planner_response_format_selection_for_chain() -> (
    None
):
    planner = _make_planner()
    prepared = _make_prepared_request()
    output = _planner_output(
        CommitArchitectureAction(
            kind="commit_architecture",
            payload=CommitArchitecturePayload(note="All clear."),
        )
    )
    turn_result = _dispatched_result(
        action_kind="commit_architecture",
        planner_output=output,
        populated=True,
    )
    decision = _structured_decision(StructuredOutputMode.STRICT_JSON_SCHEMA)
    response_format_selection = build_planner_request_response_format(decision)
    send_kwargs = _send_kwargs()
    send_kwargs["structured_output_decision"] = decision

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_planner_request_response_format",
            return_value=response_format_selection,
        ) as build_selection,
        patch(
            "intric.flows.ai_builder.ai_builder_planner.run_planner_turn",
            new=AsyncMock(return_value=turn_result),
        ) as run_turn,
        patch.object(
            planner,
            "_dispatch_chained_server_action_after_commit",
            new=AsyncMock(return_value=None),
        ) as chained_dispatch,
    ):
        await _collect_events(planner, **send_kwargs)

    build_selection.assert_called_once_with(decision)
    primary_kwargs = run_turn.await_args.kwargs["litellm_kwargs"]
    assert primary_kwargs["response_format"] == {"type": "json_object"}
    assert (
        chained_dispatch.await_args.kwargs["response_format_selection"]
        is response_format_selection
    )


@pytest.mark.asyncio
async def test_send_message_dispatched_commit_architecture_emits_status_plus_done() -> (
    None
):
    """`dispatched` + `commit_architecture` → status SSE, then done.

    The architecture-commit outcome is not user-visible prose — it is
    a session-state transition the client reconstitutes via
    `load_planning_state`. `send_message` emits a bare status sentinel
    so consumers can flip to the post-commit UI without parsing free
    text.
    """
    planner = _make_planner()
    prepared = _make_prepared_request()
    action = CommitArchitectureAction(
        kind="commit_architecture",
        payload=CommitArchitecturePayload(note="All clear."),
    )
    output = _planner_output(action)
    turn_result = _dispatched_result(
        action_kind="commit_architecture",
        planner_output=output,
        populated=True,
    )

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        _patched_send(turn_result),
    ):
        events = await _collect_events(planner, **_send_kwargs())

    assert [event["event"] for event in events] == ["status", "done"]
    assert json.loads(events[0]["data"])["status"] == "architecture_committed"


@pytest.mark.asyncio
async def test_chained_server_action_uses_planner_response_format_selection() -> None:
    planner = _make_planner()
    server_output = _planner_output(
        ConfirmRequirementsAction(
            kind="confirm_requirements",
            payload=ConfirmRequirementsPayload(summary="Ready", key_decisions=[]),
        )
    )
    turn_result = _dispatched_result(
        action_kind="confirm_requirements",
        planner_output=server_output,
    )
    response_format_selection = build_planner_request_response_format(
        _structured_decision(StructuredOutputMode.STRICT_JSON_SCHEMA)
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner.build_server_planner_output",
            return_value=server_output,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.run_planner_turn",
            new=AsyncMock(return_value=turn_result),
        ) as run_turn,
    ):
        result = await planner._dispatch_chained_server_action_after_commit(
            turn=_make_turn(base_version=1),
            conversation=[],
            litellm_model="openai/gpt-4o-mini",
            litellm_kwargs={"api_key": "sk-test"},
            response_format_selection=response_format_selection,
            flow=None,
            requirements_confirmed=False,
            ui_language="en",
        )

    assert result is turn_result
    call_kwargs = run_turn.await_args.kwargs
    assert call_kwargs["litellm_kwargs"]["api_key"] == "sk-test"
    assert call_kwargs["litellm_kwargs"]["response_format"] == {"type": "json_object"}
    assert call_kwargs["litellm_kwargs"]["drop_params"] is True


@pytest.mark.asyncio
async def test_send_message_does_not_persist_internal_commit_note_as_assistant_text() -> (
    None
):
    planner = _make_planner()
    prepared = _make_prepared_request(
        slot_classification_metadata=_slot_classification_metadata(),
    )
    action = CommitArchitectureAction(
        kind="commit_architecture",
        payload=CommitArchitecturePayload(
            note="Architecture committed from resolved planning state."
        ),
    )
    output = _planner_output(action)
    turn_result = _dispatched_result(
        action_kind="commit_architecture",
        planner_output=output,
        populated=True,
    )
    captured: dict[str, list[Any]] = {}

    async def run_and_capture(**kwargs: Any) -> PlannerTurnResult:
        captured["new_messages"] = kwargs["build_new_messages"](
            output,
            _turn_telemetry("dispatched", populated=True),
        )
        return turn_result

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        _patched_send(run_and_capture),
    ):
        await _collect_events(planner, **_send_kwargs())

    assert [message.role for message in captured["new_messages"]] == ["user"]
    assert captured["new_messages"][0].metadata is not None
    assert "slot_classification" in captured["new_messages"][0].metadata
    assert all(
        "Architecture committed" not in message.content
        for message in captured["new_messages"]
    )


@pytest.mark.asyncio
async def test_send_message_dispatched_confirm_requirements_emits_versioned_summary_event() -> (
    None
):
    """`dispatched` + `confirm_requirements` → `requirements_summary` SSE.

    The confirm turn is the primitive that unblocks every downstream
    architecture + plan turn. The client needs the full structured
    summary (summary prose, key decisions, input/output descriptions,
    assumptions, manual-setup notes) AND a stable `requirements_version`
    so a later user confirmation can be matched against the exact
    summary it was shown. A plain text SSE would drop that contract and
    the frontend would have to reconstruct the summary from
    conversation state, racing against turn-compaction.
    """
    planner = _make_planner()
    prepared = _make_prepared_request()
    action = ConfirmRequirementsAction(
        kind="confirm_requirements",
        payload=ConfirmRequirementsPayload(
            summary="Ett flöde som sammanfattar mötestranskript i kort text.",
            key_decisions=[
                KeyDecisionPayload(topic="Indata", decision="Ljudfiler"),
                KeyDecisionPayload(topic="Utdata", decision="Kort text"),
            ],
            input_description="En ljudfil per körning.",
            output_description="En kort textsammanfattning.",
            assumptions=["Ljudfilen är under 30 minuter."],
            manual_setup_notes=[],
        ),
    )
    output = _planner_output(action)
    turn_result = _dispatched_result(
        action_kind="confirm_requirements", planner_output=output
    )

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        _patched_send(turn_result),
    ):
        events = await _collect_events(planner, **_send_kwargs())

    assert [event["event"] for event in events] == ["requirements_summary", "done"]
    payload = json.loads(events[0]["data"])
    assert (
        payload["summary"] == "Ett flöde som sammanfattar mötestranskript i kort text."
    )
    assert payload["input_description"] == "En ljudfil per körning."
    assert payload["output_description"] == "En kort textsammanfattning."
    assert len(payload["key_decisions"]) == 2
    assert isinstance(payload["requirements_version"], str)
    assert len(payload["requirements_version"]) == 64


@pytest.mark.asyncio
async def test_send_message_parse_failed_with_length_finish_reason_emits_output_too_long() -> (
    None
):
    """Truncated LLM response → `planner_output_too_long` error code.

    `CompletionMetadata.finish_reason == "length"` is the LLM signaling
    its `max_tokens` budget truncated the response mid-generation. The
    planner's pipeline catches this at parse time and surfaces it as
    `parse_failed` with the truncation signal preserved in
    `final_completion`. `send_message` maps it to a user-grade error
    code rather than a generic parse failure, so the UI can suggest
    picking a more capable model.
    """
    planner = _make_planner()
    prepared = _make_prepared_request()
    truncated_turn = PlannerTurnResult(
        kind="parse_failed",
        final_completion=CompletionMetadata(
            finish_reason="length",
            prompt_tokens=1000,
            completion_tokens=2048,
            total_tokens=3048,
        ),
        parse_error_raw="<truncated JSON>",
        parse_error_message="unexpected EOF",
        llm_calls_made=1,
        turn_telemetry=_turn_telemetry("parse_failed"),
    )

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        _patched_send(truncated_turn),
    ):
        events = await _collect_events(planner, **_send_kwargs())

    assert [event["event"] for event in events] == ["error", "done"]
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "planner_output_too_long"
    assert payload["phase"] == "planner"


@pytest.mark.asyncio
async def test_send_message_rejected_emits_planner_rejected_error() -> None:
    """Terminal rejection from the pipeline → `planner_rejected` error SSE.

    `run_planner_turn` returns `rejected` when the monotonicity
    guardrails exhausted the repair budget; nothing was persisted.
    `send_message` surfaces the terminal error with a stable code so
    clients can branch on it without parsing the freeform detail from
    the rejection reason.
    """
    planner = _make_planner()
    prepared = _make_prepared_request()
    rejected_turn = PlannerTurnResult(
        kind="rejected",
        rejection=RejectionReason(
            code="off_topic_question",
            detail="asked a question that resolved nothing",
        ),
        final_completion=None,
        llm_calls_made=1,
        turn_telemetry=_turn_telemetry("rejected"),
    )

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        _patched_send(rejected_turn),
    ):
        events = await _collect_events(planner, **_send_kwargs())

    assert [event["event"] for event in events] == ["error", "done"]
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "planner_rejected"
    # The user-facing message must not leak internal vocabulary
    # (orchestrator / invariant / rejection / planner-implementation terms).
    # Stable codes cover that information surface; the message is a
    # plain-language recovery hint.
    message = payload["message"].lower()
    for leaked in ("orchestrator", "invariant", "rejection", "monotonicity"):
        assert leaked not in message, (
            f"user-facing rejection message must not leak {leaked!r}"
        )


@pytest.mark.asyncio
async def test_send_message_orchestration_context_uses_rebuilt_state() -> None:
    """The slot sets on the passed-through OrchestrationContext must be
    derived from the SAME planning state the projection renders into the
    prompt — otherwise the orchestrator rejects turns that the model
    sees as valid.

    Covers the pre-turn vs. current-turn divergence: the prompt shows
    both core slots resolved, so the planner emits a valid
    `commit_architecture`, but the orchestrator evaluates against a
    pre-turn context where those slots are still unresolved — and
    rejects the commit as premature. Feeding rebuilt state here keeps
    both sides in lockstep.
    """
    from intric.flows.ai_builder.planning_state import (
        BUILDER_SCHEMA_VERSION,
        FCM_VERSION,
        PLANNER_CONTRACT_VERSION,
        EvidenceRef,
        PlanningState,
        ResolvedSlot,
    )

    planner = _make_planner()

    def _slot(name: str, value: str) -> ResolvedSlot:
        return ResolvedSlot(
            name=name,
            value=value,
            source="structured_answer",
            confidence="high",
            evidence=(),
        )

    rebuilt_both_resolved = PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        phase="discovering",
        evidence=EvidenceRef(conversation_message_ids=[]),
        resolved_slots={
            "primary_runtime_input": _slot("primary_runtime_input", "text"),
            "terminal_output": _slot("terminal_output", "text"),
        },
    )
    prepared = PlannerPreparedRequest(
        requirements_state=SimpleNamespace(latest_summary=None, confirmed=False),
        ui_language="en",
        discovery_block_message=None,
        llm_messages=[{"role": "system", "content": "system"}],
        should_emit_forced_followup=False,
        base_planning_state_version=0,
        rebuilt_planning_state=rebuilt_both_resolved,
    )

    action = ConfirmRequirementsAction(
        kind="confirm_requirements",
        payload=ConfirmRequirementsPayload(summary="Summary."),
    )
    output = _planner_output(action)
    turn_result = _dispatched_result(
        action_kind="confirm_requirements", planner_output=output
    )

    captured: dict[str, Any] = {}

    async def _capture_turn(**kwargs: Any) -> PlannerTurnResult:
        captured["orchestration_context"] = kwargs["orchestration_context"]
        return turn_result

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.run_planner_turn",
            new=AsyncMock(side_effect=_capture_turn),
        ),
    ):
        await _collect_events(planner, **_send_kwargs())

    ctx = captured["orchestration_context"]
    # Both core slots resolved → commit is no longer blocked.
    assert ctx.unresolved_architectural_choices == frozenset()
    # Those same slots do not appear on the non-core required-slot surface.
    assert "primary_runtime_input" not in ctx.required_slot_names
    assert "terminal_output" not in ctx.required_slot_names


@pytest.mark.asyncio
async def test_send_message_orchestration_context_blocks_commit_until_core_slots_resolve() -> (
    None
):
    """Mirror of the happy-path context test: when only one core slot is
    resolved, the commit gate still blocks.

    Asserts the pattern-agnostic `unresolved_architectural_choices`
    reflects exactly the un-resolved core slot. Core slots are allowed
    through that dedicated field; `required_slot_names` is now reserved
    for non-core discovery-selected questions.
    """
    from intric.flows.ai_builder.planning_state import (
        BUILDER_SCHEMA_VERSION,
        FCM_VERSION,
        PLANNER_CONTRACT_VERSION,
        EvidenceRef,
        PlanningState,
        ResolvedSlot,
    )

    planner = _make_planner()

    partial = PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        phase="discovering",
        evidence=EvidenceRef(conversation_message_ids=[]),
        resolved_slots={
            "primary_runtime_input": ResolvedSlot(
                name="primary_runtime_input",
                value="text",
                source="structured_answer",
                confidence="high",
                evidence=(),
            ),
        },
    )
    prepared = PlannerPreparedRequest(
        requirements_state=SimpleNamespace(latest_summary=None, confirmed=False),
        ui_language="en",
        discovery_block_message=None,
        llm_messages=[{"role": "system", "content": "system"}],
        should_emit_forced_followup=False,
        base_planning_state_version=0,
        rebuilt_planning_state=partial,
    )

    action = AskQuestionAction(
        kind="ask_question",
        payload=AskQuestionPayload(
            question_id="terminal_output",
            slot_name="terminal_output",
            prompt="?",
        ),
    )
    output = _planner_output(action)
    turn_result = _dispatched_result(action_kind="ask_question", planner_output=output)

    captured: dict[str, Any] = {}

    async def _capture_turn(**kwargs: Any) -> PlannerTurnResult:
        captured["orchestration_context"] = kwargs["orchestration_context"]
        return turn_result

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.run_planner_turn",
            new=AsyncMock(side_effect=_capture_turn),
        ),
    ):
        await _collect_events(planner, **_send_kwargs())

    ctx = captured["orchestration_context"]
    assert ctx.unresolved_architectural_choices == frozenset({"terminal_output"})
    assert "terminal_output" not in ctx.required_slot_names
    assert "primary_runtime_input" not in ctx.required_slot_names


@pytest.mark.asyncio
async def test_send_message_uses_discovery_selected_questions_as_non_core_ask_surface() -> (
    None
):
    planner = _make_planner()
    prepared = PlannerPreparedRequest(
        requirements_state=SimpleNamespace(latest_summary=None, confirmed=False),
        ui_language="en",
        discovery_block_message=None,
        llm_messages=[{"role": "system", "content": "system"}],
        should_emit_forced_followup=False,
        base_planning_state_version=0,
        rebuilt_planning_state=PlanningState.empty(),
        action_policy=build_planner_action_policy(
            session_state=PlanningState.empty(),
            unresolved_architectural_choices=frozenset(
                {"primary_runtime_input", "terminal_output"}
            ),
            selected_discovery_question_ids=frozenset(
                {"document_material_scope", "runtime_metadata_fields"}
            ),
        ),
    )

    action = AskQuestionAction(
        kind="ask_question",
        payload=AskQuestionPayload(
            question_id="document_material_scope",
            slot_name="document_material_scope",
            prompt="?",
        ),
    )
    output = _planner_output(action)
    turn_result = _dispatched_result(action_kind="ask_question", planner_output=output)

    captured: dict[str, Any] = {}

    async def _capture_turn(**kwargs: Any) -> PlannerTurnResult:
        captured["orchestration_context"] = kwargs["orchestration_context"]
        return turn_result

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.run_planner_turn",
            new=AsyncMock(side_effect=_capture_turn),
        ),
    ):
        await _collect_events(planner, **_send_kwargs())

    ctx = captured["orchestration_context"]
    assert ctx.required_slot_names == frozenset(
        {"document_material_scope", "runtime_metadata_fields"}
    )


@pytest.mark.asyncio
async def test_send_message_passes_server_precomputed_commit_to_turn_runner() -> None:
    from intric.flows.ai_builder.planning_state import ResolvedSlot

    def _slot(name: str, value: str) -> ResolvedSlot:
        return ResolvedSlot(
            name=name,
            value=value,
            source="structured_answer",
            evidence=[],
            confidence="high",
        )

    planner = _make_planner()
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "documents"),
        "terminal_output": _slot("terminal_output", "text"),
        "document_material_scope": _slot(
            "document_material_scope", "flexible_document_case"
        ),
    }
    action_policy = build_planner_action_policy(
        session_state=state,
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=frozenset(),
    )
    prepared = PlannerPreparedRequest(
        requirements_state=SimpleNamespace(latest_summary=None, confirmed=False),
        ui_language="en",
        discovery_block_message=None,
        llm_messages=[],
        should_emit_forced_followup=False,
        base_planning_state_version=0,
        rebuilt_planning_state=state,
        action_policy=action_policy,
        server_output=build_server_planner_output(
            action_policy=action_policy,
            session_state=state,
            base_planning_state_version=0,
            ui_language="en",
        ),
    )
    action = CommitArchitectureAction(
        kind="commit_architecture",
        payload=CommitArchitecturePayload(note="server"),
    )
    output = _planner_output(action)
    turn_result = _dispatched_result(
        action_kind="commit_architecture", planner_output=output
    )

    captured: dict[str, Any] = {}

    async def _capture_turn(**kwargs: Any) -> PlannerTurnResult:
        captured["precomputed_output"] = kwargs["precomputed_output"]
        return turn_result

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.run_planner_turn",
            new=AsyncMock(side_effect=_capture_turn),
        ),
    ):
        await _collect_events(planner, **_send_kwargs())

    precomputed = captured["precomputed_output"]
    assert precomputed is not None
    assert precomputed.planner_action.kind == "commit_architecture"
    assert precomputed.planning_state_delta.architecture_commit is not None


@pytest.mark.asyncio
async def test_send_message_auto_advances_server_commit_to_requirements_summary() -> (
    None
):
    from datetime import datetime, timezone

    from intric.flows.ai_builder.planning_state import (
        ArchitectureCommit,
        ResolvedSlot,
        StepTriple,
    )

    def _slot(name: str, value: str) -> ResolvedSlot:
        return ResolvedSlot(
            name=name,
            value=value,
            source="structured_answer",
            evidence=[],
            confidence="high",
        )

    planner = _make_planner()
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "documents"),
        "terminal_output": _slot("terminal_output", "docx"),
        "document_material_scope": _slot(
            "document_material_scope", "flexible_document_case"
        ),
        "runtime_metadata_fields": _slot(
            "runtime_metadata_fields", "no_extra_metadata"
        ),
    }
    action_policy = build_planner_action_policy(
        session_state=state,
        unresolved_architectural_choices=frozenset(),
        selected_discovery_question_ids=frozenset(),
    )
    server_output = build_server_planner_output(
        action_policy=action_policy,
        session_state=state,
        base_planning_state_version=0,
        ui_language="en",
    )
    assert server_output is not None
    assert server_output.planner_action.kind == "commit_architecture"
    prepared = PlannerPreparedRequest(
        requirements_state=SimpleNamespace(latest_summary=None, confirmed=False),
        ui_language="en",
        discovery_block_message=None,
        llm_messages=[],
        should_emit_forced_followup=False,
        base_planning_state_version=0,
        rebuilt_planning_state=state,
        action_policy=action_policy,
        server_output=server_output,
        slot_classification_metadata=_slot_classification_metadata(),
    )

    committed_state = PlanningState.empty()
    committed_state.resolved_slots = dict(state.resolved_slots)
    committed_state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=[],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )
    planner.repo.load_planning_state.side_effect = [None, committed_state]
    planner.repo.commit_turn.side_effect = [1, 2]

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
    ):
        events = await _collect_events(planner, **_send_kwargs())

    assert [event["event"] for event in events] == [
        "status",
        "requirements_summary",
        "done",
    ]
    assert json.loads(events[0]["data"])["status"] == "architecture_committed"
    summary_payload = json.loads(events[1]["data"])
    assert "requirements_version" in summary_payload
    assert summary_payload["input_description"] == "Primary runtime input: Documents."
    assert summary_payload["output_description"] == "Primary final output: docx."
    assert planner.repo.commit_turn.await_count == 2
    first_commit_messages = planner.repo.commit_turn.await_args_list[0].kwargs[
        "new_messages"
    ]
    assert first_commit_messages[0].metadata is not None
    assert "slot_classification" in first_commit_messages[0].metadata
    planner.litellm_client.acompletion.assert_not_called()


@pytest.mark.asyncio
async def test_send_message_routes_proposal_mode_to_task_specific_proposer() -> None:
    planner = _make_planner()
    prepared = PlannerPreparedRequest(
        requirements_state=SimpleNamespace(latest_summary=None, confirmed=True),
        ui_language="en",
        discovery_block_message=None,
        llm_messages=[{"role": "system", "content": "proposal task"}],
        should_emit_forced_followup=False,
        base_planning_state_version=0,
        rebuilt_planning_state=PlanningState.empty(),
        action_policy=PlannerActionPolicy(allowed_action_kinds=("propose_plan",)),
        proposal_mode=True,
        slot_classification_metadata=_slot_classification_metadata(),
    )
    captured: dict[str, Any] = {}

    async def _proposal(**kwargs: Any) -> Any:
        captured.update(kwargs)
        yield {"event": "plan", "data": "{}"}

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        patch.object(planner.proposal_processor, "propose_plan", new=_proposal),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.run_planner_turn",
            new=AsyncMock(side_effect=AssertionError("planner union should not run")),
        ),
    ):
        events = await _collect_events(planner, **_send_kwargs())

    assert [event["event"] for event in events] == ["plan", "done"]
    assert captured["llm_messages"] == [{"role": "system", "content": "proposal task"}]
    proposal_conversation = captured["conversation"]
    assert proposal_conversation[-1].metadata is not None
    assert "slot_classification" in proposal_conversation[-1].metadata
    assert captured["available_model_refs"] == set()
    assert captured["available_kb_refs"] == set()


@pytest.mark.asyncio
async def test_send_message_derives_asked_question_ids_and_new_evidence() -> None:
    """Duplicate-question guard must be live in production.

    `OrchestrationContext.asked_question_ids` and `has_new_evidence`
    drive the orchestrator's `duplicate_question` rejection — without
    them the guard is dead code and the LLM can infinite-loop the same
    question. `send_message` must derive both inputs from the
    persisted conversation before instantiating the context:

    - `asked_question_ids` = union of `question_id` metadata on prior
      assistant messages (persisted by `_build_new_messages` whenever
      an `ask_question` action lands).
    - `has_new_evidence` = True if the latest user message (the one
      being processed this turn) carries answer evidence.
    - `question_ids_with_new_evidence` = question IDs that have a user
      evidence turn after their latest ask.
    """
    from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage

    planner = _make_planner()
    session_id = uuid4()
    conversation = [
        ConversationMessage(
            role="user",
            content="Build a summarizer",
            metadata=None,
        ),
        ConversationMessage(
            role="assistant",
            content="Vad ska flödet ta emot?",
            metadata={"question_id": "primary_runtime_input"},
        ),
    ]
    planner.repo.get_session.return_value = BuilderSession(
        id=session_id,
        tenant_id=planner.user.tenant_id,
        space_id=uuid4(),
        actor_user_id=uuid4(),
        target_kind=TargetKind.CREATE,
        status=SessionStatus.CHATTING,
        conversation=conversation,
        planning_state_version=0,
    )
    prepared = _make_prepared_request()
    action = AskQuestionAction(
        kind="ask_question",
        payload=AskQuestionPayload(
            question_id="terminal_output",
            slot_name="terminal_output",
            prompt="Vad ska flödet leverera?",
        ),
    )
    turn_result = _dispatched_result(
        action_kind="ask_question",
        planner_output=_planner_output(action),
    )

    captured: dict[str, Any] = {}

    async def _capture_turn(**kwargs: Any) -> PlannerTurnResult:
        captured["orchestration_context"] = kwargs["orchestration_context"]
        return turn_result

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata={
                        "question_answer": {"question_id": "primary_runtime_input"}
                    },
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.run_planner_turn",
            new=AsyncMock(side_effect=_capture_turn),
        ),
    ):
        await _collect_events(planner, **_send_kwargs())

    ctx = captured["orchestration_context"]
    assert ctx.asked_question_ids == frozenset({"primary_runtime_input"})
    assert ctx.has_new_evidence is True
    assert ctx.question_ids_with_new_evidence == frozenset({"primary_runtime_input"})


@pytest.mark.asyncio
async def test_send_message_counts_plain_reply_after_v2_question_as_new_evidence() -> (
    None
):
    """A prose reply to v2 ask_question is still question-specific evidence.

    The v2 planner action persists assistant questions as
    `metadata.question_id`, not as legacy `ask_structured_question`
    tool calls. The duplicate-question guard must therefore use
    conversation order, not only structured answer metadata, or a
    perfectly normal free-form answer gets rejected as "no new
    evidence arrived since".
    """
    from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage

    planner = _make_planner()
    conversation = [
        ConversationMessage(role="user", content="Build it", metadata=None),
        ConversationMessage(
            role="assistant",
            content="Vad ska flödet ta emot?",
            metadata={"question_id": "primary_runtime_input"},
        ),
        ConversationMessage(role="user", content="kanske text", metadata=None),
    ]
    planner.repo.get_session.return_value = BuilderSession(
        id=uuid4(),
        tenant_id=planner.user.tenant_id,
        space_id=uuid4(),
        actor_user_id=uuid4(),
        target_kind=TargetKind.CREATE,
        status=SessionStatus.CHATTING,
        conversation=conversation,
        planning_state_version=0,
    )
    prepared = _make_prepared_request()
    turn_result = _dispatched_result(
        action_kind="ask_question",
        planner_output=_planner_output(
            AskQuestionAction(
                kind="ask_question",
                payload=AskQuestionPayload(
                    question_id="terminal_output",
                    slot_name="terminal_output",
                    prompt="Vad ska flödet leverera?",
                ),
            )
        ),
    )

    captured: dict[str, Any] = {}

    async def _capture_turn(**kwargs: Any) -> PlannerTurnResult:
        captured["orchestration_context"] = kwargs["orchestration_context"]
        return turn_result

    with (
        patch.object(
            planner,
            "_resolve_message_metadata",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    metadata=None,
                    is_requirements_confirmation=False,
                    used_auxiliary_llm=False,
                )
            ),
        ),
        patch.object(
            planner,
            "_prepare_planner_request",
            new=AsyncMock(return_value=prepared),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner.run_planner_turn",
            new=AsyncMock(side_effect=_capture_turn),
        ),
    ):
        await _collect_events(planner, **_send_kwargs())

    ctx = captured["orchestration_context"]
    assert ctx.asked_question_ids == frozenset({"primary_runtime_input"})
    assert ctx.has_new_evidence is True
    assert ctx.question_ids_with_new_evidence == frozenset({"primary_runtime_input"})
