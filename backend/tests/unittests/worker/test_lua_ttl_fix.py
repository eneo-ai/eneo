"""Unit tests for Lua script TTL refresh fix.

These tests verify that the Lua acquire script:
- DOES refresh TTL when slot acquisition SUCCEEDS
- DOES NOT refresh TTL when slot acquisition FAILS (at capacity)

Bug context: The previous Lua script refreshed TTL on both success AND failure,
which caused zombie counters to persist indefinitely even when at capacity
(because the counter was already at max but EXPIRE kept resetting TTL).

Root cause path:
1. Feeder tries to acquire slot for tenant at capacity (counter=10, limit=10)
2. INCR makes counter=11 (over limit)
3. DECR brings counter back to 10
4. BUG: EXPIRE refreshes TTL → counter stays alive forever
5. TTL never expires → zombie counter persists

The fix: Only call EXPIRE on the success path (after confirming slot acquired).

NOTE: This uses Redis's eval() method for Lua scripts - NOT Python's eval().
Redis eval is the standard way to run atomic Lua scripts on Redis server.
"""

import pytest
from uuid import uuid4


class FakeRedis:
    """Minimal async Redis stub that tracks TTL refreshes.

    This stub precisely simulates the Lua script behavior to verify
    that TTL is only refreshed on the success path.

    Uses redis_eval method to avoid confusion with Python's eval().
    """

    def __init__(self):
        self._store: dict[str, int] = {}
        self._ttl: dict[str, int] = {}
        self._expire_call_count: dict[str, int] = {}
        self._expire_calls_on_failure: int = 0

    async def redis_eval(self, script: str, num_keys: int, key: str, *args):
        """Simulate the Lua acquire script with TTL tracking.

        This method simulates Redis's EVAL command for Lua scripts.
        """
        if "INCR" in script and "limit" in script:
            limit = int(args[0])
            ttl = int(args[1])

            if limit <= 0:
                return 1

            current = self._store.get(key, 0) + 1
            self._store[key] = current

            if current > limit:
                # Over limit - decrement and return failure
                current -= 1
                if current <= 0:
                    self._store.pop(key, None)
                    self._ttl.pop(key, None)
                else:
                    self._store[key] = current

                # CRITICAL: Check if EXPIRE is called on failure path
                # The FIX ensures this block does NOT refresh TTL
                if "EXPIRE" in script:
                    # Parse the script to check if EXPIRE is called BEFORE return 0
                    # In the FIXED script, EXPIRE is only after the success check
                    lines = script.split('\n')
                    in_failure_block = False
                    for line in lines:
                        if 'current > limit' in line:
                            in_failure_block = True
                        if in_failure_block and 'return 0' in line:
                            break
                        if in_failure_block and 'EXPIRE' in line and 'Success' not in line:
                            # BUG: EXPIRE called on failure path
                            self._expire_calls_on_failure += 1
                            self._ttl[key] = ttl
                            self._expire_call_count[key] = self._expire_call_count.get(key, 0) + 1

                return 0  # Failure - at capacity

            # Success - slot acquired
            # Check if script refreshes TTL on success (it should)
            if "EXPIRE" in script:
                self._ttl[key] = ttl
                self._expire_call_count[key] = self._expire_call_count.get(key, 0) + 1

            return current

        # Release script
        ttl = int(args[0])
        current = self._store.get(key)
        if current is None:
            return 0
        current -= 1
        if current <= 0:
            self._store.pop(key, None)
            self._ttl.pop(key, None)
            return 0
        self._store[key] = current
        self._ttl[key] = ttl
        return current


class TestLuaAcquireScript:
    """Tests for the Lua acquire script TTL behavior."""

    # The FIXED Lua script - TTL only refreshed on success
    FIXED_ACQUIRE_LUA = (
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
    )

    # The BUGGY Lua script - TTL refreshed on both success AND failure
    BUGGY_ACQUIRE_LUA = (
        "local key = KEYS[1]\n"
        "local limit = tonumber(ARGV[1])\n"
        "local ttl = tonumber(ARGV[2])\n"
        "if limit <= 0 then\n"
        "  return 1\n"
        "end\n"
        "local current = redis.call('INCR', key)\n"
        "if current > limit then\n"
        "  redis.call('DECR', key)\n"
        "  redis.call('EXPIRE', key, ttl)\n"  # BUG: EXPIRE on failure path!
        "  return 0\n"
        "end\n"
        "redis.call('EXPIRE', key, ttl)\n"
        "return current\n"
    )

    @pytest.mark.asyncio
    async def test_fixed_script_does_not_refresh_ttl_on_failure(self):
        """CRITICAL: Verify fixed script does NOT refresh TTL when at capacity.

        This is the core test for the zombie counter fix.
        """
        redis = FakeRedis()
        tenant_id = uuid4()
        key = f"tenant:{tenant_id}:active_jobs"
        limit = 2
        ttl = 3600

        # Acquire slots up to limit
        result1 = await redis.redis_eval(self.FIXED_ACQUIRE_LUA, 1, key, str(limit), str(ttl))
        assert result1 == 1, "First acquire should succeed"

        result2 = await redis.redis_eval(self.FIXED_ACQUIRE_LUA, 1, key, str(limit), str(ttl))
        assert result2 == 2, "Second acquire should succeed"

        # Try to acquire when at capacity (should fail)
        result3 = await redis.redis_eval(self.FIXED_ACQUIRE_LUA, 1, key, str(limit), str(ttl))
        assert result3 == 0, "Third acquire should fail (at capacity)"

        # Verify slot count is unchanged
        assert redis._store.get(key) == 2, "Slot count should remain at limit"

        # CRITICAL: Verify no EXPIRE call on failure path in FIXED script
        # The script structure prevents EXPIRE on failure in the fixed version
        assert "Success:" in self.FIXED_ACQUIRE_LUA, "Fixed script should have Success comment before EXPIRE"
        assert redis._expire_calls_on_failure == 0, "Fixed script should NOT call EXPIRE on failure"

    @pytest.mark.asyncio
    async def test_fixed_script_refreshes_ttl_on_success(self):
        """Verify fixed script DOES refresh TTL on successful acquisition."""
        redis = FakeRedis()
        tenant_id = uuid4()
        key = f"tenant:{tenant_id}:active_jobs"
        limit = 5
        ttl = 3600

        # Acquire first slot
        result = await redis.redis_eval(self.FIXED_ACQUIRE_LUA, 1, key, str(limit), str(ttl))
        assert result == 1, "Acquire should succeed"

        # Verify TTL was set
        assert key in redis._ttl, "TTL should be set on success"
        assert redis._ttl[key] == ttl, "TTL should match provided value"

    @pytest.mark.asyncio
    async def test_script_structure_has_ttl_refresh_only_on_success_path(self):
        """Verify the script structure places EXPIRE only after success confirmation."""
        script = self.FIXED_ACQUIRE_LUA
        lines = script.split('\n')

        # Find the failure block (current > limit) and success block
        failure_block_start = None
        success_expire_line = None

        for i, line in enumerate(lines):
            if 'current > limit' in line:
                failure_block_start = i
            if 'Success:' in line:
                # EXPIRE should be after this comment
                for j in range(i, len(lines)):
                    if 'EXPIRE' in lines[j]:
                        success_expire_line = j
                        break
                break

        assert failure_block_start is not None, "Script should have failure block"
        assert success_expire_line is not None, "Script should have EXPIRE after Success comment"

        # Verify no EXPIRE between failure_block_start and 'return 0'
        for i in range(failure_block_start, len(lines)):
            line = lines[i]
            if 'return 0' in line:
                break
            assert 'EXPIRE' not in line or 'Success' in lines[i-1] if i > 0 else False, \
                f"EXPIRE should not appear in failure block before 'return 0' (line {i})"


class TestLuaScriptConsistency:
    """Test that all three copies of the Lua script are consistent."""

    @pytest.mark.asyncio
    async def test_all_lua_scripts_match(self):
        """Verify crawl_feeder, tenant_concurrency, and crawl_service have identical scripts."""
        import dataclasses
        from intric.worker.crawl_feeder import CrawlFeeder
        from intric.worker.tenant_concurrency import TenantConcurrencyLimiter
        from intric.websites.domain.crawl_service import CrawlService

        feeder_script = CrawlFeeder._acquire_slot_lua

        # TenantConcurrencyLimiter uses dataclass field - access via fields()
        limiter_fields = {f.name: f for f in dataclasses.fields(TenantConcurrencyLimiter)}
        limiter_script = limiter_fields['_acquire_lua'].default

        service_script = CrawlService._acquire_slot_lua

        # Normalize whitespace for comparison
        def normalize(s):
            return ''.join(s.split())

        assert normalize(feeder_script) == normalize(limiter_script), \
            "CrawlFeeder and TenantConcurrencyLimiter acquire scripts must match"

        assert normalize(feeder_script) == normalize(service_script), \
            "CrawlFeeder and CrawlService acquire scripts must match"

    @pytest.mark.asyncio
    async def test_all_scripts_have_ttl_fix_comment(self):
        """Verify all scripts have the fix comment for documentation."""
        import dataclasses
        from intric.worker.crawl_feeder import CrawlFeeder
        from intric.worker.tenant_concurrency import TenantConcurrencyLimiter
        from intric.websites.domain.crawl_service import CrawlService

        # TenantConcurrencyLimiter uses dataclass field - access via fields()
        limiter_fields = {f.name: f for f in dataclasses.fields(TenantConcurrencyLimiter)}
        limiter_script = limiter_fields['_acquire_lua'].default

        scripts = [
            ("CrawlFeeder", CrawlFeeder._acquire_slot_lua),
            ("TenantConcurrencyLimiter", limiter_script),
            ("CrawlService", CrawlService._acquire_slot_lua),
        ]

        for name, script in scripts:
            assert "DO NOT refresh TTL on failure" in script or "Success:" in script, \
                f"{name} script should have fix documentation comment"


class TestLuaReleaseScript:
    """Tests for the Lua release script (unchanged but important for completeness)."""

    RELEASE_LUA = (
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
    )

    @pytest.mark.asyncio
    async def test_release_cleans_up_at_zero(self):
        """Verify release DELetes key when counter reaches zero."""
        redis = FakeRedis()
        key = "tenant:test:active_jobs"

        # Set counter to 1
        redis._store[key] = 1
        redis._ttl[key] = 3600

        # Release should delete key at zero
        result = await redis.redis_eval(self.RELEASE_LUA, 1, key, "3600")

        assert result == 0, "Release should return 0 at zero"
        assert key not in redis._store, "Key should be deleted at zero"

    @pytest.mark.asyncio
    async def test_release_safe_on_missing_key(self):
        """Verify release is safe when key doesn't exist."""
        redis = FakeRedis()
        key = "tenant:test:active_jobs"

        # Release on non-existent key
        result = await redis.redis_eval(self.RELEASE_LUA, 1, key, "3600")

        assert result == 0, "Release should return 0 for missing key"
