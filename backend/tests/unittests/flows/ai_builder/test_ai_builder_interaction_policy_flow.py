"""What the interaction policy asks, seen from discovery and the action policy."""

from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_action_policy import build_planner_action_policy
from eneo.flows.ai_builder.ai_builder_discovery import analyze_discovery
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.planning_state import PlanningState, ResolvedSlot
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
    llm_resolvable_slot_values_for_state,
)


def _answer(question_id: str, value: str, content: str) -> ConversationMessage:
    return ConversationMessage(
        role="user",
        content=content,
        metadata={
            "question_answer": {
                "question_id": question_id,
                "selected_option_ids": [value],
                "selected_values": [value],
            },
            "ui_language": "sv",
        },
    )


def _heuristic(name: str, value: str) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source="heuristic",
        evidence=[f"heuristic:{name}"],
        confidence="high",
    )


def test_a_confident_text_reading_of_the_comparison_is_asked_before_any_commit() -> (
    None
):
    # The card would otherwise show a same-run comparison while the
    # aggregation reader, which reads commit grade only, committed a linear
    # flow.
    conversation = [
        ConversationMessage(
            role="user",
            content="Ladda upp flera dokument i samma körning och jämför dem.",
            metadata={"ui_language": "sv"},
        ),
        _answer("primary_runtime_input", "documents", "Dokument"),
        _answer("terminal_output", "structured_text", "Text"),
        _answer("document_material_scope", "multiple_documents_case", "Flera"),
    ]
    state = build_planning_state_from_conversation(conversation)
    state.resolved_slots["comparison_scope"] = _heuristic(
        "comparison_scope", "same_run_compare"
    )

    analysis = analyze_discovery(conversation, planning_state=state)
    assert "comparison_scope" in analysis.selected_question_ids

    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=analysis.selected_question_ids,
    )
    assert policy.allowed_action_kinds == ("ask_question",)
    assert "comparison_scope" in policy.allowed_ask_question_targets


def test_template_wording_without_an_attachment_asks_the_docx_mode() -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content="Skapa en Word-fil från en mall utifrån ett uppladdat dokument.",
            metadata={"ui_language": "sv"},
        ),
        _answer("primary_runtime_input", "documents", "Dokument"),
        _answer("terminal_output", "docx_document", "Word"),
    ]
    state = build_planning_state_from_conversation(conversation)
    state.resolved_slots["docx_output_mode"] = _heuristic(
        "docx_output_mode", "template_fill_docx"
    )

    analysis = analyze_discovery(conversation, planning_state=state)

    assert "docx_output_mode" in analysis.selected_question_ids


def test_validating_several_files_against_a_policy_is_asked_how_to_compare() -> None:
    # No text rule turns "several files" plus "validate" into a same-run
    # comparison: the counterpart is an external policy.
    conversation = [
        ConversationMessage(
            role="user",
            content=(
                "Ladda upp flera filer och validera dem mot vår policy, "
                "med en rapport som resultat."
            ),
            metadata={"ui_language": "sv"},
        ),
        _answer("primary_runtime_input", "documents", "Dokument"),
    ]
    state = build_planning_state_from_conversation(conversation)

    assert "comparison_scope" not in state.resolved_slots
    analysis = analyze_discovery(conversation, planning_state=state)
    assert "comparison_scope" in analysis.selected_question_ids


def test_the_model_offer_follows_relevance_for_every_replaceable_value() -> None:
    # A template DOCX would rule the report disposition out, but a heuristic
    # mode is replaceable, so the disposition stays on offer without any
    # second list of which slots depend on which.
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
        name="primary_runtime_input",
        value="documents",
        source="structured_answer",
        evidence=["structured_answer:primary_runtime_input"],
        confidence="high",
    )
    state.resolved_slots["terminal_output"] = ResolvedSlot(
        name="terminal_output",
        value="docx_document",
        source="structured_answer",
        evidence=["structured_answer:terminal_output"],
        confidence="high",
    )
    state.resolved_slots["docx_output_mode"] = _heuristic(
        "docx_output_mode", "template_fill_docx"
    )

    assert "report_disposition" in llm_resolvable_slot_values_for_state(state)
