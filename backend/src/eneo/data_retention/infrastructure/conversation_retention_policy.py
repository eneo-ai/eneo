"""The shared SQL policy for assistant conversations and app runs."""

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.functions import coalesce

from eneo.data_retention.domain.retention import ConversationPolicySource
from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.spaces_table import Spaces


@dataclass(frozen=True, slots=True)
class ConversationPolicySQL:
    days: ColumnElement[int | None]
    source: ColumnElement[str | None]


def conversation_retention_policy(
    own_days: ColumnElement[int | None],
) -> ConversationPolicySQL:
    organization_days = sa.case(
        (
            AuditRetentionPolicy.conversation_retention_enabled.is_(True),
            AuditRetentionPolicy.conversation_retention_days,
        ),
        else_=None,
    )
    return ConversationPolicySQL(
        days=coalesce[int | None](
            own_days, Spaces.data_retention_days, organization_days
        ),
        source=sa.case(
            (own_days.is_not(None), ConversationPolicySource.OWN.value),
            (
                Spaces.data_retention_days.is_not(None),
                ConversationPolicySource.SPACE.value,
            ),
            (
                organization_days.is_not(None),
                ConversationPolicySource.ORGANIZATION.value,
            ),
            else_=None,
        ),
    )
