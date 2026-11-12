"""The shared SQL policy for assistant conversations and app runs.

The conversation history rule's period, with the column that holds each
level's choice.
"""

import sqlalchemy as sa
from sqlalchemy.sql.elements import ColumnElement

from eneo.data_retention.domain.rules import RetentionRule, rule_task
from eneo.data_retention.infrastructure.retention_rule_sql import (
    RulePeriodSQL,
    rule_period,
)
from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.spaces_table import Spaces
from eneo.policy_levels import PolicyLevel


def conversation_retention_policy(
    own_days: ColumnElement[int | None],
) -> RulePeriodSQL:
    return rule_period(
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
