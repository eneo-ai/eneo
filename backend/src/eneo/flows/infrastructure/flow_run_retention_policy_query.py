from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa

from eneo.data_retention.constants import MIN_RETENTION_DAYS
from eneo.data_retention.domain.rules import RetentionRule, rule_chain
from eneo.data_retention.infrastructure.retention_rule_sql import (
    RulePeriodSQL,
    rule_period,
)
from eneo.database.tables.flow_tables import FlowRuns, Flows
from eneo.database.tables.spaces_table import Spaces
from eneo.policy_levels import PolicyLevel


def flow_run_history_period_sql() -> RulePeriodSQL:
    """The Flow run history period of a row joined to its Flow and Space, by
    the rule's declaration: the Space's time caps the Flow's."""
    return rule_period(
        rule_chain(RetentionRule.FLOW_RUN_HISTORY),
        {
            PolicyLevel.SPACE: Spaces.data_retention_days.expression,
            PolicyLevel.FLOW: Flows.flow_run_history_retention_days.expression,
        },
    )


def space_retention_is_on() -> sa.ColumnElement[bool]:
    """The space's time is on: a shared space with a time. A personal space
    has no automatic removal in this version, even with a stored time."""
    return sa.and_(Spaces.data_retention_days.is_not(None), Spaces.user_id.is_(None))


def started_under_space_retention(
    *, flow_id: UUID, tenant_id: UUID
) -> sa.ColumnElement[bool]:
    """The mark of a run inserted now: whether its flow's space has its time
    on. Read in the inserting statement, so it is the time committed then."""
    return (
        sa.select(Flows.id)
        .join(
            Spaces,
            sa.and_(Flows.space_id == Spaces.id, Flows.tenant_id == Spaces.tenant_id),
        )
        .where(
            Flows.id == flow_id,
            Flows.tenant_id == tenant_id,
            space_retention_is_on(),
        )
        .exists()
    )


def flow_run_automatic_retention_predicates() -> tuple[sa.ColumnElement[bool], ...]:
    """What the automatic removal adds to the explicit purge's selection, on a
    run joined to its Space: the run started while the time was on, and the
    time is on now. Removing the space's time stops the removal; setting it
    again resumes it for the runs marked before."""
    return (FlowRuns.started_under_space_retention.is_(True), space_retention_is_on())


def flow_run_retention_anchor() -> sa.ColumnElement[datetime]:
    """When a terminal run's retention age starts: its end, or its creation.

    The expression of `ix_flow_runs_tenant_terminal_retention_anchor`; keep
    them identical so selection by age uses the index."""
    return cast(
        sa.ColumnElement[datetime],
        sa.func.coalesce(FlowRuns.finished_at, FlowRuns.created_at),
    )


def flow_run_history_due_predicates(
    *,
    now: datetime,
    anchor: sa.ColumnElement[datetime],
    effective_days: sa.ColumnElement[int | None],
) -> tuple[sa.ColumnElement[bool], ...]:
    """A run is due at its deadline, `anchor + days <= now`, the one form the
    preview and the purge share.

    Days are calendar days in the session's time zone, so around a clock
    change a day can be 23 or 25 hours; the session's zone is not pinned
    here. The bound by the shortest time is not the rule: it lets the
    anchor index narrow the scan before the deadline is computed per run."""
    return (
        effective_days.is_not(None),
        anchor <= sa.literal(now) - sa.func.make_interval(0, 0, 0, MIN_RETENTION_DAYS),
        flow_run_history_eligible_since_sql(
            anchor=anchor, effective_days=effective_days
        )
        <= sa.literal(now),
    )


def flow_run_history_eligible_since_sql(
    *,
    anchor: sa.ColumnElement[datetime],
    effective_days: sa.ColumnElement[int | None],
) -> sa.ColumnElement[datetime]:
    """The deadline: the anchor plus the period in calendar days."""
    return cast(
        sa.ColumnElement[datetime],
        anchor + sa.func.make_interval(0, 0, 0, effective_days),
    )
