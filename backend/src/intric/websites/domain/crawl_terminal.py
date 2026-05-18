from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.job_table import Jobs
from intric.database.tables.websites_table import CrawlRuns
from intric.main.models import Status
from intric.websites.domain.crawl_outcome import (
    CrawlOutcomeCode,
    FailureReason,
    serialize_failure_summary_for_storage,
)
from intric.websites.domain.crawl_run import (
    CrawlFileTooLargeSample,
    serialize_crawl_file_too_large_samples,
)
from intric.websites.domain.crawl_terminal_source import CrawlTerminalSource

ACTIVE_TERMINAL_JOB_STATUSES: tuple[Status, ...] = (
    Status.QUEUED,
    Status.IN_PROGRESS,
)


@dataclass(frozen=True, slots=True)
class CrawlRunTerminalUpdate:
    pages_crawled: int
    files_downloaded: int
    pages_failed: int
    files_failed: int
    pages_source_retained: int
    pages_hash_retained: int
    files_hash_retained: int
    files_too_large_skipped: int
    failure_summary: dict[FailureReason, int] | None
    files_too_large_download_limit_bytes: int | None = None
    files_too_large_samples: tuple[CrawlFileTooLargeSample, ...] = ()


@dataclass(frozen=True, slots=True)
class TerminalEvent:
    crawl_run_id: UUID
    job_id: UUID
    job_status: Status
    outcome_code: CrawlOutcomeCode | None
    terminal_source: CrawlTerminalSource
    finished_at: datetime
    result_location: str | None = None
    allowed_current_job_statuses: Sequence[Status] = ACTIVE_TERMINAL_JOB_STATUSES
    crawl_run_update: CrawlRunTerminalUpdate | None = None
    only_set_crawl_outcome_if_missing: bool = False


@dataclass(frozen=True, slots=True)
class TerminalBatchEvent:
    crawl_run_ids: tuple[UUID, ...]
    job_ids: tuple[UUID, ...]
    job_status: Status
    outcome_code: CrawlOutcomeCode
    terminal_source: CrawlTerminalSource
    finished_at: datetime
    result_location: str | None = None
    allowed_current_job_statuses: Sequence[Status] = ACTIVE_TERMINAL_JOB_STATUSES
    only_set_crawl_outcome_if_missing: bool = False

    def __post_init__(self) -> None:
        if not self.job_ids:
            raise ValueError("Terminal batch requires at least one job")
        if len(self.job_ids) != len(self.crawl_run_ids):
            raise ValueError(
                "Terminal batch must contain the same number of jobs and crawl runs"
            )


@dataclass(frozen=True, slots=True)
class TerminalCommitResult:
    job_rows_updated: int
    crawl_run_rows_updated: int


def _bounded_enqueue_failure_message(prefix: str, exc: BaseException) -> str:
    """Bound text to the legacy job/result storage limit before terminal commit."""
    message = str(exc).strip()
    if not message:
        message = type(exc).__name__
    return f"{prefix}: {message}"[:512]


def crawl_pending_queue_enqueue_failure_message(exc: BaseException) -> str:
    return _bounded_enqueue_failure_message(
        "Failed to add crawl to pending queue",
        exc,
    )


def crawl_direct_enqueue_failure_message(exc: BaseException) -> str:
    return _bounded_enqueue_failure_message(
        "Failed to enqueue crawl directly",
        exc,
    )


async def commit_terminal(
    session: AsyncSession,
    event: TerminalEvent,
) -> TerminalCommitResult:
    """Commit only durable Job/CrawlRun terminal fields; post-terminal effects run elsewhere.

    Why the CrawlRun update is gated on the Job update succeeding: the Jobs
    UPDATE is the optimistic concurrency token. When it matches zero rows
    (the worker has already committed a terminal state from another path)
    the CrawlRun must not be overwritten with this caller's outcome. Without
    this gate, a race between the worker writing COMPLETE and an admin
    aborting could leave Jobs.status=COMPLETE while CrawlRuns.outcome_code
    flipped to CRAWL_ABORTED.
    """
    job_result = await session.execute(
        sa.update(Jobs)
        .where(Jobs.id == event.job_id)
        .where(
            Jobs.status.in_(
                [status.value for status in event.allowed_current_job_statuses]
            )
        )
        .values(
            status=event.job_status.value,
            finished_at=event.finished_at,
            updated_at=event.finished_at,
            result_location=event.result_location,
        )
    )
    if job_result.rowcount == 0:
        return TerminalCommitResult(
            job_rows_updated=0,
            crawl_run_rows_updated=0,
        )

    crawl_run_stmt = sa.update(CrawlRuns).where(CrawlRuns.id == event.crawl_run_id)
    if event.only_set_crawl_outcome_if_missing:
        crawl_run_stmt = crawl_run_stmt.where(CrawlRuns.outcome_code.is_(None))
    crawl_run_result = await session.execute(
        crawl_run_stmt.values(_crawl_run_values(event))
    )

    return TerminalCommitResult(
        job_rows_updated=job_result.rowcount,
        crawl_run_rows_updated=crawl_run_result.rowcount,
    )


async def commit_terminal_batch(
    session: AsyncSession,
    event: TerminalBatchEvent,
) -> TerminalCommitResult:
    """Batch terminal commit preserving the job-gated CrawlRun invariant.

    A batch UPDATE can move only a subset of the requested Jobs when another
    terminal path wins the race for some rows. The matching CrawlRuns must be
    derived from the Jobs this transaction actually updated, not from the full
    caller-provided batch.
    """
    crawl_run_id_by_job_id = dict(zip(event.job_ids, event.crawl_run_ids))
    job_result = await session.execute(
        sa.update(Jobs)
        .where(Jobs.id.in_(event.job_ids))
        .where(
            Jobs.status.in_(
                [status.value for status in event.allowed_current_job_statuses]
            )
        )
        .values(
            status=event.job_status.value,
            finished_at=event.finished_at,
            updated_at=event.finished_at,
            result_location=event.result_location,
        )
        .returning(Jobs.id)
        .execution_options(synchronize_session=False)
    )
    updated_job_ids = tuple(job_result.scalars().all())
    if not updated_job_ids:
        return TerminalCommitResult(
            job_rows_updated=0,
            crawl_run_rows_updated=0,
        )

    updated_crawl_run_ids = tuple(
        crawl_run_id_by_job_id[job_id] for job_id in updated_job_ids
    )

    crawl_run_stmt = sa.update(CrawlRuns).where(CrawlRuns.id.in_(updated_crawl_run_ids))
    if event.only_set_crawl_outcome_if_missing:
        crawl_run_stmt = crawl_run_stmt.where(CrawlRuns.outcome_code.is_(None))
    crawl_run_result = await session.execute(
        crawl_run_stmt.values(
            outcome_code=event.outcome_code.value,
            terminal_source=event.terminal_source.value,
        ).execution_options(synchronize_session=False)
    )

    return TerminalCommitResult(
        job_rows_updated=len(updated_job_ids),
        crawl_run_rows_updated=crawl_run_result.rowcount,
    )


def _crawl_run_values(event: TerminalEvent) -> dict[str, object]:
    outcome_code = event.outcome_code.value if event.outcome_code is not None else None
    values: dict[str, object] = {
        "outcome_code": outcome_code,
        "terminal_source": event.terminal_source.value,
    }
    update = event.crawl_run_update
    if update is None:
        return values

    values.update(
        pages_crawled=update.pages_crawled,
        files_downloaded=update.files_downloaded,
        pages_failed=update.pages_failed,
        files_failed=update.files_failed,
        pages_source_retained=update.pages_source_retained,
        pages_hash_retained=update.pages_hash_retained,
        files_hash_retained=update.files_hash_retained,
        files_too_large_skipped=update.files_too_large_skipped,
        files_too_large_download_limit_bytes=(
            update.files_too_large_download_limit_bytes
        ),
        files_too_large_samples=serialize_crawl_file_too_large_samples(
            update.files_too_large_samples
        ),
        failure_summary=serialize_failure_summary_for_storage(update.failure_summary),
    )
    return values
