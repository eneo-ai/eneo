"""The rule vocabulary and the SQL built from a rule's levels."""

import pytest
import sqlalchemy as sa

from eneo.data_retention.domain.rules import RetentionRule, RuleTask, rule_task
from eneo.data_retention.infrastructure.retention_rule_sql import (
    rule_period,
)
from eneo.policy_levels import PolicyLevel

SPACE = PolicyLevel.SPACE
OWN = PolicyLevel.ASSISTANT_OR_APP


def test_the_sql_refuses_a_rule_it_cannot_resolve_like_the_kernel():
    """Mutants: a bounded rule gets the nearest-wins SQL, so the bound is
    silently dropped; a level without a column, or a column for a level the
    rule does not declare, changes which period applies."""
    columns = {SPACE: sa.literal(60), OWN: sa.literal(30)}

    with pytest.raises(ValueError):
        rule_period(RuleTask("bounded", (SPACE, OWN), frozenset({SPACE})), columns)
    with pytest.raises(ValueError):
        rule_period(RuleTask("partial", (SPACE, OWN)), {OWN: sa.literal(30)})
    with pytest.raises(ValueError):
        rule_period(RuleTask("extra", (OWN,)), columns)


def test_an_exempt_rule_has_no_period_to_resolve():
    """Mutant: an exempt rule resolves as if a task removed it."""
    with pytest.raises(ValueError):
        rule_task(RetentionRule.WIDGET_CONVERSATIONS)
