"""The rule vocabulary and the SQL built from a rule's levels."""

import pytest
import sqlalchemy as sa

from eneo.data_retention.domain.rules import (
    RetentionExceedsSpaceError,
    RetentionRule,
    RuleExemption,
    RuleTask,
    resolve_period,
    rule_chain,
    rule_task,
)
from eneo.data_retention.infrastructure.retention_rule_sql import (
    rule_period,
)
from eneo.policy_levels import PolicyLevel

SPACE = PolicyLevel.SPACE
OWN = PolicyLevel.ASSISTANT_OR_APP


def test_the_sql_refuses_a_rule_it_cannot_resolve_like_the_kernel():
    """Mutants: a level without a column, or a column for a level the rule
    does not declare, changes which period applies. A rule with a bound is
    resolved (its parity runs in the database)."""
    columns = {SPACE: sa.literal(60), OWN: sa.literal(30)}

    rule_period(RuleTask("bounded", (SPACE, OWN), frozenset({SPACE})), columns)
    with pytest.raises(ValueError):
        rule_period(RuleTask("partial", (SPACE, OWN)), {OWN: sa.literal(30)})
    with pytest.raises(ValueError):
        rule_period(RuleTask("extra", (OWN,)), columns)


def test_the_sql_refuses_a_rule_without_levels():
    """Mutant: a rule without levels builds an empty COALESCE, which the
    database refuses only when the query runs."""
    with pytest.raises(ValueError, match="no levels"):
        rule_period(RuleExemption("exempt"), {})


def test_an_exempt_rule_has_no_period_to_resolve():
    """Mutant: an exempt rule resolves as if a task removed it."""
    with pytest.raises(ValueError):
        rule_task(RetentionRule.WIDGET_CONVERSATIONS)
    with pytest.raises(ValueError):
        rule_chain(RetentionRule.WIDGET_CONVERSATIONS)


def test_flow_run_history_has_levels_and_caps_but_no_task():
    """Mutants: a task removes Flow run history before it may be switched on;
    the organisation is a level for Flows; the space does not cap a flow.
    One declaration gives Python and SQL the same levels."""
    disposition = rule_chain(RetentionRule.FLOW_RUN_HISTORY)

    assert isinstance(disposition, RuleExemption)
    assert disposition.levels == (SPACE, PolicyLevel.FLOW)
    assert disposition.bounding == frozenset({SPACE, PolicyLevel.FLOW})
    with pytest.raises(ValueError):
        rule_task(RetentionRule.FLOW_RUN_HISTORY)
    rule_period(
        disposition,
        {SPACE: sa.literal(7), PolicyLevel.FLOW: sa.literal(3)},
    )


def test_an_organisation_time_gives_flows_no_period():
    """Mutant: an empty space lets its flows inherit the organisation's time."""
    resolved = resolve_period(
        RetentionRule.FLOW_RUN_HISTORY,
        {PolicyLevel.ORGANIZATION: 30, SPACE: None, PolicyLevel.FLOW: None},
    )

    assert resolved.value is None


@pytest.mark.parametrize(
    "level",
    [PolicyLevel.INSTALLATION, PolicyLevel.ASSISTANT_OR_APP, PolicyLevel.FLOW_STEP],
)
def test_only_an_organization_a_space_or_a_flow_caps_a_retention_period(
    level: PolicyLevel,
):
    """Mutant: the refusal names a level no cap comes from, so a client is
    told to shorten a period to a limit nobody set."""
    with pytest.raises(ValueError):
        RetentionExceedsSpaceError(cap_days=30, cap_origin=level)


def test_a_flow_time_equal_to_the_space_is_the_flows_under_the_spaces_cap():
    """Mutant: on a tie the space is the source, or the flow becomes the cap,
    so a refusal would name the flow instead of the space."""
    resolved = resolve_period(
        RetentionRule.FLOW_RUN_HISTORY, {SPACE: 7, PolicyLevel.FLOW: 7}
    )

    assert (resolved.value, resolved.origin) == (7, PolicyLevel.FLOW)
    assert (resolved.bound, resolved.bound_origin) == (7, SPACE)
