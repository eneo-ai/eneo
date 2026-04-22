"""Tests for discovery flow: confirm_requirements handling in proposal processor
and forced-proposal gating in the planner."""

from __future__ import annotations

import json
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
from intric.flows.ai_builder.ai_builder_models import (
    ConversationMessage,
    RequirementsSummaryPayload,
    SessionStatus,
)
from intric.flows.ai_builder.ai_builder_planner import AIBuilderPlanner
from intric.flows.ai_builder.ai_builder_prompts import (
    build_clarification_hints,
    build_system_prompt,
    has_confirmed_requirements,
)
from intric.flows.ai_builder.ai_builder_proposal_processor import (
    AIBuilderProposalProcessor,
)
from intric.flows.ai_builder.ai_builder_requirements_state import (
    build_requirements_version,
)
from intric.flows.ai_builder.ai_builder_tools import (
    CONFIRM_REQUIREMENTS_TOOL_NAME,
    CREATE_FLOW_TOOL_NAME,
)
from intric.flows.flow import Flow, FlowStep

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_processor(**overrides: Any) -> AIBuilderProposalProcessor:
    defaults: dict[str, Any] = {
        "user": MagicMock(tenant_id=uuid4()),
        "repo": AsyncMock(),
        "litellm_client": AsyncMock(),
        "self_correction_temperature": 0.2,
        "self_correction_bumped_temperature": 0.5,
        "forced_proposal_temperature": 0.3,
        "quality_retry_warning_codes": set(),
    }
    defaults.update(overrides)
    return AIBuilderProposalProcessor(**defaults)


def _make_tool_call(
    name: str, arguments: dict[str, Any], tool_call_id: str | None = None
) -> MagicMock:
    tc = MagicMock()
    tc.id = tool_call_id or f"call_{uuid4().hex[:8]}"
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


# ---------------------------------------------------------------------------
# confirm_requirements handling in proposal processor
# ---------------------------------------------------------------------------


class TestHandleConfirmRequirements:
    @pytest.mark.asyncio
    async def test_converts_incomplete_confirmation_into_next_discovery_question(
        self,
    ) -> None:
        processor = _make_processor()
        # Short prompt with document+case signals — the next discovery question
        # should be one of the early-priority blockers (processing scope,
        # input mode, or final output) rather than a deeper detail question.
        conversation = [
            ConversationMessage(
                role="user",
                content="Analysera dokument från case material",
            )
        ]
        tool_call = _make_tool_call(
            CONFIRM_REQUIREMENTS_TOOL_NAME,
            {
                "summary": "A case-material flow.",
                "key_decisions": [{"topic": "Scope", "decision": "Unclear"}],
                "input_description": "Case material",
                "output_description": "Decision support",
            },
        )

        events: list[dict[str, str]] = []
        async for event in processor.handle_tool_call(
            session_id=uuid4(),
            conversation=conversation,
            new_messages_start=len(conversation),
            tool_calls=[tool_call],
            text_content=None,
            llm_messages=[],
            tool_schemas=[],
            litellm_model="test-model",
            litellm_kwargs={},
            available_model_refs=None,
            available_kb_refs=None,
            max_output_tokens=8192,
            request_id="req-discovery-block",
        ):
            events.append(event)

        assert [event["event"] for event in events] == ["text", "question"]
        payload = json.loads(events[1]["data"])
        # Vague prompt → both blocking and high_value pass through budget
        assert payload["question_id"] in (
            "processing_scope",
            "final_output_mode",
            "input_material_mode",
        )
        assert len(conversation) == 3
        assert conversation[-2].role == "assistant"
        assert conversation[-1].role == "tool"

    @pytest.mark.asyncio
    async def test_emits_requirements_summary_event(self) -> None:
        processor = _make_processor()
        tool_call = _make_tool_call(
            CONFIRM_REQUIREMENTS_TOOL_NAME,
            {
                "summary": "A PDF analysis flow.",
                "key_decisions": [{"topic": "Input", "decision": "Multiple PDFs"}],
                "input_description": "PDF uploads",
                "output_description": "DOCX report",
            },
        )

        events: list[dict[str, str]] = []
        async for event in processor.handle_tool_call(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            tool_calls=[tool_call],
            text_content="Här är min sammanfattning:",
            llm_messages=[],
            tool_schemas=[],
            litellm_model="test-model",
            litellm_kwargs={},
            available_model_refs=None,
            available_kb_refs=None,
            max_output_tokens=8192,
            request_id="req-1",
        ):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "text" in event_types
        assert "requirements_summary" in event_types

        summary_event = next(e for e in events if e["event"] == "requirements_summary")
        payload = json.loads(summary_event["data"])
        assert payload["summary"] == "A PDF analysis flow."
        assert len(payload["key_decisions"]) == 1

    @pytest.mark.asyncio
    async def test_appends_conversation_messages(self) -> None:
        processor = _make_processor()
        conversation: list[ConversationMessage] = []
        tool_call = _make_tool_call(
            CONFIRM_REQUIREMENTS_TOOL_NAME,
            {
                "summary": "A flow.",
                "key_decisions": [{"topic": "A", "decision": "B"}],
                "input_description": "X",
                "output_description": "Y",
            },
        )

        events = []
        async for event in processor.handle_tool_call(
            session_id=uuid4(),
            conversation=conversation,
            new_messages_start=0,
            tool_calls=[tool_call],
            text_content=None,
            llm_messages=[],
            tool_schemas=[],
            litellm_model="test-model",
            litellm_kwargs={},
            available_model_refs=None,
            available_kb_refs=None,
            max_output_tokens=8192,
            request_id="req-2",
        ):
            events.append(event)

        # Should have appended assistant (tool_call) + tool (result) messages
        assert len(conversation) == 2
        assert conversation[0].role == "assistant"
        assert conversation[0].tool_calls is not None
        assert conversation[1].role == "tool"
        assert "awaiting confirmation" in conversation[1].content.lower()

    @pytest.mark.asyncio
    async def test_invalid_payload_emits_error(self) -> None:
        processor = _make_processor()
        tool_call = _make_tool_call(
            CONFIRM_REQUIREMENTS_TOOL_NAME,
            {"summary": ""},  # Invalid: empty summary
        )

        events = []
        async for event in processor.handle_tool_call(
            session_id=uuid4(),
            conversation=[],
            new_messages_start=0,
            tool_calls=[tool_call],
            text_content=None,
            llm_messages=[],
            tool_schemas=[],
            litellm_model="test-model",
            litellm_kwargs={},
            available_model_refs=None,
            available_kb_refs=None,
            max_output_tokens=8192,
            request_id="req-3",
        ):
            events.append(event)

        event_types = [e["event"] for e in events]
        assert "error" in event_types


class TestProposalGating:
    @pytest.mark.asyncio
    async def test_create_flow_is_rejected_until_latest_requirements_are_confirmed(
        self,
    ) -> None:
        processor = _make_processor()
        conversation = [
            ConversationMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": "call_requirements",
                        "name": CONFIRM_REQUIREMENTS_TOOL_NAME,
                        "arguments": {"summary": "A document flow"},
                    }
                ],
            ),
            ConversationMessage(
                role="tool",
                content="Requirements presented to user. Awaiting confirmation.",
                tool_call_id="call_requirements",
                metadata={
                    "requirements_summary": {
                        "summary": "A document flow",
                        "key_decisions": [{"topic": "Input", "decision": "PDF"}],
                        "input_description": "PDF",
                        "output_description": "DOCX",
                        "manual_setup_notes": [],
                    },
                    "requirements_version": "req-v1",
                },
            ),
        ]
        tool_call = _make_tool_call(
            CREATE_FLOW_TOOL_NAME,
            {
                "flow_name": "Test Flow",
                "plan_rationale": "Extraktion först.",
                "steps": [
                    {
                        "name": "Extract",
                        "instructions": "Extract the text.",
                        "input_source": "flow_input",
                        "input_type": "text",
                        "output_type": "text",
                    }
                ],
            },
        )

        with patch(
            "intric.flows.ai_builder.ai_builder_proposal_processor.store_plan_and_update_conversation",
            new_callable=AsyncMock,
        ) as store_plan:
            events: list[dict[str, str]] = []
            async for event in processor.handle_tool_call(
                session_id=uuid4(),
                conversation=conversation,
                new_messages_start=len(conversation),
                tool_calls=[tool_call],
                text_content="Här är mitt förslag:",
                llm_messages=[],
                tool_schemas=[],
                litellm_model="test-model",
                litellm_kwargs={},
                available_model_refs=None,
                available_kb_refs=None,
                max_output_tokens=4096,
                request_id="req-proposal-gate",
            ):
                events.append(event)

        event_types = [event["event"] for event in events]
        assert "error" in event_types
        assert "plan" not in event_types
        store_plan.assert_not_awaited()


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


class TestPinnedRequirementsPrompt:
    def test_build_system_prompt_can_render_confirmed_requirements_summary(
        self,
    ) -> None:
        prompt = build_system_prompt(
            confirmed_requirements={
                "summary": "Analysera en PDF och skapa DOCX-rapport.",
                "key_decisions": [{"topic": "DOCX", "decision": "Utan mall"}],
                "input_description": "En PDF per körning",
                "output_description": "DOCX-rapport",
                "manual_setup_notes": ["Ingen mall används."],
            }
        )

        assert "Bekräftade krav" in prompt
        assert "Analysera en PDF" in prompt
        assert "DOCX" in prompt


# ---------------------------------------------------------------------------
# Extended clarification hints
# ---------------------------------------------------------------------------


class TestExtendedClarificationHints:
    def test_generic_vague_prompt_yields_discovery_question(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="I want a flow that helps me process case material and produce decision support",
            )
        ]

        analysis = analyze_discovery(conversation)
        assert analysis.ready_for_confirmation is False
        assert analysis.next_issue is not None
        assert analysis.next_issue.suggestion is not None

        hints = build_clarification_hints(
            conversation=conversation,
            latest_user_message=conversation[0].content or "",
        )
        assert hints is not None
        assert "Ask exactly ONE structured question now" in hints

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
        """When the user explicitly answers comparison_scope with
        same_run_multiple_documents, the contradiction is considered resolved
        and confirmation is no longer blocked.
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

        block_message = build_discovery_block_message(conversation)
        assert block_message is None

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
                    "documents in the same run and produce decision support."
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
        _, question_data, _assistant_text = followup
        assert question_data["question_id"] == "final_output_mode"

    def test_rich_prompt_uses_full_question_budget_when_slots_remain(
        self,
    ) -> None:
        """Rich prompts no longer get fewer questions than short ones.

        Budget is 3 for any prompt without an explicit step plan. With 2
        structured answers already given, the 3rd slot is still available
        and the engine proposes the next architecture-impact question.
        """
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde som heter Kommunanalys Pro. "
                    "Flödet ska hjälpa en chef att förstå ett ärende. "
                    "Användaren ska kunna ladda upp underlag som PDF, ange ärendenummer, "
                    "kort beskrivning, språk för rapporten och fokus för analysen. "
                    "Flödet ska analysera materialet och skapa ett beslutsunderlag."
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
                content="Structured decision support as text",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_option_ids": ["structured_text"],
                        "selected_values": ["structured_text"],
                    }
                },
            ),
        ]

        followup = build_discovery_followup(conversation)
        assert followup is not None
        _, question_data, _assistant_text = followup
        assert question_data["question_id"] == "structured_analysis_need"

    def test_vague_decision_support_prompt_is_resolved_after_full_answers(self) -> None:
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
                    "produce decision support."
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
        _issue, question, _text = followup
        assert (
            question["question"]
            == "Vilken typ av dokument ska flödet främst arbeta med?"
        )
        first_option = question["options"][0]
        assert first_option["label"] == "Ärendedokument och officiellt underlag"
        assert all(
            option["label"] != english
            for option, english in zip(
                question["options"],
                [
                    "Case documents and official material",
                    "News or article-like material",
                    "Contracts or agreements",
                    "A mixed document package",
                ],
                strict=True,
            )
        )

    def test_pdf_output_counts_as_explicit_output_choice(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill ladda upp flera pdf filer och i slutändan vill jag ha en ny pdf med detaljerna."
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
            name="Kommunanalys",
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

    def test_explicit_english_text_output_does_not_reopen_final_output_mode(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content="I want a flow that summarizes uploaded news articles as decision support text.",
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
                    "extraherar leverantörsnamn, avtalsperiod, uppsägningsvillkor, juridiska risker, "
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
                    "extraherar leverantörsnamn, avtalsperiod, uppsägningsvillkor, juridiska risker, "
                    "ekonomiska risker, operativa risker och rekommenderad nästa åtgärd. "
                    "Användaren ska också kunna ange intern referens, prioritet och ansvarig avdelning. "
                    "Jag vill att strukturerad data används där det förbättrar kvaliteten."
                ),
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="Strukturerat beslutsunderlag som text.",
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

    def test_case_like_flow_with_resolved_core_requirements_asks_runtime_metadata_fields(
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
                content="Strukturerat beslutsunderlag som text.",
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

        assert "runtime_metadata_fields" in question_ids

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
                content="Strukturerat beslutsunderlag som text.",
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
                    "Steg 1 extraherar text ur alla dokument. Steg 2 identifierar juridiska risker och "
                    "ekonomiska konsekvenser som strukturerad JSON. Steg 3 kopplar riskerna till "
                    "sociologiska och psykologiska teorier med hjälp av en kunskapsbas. Steg 4 skriver "
                    "en grounded sammanfattning med källhänvisningar. Steg 5 genererar en strukturerad "
                    "DOCX-rapport utan mall. Flödet ska ha formulärfält för ärendenummer och ansvarig nämnd."
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
        _, question_data, _ = followup
        assert question_data["question_id"] == "docx_output_mode"

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
                content="Jag vill bygga ett flöde som skapar en pdf från flera kommunala dokument.",
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

    def test_audio_hint(self) -> None:
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message="Jag vill transkribera ljud och sedan sammanfatta.",
        )
        assert hints is not None
        assert 'input_type="audio"' in hints
        assert 'output_type="text"' in hints
        assert "Backend härleder" in hints

    def test_template_hint(self) -> None:
        hints = build_clarification_hints(
            conversation=[],
            latest_user_message="Jag vill fylla i en mall med data från analysen.",
        )
        assert hints is not None
        assert "template_fill" in hints


class TestPlannerConversationEncoding:
    def test_structured_answer_metadata_is_included_for_llm_context(self) -> None:
        payload = AIBuilderPlanner.conversation_msg_to_llm_dict(
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


class TestPlannerDiscoveryShortCircuit:
    @pytest.mark.asyncio
    async def test_uses_backend_followup_without_llm_for_blocking_discovery(
        self,
    ) -> None:
        repo = AsyncMock()
        session_id = uuid4()
        repo.get_session.return_value = MagicMock(
            id=session_id,
            status=SessionStatus.CHATTING,
            conversation=[],
        )

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
                message="Jag vill bygga ett flöde som hjälper mig att förstå kommunala underlag.",
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
        planner.litellm_client.acompletion.assert_not_awaited()
        repo.append_session_messages.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_discovery_complete_unconfirmed_phase_only_exposes_confirm_requirements_tool(
        self,
    ) -> None:
        repo = AsyncMock()
        session_id = uuid4()
        repo.get_session.return_value = MagicMock(
            id=session_id,
            status=SessionStatus.CHATTING,
            conversation=[],
        )

        litellm_client = AsyncMock()
        tool_call = MagicMock()
        tool_call.id = "call_requirements"
        tool_call.function.name = "confirm_requirements"
        tool_call.function.arguments = json.dumps(
            {
                "summary": "Ett enkelt sammanfattningsflöde för PDF-dokument.",
                "key_decisions": [{"topic": "Output", "decision": "Strukturerad text"}],
                "input_description": "Ett uppladdat PDF-dokument per körning.",
                "output_description": "En kort engelsk textsammanfattning.",
            }
        )
        assistant_message = MagicMock(content=None, tool_calls=[tool_call])
        litellm_client.acompletion.return_value = MagicMock(
            choices=[MagicMock(message=assistant_message, finish_reason="tool_calls")]
        )

        planner = AIBuilderPlanner(
            user=MagicMock(tenant_id=uuid4()),
            repo=repo,
            litellm_client=litellm_client,
            planner_temperature=0.1,
            self_correction_temperature=0.1,
            forced_proposal_temperature=0.1,
            quality_retry_warning_codes=set(),
        )

        flow = Flow(
            id=uuid4(),
            tenant_id=uuid4(),
            space_id=uuid4(),
            name="Simple Summary",
            description="Existing summary flow",
            metadata_json={},
            steps=[
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=1,
                    user_description="Summarize document",
                    input_source="flow_input",
                    input_type="document",
                    output_mode="pass_through",
                    output_type="text",
                    mcp_policy="inherit",
                    input_config={
                        "runtime_input": {
                            "enabled": True,
                            "required": True,
                            "max_files": 1,
                        }
                    },
                )
            ],
        )

        events: list[dict[str, str]] = []
        with patch(
            "intric.flows.ai_builder.ai_builder_planner.lookup_model_defaults",
            return_value=MagicMock(max_input_tokens=128000, max_output_tokens=4096),
        ):
            async for event in planner.send_message(
                session_id=session_id,
                message="Build a flow that summarizes one uploaded PDF into a short plain-English summary.",
                ui_language="en",
                litellm_model="openai/gpt-5.4",
                litellm_kwargs={},
                available_models=None,
                available_kbs=None,
                flow=flow,
                max_input_tokens=128000,
                max_output_tokens=4096,
            ):
                events.append(event)

        tool_schemas = litellm_client.acompletion.await_args.kwargs["tools"]
        tool_names = [schema["function"]["name"] for schema in tool_schemas]
        tool_choice = litellm_client.acompletion.await_args.kwargs["tool_choice"]

        assert tool_names == ["confirm_requirements"]
        assert tool_choice == {
            "type": "function",
            "function": {"name": "confirm_requirements"},
        }
        assert any(event["event"] == "requirements_summary" for event in events)


def test_output_reader_followup_text_mentions_reader_not_output_format() -> None:
    """A specific prompt mentioning 'decision support text' resolves output
    mode via auto-inference. The output_reader question is nice_to_have and
    not raised as a blocking issue. Verify that the followup text for an
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
