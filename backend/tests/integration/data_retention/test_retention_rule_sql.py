"""The SQL period of a rule with a bound, run in the database, against the
kernel and against values written out by hand."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from eneo.data_retention.domain.rules import RuleTask, fewer_days
from eneo.data_retention.infrastructure.retention_rule_sql import rule_period
from eneo.policy_levels import LevelSetting, PolicyLevel, resolve

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

ORG = PolicyLevel.ORGANIZATION
SPACE = PolicyLevel.SPACE
OWN = PolicyLevel.ASSISTANT_OR_APP
LEVELS = (ORG, SPACE, OWN)

CAPPED_BY_SPACE = RuleTask("capped_by_space", LEVELS, frozenset({SPACE}))
CAPPED_BY_BOTH = RuleTask("capped_by_both", LEVELS, frozenset({ORG, SPACE}))

# (rule, organisation switch on, organisation days, space, own) and the period
# that applies, with the level that chose it.
CASES = [
    pytest.param(CAPPED_BY_SPACE, True, 30, None, 90, (30, ORG), id="inherited cap"),
    pytest.param(CAPPED_BY_SPACE, True, 30, 7, 90, (7, SPACE), id="chosen cap"),
    pytest.param(CAPPED_BY_SPACE, True, 30, 60, 90, (60, SPACE), id="space lengthens"),
    pytest.param(CAPPED_BY_SPACE, True, 30, None, 7, (7, OWN), id="inner tightens"),
    pytest.param(CAPPED_BY_SPACE, True, 30, None, 30, (30, OWN), id="tie inner"),
    pytest.param(CAPPED_BY_SPACE, True, 30, 30, None, (30, SPACE), id="tie space"),
    pytest.param(CAPPED_BY_SPACE, False, 30, None, 90, (90, OWN), id="switch off"),
    pytest.param(CAPPED_BY_SPACE, False, 30, 60, 90, (60, SPACE), id="off, space"),
    pytest.param(CAPPED_BY_SPACE, True, None, None, None, (None, None), id="none"),
    pytest.param(CAPPED_BY_BOTH, True, 30, 30, 90, (30, ORG), id="tie of bounds"),
    pytest.param(CAPPED_BY_BOTH, True, 30, 60, 90, (30, ORG), id="outer bound"),
    pytest.param(CAPPED_BY_BOTH, True, 30, 7, 90, (7, SPACE), id="inner bound"),
    pytest.param(CAPPED_BY_BOTH, True, None, None, 90, (90, OWN), id="no bound"),
    pytest.param(CAPPED_BY_BOTH, True, 30, None, None, (30, ORG), id="org only"),
]


def _days(value: int | None) -> ColumnElement[int | None]:
    return sa.cast(sa.literal(value) if value is not None else sa.null(), sa.Integer)


@pytest.mark.parametrize("rule,switch,org,space,own,expected", CASES)
async def test_a_bounded_rule_resolves_in_sql_as_in_the_kernel(
    async_session: AsyncSession,
    rule: RuleTask,
    switch: bool,
    org: int | None,
    space: int | None,
    own: int | None,
    expected: tuple[int | None, PolicyLevel | None],
):
    """Mutants: the SQL drops the bound, so the nearest period wins also when
    longer; an inherited period does not cap; a tie credits the bound or the
    inner bound instead of the nearest level and the outermost bound; a NULL
    level makes the whole period NULL."""
    period = rule_period(
        rule,
        {
            # The organisation's period counts only while its switch is on,
            # as in production.
            ORG: sa.case((sa.literal(switch), _days(org)), else_=None),
            SPACE: _days(space),
            OWN: _days(own),
        },
    )
    days, source = (
        await async_session.execute(sa.select(period.days, period.source))
    ).one()
    kernel = resolve(
        [
            LevelSetting(ORG, org if switch else None),
            LevelSetting(SPACE, space),
            LevelSetting(OWN, own),
        ],
        stricter=fewer_days,
        bounding=rule.bounding,
    )

    assert (days, source) == expected
    assert (kernel.value, kernel.origin) == expected
