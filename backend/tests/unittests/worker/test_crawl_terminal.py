from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.main.models import Status
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode, FailureReason
from intric.worker.crawl.terminal import (
    CrawlRunTerminalUpdate,
    TerminalBatchEvent,
    TerminalEvent,
    commit_terminal,
    commit_terminal_batch,
)


class _ExecuteResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


@pytest.mark.asyncio
async def test_commit_terminal_updates_job_and_crawl_run_once():
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _ExecuteResult(rowcount=1),
            _ExecuteResult(rowcount=1),
        ]
    )
    finished_at = datetime.now(timezone.utc)
    event = TerminalEvent(
        crawl_run_id=uuid4(),
        job_id=uuid4(),
        job_status=Status.FAILED,
        outcome_code=CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED,
        finished_at=finished_at,
        result_location="Skipped duplicate crawl; active job 00000000-0000-0000-0000-000000000000",
    )

    result = await commit_terminal(session, event)

    assert result.job_rows_updated == 1
    assert result.crawl_run_rows_updated == 1
    assert session.execute.call_count == 2


@pytest.mark.asyncio
async def test_commit_terminal_can_update_zero_output_crawl_run_counts():
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _ExecuteResult(rowcount=1),
            _ExecuteResult(rowcount=1),
        ]
    )
    event = TerminalEvent(
        crawl_run_id=uuid4(),
        job_id=uuid4(),
        job_status=Status.FAILED,
        outcome_code=CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
        finished_at=datetime.now(timezone.utc),
        result_location="Crawl produced no pages",
        crawl_run_update=CrawlRunTerminalUpdate(
            pages_crawled=0,
            files_downloaded=0,
            pages_failed=0,
            files_failed=0,
            pages_source_retained=0,
            pages_hash_retained=0,
            files_hash_retained=0,
            files_too_large_skipped=2,
            failure_summary=None,
        ),
    )

    await commit_terminal(session, event)

    crawl_run_stmt = session.execute.call_args_list[1].args[0]
    crawl_run_params = crawl_run_stmt.compile().params
    assert (
        crawl_run_params["outcome_code"]
        == CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED.value
    )
    assert crawl_run_params["pages_crawled"] == 0
    assert crawl_run_params["files_downloaded"] == 0
    assert crawl_run_params["pages_failed"] == 0
    assert crawl_run_params["files_failed"] == 0
    assert crawl_run_params["pages_source_retained"] == 0
    assert crawl_run_params["pages_hash_retained"] == 0
    assert crawl_run_params["files_hash_retained"] == 0
    assert crawl_run_params["files_too_large_skipped"] == 2
    assert crawl_run_params["failure_summary"] is None


@pytest.mark.asyncio
async def test_commit_terminal_serializes_failure_summary_with_string_keys():
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _ExecuteResult(rowcount=1),
            _ExecuteResult(rowcount=1),
        ]
    )
    event = TerminalEvent(
        crawl_run_id=uuid4(),
        job_id=uuid4(),
        job_status=Status.COMPLETE,
        outcome_code=CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES,
        finished_at=datetime.now(timezone.utc),
        result_location="/api/v1/websites/00000000-0000-0000-0000-000000000000/info-blobs/",
        crawl_run_update=CrawlRunTerminalUpdate(
            pages_crawled=2,
            files_downloaded=0,
            pages_failed=2,
            files_failed=0,
            pages_source_retained=0,
            pages_hash_retained=0,
            files_hash_retained=0,
            files_too_large_skipped=0,
            failure_summary={FailureReason.DB_ERROR: 2},
        ),
    )

    await commit_terminal(session, event)

    crawl_run_stmt = session.execute.call_args_list[1].args[0]
    crawl_run_params = crawl_run_stmt.compile().params
    assert crawl_run_params["failure_summary"] == {"DB_ERROR": 2}


@pytest.mark.asyncio
async def test_commit_terminal_can_preserve_existing_crawl_run_outcome():
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _ExecuteResult(rowcount=1),
            _ExecuteResult(rowcount=0),
        ]
    )
    event = TerminalEvent(
        crawl_run_id=uuid4(),
        job_id=uuid4(),
        job_status=Status.FAILED,
        outcome_code=CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR,
        finished_at=datetime.now(timezone.utc),
        result_location="Unhandled exception while running crawl",
        only_set_crawl_outcome_if_missing=True,
    )

    result = await commit_terminal(session, event)

    crawl_run_stmt = session.execute.call_args_list[1].args[0]
    assert "outcome_code IS NULL" in str(crawl_run_stmt.compile())
    assert result.job_rows_updated == 1
    assert result.crawl_run_rows_updated == 0


@pytest.mark.asyncio
async def test_commit_terminal_can_complete_successful_crawl_without_outcome_code():
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _ExecuteResult(rowcount=1),
            _ExecuteResult(rowcount=1),
        ]
    )
    event = TerminalEvent(
        crawl_run_id=uuid4(),
        job_id=uuid4(),
        job_status=Status.COMPLETE,
        outcome_code=None,
        finished_at=datetime.now(timezone.utc),
        result_location="/api/v1/websites/00000000-0000-0000-0000-000000000000/info-blobs/",
        crawl_run_update=CrawlRunTerminalUpdate(
            pages_crawled=3,
            files_downloaded=1,
            pages_failed=0,
            files_failed=0,
            pages_source_retained=0,
            pages_hash_retained=0,
            files_hash_retained=0,
            files_too_large_skipped=0,
            failure_summary=None,
        ),
    )

    result = await commit_terminal(session, event)

    job_stmt = session.execute.call_args_list[0].args[0]
    crawl_run_stmt = session.execute.call_args_list[1].args[0]
    job_params = job_stmt.compile().params
    crawl_run_params = crawl_run_stmt.compile().params
    assert job_params["status"] == Status.COMPLETE.value
    assert crawl_run_params["outcome_code"] is None
    assert crawl_run_params["pages_crawled"] == 3
    assert crawl_run_params["files_downloaded"] == 1
    assert result.job_rows_updated == 1
    assert result.crawl_run_rows_updated == 1


@pytest.mark.asyncio
async def test_commit_terminal_batch_updates_job_and_crawl_run_sets_once():
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _ExecuteResult(rowcount=2),
            _ExecuteResult(rowcount=2),
        ]
    )
    event = TerminalBatchEvent(
        crawl_run_ids=(uuid4(), uuid4()),
        job_ids=(uuid4(), uuid4()),
        job_status=Status.FAILED,
        outcome_code=CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES,
        finished_at=datetime.now(timezone.utc),
        result_location="Crawl stalled before collecting pages",
        only_set_crawl_outcome_if_missing=True,
    )

    result = await commit_terminal_batch(session, event)

    assert session.execute.call_count == 2
    crawl_run_stmt = session.execute.call_args_list[1].args[0]
    crawl_run_params = crawl_run_stmt.compile().params
    assert result.job_rows_updated == 2
    assert result.crawl_run_rows_updated == 2
    assert "outcome_code IS NULL" in str(crawl_run_stmt.compile())
    assert (
        crawl_run_params["outcome_code"]
        == CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES.value
    )


def test_terminal_batch_event_rejects_mismatched_job_and_crawl_run_counts():
    with pytest.raises(ValueError, match="same number"):
        TerminalBatchEvent(
            crawl_run_ids=(uuid4(),),
            job_ids=(uuid4(), uuid4()),
            job_status=Status.FAILED,
            outcome_code=CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES,
            finished_at=datetime.now(timezone.utc),
        )
