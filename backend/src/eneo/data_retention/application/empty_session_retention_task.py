"""Sessions without a question are removed after a grace period.

Conversation history deletes the session its last question leaves empty in the
same unit; this sweep removes the rest: sessions that never received a question,
were emptied by other paths, or were held by a live chat when their last
question went. Its own task, not a step of conversation history: every session
older than the grace period is scanned, a standing population rather than a due
backlog, and sharing a budget with due history would let that scan spend it
first. Widget sessions are left to widget retention and each widget's period,
and a Flow authoring chat's session to conversation history, which removes it
with its last question: the window reads them, charges them and passes them.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionStep,
    RetentionStepResult,
)
from eneo.data_retention.application.retention_units import RetentionEffects
from eneo.data_retention.infrastructure.empty_session_repo import (
    EmptySessionRepository,
)

EMPTY_SESSIONS_TASK = "sessions.empty"


class EmptySessionBlockReason(StrEnum):
    NO_LONGER_DUE = "no_longer_due"
    # Another transaction held the empty, due session: it stays for a later run.
    ROOT_LOCKED = "root_locked"


class EmptySessionRetentionTask:
    name = EMPTY_SESSIONS_TASK
    count_keys = frozenset({"sessions_deleted"})
    # Examined rows are progress, not disposal.
    observation_keys = frozenset({"sessions_examined"})
    blocked_keys = frozenset(reason.value for reason in EmptySessionBlockReason)

    def __init__(
        self, session: AsyncSession, *, now: datetime, grace: timedelta
    ) -> None:
        self.sessions = EmptySessionRepository(
            session, now=now.astimezone(timezone.utc), grace=grace
        )

    def steps(self) -> Sequence[RetentionStep]:
        return (RetentionStep("sessions", self._sessions, max_files=0),)

    async def _sessions(self, batch: RetentionBatch) -> RetentionStepResult:
        """One window of sessions whose discovery and release fit the batch rows.

        The step does not read the execution deadline: one call is bounded by
        its rows, and the runner checks the deadline before every call.
        """
        out = RetentionEffects()
        # Each windowed session charges its discovery row and at most one
        # release; a passed session only its discovery row.
        limit = batch.rows // (1 + EmptySessionRepository.MAX_RELEASE_ROWS)
        if limit == 0:
            return out.result(
                rows=0, exhausted=False, deferred=True, cursor=batch.cursor
            )
        window = await self.sessions.window(batch.cursor, limit)
        if not window:
            return out.result(rows=0, exhausted=True, cursor=batch.cursor)
        candidates = [root.id for root, passed in window if not passed]
        costs: Mapping[UUID, int] = (
            await self.sessions.lock_empty(candidates) if candidates else {}
        )
        admitted = [identifier for identifier in candidates if identifier in costs]
        skipped = [identifier for identifier in candidates if identifier not in costs]
        if skipped:
            out.blocked[
                EmptySessionBlockReason.ROOT_LOCKED.value
            ] += await self.sessions.count_empty(skipped)
        deleted = await self.sessions.delete_due(admitted) if admitted else ()
        out.blocked[EmptySessionBlockReason.NO_LONGER_DUE.value] += len(admitted) - len(
            deleted
        )
        out.add(None, "sessions_examined", len(window))
        out.add(None, "sessions_deleted", len(deleted))
        # A skipped session costs its discovery row and one counted row, within
        # the release it would otherwise have had.
        return out.result(
            rows=len(window)
            + len(costs)
            + len(skipped)
            + sum(costs[root] for root in deleted),
            exhausted=len(window) < limit,
            cursor=window[-1][0],
        )
