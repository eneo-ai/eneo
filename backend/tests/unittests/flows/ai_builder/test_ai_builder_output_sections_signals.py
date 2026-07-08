from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_form_intake_signals import (
    SECTIONED_FORM_INTAKE_SIGNAL,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    extract_requested_output_sections,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            """
            Skapa ett flöde som får ett Word-dokument och skriver ett beslutsunderlag.

            Följande rubriker ska finnas med:

            Rubrik: Problem/nuläge
            Beskriv nuläget.

            Rubrik: Lösningsförslag/nyläge
            Beskriv lösningen.

            Rubrik: Resursåtgång
            Skriv resursbehov.

            Rubrik: Planerad tidplan
            Skriv tidplan.
            """,
            (
                "Problem/nuläge",
                "Lösningsförslag/nyläge",
                "Resursåtgång",
                "Planerad tidplan",
            ),
        ),
        (
            "Skapa en månadsrapport med rubrikerna Personalöversikt, "
            "Sjukfrånvaro, Rekrytering och Kompetensutveckling.",
            (
                "Personalöversikt",
                "Sjukfrånvaro",
                "Rekrytering",
                "Kompetensutveckling",
            ),
        ),
        (
            """
            Skapa en upphandlingsrapport. Rapporten ska innehålla:
            - Behovsanalys
            - Marknadsanalys
            - Kravbild
            - Risker
            - Rekommendation
            """,
            (
                "Behovsanalys",
                "Marknadsanalys",
                "Kravbild",
                "Risker",
                "Rekommendation",
            ),
        ),
        (
            """
            Create a project plan with the following sections:
            1. Scope
            2. Timeline
            3. Budget
            4. Risks
            5. Next steps
            """,
            ("Scope", "Timeline", "Budget", "Risks", "Next steps"),
        ),
        (
            """
            Generate a report using this structure:
            ```markdown
            ## Summary
            ## Current state
            ## Recommendation
            ## Risks
            ```
            """,
            ("Summary", "Current state", "Recommendation", "Risks"),
        ),
    ],
)
def test_extracts_requested_output_sections(
    text: str, expected: tuple[str, ...]
) -> None:
    result = extract_requested_output_sections(text)

    assert result.high_confidence
    assert result.sections == expected


@pytest.mark.parametrize(
    "text",
    [
        "Sammanfatta detta dokument kort.",
        "Översätt texten till engelska och behåll tonen.",
        (
            "Skapa ett formulär där användaren ska lämna fritext under varje "
            "rubrik: Bakgrund, Bedömning, Beslut och Uppföljning."
        ),
        "Write an email with a subject and a body.",
        "Fyll i DOCX-mallen med {{namn}}, {{datum}}, {{belopp}} och {{ansvarig}}.",
    ],
)
def test_does_not_overfire_for_non_report_section_requests(text: str) -> None:
    assert not extract_requested_output_sections(text).high_confidence


def test_three_sections_remains_low_confidence() -> None:
    result = extract_requested_output_sections(
        """
        Skapa en rapport med rubrikerna Bakgrund, Bedömning och Rekommendation.
        """
    )

    assert result.sections == ("Bakgrund", "Bedömning", "Rekommendation")
    assert not result.high_confidence


def test_four_sections_is_high_confidence() -> None:
    result = extract_requested_output_sections(
        """
        Skapa en rapport med rubrikerna Bakgrund, Bedömning, Risker och Rekommendation.
        """
    )

    assert result.sections == ("Bakgrund", "Bedömning", "Risker", "Rekommendation")
    assert result.high_confidence


def test_model_sectioned_form_intake_signal_suppresses_output_sections() -> None:
    result = extract_requested_output_sections(
        """
        Skapa ett dokument med rubrikerna Bakgrund, Bedömning, Risker och Beslut.
        """,
        model_form_intake_signals={SECTIONED_FORM_INTAKE_SIGNAL},
    )

    assert result.sections == ()
    assert not result.high_confidence
