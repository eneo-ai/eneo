"""The shared SQL policy for assistant conversations and app runs.

Built from the conversation history rule's levels, so SQL resolves the levels
in the order the kernel does; a parity test holds the two together.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.functions import coalesce

from eneo.data_retention.domain.rules import RetentionRule, RuleTask, rule_task
from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.spaces_table import Spaces
from eneo.policy_levels import PolicyLevel


@dataclass(frozen=True, slots=True)
class ConversationPolicySQL:
    days: ColumnElement[int | None]
    # The level whose period applies, as a `PolicyLevel` value.
    source: ColumnElement[str | None]


def nearest_period(
    rule: RuleTask, chosen: Mapping[PolicyLevel, ColumnElement[int | None]]
) -> ConversationPolicySQL:
    """The kernel's resolution of a rule without a bound: the innermost chosen
    period, and the level that chose it."""
    if rule.bounding:
        raise ValueError(f"{rule.task} has a bound, which this SQL does not apply.")
    if set(chosen) != set(rule.levels):
        raise ValueError(f"{rule.task} needs a column for each of {rule.levels}.")
    inner_first = [(level, chosen[level]) for level in reversed(rule.levels)]
    return ConversationPolicySQL(
        days=coalesce[int | None](*(column for _, column in inner_first)),
        source=sa.case(
            *((column.is_not(None), level.value) for level, column in inner_first),
            else_=None,
        ),
    )


def conversation_retention_policy(
    own_days: ColumnElement[int | None],
) -> ConversationPolicySQL:
    return nearest_period(
        rule_task(RetentionRule.CONVERSATION_HISTORY),
        {
            # The organisation's period counts only while its switch is on.
            PolicyLevel.ORGANIZATION: sa.case(
                (
                    AuditRetentionPolicy.conversation_retention_enabled.is_(True),
                    AuditRetentionPolicy.conversation_retention_days,
                ),
                else_=None,
            ),
            PolicyLevel.SPACE: Spaces.data_retention_days.expression,
            PolicyLevel.ASSISTANT_OR_APP: own_days,
        },
    )
