"""Explicit platform composition; the engine does not import its adopters."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from eneo.data_retention.application.conversation_history_retention_task import (
    CONVERSATION_HISTORY_TASK,
    ConversationHistoryRetentionTask,
)
from eneo.data_retention.application.conversation_retention import (
    ConversationBlockReason,
    ConversationPageAllocation,
    conversation_page_allocation,
)
from eneo.data_retention.application.derived_copy_retention_task import (
    DERIVED_COPIES_TASK,
    DerivedCopyRetentionTask,
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
from eneo.data_retention.domain.retention import (
    FREQUENT_OVERDUE_AFTER,
    RetentionBudget,
)
from eneo.files.unused_file_retention_task import (
    UNUSED_FILES_TASK,
    UnusedFileRetentionTask,
)
from eneo.main.config import Settings

logger = logging.getLogger(__name__)

# Removals that run without an organisation, space or assistant choice, each
# with the deployment setting that switches it off. They ran before the engine
# (sessions without a question, files without a reference) or keep the engine's
# own records (job history, after the audit retention). Every other task removes
# only what such a choice selects, or is off by default. Widget conversations
# are not the engine's: each widget's nightly job removes them.
EXISTING_WITHOUT_CHOICE: Mapping[str, str] = MappingProxyType(
    {
        EMPTY_SESSIONS_TASK: "retention_empty_sessions_enabled",
        UNUSED_FILES_TASK: "retention_unused_files_enabled",
        JOB_HISTORY_TASK: "retention_job_history_enabled",
    }
)

# Removals that follow one already made, each with the setting that switches it
# off: a copy of a removed conversation is unreadable from that removal on, and
# this removes what is left of it.
FOLLOWS_A_REMOVAL: Mapping[str, str] = MappingProxyType(
    {DERIVED_COPIES_TASK: "retention_derived_copies_enabled"}
)


def _unit_budget(settings: Settings) -> Mapping[str, tuple[str, ...]]:
    """A conversation's removal, its later logs included, must fit one unit.

    Each File charges at least three rows, so a file budget that funds fewer
    rows than the unit cap can keep a unit too, and raising the cap alone would
    not admit it.
    """
    limits = ("retention_conversations_max_unit_rows",)
    if (
        settings.retention_max_files_per_run * 3
        < settings.retention_conversations_max_unit_rows
    ):
        limits += ("retention_max_files_per_run",)
    return MappingProxyType({ConversationBlockReason.UNIT_EXCEEDS_BUDGET.key: limits})


# Records kept outside the engine, each with how it ends today, until the owner
# decides whether retention removes them. Retention reports none of them as
# removed, and a removed conversation does not shorten them.
OUTSIDE_THE_ENGINE: Mapping[str, str] = MappingProxyType(
    {
        "audit exports": "cleanup_old_exports deletes each export file and its "
        "job key once it is older than export_max_age_hours",
        "insights": "an insight job keeps its question and answer in Redis "
        "until one day after its last update",
        "browser sessions": "a row ends at sign-out, at the user's next sign-in "
        "after it expired, or with the user",
        "audit logs": "purge_old_audit_logs deletes them after each "
        "organisation's audit retention period",
        "service runs": "a service run keeps its question and answer until its "
        "service or organisation is deleted; no retention period applies yet",
    }
)


# One frequent pass ends within this many seconds plus the chunk in progress,
# before the next five-minute tick, also when the nightly run starts it.
FREQUENT_RUN_SECONDS = 240


def _paced(
    registrations: Iterable[RetentionTaskRegistration],
) -> tuple[RetentionTaskRegistration, ...]:
    return tuple(
        replace(
            registration,
            budget=replace(
                registration.budget,
                seconds=min(registration.budget.seconds, FREQUENT_RUN_SECONDS),
            ),
        )
        if registration.every == "frequent"
        else registration
        for registration in registrations
    )


def retention_task_registrations(
    settings: Settings, *, now: datetime | None = None
) -> tuple[RetentionTaskRegistration, ...]:
    observed_at = now if now is not None else datetime.now(timezone.utc)
    unit_budget = _unit_budget(settings)
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

    # Built with each task, so a misconfigured budget fails that execution,
    # not the health read that lists the registrations.
    def allocation() -> ConversationPageAllocation:
        return conversation_page_allocation(
            unit_rows=settings.retention_conversations_max_unit_rows,
            chunk_rows=settings.retention_chunk_rows,
            execution_rows=chat_budget.rows,
            execution_files=chat_budget.files,
            family_rows=settings.retention_max_family_rows,
        )

    registrations = (
        RetentionTaskRegistration(
            name=CONVERSATION_HISTORY_TASK,
            enabled=settings.retention_conversations_history_enabled,
            budget=chat_budget,
            limited_by=unit_budget,
            build=lambda session: ConversationHistoryRetentionTask(
                session,
                allocation=allocation(),
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
            name=DERIVED_COPIES_TASK,
            enabled=settings.retention_derived_copies_enabled,
            budget=chat_budget,
            limited_by=unit_budget,
            build=lambda session: DerivedCopyRetentionTask(
                session,
                allocation=allocation(),
                now=observed_at,
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
                # Without a given time these two keep the database's clock.
                now=now,
            ),
        ),
        RetentionTaskRegistration(
            name=JOB_HISTORY_TASK,
            enabled=settings.retention_job_history_enabled,
            budget=budget,
            build=lambda session: JobHistoryRetentionTask(session, now=now),
        ),
    )
    return _paced(registrations)


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
                # The database's clock, which also wrote every job row's times.
                now = (await session.execute(sa.select(sa.func.now()))).scalar_one()
                return await load_retention_health(
                    RetentionJobRunRepository(session),
                    # Built an hour back: a frequent task's due probe then
                    # finds only what is more than an hour past its time.
                    retention_task_registrations(
                        settings, now=now - FREQUENT_OVERDUE_AFTER
                    ),
                    now=now,
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
