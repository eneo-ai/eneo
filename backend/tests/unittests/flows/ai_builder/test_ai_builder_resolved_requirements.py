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


def test_build_system_prompt_includes_resolved_requirements_block() -> None:
    prompt = build_system_prompt(
        resolved_requirements_block="## Backend-resolved requirements state\n- test",
    )

    assert "Backend-resolved requirements state" in prompt
