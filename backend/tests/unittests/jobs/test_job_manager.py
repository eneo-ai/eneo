from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.jobs.job_manager import JobManager
from intric.jobs.job_models import Task
from intric.websites.crawl_dependencies.crawl_models import CrawlTask
from intric.websites.domain.crawl_run import CrawlType


@pytest.mark.asyncio
async def test_enqueue_returns_true_when_arq_enqueues_job():
    manager = JobManager()
    manager._redis = AsyncMock()
    manager._redis.enqueue_job = AsyncMock(return_value=object())

    enqueued = await manager.enqueue(
        task=Task.CRAWL,
        job_id=uuid4(),
        params=CrawlTask(
            user_id=uuid4(),
            website_id=uuid4(),
            run_id=uuid4(),
            url="https://example.com",
            download_files=False,
            crawl_type=CrawlType.CRAWL,
        ),
    )

    assert enqueued is True


@pytest.mark.asyncio
async def test_enqueue_returns_false_when_arq_reports_duplicate_job_id():
    manager = JobManager()
    manager._redis = AsyncMock()
    manager._redis.enqueue_job = AsyncMock(return_value=None)

    enqueued = await manager.enqueue(
        task=Task.CRAWL,
        job_id=uuid4(),
        params=CrawlTask(
            user_id=uuid4(),
            website_id=uuid4(),
            run_id=uuid4(),
            url="https://example.com",
            download_files=False,
            crawl_type=CrawlType.CRAWL,
        ),
    )

    assert enqueued is False
