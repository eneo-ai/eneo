"""Live overdue selection of terminal, unfenced auto_delete run history.

The per-Flow query follows the K4 due index. The global limit bounds returned
runs, while physical scans remain bounded by the caller's statement timeout.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import LateralFromClause

from eneo.data_retention.domain.retention import (
    NON_FINAL_RECEIPT_PHASES,
    ReceiptPhase,
    RetentionPolicySource,
)
from eneo.database.tables.flow_tables import FlowRetentionHolds, FlowRuns, Flows
from eneo.database.tables.retention_tables import RetentionReceipts
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.domain.flow_run_retention_policy import (
    FLOWS_HISTORY_TASK,
    FlowRunRetentionMode,
    FlowRunRetentionPolicyStorageError,
    flow_run_retention_policy_from_storage,
)
from eneo.flows.enums import TERMINAL_FLOW_RUN_STATUS_VALUES
from eneo.flows.infrastructure.flow_retention_hold_repo import (
    flow_retention_hold_is_active,
    flow_run_held_predicate,
    flow_runless_data_held_predicate,
)
from eneo.flows.infrastructure.flow_run_history_purge_repo import (
    flow_run_undelivered_audit_exists,
    flow_run_unresolved_webhook_exists,
)
from eneo.flows.infrastructure.flow_run_retention_policy_query import (
    effective_flow_run_retention_policy_sql,
    flow_run_history_eligible_since_sql,
)

# The status route and nightly snapshot share one result cap.
FLOW_RUN_HISTORY_OVERDUE_CAP = 1000
FLOW_RUN_HISTORY_DIAGNOSTIC_WINDOW = 500

FLOW_RUN_RETENTION_ANCHOR: sa.ColumnElement[datetime] = sa.func.coalesce(
    FlowRuns.finished_at, FlowRuns.created_at
)


def flow_run_k4_due_predicates(
    *,
    flow_id: sa.ColumnElement[UUID] | UUID,
    cutoff: sa.ColumnElement[datetime],
) -> tuple[sa.ColumnElement[bool], ...]:
    """A run of `flow_id` due at `cutoff`; the predicate of the K4 due index."""
    return (
        FlowRuns.flow_id == flow_id,
        # Inline values, so a generic plan of the prepared statement still
        # proves the partial index predicate.
        FlowRuns.status.in_(
            sa.bindparam(
                "k4_terminal_statuses",
                value=list(TERMINAL_FLOW_RUN_STATUS_VALUES),
                expanding=True,
                literal_execute=True,
            )
        ),
        FlowRuns.retention_receipt_id.is_(None),
        FLOW_RUN_RETENTION_ANCHOR <= cutoff,
    )


# flow_id, tenant_id, space_id, mode, days, level, Flow under a legal hold.
_RuleRow = tuple[UUID, UUID, UUID, str | None, int | None, str | None, bool]


def auto_delete_flows() -> sa.Select[_RuleRow]:
    """Flows whose effective rule is auto_delete, with the rule's days and level.

    Retired Flows are included: their run history keeps its rule.
    """
    return flow_history_rules(modes=(FlowRunRetentionMode.AUTO_DELETE,))


def flow_history_rules(*, modes: Sequence[FlowRunRetentionMode]) -> sa.Select[_RuleRow]:
    """Flows whose effective rule has one of `modes`, with the rule (mode, days,
    level and the id of the level that set it)."""
    effective = effective_flow_run_retention_policy_sql(
        organization_mode=Tenants.flow_run_history_retention_mode.__clause_element__(),
        organization_days=Tenants.flow_run_history_retention_days.__clause_element__(),
        space_mode=Spaces.flow_run_history_retention_mode.__clause_element__(),
        space_days=Spaces.flow_run_history_retention_days.__clause_element__(),
        flow_mode=Flows.flow_run_history_retention_mode.__clause_element__(),
        flow_days=Flows.flow_run_history_retention_days.__clause_element__(),
    )
    return (
        sa.select(
            Flows.id.label("flow_id"),
            Flows.tenant_id.label("tenant_id"),
            Flows.space_id.label("space_id"),
            effective.mode.label("mode"),
            effective.days.label("days"),
            effective.source.label("source"),
            flow_runless_data_held_predicate(flow_id=Flows.id).label("flow_held"),
        )
        .join(
            Spaces,
            sa.and_(Spaces.id == Flows.space_id, Spaces.tenant_id == Flows.tenant_id),
        )
        .join(Tenants, Tenants.id == Flows.tenant_id)
        .where(effective.mode.in_([mode.value for mode in modes]))
    )


@dataclass(frozen=True, slots=True)
class FlowHistoryRule:
    """The rule in force for one Flow's run history, at selection."""

    flow_id: UUID
    tenant_id: UUID
    space_id: UUID
    mode: FlowRunRetentionMode
    days: int
    source: RetentionPolicySource
    # A legal hold on the whole Flow: none of its runs is deleted.
    held: bool

    @property
    def scope_id(self) -> UUID:
        """The Organization, Space or Flow whose rule this is."""
        if self.source is RetentionPolicySource.FLOW:
            return self.flow_id
        if self.source is RetentionPolicySource.SPACE:
            return self.space_id
        return self.tenant_id

    def cutoff(self, now: datetime) -> datetime:
        return now - timedelta(days=self.days)


def _rule(row: sa.Row[_RuleRow]) -> FlowHistoryRule:
    flow_id, tenant_id, space_id, mode, days, source, held = row
    policy = flow_run_retention_policy_from_storage(mode=mode, days=days)
    if policy is None or source is None:
        raise FlowRunRetentionPolicyStorageError(
            "An effective Flow run-history rule lacks its mode, days or level."
        )
    return FlowHistoryRule(
        flow_id=flow_id,
        tenant_id=tenant_id,
        space_id=space_id,
        mode=policy.mode,
        days=policy.days,
        source=RetentionPolicySource(source),
        held=held,
    )


@dataclass(frozen=True, slots=True)
class FlowRunHistoryOverdue:
    """Due auto_delete runs still stored past their deadline plus the window.

    The cap bounds returned runs; eligibility scans may examine more rows.
    Held runs past the same window are counted apart, up to the cap.
    """

    count: int
    complete: bool
    oldest_due_at: datetime | None
    held: int
    undelivered_audit: int
    unresolved_webhook: int
    not_yet_deleted: int


@dataclass(frozen=True, slots=True)
class FlowRunHistoryReceiptSummary:
    unfinished: int
    oldest_unfinished_started_at: datetime | None
    oldest_physical_pending_completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class FlowRunHistoryBlockedCounts:
    undelivered_audit: int
    unresolved_webhook: int
    review_required: int
    legal_hold: int
    counted_runs: int
    complete: bool


class FlowRunHistoryDueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def rules(
        self,
        *,
        modes: Sequence[FlowRunRetentionMode],
        after: UUID | None,
        limit: int,
        tenant_id: UUID | None = None,
        space_id: UUID | None = None,
        flow_id: UUID | None = None,
        inclusive: bool = True,
    ) -> list[FlowHistoryRule]:
        """One current rule range; exclusive after a completed Flow."""
        stmt = flow_history_rules(modes=modes).order_by(Flows.id).limit(limit)
        if after is not None:
            stmt = stmt.where(Flows.id >= after if inclusive else Flows.id > after)
        if tenant_id is not None:
            stmt = stmt.where(Flows.tenant_id == tenant_id)
        if space_id is not None:
            stmt = stmt.where(Flows.space_id == space_id)
        if flow_id is not None:
            stmt = stmt.where(Flows.id == flow_id)
        return [_rule(row) for row in await self.session.execute(stmt)]

    async def diagnostics(
        self,
        *,
        modes: Sequence[FlowRunRetentionMode],
        now: datetime,
        window: int,
        tenant_id: UUID,
        space_id: UUID | None,
        flow_id: UUID | None,
    ) -> FlowRunHistoryBlockedCounts:
        """Two global queries with separate sentinel windows for held and other runs.

        The statement timeout bounds eligibility scans. Held runs cannot displace
        other blocked runs from the diagnostic window.
        """
        rules = flow_history_rules(modes=modes).where(Flows.tenant_id == tenant_id)
        if space_id is not None:
            rules = rules.where(Flows.space_id == space_id)
        if flow_id is not None:
            rules = rules.where(Flows.id == flow_id)
        flows = rules.subquery("diagnostic_flows")
        cutoff = sa.cast(
            sa.literal(now), sa.TIMESTAMP(timezone=True)
        ) - sa.func.make_interval(0, 0, 0, flows.c.days)
        held = sa.or_(
            flows.c.flow_held,
            flow_run_held_predicate(run_id=FlowRuns.id, flow_id=FlowRuns.flow_id),
        )
        due = (
            sa.select(
                FlowRuns.id.label("run_id"),
                flows.c.mode,
                FLOW_RUN_RETENTION_ANCHOR.label("anchor"),
            )
            .select_from(flows)
            .join(FlowRuns, FlowRuns.flow_id == flows.c.flow_id)
            .where(*flow_run_k4_due_predicates(flow_id=flows.c.flow_id, cutoff=cutoff))
        )
        held_count = int(
            await self.session.scalar(
                sa.select(sa.func.count()).select_from(
                    due.where(held).limit(window + 1).subquery()
                )
            )
            or 0
        )
        window_runs = (
            due.where(sa.not_(held))
            .order_by(FLOW_RUN_RETENTION_ANCHOR, FlowRuns.id)
            .limit(window + 1)
            .subquery("diagnostic_runs")
        )
        rows = (
            await self.session.execute(
                sa.select(
                    window_runs.c.mode,
                    flow_run_undelivered_audit_exists(window_runs.c.run_id).label(
                        "audit"
                    ),
                    flow_run_unresolved_webhook_exists(window_runs.c.run_id).label(
                        "webhook"
                    ),
                ).order_by(window_runs.c.anchor, window_runs.c.run_id)
            )
        ).all()
        page = rows[:window]
        review = audit = webhook = 0
        for row in page:
            mode = FlowRunRetentionMode(row.mode)
            if mode is FlowRunRetentionMode.REVIEW_REQUIRED:
                review += 1
            elif row.audit:
                audit += 1
            elif row.webhook:
                webhook += 1
        return FlowRunHistoryBlockedCounts(
            undelivered_audit=audit,
            unresolved_webhook=webhook,
            review_required=review,
            legal_hold=min(held_count, window),
            counted_runs=len(page),
            complete=len(rows) <= window and held_count <= window,
        )

    async def overdue(
        self,
        *,
        now: datetime,
        window: timedelta,
        cap: int,
        tenant_id: UUID | None = None,
    ) -> FlowRunHistoryOverdue:
        """Return at most `cap` overdue runs, oldest deadline first.

        Held runs are excluded from overdue results and counted separately.
        A sentinel detects an incomplete page; per-Flow eligibility scans can
        examine additional rows before the global result limit applies.
        """
        flows_query = auto_delete_flows()
        if tenant_id is not None:
            flows_query = flows_query.where(Flows.tenant_id == tenant_id)
        flows = flows_query.subquery("k4_flows")
        overdue_before = sa.cast(sa.literal(now - window), sa.TIMESTAMP(timezone=True))
        cutoff = overdue_before - sa.func.make_interval(0, 0, 0, flows.c.days)
        due_at = flow_run_history_eligible_since_sql(
            anchor=FLOW_RUN_RETENTION_ANCHOR, effective_days=flows.c.days
        )

        def past_window(*extra: sa.ColumnElement[bool]) -> LateralFromClause:
            return (
                sa.select(
                    FlowRuns.id.label("run_id"),
                    FlowRuns.flow_id.label("flow_id"),
                    due_at.label("due_at"),
                )
                .where(
                    *flow_run_k4_due_predicates(flow_id=flows.c.flow_id, cutoff=cutoff),
                    *extra,
                )
                .order_by(FLOW_RUN_RETENTION_ANCHOR, FlowRuns.id)
                .limit(cap + 1)
                .lateral()
            )

        runs = past_window(
            sa.not_(
                flow_run_held_predicate(run_id=FlowRuns.id, flow_id=FlowRuns.flow_id)
            )
        )
        rows = (
            await self.session.execute(
                sa.select(
                    runs.c.due_at,
                    flow_run_undelivered_audit_exists(runs.c.run_id).label("audit"),
                    flow_run_unresolved_webhook_exists(runs.c.run_id).label("webhook"),
                )
                .select_from(flows)
                .join(runs, sa.true())
                .where(sa.not_(flows.c.flow_held))
                .order_by(runs.c.due_at, runs.c.run_id)
                .limit(cap + 1)
            )
        ).all()
        overdue = rows[:cap]
        audit = sum(1 for row in overdue if row.audit)
        webhook = sum(1 for row in overdue if row.webhook and not row.audit)
        held_flow_runs = past_window()
        held_in_held_flows = await self.session.scalar(
            sa.select(sa.func.count()).select_from(
                sa.select(held_flow_runs.c.run_id)
                .select_from(flows)
                .join(held_flow_runs, sa.true())
                .where(flows.c.flow_held)
                .limit(cap)
                .subquery()
            )
        )
        held_runs = await self.session.scalar(
            sa.select(sa.func.count()).select_from(
                sa.select(FlowRuns.id)
                .distinct()
                .join(
                    FlowRetentionHolds,
                    sa.and_(
                        FlowRetentionHolds.flow_run_id == FlowRuns.id,
                        flow_retention_hold_is_active(),
                    ),
                )
                .join(flows, flows.c.flow_id == FlowRuns.flow_id)
                .where(
                    sa.not_(flows.c.flow_held),
                    *flow_run_k4_due_predicates(flow_id=flows.c.flow_id, cutoff=cutoff),
                )
                .limit(cap)
                .subquery()
            )
        )
        return FlowRunHistoryOverdue(
            count=len(overdue),
            complete=len(rows) <= cap,
            oldest_due_at=overdue[0].due_at if overdue else None,
            held=min(cap, int(held_in_held_flows or 0) + int(held_runs or 0)),
            undelivered_audit=audit,
            unresolved_webhook=webhook,
            not_yet_deleted=len(overdue) - audit - webhook,
        )

    async def receipts(self) -> FlowRunHistoryReceiptSummary:
        """Unfinished and physically unconfirmed deletion receipts of flows.history."""
        unfinished = RetentionReceipts.phase.in_(
            [phase.value for phase in NON_FINAL_RECEIPT_PHASES]
        )
        task = RetentionReceipts.task == FLOWS_HISTORY_TASK
        not_pruning = RetentionReceipts.pruning_started_at.is_(None)
        row = (
            await self.session.execute(
                sa.select(
                    sa.select(sa.func.count())
                    .where(task, unfinished, not_pruning)
                    .scalar_subquery(),
                    sa.select(sa.func.min(RetentionReceipts.started_at))
                    .where(task, unfinished, not_pruning)
                    .scalar_subquery(),
                    sa.select(sa.func.min(RetentionReceipts.completed_at))
                    .where(
                        task,
                        not_pruning,
                        RetentionReceipts.phase == ReceiptPhase.COMPLETED.value,
                        RetentionReceipts.physical_confirmed_at.is_(None),
                    )
                    .scalar_subquery(),
                )
            )
        ).one()
        return FlowRunHistoryReceiptSummary(
            unfinished=int(row[0] or 0),
            oldest_unfinished_started_at=row[1],
            oldest_physical_pending_completed_at=row[2],
        )
