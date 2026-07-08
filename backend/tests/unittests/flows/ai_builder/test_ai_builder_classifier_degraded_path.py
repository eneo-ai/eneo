from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.ai_builder import ai_builder_discovery_runtime
from eneo.flows.ai_builder.ai_builder_discovery import analyze_discovery
from eneo.flows.ai_builder.ai_builder_discovery_runtime import (
    build_runtime_discovery_context,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected_slots", "forbidden_questions"),
    [
        (
            "Jag vill transkribera ljud och få en PDF-rapport.",
            {
                "primary_runtime_input": "audio",
                "terminal_output": "pdf_document",
            },
            {"primary_runtime_input", "terminal_output"},
        ),
        (
            (
                "Jag vill ladda upp flera dokument och få en PDF-rapport med "
                "avsnitt per dokument och en samlad översikt."
            ),
            {
                "document_material_scope": "multiple_documents_case",
                "report_disposition": "both",
            },
            {"document_material_scope", "report_disposition"},
        ),
        (
            "Jag vill ladda upp text och plocka ut beslut, nästa steg och ansvariga.",
            {"post_processing_goal": "action_followup"},
            {"post_processing_goal"},
        ),
        (
            "Bygg ett flöde som tar JSON och extraherar fält till ny JSON.",
            {"structured_io_contract": "extract_or_compute_fields"},
            {"structured_io_contract"},
        ),
        (
            (
                "Bygg ett flöde som tar ljud och användaren ska ange ärendenummer "
                "och handläggare vid körning."
            ),
            {"runtime_metadata_fields": "detailed_case_metadata"},
            {"runtime_metadata_fields"},
        ),
    ],
)
async def test_classifier_outage_keeps_deterministic_slot_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    expected_slots: dict[str, str],
    forbidden_questions: set[str],
) -> None:
    async def classifier_outage(**_: object) -> None:
        return None

    monkeypatch.setattr(
        ai_builder_discovery_runtime,
        "classify_slots",
        classifier_outage,
    )
    conversation = [
        ConversationMessage(
            role="user",
            content=text,
            metadata={"ui_language": "sv"},
        )
    ]

    context = await build_runtime_discovery_context(
        conversation,
        litellm_client=object(),
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        ui_language="sv",
    )
    analysis = analyze_discovery(
        conversation,
        planning_state=context.planning_state,
        slot_classification_result=context.slot_classification_result,
    )

    assert context.slot_classification_result is None
    for slot_name, expected_value in expected_slots.items():
        assert context.planning_state.resolved_slots[slot_name].value == expected_value
    assert forbidden_questions.isdisjoint(analysis.selected_question_ids)
