from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    BASIC_RUNTIME_METADATA,
    DETAILED_RUNTIME_METADATA,
    NO_EXTRA_RUNTIME_METADATA,
    extract_runtime_input_field_hints,
    infer_runtime_metadata_slot,
    normalize_runtime_metadata_state,
    runtime_input_fields_declared_absent,
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
    assert not runtime_metadata_disables_declared_input_fields(
        state=BASIC_RUNTIME_METADATA,
        source=source,
        confidence=confidence,
    )
    assert not runtime_metadata_disables_declared_input_fields(
        state=DETAILED_RUNTIME_METADATA,
        source=source,
        confidence=confidence,
    )
    assert not runtime_metadata_disables_declared_input_fields(
        state=None,
        source=source,
        confidence=confidence,
    )


def test_runtime_input_field_extraction_understands_explicit_absence() -> None:
    text = (
        "Skapa ett enkelt flöde som tar emot en kundfråga i text. "
        "Inga extra inmatningsfält behövs."
    )

    assert runtime_input_fields_declared_absent(text)
    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) == NO_EXTRA_RUNTIME_METADATA


@pytest.mark.parametrize(
    "text",
    [
        "Användaren ska ange inmatningsfält för Ärendenummer och Prioritet.",
        "The user should provide input fields for Case number and Priority.",
    ],
)
def test_named_user_fields_are_confirmed_evidence(text: str) -> None:
    hints = extract_runtime_input_field_hints(text)

    assert hints
    assert {hint.provenance for hint in hints} == {"user_confirmed"}


def test_runtime_input_field_extraction_understands_bare_absence() -> None:
    text = "Skapa ett enkelt flöde för kundfrågor. Inga inmatningsfält."

    assert runtime_input_fields_declared_absent(text)
    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) == NO_EXTRA_RUNTIME_METADATA


@pytest.mark.parametrize(
    "text",
    [
        "Metadata vid körning: Inga extra fält.",
        "Runtime metadata: No extra fields.",
    ],
)
def test_runtime_input_field_extraction_understands_extra_field_absence(
    text: str,
) -> None:
    assert runtime_input_fields_declared_absent(text)
    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) == NO_EXTRA_RUNTIME_METADATA


@pytest.mark.parametrize(
    "text",
    [
        "Skapa ett rapportflöde. Inmatningsfält behövs inte.",
        "Skapa ett rapportflöde. Inmatningsfält krävs inte.",
        "Create a report flow. Input fields are not needed.",
        "Create a report flow. Input fields are not required.",
    ],
)
def test_runtime_input_field_extraction_understands_post_trigger_negation(
    text: str,
) -> None:
    assert runtime_input_fields_declared_absent(text)
    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) == NO_EXTRA_RUNTIME_METADATA


def test_runtime_input_field_extraction_understands_negated_swedish_runtime_field_list() -> (
    None
):
    text = (
        "Användaren ska inte fylla i extra formulärfält, metadatafält eller "
        "inmatningsfält vid körning. Rapportfält som datum, språk i ljudet, "
        "namn, kontaktuppgifter, risker och osäkerheter ska hämtas från "
        "ljudet och transkriberingen."
    )

    assert runtime_input_fields_declared_absent(text)
    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) == NO_EXTRA_RUNTIME_METADATA


def test_runtime_input_field_extraction_ignores_source_derived_report_field_lists() -> (
    None
):
    text = (
        "Alla rapportfält ska hämtas från ljudet/transkriberingen: datum, "
        "källa, språk i ljudet, ljudkvalitet, namn, kontaktuppgifter, risker "
        "och osäkerheter. Om något saknas ska rapporten skriva Ej nämnt i "
        "underlaget."
    )

    assert not runtime_input_fields_declared_absent(text)
    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) is None


def test_runtime_input_field_extraction_ignores_source_derived_paraphrases() -> None:
    text = (
        "Rapportfält kommer ur transkriptet och tas från ljudinspelningen: "
        "datum, källa, namn, kontaktuppgifter, risker och osäkerheter."
    )

    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) is None


def test_runtime_input_field_extraction_ignores_document_heading_output_fields() -> (
    None
):
    text = (
        "Rapportens rubriker ska hämtas från dokumentet och varje avsnitt "
        "ska baseras på worddokumentet."
    )

    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) is None


def test_runtime_input_field_extraction_ignores_swedish_document_section_template() -> (
    None
):
    text = (
        "Skapa ett flöde som ska få ett worddokument uppladdat som input. "
        "Varje rubrik och text skall skrivas utifrån det ursprungliga "
        "dokumentet som helhet varje gång. Rubrik: Resursåtgång i form av "
        "tidsuppskattning och personella resurser. Ange i nedan tabell vilka "
        "roller/kompetenser du bedömer kommer behövas för att genomföra "
        "lösningsförslaget. Rubrik: Ekonomisk nytta och kostnader. Om en "
        "nyttokalkyl EJ upprättas ska istället följande anges i detta "
        "avsnitt: Ange beräknad totalkostnad för genomförandet av "
        "lösningsförslaget. Summera kostnaderna för de resurser som listas i "
        "avsnitt 2.1, samt ange och lägg till eventuella övriga kostnader."
    )

    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) is None


@pytest.mark.parametrize(
    "text",
    [
        (
            "Rubrik: Resursåtgång i form av tidsuppskattning och personella "
            "resurser. Ange i nedan tabell vilka roller/kompetenser som behövs."
        ),
        (
            "I sådana fall räcker det att fylla i kostnader i avsnitt, samt "
            "beskriva den kvalitativa nyttan i avsnitt."
        ),
        (
            "Om en nyttokalkyl EJ upprättas ska istället följande anges i "
            "detta avsnitt: Ange beräknad totalkostnad för genomförandet."
        ),
    ],
)
def test_runtime_input_field_extraction_ignores_report_template_imperatives(
    text: str,
) -> None:
    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) is None


def test_runtime_input_field_extraction_preserves_runtime_fields_with_source_report_fields() -> (
    None
):
    text = (
        "Användaren ska fylla i ärendenummer vid körning. Alla rapportfält "
        "ska hämtas från ljudet/transkriberingen: datum, källa, namn, "
        "kontaktuppgifter, risker och osäkerheter."
    )

    assert [
        (hint.variable_name, hint.label)
        for hint in extract_runtime_input_field_hints(text)
    ] == [("arendenummer", "ärendenummer")]
    assert infer_runtime_metadata_slot(text) == DETAILED_RUNTIME_METADATA


def test_runtime_input_field_extraction_preserves_real_swedish_runtime_fields() -> None:
    text = (
        "Användaren ska fylla i ärendenummer och ansvarig enhet vid körning "
        "innan ljudet analyseras."
    )

    assert not runtime_input_fields_declared_absent(text)
    assert [
        (hint.variable_name, hint.label)
        for hint in extract_runtime_input_field_hints(text)
    ] == [
        ("arendenummer", "ärendenummer"),
        ("ansvarig_enhet", "ansvarig enhet"),
    ]
    assert infer_runtime_metadata_slot(text) == DETAILED_RUNTIME_METADATA


def test_runtime_input_field_extraction_understands_bare_metadata_absence() -> None:
    text = "Skapa ett rapportflöde. Ingen metadata behövs vid körning."

    assert runtime_input_fields_declared_absent(text)
    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) == NO_EXTRA_RUNTIME_METADATA


def test_runtime_input_field_extraction_understands_english_bare_absence() -> None:
    text = "Create a simple customer reply flow. No input fields."

    assert runtime_input_fields_declared_absent(text)
    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) == NO_EXTRA_RUNTIME_METADATA


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
        == DETAILED_RUNTIME_METADATA
    )


def test_runtime_input_field_extraction_handles_optional_checklist_or_rule() -> None:
    text = (
        "Vid körning laddar jag upp en ansökan och kan också ange vilken "
        "checklista eller regel som ska användas."
    )

    assert [
        (hint.variable_name, hint.label)
        for hint in extract_runtime_input_field_hints(text)
    ] == [
        ("checklista", "checklista"),
        ("regel", "regel"),
    ]
    assert infer_runtime_metadata_slot(text) == DETAILED_RUNTIME_METADATA


def test_runtime_input_field_extraction_stops_before_report_writing_clause() -> None:
    hints = extract_runtime_input_field_hints(
        "Bygg ett flöde som använder inmatningsfält för målgrupp vid körning "
        "och skriver en rapport."
    )

    assert [(hint.variable_name, hint.label) for hint in hints] == [
        ("malgrupp", "målgrupp")
    ]


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
    assert infer_runtime_metadata_slot(text) == DETAILED_RUNTIME_METADATA


def test_runtime_input_field_extraction_keeps_bare_metadata_as_basic_intent() -> None:
    text = "Skapa ett rapportflöde med grundläggande metadata vid körning."

    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) == BASIC_RUNTIME_METADATA


def test_runtime_input_field_extraction_keeps_required_not_optional_positive() -> None:
    text = "Create a report flow. Input fields are required, not optional."

    assert not runtime_input_fields_declared_absent(text)
    assert infer_runtime_metadata_slot(text) != NO_EXTRA_RUNTIME_METADATA


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


def test_runtime_input_field_extraction_accepts_uppercase_english_i_actor() -> None:
    text = "I will provide name and salary before the recording is processed."

    hints = extract_runtime_input_field_hints(text)

    assert [(hint.variable_name, hint.label) for hint in hints] == [
        ("name", "name"),
        ("salary", "salary"),
    ]
    assert infer_runtime_metadata_slot(text) == DETAILED_RUNTIME_METADATA


@pytest.mark.parametrize(
    ("text", "expected_fields"),
    [
        (
            (
                "Create a flow where the user supplies customer name, "
                "analysis request, and optional uploaded files, then the flow "
                "produces a structured answer."
            ),
            [
                ("customer_name", "customer name"),
                ("analysis_request", "analysis request"),
            ],
        ),
        (
            "The user provided case id and business unit before analysis.",
            [("case_id", "case id"), ("business_unit", "business unit")],
        ),
        (
            "Users are providing supplier name and renewal date at runtime.",
            [("supplier_name", "supplier name"), ("renewal_date", "renewal date")],
        ),
        (
            "The user specifies priority and due date.",
            [("priority", "priority"), ("due_date", "due date")],
        ),
        (
            "The user filled in region and channel before approval.",
            [("region", "region"), ("channel", "channel")],
        ),
    ],
)
def test_runtime_input_field_extraction_understands_english_action_inflections(
    text: str,
    expected_fields: list[tuple[str, str]],
) -> None:
    hints = extract_runtime_input_field_hints(text)

    observed = [(hint.variable_name, hint.label) for hint in hints]
    for expected in expected_fields:
        assert expected in observed
    assert infer_runtime_metadata_slot(text) == DETAILED_RUNTIME_METADATA


@pytest.mark.parametrize(
    "text",
    [
        "The user reviews customer name and analysis request before approval.",
        "The user reads customer name from the document before approval.",
    ],
)
def test_runtime_input_field_extraction_ignores_user_actor_non_input_actions(
    text: str,
) -> None:
    assert extract_runtime_input_field_hints(text) == ()
    assert infer_runtime_metadata_slot(text) is None


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
    assert infer_runtime_metadata_slot(text) == DETAILED_RUNTIME_METADATA
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
