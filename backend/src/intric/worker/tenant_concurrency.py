"""Per-tenant concurrency limiting for background workers."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import redis.asyncio as aioredis

from intric.main.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class TenantConcurrencyLimiter:
    """Redis-backed semaphore that enforces per-tenant concurrency limits.

    The limiter uses Redis atomic increment/decrement operations to guarantee
    that no more than ``max_concurrent`` tasks per tenant execute in parallel.
    A TTL ensures counters are eventually cleaned up even if a worker crashes
    before releasing the semaphore.
    """

    redis: aioredis.Redis
    max_concurrent: int
    ttl_seconds: int
    _acquire_lua: str = field(init=False, default=(
        "local key = KEYS[1]\n"
        "local limit = tonumber(ARGV[1])\n"
        "local ttl = tonumber(ARGV[2])\n"
        "if limit <= 0 then\n"
        "  return 1\n"
        "end\n"
        "local current = redis.call('INCR', key)\n"
        "redis.call('EXPIRE', key, ttl)\n"
        "if current > limit then\n"
        "  local after_decr = redis.call('DECR', key)\n"
        "  if after_decr <= 0 then\n"
        "    redis.call('DEL', key)\n"
        "  else\n"
        "    redis.call('EXPIRE', key, ttl)\n"
        "  end\n"
        "  return 0\n"
        "end\n"
        "return current\n"
    ))
    _release_lua: str = field(init=False, default=(
        "local key = KEYS[1]\n"
        "local ttl = tonumber(ARGV[1])\n"
        "local current = redis.call('GET', key)\n"
        "if not current then\n"
        "  return 0\n"
        "end\n"
        "current = redis.call('DECR', key)\n"
        "if not current or current <= 0 then\n"
        "  redis.call('DEL', key)\n"
        "  return 0\n"
        "end\n"
        "redis.call('EXPIRE', key, ttl)\n"
        "return current\n"
    ))

    def _key(self, tenant_id: UUID) -> str:
        return f"tenant:{tenant_id}:active_jobs"

    async def acquire(self, tenant_id: UUID) -> bool:
        """Attempt to acquire a slot for the given tenant."""

        if self.max_concurrent <= 0:
            # Limit disabled – always allow execution
            return True

        key = self._key(tenant_id)

        try:
            result = await self.redis.eval(
                self._acquire_lua,
                1,
                key,
                str(self.max_concurrent),
                str(self.ttl_seconds),
            )

            if isinstance(result, bytes):
                result = int(result)

            allowed = bool(result and int(result) > 0)
            if not allowed:
                logger.debug(
                    "Per-tenant concurrency limit reached",
                    extra={
                        "tenant_id": str(tenant_id),
                        "max_concurrent": self.max_concurrent,
                    },
                )
            return allowed
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                "Failed to acquire tenant semaphore",
                extra={
                    "tenant_id": str(tenant_id),
                    "max_concurrent": self.max_concurrent,
                    "error": str(exc),
                },
            )
            # Fail open to avoid blocking jobs if Redis is unavailable
            return True

    async def release(self, tenant_id: UUID) -> None:
        """Release a previously acquired slot for the given tenant."""

        if self.max_concurrent <= 0:
            return

        key = self._key(tenant_id)

        try:
            await self.redis.eval(
                self._release_lua,
                1,
                key,
                str(self.ttl_seconds),
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to release tenant semaphore",
                extra={
                    "tenant_id": str(tenant_id),
                    "error": str(exc),
                },
            )
