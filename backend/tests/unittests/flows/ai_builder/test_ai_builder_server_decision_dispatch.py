from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_event_models import AIBuilderQuestionEvent
from intric.flows.ai_builder.ai_builder_server_decision_dispatch import (
    ServerDecisionDispatchRequest,
    dispatch_server_decision,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.ai_builder_turn_controller import (
    AskCanonicalQuestion,
    BuilderTurnDecision,
    CommitArchitecture,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    ArchitectureCommitDraft,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)


def _turn() -> SessionSendTurn:
    return SessionSendTurn(
        session_id=uuid4(),
        tenant_id=uuid4(),
        lease=SessionSendLease(
            request_id=uuid4(),
            lock_token=uuid4(),
        ),
        base_planning_state_version=4,
    )


def _request(
    *,
    repo: AsyncMock,
    decision: BuilderTurnDecision,
    conversation: list[ConversationMessage],
    new_messages_start: int = 0,
) -> ServerDecisionDispatchRequest:
    return ServerDecisionDispatchRequest(
        repo=repo,
        turn=_turn(),
        decision=decision,
        conversation=conversation,
        new_messages_start=new_messages_start,
        flow=None,
        discovery_analysis=None,
        requirements_confirmed=False,
        ui_language="en",
        request_id="req-test",
        litellm_model="server",
        used_auxiliary_llm=False,
    )


def _slot(name: str, value: str) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source="structured_answer",
        evidence=[],
        confidence="high",
    )


def _confirmed_state() -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "documents"),
        "terminal_output": _slot("terminal_output", "docx_document"),
        "document_material_scope": _slot(
            "document_material_scope",
            "flexible_document_case",
        ),
        "docx_output_mode": _slot("docx_output_mode", "generated_docx"),
        "runtime_metadata_fields": _slot(
            "runtime_metadata_fields",
            "no_extra_metadata",
        ),
    }
    state.architecture_commit = ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="document",
                output_type="text",
                output_mode="pass_through",
            ),
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=[],
        committed_at=datetime(2026, 4, 24, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )
    return state


@pytest.mark.asyncio
async def test_fallback_text_question_persists_user_and_assistant_turn() -> None:
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    decision = AskCanonicalQuestion(
        slot_name="structured_analysis_need",
        prompt="Should the flow use structured analysis?",
    )

    result = await dispatch_server_decision(
        _request(repo=repo, decision=decision, conversation=conversation)
    )

    assert [event.event for event in result.events] == ["text"]
    repo.commit_turn.assert_awaited_once()
    new_messages = repo.commit_turn.await_args.kwargs["new_messages"]
    assert [message.role for message in new_messages] == ["user", "assistant"]
    assert new_messages[-1].content == decision.prompt
    assert result.new_planning_state_version == 5


@pytest.mark.asyncio
async def test_server_question_uses_catalog_legacy_question_id_for_slot_rename() -> (
    None
):
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    decision = AskCanonicalQuestion(
        slot_name="primary_runtime_input",
        prompt="What should the runtime input be?",
    )

    result = await dispatch_server_decision(
        _request(repo=repo, decision=decision, conversation=conversation)
    )

    assert [event.event for event in result.events] == ["text", "question"]
    question_event = result.events[1]
    assert isinstance(question_event, AIBuilderQuestionEvent)
    assert question_event.data.question_id == "input_material_mode"

    repo.commit_turn.assert_awaited_once()
    new_messages = repo.commit_turn.await_args.kwargs["new_messages"]
    assistant_message = new_messages[-2]
    assert assistant_message.metadata is not None
    assert assistant_message.metadata["question_id"] == "input_material_mode"
    assert assistant_message.tool_calls is not None
    tool_call = assistant_message.tool_calls[0]
    arguments = tool_call["arguments"]
    assert isinstance(arguments, dict)
    assert arguments["question_id"] == "input_material_mode"
    assert result.new_planning_state_version == 5


@pytest.mark.asyncio
async def test_architecture_commit_chains_persisted_requirements_confirmation() -> None:
    repo = AsyncMock()
    repo.commit_turn.side_effect = [5, 6]
    repo.load_planning_state.return_value = _confirmed_state()
    conversation = [ConversationMessage(role="user", content="Build a document flow")]
    decision = CommitArchitecture(
        architecture_commit=ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="text",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["summarize_text"],
            required_capabilities=[],
        )
    )

    result = await dispatch_server_decision(
        _request(repo=repo, decision=decision, conversation=conversation)
    )

    assert [event.event for event in result.events] == [
        "status",
        "requirements_summary",
    ]
    assert repo.commit_turn.await_count == 2
    first_commit = repo.commit_turn.await_args_list[0].kwargs
    assert first_commit["architecture_commit"] is not None
    second_commit = repo.commit_turn.await_args_list[1].kwargs
    assert [message.role for message in second_commit["new_messages"]] == ["assistant"]
    assert result.new_planning_state_version == 6
