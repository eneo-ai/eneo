"""The kernel's resolution of a retention rule, in SQL.

Built from the rule's levels, so SQL resolves them in the order the kernel
does; a parity test holds the two together. Every domain that selects due
rows by a rule's period uses it with its own column per level.
"""

from collections.abc import Mapping
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


def rule_period(
    rule: RuleTask, chosen: Mapping[PolicyLevel, ColumnElement[int | None]]
) -> RulePeriodSQL:
    """The kernel's resolution of a rule without a bound: the innermost chosen
    period, and the level that chose it."""
    if rule.bounding:
        raise ValueError(f"{rule.task} has a bound, which this SQL does not apply.")
    if set(chosen) != set(rule.levels):
        raise ValueError(f"{rule.task} needs a column for each of {rule.levels}.")
    inner_first = [(level, chosen[level]) for level in reversed(rule.levels)]
    return RulePeriodSQL(
        days=coalesce[int | None](*(column for _, column in inner_first)),
        source=sa.case(
            *((column.is_not(None), level.value) for level, column in inner_first),
            else_=None,
        ),
    )
