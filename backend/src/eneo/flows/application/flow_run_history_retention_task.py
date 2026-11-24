"""Flow runs that started while their space had a time go once it has passed.

Every five minutes, a run that its shared space's time (or its flow's shorter
time) has made due is removed whole, with its files, one run per savepoint.
Only a run marked when it started is taken, and only while the space has its
time; the explicit purge selects by the time alone.
"""

import logging
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionContractError,
    RetentionOwnershipLost,
    RetentionStep,
    RetentionStepResult,
    is_retention_timeout,
)
from eneo.data_retention.application.retention_units import (
    RetentionEffects,
    RetentionUnitCandidate,
    RetentionUnitDisposition,
    RetentionUnitUsage,
    gather_retention_units,
)
from eneo.data_retention.domain.retention import RetentionKeyset
from eneo.data_retention.infrastructure.gallring_lock import (
    GallringLockBusy,
    GallringSubject,
    acquire_shared,
)
from eneo.files.file_retention import FileRetentionReason
from eneo.flows.infrastructure.flow_retention_repo import FlowRetentionRepository
from eneo.flows.infrastructure.flow_run_history_purge_repo import (
    FlowRunHistoryPurgeRepository,
    FlowRunRemoval,
    FlowRunRemovalOutcome,
)
from eneo.observability.error_log import log_error

logger = logging.getLogger(__name__)

FLOW_RUN_HISTORY_TASK = "flows.run_history"

# Blocked reasons: each leaves a due run in place and keeps the pass from
# being clean until it is resolved.
UNIT_EXCEEDS_BUDGET = "unit_exceeds_budget"
RUN_FAILED = "run_failed"
RUN_LOCKED = "run_locked"
# An observation: a hold or a delivery arrived after the selection.
NOT_PURGEABLE = "not_purgeable"

_FILES_KEPT = (
    FileRetentionReason.IN_USE,
    FileRetentionReason.MISSING,
    FileRetentionReason.NOT_ROOT,
)
# SQLSTATE classes of an error in one run's rows: data (22) and integrity (23).
_RUN_DATA_CLASSES = frozenset({"22", "23"})


def is_run_failure(error: BaseException) -> bool:
    """Whether an error that rolled one run back is that run's own, so the run
    is blocked as run_failed and the pass goes on.

    The run's own: an error the removal raises itself, not from the database,
    and a database error of class 22 or 23. Everything else propagates to the
    runner, which ends the chunk: its own errors; a statement or lock timeout,
    a deadlock or a busy gallring lock (retried by the next execution); a
    connection the driver invalidated, an operational or interface error; and
    every other SQLSTATE, such as 08 (connection), 28 (sign-in), 42 (syntax or
    privilege, 42501), 53 (resources), 57 (operator), 58 (system) and XX
    (internal), which would fail every run alike."""
    if isinstance(
        error, (RetentionContractError, RetentionOwnershipLost, GallringLockBusy)
    ) or is_retention_timeout(error):
        return False
    cause: BaseException | None = error
    while cause is not None:
        if isinstance(cause, DBAPIError):
            if cause.connection_invalidated or isinstance(
                cause, (OperationalError, InterfaceError)
            ):
                return False
            sqlstate = getattr(cause.orig, "sqlstate", None)
            return isinstance(sqlstate, str) and sqlstate[:2] in _RUN_DATA_CLASSES
        cause = cause.__cause__
    return True


class FlowRunHistoryRetentionTask:
    name = FLOW_RUN_HISTORY_TASK
    count_keys = frozenset(
        {
            "runs_deleted",
            "run_rows_deleted",
            "uploads_released",
            "live_transcripts_deleted",
            "roots_deleted",
            "files_deleted",
            "file_dependencies_deleted",
            "input_primary_bytes",
        }
    )
    # A run the recheck refused, or a File that stays, is progress, not audit.
    observation_keys = frozenset(
        {NOT_PURGEABLE, *(reason.key for reason in _FILES_KEPT)}
    )
    blocked_keys = frozenset({UNIT_EXCEEDS_BUDGET, RUN_FAILED, RUN_LOCKED})
    # A run it cannot remove stays due: a restore is not complete with it.
    not_due_keys: frozenset[str] = frozenset()

    def __init__(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        family_rows: int,
        chunk_rows: int,
        execution_rows: int,
        execution_files: int,
        gather_seconds: float,
    ) -> None:
        self.session = session
        self.now = now
        self.selection = FlowRetentionRepository(session)
        self.purge = FlowRunHistoryPurgeRepository(session)
        self.family_rows = family_rows
        self.chunk_rows = chunk_rows
        self.gather_seconds = gather_seconds
        self.max_batch = max(chunk_rows, family_rows + 1)
        self.execution_files = execution_files
        # A run's whole room: the most a fresh call of this step can give.
        self.unit_rows = min(self.max_batch, execution_rows)
        self.unit_files = execution_files

    def steps(self) -> Sequence[RetentionStep]:
        return (
            RetentionStep(
                "runs",
                self._runs,
                max_batch=self.max_batch,
                max_files=self.execution_files,
            ),
        )

    async def has_due(self) -> bool:
        return await self.selection.has_run_due_for_removal(now=self.now)

    async def _runs(self, batch: RetentionBatch) -> RetentionStepResult:
        # Before any selection: a change of a time or a hold commits before
        # this read or after this transaction.
        await acquire_shared(self.session, GallringSubject.FLOW_HISTORY)
        out = RetentionEffects()

        async def next_candidate(
            cursor: RetentionKeyset | None,
        ) -> RetentionUnitCandidate | None:
            found = await self.selection.next_run_due_for_removal(
                now=self.now,
                after=(cursor.at, cursor.id) if cursor is not None else None,
            )
            if found is None:
                return None
            at, run_id = found

            async def handle(rows: int, files: int) -> RetentionUnitUsage:
                return await self._remove(run_id, rows=rows, files=files, out=out)

            return RetentionKeyset(at=at, id=run_id), handle

        return await gather_retention_units(
            next_candidate,
            out,
            max_rows=batch.rows,
            max_files=batch.files,
            cursor=batch.cursor,
            chunk_rows=self.chunk_rows,
            gather_seconds=self.gather_seconds,
            deadline=batch.deadline,
        )

    async def _remove(
        self, run_id: UUID, *, rows: int, files: int, out: RetentionEffects
    ) -> RetentionUnitUsage:
        removal = await self.purge.purge_due_run(
            run_id,
            max_rows=rows,
            max_files=files,
            max_family_rows=self.family_rows,
        )
        usage = RetentionUnitUsage(rows=removal.rows, files=removal.files)
        match removal.outcome:
            case FlowRunRemovalOutcome.REMOVED:
                self._removed(removal, out)
            case FlowRunRemovalOutcome.NOT_PURGEABLE:
                out.add(None, NOT_PURGEABLE)
            case FlowRunRemovalOutcome.LOCKED:
                out.blocked[RUN_LOCKED] += 1
            case FlowRunRemovalOutcome.SHORT if (
                rows < self.unit_rows or files < self.unit_files
            ):
                # Short of a run's whole room: retried in a fresh chunk.
                return RetentionUnitUsage(
                    rows=removal.rows,
                    files=removal.files,
                    disposition=RetentionUnitDisposition.DOES_NOT_FIT,
                )
            case FlowRunRemovalOutcome.SHORT | FlowRunRemovalOutcome.TOO_LARGE:
                out.blocked[UNIT_EXCEEDS_BUDGET] += 1
            case FlowRunRemovalOutcome.REFUSED:
                self._failed(run_id, None, out)
            case FlowRunRemovalOutcome.FAILED if removal.error is not None:
                if not is_run_failure(removal.error):
                    raise removal.error
                self._failed(run_id, removal.error, out)
        return usage

    @staticmethod
    def _removed(removal: FlowRunRemoval, out: RetentionEffects) -> None:
        tenant = removal.tenant_id
        out.add(tenant, "runs_deleted")
        out.add(tenant, "run_rows_deleted", removal.run_rows)
        out.add(tenant, "uploads_released", removal.uploads_released)
        out.add(tenant, "live_transcripts_deleted", removal.live_transcripts_deleted)
        out.add(tenant, "roots_deleted", removal.roots_deleted)
        out.add(tenant, "files_deleted", removal.files_deleted)
        out.add(tenant, "file_dependencies_deleted", removal.file_dependencies_deleted)
        out.add(tenant, "input_primary_bytes", removal.input_primary_bytes)
        for reason, kept in removal.files_kept.items():
            out.add(None, reason.key, kept)

    @staticmethod
    def _failed(
        run_id: UUID, error: BaseException | None, out: RetentionEffects
    ) -> None:
        out.blocked[RUN_FAILED] += 1
        if error is None:
            logger.error("Flow run %s was kept: the file owner refused a file.", run_id)
            return
        log_error(
            logger,
            logging.ERROR,
            "Flow run %s could not be removed",
            run_id,
            error=error,
        )
