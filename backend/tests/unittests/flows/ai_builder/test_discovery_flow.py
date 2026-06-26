"""Tests for discovery flow and server-owned planning decisions."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_discovery import (
    analyze_discovery,
    build_discovery_block_message,
    build_discovery_followup,
    build_discovery_followup_text,
)
from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    build_runtime_discovery_context,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    SessionStatus,
)
from intric.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
)
from intric.flows.ai_builder.ai_builder_planner import AIBuilderPlanner
from intric.flows.ai_builder.ai_builder_planner_request_preparation import (
    conversation_message_to_llm_message,
)
from intric.flows.ai_builder.ai_builder_prompts import (
    has_confirmed_requirements,
)
from intric.flows.ai_builder.ai_builder_requirements_state import (
    build_requirements_version,
)
from intric.flows.ai_builder.ai_builder_server_decision_dispatch import (
    ServerDecisionDispatchRequest,
    dispatch_server_decision,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.ai_builder_slot_classifier import (
    ClassifiedSlot,
    SlotClassificationResult,
)
from intric.flows.ai_builder.ai_builder_tools import CONFIRM_REQUIREMENTS_TOOL_NAME
from intric.flows.ai_builder.ai_builder_turn_controller import AskCanonicalQuestion
from intric.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)
from intric.flows.domain.flow import Flow, FlowStep

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# has_confirmed_requirements conversation scanning
# ---------------------------------------------------------------------------


class TestHasConfirmedRequirements:
    def test_returns_false_for_empty_conversation(self) -> None:
        assert has_confirmed_requirements([]) is False

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
        assert has_confirmed_requirements(conversation) is False

    def test_returns_true_after_requirements_confirmed(self) -> None:
        requirements_version = build_requirements_version(
            RequirementsSummaryPayload(
                summary="A flow.",
                key_decisions=[{"topic": "Input", "decision": "PDF"}],
                input_description="PDF upload",
                output_description="DOCX report",
                manual_setup_notes=[],
            )
        )
        conversation = [
            ConversationMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": CONFIRM_REQUIREMENTS_TOOL_NAME,
                        "arguments": {
                            "summary": "A flow.",
                            "key_decisions": [{"topic": "Input", "decision": "PDF"}],
                            "input_description": "PDF upload",
                            "output_description": "DOCX report",
                        },
                    }
                ],
            ),
            ConversationMessage(
                role="tool",
                content="Requirements presented to user. Awaiting confirmation.",
                tool_call_id="call_1",
                metadata={
                    "requirements_summary": {
                        "summary": "A flow.",
                        "key_decisions": [{"topic": "Input", "decision": "PDF"}],
                        "input_description": "PDF upload",
                        "output_description": "DOCX report",
                        "manual_setup_notes": [],
                    },
                    "requirements_version": requirements_version,
                },
            ),
            ConversationMessage(
                role="user",
                content="Ja, det stämmer.",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": requirements_version,
                },
            ),
        ]
        assert has_confirmed_requirements(conversation) is True

    def test_returns_false_with_requirements_but_no_user_confirmation(self) -> None:
        requirements_version = build_requirements_version(
            RequirementsSummaryPayload(
                summary="A flow.",
                key_decisions=[{"topic": "Input", "decision": "PDF"}],
                input_description="PDF upload",
                output_description="DOCX report",
                manual_setup_notes=[],
            )
        )
        conversation = [
            ConversationMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": CONFIRM_REQUIREMENTS_TOOL_NAME,
                        "arguments": {
                            "summary": "A flow.",
                            "key_decisions": [{"topic": "Input", "decision": "PDF"}],
                            "input_description": "PDF upload",
                            "output_description": "DOCX report",
                        },
                    }
                ],
            ),
            ConversationMessage(
                role="tool",
                content="Requirements presented to user. Awaiting confirmation.",
                tool_call_id="call_1",
                metadata={
                    "requirements_summary": {
                        "summary": "A flow.",
                        "key_decisions": [{"topic": "Input", "decision": "PDF"}],
                        "input_description": "PDF upload",
                        "output_description": "DOCX report",
                        "manual_setup_notes": [],
                    },
                    "requirements_version": requirements_version,
                },
            ),
        ]
        assert has_confirmed_requirements(conversation) is False

    def test_returns_false_when_user_changes_requirements_after_confirmation(
        self,
    ) -> None:
        requirements_version = build_requirements_version(
            RequirementsSummaryPayload(
                summary="A flow.",
                key_decisions=[{"topic": "Input", "decision": "PDF"}],
                input_description="PDF upload",
                output_description="DOCX report",
                manual_setup_notes=[],
            )
        )
        conversation = [
            ConversationMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": CONFIRM_REQUIREMENTS_TOOL_NAME,
                        "arguments": {"summary": "A flow."},
                    }
                ],
            ),
            ConversationMessage(
                role="tool",
                content="Requirements presented to user. Awaiting confirmation.",
                tool_call_id="call_1",
                metadata={
                    "requirements_summary": {
                        "summary": "A flow.",
                        "key_decisions": [{"topic": "Input", "decision": "PDF"}],
                        "input_description": "PDF upload",
                        "output_description": "DOCX report",
                        "manual_setup_notes": [],
                    },
                    "requirements_version": requirements_version,
                },
            ),
            ConversationMessage(
                role="user",
                content="Ja, det stämmer.",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": requirements_version,
                },
            ),
            ConversationMessage(
                role="user",
                content="Jag vill ändra till en PDF i taget.",
            ),
        ]
        assert has_confirmed_requirements(conversation) is False

    def test_returns_false_when_stored_requirements_version_does_not_match_summary(
        self,
    ) -> None:
        valid_version = build_requirements_version(
            RequirementsSummaryPayload(
                summary="A flow.",
                key_decisions=[{"topic": "Input", "decision": "PDF"}],
                input_description="PDF upload",
                output_description="DOCX report",
                manual_setup_notes=[],
            )
        )
        conversation = [
            ConversationMessage(
                role="tool",
                content="Requirements presented to user. Awaiting confirmation.",
                tool_call_id="call_1",
                metadata={
                    "requirements_summary": {
                        "summary": "A flow.",
                        "key_decisions": [{"topic": "Input", "decision": "PDF"}],
                        "input_description": "PDF upload",
                        "output_description": "DOCX report",
                        "manual_setup_notes": [],
                    },
                    "requirements_version": "mismatch",
                },
            ),
            ConversationMessage(
                role="user",
                content="Ja, det stämmer.",
                metadata={
                    "requirements_confirmed": True,
                    "requirements_version": valid_version,
                },
            ),
        ]
        assert has_confirmed_requirements(conversation) is False


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
        assert analysis.next_issue.issue_id == "final_output_mode"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "final_output_mode"

    def test_conflicting_single_file_and_same_run_compare_resolved_by_answer(
        self,
    ) -> None:
        """Answering comparison_scope with same_run_multiple_documents clears the
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
                        "selected_values": ["same_run_multiple_documents"],
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
                        "selected_option_ids": ["same_run_multiple_documents"],
                        "selected_values": ["same_run_multiple_documents"],
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
                        "selected_option_id": "same_run_multiple_documents",
                        "answer": "same_run_multiple_documents",
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

    def test_repeats_latest_blocking_question_until_it_is_resolved(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde som analyserar leverantörsavtal i PDF och "
                    "använda strukturerad data där det förbättrar kvaliteten."
                ),
            ),
            ConversationMessage(
                role="assistant",
                content="Jag behöver förstå slutresultatet lite bättre innan jag kan bekräfta lösningen.",
                tool_calls=[
                    {
                        "id": "call_output",
                        "name": "ask_structured_question",
                        "arguments": {
                            "question_id": "final_output_mode",
                            "question": "Vad ska flödet producera som slutresultat?",
                            "options": [],
                        },
                    }
                ],
            ),
            ConversationMessage(
                role="tool",
                content="Question presented to user. Awaiting their selection.",
                tool_call_id="call_output",
            ),
            ConversationMessage(
                role="user",
                content="Ett avtal åt gången.",
            ),
        ]

        followup = build_discovery_followup(conversation)

        assert followup is not None
        question_data = followup.question_data
        assert question_data.question_id == "final_output_mode"

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
                        "question_id": "final_output_mode",
                        "selected_option_ids": ["structured_text"],
                        "selected_values": ["structured_text"],
                    }
                },
            ),
        ]

        analysis = analyze_discovery(conversation)
        assert analysis.ready_for_confirmation
        followup = build_discovery_followup(conversation)
        assert followup is None

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
                        "question_id": "input_material_mode",
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
                        "question_id": "final_output_mode",
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

        analysis = analyze_discovery(conversation)
        assert analysis.ready_for_confirmation

    def test_prefers_ui_language_for_backend_generated_followup_questions(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="I want a flow that helps me process documents.",
                metadata={"ui_language": "sv"},
            )
        ]

        followup = build_discovery_followup(conversation)
        assert followup is not None
        question = followup.question_data
        assert question.question == "Vad ska flödet hjälpa dig göra med materialet?"
        first_option = question.options[0]
        assert first_option.label == "Bara grundresultatet"
        assert all(
            option.label != english
            for option, english in zip(
                question.options,
                [
                    "Only the primary result",
                    "Summarize or give an overview",
                    "Extract key information",
                    "Structure the material",
                    "Decisions, next steps, and follow-up",
                    "Recommendations and guidance",
                    "Review risks or issues",
                    "Compare or validate",
                ],
                strict=True,
            )
        )

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
        assert "final_output_mode" not in question_ids

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
                        "question_id": "final_output_mode",
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
        assert "input_material_mode" not in question_ids

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
        assert "final_output_mode" not in question_ids

    def test_swedish_audio_prompt_with_terminal_word_file_is_ready_for_confirmation(
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

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert analysis.ready_for_confirmation is True
        assert "input_material_mode" not in question_ids
        assert "flow_input_architecture" not in question_ids
        assert "final_output_mode" not in question_ids
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

        assert "input_material_mode" not in question_ids
        assert "flow_input_architecture" not in question_ids
        assert "primary_runtime_input" not in question_ids

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
                    mcp_policy="inherit",
                ),
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=2,
                    user_description="Skriv rapport",
                    input_source="previous_step",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="docx",
                    mcp_policy="inherit",
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

        assert "input_material_mode" not in question_ids
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
                    mcp_policy="inherit",
                ),
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=2,
                    user_description="Skriv slutrapport",
                    input_source="previous_step",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="text",
                    mcp_policy="inherit",
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

        assert "final_output_mode" not in question_ids
        assert "runtime_metadata_fields" not in question_ids
        assert "document_kind" not in question_ids
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
                    mcp_policy="inherit",
                ),
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=2,
                    user_description="Skriv rapport",
                    input_source="previous_step",
                    input_type="json",
                    output_mode="pass_through",
                    output_type="pdf",
                    mcp_policy="inherit",
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

    def test_simple_single_document_flow_does_not_block_on_document_kind(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill bygga ett enkelt PDF-flöde.",
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
                        "question_id": "input_material_mode",
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
                content="PDF-dokument",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
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

        assert "document_kind" not in question_ids

    def test_specific_uploaded_pdf_text_summary_prompt_skips_document_kind_and_pdf_type(
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

        assert "document_kind" not in question_ids
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

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert "input_material_mode" not in question_ids
        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "final_output_mode"

    def test_generic_uploaded_pdf_docx_prompt_defaults_generated_docx_without_reasking(
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

        analysis = analyze_discovery(conversation)
        question_ids = [
            issue.suggestion.question_id
            for issue in analysis.blocking_issues
            if issue.suggestion is not None
        ]

        assert analysis.next_issue is None
        assert "document_kind" not in question_ids
        assert "docx_output_mode" not in question_ids

    def test_structured_analysis_is_derived_for_audio_docx_extraction(
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

        analysis = analyze_discovery(conversation)
        state = build_planning_state_from_conversation(conversation)

        assert analysis.next_issue is None
        assert state.resolved_slots["post_processing_goal"].value == (
            "extract_key_information"
        )
        assert state.resolved_slots["structured_analysis_need"].value == (
            "use_structured_analysis"
        )

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
        assert analysis.next_issue.issue_id == "final_output_mode"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "final_output_mode"

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
                        "question_id": "final_output_mode",
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
        assert analysis.next_issue.issue_id == "input_material_mode"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "input_material_mode"

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
        assert analysis.next_issue.issue_id == "input_material_mode"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "input_material_mode"

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

    def test_vague_audio_prompt_asks_outcome_before_output_format(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag har en svensk ljudinspelning från ett möte och vill "
                    "göra ett flöde av den. Flödet ska ta ljudfilen, förstå "
                    "vad som sades och skapa något användbart som jag kan dela "
                    "vidare efteråt. Jag vet inte exakt vilket format "
                    "slutresultatet ska vara ännu."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "post_processing_goal"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "post_processing_goal"

    def test_vague_document_outcome_asks_post_processing_goal(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde som hjälper mig med dokument jag "
                    "laddar upp. Det ska läsa dokumentet och skapa något "
                    "användbart av det."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "post_processing_goal"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "post_processing_goal"
        assert analysis.decision_trace is not None
        assert analysis.decision_trace.selected_action == "ask"
        assert analysis.decision_trace.selected_question_id == "post_processing_goal"

    @pytest.mark.asyncio
    async def test_model_owned_goal_does_not_suppress_vague_outcome_question(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde som hjälper mig med dokument jag "
                    "laddar upp. Det ska läsa dokumentet och skapa något "
                    "användbart av det."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        async def fake_classify_slots(**kwargs: Any) -> SlotClassificationResult:
            return SlotClassificationResult(
                slots=(
                    ClassifiedSlot(
                        slot_name="post_processing_goal",
                        value="summarize_or_overview",
                        confidence="high",
                        reason="The model guessed a useful document summary.",
                    ),
                )
            )

        with patch(
            "intric.flows.ai_builder.ai_builder_discovery_runtime.classify_slots",
            side_effect=fake_classify_slots,
        ):
            context = await build_runtime_discovery_context(
                conversation,
                litellm_client=object(),
                litellm_model="test-model",
                tenant_id=uuid4(),
            )

        assert context.planning_state.resolved_slots["post_processing_goal"].source == (
            "model"
        )

        analysis = analyze_discovery(
            conversation,
            planning_state=context.planning_state,
            slot_classification_result=context.slot_classification_result,
        )

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "post_processing_goal"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "post_processing_goal"
        assert analysis.decision_trace is not None
        assert analysis.decision_trace.selected_action == "ask"
        assert analysis.decision_trace.selected_question_id == "post_processing_goal"
        assert analysis.decision_trace.selected_reason == "model_slot_not_sufficient"

    @pytest.mark.asyncio
    async def test_vague_transcription_asks_output_or_outcome_before_confirmation(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill ha ett transkriberingsflöde.",
                metadata={"ui_language": "sv"},
            )
        ]

        async def fake_classify_slots(**kwargs: Any) -> SlotClassificationResult:
            return SlotClassificationResult(
                slots=(
                    ClassifiedSlot(
                        slot_name="post_processing_goal",
                        value="summarize_or_overview",
                        confidence="high",
                        reason="The model guessed a transcript summary.",
                    ),
                )
            )

        with patch(
            "intric.flows.ai_builder.ai_builder_discovery_runtime.classify_slots",
            side_effect=fake_classify_slots,
        ):
            context = await build_runtime_discovery_context(
                conversation,
                litellm_client=object(),
                litellm_model="test-model",
                tenant_id=uuid4(),
            )

        analysis = analyze_discovery(
            conversation,
            planning_state=context.planning_state,
            slot_classification_result=context.slot_classification_result,
        )

        assert analysis.ready_for_confirmation is False
        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id in {
            "final_output_mode",
            "post_processing_goal",
        }
        assert analysis.decision_trace is not None
        assert analysis.decision_trace.selected_action == "ask"
        assert analysis.decision_trace.selected_question_id in {
            "final_output_mode",
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
        assert (
            analysis.decision_trace.selected_reason
            == "missing_structured_payload_contract"
        )
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

    def test_document_to_json_extraction_does_not_ask_post_processing_goal(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Användaren laddar upp ett PDF-avtal. Flödet ska extrahera "
                    "kundnamn, datum, riskflaggor och saknad information som "
                    "strukturerad JSON."
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
                        "question_id": "final_output_mode",
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

    def test_spent_question_budget_suppresses_outcome_question(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill bygga ett flöde som analyserar dokument och sammanfattar dem",
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
                        "question_id": "input_material_mode",
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
                        "selected_values": ["basic_case_metadata"],
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

        assert "post_processing_goal" not in question_ids
        assert any(
            candidate.issue_id == "post_processing_goal"
            and candidate.suppressed_reason == "question_budget_exhausted"
            for candidate in analysis.suppressed_candidates
        )

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
                role="user",
                content=(
                    "Create a flow that transcribes meeting audio, extracts ten "
                    "topic sections, and produces a DOCX meeting report."
                ),
                metadata={"ui_language": "en"},
            )
        ]
        captured_allowed_values: dict[str, object] = {}

        async def fake_classify_slots(**kwargs: Any) -> SlotClassificationResult:
            captured_allowed_values.update(kwargs["allowed_slot_values"])
            return SlotClassificationResult(
                slots=(
                    ClassifiedSlot(
                        slot_name="runtime_metadata_fields",
                        value="no_runtime_metadata",
                        confidence="high",
                        reason="No separate runtime metadata requested.",
                    ),
                )
            )

        with patch(
            "intric.flows.ai_builder.ai_builder_discovery_runtime.classify_slots",
            side_effect=fake_classify_slots,
        ):
            context = await build_runtime_discovery_context(
                conversation,
                litellm_client=object(),
                litellm_model="test-model",
                tenant_id=uuid4(),
            )

        assert "structured_analysis_need" not in captured_allowed_values
        assert "runtime_metadata_fields" in captured_allowed_values
        assert context.planning_state.resolved_slots[
            "structured_analysis_need"
        ].value == ("use_structured_analysis")

    @pytest.mark.asyncio
    async def test_classifier_resolved_outcome_still_asks_input_for_unknown_input(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill ha ett OCR-flöde.",
                metadata={"ui_language": "sv"},
            )
        ]

        async def fake_classify_slots(**kwargs: Any) -> SlotClassificationResult:
            return SlotClassificationResult(
                slots=(
                    ClassifiedSlot(
                        slot_name="post_processing_goal",
                        value="extract_key_information",
                        confidence="high",
                        reason="OCR suggests extracting readable text.",
                    ),
                    ClassifiedSlot(
                        slot_name="terminal_output",
                        value="structured_text",
                        confidence="high",
                        reason="OCR commonly returns text.",
                    ),
                )
            )

        with patch(
            "intric.flows.ai_builder.ai_builder_discovery_runtime.classify_slots",
            side_effect=fake_classify_slots,
        ):
            context = await build_runtime_discovery_context(
                conversation,
                litellm_client=object(),
                litellm_model="test-model",
                tenant_id=uuid4(),
            )

        analysis = analyze_discovery(
            conversation,
            planning_state=context.planning_state,
            slot_classification_result=context.slot_classification_result,
        )

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "input_material_mode"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "input_material_mode"

    @pytest.mark.asyncio
    async def test_classifier_raw_outcome_does_not_skip_bare_transcription_followup(
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
                content="PDF-dokument",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_values": ["pdf_document"],
                    },
                    "ui_language": "sv",
                },
            ),
        ]

        async def fake_classify_slots(**kwargs: Any) -> SlotClassificationResult:
            return SlotClassificationResult(
                slots=(
                    ClassifiedSlot(
                        slot_name="post_processing_goal",
                        value="stop_after_primary_operation",
                        confidence="high",
                        reason="transcription flow",
                    ),
                    ClassifiedSlot(
                        slot_name="structured_analysis_need",
                        value="text_only_analysis",
                        confidence="high",
                        reason="raw transcription",
                    ),
                )
            )

        with patch(
            "intric.flows.ai_builder.ai_builder_discovery_runtime.classify_slots",
            side_effect=fake_classify_slots,
        ):
            context = await build_runtime_discovery_context(
                conversation,
                litellm_client=object(),
                litellm_model="test-model",
                tenant_id=uuid4(),
            )

        assert "post_processing_goal" not in context.planning_state.resolved_slots
        assert "structured_analysis_need" not in context.planning_state.resolved_slots

        analysis = analyze_discovery(
            conversation,
            planning_state=context.planning_state,
            slot_classification_result=context.slot_classification_result,
        )

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "post_processing_goal"
        assert analysis.next_issue.suggestion is not None
        assert analysis.next_issue.suggestion.question_id == "post_processing_goal"

    def test_complex_multi_document_compare_prompt_skips_document_kind_and_comparison_scope(
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

        assert "document_kind" not in question_ids
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

        analysis = analyze_discovery(conversation)

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

        analysis = analyze_discovery(conversation)

        assert analysis.next_issue is not None
        assert analysis.next_issue.issue_id == "comparison_scope"
        assert analysis.decision_trace is not None
        assert analysis.decision_trace.selected_reason == "missing_reference_source"

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

        analysis = analyze_discovery(conversation)

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

        assert "final_output_mode" not in question_ids

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

        assert "final_output_mode" not in question_ids

    @pytest.mark.parametrize(
        ("prompt", "language", "assistant_snippet", "question_snippet"),
        [
            (
                "Jag vill läsa ett dokument, extrahera viktig information och skicka resultatet till ett API.",
                "sv",
                "kan inte skapa ett utgående API-leveranssteg automatiskt",
                "Vilket internt resultat ska flödet skapa",
            ),
            (
                "Extrahera fält från dokumentet och posta resultatet till en webhook.",
                "sv",
                "kan inte skapa ett utgående API-leveranssteg automatiskt",
                "Vilket internt resultat ska flödet skapa",
            ),
            (
                "Extrahera informationen och anropa ett externt API med resultatet.",
                "sv",
                "kan inte skapa ett utgående API-leveranssteg automatiskt",
                "Vilket internt resultat ska flödet skapa",
            ),
            (
                "Read a document, extract the important fields, and send the result to an external system.",
                "en",
                "cannot automatically create an outbound API delivery step",
                "What internal result should the flow create",
            ),
            (
                "Extract data from the uploaded document and POST the result to a webhook.",
                "en",
                "cannot automatically create an outbound API delivery step",
                "What internal result should the flow create",
            ),
        ],
    )
    def test_external_delivery_request_uses_specific_unsupported_delivery_followup(
        self,
        prompt: str,
        language: str,
        assistant_snippet: str,
        question_snippet: str,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=prompt,
                metadata={"ui_language": language},
            )
        ]

        followup = build_discovery_followup(conversation)

        assert followup is not None
        assert followup.issue is not None
        issue = followup.issue
        question_data = followup.question_data
        assistant_text = followup.assistant_text
        assert issue.issue_id == "external_delivery_unsupported"
        assert question_data.question_id == "final_output_mode"
        assert assistant_snippet in assistant_text
        assert question_snippet in question_data.question

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

        assert "final_output_mode" not in question_ids
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
        assert "final_output_mode" in question_ids

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

        assert "final_output_mode" not in question_ids

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
                    mcp_policy="inherit",
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

        assert "final_output_mode" not in question_ids

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
                    mcp_policy="inherit",
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

        assert "final_output_mode" not in question_ids
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

        assert "final_output_mode" not in question_ids

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

    def test_case_like_flow_with_resolved_core_requirements_defaults_runtime_metadata_fields(
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
                        "question_id": "input_material_mode",
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
                        "question_id": "final_output_mode",
                        "selected_option_id": "structured_text",
                        "answer": "structured_text",
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

    def test_case_like_flow_with_explicit_runtime_metadata_does_not_reask_runtime_metadata_fields(
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
                        "question_id": "input_material_mode",
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
                        "question_id": "final_output_mode",
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
                        "selected_option_id": "basic_case_metadata",
                        "answer": "basic_case_metadata",
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

    def test_complex_pdf_analysis_prompt_records_structured_intermediate_assumption(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som tar emot officiella ärendedokument, extraherar centrala fakta, "
                    "gör en sociologisk och psykologisk analys och genererar en strukturerad PDF-rapport."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)

        assert any(
            "strukturerad" in assumption.lower()
            and "mellanliggande" in assumption.lower()
            for assumption in analysis.assumptions
        )

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
        assert all(
            candidate.issue_id != "final_pdf_type" for candidate in analysis.candidates
        )
        assert all(
            "slut-pdf" not in assumption.casefold()
            for assumption in analysis.assumptions
        )

    def test_explicit_plain_text_preference_disables_structured_intermediate_assumption(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som analyserar officiella dokument och genererar en PDF-rapport, "
                    "men håll analysen som vanlig text och undvik extra struktur."
                ),
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)

        assert all(
            "mellanliggande" not in assumption.lower()
            for assumption in analysis.assumptions
        )

    def test_simple_single_verb_summary_prompt_does_not_assume_structured_intermediate(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Bygg ett flöde som sammanfattar ett dokument och genererar en PDF.",
                metadata={"ui_language": "sv"},
            )
        ]

        analysis = analyze_discovery(conversation)

        assert all(
            "mellanliggande" not in assumption.lower()
            for assumption in analysis.assumptions
        )

    def test_pending_question_is_reoffered_even_when_latest_turn_is_short(self) -> None:
        conversation = [
            ConversationMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": "call_docx_mode",
                        "name": "ask_structured_question",
                        "arguments": {
                            "question_id": "docx_output_mode",
                            "question": "Hur ska DOCX-resultatet skapas?",
                            "options": [
                                {
                                    "id": "generated_docx",
                                    "label": "Genererad DOCX",
                                    "description": "Skapa dokumentet direkt.",
                                    "value": "generated_docx",
                                },
                                {
                                    "id": "template_fill_docx",
                                    "label": "DOCX från mall",
                                    "description": "Fyll en mall.",
                                    "value": "template_fill_docx",
                                },
                            ],
                        },
                    }
                ],
            ),
            ConversationMessage(
                role="user",
                content="Kortare.",
                metadata={"ui_language": "sv"},
            ),
        ]

        followup = build_discovery_followup(conversation)

        assert followup is not None
        question_data = followup.question_data
        assert question_data.question_id == "docx_output_mode"

    def test_structured_docx_output_answer_does_not_reopen_docx_mode_question(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="Behåll samma riktning.",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
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
                        "question_id": "final_output_mode",
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
                        "question_id": "input_material_mode",
                        "selected_option_ids": ["documents"],
                        "selected_values": ["documents"],
                    }
                },
            )
        )

        assert payload["role"] == "user"
        assert "Structured answer metadata" in payload["content"]
        assert "input_material_mode" in payload["content"]

    def test_unexpected_conversation_role_fails_loud_for_llm_context(self) -> None:
        with pytest.raises(ValueError, match="Unsupported AI Builder conversation role"):
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
            prompt="Should the flow use structured analysis?",
        )

        result = await dispatch_server_decision(
            ServerDecisionDispatchRequest(
                repo=repo,
                turn=_make_turn(),
                decision=decision,
                conversation=conversation,
                new_messages_start=0,
                flow=None,
                discovery_analysis=None,
                requirements_confirmed=False,
                ui_language="en",
                request_id="req-test",
                litellm_model="server",
                used_auxiliary_llm=False,
            )
        )

        assert [event["event"] for event in result.events] == ["text"]
        repo.commit_turn.assert_awaited_once()
        commit_kwargs = repo.commit_turn.await_args.kwargs
        assert commit_kwargs["new_messages"][0].role == "user"
        assert commit_kwargs["new_messages"][-1].role == "assistant"
        assert commit_kwargs["new_messages"][-1].content == decision.prompt

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
        )
        repo.load_planning_state.return_value = None

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
        with patch(
            "intric.flows.ai_builder.ai_builder_planner.lookup_model_defaults",
            return_value=MagicMock(max_input_tokens=128000),
        ):
            async for event in planner.send_message(
                session_id=session_id,
                message="Jag vill bygga ett flöde som hjälper mig att förstå officiella dokument.",
                ui_language="sv",
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_models=None,
                available_kbs=None,
                max_input_tokens=128000,
                max_output_tokens=4096,
            ):
                events.append(event)

        assert [event["event"] for event in events] == ["text", "question", "done"]
        assert planner.litellm_client.acompletion.await_count == 1
        repo.commit_turn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_audio_docx_extraction_derives_structured_analysis_before_proposal(
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
        with patch(
            "intric.flows.ai_builder.ai_builder_planner.lookup_model_defaults",
            return_value=MagicMock(max_input_tokens=128000),
        ):
            async for event in planner.send_message(
                session_id=session_id,
                message=(
                    "Create a flow that transcribes meeting audio, extracts ten "
                    "topic sections, and produces a DOCX meeting report."
                ),
                ui_language="en",
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_models=None,
                available_kbs=None,
                max_input_tokens=128000,
                max_output_tokens=4096,
            ):
                events.append(event)

        assert [event["event"] for event in events] == ["status", "done"]
        repo.commit_turn.assert_awaited_once()


def test_output_reader_followup_text_mentions_reader_not_output_format() -> None:
    """A specific prompt mentioning 'text summary' resolves output mode via
    auto-inference. The output_reader question is nice_to_have and not
    raised as a blocking issue. Verify that the followup text for an
    output_reader issue (when manually constructed) mentions 'reader'.
    """
    from intric.flows.ai_builder.ai_builder_discovery_models import (
        DiscoveryIssue,
    )
    from intric.flows.ai_builder.ai_builder_discovery_questions import (
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
