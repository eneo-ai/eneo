from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.main.models import Status
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode, FailureReason
from intric.websites.domain.crawl_run import CrawlFileTooLargeSample
from intric.websites.domain.crawl_terminal import (
    ACTIVE_TERMINAL_JOB_STATUSES,
    CrawlRunTerminalUpdate,
    TerminalBatchEvent,
    TerminalEvent,
    commit_terminal,
    commit_terminal_batch,
)
from intric.websites.domain.crawl_terminal_source import CrawlTerminalSource
from intric.worker.crawl import TerminalEvent as WorkerTerminalEvent
from intric.worker.crawl import commit_terminal as worker_commit_terminal


class _ExecuteResult:
    def __init__(self, rowcount: int, scalar_values: tuple[object, ...] = ()) -> None:
        self.rowcount = rowcount
        self._scalar_values = scalar_values

    def scalars(self) -> "_ExecuteResult":
        return self

    def all(self) -> list[object]:
        return list(self._scalar_values)


def _compiled_param_values(statement) -> set[object]:
    values: set[object] = set()
    for value in statement.compile().params.values():
        if isinstance(value, (list, tuple, set)):
            values.update(value)
        else:
            values.add(value)
    return values


def test_worker_crawl_package_re_exports_canonical_terminal_boundary():
    assert WorkerTerminalEvent is TerminalEvent
    assert worker_commit_terminal is commit_terminal
    assert ACTIVE_TERMINAL_JOB_STATUSES == (Status.QUEUED, Status.IN_PROGRESS)


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
        terminal_source=CrawlTerminalSource.CRAWLER,
        finished_at=finished_at,
        result_location="Skipped duplicate crawl; active job 00000000-0000-0000-0000-000000000000",
    )

    result = await commit_terminal(session, event)

    assert result.job_rows_updated == 1
    assert result.crawl_run_rows_updated == 1
    assert session.execute.call_count == 2
    crawl_run_stmt = session.execute.call_args_list[1].args[0]
    crawl_run_params = crawl_run_stmt.compile().params
    assert crawl_run_params["terminal_source"] == CrawlTerminalSource.CRAWLER.value


@pytest.mark.asyncio
async def test_commit_terminal_skips_crawl_run_when_job_gate_loses_race():
    """Regression: if the Jobs UPDATE matches zero rows because the worker
    has already committed a different terminal state from another path, the
    CrawlRun must not be overwritten with this caller's outcome. Otherwise
    we end up with Jobs.status=COMPLETE while CrawlRuns.outcome_code flipped
    to a contradictory CRAWL_ABORTED."""
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _ExecuteResult(rowcount=0),
        ]
    )
    event = TerminalEvent(
        crawl_run_id=uuid4(),
        job_id=uuid4(),
        job_status=Status.FAILED,
        outcome_code=CrawlOutcomeCode.CRAWL_ABORTED,
        terminal_source=CrawlTerminalSource.ADMIN,
        finished_at=datetime.now(timezone.utc),
        result_location="Crawl aborted by tenant admin",
        allowed_current_job_statuses=(Status.QUEUED, Status.IN_PROGRESS),
    )

    result = await commit_terminal(session, event)

    assert result.job_rows_updated == 0
    assert result.crawl_run_rows_updated == 0
    # Only the Jobs UPDATE should run; the CrawlRun UPDATE must be skipped.
    assert session.execute.call_count == 1


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
        terminal_source=CrawlTerminalSource.CRAWLER,
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
            files_too_large_download_limit_bytes=10_485_760,
            files_too_large_samples=(
                CrawlFileTooLargeSample(
                    url="https://example.com/large.pdf",
                    observed_size_bytes=19_746_387,
                ),
            ),
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
    assert crawl_run_params["files_too_large_download_limit_bytes"] == 10_485_760
    assert crawl_run_params["files_too_large_samples"] == [
        {
            "url": "https://example.com/large.pdf",
            "observed_size_bytes": 19_746_387,
        }
    ]
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
        terminal_source=CrawlTerminalSource.CRAWLER,
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
        terminal_source=CrawlTerminalSource.CRAWLER,
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
        terminal_source=CrawlTerminalSource.CRAWLER,
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
    job_ids = (uuid4(), uuid4())
    session.execute = AsyncMock(
        side_effect=[
            _ExecuteResult(rowcount=2, scalar_values=job_ids),
            _ExecuteResult(rowcount=2),
        ]
    )
    event = TerminalBatchEvent(
        crawl_run_ids=(uuid4(), uuid4()),
        job_ids=job_ids,
        job_status=Status.FAILED,
        outcome_code=CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES,
        terminal_source=CrawlTerminalSource.WATCHDOG,
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
    assert crawl_run_params["terminal_source"] == CrawlTerminalSource.WATCHDOG.value


@pytest.mark.asyncio
async def test_commit_terminal_batch_updates_only_crawl_runs_whose_jobs_won_gate():
    session = AsyncMock()
    crawl_run_ids = (uuid4(), uuid4())
    job_ids = (uuid4(), uuid4())
    session.execute = AsyncMock(
        side_effect=[
            _ExecuteResult(rowcount=1, scalar_values=(job_ids[0],)),
            _ExecuteResult(rowcount=1),
        ]
    )
    event = TerminalBatchEvent(
        crawl_run_ids=crawl_run_ids,
        job_ids=job_ids,
        job_status=Status.FAILED,
        outcome_code=CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES,
        terminal_source=CrawlTerminalSource.WATCHDOG,
        finished_at=datetime.now(timezone.utc),
        result_location="Crawl stalled before collecting pages",
        only_set_crawl_outcome_if_missing=True,
    )

    result = await commit_terminal_batch(session, event)

    crawl_run_stmt = session.execute.call_args_list[1].args[0]
    crawl_run_id_filter_values = _compiled_param_values(crawl_run_stmt)
    assert result.job_rows_updated == 1
    assert result.crawl_run_rows_updated == 1
    assert crawl_run_ids[0] in crawl_run_id_filter_values
    assert crawl_run_ids[1] not in crawl_run_id_filter_values


def test_terminal_batch_event_rejects_mismatched_job_and_crawl_run_counts():
    with pytest.raises(ValueError, match="same number"):
        TerminalBatchEvent(
            crawl_run_ids=(uuid4(),),
            job_ids=(uuid4(), uuid4()),
            job_status=Status.FAILED,
            outcome_code=CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES,
            terminal_source=CrawlTerminalSource.WATCHDOG,
            finished_at=datetime.now(timezone.utc),
        )
