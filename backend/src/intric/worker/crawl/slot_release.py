from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from intric.main.config import Settings
from intric.main.logging import get_logger
from intric.worker.crawl.recovery import reset_tenant_retry_delay
from intric.worker.feeder.capacity import CapacityManager
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
        if redis_client is not None:
            await CapacityManager(redis_client, settings).clear_preacquired_flag(
                request.job_id
            )
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

        released = await CapacityManager(
            redis_client, settings
        ).release_preacquired_slot(
            job_id=request.job_id,
            tenant_id=request.preacquired_tenant_id,
        )
        return CrawlSlotReleaseResult(
            released=released,
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
