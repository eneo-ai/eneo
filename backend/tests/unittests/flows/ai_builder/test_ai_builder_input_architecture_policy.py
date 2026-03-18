from __future__ import annotations

from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
    resolve_input_intent,
)


def test_resolve_input_intent_prefers_audio_for_transcribe_conversation_with_pdf_output() -> None:
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


def test_resolve_input_intent_requires_architecture_for_audio_and_document_upload() -> None:
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
