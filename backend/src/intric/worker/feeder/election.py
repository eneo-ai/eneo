"""Leader election for singleton feeder using Redis distributed lock.

Ensures only ONE feeder runs across all worker processes.
Uses Redis SET NX with TTL for automatic failover if leader crashes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from intric.main.logging import get_logger
from intric.worker.redis.lua_scripts import LuaScripts

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = get_logger(__name__)


class LeaderElection:
    """Redis-based leader election for singleton services.

    Uses atomic SET NX (only-if-not-exists) with TTL expiry.
    Leader must periodically refresh the lock to maintain leadership.

    Args:
        redis_client: Async Redis connection.
        worker_id: Unique identifier for this worker instance.
        lock_key: Redis key for the leader lock.
        ttl_seconds: Lock expiry time (automatic failover threshold).
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        worker_id: str,
        lock_key: str = "crawl_feeder:leader",
        ttl_seconds: int = 30,
    ) -> None:
        self._redis = redis_client
        self._worker_id = worker_id
        self._lock_key = lock_key
        self._ttl = ttl_seconds

    async def try_acquire(self) -> bool:
        """Attempt to acquire leadership.

        Returns:
            True if this instance became leader, False if another holds the lock.
        """
        try:
            acquired = await self._redis.set(
                self._lock_key,
                self._worker_id,
                nx=True,
                ex=self._ttl,
            )
            return bool(acquired)
        except Exception as exc:
            logger.warning(
                "Failed to acquire leader lock",
                extra={"error": str(exc), "lock_key": self._lock_key},
            )
            return False

    async def refresh(self) -> bool:
        """Refresh lock TTL if still the owner.

        Uses Lua script for atomic ownership verification.
        Prevents stale process from extending another's lock.

        Returns:
            True if lock was refreshed (still leader), False otherwise.
        """
        try:
            return await LuaScripts.refresh_leader_lock(
                self._redis,
                self._lock_key,
                self._worker_id,
                self._ttl,
            )
        except Exception as exc:
            logger.debug(
                "Failed to refresh leader lock",
                extra={"error": str(exc), "lock_key": self._lock_key},
            )
            return False

    async def release(self) -> bool:
        """Release leadership if still the owner.

        Returns:
            True if lock was released, False if not owner or error.
        """
        try:
            return await LuaScripts.release_leader_lock(
                self._redis,
                self._lock_key,
                self._worker_id,
            )
        except Exception as exc:
            logger.debug(
                "Failed to release leader lock",
                extra={"error": str(exc), "lock_key": self._lock_key},
            )
            return False
