from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from intric.websites.domain.crawl_run import CrawlType
from intric.worker.feeder.crawl_enqueue import (
    CrawlEnqueued,
    CrawlEnqueueDuplicate,
    CrawlEnqueueFailed,
    enqueue_crawl_job,
)


@pytest.mark.asyncio
async def test_enqueue_crawl_job_returns_enqueued_and_builds_crawl_task() -> None:
    job_id = uuid4()
    user_id = uuid4()
    website_id = uuid4()
    run_id = uuid4()

    with patch("intric.worker.feeder.crawl_enqueue.job_manager") as job_manager:
        job_manager.enqueue = AsyncMock(return_value=True)

        result = await enqueue_crawl_job(
            job_id=job_id,
            user_id=user_id,
            website_id=website_id,
            run_id=run_id,
            url="https://example.com",
            download_files=True,
            crawl_type=CrawlType.CRAWL,
        )

    assert isinstance(result, CrawlEnqueued)
    assert result.job_id == job_id

    job_manager.enqueue.assert_awaited_once()
    call_kwargs = job_manager.enqueue.await_args.kwargs
    params = call_kwargs["params"]
    assert call_kwargs["job_id"] == job_id
    assert params.user_id == user_id
    assert params.website_id == website_id
    assert params.run_id == run_id
    assert params.url == "https://example.com"
    assert params.download_files is True
    assert params.crawl_type == CrawlType.CRAWL


@pytest.mark.asyncio
async def test_enqueue_crawl_job_returns_duplicate_for_native_arq_duplicate() -> None:
    with patch("intric.worker.feeder.crawl_enqueue.job_manager") as job_manager:
        job_manager.enqueue = AsyncMock(return_value=False)

        result = await enqueue_crawl_job(
            job_id=uuid4(),
            user_id=uuid4(),
            website_id=uuid4(),
            run_id=uuid4(),
            url="https://example.com",
            download_files=False,
            crawl_type=CrawlType.SITEMAP,
        )

    assert isinstance(result, CrawlEnqueueDuplicate)


@pytest.mark.asyncio
async def test_enqueue_crawl_job_returns_failed_without_parsing_exception_text() -> (
    None
):
    expected_error = Exception("Job already exists")

    with patch("intric.worker.feeder.crawl_enqueue.job_manager") as job_manager:
        job_manager.enqueue = AsyncMock(side_effect=expected_error)

        result = await enqueue_crawl_job(
            job_id=uuid4(),
            user_id=uuid4(),
            website_id=uuid4(),
            run_id=uuid4(),
            url="https://example.com",
            download_files=False,
            crawl_type=CrawlType.CRAWL,
        )

    assert isinstance(result, CrawlEnqueueFailed)
    assert result.error is expected_error
