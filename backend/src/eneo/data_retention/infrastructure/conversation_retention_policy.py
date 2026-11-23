"""The shared SQL policy for assistant conversations and app runs.

The conversation history rule's period, with the column that holds each
level's choice.
"""

from typing import cast

import sqlalchemy as sa
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from eneo.data_retention.domain.rules import RetentionRule, rule_task
from eneo.data_retention.infrastructure.retention_rule_sql import (
    RulePeriodSQL,
    rule_period,
)
from eneo.database.tables.assistant_table import (
    MIGRATED_GROUP_CHAT_METADATA_KEY,
    Assistants,
    AssistantSpecialists,
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


def conversation_text_retention_days() -> ColumnElement[int | None]:
    """Names and feedback follow their conversation's current policy.

    Former groups keep their shortest member period. Their members are now
    specialists and the migration marker survives also on already-migrated
    databases. Resolve inherited periods at read/removal time, just like turns;
    copying a period into the migrated assistant would freeze the space default.
    The marker belongs to an assistant and also affects its new conversations.
    Retire it only after the marked assistants have an equivalent retention
    policy or their owner has deliberately adopted the ordinary policy.
    Ordinary consultations remain part of the orchestrator's conversation.
    The caller joins the conversation's assistant, space and organisation.
    """
    inherited = conversation_retention_policy(
        cast("ColumnElement[int | None]", sa.null())
    ).days
    member = aliased(Assistants)
    shortest_member = (
        sa.select(sa.func.min(sa.func.coalesce(member.data_retention_days, inherited)))
        .select_from(AssistantSpecialists)
        .join(member, member.id == AssistantSpecialists.specialist_id)
        .where(AssistantSpecialists.assistant_id == Assistants.id)
        .correlate(Assistants, Spaces, AuditRetentionPolicy)
        .scalar_subquery()
    )
    own_days = sa.case(
        (
            Assistants.metadata_json.contains({MIGRATED_GROUP_CHAT_METADATA_KEY: True}),
            sa.func.least(Assistants.data_retention_days, shortest_member),
        ),
        else_=Assistants.data_retention_days,
    )
    return conversation_retention_policy(own_days).days
