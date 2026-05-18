"""Duplicate-crawl guard ownership.

A worker may pick up a duplicate crawl job for a website when two
schedules overlap or when an admin manually triggers a crawl while a
previous one is still queued. Without a guard, the second worker would
race the first and waste work; with a naive guard, two workers might
also fail and "resurrect" each other through the watchdog.

The canonical behavior — owned here — is:

  1. Look up the oldest active crawl job for the website. Active means
     QUEUED or IN_PROGRESS.
  2. If the lookup returns another job ID, the current worker is the
     duplicate. Commit a typed `TerminalEvent(CRAWL_DUPLICATE_SKIPPED)`
     in its own session so the duplicate's CrawlRun and Jobs row land
     on the canonical terminal path (no ad-hoc UPDATE statements, no
     resurrection risk), then return a `DuplicateSkipDecision` carrying
     the primary job's ID so the caller can log and return without
     re-querying the DB.
  3. If the lookup returns this job's own ID, return None and let the
     caller proceed.
  4. If the lookup returns None, return None and let the caller proceed.

Why this lives in `worker/crawl/` and not in `crawl_tasks.py`: the
inline implementation was tangled with the broader `crawl_task(...)`
orchestration. The split also makes the duplicate-skip terminal commit
testable without spinning up the whole crawl_task stack.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.main.logging import get_logger
from intric.main.models import Status
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawl_terminal import (
    TerminalEvent,
    commit_terminal,
)
from intric.websites.domain.crawl_terminal_source import CrawlTerminalSource

logger = get_logger(__name__)


SessionScope = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True)
class DuplicateSkipDecision:
    """Outcome of the duplicate-guard check when a skip was committed.

    `primary_job_id` is the canonical worker the caller should report
    in logs/metrics. Returning a typed result rather than a plain UUID
    keeps the duplicate-skip log line and metric emitter at the caller
    without leaking the guard's internal SQL identifier into the
    `crawl_task` return shape.
    """

    primary_job_id: UUID


async def find_primary_active_job_id(
    session: AsyncSession,
    *,
    website_id: UUID,
) -> UUID | None:
    """Return the oldest active (QUEUED or IN_PROGRESS) crawl job ID for
    a website, or None if no active crawl exists.

    "Active" excludes terminal statuses on purpose: a watchdog or admin
    abort may have flipped this job to FAILED between queueing and the
    duplicate-guard read, in which case the next-newest job should
    proceed as the canonical worker.
    """
    # Late import keeps SQLAlchemy table modules out of the worker
    # import graph during module load — important because the
    # duplicate-guard is imported from `crawl_tasks.py`, which itself
    # is imported during worker bootstrap before all ORM modules are
    # registered.
    from intric.database.tables.job_table import Jobs
    from intric.database.tables.websites_table import CrawlRuns as CrawlRunsTable
    from intric.jobs.job_models import Task

    active_statuses = [Status.QUEUED.value, Status.IN_PROGRESS.value]
    stmt = (
        sa.select(Jobs.id)
        .join(CrawlRunsTable, CrawlRunsTable.job_id == Jobs.id)
        .where(CrawlRunsTable.website_id == website_id)
        .where(Jobs.task == Task.CRAWL.value)
        .where(Jobs.status.in_(active_statuses))
        .order_by(Jobs.created_at.asc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def try_duplicate_skip(
    *,
    session_scope: SessionScope,
    job_id: UUID,
    run_id: UUID,
    website_id: UUID,
) -> DuplicateSkipDecision | None:
    """Commit a typed duplicate-skip terminal event if the current job
    is not the canonical worker for its website.

    Returns:
        DuplicateSkipDecision when this job is a duplicate (the
        TerminalEvent was committed in its own session). The caller is
        responsible for logging + returning the duplicate-skip status.
        None when this job is the canonical worker (or no active job
        exists yet).

    Implementation note: opening the session inside this function — via
    the caller-supplied `session_scope` — keeps the duplicate-skip
    transaction isolated from the larger crawl_task transaction graph,
    so a later phase rollback cannot un-commit a duplicate skip that
    has already been observed by audit/metrics.
    """
    async with session_scope() as session:
        primary_job_id = await find_primary_active_job_id(
            session,
            website_id=website_id,
        )

        if primary_job_id is None or primary_job_id == job_id:
            return None

        skip_message = f"Skipped duplicate crawl; active job {primary_job_id}"
        result = await commit_terminal(
            session,
            TerminalEvent(
                crawl_run_id=run_id,
                job_id=job_id,
                job_status=Status.FAILED,
                outcome_code=CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED,
                terminal_source=CrawlTerminalSource.CRAWLER,
                finished_at=datetime.now(timezone.utc),
                result_location=skip_message,
            ),
        )
        if result.job_rows_updated == 0:
            # A concurrent watchdog/abort may have already terminalized
            # the row. The duplicate-skip is still the right user-facing
            # outcome (the work was a duplicate) and the caller still
            # needs to skip the crawl — log at debug so the operational
            # signal stays in metrics rather than alert volume.
            logger.debug(
                "Duplicate crawl skip ignored; job status already changed",
                extra={
                    "job_id": str(job_id),
                    "website_id": str(website_id),
                },
            )

    return DuplicateSkipDecision(primary_job_id=primary_job_id)
