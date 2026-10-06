"""The flows.history retention task: automatic deletion of Flow run history (K4).

Steps, in order (each call is one chunk of the runner, which takes the flow
history retention lock SHARED first):

1. receipts: unfinished run deletions, oldest first, from the step's durable
   cursor; scheduled and explicit-purge receipts alike (an explicit purge that
   ran out of budget finishes here, as the system on behalf of that receipt).
2. runs: Flows whose effective rule is auto_delete, in id order, and per Flow
   its due runs in anchor order from a literal cutoff (the K4 due index). Every
   examined Flow and run is charged one row; held and blocked runs are passed and
   counted, so a blocked prefix costs one examination per pass. The durable
   cursor (Flow, anchor, run) carries the pass across executions; a finished
   pass starts again from the first Flow.
3. finish: revisit unfinished receipts, including new admissions, within the
   remaining budget.
   Its independent cursor cannot prevent the next due-run pass from restarting.

When an execution ends the runner records the overdue snapshot (`overdue`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionStep,
    RetentionStepResult,
)
from eneo.data_retention.application.retention_units import (
    RetentionEffects,
    RetentionUnitCandidate,
    RetentionUnitUsage,
    gather_retention_units,
)
from eneo.data_retention.domain.retention import (
    RetentionKeyset,
    RetentionOverdue,
    RetentionTrigger,
)
from eneo.flows.application.flow_run_history_deletion import (
    FLOWS_HISTORY_BLOCKED_KEYS,
    FLOWS_HISTORY_COUNT_KEYS,
    RUN_ADMISSION_ROWS,
    RUN_RESUME_ROWS,
    SCHEDULED_MODES,
    FlowRunHistoryDeletion,
    FlowsHistoryCount,
    RunHistorySelection,
)
from eneo.flows.domain.flow_run_retention_policy import FLOWS_HISTORY_TASK
from eneo.flows.infrastructure.flow_run_history_due_repo import (
    FLOW_RUN_HISTORY_OVERDUE_CAP,
    FlowRunHistoryDueRepository,
)
from eneo.main.config import get_settings


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FlowRunHistoryRetentionTask:
    count_keys = FLOWS_HISTORY_COUNT_KEYS
    blocked_keys = FLOWS_HISTORY_BLOCKED_KEYS

    def __init__(
        self,
        session: AsyncSession,
        *,
        now: Callable[[], datetime] = _utcnow,
        family_rows: int | None = None,
    ) -> None:
        self._now = now
        self._session = session
        self._deletion = FlowRunHistoryDeletion(session, family_rows=family_rows)

    @property
    def name(self) -> str:
        return FLOWS_HISTORY_TASK

    def steps(self) -> Sequence[RetentionStep]:
        # Batches as large as one file family, which is settled in one chunk.
        family = max(self._deletion.family_rows, RUN_ADMISSION_ROWS, RUN_RESUME_ROWS)
        return (
            RetentionStep("receipts", self._locked(self._receipts), max_batch=family),
            RetentionStep("runs", self._locked(self._runs), max_batch=family),
            RetentionStep("finish", self._locked(self._receipts), max_batch=family),
        )

    def _locked(
        self, run: Callable[[RetentionBatch], Awaitable[RetentionStepResult]]
    ) -> Callable[[RetentionBatch], Awaitable[RetentionStepResult]]:
        async def locked(batch: RetentionBatch) -> RetentionStepResult:
            await self._deletion.lock()
            return await run(batch)

        return locked

    async def overdue(self) -> RetentionOverdue:
        overdue = await FlowRunHistoryDueRepository(self._session).overdue(
            now=self._now(),
            window=timedelta(days=get_settings().gallring_overdue_window_days),
            cap=FLOW_RUN_HISTORY_OVERDUE_CAP,
        )
        return RetentionOverdue(
            count=overdue.count,
            complete=overdue.complete,
            oldest_due_at=overdue.oldest_due_at,
        )

    async def _receipts(self, batch: RetentionBatch) -> RetentionStepResult:
        out = RetentionEffects()

        async def next_candidate(
            after: RetentionKeyset | None,
        ) -> RetentionUnitCandidate | None:
            receipts = await self._deletion.receipts.unfinished(
                task=FLOWS_HISTORY_TASK,
                after=(after.at, after.id) if after is not None else None,
                limit=1,
            )
            if not receipts:
                return None
            receipt = receipts[0]

            async def handle(rows: int, files: int) -> RetentionUnitUsage:
                out.add(None, FlowsHistoryCount.RECEIPTS_EXAMINED.value)
                progress = await self._deletion.advance(
                    receipt, rows=rows, files=files, out=out
                )
                return progress.usage

            return RetentionKeyset(at=receipt.started_at, id=receipt.id), handle

        settings = get_settings()
        return await gather_retention_units(
            next_candidate,
            out,
            max_rows=batch.rows,
            max_files=batch.files,
            cursor=batch.cursor,
            chunk_rows=settings.gallring_chunk_rows,
            gather_seconds=settings.gallring_family_gather_seconds,
        )

    async def _runs(self, batch: RetentionBatch) -> RetentionStepResult:
        out = RetentionEffects()
        settings = get_settings()
        selection = RunHistorySelection()
        return await gather_retention_units(
            self._deletion.due_candidates(
                now=self._now(),
                modes=SCHEDULED_MODES,
                trigger=RetentionTrigger.SCHEDULED,
                triggered_by_user_id=None,
                out=out,
                selection=selection,
            ),
            out,
            max_rows=batch.rows,
            max_files=batch.files,
            cursor=batch.cursor,
            chunk_rows=settings.gallring_chunk_rows,
            gather_seconds=settings.gallring_family_gather_seconds,
            min_candidate_rows=2,
        )
