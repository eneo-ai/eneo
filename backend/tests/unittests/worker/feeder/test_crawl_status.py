import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import redis
from arq.jobs import JobStatus

from intric.main.exceptions import NotReadyException
from intric.worker.feeder.crawl_status import (
    CrawlJobStatus,
    CrawlJobStatusKnown,
    CrawlJobStatusLookupFailed,
    get_crawl_job_status,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arq_status", "expected_status"),
    [
        (JobStatus.deferred, CrawlJobStatus.DEFERRED),
        (JobStatus.queued, CrawlJobStatus.QUEUED),
        (JobStatus.in_progress, CrawlJobStatus.IN_PROGRESS),
        (JobStatus.complete, CrawlJobStatus.COMPLETE),
        (JobStatus.not_found, CrawlJobStatus.NOT_FOUND),
    ],
)
async def test_get_crawl_job_status_maps_arq_statuses(
    arq_status: JobStatus,
    expected_status: CrawlJobStatus,
) -> None:
    job_id = uuid4()
    with patch("intric.worker.feeder.crawl_status.job_manager") as job_manager:
        job_manager.get_job_status = AsyncMock(return_value=arq_status)

        result = await get_crawl_job_status(job_id)

    assert isinstance(result, CrawlJobStatusKnown)
    assert result.job_id == job_id
    assert result.status == expected_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected_error",
    [
        NotReadyException("Job manager is not initialized!"),
        redis.ConnectionError("redis unavailable"),
        asyncio.TimeoutError("status query timed out"),
    ],
)
async def test_get_crawl_job_status_returns_lookup_failed_on_status_query_error(
    expected_error: Exception,
) -> None:
    job_id = uuid4()
    with patch("intric.worker.feeder.crawl_status.job_manager") as job_manager:
        job_manager.get_job_status = AsyncMock(side_effect=expected_error)

        result = await get_crawl_job_status(job_id)

    assert isinstance(result, CrawlJobStatusLookupFailed)
    assert result.job_id == job_id
    assert result.error is expected_error


@pytest.mark.asyncio
async def test_get_crawl_job_status_returns_lookup_failed_on_unknown_arq_status() -> (
    None
):
    job_id = uuid4()
    with patch("intric.worker.feeder.crawl_status.job_manager") as job_manager:
        job_manager.get_job_status = AsyncMock(return_value=object())

        result = await get_crawl_job_status(job_id)

    assert isinstance(result, CrawlJobStatusLookupFailed)
    assert result.job_id == job_id
    assert isinstance(result.error, KeyError)
