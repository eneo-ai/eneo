"""Tests for which discovery questions a brief leaves open.

Covers:
- R10: Mixed architecture → clarification
"""

from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_discovery import (
    analyze_discovery,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.planning_state import PlanningState, ResolvedSlot
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)


def _state_with_typed_goal(
    conversation: list[ConversationMessage],
    goal: str,
) -> PlanningState:
    state = build_planning_state_from_conversation(conversation)
    state.resolved_slots["post_processing_goal"] = ResolvedSlot(
        name="post_processing_goal",
        value=goal,
        source="model",
        confidence="high",
        evidence=["quote:user_message:test-source:typed classifier evidence"],
        evidence_level="inferred",
    )
    return state


class TestInteractionPolicyAsks:
    def test_a_brief_with_nothing_in_it_starts_with_the_purpose(self) -> None:
        """No free-discovery mode: the interaction policy asks its first question.

        The action policy adds the unresolved architectural slots regardless,
        so hiding discovery's questions would only have changed which question
        came first.
        """
        conversation = [
            ConversationMessage(
                role="user",
                content="Help me with something",
            )
        ]
        analysis = analyze_discovery(conversation)
        assert analysis.selected_question_ids[0] == "post_processing_goal"

    def test_detailed_session_stops_asking_quality_questions_after_build_plan_signal(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett komplett AI-stött arbetsflöde för en reglerad "
                    "ärendeprocess. Flödet ska aldrig fatta beslut, och omfatta "
                    "steg 1 ta emot inkommet underlag, steg 2 inhämta uppgifter, "
                    "steg 3 klassificera ärendetyp, steg 4 analysera nuläge, "
                    "steg 5 föreslå nästa handläggningssteg, steg 6 skapa "
                    "uppdragsunderlag, steg 7 dokumentera genomförande, steg 8 "
                    "följa upp resultat, steg 9 föreslå fortsatt åtgärd. Output "
                    "ska vara flödesdesign, nodspecifikation, JSON-payload, "
                    "prompts, felhantering och kvalitetskontroller."
                ),
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="Flera dokument i samma körning",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="Jag vill ha docx rapport som slutresultat",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="ärendehandläggning kopplat till hela processen",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="båda lägen",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="extraherar, jämför och kvalitetssäkrar nyckelfält mellan inkomna PDF-dokument",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="inkomna dokument",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="Ja, det stämmer. Bygg planen.",
                metadata={"ui_language": "sv"},
            ),
            ConversationMessage(
                role="user",
                content="pdf filer som inkommande underlag",
                metadata={"ui_language": "sv"},
            ),
        ]

        analysis = analyze_discovery(
            conversation,
            planning_state=_state_with_typed_goal(
                conversation,
                "compare_or_validate",
            ),
        )

        # The quality slots are assumed, never asked. What the brief still
        # leaves open is what text alone cannot settle: the input, the output,
        # the comparison it asks for and the disposition of the report.
        assert set(analysis.selected_question_ids) <= {
            "primary_runtime_input",
            "terminal_output",
            "comparison_scope",
            "report_disposition",
        }
        assert {
            "document_material_scope",
            "runtime_metadata_fields",
        }.isdisjoint(set(analysis.selected_question_ids))

    def test_detailed_swedish_prompt_gets_few_questions(self) -> None:
        """A detailed intermediate prompt should get max 2-3 blocking questions,
        not 4+ including high-value discovery questions."""
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde som heter Dokumentanalys expert. "
                    "Flödet ska hjälpa en chef att förstå ett ärende. "
                    "Användaren ska kunna ladda upp underlag som PDF, ange "
                    "referensnummer, kort beskrivning, språk för rapporten och "
                    "fokus för analysen. Flödet ska analysera materialet, "
                    "extrahera viktiga fakta, risker, möjligheter och "
                    "rekommendationer, och skapa en slutrapport. "
                    "Jag vill att lösningen blir robust och att strukturerad "
                    "data används där det förbättrar kvaliteten."
                ),
            )
        ]
        analysis = analyze_discovery(
            conversation,
            planning_state=_state_with_typed_goal(
                conversation,
                "decision_support",
            ),
        )
        blocking = analysis.blocking_issues
        # The normal policy resolves optional scope and runtime metadata through
        # visible assumptions instead of spending the question budget.
        assert len(blocking) <= 3, (
            f"Expected max 3 questions, got {len(blocking)}: "
            f"{[i.issue_id for i in blocking]}"
        )

    def test_detailed_analysis_prompt_uses_assumptions_for_scope_and_document_shape(
        self,
    ) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill bygga ett flöde som heter Dokumentanalys expert. "
                    "Flödet ska hjälpa en chef att förstå ett ärende. "
                    "Användaren ska kunna ladda upp underlag som PDF, ange "
                    "referensnummer, kort beskrivning, språk för rapporten och "
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
        assert "document_material_scope" not in blocking_ids
        assert "final_output_mode" not in blocking_ids
        # Text alone settles no architecture slot: the input and output are
        # asked; the quality slots above are not.
        assert blocking_ids <= {
            "post_processing_goal",
            "primary_runtime_input",
            "terminal_output",
        }

    def test_advanced_explicit_gets_minimal_questions(self) -> None:
        conversation = [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde med tre steg: steg 1 transkribera ljud "
                    "från mötesinsplening och skriv ut texten, steg 2 extrahera "
                    "JSON-fakta med nyckelinformation från transkriberingen, "
                    "steg 3 generera en strukturerad rapport "
                    "med rekommendationer baserat på extraherade fakta. "
                    "Flödet ska stödja uppladdning av ljudfiler vid körning."
                ),
            )
        ]
        analysis = analyze_discovery(conversation)
        # An explicit step plan no longer buys a smaller budget; what the text
        # cannot settle is asked, and nothing else is.
        assert {issue.issue_id for issue in analysis.blocking_issues} <= {
            "post_processing_goal",
            "primary_runtime_input",
            "terminal_output",
        }


class TestMixedArchitectureClarification:
    def test_mixed_audio_document_triggers_architecture_question(self) -> None:
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
