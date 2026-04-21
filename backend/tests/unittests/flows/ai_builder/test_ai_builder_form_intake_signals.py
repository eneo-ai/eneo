from __future__ import annotations

from intric.flows.ai_builder.ai_builder_form_intake_signals import (
    detect_form_intake_pattern,
    extract_form_intake_recipe_signals,
)


def test_detect_form_intake_pattern_flags_true_sectioned_runtime_intake() -> None:
    pattern = detect_form_intake_pattern(
        (
            "Visa en sektion i taget och be användaren om fritext för varje sektion. "
            "Spara innehållet separat per rubrik."
        )
    )

    assert pattern.sectioned_form_intake is True
    assert pattern.needs_form_fields is True
    assert extract_form_intake_recipe_signals(
        "Visa en sektion i taget och be användaren om fritext för varje sektion."
    ) == {"sectioned_form_intake"}


def test_detect_form_intake_pattern_ignores_output_only_heading_requirements() -> None:
    pattern = detect_form_intake_pattern(
        "Slutrapporten ska innehålla rubrikerna Planering och hälsa, Ekonomi och Övrigt."
    )

    assert pattern.sectioned_form_intake is False
