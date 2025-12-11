"""Per-tenant concurrency limiting for background workers."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, Tuple
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
    circuit_break_seconds: int = 30
    local_ttl_seconds: int = 120
    local_limit: int | None = None
    # FIX: Only refresh TTL on SUCCESS path - prevents zombie counters when acquire fails
    # Bug: Previous version refreshed TTL on both success AND failure, keeping counter alive forever
    _acquire_lua: str = field(init=False, default=(
        "local key = KEYS[1]\n"
        "local limit = tonumber(ARGV[1])\n"
        "local ttl = tonumber(ARGV[2])\n"
        "if limit <= 0 then\n"
        "  return 1\n"
        "end\n"
        "local current = redis.call('INCR', key)\n"
        "if current > limit then\n"
        "  local after_decr = redis.call('DECR', key)\n"
        "  if after_decr <= 0 then\n"
        "    redis.call('DEL', key)\n"
        "  end\n"
        "  -- DO NOT refresh TTL on failure - let counter expire naturally if unused\n"
        "  return 0\n"
        "end\n"
        "-- Success: refresh TTL only after confirming slot acquired\n"
        "redis.call('EXPIRE', key, ttl)\n"
        "return current\n"
    ))
    # NOTE: This script is duplicated in crawl_tasks.py as _RELEASE_SLOT_LUA
    # Keep both in sync if making changes
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
    _circuit_open_until: float = field(init=False, default=0.0, repr=False)
    _local_counts: Dict[UUID, Tuple[int, float]] = field(
        init=False, default_factory=dict, repr=False
    )
    _lock: asyncio.Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()
        if self.local_limit is None or self.local_limit <= 0:
            self.local_limit = self.max_concurrent
        if self.circuit_break_seconds <= 0:
            self.circuit_break_seconds = 30
        if self.local_ttl_seconds <= 0:
            self.local_ttl_seconds = 120

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _key(self, tenant_id: UUID) -> str:
        return f"tenant:{tenant_id}:active_jobs"

    def _is_circuit_open(self, now: float) -> bool:
        return bool(self._circuit_open_until and now < self._circuit_open_until)

    async def _open_circuit(self, now: float) -> None:
        self._circuit_open_until = now + self.circuit_break_seconds

    async def _close_circuit(self) -> None:
        self._circuit_open_until = 0.0

    def _cleanup_expired(self, now: float) -> None:
        if not self._local_counts:
            return
        expired = [
            tenant_id
            for tenant_id, (_, expires_at) in self._local_counts.items()
            if expires_at <= now
        ]
        for tenant_id in expired:
            self._local_counts.pop(tenant_id, None)

    async def _fallback_acquire(self, tenant_id: UUID, now: float) -> bool:
        if not self.local_limit or self.local_limit <= 0:
            return False

        async with self._lock:
            self._cleanup_expired(now)
            current, _ = self._local_counts.get(
                tenant_id, (0, now + self.local_ttl_seconds)
            )

            if current >= self.local_limit:
                logger.warning(
                    "Tenant concurrency limit reached (fallback mode)",
                    extra={
                        "tenant_id": str(tenant_id),
                        "max_concurrent": self.local_limit,
                        "mode": "local_fallback",
                        "metric_name": "tenant.limiter.rejected",
                        "metric_value": 1,
                    },
                )
                return False

            self._local_counts[tenant_id] = (
                current + 1,
                now + self.local_ttl_seconds,
            )

            logger.warning(
                "Tenant semaphore acquired via local fallback",
                extra={
                    "tenant_id": str(tenant_id),
                    "active": current + 1,
                    "max_concurrent": self.local_limit,
                    "mode": "local_fallback",
                    "metric_name": "tenant.limiter.fallback_acquired",
                    "metric_value": 1,
                },
            )
            return True

    async def _fallback_release(self, tenant_id: UUID, now: float) -> None:
        async with self._lock:
            self._cleanup_expired(now)
            if tenant_id not in self._local_counts:
                return

            current, expires_at = self._local_counts[tenant_id]
            if current <= 1:
                self._local_counts.pop(tenant_id, None)
            else:
                self._local_counts[tenant_id] = (current - 1, expires_at)

    @staticmethod
    def _mark_fallback_on_task(tenant_id: UUID) -> None:
        task = asyncio.current_task()
        if not task:
            return

        fallback_map: Dict[UUID, bool] | None = getattr(
            task, "_tenant_limiter_fallback", None
        )
        if fallback_map is None:
            fallback_map = {}
            setattr(task, "_tenant_limiter_fallback", fallback_map)

        fallback_map[tenant_id] = True

    @staticmethod
    def _consume_task_fallback_flag(tenant_id: UUID) -> bool:
        task = asyncio.current_task()
        if not task:
            return False

        fallback_map: Dict[UUID, bool] | None = getattr(
            task, "_tenant_limiter_fallback", None
        )
        if not fallback_map:
            return False

        used = fallback_map.pop(tenant_id, False)
        if not fallback_map:
            try:
                delattr(task, "_tenant_limiter_fallback")
            except AttributeError:
                pass
        return used

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def acquire(self, tenant_id: UUID) -> bool:
        """Attempt to acquire a slot for the given tenant."""

        if self.max_concurrent <= 0:
            # Limit disabled – always allow execution
            return True

        key = self._key(tenant_id)

        now = time.monotonic()
        if self._is_circuit_open(now):
            allowed = await self._fallback_acquire(tenant_id, now)
            if allowed:
                self._mark_fallback_on_task(tenant_id)
            return allowed

        try:
            result = await self.redis.eval(
                self._acquire_lua,
                1,
                key,
                str(self.max_concurrent),
                str(self.ttl_seconds),
            )
            await self._close_circuit()

            if isinstance(result, bytes):
                result = int(result)

            allowed = bool(result and int(result) > 0)
            if not allowed:
                logger.warning(
                    "Per-tenant concurrency limit reached",
                    extra={
                        "tenant_id": str(tenant_id),
                        "max_concurrent": self.max_concurrent,
                        "mode": "redis",
                        "metric_name": "tenant.limiter.rejected",
                        "metric_value": 1,
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
                    "mode": "redis",
                },
            )
            await self._open_circuit(now)
            allowed = await self._fallback_acquire(tenant_id, now)
            if allowed:
                self._mark_fallback_on_task(tenant_id)
            return allowed

    async def release(self, tenant_id: UUID) -> None:
        """Release a previously acquired slot for the given tenant.

        This method implements two distinct release paths:
        1. Fallback path: If the slot was acquired via local in-memory fallback,
           release it from local memory only. No Redis interaction needed.
        2. Redis path: If the slot was acquired via Redis, we MUST attempt to
           release it from Redis, regardless of the circuit breaker's state.
           The breaker's state is for acquisition, not for releasing already-held slots.
        """

        if self.max_concurrent <= 0:
            return

        now = time.monotonic()
        used_fallback = self._consume_task_fallback_flag(tenant_id)

        # Path 1: The slot was acquired using the local in-memory fallback.
        # We only need to release it from local memory. No Redis interaction needed.
        if used_fallback:
            await self._fallback_release(tenant_id, now)
            return

        # Path 2: The slot was acquired via Redis. We MUST attempt to release it
        # from Redis, regardless of the circuit breaker's state. The breaker's
        # state is for acquisition, not for releasing an already-held slot.
        # If we don't release here, we leak the Redis semaphore until TTL expires.
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
                "Failed to release tenant semaphore, re-opening circuit",
                extra={
                    "tenant_id": str(tenant_id),
                    "error": str(exc),
                    "mode": "redis",
                },
            )
            await self._open_circuit(now)
