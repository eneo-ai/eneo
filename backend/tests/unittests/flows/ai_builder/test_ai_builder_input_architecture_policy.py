from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
    resolve_input_intent,
)


def test_resolve_input_intent_prefers_audio_for_transcribe_conversation_with_pdf_output() -> (
    None
):
    intent = resolve_input_intent(
        (
            "Jag vill bygga ett flöde som hjälper till att transkribera ett "
            "medarbetarsamtal mellan en medarbetare och en chef. I slutet vill jag ha "
            "sammanfattningen och vad vi kom fram till och viktiga detaljer och vad vi "
            "ska uppfölja inför nästa år. Det räcker med en pdf fil."
        ),
        {},
    )

    assert intent.primary_runtime_input == "audio"
    assert intent.audio_requested is True
    assert intent.document_runtime_input_requested is False
    assert intent.needs_architecture_clarification is False


def test_resolve_input_intent_requires_architecture_for_audio_and_document_upload() -> (
    None
):
    intent = resolve_input_intent(
        "Jag vill transkribera ljud och samtidigt ladda upp dokument i samma körning.",
        {},
    )

    assert intent.audio_requested is True
    assert intent.document_runtime_input_requested is True
    assert intent.needs_architecture_clarification is True


def test_resolve_input_intent_treats_transcript_as_text_not_audio() -> None:
    intent = resolve_input_intent(
        "Sammanfatta en befintlig transkribering av ett medarbetarsamtal och skapa en PDF.",
        {},
    )

    assert intent.primary_runtime_input == "text"
    assert intent.audio_requested is False
    assert intent.needs_architecture_clarification is False


def test_resolve_input_intent_does_not_treat_keywords_as_word_document_signal() -> None:
    intent = resolve_input_intent(
        (
            "Jag vill börja bygga ett flöde där jag kommer skicka in en ljudfil som du ska "
            "transkribera sen ska du sammanfatta det och ge mig en strukturerad rapport med "
            "dom viktigaste keywords och själva ämnet. Vilka namn som förekommer och om det "
            "förekommer ett datum och själva ämnet av samtalet också."
        ),
        {},
    )

    assert intent.primary_runtime_input == "audio"
    assert intent.audio_requested is True
    assert intent.document_runtime_input_requested is False
    assert intent.needs_architecture_clarification is False


def test_resolve_input_intent_prefers_explicit_audio_upload_over_docx_output() -> None:
    intent = resolve_input_intent(
        (
            "Bygg ett flöde där användaren laddar upp en ljudfil vid körning. "
            "Flödet ska först transkribera ljudfilen till svensk text. "
            "DOCX-resultatet ska innehålla mötets rubriker. "
            "Slutresultatet ska vara ett Word-dokument."
        ),
        {},
    )

    assert intent.primary_runtime_input == "audio"
    assert intent.audio_requested is True
    assert intent.document_runtime_input_requested is False
    assert intent.needs_architecture_clarification is False


def test_resolve_input_intent_still_requires_architecture_for_audio_and_pdf_upload() -> (
    None
):
    intent = resolve_input_intent(
        (
            "Bygg ett flöde där användaren laddar upp en ljudfil och en PDF "
            "vid körning. Ljudfilen ska transkriberas och PDF-dokumentet ska "
            "användas som extra underlag."
        ),
        {},
    )

    assert intent.audio_requested is True
    assert intent.document_runtime_input_requested is True
    assert intent.needs_architecture_clarification is True


def test_resolve_input_intent_uses_role_scoped_input_clause_for_uploaded_pdf() -> None:
    intent = resolve_input_intent(
        "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en DOCX-rapport.",
        {},
    )

    assert intent.primary_runtime_input == "documents"
    assert intent.document_runtime_input_requested is True
    assert intent.audio_requested is False


def test_resolve_input_intent_recovers_audio_from_document_scope_answer() -> None:
    intent = resolve_input_intent(
        "",
        {"document_material_scope": {"ljudfil som transkribering"}},
    )

    assert intent.primary_runtime_input == "audio"
    assert intent.audio_requested is True
    assert intent.document_runtime_input_requested is False


@pytest.mark.parametrize(
    ("text", "expected_primary", "expected_clarification"),
    [
        (
            "Bygg ett flöde där användaren laddar upp en ljudfil vid körning. "
            "Transkribera ljudet och skapa ett Word-dokument.",
            "audio",
            False,
        ),
        (
            "Användaren laddar upp en audio file at runtime. "
            "Transcribe it to text and summarize it.",
            "audio",
            False,
        ),
        (
            "Jag vill transkribera ett kommunfullmäktigemöte och få en sammanfattning.",
            "audio",
            False,
        ),
        (
            "Jag vill spela in kommunmöten och få ett färdigt protokoll i Word "
            "med beslut och övriga frågor.",
            "audio",
            False,
        ),
        (
            "Skapa ett flöde för en mötesinspelning som ska bli protokoll.",
            "audio",
            False,
        ),
        (
            "Ljudfil in, DOCX ut. Gör protokoll med beslut och övriga frågor.",
            "audio",
            False,
        ),
        (
            "Bygg ett ljudflöde för mötesprotokoll i DOCX. Användaren ska bara "
            "lämna ljudfilen, inga andra inmatningsfält.",
            "audio",
            False,
        ),
        (
            "Ladda upp ljudfil och gör om den till svensk text innan du skapar "
            "sammanfattning.",
            "audio",
            False,
        ),
        (
            "Jag laddar upp ljudfilen och vill få tillbaka ett Word-dokument med rubriker.",
            "audio",
            False,
        ),
        (
            "Sammanfatta en befintlig transkribering av ett möte och skapa en DOCX.",
            "text",
            False,
        ),
        (
            "Användaren klistrar in mötesanteckningar som text och får en sammanfattning.",
            "text",
            False,
        ),
        (
            "Ta emot en kort text från användaren och förbättra språket.",
            "text",
            False,
        ),
        (
            "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en "
            "DOCX-rapport.",
            "documents",
            False,
        ),
        (
            "Bygg ett flöde där jag laddar upp ett mötesdokument och får en kort "
            "svensk sammanfattning.",
            "documents",
            False,
        ),
        (
            "Användaren laddar upp ett mötesdokument och en DOCX-mall. Fyll mallen "
            "med sammanfattning, beslut och åtgärder.",
            "documents",
            False,
        ),
        (
            "Användaren laddar upp flera dokument som underlag och får en analys.",
            "documents",
            False,
        ),
        (
            "Ta emot ett dokumentpaket med bilagor och skriv en rapport.",
            "documents",
            False,
        ),
        (
            "Användaren laddar upp ett avtal eller leverantörsavtal. "
            "Extrahera risker och skriv en rapport.",
            "documents",
            False,
        ),
        (
            "Användaren laddar upp fakturor eller kvitton och får strukturerad JSON.",
            "documents",
            False,
        ),
        (
            "Användaren skriver en fråga och laddar upp ett PDF-dokument som underlag.",
            "text_and_documents",
            False,
        ),
        (
            "Användaren laddar upp en ljudfil och en PDF vid körning. "
            "Transkribera ljudet och använd PDF som underlag.",
            "unknown",
            True,
        ),
        (
            "Transkribera ljud och samtidigt ladda upp dokument i samma körning.",
            "unknown",
            True,
        ),
        (
            "Jag har redan transkriberad text och vill få ut ett Word-dokument.",
            "text",
            False,
        ),
        (
            "Underlaget är en ljudinspelning från mötet. Skapa en sammanfattning.",
            "audio",
            False,
        ),
        (
            "Källmaterialet är inspelat ljud från ett samtal, gör en rapport.",
            "audio",
            False,
        ),
        (
            "Jag vill lämna underlag vid körning och få en rapport.",
            "documents",
            False,
        ),
    ],
)
def test_resolve_input_intent_handles_vague_and_specific_runtime_material(
    text: str,
    expected_primary: str,
    expected_clarification: bool,
) -> None:
    intent = resolve_input_intent(text, {})

    assert intent.primary_runtime_input == expected_primary
    assert intent.needs_architecture_clarification is expected_clarification
