"""Capacity management for per-tenant concurrency limiting.

Combines slot acquisition/release with tenant-specific settings retrieval.
Uses Lua scripts for atomic Redis operations to prevent race conditions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.tenants.crawler_settings_helper import get_crawler_setting
from intric.worker.redis.lua_scripts import LuaScripts

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = get_logger(__name__)


class CapacityManager:
    """Manages per-tenant concurrency slots and settings.

    Provides atomic slot acquisition/release using Lua scripts and
    retrieves tenant-specific crawler settings from the database.

    Args:
        redis_client: Async Redis connection.
        settings: Application settings (optional, uses global if not provided).
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        settings=None,
    ) -> None:
        self._redis = redis_client
        self._settings = settings or get_settings()

    async def get_tenant_settings(self, tenant_id: UUID) -> dict | None:
        """Fetch tenant's crawler_settings from the database.

        Uses a fresh session to avoid lifecycle issues in long-running services.

        Args:
            tenant_id: Tenant identifier.

        Returns:
            Dict of crawler_settings or None if tenant not found.
        """
        from sqlalchemy import select

        from intric.database.database import sessionmanager
        from intric.database.tables.tenant_table import Tenants

        try:
            async with sessionmanager.session() as session, session.begin():
                stmt = select(Tenants.crawler_settings).where(Tenants.id == tenant_id)
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                return row if row else {}
        except Exception as exc:
            logger.warning(
                "Failed to fetch tenant crawler settings",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )
            return None

    def get_max_concurrent(self, tenant_settings: dict | None = None) -> int:
        """Get maximum concurrent jobs limit for a tenant.

        Args:
            tenant_settings: Optional tenant-specific settings override.

        Returns:
            Maximum concurrent jobs allowed.
        """
        return get_crawler_setting(
            "tenant_worker_concurrency_limit",
            tenant_settings,
            default=self._settings.tenant_worker_concurrency_limit,
        )

    def get_slot_ttl(self, tenant_settings: dict | None = None) -> int:
        """Get slot TTL in seconds for a tenant.

        Args:
            tenant_settings: Optional tenant-specific settings override.

        Returns:
            TTL in seconds for slot counter.
        """
        return get_crawler_setting(
            "tenant_worker_semaphore_ttl_seconds",
            tenant_settings,
            default=self._settings.tenant_worker_semaphore_ttl_seconds,
        )

    async def try_acquire_slot(
        self,
        tenant_id: UUID,
        tenant_settings: dict | None = None,
    ) -> bool:
        """Atomically acquire a concurrency slot for a tenant.

        Uses Lua script for atomic INCR-then-check to prevent race conditions.

        Args:
            tenant_id: Tenant identifier.
            tenant_settings: Optional tenant-specific settings.

        Returns:
            True if slot acquired, False if at capacity.
        """
        max_concurrent = self.get_max_concurrent(tenant_settings)
        ttl = self.get_slot_ttl(tenant_settings)

        try:
            result = await LuaScripts.acquire_slot(
                self._redis, tenant_id, max_concurrent, ttl
            )
            acquired = result > 0

            if not acquired:
                logger.debug(
                    "Slot acquisition failed (at capacity)",
                    extra={
                        "tenant_id": str(tenant_id),
                        "max_concurrent": max_concurrent,
                    },
                )

            return acquired

        except Exception as exc:
            logger.warning(
                "Failed to acquire slot",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )
            return False

    async def release_slot(
        self,
        tenant_id: UUID,
        tenant_settings: dict | None = None,
    ) -> None:
        """Release a previously acquired slot.

        Args:
            tenant_id: Tenant identifier.
            tenant_settings: Optional tenant-specific settings.
        """
        ttl = self.get_slot_ttl(tenant_settings)

        try:
            await LuaScripts.release_slot(self._redis, tenant_id, ttl)
        except Exception as exc:
            logger.warning(
                "Failed to release slot",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )

    async def get_available_capacity(
        self,
        tenant_id: UUID,
        tenant_settings: dict | None = None,
    ) -> int:
        """Check available crawl capacity for a tenant (read-only).

        Used to decide how many pending jobs to consider.
        Actual slot acquisition is done atomically via try_acquire_slot().

        Args:
            tenant_id: Tenant identifier.
            tenant_settings: Optional tenant-specific settings.

        Returns:
            Number of jobs that can be enqueued (0 if at capacity).
        """
        key = LuaScripts.slot_key(tenant_id)
        max_concurrent = self.get_max_concurrent(tenant_settings)

        try:
            active_jobs_bytes = await self._redis.get(key)

            if not active_jobs_bytes:
                return max_concurrent  # No active jobs, full capacity

            active_jobs = int(active_jobs_bytes.decode())
            active_jobs = max(0, min(active_jobs, max_concurrent))

            return max(0, max_concurrent - active_jobs)

        except Exception as exc:
            logger.warning(
                "Failed to check available capacity",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )
            return 0  # Conservative: assume no capacity

    async def mark_slot_preacquired(
        self,
        job_id: UUID,
        tenant_id: UUID,
        tenant_settings: dict | None = None,
    ) -> None:
        """Mark that a slot was pre-acquired for a job.

        Worker checks this flag to skip limiter.acquire() when slot is already held.
        TTL ensures cleanup if job is never picked up.

        Args:
            job_id: The job identifier.
            tenant_id: Stored in value for slot release on errors.
            tenant_settings: Optional tenant-specific settings.

        Raises:
            Exception: If Redis operation fails - caller MUST handle and release slot.
        """
        key = f"job:{job_id}:slot_preacquired"
        ttl = self.get_slot_ttl(tenant_settings)
        await self._redis.set(key, str(tenant_id), ex=ttl)

    async def clear_preacquired_flag(self, job_id: UUID) -> None:
        """Clear the pre-acquired flag for a job.

        Args:
            job_id: The job identifier.
        """
        key = f"job:{job_id}:slot_preacquired"
        try:
            await self._redis.delete(key)
        except Exception:
            pass  # Best effort cleanup

    async def get_preacquired_tenant(self, job_id: UUID) -> UUID | None:
        """Get the tenant ID from a pre-acquired flag.

        Args:
            job_id: The job identifier.

        Returns:
            Tenant UUID if flag exists, None otherwise.
        """
        key = f"job:{job_id}:slot_preacquired"
        try:
            value = await self._redis.get(key)
            if value:
                return UUID(value.decode())
        except Exception:
            pass
        return None

    async def get_minimum_feeder_interval(self) -> int:
        """Get minimum feeder interval across all active tenants.

        Scans for tenant queues and returns the shortest configured interval.
        Ensures responsive scheduling for tenants who need faster polling.

        Returns:
            Minimum interval in seconds across active tenants.
        """
        pattern = "tenant:*:crawl_pending"
        tenant_ids: list[UUID] = []

        try:
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(
                    cursor=cursor, match=pattern, count=100
                )
                for key_bytes in keys:
                    key = key_bytes.decode() if isinstance(key_bytes, bytes) else key_bytes
                    parts = key.split(":")
                    if len(parts) >= 2:
                        try:
                            tenant_ids.append(UUID(parts[1]))
                        except ValueError:
                            continue
                if cursor == 0:
                    break
        except Exception as exc:
            logger.warning(
                "Failed to scan tenant queues for interval calculation",
                extra={"error": str(exc)},
            )
            return self._settings.crawl_feeder_interval_seconds

        if not tenant_ids:
            return self._settings.crawl_feeder_interval_seconds

        min_interval = self._settings.crawl_feeder_interval_seconds

        for tenant_id in tenant_ids:
            try:
                tenant_settings = await self.get_tenant_settings(tenant_id)
                interval = get_crawler_setting(
                    "crawl_feeder_interval_seconds",
                    tenant_settings,
                    default=self._settings.crawl_feeder_interval_seconds,
                )
                min_interval = min(min_interval, interval)
            except Exception:
                continue

        logger.debug(
            "Calculated minimum feeder interval",
            extra={
                "min_interval": min_interval,
                "active_tenants": len(tenant_ids),
                "global_default": self._settings.crawl_feeder_interval_seconds,
            },
        )

        return min_interval

    async def emergency_release_slot(self, job_id: UUID) -> bool:
        """Emergency slot release when normal release path fails.

        Handles the rare dual-failure scenario where both tenant and
        preacquired_tenant_id are None in the crawl task finally block.
        This occurs when:
        1. Early Redis check failed (preacquired_tenant_id = None)
        2. Tenant injection also failed (tenant = None)
        3. Both primary and fallback finally paths are skipped
        4. Slot would leak until TTL expires

        The function reads the slot_preacquired flag from Redis to recover
        the tenant_id and release the slot. Safe because watchdog deletes
        the flag when it releases a slot, so existing flag means slot needs
        release.

        Args:
            job_id: The job identifier to recover slot for.

        Returns:
            True if slot was released, False if no flag found or error.
        """
        try:
            flag_key = f"job:{job_id}:slot_preacquired"
            flag_value = await self._redis.get(flag_key)

            if not flag_value:
                # No flag = no slot to release (watchdog may have handled it)
                return False

            tenant_id = UUID(flag_value.decode())

            # Release slot using centralized Lua script
            await LuaScripts.release_slot(
                self._redis,
                tenant_id,
                self._settings.tenant_worker_semaphore_ttl_seconds,
            )

            # Clear the flag
            await self._redis.delete(flag_key)

            logger.info(
                "Emergency slot release via flag read succeeded",
                extra={
                    "job_id": str(job_id),
                    "tenant_id": str(tenant_id),
                    "reason": "dual_failure_recovery",
                },
            )
            return True

        except Exception as exc:
            # TTL is the last resort if emergency release fails
            logger.warning(
                "Emergency slot release failed - TTL is last resort",
                extra={
                    "job_id": str(job_id),
                    "error": str(exc),
                },
            )
            return False
