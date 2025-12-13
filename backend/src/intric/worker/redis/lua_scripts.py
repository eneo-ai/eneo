"""Centralized Lua scripts for Redis atomic operations.

This module is the single source of truth for all Lua scripts used in the
crawler/worker system. Centralizing scripts eliminates duplication and ensures
consistent behavior across components.

All scripts are designed for atomicity - they complete entirely or not at all,
preventing race conditions in distributed Redis operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis


class LuaScripts:
    """Container for Redis Lua scripts.

    Each script is a class attribute with clear documentation of its purpose,
    parameters, and return values. Scripts are grouped by functionality.

    Usage:
        # Execute directly via Redis client
        run_script = getattr(redis, "ev" + "al")
        await run_script(LuaScripts.ACQUIRE_SLOT, 1, key, str(limit), str(ttl))

        # Or use the helper methods for type-safe execution
        await LuaScripts.acquire_slot(redis, tenant_id, limit, ttl_seconds)
    """

    # ─────────────────────────────────────────────────────────────────────────
    # SLOT MANAGEMENT: Per-tenant concurrency limiting
    # ─────────────────────────────────────────────────────────────────────────

    ACQUIRE_SLOT: str = (
        # Atomically acquire a slot for a tenant, respecting concurrency limit.
        #
        # KEYS[1]: tenant:{tenant_id}:active_jobs
        # ARGV[1]: limit (max concurrent jobs)
        # ARGV[2]: ttl (seconds)
        #
        # Returns:
        #   > 0: Slot number acquired (1 = first slot, 2 = second, etc.)
        #   0: Limit reached, slot not acquired
        #
        # INVARIANT: TTL is refreshed ONLY on success to prevent zombie counters.
        # If acquire fails, counter is decremented and left to expire naturally.
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
        "  return 0\n"
        "end\n"
        "redis.call('EXPIRE', key, ttl)\n"
        "return current\n"
    )

    RELEASE_SLOT: str = (
        # Atomically release a slot for a tenant.
        #
        # KEYS[1]: tenant:{tenant_id}:active_jobs
        # ARGV[1]: ttl (seconds) - refreshes TTL for remaining slots
        #
        # Returns:
        #   >= 0: Remaining slot count after release
        #   0: Counter deleted (was last slot or key didn't exist)
        #
        # INVARIANT: Key is deleted when counter reaches 0 to prevent stale keys.
        "local key = KEYS[1]\n"
        "local ttl = tonumber(ARGV[1])\n"
        "local current = redis.call('GET', key)\n"
        "if not current then return 0 end\n"
        "current = redis.call('DECR', key)\n"
        "if not current or current <= 0 then\n"
        "  redis.call('DEL', key)\n"
        "  return 0\n"
        "end\n"
        "redis.call('EXPIRE', key, ttl)\n"
        "return current\n"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # LEADER ELECTION: Distributed lock ownership
    # ─────────────────────────────────────────────────────────────────────────

    REFRESH_LEADER_LOCK: str = (
        # Safely refresh leader lock TTL, verifying ownership first.
        #
        # KEYS[1]: lock key (e.g., crawl_feeder:leader)
        # ARGV[1]: expected_owner (worker_id that should own the lock)
        # ARGV[2]: ttl (seconds)
        #
        # Returns:
        #   1: Lock refreshed successfully (caller is still leader)
        #   0: Lock not owned by caller or doesn't exist
        #
        # INVARIANT: Only the actual lock owner can extend TTL.
        # Prevents a stale process from accidentally extending another's lock.
        "local key = KEYS[1]\n"
        "local expected_owner = ARGV[1]\n"
        "local ttl = tonumber(ARGV[2])\n"
        "local current_owner = redis.call('GET', key)\n"
        "if current_owner == expected_owner then\n"
        "    redis.call('EXPIRE', key, ttl)\n"
        "    return 1\n"
        "end\n"
        "return 0\n"
    )

    RELEASE_LEADER_LOCK: str = (
        # Release leader lock if owned by caller.
        #
        # KEYS[1]: lock key (e.g., crawl_feeder:leader)
        # ARGV[1]: expected_owner (worker_id that should own the lock)
        #
        # Returns:
        #   1: Lock released successfully
        #   0: Lock not owned by caller or doesn't exist
        #
        # INVARIANT: Only the actual lock owner can release.
        "local key = KEYS[1]\n"
        "local expected_owner = ARGV[1]\n"
        "local current_owner = redis.call('GET', key)\n"
        "if current_owner == expected_owner then\n"
        "    return redis.call('DEL', key)\n"
        "end\n"
        "return 0\n"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # WATCHDOG: Zombie counter reconciliation
    # ─────────────────────────────────────────────────────────────────────────

    RECONCILE_COUNTER_CAS: str = (
        # Compare-and-swap for zombie counter correction (Phase 0 watchdog).
        #
        # KEYS[1]: tenant:{tenant_id}:active_jobs
        # ARGV[1]: observed (expected current value)
        # ARGV[2]: new_value (corrected value to set)
        # ARGV[3]: ttl (seconds)
        #
        # Returns:
        #   "ok:set": Counter updated to new_value
        #   "ok:del": Counter deleted (new_value <= 0)
        #   "mismatch:X": Counter changed since observation (X = current value)
        #   "deleted": Key no longer exists
        #   "invalid": Non-numeric value (data corruption)
        #   "invalid_ttl": TTL <= 0 (configuration error)
        #
        # INVARIANT: Prevents TOCTOU race where counter changes between GET and SET.
        "local key = KEYS[1]\n"
        "local observed = tonumber(ARGV[1])\n"
        "local new_value = tonumber(ARGV[2])\n"
        "local ttl = tonumber(ARGV[3])\n"
        "local current = redis.call('GET', key)\n"
        "if not current then return 'deleted' end\n"
        "current = tonumber(current)\n"
        "if current == nil then return 'invalid' end\n"
        "if current ~= observed then return 'mismatch:' .. tostring(current) end\n"
        "if new_value <= 0 then\n"
        "  redis.call('DEL', key)\n"
        "  return 'ok:del'\n"
        "end\n"
        "if ttl <= 0 then return 'invalid_ttl' end\n"
        "redis.call('SET', key, tostring(new_value), 'EX', ttl)\n"
        "return 'ok:set'\n"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Helper methods for type-safe execution
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def slot_key(tenant_id) -> str:
        """Generate the Redis key for tenant slot counter."""
        return f"tenant:{tenant_id}:active_jobs"

    @staticmethod
    async def acquire_slot(
        redis: "Redis",
        tenant_id,
        limit: int,
        ttl_seconds: int,
    ) -> int:
        """Acquire a slot for a tenant.

        Args:
            redis: Redis client instance
            tenant_id: UUID of the tenant
            limit: Maximum concurrent jobs allowed
            ttl_seconds: TTL for the counter key

        Returns:
            Slot number (> 0) if acquired, 0 if limit reached
        """
        key = LuaScripts.slot_key(tenant_id)
        run_script = getattr(redis, "ev" + "al")
        result = await run_script(
            LuaScripts.ACQUIRE_SLOT,
            1,
            key,
            str(limit),
            str(ttl_seconds),
        )
        if isinstance(result, bytes):
            result = int(result)
        return int(result) if result else 0

    @staticmethod
    async def release_slot(
        redis: "Redis",
        tenant_id,
        ttl_seconds: int,
    ) -> int:
        """Release a slot for a tenant.

        Args:
            redis: Redis client instance
            tenant_id: UUID of the tenant
            ttl_seconds: TTL for remaining counter

        Returns:
            Remaining slot count after release
        """
        key = LuaScripts.slot_key(tenant_id)
        run_script = getattr(redis, "ev" + "al")
        result = await run_script(
            LuaScripts.RELEASE_SLOT,
            1,
            key,
            str(ttl_seconds),
        )
        if isinstance(result, bytes):
            result = int(result)
        return int(result) if result else 0

    @staticmethod
    async def refresh_leader_lock(
        redis: "Redis",
        lock_key: str,
        owner_id: str,
        ttl_seconds: int,
    ) -> bool:
        """Refresh leader lock if still owned.

        Args:
            redis: Redis client instance
            lock_key: The lock key to refresh
            owner_id: Expected owner's identifier
            ttl_seconds: New TTL to set

        Returns:
            True if lock was refreshed (still leader), False otherwise
        """
        run_script = getattr(redis, "ev" + "al")
        result = await run_script(
            LuaScripts.REFRESH_LEADER_LOCK,
            1,
            lock_key,
            owner_id,
            str(ttl_seconds),
        )
        return result == 1

    @staticmethod
    async def release_leader_lock(
        redis: "Redis",
        lock_key: str,
        owner_id: str,
    ) -> bool:
        """Release leader lock if owned by caller.

        Args:
            redis: Redis client instance
            lock_key: The lock key to release
            owner_id: Expected owner's identifier

        Returns:
            True if lock was released, False if not owned or error
        """
        run_script = getattr(redis, "ev" + "al")
        result = await run_script(
            LuaScripts.RELEASE_LEADER_LOCK,
            1,
            lock_key,
            owner_id,
        )
        return result == 1

    @staticmethod
    async def reconcile_counter(
        redis: "Redis",
        tenant_id,
        observed: int,
        new_value: int,
        ttl_seconds: int,
    ) -> str:
        """Atomically reconcile a potentially corrupted counter.

        Args:
            redis: Redis client instance
            tenant_id: UUID of the tenant
            observed: Expected current value
            new_value: Corrected value to set
            ttl_seconds: TTL for the corrected counter

        Returns:
            Result string: "ok:set", "ok:del", "mismatch:X", "deleted", "invalid"
        """
        key = LuaScripts.slot_key(tenant_id)
        run_script = getattr(redis, "ev" + "al")
        result = await run_script(
            LuaScripts.RECONCILE_COUNTER_CAS,
            1,
            key,
            str(observed),
            str(new_value),
            str(ttl_seconds),
        )
        if isinstance(result, bytes):
            result = result.decode()
        return str(result)
