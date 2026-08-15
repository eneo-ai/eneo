from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_form_intake_signals import (
    SECTIONED_FORM_INTAKE_SIGNAL,
)
from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
    build_requirements_signal_text,
    detect_planner_pattern_signals,
)


def _requirements(**overrides: object) -> RequirementsSummaryPayload:
    payload = {
        "summary": "Översätt en kort svensk text till engelska.",
        "key_decisions": [],
        "input_description": "Primär indata vid körning behöver granskas.",
        "output_description": "Huvudsakligt slutresultat behöver granskas.",
        "assumptions": [],
    }
    payload.update(overrides)
    return RequirementsSummaryPayload.model_validate(payload)


@pytest.mark.parametrize(
    "text",
    [
        "Översätt den här meningen till engelska: Vi ses imorgon.",
        "Översätter den här texten till engelska.",
        "Translate this sentence to English: Vi ses imorgon.",
        "Skriv om den här texten så att den blir kortare.",
        "Correct this text and keep the same meaning.",
    ],
)
def test_detect_planner_pattern_signals_flags_simple_text_transform(
    text: str,
) -> None:
    signals = detect_planner_pattern_signals(text)

    assert signals.is_simple_text_transform
    assert not signals.prefers_structured_intermediate
    assert not signals.prefers_quality_step


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
    ],
)
def test_detect_planner_pattern_signals_does_not_flag_complex_or_ambiguous_text(
    text: str,
) -> None:
    assert not detect_planner_pattern_signals(text).is_simple_text_transform


def test_detect_planner_pattern_signals_prefers_model_form_intake_signal() -> None:
    signals = detect_planner_pattern_signals(
        "Bygg flödet enligt beskrivningen.",
        model_form_intake_signals={SECTIONED_FORM_INTAKE_SIGNAL},
    )

    assert signals.needs_form_fields
    assert signals.sectioned_form_intake
    assert signals.recipe_signals() == {SECTIONED_FORM_INTAKE_SIGNAL}


def test_requirements_signal_text_ignores_confirmation_boilerplate() -> None:
    signal_text = build_requirements_signal_text(
        _requirements(
            assumptions=[
                "Planen ska följa kraven och underlaget i konversationen.",
                "Användaren ska kunna granska och ändra planen innan den tillämpas.",
                "Inga extra fält.",
            ],
        )
    )

    assert (
        signal_text == "Översätt en kort svensk text till engelska.\nInga extra fält."
    )
    assert "behöver granskas" not in signal_text
    assert "Användaren ska kunna granska" not in signal_text
    assert "Inga extra fält" in signal_text
    signals = detect_planner_pattern_signals(signal_text)
    assert signals.is_simple_text_transform
    assert not signals.prefers_quality_step


def test_requirements_signal_text_uses_typed_payload_without_version_leak() -> None:
    signal_text = build_requirements_signal_text(
        _requirements(
            requirements_version="do-not-render",
            summary="Skapa ett mötesprotokoll.",
            key_decisions=[
                {"topic": "Indata", "decision": "Mötesljud vid körning."},
                {"topic": "Utdata", "decision": "DOCX-protokoll."},
            ],
            assumptions=["Inga extra fält."],
            manual_setup_notes=["Koppla transkriberingsmodellen."],
        )
    )

    assert signal_text == "\n".join(
        (
            "Skapa ett mötesprotokoll.",
            "Inga extra fält.",
            "Indata",
            "Mötesljud vid körning.",
            "Utdata",
            "DOCX-protokoll.",
            "Koppla transkriberingsmodellen.",
        )
    )
    assert "do-not-render" not in signal_text
