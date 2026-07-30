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
        (
            """
            Skapa en rapport med strukturen nedan:
            ```markdown
            ## Sammanfattning
            ## Nuläge
            ## Rekommendation
            ## Risker
            ```
            """,
            ("Sammanfattning", "Nuläge", "Rekommendation", "Risker"),
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


@pytest.mark.parametrize(
    "authoring_spec",
    [
        """
        Bygg ett flöde som granskar ljud, strukturerar analysen och levererar
        en slutrapport som DOCX.

        ## Indata och avgränsning
        Ljudfilen är flödets primära underlag.

        ## Uppgift 1: transkribera
        Gör talet sökbart och låt en människa korrigera resultatet.

        ## Uppgift 2: analysera
        Samla stabila observationer i ett strukturerat resultat.

        ## Uppgift 3: skriv dokumentet
        Skriv ett sammanhållet dokument från analysen.

        ## Leverans
        Rendera den färdiga texten till DOCX.
        """,
        """
        Build a flow that examines uploaded evidence and delivers a final report.

        ## Runtime input
        The uploaded source document is the primary material.

        ## Task 1: extract evidence
        Extract grounded facts and risks from the source.

        ## Task 2: draft and review
        Draft the report and let the case owner edit it.

        ## Task 3: quality control
        Check the claims and let a reviewer approve the result.

        ## Delivery workflow
        Finalize the complete document and render it as DOCX.
        """,
    ],
)
def test_authoring_spec_headings_are_not_final_report_sections(
    authoring_spec: str,
) -> None:
    result = extract_requested_output_sections(authoring_spec)

    assert result.sections == ()
    assert not result.high_confidence


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


def test_confirmed_example_headings_use_the_shared_section_projection() -> None:
    result = extract_requested_output_sections(
        "",
        confirmed_headings=("Summary", "Decision", "Next steps"),
    )

    assert result.sections == ("Summary", "Decision", "Next steps")
    assert result.high_confidence


def test_confirmed_example_headings_merge_after_direct_user_headings() -> None:
    result = extract_requested_output_sections(
        """
        Create a report with the following headings:
        Heading: Overview
        Heading: Decision
        Heading: Risks
        Heading: Actions
        """,
        confirmed_headings=("Decision", "Appendix"),
    )

    assert result.sections == (
        "Overview",
        "Decision",
        "Risks",
        "Actions",
        "Appendix",
    )
    assert result.high_confidence
