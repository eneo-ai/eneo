from uuid import uuid4

from arq.jobs import JobStatus

from eneo.jobs.job_manager import (
    CRAWLER_QUEUE_NAME,
    DEFAULT_QUEUE_NAME,
    JobManager,
)
from eneo.jobs.job_models import Task
from eneo.jobs.task_models import TaskParams


async def test_crawl_and_upload_jobs_are_published_to_separate_queues(
    redis_client,
) -> None:
    manager = JobManager()
    crawl_job_id = uuid4()
    upload_job_id = uuid4()
    params = TaskParams(user_id=uuid4())

    await manager.init()
    try:
        await manager.enqueue(Task.CRAWL, crawl_job_id, params)
        await manager.enqueue(Task.UPLOAD_FILE, upload_job_id, params)

        assert (
            await manager.get_job_status(crawl_job_id, Task.CRAWL) == JobStatus.queued
        )
        assert (
            await redis_client.zscore(
                CRAWLER_QUEUE_NAME,
                str(crawl_job_id),
            )
            is not None
        )
        assert (
            await redis_client.zscore(
                DEFAULT_QUEUE_NAME,
                str(crawl_job_id),
            )
            is None
        )
        assert (
            await redis_client.zscore(
                DEFAULT_QUEUE_NAME,
                str(upload_job_id),
            )
            is not None
        )
        assert (
            await redis_client.zscore(
                CRAWLER_QUEUE_NAME,
                str(upload_job_id),
            )
            is None
        )
    finally:
        await redis_client.zrem(
            CRAWLER_QUEUE_NAME,
            str(crawl_job_id),
            str(upload_job_id),
        )
        await redis_client.zrem(
            DEFAULT_QUEUE_NAME,
            str(crawl_job_id),
            str(upload_job_id),
        )
        await redis_client.delete(
            f"arq:job:{crawl_job_id}",
            f"arq:job:{upload_job_id}",
        )
        await manager.close()
