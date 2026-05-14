from datetime import datetime, timezone
from uuid import uuid4

import pytest

from intric.main.models import Status
from intric.websites.domain.crawl_lifecycle import (
    CrawlLifecycle,
    derive_crawl_lifecycle,
    derive_crawl_lifecycle_from_counters,
)
from intric.websites.domain.crawl_run import CrawlRun


def _crawl_run(
    *,
    status: Status,
    finished_at: datetime | None = None,
    pages_crawled: int | None = None,
    files_downloaded: int | None = None,
    pages_failed: int | None = None,
    files_failed: int | None = None,
    pages_source_retained: int | None = None,
    pages_hash_retained: int | None = None,
    files_hash_retained: int | None = None,
    files_too_large_skipped: int | None = None,
) -> CrawlRun:
    return CrawlRun(
        id=uuid4(),
        created_at=None,
        updated_at=None,
        website_id=uuid4(),
        tenant_id=uuid4(),
        pages_crawled=pages_crawled,
        files_downloaded=files_downloaded,
        pages_failed=pages_failed,
        files_failed=files_failed,
        pages_source_retained=pages_source_retained,
        pages_hash_retained=pages_hash_retained,
        files_hash_retained=files_hash_retained,
        files_too_large_skipped=files_too_large_skipped,
        status=status,
        result_location=None,
        finished_at=finished_at,
        job_id=uuid4(),
        failure_summary=None,
        outcome_code=None,
    )


def test_queued_crawl_run_is_queued():
    assert (
        derive_crawl_lifecycle(_crawl_run(status=Status.QUEUED))
        == CrawlLifecycle.QUEUED
    )


def test_in_progress_crawl_run_without_counters_is_running_no_progress():
    assert (
        derive_crawl_lifecycle(_crawl_run(status=Status.IN_PROGRESS))
        == CrawlLifecycle.RUNNING_NO_PROGRESS
    )


def test_in_progress_crawl_run_with_zero_counters_is_running_no_progress():
    assert (
        derive_crawl_lifecycle(
            _crawl_run(
                status=Status.IN_PROGRESS,
                pages_crawled=0,
                files_downloaded=0,
                pages_failed=0,
                files_failed=0,
                pages_source_retained=0,
                pages_hash_retained=0,
                files_hash_retained=0,
                files_too_large_skipped=0,
            )
        )
        == CrawlLifecycle.RUNNING_NO_PROGRESS
    )


def test_counter_derivation_without_entity_matches_no_progress_behavior():
    assert (
        derive_crawl_lifecycle_from_counters(
            status=Status.IN_PROGRESS,
            finished_at=None,
            pages_crawled=0,
            files_downloaded=None,
            pages_failed=0,
            files_failed=None,
            pages_source_retained=0,
            pages_hash_retained=None,
            files_hash_retained=0,
            files_too_large_skipped=None,
        )
        == CrawlLifecycle.RUNNING_NO_PROGRESS
    )


@pytest.mark.parametrize(
    "counter_name",
    [
        "pages_crawled",
        "files_downloaded",
        "pages_failed",
        "files_failed",
        "pages_source_retained",
        "pages_hash_retained",
        "files_hash_retained",
        "files_too_large_skipped",
    ],
)
def test_in_progress_crawl_run_with_any_progress_counter_is_running_with_progress(
    counter_name: str,
):
    crawl_run = _crawl_run(status=Status.IN_PROGRESS, **{counter_name: 1})

    assert derive_crawl_lifecycle(crawl_run) == CrawlLifecycle.RUNNING_WITH_PROGRESS


def test_counter_derivation_without_entity_matches_progress_behavior():
    assert (
        derive_crawl_lifecycle_from_counters(
            status=Status.IN_PROGRESS,
            finished_at=None,
            pages_crawled=None,
            files_downloaded=1,
            pages_failed=None,
            files_failed=None,
            pages_source_retained=None,
            pages_hash_retained=None,
            files_hash_retained=None,
            files_too_large_skipped=None,
        )
        == CrawlLifecycle.RUNNING_WITH_PROGRESS
    )


def test_queued_status_wins_over_recorded_progress():
    crawl_run = _crawl_run(status=Status.QUEUED, pages_crawled=1)

    assert derive_crawl_lifecycle(crawl_run) == CrawlLifecycle.QUEUED


@pytest.mark.parametrize(
    "status",
    [Status.COMPLETE, Status.FAILED, Status.NOT_FOUND],
)
def test_terminal_status_is_terminal(status: Status):
    assert derive_crawl_lifecycle(_crawl_run(status=status)) == CrawlLifecycle.TERMINAL


def test_finished_at_marks_in_progress_row_terminal():
    crawl_run = _crawl_run(
        status=Status.IN_PROGRESS,
        finished_at=datetime.now(timezone.utc),
    )

    assert derive_crawl_lifecycle(crawl_run) == CrawlLifecycle.TERMINAL


def test_counter_derivation_finished_at_marks_row_terminal():
    assert (
        derive_crawl_lifecycle_from_counters(
            status=Status.IN_PROGRESS,
            finished_at=datetime.now(timezone.utc),
            pages_crawled=0,
            files_downloaded=0,
            pages_failed=0,
            files_failed=0,
            pages_source_retained=0,
            pages_hash_retained=0,
            files_hash_retained=0,
            files_too_large_skipped=0,
        )
        == CrawlLifecycle.TERMINAL
    )
