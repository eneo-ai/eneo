import asyncio
import warnings
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from arq.worker import create_worker

from eneo.jobs.job_manager import CRAWLER_QUEUE_NAME, JobManager
from eneo.jobs.job_models import Task
from eneo.main.config import get_settings
from eneo.redis.connection import build_arq_redis_settings
from eneo.websites.crawl_dependencies.crawl_models import CrawlTask
from eneo.worker import routes
from eneo.worker.arq import CrawlerWorkerSettings


async def test_a_crawl_enqueued_by_the_job_manager_is_consumed_by_the_crawler_worker(
    redis_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The role the crawler-worker Compose services start consumes crawl jobs.

    The job goes in through the production path (JobManager.enqueue to
    arq:crawler) and is picked up by a worker built from the shipped
    CrawlerWorkerSettings, so the registered function name, the queue, the
    serializers and the params round trip are all the real ones. Only the crawl
    itself, and the startup hook that needs the whole application, are replaced.
    """
    delivered: list[tuple[UUID, CrawlTask]] = []

    async def crawl_task(*, job_id: UUID, params: CrawlTask, container: object) -> str:
        del container
        delivered.append((job_id, params))
        return "crawled"

    monkeypatch.setattr(routes, "crawl_task", crawl_task)
    monkeypatch.setattr(
        routes, "_reconcile_crawl_dispatch_and_record_health", AsyncMock()
    )

    job_id = uuid4()
    params = CrawlTask(
        user_id=uuid4(),
        website_id=uuid4(),
        run_id=uuid4(),
        url="https://example.test/",
    )
    manager = JobManager()
    await manager.init()
    try:
        await manager.enqueue(Task.CRAWL, job_id, params)
        assert await redis_client.zscore(CRAWLER_QUEUE_NAME, str(job_id)) is not None

        worker = create_worker(
            CrawlerWorkerSettings,
            redis_settings=build_arq_redis_settings(get_settings()),
            on_startup=None,
            on_shutdown=None,
            burst=True,
            poll_delay=0.05,
            handle_signals=False,
        )
        try:
            await asyncio.wait_for(worker.main(), timeout=30)
        finally:
            with warnings.catch_warnings():
                # ARQ's Worker.close still calls the deprecated Redis close().
                warnings.simplefilter("ignore", DeprecationWarning)
                await worker.close()

        assert delivered == [(job_id, params)]
        assert await redis_client.zscore(CRAWLER_QUEUE_NAME, str(job_id)) is None
    finally:
        await redis_client.zrem(CRAWLER_QUEUE_NAME, str(job_id))
        await redis_client.delete(
            f"arq:job:{job_id}",
            f"arq:in-progress:{job_id}",
            f"arq:result:{job_id}",
            f"{CRAWLER_QUEUE_NAME}:health-check",
        )
        await manager.close()
