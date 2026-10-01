from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from eneo.jobs.job_manager import (
    CRAWLER_QUEUE_NAME,
    DEFAULT_QUEUE_NAME,
    JobManager,
)
from eneo.jobs.job_models import Task
from eneo.jobs.task_models import TaskParams


async def test_crawl_jobs_use_the_dedicated_crawler_queue() -> None:
    manager = JobManager()
    redis = AsyncMock()
    manager._redis = redis
    job_id = uuid4()
    params = TaskParams(user_id=uuid4())

    await manager.enqueue(Task.CRAWL, job_id, params)

    redis.enqueue_job.assert_awaited_once_with(
        Task.CRAWL,
        params,
        _job_id=str(job_id),
        _queue_name=CRAWLER_QUEUE_NAME,
    )


async def test_non_crawler_jobs_remain_on_the_general_queue() -> None:
    manager = JobManager()
    redis = AsyncMock()
    manager._redis = redis
    job_id = uuid4()
    params = TaskParams(user_id=uuid4())

    await manager.enqueue(Task.UPLOAD_FILE, job_id, params)

    redis.enqueue_job.assert_awaited_once_with(
        Task.UPLOAD_FILE,
        params,
        _job_id=str(job_id),
        _queue_name=DEFAULT_QUEUE_NAME,
    )


async def test_crawl_status_uses_the_same_queue_as_enqueue() -> None:
    manager = JobManager()
    redis = AsyncMock()
    manager._redis = redis
    job_id = uuid4()
    arq_job = MagicMock()
    arq_job.status = AsyncMock(return_value="queued")

    with patch("eneo.jobs.job_manager.Job", return_value=arq_job) as job_class:
        status = await manager.get_job_status(job_id, Task.CRAWL)

    assert status == "queued"
    job_class.assert_called_once_with(
        job_id=str(job_id),
        redis=redis,
        _queue_name=CRAWLER_QUEUE_NAME,
    )
