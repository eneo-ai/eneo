"""A saved flow the Builder can inspect but not edit is refused before any proposal.

The refusal sits at the boundary every proposal passes, so the first build and
a continuation after a server decision end the same way: a typed answer stored
on the turn, and no proposal call.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.completion_models.domain.model_capacity import ModelCapacity
from eneo.flows.ai_builder.ai_builder_checkpoint_contract import (
    AmbiguousSavedStructuredReviewsError,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    SlotClassificationMetadata,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderStatus,
    AIBuilderStreamEvent,
)
from eneo.flows.ai_builder.ai_builder_events import build_status_event
from eneo.flows.ai_builder.ai_builder_non_plan_outcome import (
    saved_steps_not_editable_answer,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderSavedFlowStepEditContext,
    ResolvedAIBuilderEditContext,
)
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    ProposalPrepared,
    SavedStepsNotEditablePrepared,
    build_proposal_prepared,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    MAX_DIAGNOSTIC_NAMES,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import RequirementsState
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_server_decision_dispatch import (
    ServerDecisionDispatchRequest,
    ServerDecisionDispatchResult,
    ServerDecisionProposalContinuation,
)
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    SLOT_CLASSIFICATION_SCHEMA_VERSION,
)
from eneo.flows.ai_builder.ai_builder_turn_controller import ReviseArchitecture
from eneo.flows.ai_builder.planning_state import (
    CheckpointIntent,
    PlanningState,
    PlanningStatePayloadTooLargeError,
)
from eneo.flows.application.flow_authoring_snapshot import UnsupportedSavedStepsError
from eneo.flows.domain.flow import Flow, FlowStep
from tests.unittests.flows.ai_builder.test_ai_builder_planner import (
    _architecture_commit,
    _budget_policy,
    _configure_minimal_send_message,
    _make_planner,
    _requirements_state_confirmed,
    _route,
    _server_output_prepared,
    _visible,
)

_CREDENTIAL = "sk-live-credential-looking-value"

_SHAPES: dict[str, dict[str, object]] = {
    "http_get_input": {
        "input_source": "http_get",
        "input_config": {
            "url": "https://example.org/a",
            "auth": {"token": _CREDENTIAL},
        },
    },
    "image_input": {"input_type": "image"},
    "http_post_output": {
        "output_mode": "http_post",
        "output_config": {
            "url": "https://example.org/b",
            "auth": {"token": _CREDENTIAL},
        },
    },
}


def _step(order: int, **overrides: object) -> FlowStep:
    fields: dict[str, object] = {
        "id": uuid4(),
        "assistant_id": uuid4(),
        "step_order": order,
        "user_description": f"Steg {order}",
        "input_source": "flow_input" if order == 1 else "previous_step",
        "input_type": "document" if order == 1 else "text",
        "output_mode": "pass_through",
        "output_type": "text",
    }
    fields.update(overrides)
    return FlowStep.model_validate(fields)


def _flow(*steps: FlowStep) -> Flow:
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Saved",
        published_version=1,
        steps=list(steps),
    )


def _scoped_to(step: FlowStep) -> ResolvedAIBuilderEditContext:
    return ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=step.id),
        scope="step",
        target_existing_step_ref=f"existing_step_{step.step_order}",
    )


def _build(
    flow: Flow,
    context: ResolvedAIBuilderEditContext | None,
    planning_state: PlanningState | None = None,
) -> ProposalPrepared:
    return build_proposal_prepared(
        requirements_state=RequirementsState(),
        ui_language="en",
        slot_classification_metadata=None,
        conversation=[ConversationMessage(role="user", content="Improve the flow.")],
        planning_state=planning_state or PlanningState.empty(),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=True,
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=None, available_kbs=None
        ),
        flow=flow,
        assistant_snapshots=None,
        plan_edit_context=context,
        prior_plan_for_revision=None,
        litellm_model="gpt-4o-mini",
        capacity=ModelCapacity(100_000, 1024),
        budget_policy=_budget_policy(),
        attachment_file_count=0,
        current_turn_start=0,
    )


@pytest.mark.parametrize("scoped", [False, True], ids=["whole_flow", "scoped_step"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_the_proposal_boundary_refuses_an_unsupported_saved_flow(
    shape: str, scoped: bool
) -> None:
    unsupported = _step(2, **_SHAPES[shape])
    flow = _flow(_step(1), unsupported, _step(3))

    with pytest.raises(UnsupportedSavedStepsError) as caught:
        _build(flow, _scoped_to(flow.steps[0]) if scoped else None)

    assert [step.step_order for step in caught.value.steps] == [2]


def test_the_proposal_boundary_keeps_speaker_mapping_and_authorable_flows() -> None:
    flow = _flow(_step(1), _step(2, output_type="json", output_mode="speaker_mapping"))

    assert isinstance(_build(flow, None), ProposalPrepared)
    assert isinstance(_build(flow, _scoped_to(flow.steps[1])), ProposalPrepared)


def test_the_answer_names_the_steps_in_both_languages_and_stays_bounded() -> None:
    names = [f"Steg {n}" for n in range(MAX_DIAGNOSTIC_NAMES + 3)]

    swedish = saved_steps_not_editable_answer(names, ui_language="sv")
    english = saved_steps_not_editable_answer(names[:1], ui_language="en")

    assert swedish.outcome is not None
    assert swedish.outcome.kind == "edit_blocked_by_unsupported_step"
    assert swedish.outcome.required_action == "edit_in_step_editor"
    assert swedish.outcome.affected == tuple(names[:MAX_DIAGNOSTIC_NAMES])
    assert swedish.outcome.affected_remaining == 3
    assert "stegredigeraren" in swedish.answer
    assert "`Steg 0`" in swedish.answer and "3 till" in swedish.answer
    assert "step editor" in english.answer and "`Steg 0`" in english.answer


def test_a_request_for_another_step_also_hears_that_no_edit_can_be_proposed() -> None:
    plain = saved_steps_not_editable_answer(["Steg 2"], ui_language="en")
    other = saved_steps_not_editable_answer(
        ["Steg 2"], ui_language="en", edit_asked_for_another_step=True
    )
    swedish = saved_steps_not_editable_answer(
        ["Steg 2", "Steg 3"], ui_language="sv", edit_asked_for_another_step=True
    )

    assert "propose edits" not in plain.answer
    assert other.answer.startswith(plain.answer)
    assert "I can't propose edits to this flow while those steps exist" in other.answer
    assert "föreslå ändringar i det här flödet" in swedish.answer
    assert other.outcome == plain.outcome


def _unsupported_flow() -> Flow:
    return _flow(
        _step(1, **_SHAPES["http_get_input"], user_description="Hämta kurser"),
        _step(2),
    )


async def _send(planner: Any, flow: Flow) -> list[AIBuilderStreamEvent]:
    return [
        event
        async for event in _visible(
            planner.send_message(
                session_id=uuid4(),
                client_turn_id=uuid4(),
                request_fingerprint="a" * 64,
                request_snapshot={"message": "Improve"},
                message="Improve",
                completion_model_route=_route(),
                available_models=None,
                available_kbs=None,
                flow=flow,
                assistant_snapshots=None,
                attachment_files=None,
                capacity=ModelCapacity(100_000, 4_096),
                budget_policy=_budget_policy(),
            )
        )
    ]


def _assert_answered_not_editable(
    planner: Any, events: list[AIBuilderStreamEvent]
) -> tuple[Any, Any]:
    assert [event.event for event in events][-1] == "done"
    text = next(event for event in events if event.event == "text")
    assert "`Hämta kurser`" in text.data.text
    assert not [event for event in events if event.event == "error"]
    planner.repo.complete_session_turn.assert_awaited_once()
    assert planner.repo.complete_session_turn.await_args.kwargs["error"] is None
    planner.repo.commit_turn.assert_awaited_once()
    commit = planner.repo.commit_turn.await_args.kwargs
    [assistant] = [m for m in commit["new_messages"] if m.role == "assistant"]
    assert assistant.metadata["non_plan_outcome"] == {
        "kind": "edit_blocked_by_unsupported_step",
        "required_action": "edit_in_step_editor",
        "affected": ["Hämta kurser"],
        "affected_remaining": 0,
    }
    stored = json.dumps(assistant.metadata, default=str) + text.data.text
    assert _CREDENTIAL not in stored
    planner.repo.mark_session_turn_processing.assert_not_awaited()
    return commit, text


async def _send_continuation_into_unsupported_flow(
    planner: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[AIBuilderStreamEvent], PlanningState]:
    continuation_state = PlanningState.empty()
    _configure_minimal_send_message(
        planner,
        monkeypatch,
        _server_output_prepared_revising(continuation_state),
    )
    proposal_calls = AsyncMock()

    async def fake_dispatch(
        _: ServerDecisionDispatchRequest,
    ) -> ServerDecisionDispatchResult:
        return ServerDecisionDispatchResult(
            action_kind="revise_architecture",
            events=(build_status_event(AIBuilderStatus.ARCHITECTURE_REVISED),),
            new_planning_state_version=9,
            proposal_continuation=ServerDecisionProposalContinuation(
                planning_state=continuation_state,
                new_messages_start=1,
            ),
        )

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.dispatch_server_decision",
        fake_dispatch,
    )
    monkeypatch.setattr(
        planner._proposal_submission, "run_active_submission_attempt", proposal_calls
    )

    events = await _send(planner, _unsupported_flow())

    proposal_calls.assert_not_called()
    planner.litellm_client.acompletion.assert_not_awaited()
    return events, continuation_state


@pytest.mark.asyncio
async def test_a_continuation_into_an_unsupported_saved_flow_answers_on_its_own_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    events, continuation_state = await _send_continuation_into_unsupported_flow(
        planner, monkeypatch
    )

    assert [event.event for event in events] == ["status", "text", "done"]
    commit, _ = _assert_answered_not_editable(planner, events)
    assert commit["turn"].base_planning_state_version == 9
    assert commit["planning_state"] is continuation_state
    assert (
        planner.repo.complete_session_turn.await_args.kwargs[
            "turn"
        ].base_planning_state_version
        == 9
    )


async def _send_first_build_on_unsupported_flow(
    planner: Any, monkeypatch: pytest.MonkeyPatch
) -> list[AIBuilderStreamEvent]:
    _configure_minimal_send_message(planner, monkeypatch, _server_output_prepared())
    flow = _unsupported_flow()

    with pytest.raises(UnsupportedSavedStepsError) as caught:
        _build(flow, None)
    reading = SlotClassificationMetadata(
        schema_version=SLOT_CLASSIFICATION_SCHEMA_VERSION,
        outcome="resolved",
        prompt_hash="a" * 64,
        model="model",
        provider="provider",
    )

    async def prepare(_: object) -> object:
        return SavedStepsNotEditablePrepared(
            requirements_state=RequirementsState(),
            ui_language="sv",
            slot_classification_metadata=reading,
            error=caught.value,
            planning_state=PlanningState.empty(),
        )

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.prepare_planner_request", prepare
    )

    return await _send(planner, flow)


@pytest.mark.asyncio
async def test_a_first_build_on_an_unsupported_saved_flow_answers_on_the_claimed_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    events = await _send_first_build_on_unsupported_flow(planner, monkeypatch)

    assert [event.event for event in events] == ["text", "done"]
    commit, _ = _assert_answered_not_editable(planner, events)
    assert commit["turn"].base_planning_state_version == 1
    # The reading the turn paid for is stored like any answered turn's.
    planner.repo.append_session_messages.assert_awaited_once()
    [stored_user_message] = planner.repo.append_session_messages.await_args.kwargs[
        "conversation"
    ]
    assert stored_user_message.role == "user"
    assert stored_user_message.metadata["slot_classification"]["outcome"] == "resolved"


def _assert_completed_with_the_size_error(
    planner: Any, events: list[AIBuilderStreamEvent], *, version: int
) -> None:
    """Saving the answer hit the planning-state cap: the turn still completes,
    once, through the typed size error, on the turn the answer was for."""

    [error] = [event for event in events if event.event == "error"]
    assert error.data.code == "planning_state_payload_too_large"
    assert [event.event for event in events][-2:] == ["error", "done"]
    assert not [event for event in events if event.event == "text"]
    planner.repo.complete_session_turn.assert_awaited_once()
    completion = planner.repo.complete_session_turn.await_args.kwargs
    assert completion["error"] == error.data
    assert completion["turn"].base_planning_state_version == version


@pytest.mark.asyncio
async def test_a_first_build_refusal_that_cannot_be_saved_completes_with_the_size_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    planner.repo.commit_turn.side_effect = PlanningStatePayloadTooLargeError(
        byte_size=131_073, cap_bytes=131_072
    )

    events = await _send_first_build_on_unsupported_flow(planner, monkeypatch)

    _assert_completed_with_the_size_error(planner, events, version=1)


@pytest.mark.asyncio
async def test_a_continuation_refusal_that_cannot_be_saved_completes_with_the_size_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    planner.repo.commit_turn.side_effect = PlanningStatePayloadTooLargeError(
        byte_size=131_073, cap_bytes=131_072
    )

    events, _ = await _send_continuation_into_unsupported_flow(planner, monkeypatch)

    assert [event.event for event in events][0] == "status"
    _assert_completed_with_the_size_error(planner, events, version=9)


def _server_output_prepared_revising(state: PlanningState) -> Any:
    return replace(
        _server_output_prepared(),
        requirements_state=_requirements_state_confirmed(),
        server_decision=ReviseArchitecture(architecture_commit=_architecture_commit()),
        planning_state=state,
    )


def _two_saved_structured_reviews() -> Flow:
    return _flow(
        *(
            _step(
                order,
                output_type="json",
                user_description=name,
                review_policy={"mode": "edit"},
            )
            for order, name in ((1, "Compare offers"), (2, "Decide grant"))
        ),
        _step(3, user_description="Write letter"),
    )


def _structured_review_request() -> PlanningState:
    state = PlanningState.empty()
    state.checkpoint_intents = [
        CheckpointIntent(
            evidence_level="explicit",
            producer_kind="structured_result",
            operation="clear",
            mode=None,
            confidence="high",
            evidence=["quote:user_message:1:Stop pausing for the data."],
        )
    ]
    return state


def test_the_proposal_boundary_refuses_a_change_to_one_of_several_saved_reviews() -> (
    None
):
    flow = _two_saved_structured_reviews()

    with pytest.raises(AmbiguousSavedStructuredReviewsError) as caught:
        _build(flow, None, _structured_review_request())

    assert caught.value.names == ("Compare offers", "Decide grant")
    # Without a structured-result request the saved reviews are no obstacle.
    assert isinstance(_build(flow, None), ProposalPrepared)


@pytest.mark.asyncio
async def test_a_refused_review_change_answers_without_a_proposal_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _make_planner()
    _configure_minimal_send_message(planner, monkeypatch, _server_output_prepared())
    flow = _two_saved_structured_reviews()
    with pytest.raises(AmbiguousSavedStructuredReviewsError) as caught:
        _build(flow, None, _structured_review_request())

    async def prepare(_: object) -> object:
        return SavedStepsNotEditablePrepared(
            requirements_state=RequirementsState(),
            ui_language="en",
            slot_classification_metadata=None,
            error=caught.value,
            planning_state=_structured_review_request(),
        )

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_planner.prepare_planner_request", prepare
    )

    events = await _send(planner, flow)

    assert [event.event for event in events] == ["text", "done"]
    assert "`Compare offers`" in events[0].data.text
    planner.repo.mark_session_turn_processing.assert_not_awaited()
    commit = planner.repo.commit_turn.await_args.kwargs
    [assistant] = [m for m in commit["new_messages"] if m.role == "assistant"]
    assert assistant.metadata["non_plan_outcome"] == {
        "kind": "structured_review_target_ambiguous",
        "required_action": "edit_in_step_editor",
        "affected": ["Compare offers", "Decide grant"],
        "affected_remaining": 0,
    }
