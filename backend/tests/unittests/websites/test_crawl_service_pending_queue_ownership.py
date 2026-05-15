from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

import pytest
import redis.asyncio as aioredis

from intric.jobs.job_models import JobInDb, Task
from intric.main.models import Status
from intric.websites.domain.crawl_run import CrawlRun, CrawlType
from intric.websites.domain.crawl_service import CrawlService
from intric.websites.domain.website import UpdateInterval, WebsiteSparse
from intric.worker.feeder.queues import (
    CrawlPendingJobData,
    PendingQueue,
    PendingQueueAddError,
)

if TYPE_CHECKING:
    from intric.jobs.task_service import TaskService
    from intric.websites.domain.crawl_run_repo import CrawlRunRepository


class AtCapacityRedis(aioredis.Redis):
    async def eval(self, script: object, numkeys: int, *keys_and_args: object) -> int:
        del script, numkeys, keys_and_args
        return 0

    async def rpush(self, name: object, *values: object) -> int:
        del name, values
        return 1


class CrawlRunRepositoryStub:
    async def add(self, crawl_run: CrawlRun) -> CrawlRun:
        return crawl_run

    async def update(self, crawl_run: CrawlRun) -> CrawlRun:
        return crawl_run


class JobServiceStub:
    def __init__(self) -> None:
        self.failed_job_ids: list[UUID] = []
        self.error_messages: list[str] = []

    async def fail_job(self, job_id: UUID, error_message: str) -> None:
        self.failed_job_ids.append(job_id)
        self.error_messages.append(error_message)


class TaskServiceStub:
    def __init__(self, job_id: UUID, user_id: UUID) -> None:
        self.job_id = job_id
        self.user_id = user_id
        self.job_service = JobServiceStub()
        self.queued_run_id: UUID | None = None

    async def queue_crawl(
        self,
        name: str,
        run_id: UUID,
        url: str,
        download_files: bool = False,
        crawl_type: CrawlType = CrawlType.CRAWL,
        website_id: UUID | None = None,
        enqueue: bool = True,
    ) -> JobInDb:
        del name, url, download_files, crawl_type, website_id, enqueue
        self.queued_run_id = run_id
        return JobInDb(
            id=self.job_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            user_id=self.user_id,
            status=Status.QUEUED,
            task=Task.CRAWL,
            result_location=None,
            finished_at=None,
        )


def _make_service(
    *,
    redis_client: AtCapacityRedis,
    task_service: TaskServiceStub,
) -> CrawlService:
    return CrawlService(
        repo=cast("CrawlRunRepository", CrawlRunRepositoryStub()),
        task_service=cast("TaskService", task_service),
        redis_client=redis_client,
    )


def _make_website(
    *,
    user_id: UUID,
    tenant_id: UUID,
    website_id: UUID | None = None,
) -> WebsiteSparse:
    now = datetime.now(UTC)
    return WebsiteSparse(
        id=website_id or uuid4(),
        created_at=now,
        updated_at=now,
        user_id=user_id,
        tenant_id=tenant_id,
        embedding_model_id=uuid4(),
        space_id=uuid4(),
        name="Example",
        url="https://example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=UpdateInterval.NEVER,
        size=0,
        last_crawled_at=None,
    )


@pytest.mark.asyncio
async def test_at_capacity_crawl_uses_pending_queue_add(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    tenant_id = uuid4()
    job_id = uuid4()
    task_service = TaskServiceStub(job_id=job_id, user_id=user_id)
    service = _make_service(
        redis_client=AtCapacityRedis(),
        task_service=task_service,
    )
    website = _make_website(user_id=user_id, tenant_id=tenant_id)
    added_jobs: list[tuple[UUID, CrawlPendingJobData]] = []

    async def record_add(
        self: PendingQueue,
        tenant_id: UUID,
        job_data: CrawlPendingJobData,
    ) -> None:
        del self
        added_jobs.append((tenant_id, job_data))

    monkeypatch.setattr(PendingQueue, "add", record_add)

    await service.crawl(website)

    assert task_service.queued_run_id is not None
    assert added_jobs == [
        (
            tenant_id,
            {
                "job_id": str(job_id),
                "user_id": str(user_id),
                "website_id": str(website.id),
                "run_id": str(task_service.queued_run_id),
                "url": website.url,
                "download_files": website.download_files,
                "crawl_type": website.crawl_type.value,
            },
        )
    ]


@pytest.mark.asyncio
async def test_at_capacity_queue_failure_fails_precreated_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    tenant_id = uuid4()
    job_id = uuid4()
    redis_error = RuntimeError("redis unavailable")
    task_service = TaskServiceStub(job_id=job_id, user_id=user_id)
    service = _make_service(
        redis_client=AtCapacityRedis(),
        task_service=task_service,
    )
    website = _make_website(user_id=user_id, tenant_id=tenant_id)

    async def fail_add(
        self: PendingQueue,
        tenant_id: UUID,
        job_data: CrawlPendingJobData,
    ) -> None:
        del self, job_data
        raise PendingQueueAddError(tenant_id=tenant_id, cause=redis_error)

    monkeypatch.setattr(PendingQueue, "add", fail_add)

    with pytest.raises(PendingQueueAddError):
        await service.crawl(website)

    assert task_service.job_service.failed_job_ids == [job_id]
    assert "redis unavailable" in task_service.job_service.error_messages[0]


def test_callers_do_not_own_pending_queue_key_or_serialization() -> None:
    backend_root = Path(__file__).parents[3]
    source_paths = [
        backend_root / "src/intric/websites/domain/crawl_service.py",
        backend_root / "src/intric/worker/crawl_tasks.py",
    ]

    forbidden_patterns = [
        re.compile(r"\.rpush\("),
        re.compile(r"tenant:.*crawl_pending"),
        re.compile(r"json\.dumps\(.*sort_keys=True"),
        re.compile(r"if not await pending_queue\.add"),
    ]

    for source_path in source_paths:
        source = source_path.read_text()
        for pattern in forbidden_patterns:
            assert pattern.search(source) is None
