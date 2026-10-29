"""Conversation stores adopt the shared retention runner and budgeted pages."""

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.conversation_retention import (
    CONVERSATION_FILE_BLOCKS,
    ConversationBlockReason,
    ConversationPageAllocation,
    ConversationRootCostEstimate,
    ConversationRootKind,
    run_conversation_page,
)
from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionStep,
    RetentionStepResult,
)
from eneo.data_retention.application.retention_step_order import rotate_retention_steps
from eneo.data_retention.domain.conversation_policy import ConversationPolicySource
from eneo.data_retention.domain.retention import (
    RetentionOverdue,
)
from eneo.data_retention.infrastructure.conversation_retention_repo import (
    ConversationRetentionRepository,
)
from eneo.files.file_retention import FileRetentionReason

CONVERSATION_HISTORY_TASK = "conversations.history"


class ConversationHistoryRetentionTask:
    count_keys = frozenset(
        {
            *(kind.deleted_key for kind in ConversationRootKind),
            "sessions_deleted",
            "files_deleted",
            *(f"by_{source.value}_rule" for source in ConversationPolicySource),
        }
    )
    # Examined owners and the Files a deleted conversation's release kept:
    # progress, not disposal. The conversation is gone, so none is blocked; a
    # File outcome that rolls back keeps the conversation and never gets here.
    # The release passes no age limit, so a File is never kept as not old enough.
    observation_keys = frozenset(
        {
            "owners_examined",
            *(
                reason.key
                for reason in FileRetentionReason
                if reason
                not in {FileRetentionReason.DELETED, FileRetentionReason.NOT_OLD_ENOUGH}
                and not reason.rolls_back
            ),
        }
    )
    blocked_keys = frozenset(
        {
            *(reason.key for reason in ConversationBlockReason),
            *(reason.key for reason in CONVERSATION_FILE_BLOCKS),
        }
    )

    def __init__(
        self,
        session: AsyncSession,
        *,
        allocation: ConversationPageAllocation,
        now: datetime,
        overdue_window: timedelta,
        overdue_rows: int,
        overdue_owner_rows: int,
        gather_seconds: float,
    ) -> None:
        self.now = now.astimezone(timezone.utc)
        self.allocation = allocation
        self.overdue_window = overdue_window
        self.overdue_rows = overdue_rows
        # The owner rows each stream's walk may read: in whole discovery pages.
        self.overdue_owner_pages = -(-overdue_owner_rows // allocation.page_size)
        self.gather_seconds = gather_seconds
        self.questions = ConversationRetentionRepository(
            session, kind=ConversationRootKind.QUESTION, now=self.now
        )
        self.app_runs = ConversationRetentionRepository(
            session, kind=ConversationRootKind.APP_RUN, now=self.now
        )
        self.question_cost = ConversationRootCostEstimate()
        self.app_run_cost = ConversationRootCostEstimate()

    @property
    def name(self) -> str:
        return CONVERSATION_HISTORY_TASK

    def steps(self) -> Sequence[RetentionStep]:
        # A standing backlog in one stream spends the budget before the next, so
        # each stream goes first on some date.
        return rotate_retention_steps(
            (
                RetentionStep(
                    "questions",
                    self._questions,
                    max_batch=self.allocation.max_batch,
                    max_files=self.allocation.unit_files,
                ),
                RetentionStep(
                    "app_runs",
                    self._app_runs,
                    max_batch=self.allocation.max_batch,
                    max_files=self.allocation.unit_files,
                ),
            ),
            execution_date=self.now.date(),
        )

    async def _questions(self, batch: RetentionBatch) -> RetentionStepResult:
        return await run_conversation_page(
            self.questions,
            batch,
            self.allocation,
            self.question_cost,
            gather_seconds=self.gather_seconds,
        )

    async def _app_runs(self, batch: RetentionBatch) -> RetentionStepResult:
        return await run_conversation_page(
            self.app_runs,
            batch,
            self.allocation,
            self.app_run_cost,
            gather_seconds=self.gather_seconds,
        )

    async def overdue(self) -> RetentionOverdue:
        remaining = self.overdue_rows
        snapshots: list[RetentionOverdue] = []
        for repository in (self.questions, self.app_runs):
            if remaining == 0:
                # Rows past the cap are not counted, so the next stream is not
                # read at all: the snapshot is incomplete whatever it holds.
                snapshots.append(
                    RetentionOverdue(count=0, complete=False, oldest_due_at=None)
                )
                break
            snapshot = await repository.overdue(
                window=self.overdue_window,
                limit=remaining,
                owner_page=self.allocation.page_size,
                max_pages=self.overdue_owner_pages,
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
