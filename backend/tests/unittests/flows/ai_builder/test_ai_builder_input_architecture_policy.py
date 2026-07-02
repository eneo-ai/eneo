from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_input_architecture_policy import (
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


def test_resolve_input_intent_treats_word_file_at_end_as_output_not_document_input() -> (
    None
):
    intent = resolve_input_intent(
        (
            "Jag vill bygga ett flöde där jag ska skicka in en ljudfil som ska "
            "transkriberas. Jag vill ha en Word-fil i slutet."
        ),
        {},
    )

    assert intent.primary_runtime_input == "audio"
    assert intent.audio_requested is True
    assert intent.document_runtime_input_requested is False
    assert intent.needs_architecture_clarification is False


def test_resolve_input_intent_treats_uploaded_ljudinspelning_as_audio() -> None:
    intent = resolve_input_intent(
        "Jag vill kunna skicka in en ljudinspelning och få ett bra Word-dokument tillbaka.",
        {},
    )

    assert intent.primary_runtime_input == "audio"
    assert intent.audio_requested is True
    assert intent.document_runtime_input_requested is False
    assert intent.needs_architecture_clarification is False


def test_resolve_input_intent_keeps_explicit_audio_meeting_docx_prompt_as_audio() -> (
    None
):
    intent = resolve_input_intent(
        (
            "Bygg ett flöde där användaren laddar upp en ljudfil vid körning. "
            "Ljudfilen är en inspelning från ett kommunfullmäktigemöte. "
            "Flödet ska först transkribera ljudfilen till svensk text. "
            "Rubrikerna ska inte vara inmatningsfält för användaren, utan ska "
            "skapas och fyllas i utifrån transkriptionen. DOCX-resultatet ska "
            "innehålla rubriker i angiven ordning. Slutresultatet ska vara ett "
            "Word-dokument. Användaren ska bara behöva lämna in ljudfilen vid körning."
        ),
        {},
    )

    assert intent.primary_runtime_input == "audio"
    assert intent.audio_requested is True
    assert intent.document_runtime_input_requested is False
    assert intent.needs_architecture_clarification is False


def test_resolve_input_intent_treats_record_meeting_as_audio() -> None:
    intent = resolve_input_intent(
        "Jag vill spela in ett möte och få ett protokoll i Word.",
        {},
    )

    assert intent.primary_runtime_input == "audio"
    assert intent.audio_requested is True
    assert intent.document_runtime_input_requested is False


@pytest.mark.parametrize(
    "prompt",
    [
        (
            "Bygg ett flöde där användaren spelar in eller laddar upp ett kundsamtal. "
            "Flödet ska transkribera ljudet, extrahera beslut och åtgärder per "
            "agendapunkt som separata JSON-underlag och skriva en slutgiltig "
            "Word-rapport. Källmaterialet får inte ersättas av rapporttonen."
        ),
        (
            "Skapa ett flöde där användaren spelar in en intervju. Flödet ska "
            "transkribera intervjun, skapa JSON-underlag per fråga och skriva en "
            "DOCX-sammanfattning som bygger på transkriptionen."
        ),
        (
            "Bygg ett flöde där användaren laddar upp en ljudfil från ett möte. "
            "Efter transkribering ska flödet skapa flera underlag som steg-output "
            "och sedan skriva en Word-rapport."
        ),
    ],
)
def test_resolve_input_intent_treats_derived_underlag_as_audio_only(
    prompt: str,
) -> None:
    intent = resolve_input_intent(prompt, {})

    assert intent.primary_runtime_input == "audio"
    assert intent.audio_requested is True
    assert intent.document_runtime_input_requested is False
    assert intent.needs_architecture_clarification is False


def test_resolve_input_intent_does_not_treat_passive_underlag_as_document_input() -> (
    None
):
    intent = resolve_input_intent(
        "Skapa en rapport där varje avsnitt har tydligt underlag och slutsats.",
        {},
    )

    assert intent.primary_runtime_input == "unknown"
    assert intent.document_runtime_input_requested is False
    assert intent.audio_requested is False


def test_resolve_input_intent_still_requires_architecture_for_audio_and_document_file() -> (
    None
):
    intent = resolve_input_intent(
        "Jag vill skicka in en ljudfil och ett bifogat dokument i samma körning.",
        {},
    )

    assert intent.audio_requested is True
    assert intent.document_runtime_input_requested is True
    assert intent.needs_architecture_clarification is True


def test_resolve_input_intent_keeps_terse_terminal_docx_upload_as_document_input() -> (
    None
):
    intent = resolve_input_intent("Skicka in en DOCX i slutet.", {})

    assert intent.primary_runtime_input == "documents"
    assert intent.document_runtime_input_requested is True
    assert intent.needs_architecture_clarification is False


def test_resolve_input_intent_keeps_terse_terminal_pdf_upload_as_document_input() -> (
    None
):
    intent = resolve_input_intent("Ladda upp en PDF i slutet.", {})

    assert intent.primary_runtime_input == "documents"
    assert intent.document_runtime_input_requested is True
    assert intent.needs_architecture_clarification is False


def test_resolve_input_intent_uses_role_scoped_input_clause_for_uploaded_pdf() -> None:
    intent = resolve_input_intent(
        "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en DOCX-rapport.",
        {},
    )

    assert intent.primary_runtime_input == "documents"
    assert intent.document_runtime_input_requested is True
    assert intent.audio_requested is False


def test_resolve_input_intent_treats_word_meeting_minutes_as_document_input() -> None:
    intent = resolve_input_intent(
        (
            "Skapa ett flöde som tar emot ett Word-dokument med ett mötesprotokoll "
            "som input och skriver en svensk rapport."
        ),
        {},
    )

    assert intent.primary_runtime_input == "documents"
    assert intent.document_runtime_input_requested is True
    assert intent.audio_requested is False
    assert intent.needs_architecture_clarification is False


def test_resolve_input_intent_still_treats_meeting_recording_as_audio_input() -> None:
    intent = resolve_input_intent(
        "Skapa ett flöde som tar emot en mötesinspelning och skriver ett protokoll.",
        {},
    )

    assert intent.primary_runtime_input == "audio"
    assert intent.audio_requested is True
    assert intent.document_runtime_input_requested is False


@pytest.mark.parametrize(
    "prompt",
    [
        "Skapa ett flöde som ska få ett worddokument uppladdat som input.",
        "Skapa ett flöde som ska få ett Word-dokument uppladdat som input.",
        "Skapa ett flöde som ska få en wordfil uppladdad som input.",
        "Ladda upp ett pdfdokument vid körning.",
        "Ladda upp en pdffil vid körning.",
        "Ladda upp ett docxdokument vid körning.",
    ],
)
def test_resolve_input_intent_treats_swedish_artifact_compounds_as_documents(
    prompt: str,
) -> None:
    intent = resolve_input_intent(prompt, {})

    assert intent.primary_runtime_input == "documents"
    assert intent.document_runtime_input_requested is True
    assert intent.audio_requested is False
    assert intent.needs_architecture_clarification is False


def test_resolve_input_intent_treats_uploaded_underlagsfiler_as_documents() -> None:
    intent = resolve_input_intent(
        (
            "Bygg ett flöde där användaren laddar upp flera underlagsfiler "
            "och en Word-mall."
        ),
        {},
    )

    assert intent.primary_runtime_input == "documents"
    assert intent.document_runtime_input_requested is True
    assert intent.audio_requested is False


@pytest.mark.parametrize(
    "prompt",
    [
        "Bygg ett flöde där användaren laddar upp underlag och en Word-mall.",
        "Bygg ett flöde där användaren lämnar underlag och en Word-mall.",
        "Build a flow where the user provides documents and a Word template.",
    ],
)
def test_resolve_input_intent_treats_provided_underlag_as_documents(
    prompt: str,
) -> None:
    intent = resolve_input_intent(
        prompt,
        {},
    )

    assert intent.primary_runtime_input == "documents"
    assert intent.document_runtime_input_requested is True
    assert intent.audio_requested is False


@pytest.mark.parametrize(
    "prompt",
    [
        "Jag vill bygga ett flöde som tar emot JSON och returnerar JSON.",
        "Bygg ett flöde där användaren laddar upp en JSON-payload vid körning.",
        "Build a flow that receives a JSON payload and returns normalized JSON.",
    ],
)
def test_resolve_input_intent_treats_runtime_json_payload_as_json(
    prompt: str,
) -> None:
    intent = resolve_input_intent(prompt, {})

    assert intent.primary_runtime_input == "json"
    assert intent.document_runtime_input_requested is False
    assert intent.audio_requested is False
    assert intent.needs_architecture_clarification is False


@pytest.mark.parametrize(
    "prompt",
    [
        "Läs en PDF och extrahera resultatet som JSON.",
        "Användaren laddar upp ett avtal och flödet ska returnera strukturerad JSON.",
        "Extract JSON fields from the uploaded document.",
    ],
)
def test_resolve_input_intent_does_not_treat_json_output_as_json_input(
    prompt: str,
) -> None:
    intent = resolve_input_intent(prompt, {})

    assert intent.primary_runtime_input == "documents"
    assert intent.document_runtime_input_requested is True
    assert intent.audio_requested is False
