"""Self-renewing, owner-checked Redis lock (lease).

A plain ``SET NX EX`` lock has two failure modes when the protected operation
can outlive the TTL:

1. The TTL expires mid-operation, so a second worker acquires the lock and runs
   a duplicate operation concurrently.
2. Releasing with a constant value (``DEL`` of the key) can delete a *different*
   holder's lock — the one that acquired it after the original TTL expired.

This lease gives each acquisition a unique owner token and keeps the lock alive
with a watchdog that periodically refreshes the TTL while the operation runs.
The TTL therefore acts as a crash-detection window (failover if the worker dies)
rather than a hard cap on operation duration. Refresh and release are
owner-verified via the same Lua scripts used for leader election, so a holder can
never extend or delete another holder's lock.

If the watchdog loses the lease, it cancels the task running the protected block.
That cancellation is cooperative and best-effort: full write-side exclusion after
process pauses still requires fencing tokens at the persistence boundary.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from time import monotonic
from typing import TYPE_CHECKING
from uuid import uuid4

from eneo.main.logging import get_logger
from eneo.worker.redis.lua_scripts import LuaScripts

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
    refresh_timeout_seconds: float | None = None,
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
        refresh_timeout_seconds: Per-refresh Redis call timeout. Defaults to
            ``min(renew_interval_seconds, 10)`` so a hung refresh cannot hide
            an expired lease indefinitely.
    """
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")

    owner = uuid4().hex
    renew_interval = (
        renew_interval_seconds
        if renew_interval_seconds is not None
        else ttl_seconds / 3
    )
    if renew_interval <= 0:
        raise ValueError("renew_interval_seconds must be positive")

    refresh_timeout = (
        refresh_timeout_seconds
        if refresh_timeout_seconds is not None
        else min(renew_interval, 10.0)
    )
    if refresh_timeout <= 0:
        raise ValueError("refresh_timeout_seconds must be positive")

    acquired = bool(await redis_client.set(key, owner, nx=True, ex=ttl_seconds))
    if not acquired:
        yield False
        return

    owner_task = asyncio.current_task()
    last_confirmed_owner_at = monotonic()

    def _cancel_owner(reason: str) -> None:
        logger.warning(reason, extra={"lock_key": key})
        if owner_task is not None and not owner_task.done():
            owner_task.cancel(reason)

    async def _watchdog() -> None:
        nonlocal last_confirmed_owner_at

        while True:
            await asyncio.sleep(renew_interval)
            try:
                still_owner = await asyncio.wait_for(
                    LuaScripts.refresh_leader_lock(
                        redis_client, key, owner, ttl_seconds
                    ),
                    timeout=refresh_timeout,
                )
            except Exception as exc:
                # Transient Redis error — keep trying; the lock only lapses if
                # this keeps failing past the TTL (which is the failover we want).
                seconds_since_confirmed = monotonic() - last_confirmed_owner_at
                if seconds_since_confirmed >= ttl_seconds:
                    _cancel_owner(
                        "Lost Redis lease before completion "
                        "(ownership could not be confirmed within TTL)"
                    )
                    return

                logger.warning(
                    "Failed to refresh Redis lease, will retry",
                    extra={
                        "lock_key": key,
                        "error": str(exc),
                        "seconds_since_confirmed": seconds_since_confirmed,
                    },
                )
                continue
            if not still_owner:
                _cancel_owner(
                    "Lost Redis lease before completion (expired or taken over)",
                )
                return
            last_confirmed_owner_at = monotonic()

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
