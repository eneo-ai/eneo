import pytest
from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_event_models import (
    KeyDecisionPayload,
    RequirementsSummaryPayload,
    ResolvedRequirementPayload,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)


def _summary(key_decisions: list[KeyDecisionPayload]) -> RequirementsSummaryPayload:
    return RequirementsSummaryPayload(
        summary="Flödet ska ta emot ljud och leverera en PDF.",
        key_decisions=key_decisions,
        input_description="Primär indata vid körning: Ljud.",
        output_description="Huvudsakligt slutresultat: PDF-dokument.",
    )


def test_requirements_summary_keeps_one_decision_per_topic() -> None:
    summary = _summary(
        [
            KeyDecisionPayload(topic="PDF-resultat", decision="Vanlig genererad PDF"),
            KeyDecisionPayload(topic="Indata vid körning", decision="Ljud"),
            KeyDecisionPayload(topic="PDF-resultat", decision="Vanlig genererad PDF"),
            KeyDecisionPayload(topic="Indata vid körning", decision="Ljud"),
            KeyDecisionPayload(
                topic="Metadata vid körning", decision="Inga extra fält"
            ),
        ]
    )

    assert [decision.topic for decision in summary.key_decisions] == [
        "PDF-resultat",
        "Indata vid körning",
        "Metadata vid körning",
    ]


def test_requirements_summary_keeps_first_decision_for_a_repeated_topic() -> None:
    summary = _summary(
        [
            KeyDecisionPayload(topic="Bearbetning", decision="Skapa PDF"),
            KeyDecisionPayload(topic="Bearbetning", decision="Skapa DOCX"),
        ]
    )

    assert len(summary.key_decisions) == 1
    assert summary.key_decisions[0].decision == "Skapa PDF"


def test_requirements_summary_preserves_distinct_decisions_in_order() -> None:
    summary = _summary(
        [
            KeyDecisionPayload(topic="Indata vid körning", decision="Ljud"),
            KeyDecisionPayload(topic="Slutresultat", decision="PDF-dokument"),
            KeyDecisionPayload(topic="Planerad bearbetning", decision="Skapa PDF"),
        ]
    )

    assert [decision.topic for decision in summary.key_decisions] == [
        "Indata vid körning",
        "Slutresultat",
        "Planerad bearbetning",
    ]


def test_requirements_summary_keeps_first_resolved_value_per_requirement() -> None:
    summary = _summary([]).model_copy(
        update={
            "resolved_requirements": [
                ResolvedRequirementPayload(
                    requirement_id="terminal_output",
                    selected_value="structured_text",
                ),
                ResolvedRequirementPayload(
                    requirement_id="terminal_output",
                    selected_value="pdf_document",
                ),
                ResolvedRequirementPayload(
                    requirement_id="runtime_metadata_fields",
                    selected_value="no_extra_metadata",
                ),
            ]
        }
    )

    restored = RequirementsSummaryPayload.model_validate(
        summary.model_dump(mode="json")
    )

    assert [
        (requirement.requirement_id, requirement.selected_value)
        for requirement in restored.resolved_requirements
    ] == [
        ("terminal_output", "structured_text"),
        ("runtime_metadata_fields", "no_extra_metadata"),
    ]


def test_requirements_summary_bounds_resolved_requirement_projection() -> None:
    with pytest.raises(ValidationError):
        RequirementsSummaryPayload(
            summary="Checkpoint ready.",
            key_decisions=[],
            input_description="Input confirmed.",
            output_description="Output confirmed.",
            resolved_requirements=[
                ResolvedRequirementPayload(
                    requirement_id=f"slot_{index}",
                    selected_value="value",
                )
                for index in range(len(KNOWN_REQUIREMENT_SLOT_NAMES) + 1)
            ],
        )
