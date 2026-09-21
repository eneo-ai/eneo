"""Owner-checked Redis lease operations.

Crawler admission and execution state live in PostgreSQL. Redis is only the
transport and still provides leases for unrelated singleton maintenance work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis


class LuaScripts:
    """Atomic operations used by the self-renewing Redis lease."""

    REFRESH_OWNED_LOCK = (
        "local current_owner = redis.call('GET', KEYS[1])\n"
        "if current_owner == ARGV[1] then\n"
        "    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))\n"
        "    return 1\n"
        "end\n"
        "return 0\n"
    )

    RELEASE_OWNED_LOCK = (
        "local current_owner = redis.call('GET', KEYS[1])\n"
        "if current_owner == ARGV[1] then\n"
        "    return redis.call('DEL', KEYS[1])\n"
        "end\n"
        "return 0\n"
    )

    @staticmethod
    async def refresh_owned_lock(
        redis: "Redis",
        lock_key: str,
        owner_id: str,
        ttl_seconds: int,
    ) -> bool:
        run_script = getattr(redis, "ev" + "al")
        result = await run_script(
            LuaScripts.REFRESH_OWNED_LOCK,
            1,
            lock_key,
            owner_id,
            str(ttl_seconds),
        )
        return result == 1

    @staticmethod
    async def release_owned_lock(
        redis: "Redis",
        lock_key: str,
        owner_id: str,
    ) -> bool:
        run_script = getattr(redis, "ev" + "al")
        result = await run_script(
            LuaScripts.RELEASE_OWNED_LOCK,
            1,
            lock_key,
            owner_id,
        )
        return result == 1
