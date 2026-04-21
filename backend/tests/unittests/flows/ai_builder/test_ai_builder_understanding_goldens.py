"""Golden cases for AI Builder DOCX understanding behavior.

Phase 2 intentionally flips the previously characterized DOCX misroutes into
their desired DOCX-specific behavior. These tests now lock the corrected
discovery routing and resolved slot state so future changes stay explicit.
"""

from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_discovery import analyze_discovery
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_resolved_requirements import (
    build_resolved_requirements_state,
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
            None,
            None,
        ),
        (
            "Bygg ett flöde som genererar en DOCX-rapport utan mall från uppladdade PDF-dokument.",
            None,
            None,
        ),
        (
            "Bygg ett flöde som fyller en DOCX-mall med data från uppladdade PDF-dokument.",
            None,
            None,
        ),
    ],
)
def test_docx_output_characterization_cases(
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
            ],
        ),
        (
            "Bygg ett flöde som genererar en DOCX-rapport utan mall från uppladdade PDF-dokument.",
            [
                ("primary_runtime_input", "documents", "heuristic"),
                ("terminal_output", "docx_document", "heuristic"),
                ("docx_output_mode", "generated_docx", "heuristic"),
            ],
        ),
        (
            "Bygg ett flöde som fyller en DOCX-mall med data från uppladdade PDF-dokument.",
            [
                ("primary_runtime_input", "documents", "heuristic"),
                ("terminal_output", "docx_document", "heuristic"),
                ("docx_output_mode", "template_fill_docx", "heuristic"),
            ],
        ),
    ],
)
def test_docx_output_characterization_slots(
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

    state = build_resolved_requirements_state(conversation)

    assert [
        (slot.name, slot.value, slot.source) for slot in state.slots
    ] == expected_slots


def test_generated_docx_without_template_characterization_excludes_docx_mode_question() -> (
    None
):
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


def test_docx_template_characterization_excludes_docx_mode_question() -> None:
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
