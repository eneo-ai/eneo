"""Explicit platform composition; the engine does not import its adopters."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import SQLAlchemyError

from eneo.data_retention.application.conversation_history_retention_task import (
    CONVERSATION_HISTORY_TASK,
    ConversationHistoryRetentionTask,
)
from eneo.data_retention.application.conversation_retention import (
    conversation_page_allocation,
)
from eneo.data_retention.application.empty_session_retention_task import (
    EMPTY_SESSIONS_TASK,
    EmptySessionRetentionTask,
)
from eneo.data_retention.application.job_history_retention_task import (
    JOB_HISTORY_TASK,
    JobHistoryRetentionTask,
)
from eneo.data_retention.application.retention_health import RetentionHealth
from eneo.data_retention.application.retention_registration import (
    RetentionTaskRegistration,
)
from eneo.data_retention.domain.retention import RetentionBudget
from eneo.files.unused_file_retention_task import (
    UNUSED_FILES_TASK,
    UnusedFileRetentionTask,
)
from eneo.main.config import Settings

logger = logging.getLogger(__name__)


def retention_task_registrations(
    settings: Settings, *, now: datetime | None = None
) -> tuple[RetentionTaskRegistration, ...]:
    observed_at = now if now is not None else datetime.now(timezone.utc)
    budget = RetentionBudget(
        rows=settings.retention_max_rows_per_run,
        files=settings.retention_max_files_per_run,
        seconds=settings.retention_max_seconds_per_run,
    )
    chat_budget = RetentionBudget(
        rows=settings.retention_conversations_max_rows_per_run,
        files=budget.files,
        seconds=budget.seconds,
    )
    return (
        RetentionTaskRegistration(
            name=CONVERSATION_HISTORY_TASK,
            enabled=settings.retention_conversations_history_enabled,
            budget=chat_budget,
            build=lambda session: ConversationHistoryRetentionTask(
                session,
                allocation=conversation_page_allocation(
                    unit_rows=settings.retention_conversations_max_unit_rows,
                    chunk_rows=settings.retention_chunk_rows,
                    execution_rows=chat_budget.rows,
                    execution_files=chat_budget.files,
                    family_rows=settings.retention_max_family_rows,
                ),
                now=observed_at,
                overdue_window=timedelta(days=settings.retention_overdue_window_days),
                overdue_rows=settings.retention_overdue_max_rows,
                # The walk reads at most one execution's row budget of owners
                # per stream: bounded like the deletion it reports on, with no
                # setting of its own.
                overdue_owner_rows=chat_budget.rows,
                gather_seconds=settings.retention_chunk_gather_seconds,
            ),
        ),
        RetentionTaskRegistration(
            name=EMPTY_SESSIONS_TASK,
            enabled=settings.retention_empty_sessions_enabled,
            budget=budget,
            build=lambda session: EmptySessionRetentionTask(
                session,
                now=observed_at,
                grace=timedelta(hours=settings.retention_empty_session_grace_hours),
            ),
        ),
        RetentionTaskRegistration(
            name=UNUSED_FILES_TASK,
            enabled=settings.retention_unused_files_enabled,
            budget=budget,
            build=lambda session: UnusedFileRetentionTask(
                session,
                grace=timedelta(hours=settings.retention_unused_file_grace_hours),
                family_rows=settings.retention_max_family_rows,
                execution_files=budget.files,
                chunk_rows=settings.retention_chunk_rows,
                gather_seconds=settings.retention_chunk_gather_seconds,
            ),
        ),
        RetentionTaskRegistration(
            name=JOB_HISTORY_TASK,
            enabled=settings.retention_job_history_enabled,
            budget=budget,
            build=lambda session: JobHistoryRetentionTask(session),
        ),
    )


async def _read_retention_health(settings: Settings) -> RetentionHealth:
    from eneo.data_retention.application.retention_health import (
        RetentionHealthStatus,
        load_retention_health,
    )
    from eneo.data_retention.application.retention_sql_limits import (
        set_retention_timeouts,
    )
    from eneo.data_retention.infrastructure.retention_job_run_repo import (
        RetentionJobRunRepository,
    )
    from eneo.database.database import sessionmanager

    try:
        async with asyncio.timeout(settings.retention_health_timeout_seconds):
            async with sessionmanager.session() as session, session.begin():
                timeout_ms = max(
                    1, int(settings.retention_health_timeout_seconds * 1000)
                )
                await set_retention_timeouts(
                    session, statement_timeout_ms=timeout_ms, lock_timeout_ms=timeout_ms
                )
                return await load_retention_health(
                    RetentionJobRunRepository(session),
                    retention_task_registrations(settings),
                    now=datetime.now(timezone.utc),
                    lease_stale_after=timedelta(
                        seconds=settings.retention_lease_stale_seconds
                    ),
                )
    # A refused connection is an OSError, not a SQLAlchemy error.
    except (TimeoutError, SQLAlchemyError, OSError):
        logger.exception("Retention health could not read the execution history.")
        return RetentionHealth(status=RetentionHealthStatus.UNKNOWN)


class RetentionHealthCache:
    """One health read per window, shared by every concurrent caller.

    /api/healthz is public, so probes must not turn into one job-history read
    each. Waiters check the cache again after acquiring the lock instead of
    repeating the read that just finished.
    """

    def __init__(
        self,
        read: Callable[[Settings], Awaitable[RetentionHealth]],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._read = read
        self._clock = clock
        self._lock = asyncio.Lock()
        self._cached: tuple[RetentionHealth, float] | None = None

    def _fresh(self) -> RetentionHealth | None:
        if self._cached is None or self._clock() >= self._cached[1]:
            return None
        return self._cached[0]

    async def __call__(self, settings: Settings) -> RetentionHealth:
        cached = self._fresh()
        if cached is not None:
            return cached
        async with self._lock:
            cached = self._fresh()
            if cached is not None:
                return cached
            health = await self._read(settings)
            self._cached = (
                health,
                self._clock() + settings.retention_health_cache_seconds,
            )
            return health


retention_health = RetentionHealthCache(_read_retention_health)
