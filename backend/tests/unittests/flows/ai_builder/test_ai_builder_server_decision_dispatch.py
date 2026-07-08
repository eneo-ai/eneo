from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    canonical_architecture_commit_payload,
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_error_contract import AIBuilderErrorCode
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderQuestionEvent
from eneo.flows.ai_builder.ai_builder_server_decision_dispatch import (
    ServerDecisionDispatchRequest,
    ServerDecisionTelemetry,
    dispatch_server_decision,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    AskCanonicalQuestion,
    BuilderTurnDecision,
    CommitArchitecture,
    ReviseArchitecture,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    ArchitectureCommitDraft,
    FileRoleEvidence,
    PlanningState,
    ResolvedSlot,
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
    planning_state: PlanningState | None = None,
    requirements_confirmed: bool = False,
    discovery_assumptions: tuple[str, ...] = (),
) -> ServerDecisionDispatchRequest:
    return ServerDecisionDispatchRequest(
        repo=repo,
        turn=_turn(),
        decision=decision,
        conversation=conversation,
        new_messages_start=new_messages_start,
        flow=None,
        requirements_confirmed=requirements_confirmed,
        ui_language="en",
        telemetry=ServerDecisionTelemetry(
            request_id="req-test",
            litellm_model="server",
            used_auxiliary_llm=False,
        ),
        planning_state=planning_state or PlanningState.empty(),
        discovery_assumptions=discovery_assumptions,
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
    state.architecture_commit = _finalized_commit_for_state(state)
    return state


def _draft_for_state(state: PlanningState) -> ArchitectureCommitDraft:
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    return draft


def _finalized_commit_for_state(state: PlanningState) -> ArchitectureCommit:
    return finalize_architecture_commit(
        _draft_for_state(state),
        now=lambda: datetime(2026, 4, 24, tzinfo=timezone.utc),
    )


def _revised_pdf_state() -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "text"),
        "terminal_output": _slot("terminal_output", "pdf_document"),
        "pdf_generation_mode": _slot("pdf_generation_mode", "generated_pdf"),
    }
    return state


@pytest.mark.asyncio
async def test_unrenderable_server_question_returns_typed_error_without_commit() -> (
    None
):
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

    assert [event.event for event in result.events] == ["error"]
    error = result.events[0].data
    assert error.code is AIBuilderErrorCode.PLANNER_UPSTREAM_ERROR
    assert error.phase == "question"
    assert error.details == {"question_id": "structured_analysis_need"}
    repo.commit_turn.assert_not_awaited()
    assert result.new_planning_state_version == 4


@pytest.mark.asyncio
async def test_server_question_preserves_prepared_file_roles_on_commit() -> None:
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    state = PlanningState.empty()
    state.file_roles = [
        FileRoleEvidence(
            file_id="00000000-0000-0000-0000-000000000701",
            filename="lagstod.pdf",
            file_type="document",
            mimetype="application/pdf",
            role="reference_material",
            source="heuristic",
            confidence="medium",
        )
    ]
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    decision = AskCanonicalQuestion(
        slot_name="primary_runtime_input",
        prompt="What should the runtime input be?",
    )

    await dispatch_server_decision(
        _request(
            repo=repo,
            decision=decision,
            conversation=conversation,
            planning_state=state,
        )
    )

    repo.commit_turn.assert_awaited_once()
    assert repo.commit_turn.await_args.kwargs["planning_state_overlay"] is state


@pytest.mark.asyncio
async def test_server_question_uses_canonical_slot_name_question_id() -> None:
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
    assert question_event.data.question_id == "primary_runtime_input"

    repo.commit_turn.assert_awaited_once()
    new_messages = repo.commit_turn.await_args.kwargs["new_messages"]
    assistant_message = new_messages[-2]
    assert assistant_message.metadata is not None
    assert assistant_message.metadata["question_id"] == "primary_runtime_input"
    assert assistant_message.tool_calls is not None
    tool_call = assistant_message.tool_calls[0]
    arguments = tool_call["arguments"]
    assert isinstance(arguments, dict)
    assert arguments["question_id"] == "primary_runtime_input"
    assert result.new_planning_state_version == 5


@pytest.mark.asyncio
async def test_architecture_commit_chains_persisted_requirements_confirmation() -> None:
    repo = AsyncMock()
    repo.commit_turn.side_effect = [5, 6]
    state = _confirmed_state()
    repo.load_planning_state.return_value = state
    conversation = [ConversationMessage(role="user", content="Build a document flow")]
    decision = CommitArchitecture(architecture_commit=_draft_for_state(state))

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=decision,
            conversation=conversation,
            discovery_assumptions=("The report should keep one section per source.",),
        )
    )

    assert [event.event for event in result.events] == [
        "status",
        "requirements_summary",
    ]
    assert "The report should keep one section per source." in (
        result.events[1].data.assumptions
    )
    assert repo.commit_turn.await_count == 2
    first_commit = repo.commit_turn.await_args_list[0].kwargs
    assert first_commit["architecture_commit"] is not None
    second_commit = repo.commit_turn.await_args_list[1].kwargs
    assert [message.role for message in second_commit["new_messages"]] == ["assistant"]
    assert result.new_planning_state_version == 6


@pytest.mark.asyncio
async def test_architecture_revision_persists_revised_commit_and_status() -> None:
    repo = AsyncMock()
    repo.commit_turn.side_effect = [5, 6]
    now = datetime(2026, 4, 24, tzinfo=timezone.utc)
    state = _revised_pdf_state()
    draft = _draft_for_state(state)
    state.architecture_commit = finalize_architecture_commit(draft, now=lambda: now)
    repo.load_planning_state.return_value = state
    conversation = [ConversationMessage(role="user", content="Make it PDF instead")]
    decision = ReviseArchitecture(architecture_commit=draft)

    result = await dispatch_server_decision(
        _request(repo=repo, decision=decision, conversation=conversation)
    )

    assert result.action_kind == "revise_architecture"
    assert [event.event for event in result.events] == [
        "status",
        "requirements_summary",
    ]
    assert result.events[0].data.status == "architecture_revised"
    first_commit = repo.commit_turn.await_args_list[0].kwargs
    persisted_commit = first_commit["architecture_commit"]
    assert isinstance(persisted_commit, ArchitectureCommit)
    assert canonical_architecture_commit_payload(persisted_commit) == (
        canonical_architecture_commit_payload(draft)
    )
    assert result.new_planning_state_version == 6


@pytest.mark.asyncio
async def test_confirmed_architecture_revision_returns_proposal_continuation() -> None:
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    now = datetime(2026, 4, 24, tzinfo=timezone.utc)
    state = _revised_pdf_state()
    draft = _draft_for_state(state)
    state.architecture_commit = finalize_architecture_commit(draft, now=lambda: now)
    repo.load_planning_state.return_value = state
    conversation = [ConversationMessage(role="user", content="Make it PDF instead")]
    decision = ReviseArchitecture(architecture_commit=draft)

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=decision,
            conversation=conversation,
            requirements_confirmed=True,
        )
    )

    assert result.action_kind == "revise_architecture"
    assert [event.event for event in result.events] == ["status"]
    assert result.events[0].data.status == "architecture_revised"
    assert result.new_planning_state_version == 5
    assert result.proposal_continuation is not None
    assert result.proposal_continuation.planning_state is state
