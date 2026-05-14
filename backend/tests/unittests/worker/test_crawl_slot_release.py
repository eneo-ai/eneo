from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.worker.crawl import CrawlSlotReleasePath


@pytest.mark.asyncio
async def test_normal_release_uses_limiter_resets_backoff_and_deletes_flag():
    from intric.main.config import get_settings
    from intric.worker.crawl.slot_release import (
        CrawlSlotReleaseRequest,
        release_crawl_slot_after_task,
    )
    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter

    job_id = uuid4()
    tenant_id = uuid4()
    redis_client = MagicMock()
    redis_client.eval = AsyncMock()
    redis_client.delete = AsyncMock()
    limiter = TenantConcurrencyLimiter(
        redis=redis_client,
        max_concurrent=4,
        ttl_seconds=300,
    )

    result = await release_crawl_slot_after_task(
        CrawlSlotReleaseRequest(
            job_id=job_id,
            tenant_id=tenant_id,
            preacquired_tenant_id=None,
            acquired=True,
        ),
        limiter=limiter,
        redis_client=redis_client,
        settings=get_settings(),
    )

    assert result.released is True
    assert result.path == CrawlSlotReleasePath.NORMAL
    redis_client.eval.assert_awaited_once()
    redis_client.delete.assert_any_await(f"tenant:{tenant_id}:limiter_backoff")
    redis_client.delete.assert_any_await(f"job:{job_id}:slot_preacquired")


@pytest.mark.asyncio
async def test_preacquired_fallback_releases_with_lua_and_deletes_flag():
    from intric.main.config import get_settings
    from intric.worker.crawl.slot_release import (
        CrawlSlotReleaseRequest,
        release_crawl_slot_after_task,
    )

    job_id = uuid4()
    tenant_id = uuid4()
    settings = get_settings()
    redis_client = MagicMock()
    redis_client.delete = AsyncMock()

    with patch(
        "intric.worker.crawl.slot_release.LuaScripts.release_slot",
        new=AsyncMock(),
    ) as release_slot:
        result = await release_crawl_slot_after_task(
            CrawlSlotReleaseRequest(
                job_id=job_id,
                tenant_id=None,
                preacquired_tenant_id=tenant_id,
                acquired=False,
            ),
            limiter=None,
            redis_client=redis_client,
            settings=settings,
        )

    assert result.released is True
    assert result.path == CrawlSlotReleasePath.PREACQUIRED_FALLBACK
    release_slot.assert_awaited_once_with(
        redis_client,
        tenant_id,
        settings.tenant_worker_semaphore_ttl_seconds,
    )
    redis_client.delete.assert_awaited_once_with(f"job:{job_id}:slot_preacquired")


@pytest.mark.asyncio
async def test_emergency_release_uses_flag_recovery_when_tenant_paths_are_unavailable():
    from intric.main.config import get_settings
    from intric.worker.crawl.slot_release import (
        CrawlSlotReleaseRequest,
        release_crawl_slot_after_task,
    )

    job_id = uuid4()
    redis_client = MagicMock()
    capacity_manager = MagicMock()
    capacity_manager.emergency_release_slot = AsyncMock(return_value=True)

    with patch(
        "intric.worker.crawl.slot_release.CapacityManager",
        return_value=capacity_manager,
    ):
        result = await release_crawl_slot_after_task(
            CrawlSlotReleaseRequest(
                job_id=job_id,
                tenant_id=None,
                preacquired_tenant_id=None,
                acquired=False,
            ),
            limiter=None,
            redis_client=redis_client,
            settings=get_settings(),
        )

    assert result.released is True
    assert result.path == CrawlSlotReleasePath.EMERGENCY
    capacity_manager.emergency_release_slot.assert_awaited_once_with(job_id)


@pytest.mark.asyncio
async def test_no_release_when_no_slot_was_acquired():
    from intric.main.config import get_settings
    from intric.worker.crawl.slot_release import (
        CrawlSlotReleaseRequest,
        release_crawl_slot_after_task,
    )

    tenant_id = uuid4()
    redis_client = MagicMock()

    result = await release_crawl_slot_after_task(
        CrawlSlotReleaseRequest(
            job_id=uuid4(),
            tenant_id=tenant_id,
            preacquired_tenant_id=None,
            acquired=False,
        ),
        limiter=None,
        redis_client=redis_client,
        settings=get_settings(),
    )

    assert result.released is False
    assert result.path == CrawlSlotReleasePath.NOOP


@pytest.mark.asyncio
async def test_preacquired_fallback_returns_unreleased_when_lua_release_fails():
    from intric.main.config import get_settings
    from intric.worker.crawl.slot_release import (
        CrawlSlotReleaseRequest,
        release_crawl_slot_after_task,
    )

    job_id = uuid4()
    tenant_id = uuid4()
    redis_client = MagicMock()
    redis_client.delete = AsyncMock()
    logger = MagicMock()

    with (
        patch(
            "intric.worker.crawl.slot_release.LuaScripts.release_slot",
            new=AsyncMock(side_effect=RuntimeError("redis unavailable")),
        ) as release_slot,
        patch("intric.worker.crawl.slot_release.logger", logger),
    ):
        result = await release_crawl_slot_after_task(
            CrawlSlotReleaseRequest(
                job_id=job_id,
                tenant_id=None,
                preacquired_tenant_id=tenant_id,
                acquired=False,
            ),
            limiter=None,
            redis_client=redis_client,
            settings=get_settings(),
        )

    assert result.released is False
    assert result.path == CrawlSlotReleasePath.PREACQUIRED_FALLBACK
    release_slot.assert_awaited_once()
    redis_client.delete.assert_not_awaited()
    logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_preacquired_fallback_reports_unreleased_when_redis_is_unavailable():
    from intric.main.config import get_settings
    from intric.worker.crawl.slot_release import (
        CrawlSlotReleaseRequest,
        release_crawl_slot_after_task,
    )

    logger = MagicMock()
    job_id = uuid4()
    tenant_id = uuid4()

    with patch("intric.worker.crawl.slot_release.logger", logger):
        result = await release_crawl_slot_after_task(
            CrawlSlotReleaseRequest(
                job_id=job_id,
                tenant_id=None,
                preacquired_tenant_id=tenant_id,
                acquired=False,
            ),
            limiter=None,
            redis_client=None,
            settings=get_settings(),
        )

    assert result.released is False
    assert result.path == CrawlSlotReleasePath.PREACQUIRED_FALLBACK
    logger.warning.assert_any_call(
        "Cannot release pre-acquired crawl slot because Redis is unavailable",
        extra={"job_id": str(job_id), "tenant_id": str(tenant_id)},
    )


@pytest.mark.asyncio
async def test_flag_delete_failure_keeps_successful_release_result():
    from intric.main.config import get_settings
    from intric.worker.crawl.slot_release import (
        CrawlSlotReleaseRequest,
        release_crawl_slot_after_task,
    )

    redis_client = MagicMock()
    redis_client.delete = AsyncMock(side_effect=RuntimeError("delete failed"))
    logger = MagicMock()

    with (
        patch(
            "intric.worker.crawl.slot_release.LuaScripts.release_slot",
            new=AsyncMock(),
        ),
        patch("intric.worker.crawl.slot_release.logger", logger),
    ):
        result = await release_crawl_slot_after_task(
            CrawlSlotReleaseRequest(
                job_id=uuid4(),
                tenant_id=None,
                preacquired_tenant_id=uuid4(),
                acquired=False,
            ),
            limiter=None,
            redis_client=redis_client,
            settings=get_settings(),
        )

    assert result.released is True
    assert result.path == CrawlSlotReleasePath.PREACQUIRED_FALLBACK
    logger.debug.assert_called_once()


@pytest.mark.asyncio
async def test_emergency_release_reports_unreleased_when_redis_is_unavailable():
    from intric.main.config import get_settings
    from intric.worker.crawl.slot_release import (
        CrawlSlotReleaseRequest,
        release_crawl_slot_after_task,
    )

    job_id = uuid4()
    logger = MagicMock()

    with patch("intric.worker.crawl.slot_release.logger", logger):
        result = await release_crawl_slot_after_task(
            CrawlSlotReleaseRequest(
                job_id=job_id,
                tenant_id=None,
                preacquired_tenant_id=None,
                acquired=False,
            ),
            limiter=None,
            redis_client=None,
            settings=get_settings(),
        )

    assert result.released is False
    assert result.path == CrawlSlotReleasePath.EMERGENCY
    logger.warning.assert_called_once_with(
        "Cannot run emergency crawl slot release because Redis is unavailable",
        extra={"job_id": str(job_id)},
    )
