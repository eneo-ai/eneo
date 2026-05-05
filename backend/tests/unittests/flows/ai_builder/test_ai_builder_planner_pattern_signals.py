from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
    build_requirements_signal_text,
    detect_planner_pattern_signals,
)


@pytest.mark.parametrize(
    "text",
    [
        "Översätt den här meningen till engelska: Vi ses imorgon.",
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
    ],
)
def test_detect_planner_pattern_signals_does_not_flag_complex_or_ambiguous_text(
    text: str,
) -> None:
    assert not detect_planner_pattern_signals(text).is_simple_text_transform


def test_requirements_signal_text_ignores_confirmation_boilerplate() -> None:
    signal_text = build_requirements_signal_text(
        {
            "summary": "Översätt en kort svensk text till engelska.",
            "input_description": "Primär indata vid körning behöver granskas.",
            "output_description": "Huvudsakligt slutresultat behöver granskas.",
            "assumptions": [
                "Planen ska följa kraven och underlaget i konversationen.",
                "Användaren ska kunna granska och ändra planen innan den tillämpas.",
                "Inga extra fält.",
            ],
        }
    )

    assert "behöver granskas" not in signal_text
    assert "Användaren ska kunna granska" not in signal_text
    assert "Inga extra fält" in signal_text
    signals = detect_planner_pattern_signals(signal_text)
    assert signals.is_simple_text_transform
    assert not signals.prefers_quality_step
