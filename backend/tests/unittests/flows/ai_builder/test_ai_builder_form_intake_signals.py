from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_form_intake_signals import (
    detect_form_intake_pattern,
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


def test_detect_form_intake_pattern_ignores_output_only_heading_requirements() -> None:
    pattern = detect_form_intake_pattern(
        "Slutrapporten ska innehålla rubrikerna Planering och hälsa, Ekonomi och Övrigt."
    )

    assert pattern.sectioned_form_intake is False
