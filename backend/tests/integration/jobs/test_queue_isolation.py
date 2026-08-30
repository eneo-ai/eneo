from uuid import uuid4

from arq.constants import abort_jobs_ss
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


async def test_discard_crawl_deliveries_removes_orphan_transport_state(
    redis_client,
) -> None:
    manager = JobManager()
    job_ids = (uuid4(), uuid4())
    upload_job_id = uuid4()
    params = TaskParams(user_id=uuid4())

    await manager.init()
    try:
        await manager.enqueue(Task.UPLOAD_FILE, upload_job_id, params)
        for job_id in job_ids:
            await manager.enqueue(Task.CRAWL, job_id, params)
            await redis_client.set(f"arq:in-progress:{job_id}", b"1")
            await redis_client.set(f"arq:retry:{job_id}", b"1")
            await redis_client.set(f"arq:result:{job_id}", b"1")
            await redis_client.zadd(abort_jobs_ss, {str(job_id): 1})

        await manager.discard_crawl_deliveries(job_ids)

        for job_id in job_ids:
            assert await redis_client.zscore(CRAWLER_QUEUE_NAME, str(job_id)) is None
            assert await redis_client.exists(f"arq:job:{job_id}") == 0
            assert await redis_client.exists(f"arq:in-progress:{job_id}") == 0
            assert await redis_client.exists(f"arq:retry:{job_id}") == 0
            assert await redis_client.exists(f"arq:result:{job_id}") == 0
            assert await redis_client.zscore(abort_jobs_ss, str(job_id)) is None
        assert (
            await redis_client.zscore(DEFAULT_QUEUE_NAME, str(upload_job_id))
            is not None
        )
        assert await redis_client.exists(f"arq:job:{upload_job_id}") == 1
    finally:
        await redis_client.delete(
            *(
                key
                for job_id in job_ids
                for key in (
                    f"arq:job:{job_id}",
                    f"arq:in-progress:{job_id}",
                    f"arq:retry:{job_id}",
                    f"arq:result:{job_id}",
                )
            )
        )
        await redis_client.zrem(CRAWLER_QUEUE_NAME, *(str(value) for value in job_ids))
        await redis_client.zrem(DEFAULT_QUEUE_NAME, str(upload_job_id))
        await redis_client.zrem(abort_jobs_ss, *(str(value) for value in job_ids))
        await redis_client.delete(f"arq:job:{upload_job_id}")
        await manager.close()
