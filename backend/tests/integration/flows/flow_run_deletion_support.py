"""Test support: delete Flow runs through the one flow-owned deletion command.

`delete_run` admits one named run whatever its policy (a test of the deletion
mechanics, not of due selection) and deletes it within a budget; `purge` runs
the explicit deletion command over the supplied tenant scope.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_units import (
    RetentionEffects,
    RetentionUnitCandidate,
    RetentionUnitDisposition,
    RetentionUnitUsage,
    gather_retention_units,
)
from eneo.data_retention.domain.retention import (
    RetentionKeyset,
    RetentionPolicySource,
    RetentionReceipt,
    RetentionTrigger,
)
from eneo.database.tables.flow_tables import FlowRuns, Flows
from eneo.flows.application.flow_run_history_deletion import (
    EXPLICIT_MODES,
    FlowRunHistoryDeletion,
    PurgeScope,
    RunDeletionProgress,
    due_blocked_reason,
)
from eneo.flows.application.flow_run_history_purge import (
    ExplicitPurgeResult,
    FlowRunHistoryExplicitPurge,
)
from eneo.flows.domain.flow_run_retention_policy import FlowRunRetentionMode
from eneo.flows.infrastructure.flow_run_deletion_repo import DueRun
from eneo.flows.infrastructure.flow_run_history_due_repo import (
    FLOW_RUN_RETENTION_ANCHOR,
    FlowHistoryRule,
)


async def delete_run(
    session: AsyncSession,
    run_id: UUID,
    *,
    max_rows: int = 50_000,
    max_files: int = 10_000,
    family_rows: int | None = None,
) -> tuple[RetentionEffects, RetentionReceipt | None]:
    """Admit the run (rechecked on its locked row) and advance its deletion."""
    deletion = FlowRunHistoryDeletion(session, family_rows=family_rows)
    await deletion.lock()
    row = (
        await session.execute(
            sa.select(
                FlowRuns.flow_id,
                FlowRuns.tenant_id,
                Flows.space_id,
                FLOW_RUN_RETENTION_ANCHOR.label("anchor"),
                FlowRuns.retention_receipt_id,
            )
            .join(Flows, Flows.id == FlowRuns.flow_id)
            .where(FlowRuns.id == run_id)
        )
    ).one()
    rule = FlowHistoryRule(
        flow_id=row.flow_id,
        tenant_id=row.tenant_id,
        space_id=row.space_id,
        mode=FlowRunRetentionMode.PRESERVE,
        days=1,
        source=RetentionPolicySource.FLOW,
        held=False,
    )
    out = RetentionEffects()
    if row.retention_receipt_id is not None:
        progress = RunDeletionProgress(
            RetentionUnitUsage(1, 0),
            await deletion.receipts.lock(row.retention_receipt_id),
        )
    else:
        progress = await deletion.admit(
            rule,
            DueRun(
                run_id=run_id,
                anchor=row.anchor,
                held=False,
                undelivered_audit=False,
                unresolved_webhook=False,
            ),
            trigger=RetentionTrigger.EXPLICIT,
            triggered_by_user_id=None,
            out=out,
            rows=max_rows,
            # Named-run mechanics tests admit at its deadline; due selection has
            # its own real-clock cases in the task and request tests.
            now=max(datetime.now(timezone.utc), row.anchor + timedelta(days=rule.days)),
        )
    receipt = progress.receipt
    pending = receipt

    async def next_candidate(
        after: RetentionKeyset | None,
    ) -> RetentionUnitCandidate | None:
        nonlocal pending, receipt
        if pending is None:
            return None
        current = pending

        async def handle(rows: int, files: int) -> RetentionUnitUsage:
            nonlocal pending, receipt
            unit = await deletion.advance(current, rows=rows, files=files, out=out)
            receipt = unit.receipt
            pending = (
                receipt
                if unit.usage.disposition is RetentionUnitDisposition.CONTINUE
                else None
            )
            return (
                replace(unit.usage, disposition=RetentionUnitDisposition.DONE)
                if pending is not None
                else unit.usage
            )

        return RetentionKeyset(at=current.started_at, id=current.id), handle

    if receipt is not None and max_rows > progress.usage.rows:
        await gather_retention_units(
            next_candidate,
            out,
            max_rows=max_rows - progress.usage.rows,
            max_files=max_files,
            cursor=None,
            chunk_rows=max_rows,
            gather_seconds=60,
        )
    return out, receipt


async def purge(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    now: datetime | None = None,
    limit: int = 10,
    user_id: UUID | None = None,
    space_id: UUID | None = None,
    flow_id: UUID | None = None,
    dry_run: bool = False,
    max_rows: int = 50_000,
    max_files: int = 10_000,
) -> ExplicitPurgeResult:
    explicit = FlowRunHistoryExplicitPurge(session)
    return await explicit.run(
        PurgeScope(tenant_id=tenant_id, space_id=space_id, flow_id=flow_id),
        now=now or datetime.now(timezone.utc),
        limit=limit,
        dry_run=dry_run,
        triggered_by_user_id=user_id,
        max_rows=max_rows,
        max_files=max_files,
    )


async def due_run_ids(
    session: AsyncSession, tenant_id: UUID, *, now: datetime
) -> tuple[set[UUID], set[UUID]]:
    """(due runs under preserve or auto_delete, those the purge would admit)."""
    deletion = FlowRunHistoryDeletion(session)
    due: set[UUID] = set()
    admissible: set[UUID] = set()
    for rule in await deletion.rules.rules(
        modes=EXPLICIT_MODES,
        after=None,
        limit=10_000,
        tenant_id=tenant_id,
        now=now,
        trigger=RetentionTrigger.SCHEDULED,
    ):
        for candidate in await deletion.candidates(
            rule, now=now, after=None, limit=10_000, trigger=RetentionTrigger.SCHEDULED
        ):
            due.add(candidate.run_id)
            if not rule.held and due_blocked_reason(candidate) is None:
                admissible.add(candidate.run_id)
    return due, admissible
