from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_runtime_input_fields import (
    extract_runtime_input_field_hints,
    extract_runtime_input_field_hints_for_metadata_state,
    infer_runtime_metadata_slot,
    runtime_input_fields_declared_absent,
)


def test_runtime_input_field_extraction_understands_explicit_absence() -> None:
    text = (
        "Skapa ett enkelt flöde som tar emot en kundfråga i text. "
        "Inga extra inmatningsfält behövs."
    )

    assert runtime_input_fields_declared_absent(text)
    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) == "no_extra_metadata"


def test_runtime_input_field_extraction_understands_bare_absence() -> None:
    text = "Skapa ett enkelt flöde för kundfrågor. Inga inmatningsfält."

    assert runtime_input_fields_declared_absent(text)
    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) == "no_extra_metadata"


def test_runtime_input_field_extraction_understands_bare_metadata_absence() -> None:
    text = "Skapa ett rapportflöde. Ingen metadata behövs vid körning."

    assert runtime_input_fields_declared_absent(text)
    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) == "no_extra_metadata"


def test_runtime_input_field_extraction_understands_english_bare_absence() -> None:
    text = "Create a simple customer reply flow. No input fields."

    assert runtime_input_fields_declared_absent(text)
    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) == "no_extra_metadata"


def test_runtime_input_field_extraction_does_not_match_partial_words() -> None:
    text = "Inmatningsfältet behövs inte. Skapa ett svar direkt från frågan."

    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) is None


def test_runtime_input_field_extraction_keeps_explicit_secondary_fields() -> None:
    hints = extract_runtime_input_field_hints(
        "Använd inmatningsfält för målgrupp och rapportnivå vid körning, "
        "och skapa rapport."
    )

    assert [(hint.variable_name, hint.label) for hint in hints] == [
        ("malgrupp", "målgrupp"),
        ("rapportniva", "rapportnivå"),
    ]
    assert (
        infer_runtime_metadata_slot(
            "Använd inmatningsfält för målgrupp och rapportnivå vid körning."
        )
        == "detailed_case_metadata"
    )


def test_runtime_input_field_extraction_understands_user_provided_metadata() -> None:
    text = (
        "Jag vill skapa ett transkriptionsflöde för utvecklingssamtal. "
        "Användaren kommer att ange namn, personnummer, yrke, roll och "
        "nuvarande lön innan ljudet analyseras."
    )

    hints = extract_runtime_input_field_hints(text)

    assert [(hint.variable_name, hint.label) for hint in hints] == [
        ("namn", "namn"),
        ("personnummer", "personnummer"),
        ("yrke", "yrke"),
        ("roll", "roll"),
        ("nuvarande_lon", "nuvarande lön"),
    ]
    assert infer_runtime_metadata_slot(text) == "detailed_case_metadata"


def test_runtime_input_field_extraction_keeps_bare_metadata_as_basic_intent() -> None:
    text = "Skapa ett rapportflöde med grundläggande metadata vid körning."

    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) == "basic_case_metadata"


def test_runtime_input_field_extraction_does_not_treat_bare_metadata_as_runtime_intent() -> (
    None
):
    text = "Extrahera metadata från dokumentet och sammanfatta innehållet."

    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) is None


def test_runtime_input_field_extraction_cleans_natural_swedish_field_phrases() -> None:
    text = (
        "Vi kommer att ange namn på medarbetaren, personnummer, vilket yrke "
        "den har, vilken roll den har och vad den har i lön nuvarande."
    )

    hints = extract_runtime_input_field_hints(text)

    assert [(hint.variable_name, hint.label) for hint in hints] == [
        ("medarbetar_namn", "medarbetar namn"),
        ("personnummer", "personnummer"),
        ("yrke", "yrke"),
        ("roll", "roll"),
        ("nuvarande_lon", "nuvarande lön"),
    ]


def test_runtime_input_field_extraction_understands_english_user_metadata() -> None:
    text = (
        "Create an audio review flow. We will provide name, social security "
        "number, role and salary before the recording is processed."
    )

    hints = extract_runtime_input_field_hints(text)

    assert [(hint.variable_name, hint.label) for hint in hints] == [
        ("name", "name"),
        ("social_security_number", "social security number"),
        ("role", "role"),
        ("salary", "salary"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Användaren ska ange intern referens, prioritet och ansvarig avdelning.",
        "We will provide supplier name, contract id and renewal date.",
        "Användaren kommer att ange namn, personnummer, yrke och roll.",
        "Use input fields for audience and detail level at runtime.",
        "Lägg till formulärfält för målgrupp och rapportnivå.",
    ],
)
def test_detailed_runtime_metadata_always_has_field_hints(text: str) -> None:
    assert infer_runtime_metadata_slot(text) == "detailed_case_metadata"
    assert extract_runtime_input_field_hints(text)


def test_runtime_input_field_extraction_ignores_output_field_lists() -> None:
    text = (
        "Transkribera samtalet och extrahera namn, personnummer, yrke, roll "
        "och nuvarande lön från inspelningen."
    )

    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) is None


def test_runtime_input_field_extraction_ignores_source_content_lists() -> None:
    text = "Samtalet innehåller namn, personnummer, yrke, roll och nuvarande lön."

    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) is None


def test_runtime_input_field_extraction_lets_newer_positive_instruction_win() -> None:
    text = (
        "Inga extra inmatningsfält behövs. "
        "Lägg sedan till inmatningsfält för målgrupp vid körning."
    )

    hints = extract_runtime_input_field_hints(text)

    assert not runtime_input_fields_declared_absent(text)
    assert [(hint.variable_name, hint.label) for hint in hints] == [
        ("malgrupp", "målgrupp")
    ]


def test_runtime_input_field_extraction_uses_text_order_across_trigger_words() -> None:
    text = (
        "Inga extra inmatningsfält behövs. "
        "Lägg sedan till formulärfält för målgrupp vid körning."
    )

    hints = extract_runtime_input_field_hints(text)

    assert not runtime_input_fields_declared_absent(text)
    assert [(hint.variable_name, hint.label) for hint in hints] == [
        ("malgrupp", "målgrupp")
    ]


def test_runtime_metadata_policy_can_disable_free_text_hints() -> None:
    hints = extract_runtime_input_field_hints_for_metadata_state(
        "Use input fields for audience and detail level at runtime.",
        runtime_metadata_state="no_extra_metadata",
    )

    assert hints == ()
