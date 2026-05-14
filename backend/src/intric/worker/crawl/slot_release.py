from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from intric.main.config import Settings
from intric.main.logging import get_logger
from intric.worker.crawl.recovery import reset_tenant_retry_delay
from intric.worker.feeder.capacity import CapacityManager
from intric.worker.redis.lua_scripts import LuaScripts
from intric.worker.tenant_concurrency import TenantConcurrencyLimiter

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = get_logger(__name__)


class CrawlSlotReleasePath(str, Enum):
    NORMAL = "normal"
    PREACQUIRED_FALLBACK = "preacquired_fallback"
    EMERGENCY = "emergency"
    NOOP = "noop"


@dataclass(frozen=True, slots=True)
class CrawlSlotReleaseRequest:
    job_id: UUID
    tenant_id: UUID | None
    preacquired_tenant_id: UUID | None
    acquired: bool


@dataclass(frozen=True, slots=True)
class CrawlSlotReleaseResult:
    released: bool
    path: CrawlSlotReleasePath


async def _delete_preacquired_flag(
    redis_client: aioredis.Redis | None,
    job_id: UUID,
) -> None:
    if redis_client is None:
        return

    try:
        await redis_client.delete(LuaScripts.preacquired_slot_key(job_id))
    except Exception as exc:
        logger.debug(
            "Failed to delete crawl pre-acquired slot flag",
            extra={"job_id": str(job_id), "error": str(exc)},
        )


async def release_crawl_slot_after_task(
    request: CrawlSlotReleaseRequest,
    *,
    limiter: TenantConcurrencyLimiter | None,
    redis_client: aioredis.Redis | None,
    settings: Settings,
) -> CrawlSlotReleaseResult:
    if limiter is not None and request.tenant_id is not None and request.acquired:
        await limiter.release(request.tenant_id)
        await reset_tenant_retry_delay(
            tenant_id=request.tenant_id,
            redis_client=redis_client,
        )
        await _delete_preacquired_flag(redis_client, request.job_id)
        return CrawlSlotReleaseResult(
            released=True,
            path=CrawlSlotReleasePath.NORMAL,
        )

    if request.preacquired_tenant_id is not None and not request.acquired:
        logger.warning(
            "Releasing pre-acquired slot due to early failure",
            extra={
                "job_id": str(request.job_id),
                "tenant_id": str(request.preacquired_tenant_id),
                "reason": "tenant_injection_failed"
                if request.tenant_id is None
                else "acquired_not_set",
            },
        )
        if redis_client is None:
            logger.warning(
                "Cannot release pre-acquired crawl slot because Redis is unavailable",
                extra={
                    "job_id": str(request.job_id),
                    "tenant_id": str(request.preacquired_tenant_id),
                },
            )
            return CrawlSlotReleaseResult(
                released=False,
                path=CrawlSlotReleasePath.PREACQUIRED_FALLBACK,
            )

        try:
            await LuaScripts.release_slot(
                redis_client,
                request.preacquired_tenant_id,
                settings.tenant_worker_semaphore_ttl_seconds,
            )
            await _delete_preacquired_flag(redis_client, request.job_id)
            return CrawlSlotReleaseResult(
                released=True,
                path=CrawlSlotReleasePath.PREACQUIRED_FALLBACK,
            )
        except Exception as release_exc:
            logger.error(
                "Failed to release pre-acquired slot in fallback",
                extra={
                    "job_id": str(request.job_id),
                    "tenant_id": str(request.preacquired_tenant_id),
                    "error": str(release_exc),
                },
            )
            return CrawlSlotReleaseResult(
                released=False,
                path=CrawlSlotReleasePath.PREACQUIRED_FALLBACK,
            )

    if (
        request.tenant_id is None
        and request.preacquired_tenant_id is None
        and not request.acquired
    ):
        if redis_client is None:
            logger.warning(
                "Cannot run emergency crawl slot release because Redis is unavailable",
                extra={"job_id": str(request.job_id)},
            )
            return CrawlSlotReleaseResult(
                released=False,
                path=CrawlSlotReleasePath.EMERGENCY,
            )

        capacity_manager = CapacityManager(redis_client, settings)
        released = await capacity_manager.emergency_release_slot(request.job_id)
        return CrawlSlotReleaseResult(
            released=released,
            path=CrawlSlotReleasePath.EMERGENCY,
        )

    return CrawlSlotReleaseResult(released=False, path=CrawlSlotReleasePath.NOOP)
