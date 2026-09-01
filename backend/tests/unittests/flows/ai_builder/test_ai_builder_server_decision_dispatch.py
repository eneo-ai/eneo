from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from litellm.exceptions import Timeout
from pydantic import ValidationError

if TYPE_CHECKING:
    from eneo.flows.domain.flow import Flow

from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    canonical_architecture_commit_payload,
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContext,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import BackendQuestion
from eneo.flows.ai_builder.ai_builder_discovery_runtime import (
    FocusedSlotClassificationRuntime,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import AIBuilderErrorCode
from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderQuestionEvent,
    AIBuilderStatus,
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import ProposalTurnTelemetry
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
    build_requirements_disclosure,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    DeclaredSchemaCandidate,
    build_declared_schema_candidate,
)
from eneo.flows.ai_builder.ai_builder_server_decision_dispatch import (
    ServerDecisionDispatchRequest,
    ServerDecisionTelemetry,
    dispatch_server_decision,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from eneo.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
from eneo.flows.ai_builder.ai_builder_telemetry import (
    planner_call_records_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    AskCanonicalQuestion,
    BuilderTurnDecision,
    CommitArchitecture,
    ConfirmRequirements,
    RefuseArchitectureCommit,
    ReviseArchitecture,
    resolve_turn_control,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    ArchitectureCommitDraft,
    CheckpointIntent,
    FileRoleEvidence,
    NamedResultEvidence,
    PlanningState,
    ResolvedSlot,
)
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
    carry_forward_persisted_planner_state,
    carry_forward_turn_resolved_planner_state,
)
from eneo.flows.ai_builder.question_catalog import render_summary_label


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
    confirmed_requirements_version: str | None = None,
    discovery_assumptions: tuple[str, ...] = (),
    flow: object | None = None,
    ui_language: str = "en",
    selected_discovery_question_ids: tuple[str, ...] = (),
    requirements_confirmation_required: bool = True,
    attachment_context: AIBuilderAttachmentContext | None = None,
    schema_candidates: tuple[DeclaredSchemaCandidate, ...] = (),
    schema_direction_pending: bool = False,
    focused_classification_runtime: FocusedSlotClassificationRuntime | None = None,
) -> ServerDecisionDispatchRequest:
    return ServerDecisionDispatchRequest(
        repo=repo,
        turn=_turn(),
        decision=decision,
        conversation=conversation,
        new_messages_start=new_messages_start,
        flow=cast("Flow | None", flow),
        confirmed_requirements_version=confirmed_requirements_version,
        ui_language=ui_language,
        telemetry=ServerDecisionTelemetry(
            request_id="req-test",
            litellm_model="server",
            usage_tracker=ProposalTurnTelemetry(
                request_id="req-test",
                model="server",
                target_kind=TargetKind.CREATE,
            ),
        ),
        planning_state=planning_state or PlanningState.empty(),
        selected_discovery_question_ids=selected_discovery_question_ids,
        requirements_confirmation_required=requirements_confirmation_required,
        attachment_context=attachment_context,
        schema_candidates=schema_candidates,
        schema_direction_pending=schema_direction_pending,
        discovery_assumptions=discovery_assumptions,
        focused_classification_runtime=focused_classification_runtime,
    )


def _focused_runtime(
    response_payload: dict[str, object],
) -> tuple[FocusedSlotClassificationRuntime, MagicMock]:
    message = MagicMock(content=json.dumps(response_payload))
    response = MagicMock(choices=[MagicMock(message=message)])
    litellm_client = MagicMock()
    litellm_client.acompletion = AsyncMock(return_value=response)
    route = ResolvedCompletionModelRoute(
        litellm_model="focused-test",
        provider_type="openai",
        litellm_kwargs={},
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(supported=True)
        ),
    )
    return (
        FocusedSlotClassificationRuntime(
            litellm_client=litellm_client,
            completion_model_route=route,
            max_input_tokens=100_000,
            max_output_tokens=4_096,
            budget_policy=AIBuilderBudgetPolicy(
                conversation_safety_buffer_tokens=0,
                minimum_conversation_budget_tokens=0,
            ),
        ),
        litellm_client,
    )


def _focused_slot_response(*slots: dict[str, object]) -> dict[str, object]:
    return {
        "slots": list(slots),
        "file_roles": [],
        "checkpoint_updates": [],
        "form_intake": None,
        "named_result_evidence": None,
        "example_output_constraints": None,
        "schema_direction": None,
        "secondary_obligations": [],
        "assumptions": [],
        "contradictions": [],
    }


def _rebuilding_commit_side_effect(
    *,
    persisted_conversation: list[ConversationMessage],
    persisted_states: list[PlanningState],
) -> object:
    async def commit_turn(
        *,
        turn: SessionSendTurn,
        new_messages: list[ConversationMessage],
        flow: "Flow | None" = None,
        planning_state: PlanningState,
        architecture_commit: ArchitectureCommit | None = None,
        **_: object,
    ) -> int:
        positions = {
            message.message_id: index
            for index, message in enumerate(persisted_conversation)
        }
        for message in new_messages:
            index = positions.get(message.message_id)
            if index is None:
                positions[message.message_id] = len(persisted_conversation)
                persisted_conversation.append(message.model_copy(deep=True))
            else:
                persisted_conversation[index] = message.model_copy(deep=True)
        rebuilt = build_planning_state_from_conversation(
            persisted_conversation,
            flow=flow,
        )
        if architecture_commit is not None:
            rebuilt.architecture_commit = architecture_commit
        carry_forward_turn_resolved_planner_state(
            rebuilt,
            planning_state,
            conversation=persisted_conversation,
            attached_file_ids=set(),
        )
        carry_forward_persisted_planner_state(
            rebuilt,
            persisted_states[-1] if persisted_states else None,
            attached_file_ids=set(),
        )
        persisted_states.append(rebuilt)
        return turn.base_planning_state_version + 1

    return commit_turn


def _transcription_flow() -> "Flow":
    """A published flow whose runs start from an uploaded recording.

    Shaped after the session that surfaced the defect: a recording is
    transcribed, and the transcript becomes a Word document.
    """

    from eneo.flows.domain.flow import Flow, FlowStep

    flow_id = uuid4()
    tenant_id = uuid4()
    return Flow(
        id=flow_id,
        name="Mötesljud till protokoll",
        description="Transkriberar mötesljud och skriver protokoll.",
        tenant_id=tenant_id,
        space_id=uuid4(),
        steps=[
            FlowStep(
                id=uuid4(),
                flow_id=flow_id,
                tenant_id=tenant_id,
                assistant_id=uuid4(),
                step_order=1,
                user_description="Transkribera mötesljudet",
                input_source="flow_input",
                input_type="audio",
                output_mode="transcribe_only",
                output_type="text",
            ),
            FlowStep(
                id=uuid4(),
                flow_id=flow_id,
                tenant_id=tenant_id,
                assistant_id=uuid4(),
                step_order=2,
                user_description="Skriv tjänsteskrivelsen som Word-dokument",
                input_source="previous_step",
                input_type="text",
                output_mode="compose_text",
                output_type="docx",
            ),
        ],
    )


def _recording_and_documents_flow() -> "Flow":
    """A flow whose runs take a recording and uploaded documents together.

    The runtime input question offers one material per run, so this flow's own
    answer is not among the options it lists.
    """

    from eneo.flows.domain.flow import FlowStep

    flow = _transcription_flow()
    flow.steps.append(
        FlowStep(
            id=uuid4(),
            flow_id=flow.id,
            tenant_id=flow.tenant_id,
            assistant_id=uuid4(),
            step_order=3,
            user_description="Läs de uppladdade underlagen",
            input_source="flow_input",
            input_type="document",
            output_mode="compose_text",
            output_type="text",
        )
    )
    return flow


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
        "report_disposition": _slot("report_disposition", "both"),
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
async def test_architecture_refusal_projects_selected_public_code_without_commit() -> (
    None
):
    repo = AsyncMock()

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=RefuseArchitectureCommit(
                code=AIBuilderErrorCode.TEMPLATE_ATTACHMENT_UNREADABLE,
                message="Attach a readable DOCX template.",
            ),
            conversation=[ConversationMessage(role="user", content="Use the template")],
        )
    )

    assert result.action_kind == "refuse_architecture_commit"
    assert result.new_planning_state_version == 4
    assert [event.event for event in result.events] == ["error"]
    error = result.events[0].data
    assert error.code is AIBuilderErrorCode.TEMPLATE_ATTACHMENT_UNREADABLE
    assert error.category == "bad_request"
    assert error.phase == "planner"
    assert error.message == "Attach a readable DOCX template."
    repo.commit_turn.assert_not_awaited()


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
            has_readable_text=True,
            coverage="fully_seen",
            role="reference_material",
            source="heuristic",
            confidence="medium",
        )
    ]
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    decision = AskCanonicalQuestion(
        slot_name="primary_runtime_input",
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
    assert repo.commit_turn.await_args.kwargs["planning_state"] is state


@pytest.mark.asyncio
async def test_focused_classification_resolves_missed_slot_before_question() -> None:
    quote = "The user uploads a CV and cover letter."
    source_id = "user_message:user-focused"
    runtime, litellm_client = _focused_runtime(
        _focused_slot_response(
            {
                "slot_name": "primary_runtime_input",
                "value": "documents",
                "confidence": "high",
                "reason": "The runtime material is uploaded documents.",
                "evidence": [{"source_id": source_id, "quote": quote}],
                "evidence_level": "explicit",
            }
        )
    )
    state = _confirmed_state()
    del state.resolved_slots["primary_runtime_input"]
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    conversation = [
        ConversationMessage(
            role="user",
            content=quote,
            message_id="user-focused",
        )
    ]
    request = _request(
        repo=repo,
        decision=AskCanonicalQuestion(slot_name="primary_runtime_input"),
        conversation=conversation,
        planning_state=state,
        focused_classification_runtime=runtime,
    )

    result = await dispatch_server_decision(request)

    assert result.action_kind == "confirm_requirements"
    assert all(not isinstance(event, AIBuilderQuestionEvent) for event in result.events)
    resolved = state.resolved_slots["primary_runtime_input"]
    assert resolved.value == "documents"
    assert resolved.source == "model"
    assert resolved.is_commit_grade is True
    assert state.focused_classification_attempted_slots == ["primary_runtime_input"]
    assert litellm_client.acompletion.await_count == 1
    telemetry = request.telemetry.usage_tracker.build_planner_telemetry()
    assert telemetry["auxiliary_llm_call_count"] == 1
    assert [record["call_kind"] for record in telemetry["call_records"]] == [
        "slot_classification"
    ]


@pytest.mark.asyncio
async def test_focused_classification_resolves_explicit_report_disposition_without_asking() -> (
    None
):
    quote = "Create both one section per source and a combined overview."
    source_id = "user_message:user-report-disposition"
    runtime, litellm_client = _focused_runtime(
        _focused_slot_response(
            {
                "slot_name": "report_disposition",
                "value": "both",
                "confidence": "high",
                "reason": "The user explicitly requests both report structures.",
                "evidence": [{"source_id": source_id, "quote": quote}],
                "evidence_level": "explicit",
            }
        )
    )
    state = _confirmed_state()
    state.architecture_commit = None
    del state.resolved_slots["report_disposition"]
    conversation = [
        ConversationMessage(
            role="user",
            content=quote,
            message_id="user-report-disposition",
        )
    ]
    decision = resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        requirements_disclosure=build_requirements_disclosure(
            state,
            ui_language="en",
        ),
        confirmed_requirements_version=None,
        ui_language="en",
    ).decision
    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "report_disposition"

    persisted_conversation: list[ConversationMessage] = []
    persisted_states: list[PlanningState] = []
    repo = AsyncMock()
    repo.commit_turn.side_effect = _rebuilding_commit_side_effect(
        persisted_conversation=persisted_conversation,
        persisted_states=persisted_states,
    )
    repo.load_planning_state.side_effect = lambda **_: persisted_states[-1]

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=decision,
            conversation=conversation,
            planning_state=state,
            focused_classification_runtime=runtime,
        )
    )

    assert result.action_kind == "commit_architecture"
    assert all(not isinstance(event, AIBuilderQuestionEvent) for event in result.events)
    assert state.resolved_slots["report_disposition"].value == "both"
    assert state.focused_classification_attempted_slots == ["report_disposition"]
    assert litellm_client.acompletion.await_count == 1
    assert persisted_states[-1].architecture_commit is not None
    assert persisted_states[-1].architecture_commit.report_disposition == "both"
    assert persisted_states[-1].resolved_slots["report_disposition"].value == "both"


@pytest.mark.asyncio
async def test_direct_proposal_persists_focused_evidence_for_repository_rebuild() -> (
    None
):
    quote = "The user uploads a CV and cover letter."
    runtime, _ = _focused_runtime(
        _focused_slot_response(
            {
                "slot_name": "primary_runtime_input",
                "value": "documents",
                "confidence": "high",
                "reason": "The runtime material is uploaded documents.",
                "evidence": [
                    {
                        "source_id": "user_message:user-direct-proposal",
                        "quote": quote,
                    }
                ],
                "evidence_level": "explicit",
            }
        )
    )
    state = _confirmed_state()
    del state.resolved_slots["primary_runtime_input"]
    persisted_conversation: list[ConversationMessage] = []
    persisted_states: list[PlanningState] = []
    repo = AsyncMock()
    repo.commit_turn.side_effect = _rebuilding_commit_side_effect(
        persisted_conversation=persisted_conversation,
        persisted_states=persisted_states,
    )
    conversation = [
        ConversationMessage(
            role="user",
            content=quote,
            message_id="user-direct-proposal",
        )
    ]
    request = _request(
        repo=repo,
        decision=AskCanonicalQuestion(slot_name="primary_runtime_input"),
        conversation=conversation,
        planning_state=state,
        requirements_confirmation_required=False,
        focused_classification_runtime=runtime,
    )

    result = await dispatch_server_decision(request)

    assert result.action_kind == "continue_proposal"
    continuation = result.proposal_continuation
    assert continuation is not None
    await repo.commit_turn(
        turn=request.turn,
        new_messages=conversation[continuation.new_messages_start :],
        planning_state=continuation.planning_state,
    )
    rebuilt = persisted_states[-1]
    resolved = rebuilt.resolved_slots["primary_runtime_input"]
    assert resolved.value == "documents"
    assert resolved.source == "model"
    assert any("user-direct-proposal" in evidence for evidence in resolved.evidence)


@pytest.mark.asyncio
async def test_newer_output_uncertainty_invalidates_persisted_focused_result() -> None:
    quote = "The final output is a PDF document."
    runtime, litellm_client = _focused_runtime(
        _focused_slot_response(
            {
                "slot_name": "terminal_output",
                "value": "pdf_document",
                "confidence": "high",
                "reason": "The final deliverable is explicitly a PDF.",
                "evidence": [
                    {
                        "source_id": "user_message:user-focused-output",
                        "quote": quote,
                    }
                ],
                "evidence_level": "explicit",
            }
        )
    )
    repo = AsyncMock()
    persisted_conversation: list[ConversationMessage] = []
    persisted_states: list[PlanningState] = []
    repo.commit_turn.side_effect = _rebuilding_commit_side_effect(
        persisted_conversation=persisted_conversation,
        persisted_states=persisted_states,
    )
    repo.load_planning_state.side_effect = lambda **_: persisted_states[-1]
    conversation = [
        ConversationMessage(
            role="user",
            content=quote,
            message_id="user-focused-output",
        )
    ]
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "documents",
    )
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "synthesized_overview",
    )

    await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(slot_name="terminal_output"),
            conversation=conversation,
            planning_state=state,
            requirements_confirmation_required=False,
            focused_classification_runtime=runtime,
        )
    )
    assert persisted_states[-1].commit_grade_slot_value("terminal_output") == (
        "pdf_document"
    )

    uncertain_message = ConversationMessage(
        role="user",
        content=("I do not know exactly what format the final output should be yet."),
        message_id="user-output-uncertain",
    )
    replay_conversation = [*persisted_conversation, uncertain_message]
    replayed_state = build_planning_state_from_conversation(replay_conversation)
    carry_forward_persisted_planner_state(
        replayed_state,
        persisted_states[-1],
        attached_file_ids=set(),
    )
    second_repo = AsyncMock()
    second_repo.commit_turn.return_value = 6
    result = await dispatch_server_decision(
        _request(
            repo=second_repo,
            decision=AskCanonicalQuestion(slot_name="terminal_output"),
            conversation=replay_conversation,
            planning_state=replayed_state,
            focused_classification_runtime=runtime,
        )
    )

    assert replayed_state.commit_grade_slot_value("terminal_output") is None
    assert result.action_kind == "ask_question"
    assert any(isinstance(event, AIBuilderQuestionEvent) for event in result.events)
    assert replayed_state.focused_classification_attempted_slots == ["terminal_output"]
    assert litellm_client.acompletion.await_count == 1


@pytest.mark.asyncio
async def test_focused_provider_failure_asks_and_persisted_attempt_is_not_retried() -> (
    None
):
    runtime, litellm_client = _focused_runtime(_focused_slot_response())
    litellm_client.acompletion.side_effect = Timeout(
        "provider timed out",
        model="focused-test",
        llm_provider="openai",
    )
    repo = AsyncMock()
    persisted_conversation: list[ConversationMessage] = []
    persisted_states: list[PlanningState] = []
    repo.commit_turn.side_effect = _rebuilding_commit_side_effect(
        persisted_conversation=persisted_conversation,
        persisted_states=persisted_states,
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="Build a useful flow.",
            message_id="user-provider-failure",
        )
    ]
    decision = AskCanonicalQuestion(slot_name="primary_runtime_input")

    first_request = _request(
        repo=repo,
        decision=decision,
        conversation=conversation,
        planning_state=PlanningState.empty(),
        focused_classification_runtime=runtime,
    )
    first = await dispatch_server_decision(first_request)
    replayed_state = persisted_states[-1]
    second_repo = AsyncMock()
    second_repo.commit_turn.return_value = 6
    second = await dispatch_server_decision(
        _request(
            repo=second_repo,
            decision=decision,
            conversation=persisted_conversation,
            planning_state=replayed_state,
            focused_classification_runtime=runtime,
        )
    )

    assert first.action_kind == "ask_question"
    assert second.action_kind == "ask_question"
    assert any(isinstance(event, AIBuilderQuestionEvent) for event in first.events)
    assert any(isinstance(event, AIBuilderQuestionEvent) for event in second.events)
    assert replayed_state.focused_classification_attempted_slots == [
        "primary_runtime_input"
    ]
    assert litellm_client.acompletion.await_count == 1
    telemetry = first_request.telemetry.usage_tracker.build_planner_telemetry()
    assert telemetry["auxiliary_llm_call_count"] == 1
    assert telemetry["call_records"][0]["provider_failure_kind"] == "timeout"


@pytest.mark.asyncio
async def test_report_disposition_provider_failure_persists_question_without_commit_or_retry() -> (
    None
):
    runtime, litellm_client = _focused_runtime(_focused_slot_response())
    litellm_client.acompletion.side_effect = Timeout(
        "provider timed out",
        model="focused-test",
        llm_provider="openai",
    )
    state = _confirmed_state()
    state.architecture_commit = None
    del state.resolved_slots["report_disposition"]
    decision = AskCanonicalQuestion(slot_name="report_disposition")
    conversation = [
        ConversationMessage(
            role="user",
            content="Build one report from several documents.",
            message_id="user-report-provider-failure",
        )
    ]
    persisted_conversation: list[ConversationMessage] = []
    persisted_states: list[PlanningState] = []
    repo = AsyncMock()
    repo.commit_turn.side_effect = _rebuilding_commit_side_effect(
        persisted_conversation=persisted_conversation,
        persisted_states=persisted_states,
    )
    first_request = _request(
        repo=repo,
        decision=decision,
        conversation=conversation,
        planning_state=state,
        focused_classification_runtime=runtime,
    )

    first = await dispatch_server_decision(first_request)
    replayed_state = persisted_states[-1]
    second_repo = AsyncMock()
    second_repo.commit_turn.return_value = 6
    second = await dispatch_server_decision(
        _request(
            repo=second_repo,
            decision=decision,
            conversation=persisted_conversation,
            planning_state=replayed_state,
            focused_classification_runtime=runtime,
        )
    )

    first_question = next(
        event for event in first.events if isinstance(event, AIBuilderQuestionEvent)
    )
    second_question = next(
        event for event in second.events if isinstance(event, AIBuilderQuestionEvent)
    )
    assert first.action_kind == "ask_question"
    assert second.action_kind == "ask_question"
    assert first_question.data.question_id == "report_disposition"
    assert second_question.data.question_id == "report_disposition"
    assert replayed_state.architecture_commit is None
    assert replayed_state.focused_classification_attempted_slots == [
        "report_disposition"
    ]
    assert litellm_client.acompletion.await_count == 1
    telemetry = first_request.telemetry.usage_tracker.build_planner_telemetry()
    assert telemetry["auxiliary_llm_call_count"] == 1
    assert telemetry["call_records"][0]["provider_failure_kind"] == "timeout"


@pytest.mark.asyncio
async def test_focused_request_budget_failure_asks_and_records_attempt() -> None:
    base_runtime, litellm_client = _focused_runtime(_focused_slot_response())
    runtime = FocusedSlotClassificationRuntime(
        litellm_client=base_runtime.litellm_client,
        completion_model_route=base_runtime.completion_model_route,
        max_input_tokens=1,
        max_output_tokens=1,
        budget_policy=base_runtime.budget_policy,
    )
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    state = PlanningState.empty()
    request = _request(
        repo=repo,
        decision=AskCanonicalQuestion(slot_name="primary_runtime_input"),
        conversation=[
            ConversationMessage(
                role="user",
                content="Build a useful flow.",
                message_id="user-budget-failure",
            )
        ],
        planning_state=state,
        focused_classification_runtime=runtime,
    )

    result = await dispatch_server_decision(request)

    assert result.action_kind == "ask_question"
    assert state.focused_classification_attempted_slots == ["primary_runtime_input"]
    assert repo.commit_turn.await_args.kwargs["planning_state"] is state
    litellm_client.acompletion.assert_not_awaited()
    telemetry = request.telemetry.usage_tracker.build_planner_telemetry()
    assert telemetry["llm_calls_made"] == 0
    assert telemetry["auxiliary_llm_call_count"] == 0


@pytest.mark.parametrize(
    ("confidence", "evidence"),
    [
        ("high", []),
        (
            "low",
            [
                {
                    "source_id": "user_message:user-not-admitted",
                    "quote": "The user uploads a CV.",
                }
            ],
        ),
    ],
)
@pytest.mark.asyncio
async def test_focused_classification_keeps_normal_admission_bar(
    confidence: str,
    evidence: list[dict[str, str]],
) -> None:
    runtime, litellm_client = _focused_runtime(
        _focused_slot_response(
            {
                "slot_name": "primary_runtime_input",
                "value": "documents",
                "confidence": confidence,
                "reason": "The runtime material may be documents.",
                "evidence": evidence,
                "evidence_level": "explicit",
            }
        )
    )
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    state = PlanningState.empty()

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(slot_name="primary_runtime_input"),
            conversation=[
                ConversationMessage(
                    role="user",
                    content="The user uploads a CV.",
                    message_id="user-not-admitted",
                )
            ],
            planning_state=state,
            focused_classification_runtime=runtime,
        )
    )

    assert result.action_kind == "ask_question"
    assert any(isinstance(event, AIBuilderQuestionEvent) for event in result.events)
    assert state.commit_grade_slot_value("primary_runtime_input") is None
    assert litellm_client.acompletion.await_count == 1


@pytest.mark.asyncio
async def test_non_classifier_question_skips_focused_classification() -> None:
    runtime, litellm_client = _focused_runtime(_focused_slot_response())
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    question = BackendQuestion(
        question_data=StructuredQuestionPayload(
            question_id="schema_direction",
            question="Which schema direction?",
            options=[
                StructuredQuestionOptionPayload(
                    id="input",
                    label="Input",
                    value="input",
                )
            ],
            selection_mode="single",
            allow_custom=False,
            requires_confirm=True,
        ),
        assistant_text="Choose how the schema is used.",
    )
    state = PlanningState.empty()

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(
                slot_name="schema_direction",
                question=question,
            ),
            conversation=[ConversationMessage(role="user", content="Build a flow")],
            planning_state=state,
            focused_classification_runtime=runtime,
        )
    )

    assert result.action_kind == "ask_question"
    assert any(isinstance(event, AIBuilderQuestionEvent) for event in result.events)
    assert state.focused_classification_attempted_slots == []
    litellm_client.acompletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_question_uses_canonical_slot_name_question_id() -> None:
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    conversation = [ConversationMessage(role="user", content="Build a flow")]
    decision = AskCanonicalQuestion(
        slot_name="primary_runtime_input",
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
async def test_architecture_commit_chains_runtime_metadata_field_question() -> None:
    repo = AsyncMock()
    repo.commit_turn.side_effect = [5, 6]
    state = _confirmed_state()
    state.resolved_slots["runtime_metadata_fields"] = _slot(
        "runtime_metadata_fields",
        "basic_runtime_metadata",
    )
    state.architecture_commit = _finalized_commit_for_state(state)
    repo.load_planning_state.return_value = state
    conversation = [ConversationMessage(role="user", content="Build a document flow")]
    decision = CommitArchitecture(architecture_commit=_draft_for_state(state))

    result = await dispatch_server_decision(
        _request(repo=repo, decision=decision, conversation=conversation)
    )

    assert [event.event for event in result.events] == ["status", "text", "question"]
    question = result.events[2]
    assert isinstance(question, AIBuilderQuestionEvent)
    assert question.data.question_id == "runtime_metadata_field_details"
    assert repo.commit_turn.await_count == 2
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
    assert result.events[0].data.status == AIBuilderStatus.ARCHITECTURE_REVISED
    first_commit = repo.commit_turn.await_args_list[0].kwargs
    persisted_commit = first_commit["architecture_commit"]
    assert isinstance(persisted_commit, ArchitectureCommit)
    assert canonical_architecture_commit_payload(persisted_commit) == (
        canonical_architecture_commit_payload(draft)
    )
    assert result.new_planning_state_version == 6


@pytest.mark.asyncio
async def test_architecture_revision_chains_selected_discovery_question() -> None:
    repo = AsyncMock()
    repo.commit_turn.side_effect = [5, 6]
    state = _revised_pdf_state()
    draft = _draft_for_state(state)
    state.architecture_commit = finalize_architecture_commit(
        draft,
        now=lambda: datetime(2026, 4, 24, tzinfo=timezone.utc),
    )
    repo.load_planning_state.return_value = state

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=ReviseArchitecture(architecture_commit=draft),
            conversation=[
                ConversationMessage(role="user", content="Make it PDF instead")
            ],
            selected_discovery_question_ids=("runtime_metadata_fields",),
        )
    )

    assert [event.event for event in result.events] == ["status", "text", "question"]
    question = result.events[2]
    assert isinstance(question, AIBuilderQuestionEvent)
    assert question.data.question_id == "runtime_metadata_fields"
    assert result.new_planning_state_version == 6


@pytest.mark.asyncio
async def test_architecture_commit_chains_refusal_instead_of_ending_silently() -> None:
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    state = _confirmed_state()
    state.checkpoint_intents = [
        CheckpointIntent(
            evidence_level="explicit",
            producer_kind="transcript",
            operation="set",
            mode="edit",
            confidence="high",
            evidence=["quote:user_message:test:review the transcript"],
        )
    ]
    repo.load_planning_state.return_value = state

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=CommitArchitecture(architecture_commit=_draft_for_state(state)),
            conversation=[
                ConversationMessage(role="user", content="Review the transcript")
            ],
        )
    )

    assert [event.event for event in result.events] == ["status", "error"]
    error = result.events[1].data
    assert error.code is AIBuilderErrorCode.TRANSCRIPT_CHECKPOINT_REQUIRES_AUDIO
    assert result.new_planning_state_version == 5


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
    confirmation = resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        requirements_disclosure=build_requirements_disclosure(state, ui_language="en"),
        confirmed_requirements_version=None,
        ui_language="en",
    ).decision
    assert isinstance(confirmation, ConfirmRequirements)

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=decision,
            conversation=conversation,
            confirmed_requirements_version=(confirmation.payload.requirements_version),
        )
    )

    assert result.action_kind == "revise_architecture"
    assert [event.event for event in result.events] == ["status"]
    assert result.events[0].data.status == AIBuilderStatus.ARCHITECTURE_REVISED
    assert result.new_planning_state_version == 5
    assert result.proposal_continuation is not None
    assert result.proposal_continuation.planning_state is state


@pytest.mark.asyncio
async def test_step_edit_revision_continues_without_requirements_confirmation() -> None:
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    state = _revised_pdf_state()
    draft = _draft_for_state(state)
    state.architecture_commit = finalize_architecture_commit(
        draft,
        now=lambda: datetime(2026, 4, 24, tzinfo=timezone.utc),
    )
    repo.load_planning_state.return_value = state

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=ReviseArchitecture(architecture_commit=draft),
            conversation=[
                ConversationMessage(role="user", content="Make this step a PDF")
            ],
            requirements_confirmation_required=False,
            flow=object(),
        )
    )

    assert [event.event for event in result.events] == ["status"]
    assert result.proposal_continuation is not None
    assert repo.commit_turn.await_count == 1


@pytest.mark.asyncio
async def test_revision_chains_schema_direction_question_with_same_candidates() -> None:
    repo = AsyncMock()
    repo.commit_turn.side_effect = [5, 6]
    state = _revised_pdf_state()
    draft = _draft_for_state(state)
    state.architecture_commit = finalize_architecture_commit(
        draft,
        now=lambda: datetime(2026, 4, 24, tzinfo=timezone.utc),
    )
    repo.load_planning_state.return_value = state
    candidates = (
        build_declared_schema_candidate(
            {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            },
            source_file_ids=(UUID(int=1),),
            provenance=(f"file:{UUID(int=1)}:json_schema_attachment",),
        ),
    )

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=ReviseArchitecture(architecture_commit=draft),
            conversation=[
                ConversationMessage(role="user", content="Make it PDF instead")
            ],
            schema_candidates=candidates,
            schema_direction_pending=True,
        )
    )

    assert [event.event for event in result.events] == ["status", "text", "question"]
    question = result.events[2]
    assert isinstance(question, AIBuilderQuestionEvent)
    assert question.data.question_id == "schema_direction"


@pytest.mark.asyncio
async def test_architecture_chain_rejects_a_second_revision() -> None:
    repo = AsyncMock()
    stale_state = PlanningState.empty()
    stale_state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "text"),
        "terminal_output": _slot("terminal_output", "structured_text"),
    }
    stale_state.architecture_commit = _finalized_commit_for_state(stale_state)
    stale_state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    stale_state.resolved_slots["pdf_generation_mode"] = _slot(
        "pdf_generation_mode",
        "generated_pdf",
    )
    revision = _draft_for_state(stale_state)
    repo.commit_turn.return_value = 5
    repo.load_planning_state.return_value = stale_state

    with pytest.raises(
        ValueError,
        match=(
            "architecture commit chain produced another architecture decision: "
            "original=ReviseArchitecture, chained=ReviseArchitecture, "
            "request_id=req-test"
        ),
    ):
        await dispatch_server_decision(
            _request(
                repo=repo,
                decision=ReviseArchitecture(architecture_commit=revision),
                conversation=[
                    ConversationMessage(role="user", content="Make it PDF instead")
                ],
            )
        )


@pytest.mark.asyncio
async def test_architecture_revision_reconfirms_changed_hidden_attachment() -> None:
    repo = AsyncMock()
    repo.commit_turn.side_effect = [5, 6]
    now = datetime(2026, 4, 24, tzinfo=timezone.utc)
    state = _revised_pdf_state()
    state.file_roles = [
        FileRoleEvidence(
            file_id=UUID(int=index + 1),
            filename=f"reference-{index}.pdf",
            file_type="document",
            mimetype="application/pdf",
            has_readable_text=True,
            coverage="fully_seen",
            role="context_only",
            source="heuristic",
            confidence="low",
        )
        for index in range(12)
    ]
    draft = _draft_for_state(state)
    state.architecture_commit = finalize_architecture_commit(draft, now=lambda: now)
    confirmation = resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        requirements_disclosure=build_requirements_disclosure(state, ui_language="en"),
        confirmed_requirements_version=None,
        ui_language="en",
    ).decision
    assert isinstance(confirmation, ConfirmRequirements)
    state.file_roles[11] = state.file_roles[11].model_copy(
        update={
            "coverage": "excerpt_truncated",
            "role": "reference_material",
        }
    )
    repo.load_planning_state.return_value = state

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=ReviseArchitecture(architecture_commit=draft),
            conversation=[
                ConversationMessage(role="user", content="Use the new reference")
            ],
            confirmed_requirements_version=(confirmation.payload.requirements_version),
        )
    )

    assert result.action_kind == "revise_architecture"
    assert [event.event for event in result.events] == [
        "status",
        "requirements_summary",
    ]
    assert result.new_planning_state_version == 6
    assert result.proposal_continuation is None


@pytest.mark.asyncio
async def test_chained_confirmation_of_an_edit_session_ignores_named_result_admission() -> (
    None
):
    # The chained confirmation resolves turn control itself, so it needs the
    # same edit-mode fact the direct path has. Without it an edit session with
    # more named results than the create projection admits would be refused
    # over a create schema it never builds.
    repo = AsyncMock()
    repo.commit_turn.side_effect = [5, 6]
    state = _confirmed_state()
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_json",
    )
    state.named_result_evidence = [
        NamedResultEvidence(
            name=f"field_{index}",
            confidence="high",
            evidence=[f"quote:user_message:user-1:field_{index}"],
        )
        for index in range(13)
    ]
    state.architecture_commit = _finalized_commit_for_state(state)
    repo.load_planning_state.return_value = state
    conversation = [ConversationMessage(role="user", content="Change the flow")]
    decision = CommitArchitecture(architecture_commit=_draft_for_state(state))

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=decision,
            conversation=conversation,
            flow=object(),
        )
    )

    assert [event.event for event in result.events] == [
        "status",
        "requirements_summary",
    ]
    # The chained path builds its own disclosure, so it also has to carry the
    # edit-mode fact: an edit projects nothing, and the confirmation is hashed,
    # so a create-only placement sentence would be attested to here.
    summary = next(
        event for event in result.events if event.event == "requirements_summary"
    )
    assert "top level" not in summary.data.summary


@pytest.mark.asyncio
async def test_a_question_is_numbered_by_the_ones_the_user_has_already_seen() -> None:
    # "Another question" reads as an open-ended interview. The count is taken
    # from the questions actually put to the user, and this one is not persisted
    # yet, so it is the next number after them.
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    conversation = [
        ConversationMessage(role="user", content="Bygg ett flöde"),
        ConversationMessage(
            role="assistant",
            content="Vad ska flödet ta emot?",
            metadata={"question_id": "primary_runtime_input", "question_index": 1},
        ),
        ConversationMessage(role="user", content="Dokument"),
    ]

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(slot_name="post_processing_goal"),
            conversation=conversation,
        )
    )

    question = next(event for event in result.events if event.event == "question")
    assert question.data.question_index == 2


@pytest.mark.asyncio
async def test_a_question_carries_the_questions_still_queued_behind_it() -> None:
    # The count travels on the decision, from the turn control that ranked the
    # queue, so a user weighing a choice can also see roughly how much of the
    # interview is left.
    repo = AsyncMock()
    repo.commit_turn.return_value = 5

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(
                slot_name="post_processing_goal",
                planned_remaining=2,
            ),
            conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        )
    )

    question = next(event for event in result.events if event.event == "question")
    assert question.data.questions_planned_remaining == 2


@pytest.mark.asyncio
async def test_a_question_names_its_topic_the_way_the_summary_will() -> None:
    # The user meets this topic twice: once as a question, once as a row in the
    # summary they confirm. Both read the catalog's label for the slot, in the
    # session's own language, so the two cannot drift apart.
    repo = AsyncMock()
    repo.commit_turn.return_value = 5

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(slot_name="post_processing_goal"),
            conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
            ui_language="sv",
        )
    )

    question = next(event for event in result.events if event.event == "question")
    assert question.data.topic == render_summary_label("post_processing_goal", "sv")


@pytest.mark.asyncio
async def test_a_question_outside_the_catalog_names_no_topic() -> None:
    # Schema direction settles no catalog slot, so there is no label to give.
    # Describing it from its own wording would be a second name for the topic,
    # free to drift from whatever the summary later calls it.
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    followup = BackendQuestion(
        question_data=StructuredQuestionPayload(
            question_id="schema_direction",
            question="Which schema controls the result?",
            options=[
                StructuredQuestionOptionPayload(
                    id="attached", label="The attached schema", value="attached"
                )
            ],
            selection_mode="single",
            allow_custom=False,
        ),
        assistant_text="Which schema controls the result?",
    )

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(
                slot_name="schema_direction",
                question=followup,
            ),
            conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        )
    )

    question = next(event for event in result.events if event.event == "question")
    assert question.data.topic is None


@pytest.mark.asyncio
async def test_a_field_details_question_is_named_after_the_slot_it_settles() -> None:
    # The runtime-field question is not a catalog slot, but it settles one:
    # the decision row "Metadata vid körning" must lead back to it.
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    followup = BackendQuestion(
        question_data=StructuredQuestionPayload(
            question_id="runtime_metadata_field_details",
            question="Vad ska den som kör flödet fylla i?",
            options=[
                StructuredQuestionOptionPayload(
                    id="whole_flow",
                    label="Använd genom hela flödet",
                    value="whole_flow",
                )
            ],
            selection_mode="single",
            allow_custom=False,
            input_field_collection=True,
        ),
        assistant_text="Fälten blir ett formulär.",
    )

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(
                slot_name="runtime_metadata_field_details",
                question=followup,
            ),
            conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        )
    )

    question = next(event for event in result.events if event.event == "question")
    assert question.data.topic == render_summary_label("runtime_metadata_fields", "en")


@pytest.mark.asyncio
async def test_an_edit_question_names_the_value_the_running_flow_uses_today() -> None:
    # The flow being edited already answers this slot, and the user is looking at
    # a question about it. Without the current value on the payload the client
    # cannot tell a choice apart from a change.
    repo = AsyncMock()
    repo.commit_turn.return_value = 5

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(slot_name="primary_runtime_input"),
            conversation=[
                ConversationMessage(role="user", content="Förtydliga instruktionen")
            ],
            flow=_transcription_flow(),
        )
    )

    question = next(event for event in result.events if event.event == "question")
    assert question.data.current_option_id == "audio"


@pytest.mark.asyncio
async def test_a_create_question_names_no_current_value() -> None:
    # Nothing is running yet, so there is no value in use to name.
    repo = AsyncMock()
    repo.commit_turn.return_value = 5

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(slot_name="primary_runtime_input"),
            conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        )
    )

    question = next(event for event in result.events if event.event == "question")
    assert question.data.current_option_id is None


@pytest.mark.asyncio
async def test_an_edit_question_never_recommends_changing_what_the_flow_receives() -> (
    None
):
    # Taken from a real session. The live flow transcribes audio and writes a
    # Word document, and the user asked only for a PDF instead. "PDF fil" and
    # "docx fil" read as document material, so the input slot resolves to
    # documents on a heuristic; that is not commit-grade, so the slot counts as
    # an unresolved core gap and turn control asks about it. Reading the same
    # slot back as a recommendation badged Dokument on a flow that takes audio,
    # and one click on Bekräfta would have changed the input contract of
    # something other applications already run. Eneo does not badge that.
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    conversation = [
        ConversationMessage(
            role="user",
            content="Jag vill ha en PDF fil istället som utdata än en docx fil.",
        )
    ]
    flow = _transcription_flow()

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(slot_name="primary_runtime_input"),
            conversation=conversation,
            planning_state=build_planning_state_from_conversation(
                conversation, flow=flow
            ),
            flow=flow,
        )
    )

    question = next(event for event in result.events if event.event == "question")
    assert question.data.current_option_id == "audio"
    assert question.data.recommended_option_id is None
    assert question.data.recommended_option_evidence is None


@pytest.mark.asyncio
async def test_the_emitted_question_is_checked_against_the_payloads_own_rules() -> None:
    # Dispatch decides the last facts on the payload, so it is the last place the
    # model's rules can still be applied. Copying them into place would skip
    # those rules, and the pair they forbid is exactly the one this guard exists
    # to prevent, so the emitted question is built through validation.
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    flow = _transcription_flow()

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(slot_name="primary_runtime_input"),
            conversation=[
                ConversationMessage(role="user", content="Förtydliga instruktionen")
            ],
            flow=flow,
        )
    )

    question = next(event for event in result.events if event.event == "question")
    with pytest.raises(ValidationError):
        StructuredQuestionPayload.model_validate(
            question.data.model_dump() | {"recommended_option_id": "documents"}
        )


@pytest.mark.asyncio
async def test_a_flow_the_question_cannot_describe_recommends_nothing() -> None:
    # This flow takes a recording and uploaded documents in the same run, which
    # is not one of the materials the question offers. Naming one of them as the
    # current value would misstate what the flow does today, and every option on
    # screen would change the flow, so there is nothing safe to recommend either.
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    planning_state = PlanningState.empty()
    planning_state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="documents",
            source="heuristic",
            evidence=["heuristic:role-aware freeform analysis"],
            confidence="high",
        )
    }

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(slot_name="primary_runtime_input"),
            conversation=[
                ConversationMessage(role="user", content="Förtydliga instruktionen")
            ],
            planning_state=planning_state,
            flow=_recording_and_documents_flow(),
        )
    )

    question = next(event for event in result.events if event.event == "question")
    assert question.data.current_option_id is None
    assert question.data.recommended_option_id is None


@pytest.mark.asyncio
async def test_an_edit_recommendation_that_agrees_with_the_flow_is_kept() -> None:
    # Agreeing with what the flow already does changes nothing, so the
    # recommendation is still worth offering to a user who cannot judge the slot.
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    planning_state = PlanningState.empty()
    planning_state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="audio",
            source="heuristic",
            evidence=["heuristic:role-aware freeform analysis"],
            confidence="high",
        )
    }

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(slot_name="primary_runtime_input"),
            conversation=[
                ConversationMessage(role="user", content="Förtydliga instruktionen")
            ],
            planning_state=planning_state,
            flow=_transcription_flow(),
        )
    )

    question = next(event for event in result.events if event.event == "question")
    assert question.data.current_option_id == "audio"
    assert question.data.recommended_option_id == "audio"


@pytest.mark.asyncio
async def test_a_question_decided_outside_the_ask_queue_promises_nothing() -> None:
    # Schema direction and the runtime-field follow-up are decided ahead of the
    # ranked queue, so nothing behind them has been planned. Saying zero would
    # claim this is the last question, which the next turn can contradict.
    repo = AsyncMock()
    repo.commit_turn.return_value = 5

    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(slot_name="post_processing_goal"),
            conversation=[ConversationMessage(role="user", content="Bygg ett flöde")],
        )
    )

    question = next(event for event in result.events if event.event == "question")
    assert question.data.questions_planned_remaining is None


@pytest.mark.asyncio
async def test_a_classifier_only_turn_persists_its_provider_call_for_diagnostics() -> (
    None
):
    """The question turn's assistant message accounts for the classifier call.

    Diagnostics read persisted metadata, so a turn that classifies and then
    asks must leave its call record behind or the classifier's spend vanishes.
    """

    runtime, litellm_client = _focused_runtime(
        _focused_slot_response(
            {
                "slot_name": "primary_runtime_input",
                "value": "documents",
                "confidence": "high",
                "reason": "No admissible evidence.",
                "evidence": [],
                "evidence_level": "explicit",
            }
        )
    )
    repo = AsyncMock()
    repo.commit_turn.return_value = 5
    result = await dispatch_server_decision(
        _request(
            repo=repo,
            decision=AskCanonicalQuestion(slot_name="primary_runtime_input"),
            conversation=[
                ConversationMessage(
                    role="user",
                    content="The user uploads a CV.",
                    message_id="user-classifier-only",
                )
            ],
            planning_state=PlanningState.empty(),
            focused_classification_runtime=runtime,
        )
    )

    assert result.action_kind == "ask_question"
    assert litellm_client.acompletion.await_count == 1
    assistant_message = repo.commit_turn.await_args.kwargs["new_messages"][-2]
    read = planner_call_records_from_metadata(assistant_message.metadata)
    assert read.skipped == 0
    assert [(record.call_kind, record.attempt) for record in read.records] == [
        ("slot_classification", 1)
    ]
