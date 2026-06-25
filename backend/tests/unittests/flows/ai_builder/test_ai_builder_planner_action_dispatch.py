from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from intric.completion_models.infrastructure.tenant_model_capabilities import (
    StructuredOutputCapabilityDecision,
    StructuredOutputDecisionSource,
    StructuredOutputMode,
)
from intric.flows.ai_builder.ai_builder_dispatcher import PlannerDispatchResult
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_orchestrator import (
    AskQuestionAction,
    AskQuestionPayload,
    CommitArchitectureAction,
    CommitArchitecturePayload,
    ConfirmRequirementsAction,
    ConfirmRequirementsPayload,
    PlannerOutput,
    PlanningStateDelta,
)
from intric.flows.ai_builder.ai_builder_planner_action_dispatch import (
    BackendSelectedQuestionDispatchRequest,
    DispatchedActionEventRequest,
    build_dispatched_action_events,
    dispatch_backend_selected_question_if_any,
)
from intric.flows.ai_builder.ai_builder_planner_turn import (
    PlannerTurnResult,
    TurnTelemetry,
)
from intric.flows.ai_builder.ai_builder_response_format import (
    build_planner_request_response_format,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.planning_state import PlanningState


def _planner_output(
    action: AskQuestionAction | CommitArchitectureAction | ConfirmRequirementsAction,
) -> PlannerOutput:
    return PlannerOutput(
        planning_state_delta=PlanningStateDelta(base_planning_state_version=0),
        planner_action=action,
    )


def _turn_telemetry() -> TurnTelemetry:
    return TurnTelemetry(
        request_id="request-1",
        model="openai/gpt-4o-mini",
        outcome_kind="dispatched",
        wall_clock_ms=5,
        llm_calls_made=1,
        repair_attempts=0,
        architecture_commit_populated=False,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        finish_reason=None,
    )


def _turn(*, base_version: int = 0) -> SessionSendTurn:
    return SessionSendTurn(
        session_id=uuid4(),
        tenant_id=uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=base_version,
    )


def _dispatched_result(
    *,
    action_kind: str,
    output: PlannerOutput,
    new_version: int = 1,
) -> PlannerTurnResult:
    return PlannerTurnResult(
        kind="dispatched",
        accepted_output=output,
        dispatch_result=PlannerDispatchResult(
            action_kind=action_kind,
            new_planning_state_version=new_version,
        ),
        turn_telemetry=_turn_telemetry(),
        llm_calls_made=1,
    )


def _structured_decision() -> StructuredOutputCapabilityDecision:
    return StructuredOutputCapabilityDecision(
        mode=StructuredOutputMode.STRICT_JSON_SCHEMA,
        source=StructuredOutputDecisionSource.LITELLM_RESPONSE_SCHEMA,
        supports_response_schema=True,
        supports_response_format=True,
    )


@pytest.mark.asyncio
async def test_backend_selected_question_dispatch_uses_typed_discovery_followup() -> (
    None
):
    repo = AsyncMock()
    repo.commit_turn.return_value = 1
    conversation = [
        ConversationMessage(
            role="user",
            content=(
                "Create a flow that transcribes meeting audio, extracts ten "
                "topic sections, and produces a DOCX meeting report."
            ),
        )
    ]
    output = _planner_output(
        AskQuestionAction(
            kind="ask_question",
            payload=AskQuestionPayload(
                question_id="structured_analysis_need",
                slot_name="structured_analysis_need",
                prompt="Should the flow use structured analysis?",
            ),
        )
    )

    events = await dispatch_backend_selected_question_if_any(
        BackendSelectedQuestionDispatchRequest(
            repo=repo,
            turn=_turn(),
            server_output=output,
            conversation=conversation,
            new_messages_start=len(conversation),
            flow=None,
        )
    )

    assert events is not None
    assert [event["event"] for event in events] == ["text"]
    repo.commit_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_backend_selected_question_prefers_contextual_discovery_question() -> (
    None
):
    repo = AsyncMock()
    conversation = [
        ConversationMessage(
            role="user",
            content="Jag vill bygga ett flöde som tar emot JSON och returnerar JSON.",
        )
    ]
    output = _planner_output(
        AskQuestionAction(
            kind="ask_question",
            payload=AskQuestionPayload(
                question_id="structured_io_contract",
                slot_name="structured_io_contract",
                prompt="Vad ska flödet göra mellan input-JSON och output-JSON?",
            ),
        )
    )

    with patch(
        "intric.flows.ai_builder.ai_builder_planner_action_dispatch."
        "persist_backend_question",
        new=AsyncMock(return_value=SimpleNamespace(events=[])),
    ) as persist_question:
        events = await dispatch_backend_selected_question_if_any(
            BackendSelectedQuestionDispatchRequest(
                repo=repo,
                turn=_turn(),
                server_output=output,
                conversation=conversation,
                new_messages_start=len(conversation),
                flow=None,
            )
        )

    assert events == []
    question = persist_question.await_args.kwargs["question"].question_data
    assert question.question == "Vad ska flödet göra mellan input-JSON och output-JSON?"
    assert [option.value for option in question.options] == [
        "map_to_new_schema",
        "validate_against_schema_or_rules",
        "extract_or_compute_fields",
        "normalize_or_enrich",
        "classify_or_tag",
        "custom_schema_or_rules",
    ]


@pytest.mark.asyncio
async def test_dispatched_commit_chains_confirm_with_same_response_format_selection() -> (
    None
):
    repo = AsyncMock()
    repo.load_planning_state.return_value = PlanningState.empty()
    response_format_selection = build_planner_request_response_format(
        _structured_decision()
    )
    committed_output = _planner_output(
        CommitArchitectureAction(
            kind="commit_architecture",
            payload=CommitArchitecturePayload(note="Committed."),
        )
    )
    confirm_output = _planner_output(
        ConfirmRequirementsAction(
            kind="confirm_requirements",
            payload=ConfirmRequirementsPayload(
                summary="Ready",
                key_decisions=[],
                input_description="Text input.",
                output_description="Text output.",
                assumptions=[],
                manual_setup_notes=[],
            ),
        )
    )
    chained_result = _dispatched_result(
        action_kind="confirm_requirements",
        output=confirm_output,
        new_version=2,
    )

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_planner_action_dispatch."
            "planner_output_for_turn_decision",
            return_value=confirm_output,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_planner_action_dispatch.run_planner_turn",
            new=AsyncMock(return_value=chained_result),
        ) as run_turn,
    ):
        events = await build_dispatched_action_events(
            DispatchedActionEventRequest(
                repo=repo,
                litellm_client=AsyncMock(),
                turn=_turn(base_version=1),
                turn_result=_dispatched_result(
                    action_kind="commit_architecture",
                    output=committed_output,
                    new_version=1,
                ),
                conversation=[],
                litellm_model="openai/gpt-4o-mini",
                litellm_kwargs={"api_key": "sk-test"},
                response_format_selection=response_format_selection,
                flow=None,
                requirements_confirmed=False,
                ui_language="en",
                planner_temperature=0.1,
            )
        )

    assert [event["event"] for event in events] == ["status", "requirements_summary"]
    call_kwargs = run_turn.await_args.kwargs
    assert call_kwargs["litellm_kwargs"]["api_key"] == "sk-test"
    assert call_kwargs["litellm_kwargs"]["response_format"] == {"type": "json_object"}
    assert call_kwargs["litellm_kwargs"]["drop_params"] is True
    assert call_kwargs["precomputed_output"] is confirm_output
