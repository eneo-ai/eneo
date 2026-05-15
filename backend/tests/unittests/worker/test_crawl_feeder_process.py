"""Unit tests for crawl feeder orchestration."""

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call
from uuid import UUID, uuid4

import pytest

from intric.tenants.crawler_settings_helper import TenantCrawlerSettings
from intric.websites.domain.crawl_run import CrawlType
from intric.worker.crawl_feeder import DLQ_MAX_ENTRIES, DLQ_TTL_SECONDS, CrawlFeeder
from intric.worker.feeder.capacity import CapacityManager
from intric.worker.feeder.crawl_enqueue import (
    CrawlEnqueued,
    CrawlEnqueueDuplicate,
    CrawlEnqueueFailed,
    CrawlEnqueueResult,
)
from intric.worker.feeder.queues import JobEnqueuer, PendingCrawlPayload, PendingQueue
from intric.worker.redis.lua_scripts import LuaScripts


@dataclass(frozen=True, slots=True)
class _PendingJob:
    raw_bytes: bytes
    job_data: PendingCrawlPayload


class _PendingQueueForProcessTest(PendingQueue):
    def __init__(self, jobs: Sequence[_PendingJob]) -> None:
        self.jobs = list(jobs)
        self.removed_raw_bytes: list[bytes] = []

    async def get_pending(
        self, tenant_id: UUID, limit: int
    ) -> list[tuple[bytes, PendingCrawlPayload]]:
        return [(pending.raw_bytes, pending.job_data) for pending in self.jobs[:limit]]

    async def remove(self, tenant_id: UUID, raw_bytes: bytes) -> None:
        self.removed_raw_bytes.append(raw_bytes)


class _CapacityManagerForProcessTest(CapacityManager):
    def __init__(self) -> None:
        self.released_tenants: list[UUID] = []
        self.preacquired_jobs: list[UUID] = []

    async def get_tenant_settings(self, tenant_id: UUID) -> TenantCrawlerSettings:
        return TenantCrawlerSettings.from_overrides(None)

    async def get_available_capacity(
        self,
        tenant_id: UUID,
        tenant_settings: TenantCrawlerSettings | None = None,
    ) -> int:
        return 1

    async def try_acquire_slot(
        self,
        tenant_id: UUID,
        tenant_settings: TenantCrawlerSettings | None = None,
    ) -> bool:
        return True

    async def mark_slot_preacquired(
        self,
        job_id: UUID,
        tenant_id: UUID,
        tenant_settings: TenantCrawlerSettings | None = None,
    ) -> None:
        self.preacquired_jobs.append(job_id)

    async def release_slot(
        self,
        tenant_id: UUID,
        tenant_settings: TenantCrawlerSettings | None = None,
    ) -> None:
        self.released_tenants.append(tenant_id)


class _TypedJobEnqueuerForProcessTest(JobEnqueuer):
    def __init__(self, result: CrawlEnqueueResult) -> None:
        self.result = result
        self.calls: list[tuple[PendingCrawlPayload, UUID]] = []

    async def enqueue(
        self, job_data: PendingCrawlPayload, tenant_id: UUID
    ) -> CrawlEnqueueResult:
        self.calls.append((job_data, tenant_id))
        return self.result


def _pending_job(job_id: UUID, raw_bytes: bytes) -> _PendingJob:
    return _PendingJob(
        raw_bytes=raw_bytes,
        job_data={
            "job_id": str(job_id),
            "user_id": str(uuid4()),
            "website_id": str(uuid4()),
            "run_id": str(uuid4()),
            "url": "https://example.com",
            "download_files": False,
            "crawl_type": CrawlType.CRAWL.value,
        },
    )


@pytest.mark.asyncio
class TestCrawlFeederProcessTenantQueue:
    async def test_successful_enqueue_keeps_slot_and_removes_pending(self) -> None:
        tenant_id = uuid4()
        job_id = uuid4()
        raw_bytes = b'{"job_id":"enqueued"}'
        pending_queue = _PendingQueueForProcessTest([_pending_job(job_id, raw_bytes)])
        capacity_manager = _CapacityManagerForProcessTest()
        job_enqueuer = _TypedJobEnqueuerForProcessTest(CrawlEnqueued(job_id=job_id))
        redis_client = MagicMock()
        redis_client.delete = AsyncMock()

        feeder = CrawlFeeder()
        feeder._pending_queue = pending_queue
        feeder._capacity_manager = capacity_manager
        feeder._job_enqueuer = job_enqueuer

        await feeder._process_tenant_queue(tenant_id, redis_client)

        assert pending_queue.removed_raw_bytes == [raw_bytes]
        assert capacity_manager.preacquired_jobs == [job_id]
        assert capacity_manager.released_tenants == []
        redis_client.delete.assert_not_awaited()

    async def test_duplicate_enqueue_releases_slot_keeps_flag_and_removes_pending(
        self,
    ) -> None:
        tenant_id = uuid4()
        job_id = uuid4()
        raw_bytes = b'{"job_id":"duplicate"}'
        pending_queue = _PendingQueueForProcessTest([_pending_job(job_id, raw_bytes)])
        capacity_manager = _CapacityManagerForProcessTest()
        job_enqueuer = _TypedJobEnqueuerForProcessTest(
            CrawlEnqueueDuplicate(job_id=job_id)
        )
        redis_client = MagicMock()
        redis_client.delete = AsyncMock()

        feeder = CrawlFeeder()
        feeder._pending_queue = pending_queue
        feeder._capacity_manager = capacity_manager
        feeder._job_enqueuer = job_enqueuer

        await feeder._process_tenant_queue(tenant_id, redis_client)

        assert pending_queue.removed_raw_bytes == [raw_bytes]
        assert capacity_manager.preacquired_jobs == [job_id]
        assert capacity_manager.released_tenants == [tenant_id]
        redis_client.delete.assert_not_awaited()

    async def test_failed_enqueue_releases_slot_deletes_flag_and_keeps_pending(
        self,
    ) -> None:
        tenant_id = uuid4()
        job_id = uuid4()
        raw_bytes = b'{"job_id":"failed"}'
        pending_queue = _PendingQueueForProcessTest([_pending_job(job_id, raw_bytes)])
        capacity_manager = _CapacityManagerForProcessTest()
        job_enqueuer = _TypedJobEnqueuerForProcessTest(
            CrawlEnqueueFailed(job_id=job_id, error=RuntimeError("redis unavailable"))
        )
        redis_client = MagicMock()
        redis_client.delete = AsyncMock()

        feeder = CrawlFeeder()
        feeder._pending_queue = pending_queue
        feeder._capacity_manager = capacity_manager
        feeder._job_enqueuer = job_enqueuer

        await feeder._process_tenant_queue(tenant_id, redis_client)

        assert pending_queue.removed_raw_bytes == []
        assert capacity_manager.preacquired_jobs == [job_id]
        assert capacity_manager.released_tenants == [tenant_id]
        redis_client.delete.assert_awaited_once_with(
            LuaScripts.preacquired_slot_key(job_id)
        )

    async def test_invalid_pending_job_id_moves_entry_to_dlq_and_removes_pending(
        self,
    ) -> None:
        tenant_id = uuid4()
        raw_bytes = b'{"url":"missing-job-id"}'
        pending_queue = _PendingQueueForProcessTest(
            [_PendingJob(raw_bytes=raw_bytes, job_data={"url": "https://example.com"})]
        )
        capacity_manager = _CapacityManagerForProcessTest()
        job_enqueuer = _TypedJobEnqueuerForProcessTest(
            CrawlEnqueueFailed(
                job_id=UUID("00000000-0000-0000-0000-000000000000"),
                error=RuntimeError("should not enqueue poison payload"),
            )
        )
        redis_client = MagicMock()
        redis_client.lpush = AsyncMock(return_value=1)
        redis_client.ltrim = AsyncMock(return_value=True)
        redis_client.expire = AsyncMock(return_value=True)

        feeder = CrawlFeeder()
        feeder._pending_queue = pending_queue
        feeder._capacity_manager = capacity_manager
        feeder._job_enqueuer = job_enqueuer

        await feeder._process_tenant_queue(tenant_id, redis_client)

        dlq_key = f"tenant:{tenant_id}:crawl_pending:dlq"
        assert redis_client.mock_calls == [
            call.lpush(dlq_key, raw_bytes),
            call.ltrim(dlq_key, 0, DLQ_MAX_ENTRIES - 1),
            call.expire(dlq_key, DLQ_TTL_SECONDS),
        ]
        assert pending_queue.removed_raw_bytes == [raw_bytes]
        assert capacity_manager.preacquired_jobs == []
        assert job_enqueuer.calls == []


def test_feeder_and_pending_queue_do_not_import_any_or_cast() -> None:
    """Redis typing uncertainty belongs in worker.redis.client."""
    repo_root = Path(__file__).parents[3]
    source_paths = [
        repo_root / "src/intric/worker/crawl_feeder.py",
        repo_root / "src/intric/worker/feeder/queues.py",
    ]

    for source_path in source_paths:
        module = ast.parse(source_path.read_text())
        forbidden: list[str] = []

        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom) and node.module == "typing":
                forbidden.extend(
                    alias.name for alias in node.names if alias.name in {"Any", "cast"}
                )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "cast":
                    forbidden.append("cast")

        assert forbidden == [], (
            f"{source_path.name} uses weak local typing: {forbidden}"
        )
