from __future__ import annotations

from intric.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.planning_state import PlanningState, ResolvedSlot
from intric.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)


def _slot(name: str, value: str) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source="structured_answer",
        confidence="high",
    )


def _state_with_slots(**slots: str) -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots = {name: _slot(name, value) for name, value in slots.items()}
    return state


def test_derives_text_to_text_architecture_from_resolved_slots() -> None:
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="text",
            terminal_output="structured_text",
        )
    )

    assert draft is not None
    assert [triple.model_dump() for triple in draft.tuples_chain] == [
        {
            "input_type": "text",
            "output_type": "text",
            "output_mode": "pass_through",
        }
    ]
    assert draft.chosen_patterns == ["summarize_text"]
    assert "form_field_runtime_inputs" not in draft.chosen_patterns
    assert draft.required_capabilities == ["input_text", "output_mode_pass_through"]


def test_derives_docx_template_architecture_from_resolved_slots() -> None:
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="documents",
            terminal_output="docx_document",
            docx_output_mode="template_fill_docx",
            document_material_scope="single_document_case",
        )
    )

    assert draft is not None
    assert [triple.model_dump() for triple in draft.tuples_chain] == [
        {
            "input_type": "document",
            "output_type": "docx",
            "output_mode": "template_fill",
        }
    ]
    assert draft.chosen_patterns == ["document_to_docx_template"]
    assert draft.required_capabilities == [
        "input_document",
        "output_mode_template_fill",
    ]


def test_derives_audio_to_pdf_architecture_without_document_scope() -> None:
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="audio",
            terminal_output="pdf_document",
        )
    )

    assert draft is not None
    assert [triple.model_dump() for triple in draft.tuples_chain] == [
        {
            "input_type": "audio",
            "output_type": "pdf",
            "output_mode": "pass_through",
        }
    ]
    assert draft.chosen_patterns == ["audio_to_artifact_report"]
    assert draft.required_capabilities == ["input_audio", "output_mode_pass_through"]


def test_prefers_multi_step_quality_pattern_when_structured_analysis_is_resolved() -> (
    None
):
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="documents",
            terminal_output="structured_text",
            document_material_scope="single_document_case",
            structured_analysis_need="use_structured_analysis",
        )
    )

    assert draft is not None
    assert [triple.model_dump() for triple in draft.tuples_chain] == [
        {
            "input_type": "document",
            "output_type": "text",
            "output_mode": "pass_through",
        }
    ]
    assert draft.chosen_patterns == ["multi_step_quality_chain"]
    assert draft.aggregation_intent == "linear"


def test_derives_aggregate_intent_for_multiple_document_scope() -> None:
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="documents",
            terminal_output="docx_document",
            document_material_scope="multiple_documents_case",
        )
    )

    assert draft is not None
    assert draft.aggregation_intent == "aggregate"


def test_derives_compare_intent_for_same_run_comparison_scope() -> None:
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="documents",
            terminal_output="structured_text",
            document_material_scope="single_document_case",
            comparison_scope="same_run_compare",
        )
    )

    assert draft is not None
    assert draft.aggregation_intent == "compare"


def test_derives_compare_intent_from_high_confidence_multi_source_prompt() -> None:
    state = build_planning_state_from_conversation(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Användaren laddar upp 2-5 underlagsfiler. Flödet ska "
                    "extrahera nyckelfakta från varje fil och identifiera "
                    "motsägelser mellan källorna i ett separat analyssteg. "
                    "Slutresultatet ska vara strukturerad JSON."
                ),
            )
        ]
    )

    draft = derive_architecture_commit_draft(state)

    assert draft is not None
    assert draft.aggregation_intent == "compare"


def test_does_not_force_multi_step_pattern_when_structured_analysis_is_rejected() -> (
    None
):
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="documents",
            terminal_output="structured_text",
            document_material_scope="single_document_case",
            structured_analysis_need="text_only_analysis",
        )
    )

    assert draft is not None
    assert draft.chosen_patterns == ["document_to_structured_report"]


def test_no_extra_runtime_metadata_does_not_select_form_field_pattern() -> None:
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="documents",
            terminal_output="structured_text",
            document_material_scope="flexible_document_case",
            runtime_metadata_fields="no_extra_metadata",
        )
    )

    assert draft is not None
    assert "form_field_runtime_inputs" not in draft.chosen_patterns


def test_returns_none_until_core_slots_are_resolved() -> None:
    assert (
        derive_architecture_commit_draft(
            _state_with_slots(primary_runtime_input="text")
        )
        is None
    )
