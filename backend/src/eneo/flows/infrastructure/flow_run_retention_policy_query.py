from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

import sqlalchemy as sa

from eneo.data_retention.constants import MIN_RETENTION_DAYS
from eneo.database.tables.flow_tables import FlowRuns


@dataclass(frozen=True, slots=True)
class EffectiveFlowRunRetentionPolicySql:
    mode: sa.ColumnElement[str | None]
    days: sa.ColumnElement[int | None]
    source: sa.ColumnElement[str | None]


def effective_flow_run_retention_policy_sql(
    *,
    organization_mode: sa.ColumnElement[str | None],
    organization_days: sa.ColumnElement[int | None],
    space_mode: sa.ColumnElement[str | None],
    space_days: sa.ColumnElement[int | None],
    flow_mode: sa.ColumnElement[str | None],
    flow_days: sa.ColumnElement[int | None],
) -> EffectiveFlowRunRetentionPolicySql:
    return EffectiveFlowRunRetentionPolicySql(
        mode=cast(
            sa.ColumnElement[str | None],
            sa.func.coalesce(flow_mode, space_mode, organization_mode),
        ),
        days=cast(
            sa.ColumnElement[int | None],
            sa.func.coalesce(flow_days, space_days, organization_days),
        ),
        source=cast(
            sa.ColumnElement[str | None],
            sa.case(
                (flow_mode.is_not(None), sa.literal("flow")),
                (space_mode.is_not(None), sa.literal("space")),
                (organization_mode.is_not(None), sa.literal("organization")),
                else_=sa.null(),
            ),
        ),
    )


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
    return (
        effective_days.is_not(None),
        anchor <= sa.literal(now) - sa.func.make_interval(0, 0, 0, MIN_RETENTION_DAYS),
        anchor <= sa.literal(now) - sa.func.make_interval(0, 0, 0, effective_days),
    )


def flow_run_history_eligible_since_sql(
    *,
    anchor: sa.ColumnElement[datetime],
    effective_days: sa.ColumnElement[int | None],
) -> sa.ColumnElement[datetime]:
    return cast(
        sa.ColumnElement[datetime],
        anchor + sa.func.make_interval(0, 0, 0, effective_days),
    )
