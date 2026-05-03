from __future__ import annotations

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
