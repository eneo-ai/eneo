from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.worker.crawl import CrawlSlotAcquirePath
from intric.worker.crawl.slot_acquire import (
    CrawlSlotAcquireRequest,
    acquire_crawl_slot,
)
from intric.worker.redis.lua_scripts import LuaScripts
from intric.worker.tenant_concurrency import TenantConcurrencyLimiter


def _limiter(*, acquired: bool = True) -> MagicMock:
    limiter = MagicMock(spec=TenantConcurrencyLimiter)
    limiter.acquire = AsyncMock(return_value=acquired)
    return limiter


def _redis() -> MagicMock:
    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.expire = AsyncMock()
    return redis_client


@pytest.mark.asyncio
async def test_matching_preacquired_slot_is_reused_and_refreshes_ttl():
    job_id = uuid4()
    tenant_id = uuid4()
    redis_client = _redis()
    limiter = _limiter()

    result = await acquire_crawl_slot(
        CrawlSlotAcquireRequest(
            job_id=job_id,
            tenant_id=tenant_id,
            preacquired_tenant_id=tenant_id,
            semaphore_ttl_seconds=300,
        ),
        limiter=limiter,
        redis_client=redis_client,
    )

    assert result.acquired is True
    assert result.path == CrawlSlotAcquirePath.PREACQUIRED_REUSED
    assert result.preacquired_tenant_id == tenant_id
    limiter.acquire.assert_not_awaited()
    redis_client.expire.assert_awaited_once_with(
        f"tenant:{tenant_id}:active_jobs",
        300,
    )


@pytest.mark.asyncio
async def test_mismatched_preacquired_slot_is_released_before_acquiring_tenant_slot():
    job_id = uuid4()
    feeder_tenant_id = uuid4()
    worker_tenant_id = uuid4()
    redis_client = _redis()
    limiter = _limiter()

    with patch(
        "intric.worker.crawl.slot_acquire.LuaScripts.release_slot",
        new=AsyncMock(),
    ) as release_slot:
        result = await acquire_crawl_slot(
            CrawlSlotAcquireRequest(
                job_id=job_id,
                tenant_id=worker_tenant_id,
                preacquired_tenant_id=feeder_tenant_id,
                semaphore_ttl_seconds=300,
            ),
            limiter=limiter,
            redis_client=redis_client,
        )

    assert result.acquired is True
    assert result.path == CrawlSlotAcquirePath.PREACQUIRED_MISMATCH_REACQUIRED
    assert result.preacquired_tenant_id is None
    release_slot.assert_awaited_once_with(redis_client, feeder_tenant_id, 300)
    limiter.acquire.assert_awaited_once_with(worker_tenant_id)


@pytest.mark.asyncio
async def test_absent_preacquired_state_is_retried_from_redis_before_normal_acquire():
    job_id = uuid4()
    tenant_id = uuid4()
    redis_client = _redis()
    redis_client.get = AsyncMock(return_value=str(tenant_id).encode())
    limiter = _limiter()

    result = await acquire_crawl_slot(
        CrawlSlotAcquireRequest(
            job_id=job_id,
            tenant_id=tenant_id,
            preacquired_tenant_id=None,
            semaphore_ttl_seconds=300,
        ),
        limiter=limiter,
        redis_client=redis_client,
    )

    assert result.acquired is True
    assert result.path == CrawlSlotAcquirePath.PREACQUIRED_REUSED
    assert result.preacquired_tenant_id == tenant_id
    redis_client.get.assert_awaited_once_with(LuaScripts.preacquired_slot_key(job_id))
    limiter.acquire.assert_not_awaited()


@pytest.mark.asyncio
async def test_normal_acquire_when_no_preacquired_slot_exists():
    tenant_id = uuid4()
    redis_client = _redis()
    limiter = _limiter()

    result = await acquire_crawl_slot(
        CrawlSlotAcquireRequest(
            job_id=uuid4(),
            tenant_id=tenant_id,
            preacquired_tenant_id=None,
            semaphore_ttl_seconds=300,
        ),
        limiter=limiter,
        redis_client=redis_client,
    )

    assert result.acquired is True
    assert result.path == CrawlSlotAcquirePath.NORMAL_ACQUIRED
    assert result.preacquired_tenant_id is None
    limiter.acquire.assert_awaited_once_with(tenant_id)


@pytest.mark.asyncio
async def test_limit_reached_when_normal_acquire_is_rejected():
    tenant_id = uuid4()
    redis_client = _redis()
    limiter = _limiter(acquired=False)

    result = await acquire_crawl_slot(
        CrawlSlotAcquireRequest(
            job_id=uuid4(),
            tenant_id=tenant_id,
            preacquired_tenant_id=None,
            semaphore_ttl_seconds=300,
        ),
        limiter=limiter,
        redis_client=redis_client,
    )

    assert result.acquired is False
    assert result.path == CrawlSlotAcquirePath.LIMIT_REACHED
    assert result.preacquired_tenant_id is None


@pytest.mark.asyncio
async def test_preacquired_read_failure_falls_back_to_normal_acquire_and_logs_warning():
    job_id = uuid4()
    tenant_id = uuid4()
    redis_client = _redis()
    redis_client.get = AsyncMock(side_effect=RuntimeError("redis unavailable"))
    limiter = _limiter()
    logger = MagicMock()

    with patch("intric.worker.crawl.slot_acquire.logger", logger):
        result = await acquire_crawl_slot(
            CrawlSlotAcquireRequest(
                job_id=job_id,
                tenant_id=tenant_id,
                preacquired_tenant_id=None,
                semaphore_ttl_seconds=300,
            ),
            limiter=limiter,
            redis_client=redis_client,
        )

    assert result.acquired is True
    assert result.path == CrawlSlotAcquirePath.NORMAL_ACQUIRED
    limiter.acquire.assert_awaited_once_with(tenant_id)
    logger.warning.assert_called_once_with(
        "Failed to check pre-acquired crawl slot",
        extra={"job_id": str(job_id), "error": "redis unavailable"},
    )


@pytest.mark.asyncio
async def test_invalid_preacquired_tenant_id_falls_back_to_normal_acquire():
    job_id = uuid4()
    tenant_id = uuid4()
    redis_client = _redis()
    redis_client.get = AsyncMock(return_value=b"not-a-uuid")
    limiter = _limiter()
    logger = MagicMock()

    with patch("intric.worker.crawl.slot_acquire.logger", logger):
        result = await acquire_crawl_slot(
            CrawlSlotAcquireRequest(
                job_id=job_id,
                tenant_id=tenant_id,
                preacquired_tenant_id=None,
                semaphore_ttl_seconds=300,
            ),
            limiter=limiter,
            redis_client=redis_client,
        )

    assert result.acquired is True
    assert result.path == CrawlSlotAcquirePath.NORMAL_ACQUIRED
    limiter.acquire.assert_awaited_once_with(tenant_id)
    logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_preacquired_ttl_refresh_failure_keeps_reused_slot_result():
    job_id = uuid4()
    tenant_id = uuid4()
    redis_client = _redis()
    redis_client.expire = AsyncMock(side_effect=RuntimeError("expire failed"))
    limiter = _limiter()
    logger = MagicMock()

    with patch("intric.worker.crawl.slot_acquire.logger", logger):
        result = await acquire_crawl_slot(
            CrawlSlotAcquireRequest(
                job_id=job_id,
                tenant_id=tenant_id,
                preacquired_tenant_id=tenant_id,
                semaphore_ttl_seconds=300,
            ),
            limiter=limiter,
            redis_client=redis_client,
        )

    assert result.acquired is True
    assert result.path == CrawlSlotAcquirePath.PREACQUIRED_REUSED
    limiter.acquire.assert_not_awaited()
    logger.debug.assert_any_call(
        "Failed to refresh pre-acquired crawl slot TTL",
        extra={
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "error": "expire failed",
        },
    )


@pytest.mark.asyncio
async def test_tenant_injection_failure_discovers_preacquired_slot_without_acquiring():
    job_id = uuid4()
    preacquired_tenant_id = uuid4()
    redis_client = _redis()
    redis_client.get = AsyncMock(return_value=str(preacquired_tenant_id).encode())

    result = await acquire_crawl_slot(
        CrawlSlotAcquireRequest(
            job_id=job_id,
            tenant_id=None,
            preacquired_tenant_id=None,
            semaphore_ttl_seconds=300,
        ),
        limiter=None,
        redis_client=redis_client,
    )

    assert result.acquired is False
    assert result.path == CrawlSlotAcquirePath.NOOP
    assert result.preacquired_tenant_id == preacquired_tenant_id


@pytest.mark.asyncio
async def test_mismatch_release_followed_by_limit_reached_clears_preacquired_state():
    job_id = uuid4()
    feeder_tenant_id = uuid4()
    worker_tenant_id = uuid4()
    redis_client = _redis()
    limiter = _limiter(acquired=False)

    with patch(
        "intric.worker.crawl.slot_acquire.LuaScripts.release_slot",
        new=AsyncMock(),
    ) as release_slot:
        result = await acquire_crawl_slot(
            CrawlSlotAcquireRequest(
                job_id=job_id,
                tenant_id=worker_tenant_id,
                preacquired_tenant_id=feeder_tenant_id,
                semaphore_ttl_seconds=300,
            ),
            limiter=limiter,
            redis_client=redis_client,
        )

    assert result.acquired is False
    assert result.path == CrawlSlotAcquirePath.PREACQUIRED_MISMATCH_REACQUIRED
    assert result.preacquired_tenant_id is None
    release_slot.assert_awaited_once_with(redis_client, feeder_tenant_id, 300)
    limiter.acquire.assert_awaited_once_with(worker_tenant_id)


@pytest.mark.asyncio
async def test_mismatch_release_failure_is_logged_and_correct_tenant_acquire_still_runs():
    job_id = uuid4()
    feeder_tenant_id = uuid4()
    worker_tenant_id = uuid4()
    redis_client = _redis()
    limiter = _limiter()
    logger = MagicMock()

    with (
        patch(
            "intric.worker.crawl.slot_acquire.LuaScripts.release_slot",
            new=AsyncMock(side_effect=RuntimeError("redis failed")),
        ) as release_slot,
        patch("intric.worker.crawl.slot_acquire.logger", logger),
    ):
        result = await acquire_crawl_slot(
            CrawlSlotAcquireRequest(
                job_id=job_id,
                tenant_id=worker_tenant_id,
                preacquired_tenant_id=feeder_tenant_id,
                semaphore_ttl_seconds=300,
            ),
            limiter=limiter,
            redis_client=redis_client,
        )

    assert result.acquired is True
    assert result.path == CrawlSlotAcquirePath.PREACQUIRED_MISMATCH_REACQUIRED
    release_slot.assert_awaited_once()
    limiter.acquire.assert_awaited_once_with(worker_tenant_id)
    logger.error.assert_any_call(
        "Failed to release mismatched pre-acquired crawl slot",
        extra={
            "job_id": str(job_id),
            "tenant_id": str(feeder_tenant_id),
            "error": "redis failed",
        },
    )
