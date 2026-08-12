from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    BASIC_RUNTIME_METADATA,
    DETAILED_RUNTIME_METADATA,
    NO_EXTRA_RUNTIME_METADATA,
    infer_runtime_metadata_slot,
    normalize_runtime_metadata_state,
    runtime_input_fields_declared_absent,
    runtime_input_fields_requested,
    runtime_metadata_allows_input_fields,
    runtime_metadata_disables_declared_input_fields,
)
from eneo.flows.ai_builder.planning_state import SlotConfidence, SlotSource
from eneo.flows.ai_builder.question_catalog import legal_slot_values


def test_runtime_metadata_state_constants_match_question_catalog() -> None:
    assert {
        NO_EXTRA_RUNTIME_METADATA,
        BASIC_RUNTIME_METADATA,
        DETAILED_RUNTIME_METADATA,
    } == legal_slot_values("runtime_metadata_fields")


def test_runtime_metadata_policy_allows_fields_only_for_metadata_states() -> None:
    assert not runtime_metadata_allows_input_fields(NO_EXTRA_RUNTIME_METADATA)
    assert runtime_metadata_allows_input_fields(BASIC_RUNTIME_METADATA)
    assert runtime_metadata_allows_input_fields(DETAILED_RUNTIME_METADATA)
    assert normalize_runtime_metadata_state("unknown") is None


@pytest.mark.parametrize(
    ("source", "confidence", "expected"),
    [
        ("structured_answer", "high", True),
        ("structured_answer", "low", True),
        ("requirements_summary", "high", True),
        ("requirements_summary", "low", True),
        ("flow_default", "high", False),
        ("flow_default", "low", False),
        ("policy_default", "high", False),
        ("policy_default", "low", False),
        ("heuristic", "high", True),
        ("heuristic", "low", False),
        ("model", "high", True),
        ("model", "low", False),
    ],
)
def test_runtime_metadata_declared_field_suppression_is_source_aware(
    source: SlotSource,
    confidence: SlotConfidence,
    *,
    expected: bool,
) -> None:
    assert (
        runtime_metadata_disables_declared_input_fields(
            state=NO_EXTRA_RUNTIME_METADATA,
            source=source,
            confidence=confidence,
        )
        is expected
    )
    for state in (BASIC_RUNTIME_METADATA, DETAILED_RUNTIME_METADATA, None):
        assert not runtime_metadata_disables_declared_input_fields(
            state=state,
            source=source,
            confidence=confidence,
        )


@pytest.mark.parametrize(
    "text",
    [
        "Inga extra inmatningsfält behövs.",
        "Inmatningsfält krävs inte.",
        "No input fields are needed.",
        "Runtime metadata: No extra fields.",
        "Användaren ska inte fylla i formulärfält vid körning.",
    ],
)
def test_runtime_input_field_absence_is_explicit_and_coarse(text: str) -> None:
    assert runtime_input_fields_declared_absent(text)
    assert not runtime_input_fields_requested(text)
    assert infer_runtime_metadata_slot(text) == NO_EXTRA_RUNTIME_METADATA


@pytest.mark.parametrize(
    "text",
    [
        "Användaren ska ange ärendenummer och prioritet vid körning.",
        "The user should provide case number and priority at runtime.",
        "Use input fields for audience and detail level.",
        "Lägg till formulärfält för målgrupp och rapportnivå.",
        "I will provide name and salary before the recording is processed.",
    ],
)
def test_runtime_input_field_request_infers_only_basic_metadata(text: str) -> None:
    assert not runtime_input_fields_declared_absent(text)
    assert runtime_input_fields_requested(text)
    assert infer_runtime_metadata_slot(text) == BASIC_RUNTIME_METADATA


def test_bare_basic_metadata_remains_basic_intent() -> None:
    text = "Skapa ett rapportflöde med grundläggande metadata vid körning."

    assert runtime_input_fields_requested(text)
    assert infer_runtime_metadata_slot(text) == BASIC_RUNTIME_METADATA


@pytest.mark.parametrize(
    "text",
    [
        "Extrahera metadata från dokumentet och sammanfatta innehållet.",
        "Rapportens rubriker ska hämtas från dokumentet.",
        "The user reviews customer name before approval.",
        "Inmatningsfältet behövs inte.",
    ],
)
def test_non_runtime_field_text_does_not_infer_metadata(text: str) -> None:
    assert not runtime_input_fields_requested(text)
    assert infer_runtime_metadata_slot(text) is None


def test_newer_positive_runtime_field_instruction_wins() -> None:
    text = (
        "Inga extra inmatningsfält behövs. "
        "Lägg sedan till formulärfält för målgrupp vid körning."
    )

    assert not runtime_input_fields_declared_absent(text)
    assert runtime_input_fields_requested(text)
    assert infer_runtime_metadata_slot(text) == BASIC_RUNTIME_METADATA


def test_runtime_metadata_state_normalizes_catalog_values() -> None:
    assert normalize_runtime_metadata_state("no_extra_metadata") == (
        NO_EXTRA_RUNTIME_METADATA
    )
    assert normalize_runtime_metadata_state("basic_runtime_metadata") == (
        BASIC_RUNTIME_METADATA
    )
    assert normalize_runtime_metadata_state("detailed_runtime_metadata") == (
        DETAILED_RUNTIME_METADATA
    )
