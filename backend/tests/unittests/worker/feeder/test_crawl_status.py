import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import redis

from intric.jobs.job_manager import JobRuntimeStatus
from intric.main.exceptions import NotReadyException
from intric.worker.feeder.crawl_status import (
    CrawlJobStatus,
    CrawlJobStatusKnown,
    CrawlJobStatusLookupFailed,
    get_crawl_job_status,
)


def test_crawl_status_does_not_import_arq_status_enum() -> None:
    source_path = Path(__file__).parents[4] / "src/intric/worker/feeder/crawl_status.py"
    source = source_path.read_text()

    assert "arq.jobs" not in source


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arq_status", "expected_status"),
    [
        (JobRuntimeStatus.DEFERRED, CrawlJobStatus.DEFERRED),
        (JobRuntimeStatus.QUEUED, CrawlJobStatus.QUEUED),
        (JobRuntimeStatus.IN_PROGRESS, CrawlJobStatus.IN_PROGRESS),
        (JobRuntimeStatus.COMPLETE, CrawlJobStatus.COMPLETE),
        (JobRuntimeStatus.NOT_FOUND, CrawlJobStatus.NOT_FOUND),
    ],
)
async def test_get_crawl_job_status_maps_runtime_statuses(
    arq_status: JobRuntimeStatus,
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
