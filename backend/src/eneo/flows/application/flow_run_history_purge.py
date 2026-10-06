"""Explicit Flow run-history purge through the shared retention-unit engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_runner import RetentionTenantEffect
from eneo.data_retention.application.retention_sql_limits import (
    retention_request_sql_limits,
)
from eneo.data_retention.application.retention_units import (
    RetentionEffects,
    gather_retention_units,
)
from eneo.data_retention.domain.retention import RetentionTrigger
from eneo.flows.application.flow_run_history_deletion import (
    EXPLICIT_MODES,
    FlowRunHistoryDeletion,
    PurgeScope,
    RunHistorySelection,
)
from eneo.flows.domain.flow_run_retention_policy import FlowRunRetentionMode
from eneo.flows.infrastructure.flow_run_history_due_repo import (
    FLOW_RUN_HISTORY_DIAGNOSTIC_WINDOW,
    FlowRunHistoryBlockedCounts,
)
from eneo.main.config import get_settings

_DIAGNOSED_MODES = (*EXPLICIT_MODES, FlowRunRetentionMode.REVIEW_REQUIRED)


@dataclass(frozen=True, slots=True)
class ExplicitPurgeResult:
    selection_complete: bool
    candidate_count: int
    purged_run_ids: tuple[UUID, ...]
    pending_receipt_ids: tuple[UUID, ...]
    effects: tuple[RetentionTenantEffect, ...]
    blocked: Mapping[str, int]


class FlowRunHistoryExplicitPurge:
    """The administrator's purge: the same command with explicit admission.

    Flows in scope under preserve or auto_delete, in id order, and per Flow its
    due runs oldest first; held and blocked runs are passed. Admitted runs are
    deleted within the request's budget; a run the budget cuts short keeps its
    explicit receipt for later nightly executions, subject to fresh checks and caps.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.deletion = FlowRunHistoryDeletion(session)

    async def blocked(
        self, scope: PurgeScope, *, now: datetime
    ) -> FlowRunHistoryBlockedCounts:
        """Count due runs by blocker in independent global sentinel windows."""
        settings = get_settings()
        async with retention_request_sql_limits(
            self.session,
            statement_timeout_ms=settings.gallring_chunk_statement_timeout_ms,
            lock_timeout_ms=settings.gallring_chunk_lock_timeout_ms,
        ):
            return await self.deletion.rules.diagnostics(
                modes=_DIAGNOSED_MODES,
                now=now,
                window=FLOW_RUN_HISTORY_DIAGNOSTIC_WINDOW,
                tenant_id=scope.tenant_id,
                space_id=scope.space_id,
                flow_id=scope.flow_id,
            )

    async def run(
        self,
        scope: PurgeScope,
        *,
        now: datetime,
        limit: int,
        dry_run: bool,
        triggered_by_user_id: UUID | None,
        max_rows: int,
        max_files: int,
    ) -> ExplicitPurgeResult:
        """Admit up to `limit` due runs in scope; delete them unless `dry_run`."""
        settings = get_settings()
        async with retention_request_sql_limits(
            self.session,
            statement_timeout_ms=settings.gallring_chunk_statement_timeout_ms,
            lock_timeout_ms=settings.gallring_chunk_lock_timeout_ms,
        ):
            if not dry_run:
                await self.deletion.lock()
            out = RetentionEffects()
            selection = RunHistorySelection()
            collected = await gather_retention_units(
                self.deletion.due_candidates(
                    now=now,
                    modes=EXPLICIT_MODES,
                    trigger=RetentionTrigger.EXPLICIT,
                    triggered_by_user_id=triggered_by_user_id,
                    out=out,
                    selection=selection,
                    scope=scope,
                    limit=limit,
                    dry_run=dry_run,
                ),
                out,
                max_rows=max_rows,
                max_files=max_files,
                cursor=None,
                chunk_rows=max_rows,
                gather_seconds=get_settings().gallring_family_gather_seconds,
                min_candidate_rows=2,
            )
            return ExplicitPurgeResult(
                # None from the producer can also mean the request limit was
                # reached, so exhaustion alone cannot prove scope exhaustion.
                selection_complete=collected.exhausted
                and selection.candidate_count < limit,
                candidate_count=selection.candidate_count,
                purged_run_ids=tuple(selection.purged_run_ids),
                effects=collected.effects,
                blocked=collected.blocked,
                pending_receipt_ids=tuple(
                    receipt_id
                    for receipt_id in selection.admitted_receipt_ids
                    if receipt_id not in selection.completed_receipt_ids
                ),
            )
