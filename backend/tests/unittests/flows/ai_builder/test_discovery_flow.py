"""Tests for discovery flow and server-owned planning decisions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.completion_models.domain.model_kwargs_capabilities import (
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.flows.ai_builder.ai_builder_action_policy import (
    build_planner_action_policy,
)
from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    metadata_for_assistant_question,
    question_answer_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_discovery import (
    analyze_discovery,
    build_discovery_block_message,
    build_discovery_followup_text,
    build_registry_question_followup,
)
from eneo.flows.ai_builder.ai_builder_discovery_issue_rules import (
    post_processing_goal_is_vague,
)
from eneo.flows.ai_builder.ai_builder_discovery_profile_builder import (
    build_discovery_profile,
)
from eneo.flows.ai_builder.ai_builder_discovery_runtime import (
    build_runtime_discovery_context,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    SessionStatus,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    KeyDecisionPayload,
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_events import encode_ai_builder_stream_event
from eneo.flows.ai_builder.ai_builder_planner import AIBuilderPlanner
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    conversation_message_to_llm_message,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import ProposalTurnTelemetry
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
    build_requirements_disclosure,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    resolve_requirements_state,
)
from eneo.flows.ai_builder.ai_builder_server_decision_dispatch import (
    ServerDecisionDispatchRequest,
    ServerDecisionTelemetry,
    dispatch_server_decision,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
    SessionTurnAcceptance,
    SessionTurnClaim,
    SessionTurnClaimDisposition,
    SessionTurnPreflight,
    SessionTurnPreparationBaseline,
)
from eneo.flows.ai_builder.ai_builder_signal_confidence import ScoredSignal
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    UNKNOWN_SLOT_VALUE,
    ClassifiedEvidence,
    ClassifiedSlot,
    SlotClassificationAttempt,
    SlotClassificationEvidenceLevel,
    SlotClassificationResult,
)
from eneo.flows.ai_builder.ai_builder_turn_controller import AskCanonicalQuestion
from eneo.flows.ai_builder.ai_builder_user_question_metadata import (
    prepare_user_question_metadata,
)
from eneo.flows.ai_builder.planning_state import (
    FileRoleEvidence,
    MappedFileLimit,
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotSource,
)
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
    merge_llm_resolved_slots,
)
from eneo.flows.ai_builder.question_catalog import render_summary_label
from eneo.flows.domain.flow import Flow, FlowStep

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classifier_evidence(quote: str) -> tuple[ClassifiedEvidence, ...]:
    return (ClassifiedEvidence(source_id="user_message:test-source", quote=quote),)


def _planning_state_with_post_processing_goal(value: str) -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots["post_processing_goal"] = ResolvedSlot(
        name="post_processing_goal",
        value=value,
        source="model",
        confidence="high",
        evidence=["quote:user_message:test-source:typed classifier evidence"],
        evidence_level="inferred",
    )
    return state


def _open_interview_conversation(prompt: str) -> list[ConversationMessage]:
    return [
        ConversationMessage(
            message_id="test-source",
            role="user",
            content=prompt,
            metadata={"ui_language": "sv"},
        )
    ]


def _classified_open_interview(
    prompt: str,
    *,
    goal_confidence: SlotConfidence,
    goal_evidence_level: SlotClassificationEvidenceLevel,
    terminal_output: tuple[str, SlotConfidence] | None = None,
) -> tuple[PlanningState, SlotClassificationResult]:
    """Planning state as the turn builds it: classify, then merge, then ask."""

    slots = [
        ClassifiedSlot(
            slot_name="primary_runtime_input",
            value="text",
            confidence="high",
            reason="The runtime input is explicit.",
            evidence=_classifier_evidence(prompt),
            evidence_level="explicit",
        ),
        ClassifiedSlot(
            slot_name="post_processing_goal",
            value="structure_key_information",
            confidence=goal_confidence,
            reason="The requested outcome for the material.",
            evidence=_classifier_evidence(prompt),
            evidence_level=goal_evidence_level,
        ),
    ]
    if terminal_output is not None:
        terminal_value, terminal_confidence = terminal_output
        slots.append(
            ClassifiedSlot(
                slot_name="terminal_output",
                value=terminal_value,
                confidence=terminal_confidence,
                reason="The final result is implied by the request.",
                evidence=_classifier_evidence(prompt),
                evidence_level="inferred",
            )
        )
    classification = SlotClassificationResult(slots=tuple(slots))
    state = PlanningState.empty()
    merge_llm_resolved_slots(
        state,
        classification,
        prompt_hash="test-prompt-hash",
        freeform_text=prompt,
    )
    return state, classification


def _battle_case_prompt(case_id: str) -> str:
    cases_path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ai_builder_api_battle_cases.json"
    )
    payload = cast(
        dict[str, object], json.loads(cases_path.read_text(encoding="utf-8"))
    )
    cases = cast(list[dict[str, str]], payload["cases"])
    return next(case["prompt"] for case in cases if case["id"] == case_id)


def test_question_recommends_eneos_own_reading_of_the_slot() -> None:
    planning_state = PlanningState.empty()
    planning_state.resolved_slots = {
        "post_processing_goal": ResolvedSlot(
            name="post_processing_goal",
            value="summarize_or_overview",
            source="heuristic",
            confidence="medium",
            evidence=["heuristic:role-aware freeform analysis"],
        ),
    }

    followup = build_registry_question_followup(
        "post_processing_goal",
        [ConversationMessage(role="user", content="Summarize meeting notes")],
        planning_state=planning_state,
    )

    assert followup is not None
    recommended_id = followup.question_data.recommended_option_id
    assert recommended_id is not None
    recommended = next(
        option
        for option in followup.question_data.options
        if option.id == recommended_id
    )
    assert recommended.value == "summarize_or_overview"


def test_question_recommends_nothing_when_the_slot_is_unread() -> None:
    followup = build_registry_question_followup(
        "post_processing_goal",
        [ConversationMessage(role="user", content="Summarize meeting notes")],
        planning_state=PlanningState.empty(),
    )

    assert followup is not None
    assert followup.question_data.recommended_option_id is None


def test_a_delegated_question_is_settled_and_never_asked_again() -> None:
    """Handing a question back to Eneo decides it as firmly as answering it."""

    planning_state = PlanningState.empty()
    planning_state.resolved_slots = {
        "post_processing_goal": ResolvedSlot(
            name="post_processing_goal",
            value="summarize_or_overview",
            source="heuristic",
            confidence="medium",
            evidence=["heuristic:role-aware freeform analysis"],
        ),
    }
    request = ConversationMessage(role="user", content="Summarize meeting notes")
    followup = build_registry_question_followup(
        "post_processing_goal",
        [request],
        planning_state=planning_state,
    )
    assert followup is not None

    conversation = [
        request,
        ConversationMessage(
            role="assistant",
            content=followup.assistant_text,
            metadata=metadata_for_assistant_question(followup.question_data),
            tool_calls=[
                {
                    "id": "question-1",
                    "name": "ask_structured_question",
                    "arguments": followup.question_data.model_dump(mode="json"),
                }
            ],
        ),
    ]
    prepared = prepare_user_question_metadata(
        conversation=conversation,
        message="",
        question_answer={
            "kind": "delegated_question_answer",
            "question_id": "post_processing_goal",
        },
    )
    conversation.append(
        ConversationMessage(role="user", content="", metadata=prepared.metadata)
    )

    replayed = question_answer_from_metadata(prepared.metadata)
    assert replayed is not None
    assert replayed.selected_value == "summarize_or_overview"
    assert replayed.delegated is True

    settled = build_planning_state_from_conversation(conversation)
    slot = settled.resolved_slots["post_processing_goal"]
    assert slot.value == "summarize_or_overview"
    assert slot.source == "structured_answer"
    assert slot.is_commit_grade

    disclosure = build_requirements_disclosure(settled, ui_language="sv")
    assert "post_processing_goal" in {
        requirement.requirement_id for requirement in disclosure.resolved_requirements
    }
    assert render_summary_label("post_processing_goal", "sv") in {
        decision.topic for decision in disclosure.key_decisions
    }

    analysis = analyze_discovery(conversation, planning_state=settled)
    assert "post_processing_goal" not in {
        issue.suggestion.question_id
        for issue in analysis.issues
        if issue.suggestion is not None
    }


def test_mapped_file_limit_question_displays_current_policy_ceiling() -> None:
    planning_state = PlanningState.empty()
    planning_state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="documents",
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:primary_runtime_input"],
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_json",
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:terminal_output"],
        ),
        "document_material_scope": ResolvedSlot(
            name="document_material_scope",
            value="multiple_documents_case",
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:document_material_scope"],
        ),
    }
    draft = derive_architecture_commit_draft(planning_state)
    assert draft is not None
    planning_state.architecture_commit = finalize_architecture_commit(draft)
    planning_state.mapped_file_limit = MappedFileLimit(
        proposed_value=8,
        diagnostic="confirmation_required",
    )

    followup = build_registry_question_followup(
        "mapped_file_limit",
        [ConversationMessage(role="user", content="Process documents")],
        planning_state=planning_state,
    )

    assert followup is not None
    organization_option = next(
        option
        for option in followup.question_data.options
        if option.id == "organization_limit"
    )
    assert organization_option.label == "Use organization limit (8)"


def _make_turn(
    *,
    session_id=None,
    tenant_id=None,
    base_planning_state_version: int = 0,
) -> SessionSendTurn:
    return SessionSendTurn(
        session_id=session_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=base_planning_state_version,
    )


def _configure_turn_acceptance(repo: AsyncMock) -> None:
    async def accept_turn(**kwargs: object) -> SessionTurnClaim:
        acceptance = cast(SessionTurnAcceptance, kwargs["acceptance"])
        session = repo.get_session.return_value
        session.conversation = [*session.conversation, acceptance.user_message]
        return SessionTurnClaim(
            disposition=SessionTurnClaimDisposition.EXECUTE,
            user_message=acceptance.user_message,
            base_planning_state_version=session.planning_state_version,
        )

    repo.accept_session_turn.side_effect = accept_turn

    async def preflight_turn(**_: object) -> SessionTurnPreflight:
        session = repo.get_session.return_value
        return SessionTurnPreflight(
            session=session,
            baseline=SessionTurnPreparationBaseline(
                session_status=SessionStatus(session.status),
                latest_plan_id=None,
                planning_state_version=session.planning_state_version,
                latest_turn_id=None,
                latest_turn_state=None,
                attachment_file_ids=(),
            ),
        )

    repo.preflight_session_turn.side_effect = preflight_turn


def _resolved_slot(
    name: str,
    value: str,
    *,
    source: SlotSource = "model",
    confidence: SlotConfidence = "high",
) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source=source,
        confidence=confidence,
        evidence=["quote:test"],
        evidence_level="inferred" if source == "model" else None,
    )


class TestLowConfidenceDiscoveryGate:
    def test_low_confidence_question_still_fires_without_classifier_result(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Analyze file output report",
            )
        ]
        planning_state = PlanningState.empty()
        planning_state.resolved_slots["terminal_output"] = _resolved_slot(
            "terminal_output",
            "structured_text",
            confidence="medium",
        )

        with (
            patch(
                "eneo.flows.ai_builder.ai_builder_discovery._build_raw_discovery_issues",
                return_value=[],
            ),
            patch(
                "eneo.flows.ai_builder.ai_builder_discovery.score_conversation_signals",
                return_value=[
                    ScoredSignal(
                        question_id="terminal_output",
                        value="structured_text",
                        confidence="low",
                        source="freeform_text",
                    )
                ],
            ),
        ):
            analysis = analyze_discovery(conversation, planning_state=planning_state)

        assert "low_confidence_terminal_output" in {
            issue.issue_id for issue in analysis.issues
        }

    def test_classifier_resolved_slot_suppresses_low_confidence_question(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Analyze file output report",
            )
        ]
        planning_state = PlanningState.empty()
        planning_state.resolved_slots["terminal_output"] = _resolved_slot(
            "terminal_output",
            "structured_text",
            confidence="medium",
        )

        with (
            patch(
                "eneo.flows.ai_builder.ai_builder_discovery._build_raw_discovery_issues",
                return_value=[],
            ),
            patch(
                "eneo.flows.ai_builder.ai_builder_discovery.score_conversation_signals",
                return_value=[
                    ScoredSignal(
                        question_id="terminal_output",
                        value="structured_text",
                        confidence="low",
                        source="freeform_text",
                    )
                ],
            ),
        ):
            analysis = analyze_discovery(
                conversation,
                planning_state=planning_state,
                slot_classification_result=SlotClassificationResult(
                    slots=(
                        ClassifiedSlot(
                            slot_name="terminal_output",
                            value="structured_text",
                            confidence="medium",
                            reason="user asked for text output",
                            evidence=_classifier_evidence("output report"),
                        ),
                    )
                ),
            )

        assert "low_confidence_terminal_output" not in {
            issue.issue_id for issue in analysis.issues
        }

    @pytest.mark.parametrize(
        (
            "accepted_value",
            "accepted_source",
            "classifier_value",
            "expects_question",
        ),
        [
            pytest.param(
                "structured_text",
                "model",
                "structured_text",
                False,
                id="same_accepted_value",
            ),
            pytest.param(
                "structured_text",
                "requirements_summary",
                "pdf_document",
                True,
                id="rejected_different_value",
            ),
            pytest.param(
                "pdf_document",
                "structured_answer",
                "pdf_document",
                False,
                id="later_explicit_correction",
            ),
            pytest.param(
                None,
                None,
                "structured_text",
                True,
                id="missing_accepted_evidence",
            ),
        ],
    )
    def test_classifier_suppression_tracks_the_accepted_value(
        self,
        accepted_value: str | None,
        accepted_source: SlotSource | None,
        classifier_value: str,
        expects_question: bool,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Analyze file output report",
            )
        ]
        planning_state = PlanningState.empty()
        if accepted_value is not None:
            assert accepted_source is not None
            planning_state.resolved_slots["terminal_output"] = _resolved_slot(
                "terminal_output",
                accepted_value,
                source=accepted_source,
            )
        classifier_result = SlotClassificationResult(
            slots=(
                ClassifiedSlot(
                    slot_name="terminal_output",
                    value=classifier_value,
                    confidence="medium",
                    reason="user asked for this output",
                    evidence=_classifier_evidence("output report"),
                ),
            )
        )

        with (
            patch(
                "eneo.flows.ai_builder.ai_builder_discovery._build_raw_discovery_issues",
                return_value=[],
            ),
            patch(
                "eneo.flows.ai_builder.ai_builder_discovery.score_conversation_signals",
                return_value=[
                    ScoredSignal(
                        question_id="terminal_output",
                        value="structured_text",
                        confidence="low",
                        source="freeform_text",
                    )
                ],
            ),
        ):
            analyses = tuple(
                analyze_discovery(
                    conversation,
                    planning_state=planning_state,
                    slot_classification_result=classifier_result,
                )
                for _ in range(2)
            )

        question_presence = tuple(
            "low_confidence_terminal_output"
            in {issue.issue_id for issue in analysis.issues}
            for analysis in analyses
        )
        assert question_presence == (expects_question, expects_question)
        assert analyses[0] == analyses[1]


# ---------------------------------------------------------------------------
# requirements confirmation conversation scanning
# ---------------------------------------------------------------------------


class TestRequirementsConfirmation:
    """One disclosure, one version, one confirmation that names it."""

    def _disclosure_metadata(self) -> dict[str, object]:
        payload = RequirementsSummaryPayload(
            requirements_version="c0ffee" + "0" * 58,
            summary="A flow.",
            key_decisions=[KeyDecisionPayload(topic="Input", decision="PDF")],
            input_description="PDF upload",
            output_description="DOCX report",
            manual_setup_notes=[],
        )
        return {
            "requirements_summary": payload.model_dump(mode="json"),
            "requirements_version": payload.requirements_version,
        }

    def test_returns_false_for_empty_conversation(self) -> None:
        assert resolve_requirements_state([]).confirmed is False

    def test_returns_false_without_confirmation(self) -> None:
        conversation = [
            ConversationMessage(role="user", content="Build me a flow"),
            ConversationMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "ask_structured_question",
                        "arguments": {"question": "Which format?"},
                    }
                ],
            ),
            ConversationMessage(
                role="tool",
                content="Question presented.",
                tool_call_id="call_1",
            ),
        ]
        assert resolve_requirements_state(conversation).confirmed is False

    def test_returns_true_after_requirements_confirmed(self) -> None:
        metadata = self._disclosure_metadata()
        conversation = [
            ConversationMessage(
                role="assistant",
                content="Requirements presented to user.",
                metadata=metadata,
            ),
            ConversationMessage(
                role="user",
                content="",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": metadata["requirements_version"],
                },
            ),
        ]
        assert resolve_requirements_state(conversation).confirmed is True

    def test_returns_false_with_requirements_but_no_user_confirmation(self) -> None:
        conversation = [
            ConversationMessage(
                role="assistant",
                content="Requirements presented to user.",
                metadata=self._disclosure_metadata(),
            ),
        ]
        assert resolve_requirements_state(conversation).confirmed is False

    def test_returns_false_when_user_changes_requirements_after_confirmation(
        self,
    ) -> None:
        metadata = self._disclosure_metadata()
        conversation = [
            ConversationMessage(
                role="assistant",
                content="Requirements presented to user.",
                metadata=metadata,
            ),
            ConversationMessage(
                role="user",
                content="",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": metadata["requirements_version"],
                },
            ),
            ConversationMessage(
                role="user",
                content="Jag vill ändra till en PDF i taget.",
            ),
        ]
        assert resolve_requirements_state(conversation).confirmed is False


# ---------------------------------------------------------------------------
# Extended discovery
# ---------------------------------------------------------------------------


class TestExtendedClarificationHints:
    def test_generic_vague_prompt_yields_discovery_question(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="I want a flow that helps me process case material and produce a summary report",
            )
        ]

        analysis = analyze_discovery(conversation)
        assert analysis.ready_for_confirmation is False
        assert analysis.next_issue is not None
        assert analysis.next_issue.suggestion is not None

    def test_ultra_vague_summary_prompt_blocks_on_final_output_mode(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Bygg ett flöde som sammanfattar ett dokument.",
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "terminal_output"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "terminal_output"

    def test_conflicting_single_file_and_same_run_compare_resolved_by_answer(
        self,
    ) -> None:
        """Answering comparison_scope with same_run_compare clears the
        contradiction block. Other unresolved families (e.g. the final output
        format, which is still ambiguous here) can still block — the guarantee
        is only that the comparison-contradiction question no longer blocks.
        """
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "I want one PDF per run and the flow should always compare multiple "
                    "documents in the same run."
                ),
                metadata={
                    "question_answer": {
                        "question_id": "comparison_scope",
                        "selected_values": ["same_run_compare"],
                    }
                },
            )
        ]

        analysis = analyze_discovery(conversation)
        blocking_question_ids = {
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        }
        assert "comparison_scope_conflict" not in blocking_question_ids
        assert "comparison_scope" not in blocking_question_ids

    def test_conflicting_single_pdf_and_same_run_compare_blocks_confirmation_in_swedish(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill ladda upp en pdf per körning men flödet ska alltid jämföra "
                    "flera dokument i samma körning."
                ),
            )
        ]

        block_message = build_discovery_block_message(conversation)
        assert block_message is not None
        assert (
            "motsättning" in block_message.lower()
            or "jämförelse" in block_message.lower()
        )

    def test_conflict_and_generic_compare_do_not_duplicate_same_question(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "I want one PDF per run and the flow should always compare multiple "
                    "documents in the same run."
                ),
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]
        assert question_ids.count("comparison_scope") == 1

    def test_conflict_question_is_ranked_before_generic_scope_questions(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "I want one PDF per run and the flow should always compare multiple "
                    "documents in the same run and produce a summary report."
                ),
            )
        ]

        analysis = analyze_discovery(conversation)
        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "comparison_scope_conflict"

    def test_same_run_comparison_answer_clears_single_file_contradiction(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill ladda upp en pdf per körning men flödet ska alltid jämföra "
                    "flera dokument i samma körning."
                ),
            ),
            ConversationMessage(
                role="user",
                content="Flera dokument i samma körning",
                metadata={
                    "question_answer": {
                        "question_id": "comparison_scope",
                        "selected_option_ids": ["same_run_compare"],
                        "selected_values": ["same_run_compare"],
                    }
                },
            ),
        ]

        analysis = analyze_discovery(conversation)
        issue_ids = [issue.issue_id for issue in analysis.blocking_issues]

        assert "comparison_scope_conflict" not in issue_ids

    def test_same_run_comparison_answer_clears_contradiction_when_runtime_payload_uses_singular_fields(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill ladda upp en pdf per körning men flödet ska alltid jämföra "
                    "flera dokument i samma körning."
                ),
            ),
            ConversationMessage(
                role="user",
                content="Flera dokument i samma körning",
                metadata={
                    "question_answer": {
                        "question_id": "comparison_scope",
                        "selected_option_id": "same_run_compare",
                        "answer": "same_run_compare",
                    }
                },
            ),
        ]

        analysis = analyze_discovery(conversation)
        issue_ids = [issue.issue_id for issue in analysis.blocking_issues]

        assert "comparison_scope_conflict" not in issue_ids

    def test_freeform_multiple_upload_answer_clears_same_run_contradiction(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill ladda upp en pdf per körning men flödet ska alltid jämföra "
                    "flera dokument i samma körning."
                ),
            ),
            ConversationMessage(
                role="user",
                content="Låt användaren ladda upp flera PDF:er i samma körning.",
            ),
        ]

        analysis = analyze_discovery(conversation)
        issue_ids = [issue.issue_id for issue in analysis.blocking_issues]

        assert "comparison_scope_conflict" not in issue_ids
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]
        assert "comparison_scope" not in question_ids

    def test_rich_prompt_uses_full_question_budget_when_slots_remain(
        self,
    ) -> None:
        """Rich prompts with clear outcome intent do not ask a meta question."""
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde som heter Dokumentanalys Pro. "
                    "Flödet ska hjälpa en chef att förstå ett ärende. "
                    "Användaren ska kunna ladda upp underlag som PDF, ange referensnummer, "
                    "kort beskrivning, språk för rapporten och fokus för analysen. "
                    "Flödet ska analysera materialet och skapa en slutrapport."
                ),
            ),
            ConversationMessage(
                role="user",
                content="One case at a time",
                metadata={
                    "question_answer": {
                        "question_id": "processing_scope",
                        "selected_option_ids": ["single_case"],
                        "selected_values": ["single_case"],
                    }
                },
            ),
            ConversationMessage(
                role="user",
                content="Structured text output",
                metadata={
                    "question_answer": {
                        "question_id": "terminal_output",
                        "selected_option_ids": ["structured_text"],
                        "selected_values": ["structured_text"],
                    }
                },
            ),
        ]

        planning_state = build_planning_state_from_conversation(conversation)
        planning_state.resolved_slots["post_processing_goal"] = (
            _planning_state_with_post_processing_goal(
                "structure_key_information"
            ).resolved_slots["post_processing_goal"]
        )
        analysis = analyze_discovery(conversation, planning_state=planning_state)
        assert analysis.ready_for_confirmation

    def test_vague_case_analysis_prompt_is_resolved_after_full_answers(self) -> None:
        """After 5 explicit answers covering scope, input, output mode, and
        DOCX mode, the discovery analysis infers enough context that
        nice_to_have questions (output_reader, final_output_scope) are
        not generated as blocking issues.
        """
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "I want a flow that helps me process case material and "
                    "produce a summary report."
                ),
            ),
            ConversationMessage(
                role="user",
                content="One case at a time",
                metadata={
                    "question_answer": {
                        "question_id": "processing_scope",
                        "selected_option_ids": ["single_case"],
                        "selected_values": ["single_case"],
                    }
                },
            ),
            ConversationMessage(
                role="user",
                content="Documents",
                metadata={
                    "question_answer": {
                        "question_id": "primary_runtime_input",
                        "selected_option_ids": ["documents"],
                        "selected_values": ["documents"],
                    }
                },
            ),
            ConversationMessage(
                role="user",
                content="DOCX document",
                metadata={
                    "question_answer": {
                        "question_id": "terminal_output",
                        "selected_option_ids": ["docx_document"],
                        "selected_values": ["docx_document"],
                    }
                },
            ),
            ConversationMessage(
                role="user",
                content="Generated DOCX without template",
                metadata={
                    "question_answer": {
                        "question_id": "docx_output_mode",
                        "selected_option_ids": ["generated_docx"],
                        "selected_values": ["generated_docx"],
                    }
                },
            ),
        ]

        analysis = analyze_discovery(
            conversation,
            planning_state=_planning_state_with_post_processing_goal(
                "summarize_or_overview"
            ),
        )
        assert analysis.ready_for_confirmation

    def test_pdf_output_counts_as_explicit_output_choice(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill ladda upp flera pdf filer och skapa en ny pdf med detaljerna."
                ),
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]
        assert "terminal_output" not in question_ids

    def test_pdf_template_expectation_asks_pdf_generation_mode_before_docx_mode(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill transkribera samtal.",
            ),
            ConversationMessage(
                role="user",
                content="Ljudfil som primär indata",
                metadata={
                    "question_answer": {
                        "question_id": "flow_input_architecture",
                        "selected_option_id": "audio_primary_input",
                        "answer": "audio_primary_input",
                    }
                },
            ),
            ConversationMessage(
                role="user",
                content="PDF-dokument",
                metadata={
                    "question_answer": {
                        "question_id": "terminal_output",
                        "selected_option_id": "pdf_document",
                        "answer": "pdf_document",
                    }
                },
            ),
            ConversationMessage(
                role="user",
                content="Jag behöver att den följer en PDF-mall.",
            ),
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "pdf_generation_mode" in question_ids
        assert "docx_output_mode" not in question_ids
        assert analysis.next_issue is not None
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "pdf_generation_mode"

    def test_transcribe_conversation_with_pdf_output_does_not_trigger_mixed_input_question(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde som hjälper till att transkribera ett "
                    "medarbetarsamtal mellan en medarbetare och en chef. I slutet vill "
                    "jag ha sammanfattningen och vad vi kom fram till och viktiga detaljer "
                    "och vad vi ska uppfölja inför nästa år. Det räcker med en pdf fil."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "flow_input_architecture" not in question_ids
        assert "primary_runtime_input" not in question_ids

    def test_audio_report_prompt_with_keywords_does_not_reopen_input_or_output_questions(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill börja bygga ett flöde där jag kommer skicka in en ljudfil "
                    "som du ska transkribera sen ska du sammanfatta det och ge mig en "
                    "strukturerad rapport med dom viktigaste keywords och själva ämnet. "
                    "Vilka namn som förekommer och om det förekommer ett datum och själva "
                    "ämnet av samtalet också."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "flow_input_architecture" not in question_ids
        assert "terminal_output" not in question_ids

    def test_swedish_audio_prompt_assumes_no_runtime_metadata_before_confirmation(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde där jag ska skicka in en ljudfil "
                    "som ska transkriberas. Jag vill ha en Word-fil i slutet."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(
            conversation,
            planning_state=_planning_state_with_post_processing_goal(
                "stop_after_primary_operation"
            ),
        )
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert analysis.ready_for_confirmation is True
        assert analysis.next_issue is None
        assert "runtime_metadata_fields" not in question_ids
        assert (
            "Antar tills vidare att inga extra formulärfält behövs vid körning; "
            "du kan lägga till dem innan du bekräftar."
        ) in analysis.assumptions
        assert "primary_runtime_input" not in question_ids
        assert "flow_input_architecture" not in question_ids
        assert "terminal_output" not in question_ids
        assert "docx_output_mode" not in question_ids

    def test_template_file_role_requires_docx_mode_when_generated_docx_is_defaulted(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde där jag ska skicka in en ljudfil "
                    "som ska transkriberas. Jag vill ha en Word-fil i slutet."
                ),
                metadata={"ui_language": "sv"},
            )
        ]
        planning_state = build_planning_state_from_conversation(conversation)
        docx_mode_slot = planning_state.resolved_slots["docx_output_mode"]
        assert docx_mode_slot.value == "generated_docx"
        assert docx_mode_slot.source == "policy_default"
        planning_state.file_roles = [
            FileRoleEvidence(
                file_id="00000000-0000-0000-0000-000000000701",
                filename="beslutsmall.docx",
                file_type="document",
                mimetype=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml."
                    "document"
                ),
                has_readable_text=True,
                coverage="fully_seen",
                role="template",
                source="heuristic",
                confidence="medium",
            )
        ]

        analysis = analyze_discovery(conversation, planning_state=planning_state)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "docx_output_mode" in question_ids
        assert analysis.ready_for_confirmation is False

    def test_conflicting_template_reference_role_still_requires_docx_mode_choice(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde där jag ska skicka in en ljudfil "
                    "som ska transkriberas. Jag vill ha en Word-fil i slutet."
                ),
                metadata={"ui_language": "sv"},
            )
        ]
        planning_state = build_planning_state_from_conversation(conversation)
        planning_state.file_roles = [
            FileRoleEvidence(
                file_id="00000000-0000-0000-0000-000000000701",
                filename="lagmall.docx",
                file_type="document",
                mimetype=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml."
                    "document"
                ),
                has_readable_text=True,
                coverage="fully_seen",
                role="template",
                source="heuristic",
                confidence="medium",
                evidence=["filename:template_keyword", "content:reference_keyword"],
                candidate_roles=["template", "reference_material"],
            )
        ]

        analysis = analyze_discovery(conversation, planning_state=planning_state)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "docx_output_mode" in question_ids
        assert analysis.ready_for_confirmation is False

    def test_template_file_role_does_not_reask_after_explicit_generated_docx_choice(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="DOCX document",
                metadata={
                    "question_answer": {
                        "question_id": "terminal_output",
                        "selected_option_ids": ["docx_document"],
                        "selected_values": ["docx_document"],
                    },
                    "ui_language": "sv",
                },
            ),
            ConversationMessage(
                role="user",
                content="Generated DOCX without template",
                metadata={
                    "question_answer": {
                        "question_id": "docx_output_mode",
                        "selected_option_ids": ["generated_docx"],
                        "selected_values": ["generated_docx"],
                    },
                    "ui_language": "sv",
                },
            ),
        ]
        planning_state = build_planning_state_from_conversation(conversation)
        planning_state.file_roles = [
            FileRoleEvidence(
                file_id="00000000-0000-0000-0000-000000000702",
                filename="beslutsmall.docx",
                file_type="document",
                mimetype=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml."
                    "document"
                ),
                has_readable_text=True,
                coverage="fully_seen",
                role="template",
                source="heuristic",
                confidence="medium",
            )
        ]

        analysis = analyze_discovery(conversation, planning_state=planning_state)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "docx_output_mode" not in question_ids

    def test_audio_prompt_with_derived_underlag_does_not_trigger_mixed_input_question(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde där användaren spelar in eller laddar upp ett "
                    "kundsamtal. Innan körning ska användaren ange ticket_id, "
                    "kundnamn och önskad rapportton som inmatningsfält. Flödet ska "
                    "transkribera ljudet, extrahera beslut och åtgärder per "
                    "agendapunkt som separata JSON-underlag, skriva ett första "
                    "Word-utkast, kritisera utkastet och revidera det till en "
                    "slutgiltig Word-rapport. Rapportton ska styra utkast och "
                    "revision, men den ska inte ersätta källmaterialet."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "primary_runtime_input" not in question_ids
        assert "flow_input_architecture" not in question_ids
        assert "primary_runtime_input" not in question_ids

    def test_chosen_document_input_does_not_reask_from_stale_raw_conflict(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "I will upload an audio file and documents at runtime. "
                    "Transcribe the audio, analyze the documents, and return a report."
                ),
                metadata={"ui_language": "en"},
            )
        ]
        planning_state = PlanningState.empty()
        planning_state.resolved_slots = {
            "primary_runtime_input": _resolved_slot(
                "primary_runtime_input",
                "documents",
                source="structured_answer",
            ),
            "terminal_output": _resolved_slot(
                "terminal_output",
                "structured_text",
            ),
        }

        analysis = analyze_discovery(
            conversation,
            planning_state=planning_state,
        )
        question_ids = {
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        }

        assert "flow_input_architecture" not in question_ids
        assert "primary_runtime_input" not in question_ids
        assert "terminal_output" not in question_ids

    def test_model_guess_does_not_settle_two_runtime_materials(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "I will upload an audio file and documents at runtime. "
                    "Transcribe the audio, analyze the documents, and return a report."
                ),
                metadata={"ui_language": "en"},
            )
        ]
        planning_state = PlanningState.empty()
        planning_state.resolved_slots = {
            "primary_runtime_input": _resolved_slot(
                "primary_runtime_input",
                "audio",
            ),
        }

        analysis = analyze_discovery(
            conversation,
            planning_state=planning_state,
        )
        question_ids = {
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        }

        assert "flow_input_architecture" in question_ids

    def test_answered_architecture_survives_a_conflicting_model_guess(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "I will upload an audio file and documents at runtime. "
                    "Transcribe the audio, analyze the documents, and return a report."
                ),
                metadata={"ui_language": "en"},
            ),
            ConversationMessage(
                role="user",
                content="The recording",
                metadata={
                    "question_answer": {
                        "question_id": "flow_input_architecture",
                        "selected_values": ["audio_primary_input"],
                    }
                },
            ),
        ]
        planning_state = PlanningState.empty()
        planning_state.resolved_slots = {
            "primary_runtime_input": _resolved_slot(
                "primary_runtime_input",
                "documents",
            ),
        }

        analysis = analyze_discovery(
            conversation,
            planning_state=planning_state,
        )
        question_ids = {
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        }

        assert "flow_input_architecture" not in question_ids
        assert "primary_runtime_input" not in question_ids
        profile = build_discovery_profile(conversation, planning_state=planning_state)
        assert profile.input_intent.primary_runtime_input == "audio", (
            "the answered choice, not the model slot, decides the runtime material"
        )

    def test_unoffered_architecture_answer_does_not_settle_the_material(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "I will upload an audio file and documents at runtime. "
                    "Transcribe the audio, analyze the documents, and return a report."
                ),
                metadata={"ui_language": "en"},
            ),
            ConversationMessage(
                role="user",
                content="banana",
                metadata={
                    "question_answer": {
                        "question_id": "flow_input_architecture",
                        "selected_values": ["banana"],
                    }
                },
            ),
        ]

        analysis = analyze_discovery(conversation)
        question_ids = {
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        }

        assert "flow_input_architecture" in question_ids

    def test_audio_edit_with_derived_underlag_does_not_trigger_mixed_input_question(
        self,
    ) -> None:
        flow = Flow(
            id=uuid4(),
            tenant_id=uuid4(),
            space_id=uuid4(),
            name="Samtalsrapport",
            description="Transkriberar samtal och skriver rapport.",
            steps=[
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=1,
                    user_description="Transkribera samtal",
                    input_source="flow_input",
                    input_type="audio",
                    output_mode="transcribe_only",
                    output_type="text",
                ),
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=2,
                    user_description="Skriv rapport",
                    input_source="previous_step",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="docx",
                ),
            ],
        )
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Behåll ljudflödet men lägg till fyra JSON-underlag per "
                    "agendapunkt innan Word-rapporten skrivs."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation, flow=flow)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "primary_runtime_input" not in question_ids
        assert "flow_input_architecture" not in question_ids

    def test_edit_flow_uses_existing_flow_defaults_before_reasking_output_or_metadata(
        self,
    ) -> None:
        flow = Flow(
            id=uuid4(),
            tenant_id=uuid4(),
            space_id=uuid4(),
            name="Analys av Bora Hocas marknadskommentarer",
            description="Befintligt ljudflöde",
            metadata_json={
                "form_schema": {
                    "fields": [
                        {
                            "name": "Rapportspråk",
                            "type": "text",
                            "label": "Rapportspråk",
                            "required": True,
                        }
                    ]
                }
            },
            steps=[
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=1,
                    user_description="Transkribera ljud",
                    input_source="flow_input",
                    input_type="audio",
                    output_mode="transcribe_only",
                    output_type="text",
                ),
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=2,
                    user_description="Skriv slutrapport",
                    input_source="previous_step",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="text",
                ),
            ],
        )
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Behåll samma flöde men gör slutrapporten på engelska och lägg till "
                    "makrotrender och geopolitiska signaler."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation, flow=flow)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "terminal_output" not in question_ids
        assert "runtime_metadata_fields" not in question_ids
        assert "output_reader" not in question_ids
        assert "final_output_scope" not in question_ids

    def test_edit_flow_blocks_on_mixed_audio_and_document_input_architecture(
        self,
    ) -> None:
        flow = Flow(
            id=uuid4(),
            tenant_id=uuid4(),
            space_id=uuid4(),
            name="Dokumentanalys",
            description="Befintligt dokumentflöde",
            steps=[
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=1,
                    user_description="Analysera dokument",
                    input_source="flow_input",
                    input_type="document",
                    output_mode="pass_through",
                    output_type="json",
                ),
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=2,
                    user_description="Skriv rapport",
                    input_source="previous_step",
                    input_type="json",
                    output_mode="pass_through",
                    output_type="pdf",
                ),
            ],
        )
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Behåll samma flöde men lägg till ljudfiler och transkribera samtalet först, "
                    "och skicka sedan in dokument som vanligt. Jag vill fortfarande ha PDF ut."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation, flow=flow)
        next_issue = analysis.next_issue

        assert next_issue is not None
        assert next_issue.issue_id == "flow_input_architecture"
        assert next_issue.suggestion is not None
        assert next_issue.suggestion.question_id == "flow_input_architecture"

    def test_specific_uploaded_pdf_text_summary_prompt_skips_pdf_type(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett enkelt flöde som tar ett uppladdat PDF-dokument och returnerar en kort textsammanfattning på svenska."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "final_pdf_type" not in question_ids

    def test_swedish_uploaded_pdf_prompt_resolves_runtime_document_input(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Skapa ett flöde som tar emot uppladdade PDF-filer, analyserar "
                    "innehållet och sammanfattar risker, beslutspunkter och nästa steg."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(
            conversation,
            planning_state=_planning_state_with_post_processing_goal("action_followup"),
        )
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "primary_runtime_input" not in question_ids
        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "terminal_output"

    def test_generic_uploaded_pdf_docx_prompt_assumes_no_runtime_metadata(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en DOCX-rapport."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        planning_state = build_planning_state_from_conversation(conversation)
        planning_state.resolved_slots["post_processing_goal"] = (
            _planning_state_with_post_processing_goal(
                "structure_key_information"
            ).resolved_slots["post_processing_goal"]
        )
        analysis = analyze_discovery(conversation, planning_state=planning_state)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert analysis.next_issue is None
        assert "runtime_metadata_fields" not in question_ids
        assert (
            "Antar tills vidare att inga extra formulärfält behövs vid körning; "
            "du kan lägga till dem innan du bekräftar."
        ) in analysis.assumptions
        assert "docx_output_mode" not in question_ids

    def test_audio_docx_extraction_assumes_no_runtime_metadata_without_structured_analysis_slot(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Create a flow that transcribes meeting audio, extracts ten "
                    "topic sections, and produces a DOCX meeting report."
                ),
                metadata={"ui_language": "en"},
            )
        ]

        state = _planning_state_with_post_processing_goal("extract_key_information")
        analysis = analyze_discovery(conversation, planning_state=state)

        assert analysis.next_issue is None
        assert (
            "Assuming no extra form fields are needed at runtime for now; "
            "you can add them before confirming."
        ) in analysis.assumptions
        assert state.resolved_slots["post_processing_goal"].value == (
            "extract_key_information"
        )
        assert "structured_analysis_need" not in state.resolved_slots

    def test_structured_analysis_plain_text_optout_wins_for_audio_docx_extraction(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Create a flow that transcribes meeting audio, extracts ten "
                    "topic sections, and produces a DOCX meeting report, but keep "
                    "the analysis as plain text."
                ),
                metadata={"ui_language": "en"},
            )
        ]

        analysis = analyze_discovery(conversation)

        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]
        assert "structured_analysis_need" not in question_ids

    def test_simple_audio_docx_transcript_does_not_force_structured_analysis_question(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Create a flow that transcribes meeting audio and produces "
                    "a DOCX file with the transcription."
                ),
                metadata={"ui_language": "en"},
            )
        ]

        analysis = analyze_discovery(conversation)

        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]
        assert "structured_analysis_need" not in question_ids

    def test_bare_transcription_prompt_asks_output_question(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill ha ett transkriberingsflöde.",
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "terminal_output"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "terminal_output"

    def test_bare_transcription_prompt_asks_outcome_after_output_answer(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill ha ett transkriberingsflöde.",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="Strukturerat textresultat",
                metadata={
                    "question_answer": {
                        "question_id": "terminal_output",
                        "selected_values": ["structured_text"],
                    },
                    "ui_language": "sv",
                },
            ),
        ]

        analysis = analyze_discovery(conversation)

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "post_processing_goal"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "post_processing_goal"

    @pytest.mark.parametrize(
        "prompt",
        [
            "Jag vill ha ett OCR-flöde.",
            "Jag vill ha ett sammanfattningsflöde.",
            "Jag vill ha ett jämförelseflöde.",
        ],
    )
    def test_bare_workflow_prompt_with_unknown_input_asks_input_question(
        self,
        prompt: str,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=prompt,
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "primary_runtime_input"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "primary_runtime_input"

    def test_detailed_task_spec_with_unknown_input_still_asks_input_question(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som först sammanfattar materialet, sedan "
                    "identifierar beslut, risker, öppna frågor, rekommendationer "
                    "och nästa steg, och till sist skapar en tydlig DOCX-rapport "
                    "med rubriker för sammanfattning, viktiga punkter, beslut, "
                    "åtgärder, risker och frågor. Rapporten ska vara saklig, "
                    "professionell och enkel att skicka vidare till ledningen."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "primary_runtime_input"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "primary_runtime_input"

    def test_pure_information_question_does_not_trigger_workflow_fallback(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Vad betyder transcribe_only?",
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)

        assert analysis.next_issue is None
        assert analysis.selected_question_ids == ()

    @pytest.mark.parametrize(
        ("case_id", "primary_runtime_input", "classified_goal"),
        [
            (
                "interview_open_citizen_feedback",
                "text",
                ("unknown", "high", "user_explicit_uncertain"),
            ),
            # Ordinary semantic ambiguity: the classifier contract returns
            # unknown with LOW confidence — the common vague-interview shape.
            (
                "interview_open_citizen_feedback",
                "text",
                ("unknown", "low", "The goal is ambiguous between options."),
            ),
            # A low-confidence guessed value is equally unresolved.
            (
                "interview_open_special_diet",
                "text",
                ("summarize_or_overview", "low", "Weakly implied by phrasing."),
            ),
            ("interview_open_special_diet", "text", None),
        ],
    )
    def test_interview_open_cohort_asks_purpose_first_from_typed_classifier(
        self,
        case_id: str,
        primary_runtime_input: str,
        classified_goal: tuple[str, str, str] | None,
    ) -> None:
        prompt = _battle_case_prompt(case_id)
        conversation = [
            ConversationMessage(
                message_id="test-source",
                role="user",
                content=prompt,
                metadata={"ui_language": "sv"},
            )
        ]
        planning_state = PlanningState.empty()
        planning_state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
            name="primary_runtime_input",
            value=primary_runtime_input,
            source="model",
            confidence="high",
            evidence=[f"quote:user_message:test-source:{prompt}"],
            evidence_level="explicit",
        )
        classified_slots = [
            ClassifiedSlot(
                slot_name="primary_runtime_input",
                value=primary_runtime_input,
                confidence="high",
                reason="The runtime input is explicit.",
                evidence=_classifier_evidence(prompt),
                evidence_level="explicit",
            )
        ]
        if classified_goal is not None:
            goal_value, goal_confidence, goal_reason = classified_goal
            classified_slots.append(
                ClassifiedSlot(
                    slot_name="post_processing_goal",
                    value=goal_value,
                    confidence=goal_confidence,
                    reason=goal_reason,
                    evidence=_classifier_evidence(prompt),
                    evidence_level="inferred",
                )
            )

        analysis = analyze_discovery(
            conversation,
            planning_state=planning_state,
            slot_classification_result=SlotClassificationResult(
                slots=tuple(classified_slots)
            ),
        )

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "post_processing_goal"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "post_processing_goal"

    def test_guessed_purpose_is_asked_before_terminal_output(self) -> None:
        # A medium-confidence inferred purpose is below commit grade, so the
        # architecture layer and the result contract refuse to read it.
        # Discovery must ask for it rather than spend the turn on an output
        # format for a purpose nobody has confirmed.
        prompt = _battle_case_prompt("interview_open_accessibility_reports")
        conversation = _open_interview_conversation(prompt)
        state, classification = _classified_open_interview(
            prompt,
            goal_confidence="medium",
            goal_evidence_level="inferred",
        )

        assert state.commit_grade_slot_value("primary_runtime_input") == "text"
        assert state.commit_grade_slot_value("post_processing_goal") is None

        profile = build_discovery_profile(conversation, planning_state=state)
        assert (
            post_processing_goal_is_vague(
                profile,
                slot_classification_result=classification,
            )
            is True
        )

        analysis = analyze_discovery(
            conversation,
            planning_state=state,
            slot_classification_result=classification,
        )
        policy = build_planner_action_policy(
            session_state=state,
            selected_discovery_question_ids=analysis.selected_question_ids,
        )

        assert policy.allowed_ask_question_targets[0] == "post_processing_goal"

    def test_committed_purpose_keeps_terminal_output_first(self) -> None:
        prompt = _battle_case_prompt("interview_open_accessibility_reports")
        conversation = _open_interview_conversation(prompt)
        state, classification = _classified_open_interview(
            prompt,
            goal_confidence="high",
            goal_evidence_level="explicit",
        )

        assert (
            state.commit_grade_slot_value("post_processing_goal")
            == "structure_key_information"
        )

        profile = build_discovery_profile(conversation, planning_state=state)
        assert (
            post_processing_goal_is_vague(
                profile,
                slot_classification_result=classification,
            )
            is False
        )

        analysis = analyze_discovery(
            conversation,
            planning_state=state,
            slot_classification_result=classification,
        )
        policy = build_planner_action_policy(
            session_state=state,
            selected_discovery_question_ids=analysis.selected_question_ids,
        )

        assert policy.allowed_ask_question_targets[0] == "terminal_output"

    def test_guessed_terminal_output_does_not_close_the_output_question(self) -> None:
        # A guessed terminal output is not an answer either: it must not
        # displace the purpose question, and the output question it guessed
        # at stays open.
        prompt = _battle_case_prompt("interview_open_accessibility_reports")
        conversation = _open_interview_conversation(prompt)
        state, classification = _classified_open_interview(
            prompt,
            goal_confidence="medium",
            goal_evidence_level="inferred",
            terminal_output=("structured_text", "medium"),
        )

        assert state.resolved_slots["terminal_output"].value == "structured_text"
        assert state.commit_grade_slot_value("terminal_output") is None

        analysis = analyze_discovery(
            conversation,
            planning_state=state,
            slot_classification_result=classification,
        )
        policy = build_planner_action_policy(
            session_state=state,
            selected_discovery_question_ids=analysis.selected_question_ids,
        )

        assert policy.allowed_ask_question_targets[0] == "post_processing_goal"
        assert "terminal_output" in policy.allowed_ask_question_targets

    def test_classification_without_readable_slots_does_not_ask_purpose(self) -> None:
        # The classifier read the turn but placed nothing: every slot came
        # back unknown and none of them was the purpose. That is too early to
        # spend the purpose question on, so discovery stays quiet about it.
        prompt = _battle_case_prompt("interview_open_accessibility_reports")
        conversation = _open_interview_conversation(prompt)
        classification = SlotClassificationResult(
            slots=(
                ClassifiedSlot(
                    slot_name="primary_runtime_input",
                    value=UNKNOWN_SLOT_VALUE,
                    confidence="high",
                    reason="user_explicit_uncertain",
                    evidence=_classifier_evidence(prompt),
                    evidence_level="explicit",
                ),
            )
        )
        state = PlanningState.empty()
        merge_llm_resolved_slots(
            state,
            classification,
            prompt_hash="test-prompt-hash",
            freeform_text=prompt,
        )

        assert state.resolved_slots == {}

        profile = build_discovery_profile(conversation, planning_state=state)
        assert (
            post_processing_goal_is_vague(
                profile,
                slot_classification_result=classification,
            )
            is False
        )

        analysis = analyze_discovery(
            conversation,
            planning_state=state,
            slot_classification_result=classification,
        )

        assert "post_processing_goal" not in analysis.selected_question_ids

    def test_interview_input_cohort_keeps_input_first(self) -> None:
        case_id = "interview_input_building_supplement"
        prompt = _battle_case_prompt(case_id)
        conversation = [
            ConversationMessage(
                message_id="test-source",
                role="user",
                content=prompt,
                metadata={"ui_language": "sv"},
            )
        ]
        planning_state = _planning_state_with_post_processing_goal(
            "extract_key_information"
        )
        planning_state.resolved_slots["terminal_output"] = ResolvedSlot(
            name="terminal_output",
            value="structured_json",
            source="model",
            confidence="high",
            evidence=[f"quote:user_message:test-source:{prompt}"],
            evidence_level="explicit",
        )
        classification_result = SlotClassificationResult(
            slots=(
                ClassifiedSlot(
                    slot_name="primary_runtime_input",
                    value="unknown",
                    confidence="high",
                    reason="user_explicit_uncertain",
                    evidence=_classifier_evidence(prompt),
                    evidence_level="explicit",
                ),
                ClassifiedSlot(
                    slot_name="post_processing_goal",
                    value="extract_key_information",
                    confidence="high",
                    reason="The requested extraction outcome is explicit.",
                    evidence=_classifier_evidence(prompt),
                    evidence_level="explicit",
                ),
                ClassifiedSlot(
                    slot_name="terminal_output",
                    value="structured_json",
                    confidence="high",
                    reason="The JSON result is explicit.",
                    evidence=_classifier_evidence(prompt),
                    evidence_level="explicit",
                ),
            )
        )

        analysis = analyze_discovery(
            conversation,
            planning_state=planning_state,
            slot_classification_result=classification_result,
        )

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "primary_runtime_input"
        assert "post_processing_goal" not in {
            issue.issue_id for issue in analysis.issues
        }

    def test_resolved_post_processing_goal_slot_suppresses_outcome_question(
        self,
    ) -> None:
        prompt = _battle_case_prompt("interview_open_meeting_audio")
        conversation = [
            ConversationMessage(
                role="user",
                content=prompt,
                metadata={"ui_language": "sv"},
            )
        ]
        planning_state = PlanningState.empty()
        planning_state.resolved_slots["post_processing_goal"] = ResolvedSlot(
            name="post_processing_goal",
            value="summarize_or_overview",
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:post_processing_goal"],
        )

        analysis = analyze_discovery(
            conversation,
            planning_state=planning_state,
        )

        assert "post_processing_goal" not in {
            issue.issue_id for issue in analysis.issues
        }

    @pytest.mark.asyncio
    async def test_vague_transcription_asks_output_or_outcome_before_confirmation(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                message_id="test-source",
                role="user",
                content="Jag vill ha ett transkriberingsflöde.",
                metadata={"ui_language": "sv"},
            )
        ]

        async def fake_classify_slots(**kwargs: Any) -> SlotClassificationAttempt:
            result = SlotClassificationResult(
                slots=(
                    ClassifiedSlot(
                        slot_name="post_processing_goal",
                        value="summarize_or_overview",
                        confidence="high",
                        reason="The model guessed a transcript summary.",
                        evidence=_classifier_evidence("transkriberingsflöde"),
                    ),
                )
            )
            return SlotClassificationAttempt(outcome="resolved", result=result)

        with patch(
            "eneo.flows.ai_builder.ai_builder_discovery_runtime.classify_slots",
            side_effect=fake_classify_slots,
        ):
            context = await build_runtime_discovery_context(
                conversation,
                litellm_client=object(),
                completion_model_route=ResolvedCompletionModelRoute(
                    litellm_model="test-model",
                    provider_type="openai",
                    litellm_kwargs={},
                    supported_model_kwargs=SupportedModelKwargs(),
                ),
                tenant_id=uuid4(),
                max_input_tokens=100_000,
                max_output_tokens=2_000,
            )

        analysis = analyze_discovery(
            conversation,
            planning_state=context.planning_state,
            slot_classification_result=context.slot_classification_result,
        )

        assert analysis.ready_for_confirmation is False
        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id in {
            "terminal_output",
            "post_processing_goal",
        }
        assert analysis.selected_question_ids[0] in {
            "terminal_output",
            "post_processing_goal",
        }

    def test_exact_json_flow_does_not_ask_post_processing_goal(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde där användaren klistrar in en JSON payload "
                    "och får tillbaka strikt JSON enligt det här schemat: "
                    "{name: string, amount: number, deadline: string}. "
                    "Returnera bara giltig JSON."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)

        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]
        assert "post_processing_goal" not in question_ids

    def test_json_in_out_without_rules_asks_structured_payload_contract(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde som tar emot JSON och returnerar JSON."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "structured_io_contract"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "structured_io_contract"
        assert "input-JSON" in analysis.next_issue.suggestion.question

    def test_exact_json_schema_prompt_skips_human_document_purpose_question(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde där användaren klistrar in en JSON payload "
                    "och får tillbaka strikt JSON enligt det här schemat: "
                    "{name: string, amount: number, deadline: string}. "
                    "Returnera bara giltig JSON."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)

        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]
        assert "post_processing_goal" not in question_ids
        assert "structured_io_contract" not in question_ids

    def test_pdf_template_mode_question_suppresses_outcome_question(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill skapa en PDF från en mall.",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="PDF-dokument",
                metadata={
                    "question_answer": {
                        "question_id": "terminal_output",
                        "selected_values": ["pdf_document"],
                    },
                    "ui_language": "sv",
                },
            ),
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "pdf_generation_mode" in question_ids
        assert "post_processing_goal" not in question_ids

    def test_spent_question_budget_keeps_unresolved_outcome_question(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill bygga ett flöde som analyserar dokument.",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="Ett dokument åt gången",
                metadata={
                    "question_answer": {
                        "question_id": "processing_scope",
                        "selected_values": ["single_case"],
                    },
                    "ui_language": "sv",
                },
            ),
            ConversationMessage(
                role="user",
                content="Dokument",
                metadata={
                    "question_answer": {
                        "question_id": "primary_runtime_input",
                        "selected_values": ["documents"],
                    },
                    "ui_language": "sv",
                },
            ),
            ConversationMessage(
                role="user",
                content="Flera relaterade dokument för samma ärende",
                metadata={
                    "question_answer": {
                        "question_id": "document_material_scope",
                        "selected_values": ["multiple_documents_case"],
                    },
                    "ui_language": "sv",
                },
            ),
            ConversationMessage(
                role="user",
                content="Grundläggande metadata",
                metadata={
                    "question_answer": {
                        "question_id": "runtime_metadata_fields",
                        "selected_values": ["basic_runtime_metadata"],
                    },
                    "ui_language": "sv",
                },
            ),
            ConversationMessage(
                role="user",
                content="DOCX utan mall",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_format",
                        "selected_values": ["docx_generated"],
                    },
                    "ui_language": "sv",
                },
            ),
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert question_ids == ["post_processing_goal"]

    def test_rejected_scope_does_not_hide_comparison_architecture_question(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Build the plan for a flow that compares official material "
                    "against an internal policy and creates a DOCX report."
                ),
                metadata={"ui_language": "en"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "comparison_scope" in question_ids

    def test_structured_analysis_answer_resolves_audio_docx_extraction_question(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Create a flow that transcribes meeting audio, extracts ten "
                    "topic sections, and produces a DOCX meeting report."
                ),
                metadata={"ui_language": "en"},
            ),
            ConversationMessage(
                role="user",
                content="Use structured analysis.",
                metadata={
                    "question_answer": {
                        "question_id": "structured_analysis_need",
                        "selected_option_id": "use_structured_analysis",
                        "selected_values": ["use_structured_analysis"],
                        "answer": "use_structured_analysis",
                    },
                    "ui_language": "en",
                },
            ),
        ]

        analysis = analyze_discovery(conversation)

        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]
        assert "structured_analysis_need" not in question_ids

    @pytest.mark.asyncio
    async def test_classifier_text_only_does_not_override_audio_docx_extraction_intent(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                message_id="test-source",
                role="user",
                content=(
                    "Create a flow that transcribes meeting audio, extracts ten "
                    "topic sections, and produces a DOCX meeting report."
                ),
                metadata={"ui_language": "en"},
            )
        ]
        captured_allowed_values: dict[str, object] = {}

        async def fake_classify_slots(**kwargs: Any) -> SlotClassificationAttempt:
            captured_allowed_values.update(kwargs["allowed_slot_values"])
            result = SlotClassificationResult(
                slots=(
                    ClassifiedSlot(
                        slot_name="runtime_metadata_fields",
                        value="no_runtime_metadata",
                        confidence="high",
                        reason="No separate runtime metadata requested.",
                        evidence=_classifier_evidence("summarize the uploaded policy"),
                    ),
                )
            )
            return SlotClassificationAttempt(outcome="resolved", result=result)

        with patch(
            "eneo.flows.ai_builder.ai_builder_discovery_runtime.classify_slots",
            side_effect=fake_classify_slots,
        ):
            context = await build_runtime_discovery_context(
                conversation,
                litellm_client=object(),
                completion_model_route=ResolvedCompletionModelRoute(
                    litellm_model="test-model",
                    provider_type="openai",
                    litellm_kwargs={},
                    supported_model_kwargs=SupportedModelKwargs(),
                ),
                tenant_id=uuid4(),
                max_input_tokens=100_000,
                max_output_tokens=2_000,
            )

        assert "structured_analysis_need" not in captured_allowed_values
        assert "runtime_metadata_fields" in captured_allowed_values
        assert "structured_analysis_need" not in context.planning_state.resolved_slots

    @pytest.mark.asyncio
    async def test_classifier_resolved_outcome_still_asks_input_for_unknown_input(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                message_id="test-source",
                role="user",
                content="Jag vill ha ett OCR-flöde.",
                metadata={"ui_language": "sv"},
            )
        ]

        async def fake_classify_slots(**kwargs: Any) -> SlotClassificationAttempt:
            result = SlotClassificationResult(
                slots=(
                    ClassifiedSlot(
                        slot_name="post_processing_goal",
                        value="extract_key_information",
                        confidence="high",
                        reason="OCR suggests extracting readable text.",
                        evidence=_classifier_evidence("OCR-flöde"),
                    ),
                    ClassifiedSlot(
                        slot_name="terminal_output",
                        value="structured_text",
                        confidence="high",
                        reason="OCR commonly returns text.",
                        evidence=_classifier_evidence("OCR-flöde"),
                    ),
                )
            )
            return SlotClassificationAttempt(outcome="resolved", result=result)

        with patch(
            "eneo.flows.ai_builder.ai_builder_discovery_runtime.classify_slots",
            side_effect=fake_classify_slots,
        ):
            context = await build_runtime_discovery_context(
                conversation,
                litellm_client=object(),
                completion_model_route=ResolvedCompletionModelRoute(
                    litellm_model="test-model",
                    provider_type="openai",
                    litellm_kwargs={},
                    supported_model_kwargs=SupportedModelKwargs(),
                ),
                tenant_id=uuid4(),
                max_input_tokens=100_000,
                max_output_tokens=2_000,
            )

        analysis = analyze_discovery(
            conversation,
            planning_state=context.planning_state,
            slot_classification_result=context.slot_classification_result,
        )

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "primary_runtime_input"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "primary_runtime_input"

    @pytest.mark.asyncio
    async def test_classifier_outcome_drives_discovery_without_raw_text_veto(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                message_id="test-source",
                role="user",
                content="Jag vill ha ett transkriberingsflöde.",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="PDF-dokument",
                metadata={
                    "question_answer": {
                        "question_id": "terminal_output",
                        "selected_values": ["pdf_document"],
                    },
                    "ui_language": "sv",
                },
            ),
        ]

        async def fake_classify_slots(**kwargs: Any) -> SlotClassificationAttempt:
            result = SlotClassificationResult(
                slots=(
                    ClassifiedSlot(
                        slot_name="post_processing_goal",
                        value="stop_after_primary_operation",
                        confidence="high",
                        reason="transcription flow",
                        evidence=_classifier_evidence("transkriberingsflöde"),
                    ),
                    ClassifiedSlot(
                        slot_name="structured_analysis_need",
                        value="text_only_analysis",
                        confidence="high",
                        reason="raw transcription",
                        evidence=_classifier_evidence("transkriberingsflöde"),
                    ),
                )
            )
            return SlotClassificationAttempt(outcome="resolved", result=result)

        with patch(
            "eneo.flows.ai_builder.ai_builder_discovery_runtime.classify_slots",
            side_effect=fake_classify_slots,
        ):
            context = await build_runtime_discovery_context(
                conversation,
                litellm_client=object(),
                completion_model_route=ResolvedCompletionModelRoute(
                    litellm_model="test-model",
                    provider_type="openai",
                    litellm_kwargs={},
                    supported_model_kwargs=SupportedModelKwargs(),
                ),
                tenant_id=uuid4(),
                max_input_tokens=100_000,
                max_output_tokens=2_000,
            )

        goal = context.planning_state.resolved_slots["post_processing_goal"]
        assert goal.value == "stop_after_primary_operation"
        assert goal.source == "model"
        assert "structured_analysis_need" not in context.planning_state.resolved_slots

        analysis = analyze_discovery(
            conversation,
            planning_state=context.planning_state,
            slot_classification_result=context.slot_classification_result,
        )

        assert "post_processing_goal" not in {
            issue.issue_id for issue in analysis.issues
        }

    def test_complex_multi_document_compare_prompt_avoids_redundant_questions(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som tar ett dokumentpaket med flera relaterade PDF:er i samma ärende, "
                    "jämför uppgifterna mellan dokumenten, extraherar strukturerad JSON med avvikelser, risker "
                    "och rekommenderade åtgärder, och genererar en DOCX-rapport."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "runtime_metadata_fields" not in question_ids
        assert "document_material_scope" not in question_ids
        assert "comparison_scope" not in question_ids

    def test_multi_source_contradiction_prompt_skips_comparison_scope(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Användaren laddar upp 2-5 underlagsfiler. Flödet ska "
                    "extrahera nyckelfakta som strukturerad JSON från varje fil "
                    "eller från varje dokumentdel, sedan identifiera motsägelser "
                    "mellan källorna i ett separat analyssteg."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "comparison_scope" not in question_ids

    def test_ambiguous_compare_prompt_prioritizes_comparison_scope(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som jämför flera dokument och genererar en DOCX-rapport."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(
            conversation,
            planning_state=_planning_state_with_post_processing_goal(
                "compare_or_validate"
            ),
        )

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "comparison_scope"

    def test_comparison_against_internal_policy_asks_reference_source(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som jämför ett uppladdat avtal mot vår interna "
                    "policy och skriver en kort rapport."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(
            conversation,
            planning_state=_planning_state_with_post_processing_goal(
                "compare_or_validate"
            ),
        )

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "comparison_scope"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "comparison_scope"

    def test_comparison_with_two_runtime_documents_does_not_ask_reference_source(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde där användaren laddar upp flera dokument i "
                    "samma körning och jämför dem direkt i en strukturerad rapport."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "comparison_scope" not in question_ids

    def test_build_intent_does_not_suppress_reference_source_question(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg planen för ett flöde som jämför uppladdade avtal mot "
                    "vår interna policy och returnerar en DOCX-rapport."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(
            conversation,
            planning_state=_planning_state_with_post_processing_goal(
                "compare_or_validate"
            ),
        )

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "comparison_scope"

    def test_explicit_english_text_output_does_not_reopen_final_output_mode(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="I want a flow that summarizes uploaded news articles as a text summary.",
                metadata={"ui_language": "en"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "terminal_output" not in question_ids

    def test_swedish_short_summary_output_does_not_reopen_final_output_mode(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill kunna ladda upp ett dokument och få en kort sammanfattning.",
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "terminal_output" not in question_ids

    @pytest.mark.parametrize(
        "prompt",
        [
            "Jag vill kombinera API-data från olika dokument.",
            "Anropa en intern API-katalog för referens.",
            "Skicka resultatet till mig.",
        ],
    )
    def test_external_delivery_followup_does_not_fire_for_near_misses(
        self,
        prompt: str,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=prompt,
                metadata={"ui_language": "sv"},
            )
        ]

        issues = analyze_discovery(conversation).issues

        assert {issue.issue_id for issue in issues}.isdisjoint(
            {"external_delivery_unsupported"}
        )

    def test_uploaded_word_template_fill_output_does_not_reask_output_mode(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Fyll i en uppladdad Word-mall som innehåller {{platshållare}}. "
                    "Användaren laddar upp ett underlagsdokument och fyller i "
                    "inmatningsfälten referens_id och ansvarig innan körning. "
                    "Steg 1 ska extrahera strukturerad JSON ur underlaget. "
                    "Steg 2 ska kombinera den extraherade JSON:en med referens_id "
                    "och ansvarig till en sammanställning som matchar mallens "
                    "platshållare. Steg 3 ska fylla mallen från sammanställningen."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "terminal_output" not in question_ids
        assert "docx_output_mode" not in question_ids

    def test_word_input_form_fields_do_not_resolve_as_template_fill_output(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Användaren laddar upp ett Word-dokument och fyll i "
                    "inmatningsfält. Sammanfatta innehållet."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "docx_output_mode" not in question_ids
        assert "terminal_output" in question_ids

    def test_text_answer_flow_does_not_reopen_final_output_mode(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Skapa ett enkelt textflöde som skriver ett kort svar på en "
                    "inkommande fråga, låter ett separat kritiksteg kontrollera "
                    "tydlighet och saklighet, och skriver en slutversion som "
                    "använder kritiken. Inga filer och inga inmatningsfält behövs."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "terminal_output" not in question_ids

    def test_edit_prompt_short_summary_output_does_not_reopen_final_output_mode(
        self,
    ) -> None:
        flow = Flow(
            id=uuid4(),
            tenant_id=uuid4(),
            space_id=uuid4(),
            name="Dokumentflöde",
            description="Befintligt dokumentflöde",
            steps=[
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=1,
                    user_description="Analysera dokument",
                    input_source="flow_input",
                    input_type="document",
                    output_mode="pass_through",
                    output_type="text",
                )
            ],
        )
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Behåll dokumentuppladdningen men ändra slutresultatet så att "
                    "användaren får en kort sammanfattning."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation, flow=flow)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "terminal_output" not in question_ids

    def test_edit_prompt_word_template_fill_output_does_not_reask_docx_mode(
        self,
    ) -> None:
        flow = Flow(
            id=uuid4(),
            tenant_id=uuid4(),
            space_id=uuid4(),
            name="Dokumentflöde",
            description="Befintligt dokumentflöde",
            steps=[
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=1,
                    user_description="Analysera dokument",
                    input_source="flow_input",
                    input_type="document",
                    output_mode="pass_through",
                    output_type="text",
                )
            ],
        )
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Behåll dokumentunderlaget men ändra slutresultatet till att "
                    "fylla i en uppladdad Word-mall. Steget ska fylla mallen från "
                    "den strukturerade sammanställningen."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation, flow=flow)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "terminal_output" not in question_ids
        assert "docx_output_mode" not in question_ids

    def test_contract_heavy_prompt_infers_output_from_detailed_description(
        self,
    ) -> None:
        """A 45-word prompt describing contract analysis with extraction of
        specific fields and structured data implies structured text output.
        The auto-inference resolves final_output_mode so it is not raised as
        a blocking issue. Medium complexity budget also suppresses high_value
        questions.
        """
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde som analyserar leverantörsavtal i PDF, "
                    "extraherar leverantörsnamn, avtalsperiod, uppsägningsvillkor, kommersiella risker, "
                    "ekonomiska risker, operativa risker och rekommenderad nästa åtgärd. "
                    "Användaren ska också kunna ange intern referens, prioritet och ansvarig avdelning. "
                    "Jag vill att strukturerad data används där det förbättrar kvaliteten."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "terminal_output" not in question_ids

    def test_contract_flow_freeform_case_scope_resolves_document_material_scope(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde som analyserar leverantörsavtal i PDF, "
                    "extraherar leverantörsnamn, avtalsperiod, uppsägningsvillkor, kommersiella risker, "
                    "ekonomiska risker, operativa risker och rekommenderad nästa åtgärd. "
                    "Användaren ska också kunna ange intern referens, prioritet och ansvarig avdelning. "
                    "Jag vill att strukturerad data används där det förbättrar kvaliteten."
                ),
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="Strukturerat textresultat.",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="Ett avtal åt gången.",
                metadata={"ui_language": "sv"},
            ),
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "document_material_scope" not in question_ids
        assert "structured_analysis_need" not in question_ids
        assert "runtime_metadata_fields" not in question_ids

    def test_generic_flow_with_resolved_core_requirements_assumes_no_runtime_metadata(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Build a flow that summarizes uploaded documents.",
                metadata={"ui_language": "en"},
            )
        ]
        planning_state = PlanningState.empty()
        planning_state.resolved_slots = {
            "primary_runtime_input": _resolved_slot(
                "primary_runtime_input",
                "documents",
            ),
            "document_material_scope": _resolved_slot(
                "document_material_scope",
                "single_document_case",
            ),
            "terminal_output": _resolved_slot(
                "terminal_output",
                "structured_text",
            ),
            "post_processing_goal": _resolved_slot(
                "post_processing_goal",
                "summarize_or_overview",
            ),
        }

        analysis = analyze_discovery(conversation, planning_state=planning_state)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "runtime_metadata_fields" not in question_ids
        assert analysis.ready_for_confirmation is True
        assert analysis.assumptions == (
            "Assuming no extra form fields are needed at runtime for now; "
            "you can add them before confirming.",
        )

    def test_explicit_runtime_metadata_does_not_reask_runtime_metadata_fields(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Bygg ett flöde för ett ärende.",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="Ett ärende åt gången",
                metadata={
                    "question_answer": {
                        "question_id": "processing_scope",
                        "selected_option_id": "single_case",
                        "answer": "single_case",
                    },
                    "ui_language": "sv",
                },
            ),
            ConversationMessage(
                role="user",
                content="Dokument",
                metadata={
                    "question_answer": {
                        "question_id": "primary_runtime_input",
                        "selected_option_id": "documents",
                        "answer": "documents",
                    },
                    "ui_language": "sv",
                },
            ),
            ConversationMessage(
                role="user",
                content="Ett huvuddokument per ärende",
                metadata={
                    "question_answer": {
                        "question_id": "document_material_scope",
                        "selected_option_id": "single_document_case",
                        "answer": "single_document_case",
                    },
                    "ui_language": "sv",
                },
            ),
            ConversationMessage(
                role="user",
                content="Strukturerat textresultat.",
                metadata={
                    "question_answer": {
                        "question_id": "terminal_output",
                        "selected_option_id": "structured_text",
                        "answer": "structured_text",
                    },
                    "ui_language": "sv",
                },
            ),
            ConversationMessage(
                role="user",
                content="Lägg till grundläggande metadata",
                metadata={
                    "question_answer": {
                        "question_id": "runtime_metadata_fields",
                        "selected_option_id": "basic_runtime_metadata",
                        "answer": "basic_runtime_metadata",
                    },
                    "ui_language": "sv",
                },
            ),
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "runtime_metadata_fields" not in question_ids

    def test_complex_pdf_analysis_prompt_does_not_surface_structured_analysis_question(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som tar emot ett eller flera PDF-dokument i ett ärende, "
                    "extraherar centrala fakta, gör en sociologisk och psykologisk analys, "
                    "och genererar en slutrapport som PDF med tydlig struktur."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "structured_analysis_need" not in question_ids

    def test_docx_create_prompt_with_pdf_input_does_not_emit_pdf_assumption(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som tar emot ett dokumentpaket med flera PDF-filer i ett ärende. "
                    "Steg 1 extraherar text ur alla dokument. Steg 2 identifierar risker och "
                    "konsekvenser som strukturerad JSON. Steg 3 kopplar riskerna till "
                    "sociologiska och psykologiska teorier med hjälp av en kunskapsbas. Steg 4 skriver "
                    "en grounded sammanfattning med källhänvisningar. Steg 5 genererar en strukturerad "
                    "DOCX-rapport utan mall. Flödet ska ha formulärfält för referensnummer och ansvarig enhet."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "final_pdf_type" not in question_ids

    def test_structured_docx_output_answer_does_not_reopen_docx_mode_question(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Behåll samma riktning.",
                metadata={
                    "question_answer": {
                        "question_id": "terminal_output",
                        "selected_option_id": "docx_document",
                        "selected_value": "docx_document",
                        "answer": "docx_document",
                    },
                    "ui_language": "sv",
                },
            ),
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "docx_output_mode" not in question_ids

    def test_pdf_output_with_explicit_answer_resolves_without_pdf_type_question(
        self,
    ) -> None:
        """When the user explicitly selects pdf_document as output mode, the
        auto-inference resolves enough context that final_pdf_type (high_value)
        is not raised as a blocking issue.
        """
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill bygga ett flöde som skapar en pdf från flera officiella dokument.",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="PDF-dokument",
                metadata={
                    "question_answer": {
                        "question_id": "terminal_output",
                        "selected_option_id": "pdf_document",
                        "answer": "pdf_document",
                    },
                    "ui_language": "sv",
                },
            ),
        ]

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "final_pdf_type" not in question_ids
        assert "pdf_generation_mode" not in question_ids


class TestPlannerConversationEncoding:
    def test_structured_answer_metadata_is_included_for_llm_context(self) -> None:
        payload = conversation_message_to_llm_message(
            ConversationMessage(
                role="user",
                content="Documents",
                metadata={
                    "question_answer": {
                        "question_id": "primary_runtime_input",
                        "selected_option_ids": ["documents"],
                        "selected_values": ["documents"],
                    }
                },
            )
        )

        assert payload["role"] == "user"
        assert "Structured answer metadata" in payload["content"]
        assert "primary_runtime_input" in payload["content"]

    def test_unexpected_conversation_role_fails_loud_for_llm_context(self) -> None:
        with pytest.raises(
            ValueError, match="Unsupported AI Builder conversation role"
        ):
            conversation_message_to_llm_message(
                ConversationMessage(role="invalid", content="Bad role")
            )


class TestPlannerDiscoveryQuestionDispatch:
    @pytest.mark.asyncio
    async def test_server_question_fallback_text_is_persisted(
        self,
    ) -> None:
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
        decision = AskCanonicalQuestion(
            slot_name="structured_analysis_need",
        )

        result = await dispatch_server_decision(
            ServerDecisionDispatchRequest(
                repo=repo,
                turn=_make_turn(),
                decision=decision,
                conversation=conversation,
                new_messages_start=0,
                flow=None,
                confirmed_requirements_version=None,
                ui_language="en",
                telemetry=ServerDecisionTelemetry(
                    request_id="req-test",
                    litellm_model="server",
                    usage_tracker=ProposalTurnTelemetry(
                        request_id="req-test",
                        model="server",
                        target_kind=TargetKind.CREATE,
                    ),
                ),
                planning_state=PlanningState.empty(),
            )
        )

        assert [event.event for event in result.events] == ["error"]
        repo.commit_turn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_uses_backend_followup_after_llm_slot_classification_for_blocking_discovery(
        self,
    ) -> None:
        repo = AsyncMock()
        session_id = uuid4()
        repo.get_session.return_value = MagicMock(
            id=session_id,
            status=SessionStatus.CHATTING,
            conversation=[],
            planning_state_version=0,
        )
        repo.load_planning_state.return_value = None
        _configure_turn_acceptance(repo)

        planner = AIBuilderPlanner(
            user=MagicMock(tenant_id=uuid4()),
            repo=repo,
            litellm_client=AsyncMock(),
            planner_temperature=0.1,
            self_correction_temperature=0.1,
            forced_proposal_temperature=0.1,
            quality_retry_warning_codes=set(),
        )

        events: list[dict[str, str]] = []
        client_turn_id = uuid4()
        with patch(
            "eneo.flows.ai_builder.ai_builder_planner.lookup_model_defaults",
            return_value=MagicMock(max_input_tokens=128000),
        ):
            async for event in planner.send_message(
                session_id=session_id,
                client_turn_id=client_turn_id,
                request_fingerprint="a" * 64,
                request_snapshot={
                    "client_turn_id": str(client_turn_id),
                    "message": "Jag vill bygga ett flöde som hjälper mig att förstå officiella dokument.",
                    "ui_language": "sv",
                },
                message="Jag vill bygga ett flöde som hjälper mig att förstå officiella dokument.",
                ui_language="sv",
                completion_model_route=ResolvedCompletionModelRoute(
                    litellm_model="openai/gpt-5.4",
                    provider_type="openai",
                    litellm_kwargs={},
                    supported_model_kwargs=SupportedModelKwargs(),
                ),
                available_models=None,
                available_kbs=None,
                max_input_tokens=128000,
                max_output_tokens=4096,
            ):
                events.append(encode_ai_builder_stream_event(event))

        assert [event["event"] for event in events] == ["text", "question", "done"]
        assert planner.litellm_client.acompletion.await_count == 1
        repo.commit_turn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_audio_docx_extraction_requires_core_input_evidence_before_proposal(
        self,
    ) -> None:
        repo = AsyncMock()
        session_id = uuid4()
        repo.get_session.return_value = MagicMock(
            id=session_id,
            status=SessionStatus.CHATTING,
            conversation=[],
            planning_state_version=0,
        )
        repo.load_planning_state.return_value = None
        _configure_turn_acceptance(repo)

        planner = AIBuilderPlanner(
            user=MagicMock(tenant_id=uuid4()),
            repo=repo,
            litellm_client=AsyncMock(),
            planner_temperature=0.1,
            self_correction_temperature=0.1,
            forced_proposal_temperature=0.1,
            quality_retry_warning_codes=set(),
        )

        events: list[dict[str, str]] = []
        client_turn_id = uuid4()
        with patch(
            "eneo.flows.ai_builder.ai_builder_planner.lookup_model_defaults",
            return_value=MagicMock(max_input_tokens=128000),
        ):
            async for event in planner.send_message(
                session_id=session_id,
                client_turn_id=client_turn_id,
                request_fingerprint="a" * 64,
                request_snapshot={
                    "client_turn_id": str(client_turn_id),
                    "message": (
                        "Create a flow that transcribes meeting audio, extracts ten "
                        "topic sections, and produces a DOCX meeting report."
                    ),
                    "ui_language": "en",
                },
                message=(
                    "Create a flow that transcribes meeting audio, extracts ten "
                    "topic sections, and produces a DOCX meeting report."
                ),
                ui_language="en",
                completion_model_route=ResolvedCompletionModelRoute(
                    litellm_model="openai/gpt-5.4",
                    provider_type="openai",
                    litellm_kwargs={},
                    supported_model_kwargs=SupportedModelKwargs(),
                ),
                available_models=None,
                available_kbs=None,
                max_input_tokens=128000,
                max_output_tokens=4096,
            ):
                events.append(encode_ai_builder_stream_event(event))

        assert [event["event"] for event in events] == ["text", "question", "done"]
        assert json.loads(events[1]["data"])["question_id"] == ("primary_runtime_input")
        repo.commit_turn.assert_awaited_once()


def test_output_reader_followup_text_mentions_reader_not_output_format() -> None:
    """A specific prompt mentioning 'text summary' resolves output mode via
    auto-inference. The output_reader question is nice_to_have and not
    raised as a blocking issue. Verify that the followup text for an
    output_reader issue (when manually constructed) mentions 'reader'.
    """
    from eneo.flows.ai_builder.ai_builder_discovery_models import (
        DiscoveryIssue,
    )
    from eneo.flows.ai_builder.ai_builder_discovery_questions import (
        output_reader_question,
    )

    issue = DiscoveryIssue(
        issue_id="output_reader",
        category="output",
        severity="blocking",
        message="The main reader and tone of the final output are still unclear.",
        suggestion=output_reader_question("en"),
        question_level="nice_to_have",
    )

    text = build_discovery_followup_text(issue, "en")

    assert "primarily for" in text.lower() or "reader" in text.lower()
    assert "final output a bit better" not in text.lower()
