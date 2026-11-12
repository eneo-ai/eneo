"""The kernel's resolution of a retention rule, in SQL.

Built from the rule's levels, so SQL resolves them in the order the kernel
does; a parity test holds the two together. Every domain that selects due
rows by a rule's period uses it with its own column per level.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.functions import coalesce

from eneo.data_retention.domain.rules import RuleTask
from eneo.policy_levels import PolicyLevel


@dataclass(frozen=True, slots=True)
class RulePeriodSQL:
    days: ColumnElement[int | None]
    # The level whose period applies, as a `PolicyLevel` value.
    source: ColumnElement[str | None]


def _nearest(
    levels: Sequence[tuple[PolicyLevel, ColumnElement[int | None]]],
) -> RulePeriodSQL:
    """The innermost chosen period of `levels` (outermost first), and the level
    that chose it."""
    inner_first = list(reversed(levels))
    return RulePeriodSQL(
        days=coalesce[int | None](*(column for _, column in inner_first)),
        source=sa.case(
            *((column.is_not(None), level.value) for level, column in inner_first),
            else_=None,
        ),
    )


def rule_period(
    rule: RuleTask, chosen: Mapping[PolicyLevel, ColumnElement[int | None]]
) -> RulePeriodSQL:
    """The kernel's resolution of a rule: the period that applies and the
    level that chose it.

    Without a bound, the innermost chosen period. With one, each bounding
    level caps with the period that applies there, chosen or inherited, so the
    result is the shortest of the nearest period and those caps (LEAST skips
    a NULL, and is NULL only when nothing is chosen). On a tie the nearest
    level is the source, and among equal caps the outermost.
    """
    if set(chosen) != set(rule.levels):
        raise ValueError(f"{rule.task} needs a column for each of {rule.levels}.")
    levels = [(level, chosen[level]) for level in rule.levels]
    nearest = _nearest(levels)
    caps = [
        _nearest(levels[: index + 1])
        for index, (level, _) in enumerate(levels)
        if level in rule.bounding
    ]
    if not caps:
        return nearest
    days = sa.func.least(nearest.days, *(cap.days for cap in caps))
    return RulePeriodSQL(
        days=days,
        source=sa.case(
            (nearest.days == days, nearest.source),
            *((cap.days == days, cap.source) for cap in caps),
            else_=None,
        ),
    )
