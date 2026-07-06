from __future__ import annotations

import pytest

from eneo.flows.ai_builder import ai_builder_architecture_derivation
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.planning_state import (
    PlanningState,
    ResolvedSlot,
    SlotConfidence,
    SlotSource,
)
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)


def _slot(
    name: str,
    value: str,
    *,
    source: SlotSource = "structured_answer",
    confidence: SlotConfidence = "high",
) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source=source,
        confidence=confidence,
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


def test_derives_json_to_json_architecture_from_resolved_slots() -> None:
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="json",
            terminal_output="structured_json",
        )
    )

    assert draft is not None
    assert [triple.model_dump() for triple in draft.tuples_chain] == [
        {
            "input_type": "json",
            "output_type": "json",
            "output_mode": "pass_through",
        }
    ]
    assert draft.chosen_patterns == ["json_to_structured_payload"]
    assert draft.required_capabilities == ["input_json", "output_mode_pass_through"]


def test_derives_json_to_text_architecture_from_resolved_slots() -> None:
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="json",
            terminal_output="structured_text",
        )
    )

    assert draft is not None
    assert [triple.model_dump() for triple in draft.tuples_chain] == [
        {
            "input_type": "json",
            "output_type": "text",
            "output_mode": "pass_through",
        }
    ]
    assert draft.chosen_patterns == ["json_to_text_summary"]


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


def test_derives_text_to_docx_architecture_with_non_empty_pattern() -> None:
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="text",
            terminal_output="docx_document",
        )
    )

    assert draft is not None
    assert [triple.model_dump() for triple in draft.tuples_chain] == [
        {
            "input_type": "text",
            "output_type": "docx",
            "output_mode": "render_verbatim",
        }
    ]
    assert draft.chosen_patterns == ["text_to_artifact_report"]
    assert draft.required_capabilities == ["input_text", "output_mode_render_verbatim"]


def test_derives_text_to_pdf_architecture_without_document_pattern() -> None:
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="text",
            terminal_output="pdf_document",
        )
    )

    assert draft is not None
    assert [triple.model_dump() for triple in draft.tuples_chain] == [
        {
            "input_type": "text",
            "output_type": "pdf",
            "output_mode": "render_verbatim",
        }
    ]
    assert draft.chosen_patterns == ["text_to_artifact_report"]


def test_returns_none_when_no_primary_pattern_can_be_chosen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_primary_pattern(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        ai_builder_architecture_derivation,
        "_primary_pattern_id",
        no_primary_pattern,
    )

    assert (
        derive_architecture_commit_draft(
            _state_with_slots(
                primary_runtime_input="text",
                terminal_output="structured_text",
            )
        )
        is None
    )


def test_metadata_fields_do_not_create_architecture_without_primary_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_primary_pattern(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        ai_builder_architecture_derivation,
        "_primary_pattern_id",
        no_primary_pattern,
    )

    assert (
        derive_architecture_commit_draft(
            _state_with_slots(
                primary_runtime_input="text",
                terminal_output="structured_text",
                runtime_metadata_fields="has_extra_metadata",
            )
        )
        is None
    )


def test_structured_analysis_slot_does_not_force_quality_chain() -> None:
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
    assert draft.chosen_patterns == ["document_to_structured_report"]
    assert draft.aggregation_intent == "linear"


def test_document_pdf_ignores_structured_analysis_slot() -> None:
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="documents",
            terminal_output="pdf_document",
            document_material_scope="multiple_documents_case",
            structured_analysis_need="use_structured_analysis",
        )
    )

    assert draft is not None
    assert [triple.model_dump() for triple in draft.tuples_chain] == [
        {
            "input_type": "document",
            "output_type": "pdf",
            "output_mode": "pass_through",
        }
    ]
    assert draft.chosen_patterns == ["document_to_pdf_report"]
    assert draft.aggregation_intent == "aggregate"


def test_json_terminal_schema_extraction_does_not_select_quality_chain() -> None:
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="documents",
            terminal_output="structured_json",
            document_material_scope="single_document_case",
            structured_analysis_need="use_structured_analysis",
        )
    )

    assert draft is not None
    assert [triple.model_dump() for triple in draft.tuples_chain] == [
        {
            "input_type": "document",
            "output_type": "json",
            "output_mode": "pass_through",
        }
    ]
    assert draft.chosen_patterns == ["document_to_structured_report"]
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


def test_document_scope_does_not_make_audio_artifact_aggregate() -> None:
    draft = derive_architecture_commit_draft(
        _state_with_slots(
            primary_runtime_input="audio",
            terminal_output="docx_document",
            document_material_scope="multiple_documents_case",
        )
    )

    assert draft is not None
    assert draft.chosen_patterns == ["audio_to_artifact_report"]
    assert draft.aggregation_intent == "linear"


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


def test_derives_linear_intent_for_medium_comparison_scope() -> None:
    state = _state_with_slots(
        primary_runtime_input="documents",
        terminal_output="structured_text",
        document_material_scope="single_document_case",
    )
    state.resolved_slots["comparison_scope"] = _slot(
        "comparison_scope",
        "same_run_compare",
        source="model",
        confidence="medium",
    )

    draft = derive_architecture_commit_draft(state)

    assert draft is not None
    assert draft.aggregation_intent == "linear"


def test_derives_compare_intent_for_high_model_comparison_scope() -> None:
    state = _state_with_slots(
        primary_runtime_input="documents",
        terminal_output="structured_text",
        document_material_scope="single_document_case",
    )
    state.resolved_slots["comparison_scope"] = _slot(
        "comparison_scope",
        "same_run_compare",
        source="model",
        confidence="high",
    )

    draft = derive_architecture_commit_draft(state)

    assert draft is not None
    assert draft.aggregation_intent == "compare"


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        ("medium", "linear"),
        ("high", "compare"),
    ],
)
def test_document_comparison_scope_respects_commit_grade(
    confidence: SlotConfidence,
    expected: str,
) -> None:
    state = _state_with_slots(
        primary_runtime_input="documents",
        terminal_output="structured_text",
        document_material_scope="single_document_case",
    )
    state.resolved_slots["comparison_scope"] = _slot(
        "comparison_scope",
        "same_run_multiple_documents",
        source="model",
        confidence=confidence,
    )

    draft = derive_architecture_commit_draft(state)

    assert draft is not None
    assert draft.aggregation_intent == expected


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
