"""Give each competing stream first access on consecutive execution dates."""

from collections.abc import Sequence
from datetime import date

from eneo.data_retention.application.retention_runner import RetentionStep


def rotate_retention_steps(
    steps: Sequence[RetentionStep], *, execution_date: date
) -> tuple[RetentionStep, ...]:
    ordered = tuple(steps)
    if not ordered:
        return ordered
    offset = execution_date.toordinal() % len(ordered)
    return ordered[offset:] + ordered[:offset]
