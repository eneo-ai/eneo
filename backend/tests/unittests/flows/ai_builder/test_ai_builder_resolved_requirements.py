from __future__ import annotations

from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_prompts import build_system_prompt
from intric.flows.ai_builder.ai_builder_resolved_requirements import (
    build_resolved_requirements_prompt_block,
    build_resolved_requirements_state,
)


def test_resolved_requirements_state_tracks_role_aware_input_and_output() -> None:
    state = build_resolved_requirements_state(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en DOCX-rapport."
                ),
            )
        ]
    )

    assert state.slot("primary_runtime_input") is not None
    assert state.slot("primary_runtime_input").value == "documents"
    assert state.slot("terminal_output").value == "docx_document"


def test_resolved_requirements_state_prefers_confirmed_summary_as_output_source() -> (
    None
):
    state = build_resolved_requirements_state(
        [
            ConversationMessage(
                role="user",
                content="Bygg ett flöde som tar ett uppladdat PDF-dokument.",
            ),
            ConversationMessage(
                role="tool",
                metadata={
                    "requirements_summary": {
                        "summary": "DOCX-rapport",
                        "key_decisions": [],
                        "input_description": "PDF in",
                        "output_description": "En DOCX-rapport.",
                    }
                },
            ),
        ]
    )

    terminal_output = state.slot("terminal_output")
    assert terminal_output is not None
    assert terminal_output.value == "docx_document"
    assert terminal_output.source == "requirements_summary"


def test_resolved_requirements_state_keeps_freeform_inference_as_heuristic_source() -> (
    None
):
    state = build_resolved_requirements_state(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en DOCX-rapport."
                ),
            )
        ]
    )

    terminal_output = state.slot("terminal_output")
    assert terminal_output is not None
    assert terminal_output.source == "heuristic"
    assert terminal_output.confidence == "medium"


def test_resolved_requirements_state_uses_policy_default_when_docx_is_only_selected_via_output_answer() -> (
    None
):
    state = build_resolved_requirements_state(
        [
            ConversationMessage(
                role="user",
                content="Behåll samma riktning.",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_option_id": "docx_document",
                        "selected_value": "docx_document",
                        "answer": "docx_document",
                    }
                },
            )
        ]
    )

    docx_mode = state.slot("docx_output_mode")
    assert docx_mode is not None
    assert docx_mode.value == "generated_docx"
    assert docx_mode.source == "policy_default"
    assert docx_mode.confidence == "medium"


def test_resolved_requirements_state_uses_policy_default_when_pdf_is_only_selected_via_output_answer() -> (
    None
):
    state = build_resolved_requirements_state(
        [
            ConversationMessage(
                role="user",
                content="Behåll samma riktning.",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_option_id": "pdf_document",
                        "selected_value": "pdf_document",
                        "answer": "pdf_document",
                    }
                },
            )
        ]
    )

    pdf_mode = state.slot("pdf_generation_mode")
    assert pdf_mode is not None
    assert pdf_mode.value == "generated_pdf"
    assert pdf_mode.source == "policy_default"
    assert pdf_mode.confidence == "medium"


def test_build_resolved_requirements_prompt_block_includes_sources_and_evidence() -> (
    None
):
    block = build_resolved_requirements_prompt_block(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som tar ett uppladdat PDF-dokument och returnerar en kort textsammanfattning på svenska."
                ),
            )
        ]
    )

    assert block is not None
    assert "## Backend-resolved requirements state" in block
    assert "primary_runtime_input: documents" in block
    assert "terminal_output: structured_text" in block
    assert "source=heuristic" in block


def test_resolved_requirements_state_tracks_document_scope_and_runtime_metadata_slots() -> (
    None
):
    state = build_resolved_requirements_state(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som analyserar flera PDF-dokument i samma ärende. "
                    "Användaren ska ange intern referens och önskat språk."
                ),
            )
        ]
    )

    document_scope = state.slot("document_material_scope")
    runtime_metadata = state.slot("runtime_metadata_fields")

    assert document_scope is not None
    assert document_scope.value == "multiple_documents_case"
    assert document_scope.source == "heuristic"
    assert runtime_metadata is not None
    assert runtime_metadata.value in {"basic_case_metadata", "detailed_case_metadata"}
    assert runtime_metadata.source == "heuristic"


def test_resolved_requirements_state_tracks_structured_analysis_need_slot() -> None:
    state = build_resolved_requirements_state(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Strukturerad data ska användas där det förbättrar kvaliteten."
                ),
            )
        ]
    )

    structured_analysis = state.slot("structured_analysis_need")

    assert structured_analysis is not None
    assert structured_analysis.value == "use_structured_analysis"
    assert structured_analysis.source == "heuristic"


def test_build_system_prompt_includes_resolved_requirements_block() -> None:
    prompt = build_system_prompt(
        resolved_requirements_block="## Backend-resolved requirements state\n- test",
    )

    assert "Backend-resolved requirements state" in prompt
