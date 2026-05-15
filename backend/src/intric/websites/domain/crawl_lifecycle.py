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
