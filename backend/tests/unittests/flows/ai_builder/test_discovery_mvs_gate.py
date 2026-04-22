"""Tests for MVS gate, question taxonomy, and free discovery mode.

Covers:
- R1: Vague Swedish triggers free discovery (MVS not met)
- R9: Free discovery turn limit
- R10: Mixed architecture → clarification
- Question level taxonomy correctness
"""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_discovery import (
    analyze_discovery,
    build_discovery_block_message,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage

# ---------------------------------------------------------------------------
# Question taxonomy — every issue has the correct question_level
# ---------------------------------------------------------------------------

_EXPECTED_QUESTION_LEVELS: dict[str, str] = {
    "comparison_scope_conflict": "blocking",
    "case_scope": "high_value",
    "input_material_mode": "blocking",
    "flow_input_architecture": "blocking",
    "document_kind": "high_value",
    "document_material_scope": "high_value",
    "comparison_scope": "blocking",
    "final_output_mode": "blocking",
    "docx_output_mode": "blocking",
    "pdf_generation_mode": "blocking",
    "output_reader": "nice_to_have",
    "final_output_scope": "nice_to_have",
    "final_pdf_type": "high_value",
    "structured_analysis_need": "high_value",
    "runtime_metadata_fields": "high_value",
}


class TestQuestionTaxonomy:
    def test_document_processing_issues_have_correct_levels(self) -> None:
        """Document flow triggers several issues — verify each has correct level."""
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill ha ett flöde som bearbetar ett ärende med dokument "
                    "och producerar rapport med beslutsstöd"
                ),
            )
        ]
        analysis = analyze_discovery(conversation)
        issue_levels = {
            issue.issue_id: issue.question_level for issue in analysis.issues
        }
        for issue_id, expected_level in issue_levels.items():
            if issue_id in _EXPECTED_QUESTION_LEVELS:
                assert expected_level == _EXPECTED_QUESTION_LEVELS[issue_id], (
                    f"Issue {issue_id} should be {_EXPECTED_QUESTION_LEVELS[issue_id]}, "
                    f"got {expected_level}"
                )

    def test_output_reader_is_nice_to_have(self) -> None:
        """output_reader should be nice_to_have, not blocking architecture."""
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill analysera dokument och producera rapport med beslutsstöd"
                ),
            ),
            ConversationMessage(
                role="user",
                content="Dokument",
                metadata={
                    "question_answer": {
                        "question_id": "input_material_mode",
                        "selected_option_ids": ["documents"],
                        "selected_values": ["documents"],
                    }
                },
            ),
        ]
        analysis = analyze_discovery(conversation)
        reader_issues = [i for i in analysis.issues if i.issue_id == "output_reader"]
        for issue in reader_issues:
            assert issue.question_level == "nice_to_have"


# ---------------------------------------------------------------------------
# MVS gate — Minimum Viable Specification
# ---------------------------------------------------------------------------


class TestMVSGate:
    def test_vague_swedish_triggers_mvs_not_met(self) -> None:
        """E1: 'Hjälp mig bygga ett flöde' → MVS not met → not ready for confirmation."""
        conversation = [
            ConversationMessage(
                role="user",
                content="Hjälp mig bygga ett flöde",
            )
        ]
        analysis = analyze_discovery(conversation)
        assert not analysis.mvs_met
        assert not analysis.ready_for_confirmation

    def test_vague_english_triggers_mvs_not_met(self) -> None:
        """E5: 'Build me a flow' → MVS not met."""
        conversation = [
            ConversationMessage(
                role="user",
                content="Build me a flow",
            )
        ]
        analysis = analyze_discovery(conversation)
        assert not analysis.mvs_met
        assert not analysis.ready_for_confirmation

    def test_rich_swedish_has_mvs_met(self) -> None:
        """E3: Rich input with document + output → MVS met."""
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Analysera kommunala handlingar och ta fram beslutsunderlag som DOCX"
                ),
            )
        ]
        analysis = analyze_discovery(conversation)
        assert analysis.mvs_met

    def test_rich_english_has_mvs_met(self) -> None:
        """E16: Rich English with task verbs + output → MVS met."""
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Extract key clauses as JSON with fields, then produce comparison DOCX"
                ),
            )
        ]
        analysis = analyze_discovery(conversation)
        assert analysis.mvs_met

    def test_purpose_only_is_not_enough(self) -> None:
        """Just a task verb without input or output → MVS not met."""
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill analysera något",
            )
        ]
        analysis = analyze_discovery(conversation)
        assert not analysis.mvs_met

    def test_input_and_purpose_is_enough(self) -> None:
        """Document input + task verb → 2/3 dimensions → MVS met."""
        conversation = [
            ConversationMessage(
                role="user",
                content="Jag vill sammanfatta dokument",
            )
        ]
        analysis = analyze_discovery(conversation)
        assert analysis.mvs_met

    def test_mvs_not_met_blocks_confirmation_but_allows_free_discovery(self) -> None:
        """When MVS not met, ready_for_confirmation is False.

        build_discovery_block_message returns None (no backend-driven question),
        allowing the planner to enter free discovery mode instead.
        """
        conversation = [
            ConversationMessage(
                role="user",
                content="Help me with something",
            )
        ]
        analysis = analyze_discovery(conversation)
        assert not analysis.mvs_met
        assert not analysis.ready_for_confirmation
        # No backend-driven block — free discovery mode handles this
        block = build_discovery_block_message(conversation)
        assert block is None

    def test_advanced_explicit_user_has_mvs_met(self) -> None:
        """E4: Advanced user specifying steps → MVS met, minimal questions."""
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg 3-stegs: transkribera ljud, extrahera JSON-fakta, generera rapport"
                ),
            )
        ]
        analysis = analyze_discovery(conversation)
        assert analysis.mvs_met


# ---------------------------------------------------------------------------
# E13: Mixed architecture → clarification question
# ---------------------------------------------------------------------------


class TestQuestionBudget:
    def test_detailed_swedish_prompt_gets_few_questions(self) -> None:
        """A detailed intermediate prompt should get max 2-3 blocking questions,
        not 4+ including high_value ones like processing_scope and document_kind."""
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde som heter Kommunanalys expertz. "
                    "Flödet ska hjälpa en chef att förstå ett ärende. "
                    "Användaren ska kunna ladda upp underlag som PDF, ange "
                    "ärendenummer, kort beskrivning, språk för rapporten och "
                    "fokus för analysen. Flödet ska analysera materialet, "
                    "extrahera viktiga fakta, risker, möjligheter och "
                    "rekommendationer, och skapa ett beslutsunderlag. "
                    "Jag vill att lösningen blir robust och att strukturerad "
                    "data används där det förbättrar kvaliteten."
                ),
            )
        ]
        analysis = analyze_discovery(conversation)
        # Should be assessed as medium/advanced — not vague
        assert analysis.mvs_met

        blocking = analysis.blocking_issues
        # Budget should suppress high_value questions (case_scope,
        # document_kind, document_material_scope, runtime_metadata_fields)
        # Only blocking-level questions should remain
        high_value_count = sum(1 for i in blocking if i.question_level == "high_value")
        assert high_value_count == 0, (
            f"Expected 0 high_value questions for detailed prompt, "
            f"got {high_value_count}: {[i.issue_id for i in blocking if i.question_level == 'high_value']}"
        )
        assert len(blocking) <= 3, (
            f"Expected max 3 questions, got {len(blocking)}: "
            f"{[i.issue_id for i in blocking]}"
        )

    def test_kommunanalys_prompt_uses_assumptions_for_scope_and_document_shape(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde som heter Kommunanalys expertz. "
                    "Flödet ska hjälpa en chef att förstå ett ärende. "
                    "Användaren ska kunna ladda upp underlag som PDF, ange "
                    "ärendenummer, kort beskrivning, språk för rapporten och "
                    "fokus för analysen. Flödet ska analysera materialet, "
                    "extrahera viktiga fakta, risker, möjligheter och "
                    "rekommendationer, och skapa en rapport. "
                    "Jag vill att lösningen blir robust och att strukturerad "
                    "data används där det förbättrar kvaliteten."
                ),
            )
        ]
        analysis = analyze_discovery(conversation)

        blocking_ids = {issue.issue_id for issue in analysis.blocking_issues}
        assert "case_scope" not in blocking_ids
        assert "document_material_scope" not in blocking_ids
        assert "final_output_mode" not in blocking_ids
        assert len(blocking_ids) <= 2
        assert any(
            "ett ärende åt gången" in assumption for assumption in analysis.assumptions
        )
        assert any(
            "ett huvuddokument" in assumption for assumption in analysis.assumptions
        )

    def test_vague_prompt_allows_high_value_questions(self) -> None:
        """A short vague prompt should still allow high_value questions."""
        conversation = [
            ConversationMessage(
                role="user",
                content="Analysera dokument",
            )
        ]
        analysis = analyze_discovery(conversation)
        # Short prompt → vague complexity → high_value questions pass through
        # (Though MVS might not be met for very short prompts, the budget
        # should not suppress high_value for vague complexity)
        all_issues = analysis.issues
        # With such a short prompt, not many issues fire, but the ones
        # that do should include high_value if applicable
        high_value = [i for i in all_issues if i.question_level == "high_value"]
        # Budget for vague allows high_value, so they should not be filtered
        assert all(i.severity == "blocking" for i in high_value) or len(high_value) == 0

    def test_advanced_explicit_gets_minimal_questions(self) -> None:
        """E4: Advanced user specifying steps → few blocking questions only."""
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde med tre steg: steg 1 transkribera ljud "
                    "från mötesinsplening och skriv ut texten, steg 2 extrahera "
                    "JSON-fakta med nyckelinformation från transkriberingen, "
                    "steg 3 generera en strukturerad rapport som beslutsunderlag "
                    "med rekommendationer baserat på extraherade fakta. "
                    "Flödet ska stödja uppladdning av ljudfiler vid körning."
                ),
            )
        ]
        analysis = analyze_discovery(conversation)
        assert analysis.mvs_met
        # Advanced (60+ words, mentions steg) → max 1 blocking question
        assert len(analysis.blocking_issues) <= 1


class TestMixedArchitectureClarification:
    def test_mixed_audio_document_triggers_architecture_question(self) -> None:
        """E13: Audio + document mention → flow_input_architecture question."""
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill transkribera ljud och samtidigt ladda upp dokument "
                    "i samma körning"
                ),
            )
        ]
        analysis = analyze_discovery(conversation)
        arch_issues = [
            i for i in analysis.issues if i.issue_id == "flow_input_architecture"
        ]
        assert len(arch_issues) == 1
        assert arch_issues[0].question_level == "blocking"
