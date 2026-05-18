from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from intric.main.logging import get_logger
from intric.worker.feeder.capacity import CapacityManager
from intric.worker.tenant_concurrency import TenantConcurrencyLimiter

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = get_logger(__name__)


class CrawlSlotAcquirePath(str, Enum):
    PREACQUIRED_REUSED = "preacquired_reused"
    PREACQUIRED_MISMATCH_REACQUIRED = "preacquired_mismatch_reacquired"
    NORMAL_ACQUIRED = "normal_acquired"
    LIMIT_REACHED = "limit_reached"
    NOOP = "noop"


@dataclass(frozen=True, slots=True)
class CrawlSlotAcquireRequest:
    job_id: UUID
    tenant_id: UUID | None
    preacquired_tenant_id: UUID | None
    semaphore_ttl_seconds: int


@dataclass(frozen=True, slots=True)
class CrawlSlotAcquireResult:
    acquired: bool
    path: CrawlSlotAcquirePath
    preacquired_tenant_id: UUID | None


async def _read_preacquired_tenant_id(
    *,
    redis_client: aioredis.Redis | None,
    job_id: UUID,
) -> UUID | None:
    if redis_client is None:
        return None

    return await CapacityManager(redis_client).get_preacquired_tenant(job_id)


async def _refresh_preacquired_slot_ttl(
    *,
    redis_client: aioredis.Redis | None,
    tenant_id: UUID,
    ttl_seconds: int,
    job_id: UUID,
) -> None:
    if redis_client is None:
        return

    await CapacityManager(redis_client).refresh_slot_ttl(
        tenant_id=tenant_id,
        ttl_seconds=ttl_seconds,
        job_id=job_id,
    )


async def _release_mismatched_preacquired_slot(
    *,
    redis_client: aioredis.Redis | None,
    preacquired_tenant_id: UUID,
    worker_tenant_id: UUID,
    job_id: UUID,
    ttl_seconds: int,
) -> None:
    logger.error(
        "Tenant ID mismatch between feeder and worker",
        extra={
            "job_id": str(job_id),
            "feeder_tenant_id": str(preacquired_tenant_id),
            "worker_tenant_id": str(worker_tenant_id),
            "action": "releasing_feeder_slot_and_acquiring_new",
        },
    )

    if redis_client is None:
        return

    await CapacityManager(redis_client).release_preacquired_slot(
        job_id=job_id,
        tenant_id=preacquired_tenant_id,
        ttl_seconds=ttl_seconds,
    )


async def acquire_crawl_slot(
    request: CrawlSlotAcquireRequest,
    *,
    limiter: TenantConcurrencyLimiter | None,
    redis_client: aioredis.Redis | None,
) -> CrawlSlotAcquireResult:
    preacquired_tenant_id = request.preacquired_tenant_id
    if preacquired_tenant_id is None:
        preacquired_tenant_id = await _read_preacquired_tenant_id(
            redis_client=redis_client,
            job_id=request.job_id,
        )

    if request.tenant_id is None or limiter is None:
        return CrawlSlotAcquireResult(
            acquired=False,
            path=CrawlSlotAcquirePath.NOOP,
            preacquired_tenant_id=preacquired_tenant_id,
        )

    if preacquired_tenant_id == request.tenant_id:
        logger.debug(
            "Slot pre-acquired by feeder, skipping limiter.acquire()",
            extra={"job_id": str(request.job_id), "tenant_id": str(request.tenant_id)},
        )
        await _refresh_preacquired_slot_ttl(
            redis_client=redis_client,
            tenant_id=request.tenant_id,
            ttl_seconds=request.semaphore_ttl_seconds,
            job_id=request.job_id,
        )
        return CrawlSlotAcquireResult(
            acquired=True,
            path=CrawlSlotAcquirePath.PREACQUIRED_REUSED,
            preacquired_tenant_id=preacquired_tenant_id,
        )

    if preacquired_tenant_id is not None:
        await _release_mismatched_preacquired_slot(
            redis_client=redis_client,
            preacquired_tenant_id=preacquired_tenant_id,
            worker_tenant_id=request.tenant_id,
            job_id=request.job_id,
            ttl_seconds=request.semaphore_ttl_seconds,
        )
        acquired = await limiter.acquire(request.tenant_id)
        return CrawlSlotAcquireResult(
            acquired=acquired,
            path=CrawlSlotAcquirePath.PREACQUIRED_MISMATCH_REACQUIRED,
            preacquired_tenant_id=None,
        )

    acquired = await limiter.acquire(request.tenant_id)
    return CrawlSlotAcquireResult(
        acquired=acquired,
        path=CrawlSlotAcquirePath.NORMAL_ACQUIRED
        if acquired
        else CrawlSlotAcquirePath.LIMIT_REACHED,
        preacquired_tenant_id=None,
    )
