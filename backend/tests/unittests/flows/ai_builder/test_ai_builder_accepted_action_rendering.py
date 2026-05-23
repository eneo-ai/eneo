from __future__ import annotations

import json

from intric.flows.ai_builder.ai_builder_accepted_action_rendering import (
    RequirementsSummaryRenderContext,
    build_accepted_action_events,
    build_accepted_action_messages,
    build_requirements_summary_data,
)
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
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
)
from intric.flows.ai_builder.ai_builder_planner_turn import TurnTelemetry


def _context(
    conversation: list[ConversationMessage],
) -> RequirementsSummaryRenderContext:
    return RequirementsSummaryRenderContext(
        conversation=conversation,
        flow=None,
        ui_language="en",
    )


def _planner_output(
    action: AskQuestionAction | CommitArchitectureAction | ConfirmRequirementsAction,
) -> PlannerOutput:
    return PlannerOutput(
        planning_state_delta=PlanningStateDelta(base_planning_state_version=0),
        planner_action=action,
    )


def _telemetry() -> TurnTelemetry:
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


def test_ask_question_rendering_persists_question_id_and_text_event() -> None:
    conversation = [
        ConversationMessage(role="assistant", content="Previous message."),
        ConversationMessage(role="user", content="Build a document flow."),
    ]
    output = _planner_output(
        AskQuestionAction(
            kind="ask_question",
            payload=AskQuestionPayload(
                question_id="final_output_mode",
                slot_name="terminal_output",
                prompt="What should the flow produce?",
            ),
        )
    )

    messages = build_accepted_action_messages(
        output,
        _telemetry(),
        context=_context(conversation),
        new_messages_start=1,
        used_auxiliary_llm=False,
    )
    events = build_accepted_action_events(output, context=_context(conversation))

    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[1].content == "What should the flow produce?"
    assert messages[1].metadata is not None
    assert messages[1].metadata["question_id"] == "final_output_mode"
    assert [event["event"] for event in events] == ["text"]
    assert json.loads(events[0]["data"])["text"] == "What should the flow produce?"


def test_commit_rendering_does_not_persist_internal_note_as_assistant_text() -> None:
    conversation = [
        ConversationMessage(role="assistant", content="Previous message."),
        ConversationMessage(
            role="user",
            content="Yes, build the plan.",
            metadata={"slot_classification": {"slots": []}},
        ),
    ]
    output = _planner_output(
        CommitArchitectureAction(
            kind="commit_architecture",
            payload=CommitArchitecturePayload(
                note="Architecture committed from resolved planning state."
            ),
        )
    )

    messages = build_accepted_action_messages(
        output,
        _telemetry(),
        context=_context(conversation),
        new_messages_start=1,
        used_auxiliary_llm=False,
    )
    events = build_accepted_action_events(output, context=_context(conversation))

    assert messages == [conversation[1]]
    assert "Architecture committed" not in messages[0].content
    assert [event["event"] for event in events] == ["status"]
    assert json.loads(events[0]["data"])["status"] == "architecture_committed"


def test_confirm_requirements_rendering_reuses_one_versioned_summary_payload() -> None:
    conversation = [ConversationMessage(role="user", content="Make a meeting report.")]
    context = _context(conversation)
    output = _planner_output(
        ConfirmRequirementsAction(
            kind="confirm_requirements",
            payload=ConfirmRequirementsPayload(
                summary="Create a meeting report from an audio transcript.",
                key_decisions=[
                    KeyDecisionPayload(topic="Input", decision="Meeting audio"),
                    KeyDecisionPayload(topic="Output", decision="DOCX report"),
                ],
                input_description="One meeting audio file per run.",
                output_description="A DOCX meeting report.",
                assumptions=[],
                manual_setup_notes=[],
            ),
        )
    )

    messages = build_accepted_action_messages(
        output,
        _telemetry(),
        context=context,
        new_messages_start=0,
        used_auxiliary_llm=True,
    )
    events = build_accepted_action_events(output, context=context)
    summary_data = build_requirements_summary_data(
        output.planner_action.payload,
        context=context,
    )

    assert messages[-1].metadata is not None
    assert messages[-1].metadata["requirements_summary"] == summary_data
    assert (
        messages[-1].metadata["requirements_version"]
        == (summary_data["requirements_version"])
    )
    assert [event["event"] for event in events] == ["requirements_summary"]
    assert json.loads(events[0]["data"]) == summary_data
