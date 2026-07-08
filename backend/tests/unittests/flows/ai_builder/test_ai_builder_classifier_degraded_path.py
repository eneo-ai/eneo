from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.ai_builder import ai_builder_discovery_runtime
from eneo.flows.ai_builder.ai_builder_discovery import analyze_discovery
from eneo.flows.ai_builder.ai_builder_discovery_runtime import (
    build_runtime_discovery_context,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    ClassifiedSlot,
    SlotClassificationResult,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import LLM_RESOLVABLE_SLOT_NAMES
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.ai_builder.planning_state_builder import merge_llm_resolved_slots

KEYWORD_BASELINE_CASES = (
    pytest.param(
        "Jag vill transkribera ljud och få en PDF-rapport.",
        {
            "primary_runtime_input": "audio",
            "terminal_output": "pdf_document",
        },
        {"primary_runtime_input", "terminal_output"},
        id="audio-to-pdf-report",
    ),
    pytest.param(
        (
            "Jag vill ladda upp flera dokument och få en PDF-rapport med "
            "avsnitt per dokument och en samlad översikt."
        ),
        {
            "document_material_scope": "multiple_documents_case",
            "report_disposition": "both",
        },
        {"document_material_scope", "report_disposition"},
        id="multi-document-per-source-plus-overview",
    ),
    pytest.param(
        "Jag vill ladda upp text och plocka ut beslut, nästa steg och ansvariga.",
        {"post_processing_goal": "action_followup"},
        {"post_processing_goal"},
        id="action-followup",
    ),
    pytest.param(
        "Bygg ett flöde som tar JSON och extraherar fält till ny JSON.",
        {"structured_io_contract": "extract_or_compute_fields"},
        {"structured_io_contract"},
        id="json-field-extraction",
    ),
    pytest.param(
        (
            "Bygg ett flöde som tar ljud och användaren ska ange ärendenummer "
            "och handläggare vid körning."
        ),
        {"runtime_metadata_fields": "detailed_case_metadata"},
        {"runtime_metadata_fields"},
        id="runtime-metadata-fields",
    ),
)


def test_keyword_baseline_cases_cover_all_llm_resolvable_slots() -> None:
    covered_slots = {
        slot_name
        for _text, expected_slots, _forbidden_questions in (
            case.values for case in KEYWORD_BASELINE_CASES
        )
        for slot_name in expected_slots
    }

    assert covered_slots == LLM_RESOLVABLE_SLOT_NAMES


def _classifier_result_for(
    text: str,
    expected_slots: dict[str, str],
) -> SlotClassificationResult:
    return SlotClassificationResult(
        slots=tuple(
            ClassifiedSlot(
                slot_name=slot_name,
                value=value,
                confidence="high",
                reason="understanding eval golden",
                evidence=(text,),
            )
            for slot_name, value in expected_slots.items()
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected_slots", "forbidden_questions"),
    KEYWORD_BASELINE_CASES,
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected_slots", "forbidden_questions"),
    KEYWORD_BASELINE_CASES,
)
async def test_classifier_primary_path_suppresses_keyword_baseline_questions(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    expected_slots: dict[str, str],
    forbidden_questions: set[str],
) -> None:
    async def classifier_result(**kwargs: object) -> SlotClassificationResult:
        allowed_slot_values = kwargs["allowed_slot_values"]
        assert isinstance(allowed_slot_values, dict)
        assert expected_slots.keys() <= allowed_slot_values.keys()
        return _classifier_result_for(text, expected_slots)

    monkeypatch.setattr(
        ai_builder_discovery_runtime,
        "classify_slots",
        classifier_result,
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

    assert context.slot_classification_result is not None
    for slot_name, expected_value in expected_slots.items():
        slot = context.planning_state.resolved_slots[slot_name]
        assert slot.value == expected_value
        assert slot.source == "model"
    assert forbidden_questions.isdisjoint(analysis.selected_question_ids)


@pytest.mark.parametrize(
    ("text", "expected_slots", "_forbidden_questions"),
    KEYWORD_BASELINE_CASES,
)
def test_keyword_baseline_cases_are_classifier_shape_ready(
    text: str,
    expected_slots: dict[str, str],
    _forbidden_questions: set[str],
) -> None:
    state = PlanningState.empty()

    merge_llm_resolved_slots(
        state,
        _classifier_result_for(text, expected_slots),
        prompt_hash="a" * 64,
        freeform_text=text,
    )

    for slot_name, expected_value in expected_slots.items():
        assert state.resolved_slots[slot_name].value == expected_value
        assert state.resolved_slots[slot_name].source == "model"
