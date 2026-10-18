"""The ordering rule between the Flow AI Builder's provider-call deadlines.

Shared by deployment startup (main/config.py, env values) and the tenant-aware
resolver and settings writer (flows/ai_builder/ai_builder_settings.py). It lives
here, outside the flows package, because config is imported by code that must
load without Flows.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TimingOrderViolation:
    """The silence deadline ``value`` is above the call ceiling ``bound``;
    both are effective seconds."""

    value: float
    bound: float


def ai_builder_timing_order_violation(
    *,
    silence_seconds: float,
    call_ceiling_seconds: float,
) -> TimingOrderViolation | None:
    """The deadlines when they break the ordering rule, or None.

    The one statement of the ordering rule, shared by deployment startup (env
    values) and the tenant-aware resolver and settings writer, each of which
    words the refusal in its own vocabulary: the silence deadline may not
    exceed the call ceiling. Written as a negated comparison so NaN breaks it.
    """

    if not silence_seconds <= call_ceiling_seconds:
        return TimingOrderViolation(silence_seconds, call_ceiling_seconds)
    return None
