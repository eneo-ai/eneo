from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement

from intric.main.models import Status
from intric.websites.domain.crawl_run import CrawlRun


class CrawlLifecycle(str, Enum):
    QUEUED = "queued"
    RUNNING_NO_PROGRESS = "running_no_progress"
    RUNNING_WITH_PROGRESS = "running_with_progress"
    TERMINAL = "terminal"


_TERMINAL_STATUSES: frozenset[Status] = frozenset(
    {
        Status.COMPLETE,
        Status.FAILED,
        Status.NOT_FOUND,
    }
)


def derive_crawl_lifecycle(crawl_run: CrawlRun) -> CrawlLifecycle:
    return derive_crawl_lifecycle_from_counters(
        status=crawl_run.status,
        finished_at=crawl_run.finished_at,
        pages_crawled=crawl_run.pages_crawled,
        files_downloaded=crawl_run.files_downloaded,
        pages_failed=crawl_run.pages_failed,
        files_failed=crawl_run.files_failed,
        pages_source_retained=crawl_run.pages_source_retained,
        pages_hash_retained=crawl_run.pages_hash_retained,
        files_hash_retained=crawl_run.files_hash_retained,
        files_too_large_skipped=crawl_run.files_too_large_skipped,
    )


def derive_crawl_lifecycle_from_counters(
    *,
    status: Status,
    finished_at: datetime | None,
    pages_crawled: int | None,
    files_downloaded: int | None,
    pages_failed: int | None,
    files_failed: int | None,
    pages_source_retained: int | None,
    pages_hash_retained: int | None,
    files_hash_retained: int | None,
    files_too_large_skipped: int | None,
) -> CrawlLifecycle:
    if finished_at is not None or status in _TERMINAL_STATUSES:
        return CrawlLifecycle.TERMINAL

    if status == Status.QUEUED:
        return CrawlLifecycle.QUEUED

    if _has_recorded_progress(
        pages_crawled=pages_crawled,
        files_downloaded=files_downloaded,
        pages_failed=pages_failed,
        files_failed=files_failed,
        pages_source_retained=pages_source_retained,
        pages_hash_retained=pages_hash_retained,
        files_hash_retained=files_hash_retained,
        files_too_large_skipped=files_too_large_skipped,
    ):
        return CrawlLifecycle.RUNNING_WITH_PROGRESS

    return CrawlLifecycle.RUNNING_NO_PROGRESS


def _has_recorded_progress(
    *,
    pages_crawled: int | None,
    files_downloaded: int | None,
    pages_failed: int | None,
    files_failed: int | None,
    pages_source_retained: int | None,
    pages_hash_retained: int | None,
    files_hash_retained: int | None,
    files_too_large_skipped: int | None,
) -> bool:
    return any(
        count is not None and count > 0
        for count in (
            pages_crawled,
            files_downloaded,
            pages_failed,
            files_failed,
            pages_source_retained,
            pages_hash_retained,
            files_hash_retained,
            files_too_large_skipped,
        )
    )


def lifecycle_predicate_for_active_query(
    *,
    job_status_column: InstrumentedAttribute[str],
    pages_crawled_column: InstrumentedAttribute[int | None],
    files_downloaded_column: InstrumentedAttribute[int | None],
    pages_failed_column: InstrumentedAttribute[int | None],
    files_failed_column: InstrumentedAttribute[int | None],
    pages_source_retained_column: InstrumentedAttribute[int | None],
    pages_hash_retained_column: InstrumentedAttribute[int | None],
    files_hash_retained_column: InstrumentedAttribute[int | None],
    files_too_large_skipped_column: InstrumentedAttribute[int | None],
    lifecycle: CrawlLifecycle,
) -> ColumnElement[bool]:
    """SQL counterpart of `derive_crawl_lifecycle_from_counters` for the
    active-inventory query path. Returns a WHERE-clause expression that
    matches rows in the requested lifecycle bucket.

    Why this lives in the domain module: the active-inventory endpoint
    accepts a `lifecycle_status` filter that must agree exactly with the
    Python derivation applied to the SELECT result rows. Centralizing
    the predicate keeps the SQL filter and the Python classifier from
    drifting — a regression where the filter and the row-rendered
    lifecycle disagree would silently hide rows from operators.

    `TERMINAL` is accepted but never matches active-inventory rows
    (the endpoint's primary WHERE filter excludes `Jobs.status` outside
    QUEUED/IN_PROGRESS and `Jobs.finished_at` is null). Returning a
    false-literal lets the API render an empty result cleanly rather
    than rejecting a valid `CrawlLifecycle` enum value.
    """
    progress_counters: tuple[InstrumentedAttribute[int | None], ...] = (
        pages_crawled_column,
        files_downloaded_column,
        pages_failed_column,
        files_failed_column,
        pages_source_retained_column,
        pages_hash_retained_column,
        files_hash_retained_column,
        files_too_large_skipped_column,
    )
    has_any_progress = sa.or_(
        *(sa.func.coalesce(column, 0) > 0 for column in progress_counters)
    )
    if lifecycle is CrawlLifecycle.QUEUED:
        return job_status_column == Status.QUEUED.value
    if lifecycle is CrawlLifecycle.RUNNING_WITH_PROGRESS:
        return sa.and_(
            job_status_column == Status.IN_PROGRESS.value,
            has_any_progress,
        )
    if lifecycle is CrawlLifecycle.RUNNING_NO_PROGRESS:
        return sa.and_(
            job_status_column == Status.IN_PROGRESS.value,
            sa.not_(has_any_progress),
        )
    # CrawlLifecycle.TERMINAL: never matches active-inventory rows.
    return sa.false()


def has_no_page_progress(*, pages_crawled: int | None) -> bool:
    """Domain rule: a running crawl has not recorded page progress when the
    page counter is unset or zero.

    Why: Watchdog Phase 3.5 uses this predicate to detect early zombies —
    crawls that flipped to IN_PROGRESS but crashed before any page item was
    counted. Naming the predicate inside the domain module keeps the
    watchdog SQL from drifting from the operational definition and lets a
    second consumer (lifecycle observation, admin diagnostics) share one
    canonical source.

    Note: This is intentionally narrower than `RUNNING_NO_PROGRESS`. The
    lifecycle enum considers any non-page counter as progress; this fact
    isolates the page-level signal that the crawler reports first.
    """
    return pages_crawled is None or pages_crawled == 0


def no_page_progress_sql_predicate(
    pages_crawled_column: InstrumentedAttribute[int | None],
) -> ColumnElement[bool]:
    """SQL counterpart of `has_no_page_progress` for WHERE clauses.

    Use this from any SQL `SELECT` that needs to mirror the watchdog Phase
    3.5 early-zombie detection rule. Compiling identical SQL across the two
    is the whole point of relocating the predicate from inline `or_(...)`
    expressions into one named owner.
    """
    return sa.or_(pages_crawled_column.is_(None), pages_crawled_column == 0)
