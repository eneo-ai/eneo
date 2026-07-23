"""Deterministic phrase-routing contracts for AI Builder DOCX intent.

These cases exercise the owned heuristic and planning-state merge paths. They
do not measure live model accuracy; the battle harness owns that separate gate.
"""

from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_discovery import analyze_discovery
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)


def _question_ids_for(conversation: list[ConversationMessage]) -> list[str]:
    analysis = analyze_discovery(conversation)
    return [
        issue.suggestion.question_id
        for issue in analysis.blocking_issues
        if issue.suggestion is not None
    ]


@pytest.mark.parametrize(
    ("prompt", "expected_issue_id", "expected_question_id"),
    [
        (
            "Bygg ett flöde som genererar en DOCX-rapport från uppladdade PDF-dokument.",
            "runtime_metadata_fields",
            "runtime_metadata_fields",
        ),
        (
            "Bygg ett flöde som genererar en DOCX-rapport utan mall från uppladdade PDF-dokument.",
            "runtime_metadata_fields",
            "runtime_metadata_fields",
        ),
        (
            "Bygg ett flöde som fyller en DOCX-mall med data från uppladdade PDF-dokument.",
            "runtime_metadata_fields",
            "runtime_metadata_fields",
        ),
    ],
)
def test_docx_output_deterministic_routing(
    prompt: str,
    expected_issue_id: str | None,
    expected_question_id: str | None,
) -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content=prompt,
            metadata={"ui_language": "sv"},
        )
    ]

    analysis = analyze_discovery(conversation)

    if expected_issue_id is None:
        assert analysis.next_issue is None
        return

    assert analysis.next_issue is not None
    assert analysis.next_issue.issue_id == expected_issue_id
    assert analysis.next_issue.suggestion is not None
    assert analysis.next_issue.suggestion.question_id == expected_question_id


@pytest.mark.parametrize(
    ("prompt", "expected_slots"),
    [
        (
            "Bygg ett flöde som genererar en DOCX-rapport från uppladdade PDF-dokument.",
            [
                ("primary_runtime_input", "documents", "heuristic"),
                ("terminal_output", "docx_document", "heuristic"),
                ("docx_output_mode", "generated_docx", "policy_default"),
                (
                    "document_material_scope",
                    "flexible_document_case",
                    "policy_default",
                ),
                ("post_processing_goal", "structure_key_information", "heuristic"),
            ],
        ),
        (
            "Bygg ett flöde som genererar en DOCX-rapport utan mall från uppladdade PDF-dokument.",
            [
                ("primary_runtime_input", "documents", "heuristic"),
                ("terminal_output", "docx_document", "heuristic"),
                ("docx_output_mode", "generated_docx", "heuristic"),
                (
                    "document_material_scope",
                    "flexible_document_case",
                    "policy_default",
                ),
                ("post_processing_goal", "structure_key_information", "heuristic"),
            ],
        ),
        (
            "Bygg ett flöde som fyller en DOCX-mall med data från uppladdade PDF-dokument.",
            [
                ("primary_runtime_input", "documents", "heuristic"),
                ("terminal_output", "docx_document", "heuristic"),
                ("docx_output_mode", "template_fill_docx", "heuristic"),
                (
                    "document_material_scope",
                    "flexible_document_case",
                    "policy_default",
                ),
                ("post_processing_goal", "extract_key_information", "heuristic"),
            ],
        ),
    ],
)
def test_docx_output_deterministic_slots(
    prompt: str,
    expected_slots: list[tuple[str, str, str]],
) -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content=prompt,
            metadata={"ui_language": "sv"},
        )
    ]

    state = build_planning_state_from_conversation(conversation)

    assert [
        (slot.name, slot.value, slot.source) for slot in state.resolved_slots.values()
    ] == expected_slots


def test_generated_docx_without_template_excludes_docx_mode_question() -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content=(
                "Bygg ett flöde som genererar en DOCX-rapport utan mall från uppladdade PDF-dokument."
            ),
            metadata={"ui_language": "sv"},
        )
    ]

    question_ids = _question_ids_for(conversation)

    assert "docx_output_mode" not in question_ids
    assert "final_pdf_type" not in question_ids


def test_docx_template_excludes_docx_mode_question() -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content=(
                "Bygg ett flöde som fyller en DOCX-mall med data från uppladdade PDF-dokument."
            ),
            metadata={"ui_language": "sv"},
        )
    ]

    question_ids = _question_ids_for(conversation)

    assert "docx_output_mode" not in question_ids
    assert "pdf_generation_mode" not in question_ids
