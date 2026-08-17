import pytest
from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_event_models import (
    KeyDecisionPayload,
    RequirementsDisclosureContent,
    RequirementsSummaryPayload,
    ResolvedRequirementPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)


def _summary(key_decisions: list[KeyDecisionPayload]) -> RequirementsDisclosureContent:
    return RequirementsDisclosureContent(
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

    restored = RequirementsDisclosureContent.model_validate(
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
        RequirementsDisclosureContent(
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


@pytest.mark.parametrize("blank", ["", "   "])
@pytest.mark.parametrize("field", ["input_description", "output_description"])
def test_a_disclosure_cannot_leave_the_input_or_output_blank(
    field: str, blank: str
) -> None:
    """The card the user signs must name what goes in and what comes out."""
    content = {
        "summary": "Flödet ska ta emot ljud och leverera en PDF.",
        "key_decisions": [],
        "input_description": "Primär indata vid körning: Ljud.",
        "output_description": "Huvudsakligt slutresultat: PDF-dokument.",
        field: blank,
    }
    with pytest.raises(ValidationError):
        RequirementsDisclosureContent(**content)


def test_an_emitted_summary_must_name_itself() -> None:
    """A disclosure the client cannot name is one the user cannot confirm."""

    content = _summary([]).model_dump(mode="json")

    with pytest.raises(ValidationError):
        RequirementsSummaryPayload.model_validate(content)
    with pytest.raises(ValidationError):
        RequirementsSummaryPayload.model_validate(
            {**content, "requirements_version": "not-a-digest"}
        )
    assert RequirementsSummaryPayload.model_validate(
        {**content, "requirements_version": "a" * 64}
    ).requirements_version == ("a" * 64)


def _question(recommended_option_id: str | None) -> dict[str, object]:
    return {
        "question_id": "terminal_output",
        "question": "Vilket slutresultat ska flödet leverera?",
        "options": [
            {"id": "pdf_document", "label": "PDF", "value": "pdf_document"},
            {"id": "docx_document", "label": "Word", "value": "docx_document"},
        ],
        "selection_mode": "single",
        "allow_custom": False,
        "recommended_option_id": recommended_option_id,
    }


def test_a_recommendation_must_name_an_option_the_user_was_offered() -> None:
    """A recommendation nobody can select is not a choice Eneo can make."""

    assert (
        StructuredQuestionPayload.model_validate(
            _question("pdf_document")
        ).recommended_option_id
        == "pdf_document"
    )
    assert (
        StructuredQuestionPayload.model_validate(_question(None)).recommended_option_id
        is None
    )
    with pytest.raises(ValidationError):
        StructuredQuestionPayload.model_validate(_question("csv_document"))


def test_evidence_without_a_recommendation_is_not_a_payload() -> None:
    """A quote is the reason for a recommendation, so it cannot stand alone."""

    with pytest.raises(ValidationError):
        StructuredQuestionPayload.model_validate(
            {
                **_question(None),
                "recommended_option_evidence": "en kort sammanfattning",
            }
        )


def test_a_current_value_must_name_an_option_the_user_was_offered() -> None:
    """A current value the user cannot pick tells them nothing they can act on."""

    assert (
        StructuredQuestionPayload.model_validate(
            {**_question(None), "current_option_id": "docx_document"}
        ).current_option_id
        == "docx_document"
    )
    with pytest.raises(ValidationError):
        StructuredQuestionPayload.model_validate(
            {**_question(None), "current_option_id": "csv_document"}
        )


def test_a_recommendation_never_contradicts_the_value_the_flow_uses_today() -> None:
    # Badging a different value as Eneo's own reading turns a proposal to change
    # a running flow into a one-click confirmation. The payload cannot carry that
    # pair at all, so no owner can emit it.
    assert (
        StructuredQuestionPayload.model_validate(
            {**_question("pdf_document"), "current_option_id": "pdf_document"}
        ).recommended_option_id
        == "pdf_document"
    )
    with pytest.raises(ValidationError):
        StructuredQuestionPayload.model_validate(
            {**_question("docx_document"), "current_option_id": "pdf_document"}
        )


def test_a_question_persisted_before_the_number_existed_still_loads() -> None:
    # The pending question is replayed from persisted tool arguments to settle
    # a delegated answer. A number the old record cannot carry must not make
    # that payload unreadable.
    payload = StructuredQuestionPayload.model_validate(_question("pdf_document"))

    assert payload.question_index is None
    assert payload.recommended_option_evidence is None


def test_a_decision_makes_one_claim_about_where_it_came_from() -> None:
    """Provenance is one fact; two fields that can disagree are not one fact."""

    answered = KeyDecisionPayload.model_validate(
        {
            "topic": "Slutresultat",
            "decision": "PDF-dokument",
            "question_id": "terminal_output",
            "is_derived": False,
        }
    )
    assert (answered.question_id, answered.is_derived) == ("terminal_output", False)

    derived = KeyDecisionPayload.model_validate(
        {"topic": "Planerad bearbetning", "decision": "dokument till PDF"}
    )
    assert (derived.question_id, derived.is_derived) == (None, True)

    with pytest.raises(ValidationError):
        KeyDecisionPayload.model_validate(
            {
                "topic": "Slutresultat",
                "decision": "PDF-dokument",
                "question_id": "terminal_output",
                "is_derived": True,
            }
        )
    with pytest.raises(ValidationError):
        KeyDecisionPayload.model_validate(
            {
                "topic": "Slutresultat",
                "decision": "PDF-dokument",
                "is_derived": False,
            }
        )


def test_a_decision_cannot_point_at_a_question_that_cannot_be_asked() -> None:
    # Naming a question is an offer to go back to it. A name outside the
    # requirement vocabulary is a link to nowhere, which reads as a change the
    # user can make and is not.
    with pytest.raises(ValidationError):
        KeyDecisionPayload.model_validate(
            {
                "topic": "Slutresultat",
                "decision": "PDF-dokument",
                "question_id": "not-a-question",
                "is_derived": False,
            }
        )
