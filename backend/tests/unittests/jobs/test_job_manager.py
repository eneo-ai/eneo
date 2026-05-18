from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from arq.connections import ArqRedis
from arq.jobs import JobStatus

from intric.jobs.job_manager import JobManager, JobRuntimeStatus
from intric.jobs.job_models import Task
from intric.main.exceptions import NotReadyException
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


@pytest.mark.asyncio
async def test_abort_job_delegates_to_arq_job_abort():
    job_id = uuid4()
    manager = JobManager()
    redis = AsyncMock(spec=ArqRedis)
    manager._redis = redis

    arq_job = Mock()
    arq_job.abort = AsyncMock(return_value=True)
    with patch(
        "intric.jobs.job_manager.Job",
        return_value=arq_job,
    ) as job_cls:
        aborted = await manager.abort_job(
            job_id,
            timeout=12.0,
            poll_delay=0.25,
        )

    assert aborted is True
    job_cls.assert_called_once_with(job_id=str(job_id), redis=redis)
    arq_job.abort.assert_awaited_once_with(timeout=12.0, poll_delay=0.25)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arq_status", "expected_status"),
    [
        (JobStatus.deferred, JobRuntimeStatus.DEFERRED),
        (JobStatus.queued, JobRuntimeStatus.QUEUED),
        (JobStatus.in_progress, JobRuntimeStatus.IN_PROGRESS),
        (JobStatus.complete, JobRuntimeStatus.COMPLETE),
        (JobStatus.not_found, JobRuntimeStatus.NOT_FOUND),
    ],
)
async def test_get_job_status_maps_arq_status_to_runtime_status(
    arq_status: JobStatus,
    expected_status: JobRuntimeStatus,
):
    job_id = uuid4()
    manager = JobManager()
    redis = AsyncMock(spec=ArqRedis)
    manager._redis = redis

    arq_job = Mock()
    arq_job.status = AsyncMock(return_value=arq_status)
    with patch("intric.jobs.job_manager.Job", return_value=arq_job):
        status = await manager.get_job_status(job_id)

    assert status == expected_status


@pytest.mark.asyncio
async def test_abort_job_uses_arq_default_abort_options():
    job_id = uuid4()
    manager = JobManager()
    redis = AsyncMock(spec=ArqRedis)
    manager._redis = redis

    arq_job = Mock()
    arq_job.abort = AsyncMock(return_value=False)
    with patch(
        "intric.jobs.job_manager.Job",
        return_value=arq_job,
    ) as job_cls:
        aborted = await manager.abort_job(job_id)

    assert aborted is False
    job_cls.assert_called_once_with(job_id=str(job_id), redis=redis)
    arq_job.abort.assert_awaited_once_with(timeout=None, poll_delay=0.5)


@pytest.mark.asyncio
async def test_abort_job_requires_initialized_job_manager():
    manager = JobManager()

    with pytest.raises(NotReadyException):
        await manager.abort_job(uuid4())
