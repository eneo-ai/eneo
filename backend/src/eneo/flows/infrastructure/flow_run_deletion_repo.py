"""Statements of the bounded deletion of one Flow run (flows.history and the
explicit purge). Run and family queries are shared by the Flow adopters.

Due selection per Flow over the K4 due index, the admission checks on the
locked run row, the fence, the run's file links (its links are the cursor of
its file families) and its child rows, deleted in foreign-key order with the
run row last; each call deletes at most `limit` rows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from eneo.data_retention.infrastructure.retention_sql import uuid_in
from eneo.database.affected_rows import affected_row_count
from eneo.database.tables.base_class import BaseWithTableName
from eneo.database.tables.flow_tables import (
    FlowProviderCalls,
    FlowRunAuditOutbox,
    FlowRunReviewCheckpointEdits,
    FlowRunReviewCheckpoints,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRuntimeUploadedFiles,
    FlowRunWebhookDeliveries,
    FlowStepAttemptResolvedInputs,
    FlowStepAttempts,
    FlowStepResults,
    FlowStepTranscriptSources,
    FlowStepTranscriptWords,
    FlowTranscriptCorrectionRevisions,
    FlowTranscriptCorrections,
)
from eneo.database.tables.object_content_table import FileContentReferences
from eneo.flows.enums import TERMINAL_FLOW_RUN_STATUS_VALUES
from eneo.flows.infrastructure.flow_retention_hold_repo import flow_run_held_predicate
from eneo.flows.infrastructure.flow_run_history_due_repo import (
    FLOW_RUN_RETENTION_ANCHOR,
    flow_run_k4_due_predicates,
)
from eneo.flows.infrastructure.flow_run_history_purge_repo import (
    flow_run_undelivered_audit_exists,
    flow_run_unresolved_webhook_exists,
)


def _of_run(
    flow_run_id: InstrumentedAttribute[UUID],
) -> Callable[[UUID], sa.ColumnElement[bool]]:
    return lambda run_id: flow_run_id == run_id


def _attempts_of(run_id: UUID) -> sa.Select[tuple[UUID]]:
    return sa.select(FlowStepAttempts.id).where(FlowStepAttempts.flow_run_id == run_id)


def _corrections_of(run_id: UUID) -> sa.Select[tuple[UUID]]:
    return sa.select(FlowTranscriptCorrections.id).where(
        FlowTranscriptCorrections.flow_run_id == run_id
    )


# Every table below flow_runs, in deletion order: a table comes before every
# table it references. The run row goes after all of them. A test pins this
# list to the foreign-key graph, so a new child table fails until it is placed.
FLOW_RUN_CHILD_TABLES: tuple[
    tuple[type[BaseWithTableName], Callable[[UUID], sa.ColumnElement[bool]]], ...
] = (
    (FlowRunWebhookDeliveries, _of_run(FlowRunWebhookDeliveries.flow_run_id)),
    (FlowRunAuditOutbox, _of_run(FlowRunAuditOutbox.flow_run_id)),
    (FlowRunReviewCheckpointEdits, _of_run(FlowRunReviewCheckpointEdits.flow_run_id)),
    (FlowRunReviewCheckpoints, _of_run(FlowRunReviewCheckpoints.flow_run_id)),
    (
        FlowTranscriptCorrectionRevisions,
        lambda run_id: FlowTranscriptCorrectionRevisions.correction_set_id.in_(
            _corrections_of(run_id)
        ),
    ),
    (FlowTranscriptCorrections, _of_run(FlowTranscriptCorrections.flow_run_id)),
    (FlowStepTranscriptWords, _of_run(FlowStepTranscriptWords.flow_run_id)),
    (FlowStepTranscriptSources, _of_run(FlowStepTranscriptSources.flow_run_id)),
    (
        FlowProviderCalls,
        lambda run_id: FlowProviderCalls.flow_step_attempt_id.in_(_attempts_of(run_id)),
    ),
    (FlowRunStepResultFiles, _of_run(FlowRunStepResultFiles.flow_run_id)),
    (FlowRunStepInputFiles, _of_run(FlowRunStepInputFiles.flow_run_id)),
    (
        FlowStepAttemptResolvedInputs,
        lambda run_id: FlowStepAttemptResolvedInputs.flow_step_attempt_id.in_(
            _attempts_of(run_id)
        ),
    ),
    (FlowStepAttempts, _of_run(FlowStepAttempts.flow_run_id)),
    (FlowStepResults, _of_run(FlowStepResults.flow_run_id)),
)


@dataclass(frozen=True, slots=True)
class DueRun:
    run_id: UUID
    anchor: datetime
    held: bool
    undelivered_audit: bool
    unresolved_webhook: bool


@dataclass(frozen=True, slots=True)
class LockedRun:
    id: UUID
    tenant_id: UUID
    flow_id: UUID
    anchor: datetime
    retention_receipt_id: UUID | None


@dataclass(frozen=True, slots=True)
class ChildDeletion:
    # Rows deleted by this call (child rows, then the run row).
    rows: int
    # The run row is gone.
    root_deleted: bool


@dataclass(frozen=True, slots=True)
class RunBlockers:
    terminal: bool
    held: bool
    undelivered_audit: bool
    unresolved_webhook: bool

    @property
    def clear(self) -> bool:
        return (
            self.terminal
            and not self.held
            and not self.undelivered_audit
            and not self.unresolved_webhook
        )


def run_file_roots(run_id: UUID) -> sa.CompoundSelect[tuple[UUID]]:
    """The run's own file roots: its result files and its consumed inputs."""
    return sa.union_all(
        sa.select(FlowRunStepResultFiles.file_id.label("file_id")).where(
            FlowRunStepResultFiles.flow_run_id == run_id
        ),
        sa.select(FlowRunStepInputFiles.file_id.label("file_id")).where(
            FlowRunStepInputFiles.flow_run_id == run_id
        ),
    )


class FlowRunDeletionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def due_runs(
        self,
        *,
        flow_id: UUID,
        cutoff: datetime,
        after: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[DueRun]:
        """The Flow's next `limit` due runs in anchor order, with their blockers.

        Ranges over ix_flow_runs_flow_gallring_due from a literal cutoff; the
        blockers are evaluated per examined run, never in the range condition, so
        a blocked prefix is passed once per pass.
        """
        stmt = (
            sa.select(
                FlowRuns.id,
                FLOW_RUN_RETENTION_ANCHOR.label("anchor"),
                flow_run_held_predicate(
                    run_id=FlowRuns.id, flow_id=FlowRuns.flow_id
                ).label("held"),
                flow_run_undelivered_audit_exists(FlowRuns.id).label("audit"),
                flow_run_unresolved_webhook_exists(FlowRuns.id).label("webhook"),
            )
            .where(
                *flow_run_k4_due_predicates(
                    flow_id=flow_id,
                    cutoff=sa.cast(sa.literal(cutoff), sa.TIMESTAMP(timezone=True)),
                )
            )
            .order_by(FLOW_RUN_RETENTION_ANCHOR, FlowRuns.id)
            .limit(limit)
        )
        if after is not None:
            stmt = stmt.where(
                sa.tuple_(FLOW_RUN_RETENTION_ANCHOR, FlowRuns.id)
                > sa.tuple_(
                    sa.cast(sa.literal(after[0]), sa.TIMESTAMP(timezone=True)),
                    sa.literal(after[1]),
                )
            )
        return [
            DueRun(
                run_id=row.id,
                anchor=row.anchor,
                held=row.held,
                undelivered_audit=row.audit,
                unresolved_webhook=row.webhook,
            )
            for row in await self.session.execute(stmt)
        ]

    async def lock_run(self, run_id: UUID) -> LockedRun | None:
        """The run row, locked for this transaction; None if it is gone or another
        transaction holds it (a retry copying it, another deleter)."""
        row = (
            await self.session.execute(
                sa.select(
                    FlowRuns.id,
                    FlowRuns.tenant_id,
                    FlowRuns.flow_id,
                    FLOW_RUN_RETENTION_ANCHOR.label("anchor"),
                    FlowRuns.retention_receipt_id,
                )
                .where(FlowRuns.id == run_id)
                .with_for_update(of=FlowRuns, skip_locked=True)
            )
        ).one_or_none()
        if row is None:
            return None
        return LockedRun(
            id=row.id,
            tenant_id=row.tenant_id,
            flow_id=row.flow_id,
            anchor=row.anchor,
            retention_receipt_id=row.retention_receipt_id,
        )

    async def run_exists(self, run_id: UUID) -> bool:
        return (
            await self.session.scalar(
                sa.select(FlowRuns.id).where(FlowRuns.id == run_id)
            )
        ) is not None

    async def admissible(self, run_id: UUID) -> RunBlockers:
        """The locked run's blockers, read under the lock right before release."""
        row = (
            await self.session.execute(
                sa.select(
                    FlowRuns.status.in_(TERMINAL_FLOW_RUN_STATUS_VALUES).label(
                        "terminal"
                    ),
                    flow_run_held_predicate(
                        run_id=FlowRuns.id, flow_id=FlowRuns.flow_id
                    ).label("held"),
                    flow_run_undelivered_audit_exists(FlowRuns.id).label("audit"),
                    flow_run_unresolved_webhook_exists(FlowRuns.id).label("webhook"),
                ).where(FlowRuns.id == run_id)
            )
        ).one()
        return RunBlockers(
            terminal=row.terminal,
            held=row.held,
            undelivered_audit=row.audit,
            unresolved_webhook=row.webhook,
        )

    async def held(self, *, run_id: UUID, flow_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                sa.select(flow_run_held_predicate(run_id=run_id, flow_id=flow_id))
            )
        )

    async def fence(self, run_id: UUID, receipt_id: UUID) -> None:
        """From here every reader treats the run as deleted."""
        await self.session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id, FlowRuns.retention_receipt_id.is_(None))
            .values(retention_receipt_id=receipt_id)
        )

    async def delete_children(self, run_id: UUID, *, limit: int) -> ChildDeletion:
        """Delete the next `limit` rows below the run, in foreign-key order, then
        the run row once nothing is left below it."""
        deleted = 0
        for table, of_run in FLOW_RUN_CHILD_TABLES:
            if deleted >= limit:
                return ChildDeletion(rows=deleted, root_deleted=False)
            deleted += await self._delete_page(
                table, of_run(run_id), limit=limit - deleted
            )
        if deleted >= limit:
            return ChildDeletion(rows=deleted, root_deleted=False)
        root = affected_row_count(
            await self.session.execute(sa.delete(FlowRuns).where(FlowRuns.id == run_id))
        )
        return ChildDeletion(rows=deleted + root, root_deleted=True)

    async def _delete_page(
        self,
        table: type[BaseWithTableName],
        condition: sa.ColumnElement[bool],
        *,
        limit: int,
    ) -> int:
        key = list(sa.inspect(table, raiseerr=True).primary_key)
        page = sa.select(*key).where(condition).limit(limit)
        target = key[0] if len(key) == 1 else sa.tuple_(*key)
        return affected_row_count(
            await self.session.execute(sa.delete(table).where(target.in_(page)))
        )

    # The run's file families -------------------------------------------------

    async def drop_links(self, run_id: UUID, file_ids: list[UUID]) -> int:
        """Delete this run's links to the given files (results and inputs); the
        rows deleted."""
        deleted = 0
        for table in (FlowRunStepResultFiles, FlowRunStepInputFiles):
            deleted += affected_row_count(
                await self.session.execute(
                    sa.delete(table).where(
                        table.flow_run_id == run_id, uuid_in(table.file_id, file_ids)
                    )
                )
            )
        return deleted

    async def upload_consumed(self, file_id: UUID) -> bool:
        """Another run still consumes the file as a runtime input."""
        return bool(
            await self.session.scalar(
                sa.select(
                    sa.select(sa.literal(1))
                    .select_from(FlowRunStepInputFiles)
                    .where(FlowRunStepInputFiles.file_id == file_id)
                    .exists()
                )
            )
        )

    async def lock_binding(self, file_id: UUID) -> tuple[bool, int]:
        """Lock the upload binding and charge the metadata rows examined."""
        binding = sa.select(FlowRuntimeUploadedFiles.file_id).where(
            FlowRuntimeUploadedFiles.file_id == file_id
        )
        if await self.session.scalar(binding) is None:
            return True, 1
        locked = await self.session.scalar(
            binding.with_for_update(of=FlowRuntimeUploadedFiles, skip_locked=True)
        )
        return locked is not None, 2

    async def root_without_content(self, run_id: UUID) -> bool:
        """A file root of the run has no stored content reference: its content
        cannot be recorded in the manifest, so the run is not released."""
        roots = run_file_roots(run_id).subquery()
        return bool(
            await self.session.scalar(
                sa.select(
                    sa.select(sa.literal(1))
                    .select_from(roots)
                    .where(
                        sa.not_(
                            sa.select(sa.literal(1))
                            .select_from(FileContentReferences)
                            .where(FileContentReferences.file_id == roots.c.file_id)
                            .exists()
                        )
                    )
                    .exists()
                )
            )
        )
