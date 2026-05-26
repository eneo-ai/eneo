"""Self-renewing, owner-checked Redis lock (lease).

A plain ``SET NX EX`` lock has two failure modes when the protected operation
can outlive the TTL:

1. The TTL expires mid-operation, so a second worker acquires the lock and runs
   a duplicate operation concurrently.
2. Releasing with a constant value (``DEL`` of the key) can delete a *different*
   holder's lock — the one that acquired it after the original TTL expired.

This lease fixes both by giving each acquisition a unique owner token and
keeping the lock alive with a watchdog that periodically refreshes the TTL while
the operation runs. The TTL therefore acts as a crash-detection window (failover
if the worker dies) rather than a hard cap on operation duration. Refresh and
release are owner-verified via the same Lua scripts used for leader election, so
a holder can never extend or delete another holder's lock.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from uuid import uuid4

from intric.main.logging import get_logger
from intric.worker.redis.lua_scripts import LuaScripts

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = get_logger(__name__)

DEFAULT_LEASE_TTL_SECONDS = 300


@contextlib.asynccontextmanager
async def redis_lease(
    redis_client: "aioredis.Redis",
    key: str,
    *,
    ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    renew_interval_seconds: float | None = None,
) -> AsyncIterator[bool]:
    """Acquire a self-renewing distributed lock for the duration of the block.

    Yields ``True`` if the lock was acquired (a watchdog keeps it alive until the
    block exits), or ``False`` if another holder owns it — in which case the
    caller should skip its work. The lock is always released on exit, but only if
    this acquisition still owns it.

    Args:
        redis_client: Async Redis connection.
        key: Lock key.
        ttl_seconds: Lock expiry; also the failover window if the worker crashes.
        renew_interval_seconds: How often the watchdog refreshes the TTL.
            Defaults to ``ttl_seconds / 3`` so two refreshes can fail before the
            lock expires.
    """
    owner = uuid4().hex
    renew_interval = renew_interval_seconds or ttl_seconds / 3

    acquired = bool(await redis_client.set(key, owner, nx=True, ex=ttl_seconds))
    if not acquired:
        yield False
        return

    async def _watchdog() -> None:
        while True:
            await asyncio.sleep(renew_interval)
            try:
                still_owner = await LuaScripts.refresh_leader_lock(
                    redis_client, key, owner, ttl_seconds
                )
            except Exception as exc:
                # Transient Redis error — keep trying; the lock only lapses if
                # this keeps failing past the TTL (which is the failover we want).
                logger.warning(
                    "Failed to refresh Redis lease, will retry",
                    extra={"lock_key": key, "error": str(exc)},
                )
                continue
            if not still_owner:
                logger.warning(
                    "Lost Redis lease before completion (expired or taken over)",
                    extra={"lock_key": key},
                )
                return

    watchdog = asyncio.create_task(_watchdog())
    try:
        yield True
    finally:
        watchdog.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watchdog
        try:
            await LuaScripts.release_leader_lock(redis_client, key, owner)
        except Exception as exc:
            # Non-critical: the lock will expire on its own.
            logger.debug(
                "Failed to release Redis lease",
                extra={"lock_key": key, "error": str(exc)},
            )
