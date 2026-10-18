"""The ordering rule between the Flow AI Builder's provider-call deadlines.

Shared by deployment startup (main/config.py, env values) and the tenant-aware
resolver and settings writer (flows/ai_builder/ai_builder_settings.py). It lives
here, outside the flows package, because config is imported by code that must
load without Flows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TimingOrderRule = Literal[
    "silence_above_call_ceiling",
    "classification_silence_above_call_ceiling",
    "classification_ceiling_above_call_ceiling",
    "classification_ceiling_below_classification_silence",
]


@dataclass(frozen=True, slots=True)
class TimingOrderViolation:
    """``value`` breaks ``rule`` against ``bound``; both are effective seconds."""

    rule: TimingOrderRule
    value: float
    bound: float


def ai_builder_timing_order_violation(
    *,
    silence_seconds: float,
    call_ceiling_seconds: float,
    classification_silence_seconds: float | None,
    classification_ceiling_seconds: float | None,
) -> TimingOrderViolation | None:
    """The first ordering rule the effective deadlines break, or None.

    The one statement of the ordering rule, shared by deployment startup (env
    values) and the tenant-aware resolver and settings writer, each of which
    words the refusal in its own vocabulary: the silence deadline and an
    explicit classification silence deadline may not exceed the call ceiling,
    and an explicit classification ceiling lies between the classification
    silence deadline (the silence deadline when none is explicit) and the call
    ceiling. Written as negated comparisons so NaN breaks a rule.
    """

    if not silence_seconds <= call_ceiling_seconds:
        return TimingOrderViolation(
            "silence_above_call_ceiling", silence_seconds, call_ceiling_seconds
        )
    if classification_silence_seconds is not None and not (
        classification_silence_seconds <= call_ceiling_seconds
    ):
        return TimingOrderViolation(
            "classification_silence_above_call_ceiling",
            classification_silence_seconds,
            call_ceiling_seconds,
        )
    if classification_ceiling_seconds is None:
        return None
    effective_classification_silence = (
        silence_seconds
        if classification_silence_seconds is None
        else classification_silence_seconds
    )
    if not effective_classification_silence <= classification_ceiling_seconds:
        return TimingOrderViolation(
            "classification_ceiling_below_classification_silence",
            classification_ceiling_seconds,
            effective_classification_silence,
        )
    if not classification_ceiling_seconds <= call_ceiling_seconds:
        return TimingOrderViolation(
            "classification_ceiling_above_call_ceiling",
            classification_ceiling_seconds,
            call_ceiling_seconds,
        )
    return None
