"""Conversation stores adopt the shared retention runner and budgeted pages."""

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.conversation_retention import (
    ConversationBlockReason,
    ConversationPageAllocation,
    run_conversation_page,
)
from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionStep,
    RetentionStepResult,
)
from eneo.data_retention.application.retention_step_order import rotate_retention_steps
from eneo.data_retention.application.retention_units import RetentionEffects
from eneo.data_retention.domain.retention import (
    ConversationPolicySource,
    RetentionOverdue,
)
from eneo.data_retention.infrastructure.conversation_retention_repo import (
    ConversationRetentionRepository,
    ConversationRootKind,
)
from eneo.data_retention.infrastructure.orphan_session_retention_repo import (
    OrphanSessionRetentionRepository,
)

CONVERSATION_HISTORY_TASK = "chats.history"


class ConversationHistoryRetentionTask:
    count_keys = frozenset(
        {
            "conversations_deleted",
            "orphan_sessions_deleted",
            "session_rows_examined",
            *(f"by_{source.value}_rule" for source in ConversationPolicySource),
        }
    )
    blocked_keys = frozenset(reason.value for reason in ConversationBlockReason)

    def __init__(
        self,
        session: AsyncSession,
        *,
        allocation: ConversationPageAllocation,
        now: datetime,
        overdue_window: timedelta,
        overdue_rows: int,
    ) -> None:
        self.now = now.astimezone(timezone.utc)
        self.allocation = allocation
        self.overdue_window = overdue_window
        self.overdue_rows = overdue_rows
        self.questions = ConversationRetentionRepository(
            session, kind=ConversationRootKind.QUESTION, now=self.now
        )
        self.app_runs = ConversationRetentionRepository(
            session, kind=ConversationRootKind.APP_RUN, now=self.now
        )
        self.sessions = OrphanSessionRetentionRepository(session, now=self.now)

    @property
    def name(self) -> str:
        return CONVERSATION_HISTORY_TASK

    def steps(self) -> Sequence[RetentionStep]:
        return (
            *rotate_retention_steps(
                (
                    RetentionStep(
                        "questions",
                        self._questions,
                        max_batch=self.allocation.max_batch,
                        max_files=0,
                    ),
                    RetentionStep(
                        "app_runs",
                        self._app_runs,
                        max_batch=self.allocation.max_batch,
                        max_files=0,
                    ),
                ),
                execution_date=self.now.date(),
            ),
            RetentionStep("orphan_sessions", self._orphan_sessions, max_files=0),
        )

    async def _questions(self, batch: RetentionBatch) -> RetentionStepResult:
        return await run_conversation_page(self.questions, batch, self.allocation)

    async def _app_runs(self, batch: RetentionBatch) -> RetentionStepResult:
        return await run_conversation_page(self.app_runs, batch, self.allocation)

    async def _orphan_sessions(self, batch: RetentionBatch) -> RetentionStepResult:
        out = RetentionEffects()
        # Discovery, proof, root and the UNIQUE helper row must fit together.
        limit = batch.rows // 4
        if limit == 0:
            return out.result(
                rows=0, exhausted=False, deferred=True, cursor=batch.cursor
            )
        window = await self.sessions.window(batch.cursor, limit)
        if not window:
            return out.result(rows=0, exhausted=True, cursor=batch.cursor)
        costs = await self.sessions.lock_orphans([root.id for root in window])
        admitted: list[UUID] = []
        for root in window:
            cost = costs.get(root.id)
            if cost is None:
                continue
            if cost > self.allocation.unit_rows:
                out.blocked[ConversationBlockReason.UNIT_EXCEEDS_BUDGET.value] += 1
            else:
                admitted.append(root.id)
        deleted = await self.sessions.delete_due(admitted) if admitted else ()
        out.blocked[ConversationBlockReason.NO_LONGER_DUE.value] += len(admitted) - len(
            deleted
        )
        out.add(None, "session_rows_examined", len(window))
        out.add(None, "orphan_sessions_deleted", len(deleted))
        return out.result(
            rows=len(window) + len(costs) + sum(costs[root] for root in deleted),
            exhausted=len(window) < limit,
            cursor=window[-1],
        )

    async def overdue(self) -> RetentionOverdue:
        remaining = self.overdue_rows
        snapshots: list[RetentionOverdue] = []
        for repository in (self.questions, self.app_runs):
            snapshot = await repository.overdue(
                window=self.overdue_window, limit=remaining
            )
            snapshots.append(snapshot)
            remaining -= snapshot.count
        deadlines = [
            snapshot.oldest_due_at
            for snapshot in snapshots
            if snapshot.oldest_due_at is not None
        ]
        return RetentionOverdue(
            count=sum(snapshot.count for snapshot in snapshots),
            complete=all(snapshot.complete for snapshot in snapshots),
            oldest_due_at=min(deadlines) if deadlines else None,
        )
