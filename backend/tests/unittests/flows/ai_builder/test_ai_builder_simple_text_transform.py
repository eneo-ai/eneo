from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_form_intake_signals import (
    SECTIONED_FORM_INTAKE_SIGNAL,
)
from eneo.flows.ai_builder.ai_builder_simple_text_transform import (
    user_requested_simple_text_transform,
)


@pytest.mark.parametrize(
    "text",
    [
        "Översätt den här meningen till engelska: Vi ses imorgon.",
        "Översätter den här texten till engelska.",
        "Translate this sentence to English: Vi ses imorgon.",
        "Skriv om den här texten så att den blir kortare.",
        "Correct this text and keep the same meaning.",
        "Översätt texten utan extra steg.",
        "Translate this sentence. Do not add another step.",
        "Översätt meningen, lägg inte till ett steg.",
    ],
)
def test_flags_direct_text_transform(text: str) -> None:
    assert user_requested_simple_text_transform(text)


@pytest.mark.parametrize(
    "text",
    [
        "Översätt texten, låt ett separat kritiksteg granska den och skriv en slutversion.",
        "Translate this paragraph and return JSON fields with terminology notes.",
        "Ladda upp ett dokument och översätt det till en Word-rapport.",
        "Translate the text provided in the runtime input field target_text.",
        "Help me with this text.",
        "Beskriv om processen behöver godkännanden.",
        "Bygg ett flöde där användaren skriver om upplevelsen.",
        "Förrätta uppdraget och sammanställ en kort notis.",
        "Sammanfatta den här leverantörsavtalet.",
        "Översätt fakturor till engelska.",
        "Translate this and use more than two steps.",
        "Översätt texten i flera steg.",
        "Translate this text, not just two steps.",
        "Lägg till ett avslutande steg som översätter intranätsnyheten till engelska.",
        "Översätt texten och lägg till ett steg som kontrollerar tonen.",
        "Translate the text and add a final step that shortens it.",
        (
            "Lägg till ett avslutande steg som översätter intranätsnyheten till "
            "engelska. Lägg inte till nya uppgifter."
        ),
        "Add a final step to translate the news item into English. Do not add new facts.",
        "",
    ],
)
def test_does_not_flag_complex_or_ambiguous_text(text: str) -> None:
    assert not user_requested_simple_text_transform(text)


def test_model_form_intake_signal_excludes_the_restraint() -> None:
    """A classifier verdict counts as the user asking for runtime fields."""

    text = "Översätt den här texten till engelska."

    assert user_requested_simple_text_transform(text)
    assert not user_requested_simple_text_transform(
        text, model_form_intake_signals={SECTIONED_FORM_INTAKE_SIGNAL}
    )
