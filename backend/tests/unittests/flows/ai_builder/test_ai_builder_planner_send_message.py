"""Transport contract tests for `AIBuilderPlanner.send_message`.

`send_message` bridges the builder's public SSE surface and the
orchestrator's structured-JSON planner pipeline. This suite pins the
five `PlannerTurnResult` outcomes the planner can surface — dispatched
(ask_question / commit_architecture / confirm_requirements),
parse_failed with finish_reason=="length", rejected, and
propose_plan_pending_adapter — to specific SSE event sequences.

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
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_domain_models import BuilderSession
from intric.flows.ai_builder.ai_builder_event_models import KeyDecisionPayload
from intric.flows.ai_builder.ai_builder_models import SessionStatus, TargetKind
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
from intric.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy


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
    *, should_emit_forced_followup: bool = False
) -> PlannerPreparedRequest:
    return PlannerPreparedRequest(
        requirements_state=SimpleNamespace(latest_summary=None, confirmed=False),
        ui_language="en",
        discovery_block_message=None,
        llm_messages=[{"role": "system", "content": "system"}],
        should_emit_forced_followup=should_emit_forced_followup,
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


def _patched_send(
    turn_result: PlannerTurnResult | Callable[..., Any],
) -> Any:
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
    return patch.multiple(
        "intric.flows.ai_builder.ai_builder_planner",
        run_planner_turn=run_mock,
    )


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


@pytest.mark.asyncio
async def test_send_message_propose_plan_pending_adapter_emits_transient_error() -> (
    None
):
    """`propose_plan_pending_adapter` → `propose_plan_adapter_unavailable`.

    The materialization bridge is the adapter that translates the
    orchestrator's `DraftPlanEnvelope` into the persistence format
    the proposal processor expects. Until that adapter is wired in
    `send_message`, the planner's `propose_plan` turns are surfaced as
    a transient error so the user can retry; nothing should be written
    to `builder_plans`.
    """
    planner = _make_planner()
    prepared = _make_prepared_request()
    pending_turn = PlannerTurnResult(
        kind="propose_plan_pending_adapter",
        accepted_output=None,
        turn_telemetry=_turn_telemetry("propose_plan_pending_adapter"),
        llm_calls_made=1,
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
        _patched_send(pending_turn),
    ):
        events = await _collect_events(planner, **_send_kwargs())

    assert [event["event"] for event in events] == ["error", "done"]
    payload = json.loads(events[0]["data"])
    assert payload["code"] == "propose_plan_adapter_unavailable"
    assert payload["phase"] == "planner"
    planner.repo.commit_turn.assert_not_called()


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
    # Those same slots do not appear on the broad required-slot surface.
    assert "primary_runtime_input" not in ctx.required_slot_names
    assert "terminal_output" not in ctx.required_slot_names


@pytest.mark.asyncio
async def test_send_message_orchestration_context_blocks_commit_until_core_slots_resolve() -> (
    None
):
    """Mirror of the happy-path context test: when only one core slot is
    resolved, the commit gate still blocks.

    Asserts the pattern-agnostic `unresolved_architectural_choices`
    reflects exactly the un-resolved core slot, and the broad
    `required_slot_names` surface covers the discovery surface minus
    what's been resolved.
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
    assert "terminal_output" in ctx.required_slot_names
    assert "primary_runtime_input" not in ctx.required_slot_names


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
      being processed this turn) carries `question_answer` metadata.
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


@pytest.mark.asyncio
async def test_send_message_has_new_evidence_false_when_last_user_message_plain() -> (
    None
):
    """Free-form user chat does not count as new evidence.

    Only a structured `question_answer` payload proves a slot moved.
    A plain chat message since the last ask leaves the guard blocking
    a repeat — the LLM must surface new signal before asking again.
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
    assert ctx.has_new_evidence is False
