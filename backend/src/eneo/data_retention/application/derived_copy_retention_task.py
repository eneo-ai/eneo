"""Copies of a removed conversation follow the removal.

A copy whose source question was removed is unreadable from the moment that
removal commits, whether this task runs or not. This task then removes it:
the `copies` step deletes every question of each invalid copy session through
the shared conversation unit, which releases the session with its last
question; the `edges` step deletes the edges of copy sessions that are gone
and releases an invalid copy session left without questions. It follows a
removal already made, so it runs without an organisation choice.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from uuid import UUID

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
from eneo.data_retention.application.retention_units import RetentionEffects
from eneo.data_retention.infrastructure.derived_copy_repo import (
    DerivedCopyRepository,
    edge_position,
)
from eneo.data_retention.infrastructure.empty_session_repo import (
    EmptySessionRepository,
)
from eneo.files.file_retention import FileRetentionReason

DERIVED_COPIES_TASK = "conversations.derived_copies"

# An invalid copy session without questions is released only once it is this
# old: a feature that created the copy may still be writing it. It is
# unreadable meanwhile; its questions are removed without waiting.
COPY_IN_FLIGHT_MARGIN = timedelta(days=1)


class DerivedCopyRetentionTask:
    name = DERIVED_COPIES_TASK
    count_keys = frozenset(
        {
            ConversationRootKind.QUESTION.deleted_key,
            "sessions_deleted",
            "files_deleted",
            "edges_deleted",
        }
    )
    # Examined edges and the Files a deleted copy's release kept: progress,
    # not disposal, as for conversation history.
    observation_keys = frozenset(
        {
            "edges_examined",
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
        gather_seconds: float,
    ) -> None:
        now = now.astimezone(timezone.utc)
        self.allocation = allocation
        self.gather_seconds = gather_seconds
        self.copies = DerivedCopyRepository(session, now=now)
        self.empty_copies = EmptySessionRepository(
            session, now=now, grace=COPY_IN_FLIGHT_MARGIN
        )
        self.question_cost = ConversationRootCostEstimate()

    def steps(self) -> Sequence[RetentionStep]:
        return (
            RetentionStep(
                "copies",
                self._copies,
                max_batch=self.allocation.max_batch,
                max_files=self.allocation.unit_files,
            ),
            RetentionStep("edges", self._edges, max_files=0),
        )

    async def _copies(self, batch: RetentionBatch) -> RetentionStepResult:
        return await run_conversation_page(
            self.copies,
            batch,
            self.allocation,
            self.question_cost,
            gather_seconds=self.gather_seconds,
        )

    async def _edges(self, batch: RetentionBatch) -> RetentionStepResult:
        """One window of edges whose discovery, deletion and releases fit the
        batch rows; bounded by its rows, like the empty-session sweep."""
        out = RetentionEffects()
        # Each edge charges its discovery row and at most one edge deletion or
        # one session release.
        limit = batch.rows // (1 + EmptySessionRepository.MAX_RELEASE_ROWS)
        if limit == 0:
            return out.result(
                rows=0, exhausted=False, deferred=True, cursor=batch.cursor
            )
        edges = await self.copies.edge_window(batch.cursor, limit)
        if not edges:
            return out.result(rows=0, exhausted=True, cursor=batch.cursor)
        removed_sessions = [edge.id for edge in edges if edge.session_removed]
        edges_deleted = (
            await self.copies.delete_edges_of_removed_sessions(removed_sessions)
            if removed_sessions
            else 0
        )
        invalid = sorted(
            {
                edge.copy_session_id
                for edge in edges
                if edge.source_removed and not edge.session_removed
            }
        )
        costs: Mapping[UUID, int] = (
            await self.empty_copies.lock_empty(invalid) if invalid else {}
        )
        released = await self.empty_copies.delete_due(tuple(costs)) if costs else ()
        out.blocked[ConversationBlockReason.NO_LONGER_DUE.key] += len(costs) - len(
            released
        )
        out.add(None, "edges_examined", len(edges))
        out.add(None, "edges_deleted", edges_deleted)
        out.add(None, "sessions_deleted", len(released))
        last = edges[-1]
        return out.result(
            rows=len(edges)
            + edges_deleted
            + len(costs)
            + sum(costs[copy] for copy in released),
            exhausted=len(edges) < limit,
            cursor=edge_position(last.copy_session_id, last.source_question_id),
        )
