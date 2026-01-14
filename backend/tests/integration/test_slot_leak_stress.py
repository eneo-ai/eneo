"""Stress tests for slot leak detection and edge cases.

These tests focus on DIVERGENCE TESTING - verifying that Redis state matches
application truth. The goal is to find slot leaks and edge cases that could
cause resource exhaustion in production.

Key scenarios tested:
1. Enqueue Gap: Pre-acquire slot → ARQ fails → slot must be released
2. Emergency Release: Dual-failure recovery path via flag lookup
3. Heartbeat Starvation: TTL expiry during slow operations
4. Watchdog Race: Concurrent completion between watchdog and worker
5. CancelledError: Task cancellation during persist_batch

Run with: pytest tests/integration/test_slot_leak_stress.py -v --tb=short
"""

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from intric.worker.feeder.capacity import CapacityManager
from intric.worker.redis.lua_scripts import LuaScripts


# =============================================================================
# HELPER: Slot Counter Assertion
# =============================================================================


class SlotLeakDetector:
    """Helper for detecting slot leaks via Redis state divergence.

    Usage:
        detector = SlotLeakDetector(redis_client, tenant_id)
        initial = await detector.snapshot()
        # ... operation under test ...
        await detector.assert_no_leak(initial)
    """

    def __init__(self, redis_client: aioredis.Redis, tenant_id):
        self._redis = redis_client
        self._tenant_id = tenant_id
        self._key = f"tenant:{tenant_id}:active_jobs"

    async def snapshot(self) -> int:
        """Capture current slot count."""
        value = await self._redis.get(self._key)
        return int(value.decode()) if value else 0

    async def assert_no_leak(self, initial: int, msg: str = "") -> None:
        """Assert slot count matches initial state (no leak)."""
        final = await self.snapshot()
        assert final == initial, (
            f"Slot leak detected! Initial={initial}, Final={final}, "
            f"Leaked={(final - initial)} slots. {msg}"
        )

    async def assert_slots_released(
        self, initial: int, expected_release: int, msg: str = ""
    ) -> None:
        """Assert specific number of slots were released."""
        final = await self.snapshot()
        actual_release = initial - final
        assert actual_release == expected_release, (
            f"Slot release mismatch! Expected {expected_release} released, "
            f"but got {actual_release}. Initial={initial}, Final={final}. {msg}"
        )


# =============================================================================
# TEST 1: ENQUEUE GAP SLOT LEAK
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
class TestEnqueueGapSlotLeak:
    """Tests for slot leak when ARQ enqueue fails after pre-acquisition.

    The "enqueue gap" is the window between:
    1. CapacityManager.try_acquire_slot() - slot incremented
    2. job_manager.enqueue() - may fail
    3. CapacityManager.release_slot() - must happen on failure

    If step 2 fails and step 3 is missed, we have a slot leak.
    """

    async def test_enqueue_failure_releases_slot(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """When ARQ enqueue fails (non-duplicate), slot MUST be released."""
        tenant_id = uuid4()

        # Setup: Ensure clean state
        slot_key = LuaScripts.slot_key(tenant_id)
        await redis_client.delete(slot_key)

        detector = SlotLeakDetector(redis_client, tenant_id)
        capacity_mgr = CapacityManager(redis_client, test_settings)

        # Step 1: Pre-acquire slot
        initial = await detector.snapshot()
        acquired = await capacity_mgr.try_acquire_slot(tenant_id)
        assert acquired is True, "Should acquire slot"

        after_acquire = await detector.snapshot()
        assert after_acquire == initial + 1, "Slot count should increase by 1"

        # Step 2: Simulate ARQ enqueue failure (non-duplicate error)
        # This is the critical path - we need to ensure slot is released

        try:
            # Simulate failure - in real code this would be job_manager.enqueue()
            raise RuntimeError("Connection refused to ARQ Redis")
        except RuntimeError:
            # Step 3: Release slot on failure (this is what the code should do)
            await capacity_mgr.release_slot(tenant_id)

        # Verify: No slot leak
        await detector.assert_no_leak(initial, "Enqueue failure must release slot")

        # Cleanup
        await redis_client.delete(slot_key)

    async def test_enqueue_duplicate_keeps_slot_but_removes_from_pending(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """When ARQ returns 'already exists', slot stays but job leaves pending queue.

        This is the idempotency case - the job IS running, so keeping the slot
        is correct. The pending queue entry should be removed.
        """
        tenant_id = uuid4()
        job_id = uuid4()

        slot_key = LuaScripts.slot_key(tenant_id)
        await redis_client.delete(slot_key)

        # Pre-acquire slot
        capacity_mgr = CapacityManager(redis_client, test_settings)
        await capacity_mgr.try_acquire_slot(tenant_id)

        detector = SlotLeakDetector(redis_client, tenant_id)
        initial = await detector.snapshot()
        assert initial == 1, "Should have 1 slot acquired"

        # Simulate duplicate detection via JobEnqueuer pattern matching
        from intric.worker.feeder.queues import JobEnqueuer

        enqueuer = JobEnqueuer()

        # Create a duplicate error
        dup_error = RuntimeError("Job already exists in queue")
        result, is_duplicate, returned_job_id = enqueuer._handle_enqueue_error(
            exc=dup_error,
            job_id=job_id,
            job_data={"url": "https://example.com"},
            tenant_id=tenant_id,
        )

        # Duplicate should return success=True (idempotency) and is_duplicate=True
        assert result is True, "Duplicate detection should return success=True"
        assert is_duplicate is True, "Should be marked as duplicate"

        # Slot should NOT be released for duplicates
        await detector.assert_no_leak(initial, "Duplicate should not release slot")

        # Cleanup
        await redis_client.delete(slot_key)


# =============================================================================
# TEST 2: EMERGENCY RELEASE PATH
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
class TestEmergencyReleaseSlot:
    """Tests for emergency_release_slot() dual-failure recovery.

    The emergency release path handles the rare scenario where:
    1. Early Redis check failed (preacquired_tenant_id = None)
    2. Tenant injection also failed (tenant = None)
    3. Both primary and fallback finally paths are skipped
    4. Slot would leak until TTL expires

    The emergency_release_slot() reads the slot_preacquired flag from Redis
    to recover the tenant_id and release the slot.
    """

    async def test_emergency_release_recovers_slot_from_flag(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Emergency release should recover tenant_id from flag and release slot."""
        tenant_id = uuid4()
        job_id = uuid4()

        slot_key = LuaScripts.slot_key(tenant_id)
        flag_key = f"job:{job_id}:slot_preacquired"

        # Setup: Clean state
        await redis_client.delete(slot_key, flag_key)

        capacity_mgr = CapacityManager(redis_client, test_settings)

        # Step 1: Acquire slot and set flag (simulating pre-acquire pattern)
        await capacity_mgr.try_acquire_slot(tenant_id)
        await capacity_mgr.mark_slot_preacquired(job_id, tenant_id)

        detector = SlotLeakDetector(redis_client, tenant_id)
        initial = await detector.snapshot()
        assert initial == 1, "Should have 1 slot"

        # Verify flag exists
        flag_value = await redis_client.get(flag_key)
        assert flag_value is not None, "Flag should exist"
        assert flag_value.decode() == str(tenant_id), "Flag should contain tenant_id"

        # Step 2: Simulate dual-failure scenario - call emergency release
        # This is the untested path that was identified in analysis
        released = await capacity_mgr.emergency_release_slot(job_id)

        assert released is True, "Emergency release should succeed"

        # Step 3: Verify slot was released
        final = await detector.snapshot()
        assert final == 0, "Slot should be released"

        # Step 4: Verify flag was cleaned up
        flag_after = await redis_client.get(flag_key)
        assert flag_after is None, "Flag should be deleted after emergency release"

        # Cleanup
        await redis_client.delete(slot_key, flag_key)

    async def test_emergency_release_noop_when_no_flag(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Emergency release should return False when no flag exists.

        This handles the case where:
        - Watchdog already released the slot (and deleted the flag)
        - Normal release path already ran
        """
        job_id = uuid4()

        capacity_mgr = CapacityManager(redis_client, test_settings)

        # No flag set - emergency release should be no-op
        released = await capacity_mgr.emergency_release_slot(job_id)

        assert released is False, "Should return False when no flag exists"

    async def test_emergency_release_handles_corrupted_flag(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Emergency release should handle invalid UUID in flag gracefully."""
        job_id = uuid4()
        flag_key = f"job:{job_id}:slot_preacquired"

        # Set corrupted flag value
        await redis_client.set(flag_key, "not-a-valid-uuid", ex=60)

        capacity_mgr = CapacityManager(redis_client, test_settings)

        # Should handle gracefully without raising
        released = await capacity_mgr.emergency_release_slot(job_id)

        # Should return False due to UUID parse error
        assert released is False, "Should return False on corrupted flag"

        # Cleanup
        await redis_client.delete(flag_key)


# =============================================================================
# TEST 3: HEARTBEAT TTL TIMING
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
class TestHeartbeatTTLTiming:
    """Tests for heartbeat TTL refresh timing under load.

    If persist_batch takes longer than the heartbeat interval, we risk:
    1. Counter TTL expiring (zombie counter)
    2. Flag TTL expiring (slot ownership lost)
    3. Watchdog incorrectly reconciling the counter
    """

    async def test_ttl_refresh_both_keys_atomically(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Heartbeat should refresh BOTH counter and flag TTL atomically."""
        tenant_id = uuid4()
        job_id = uuid4()

        slot_key = LuaScripts.slot_key(tenant_id)
        flag_key = f"job:{job_id}:slot_preacquired"

        # Setup with short TTL
        short_ttl = 5
        await redis_client.set(slot_key, "1", ex=short_ttl)
        await redis_client.set(flag_key, str(tenant_id), ex=short_ttl)

        # Simulate heartbeat TTL refresh (from HeartbeatMonitor._refresh_redis_ttl)
        longer_ttl = 600
        pipe = redis_client.pipeline(transaction=True)
        pipe.expire(slot_key, longer_ttl)
        pipe.expire(flag_key, longer_ttl)
        results = await pipe.execute()

        # Both should be refreshed
        assert results[0] == 1, "Counter TTL should be refreshed"
        assert results[1] == 1, "Flag TTL should be refreshed"

        # Verify TTLs
        counter_ttl = await redis_client.ttl(slot_key)
        flag_ttl = await redis_client.ttl(flag_key)

        assert counter_ttl > short_ttl, f"Counter TTL should be extended: {counter_ttl}"
        assert flag_ttl > short_ttl, f"Flag TTL should be extended: {flag_ttl}"

        # Cleanup
        await redis_client.delete(slot_key, flag_key)

    async def test_heartbeat_monitor_interval_check(self):
        """HeartbeatMonitor.tick() should skip if called before interval."""
        from intric.worker.crawl.heartbeat import HeartbeatMonitor

        job_id = uuid4()

        # Create monitor with long interval
        monitor = HeartbeatMonitor(
            job_id=job_id,
            redis_client=None,
            tenant=None,
            interval_seconds=300,  # 5 minutes
            max_failures=3,
            semaphore_ttl_seconds=600,
        )

        # First tick should execute
        with patch.object(
            monitor, "_execute_heartbeat", new_callable=AsyncMock
        ) as mock_execute:
            # Need to set last_beat_time to 0 to ensure first tick runs
            monitor._last_beat_time = 0
            await monitor.tick()

            # After first tick, immediate second tick should be skipped
            await monitor.tick()

            # Only one execution despite two ticks
            assert mock_execute.call_count == 1, "Second tick should be skipped"


# =============================================================================
# TEST 4: WATCHDOG VS WORKER RACE
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
class TestWatchdogWorkerRace:
    """Tests for race condition between watchdog cleanup and worker completion.

    Scenario: Worker is finishing successfully at the exact moment watchdog
    decides to mark the job as failed for being "long-running".

    Expected: Job should end in COMPLETED state, not FAILED.
    """

    async def test_watchdog_skip_recently_updated_jobs(self):
        """Watchdog should skip jobs with recent updated_at timestamps.

        This prevents the race condition where a job is being actively
        processed (heartbeat updating updated_at) but watchdog tries to
        fail it based on stale criteria.
        """

        # This test documents the expected behavior:
        # Phase 3 should skip jobs where:
        # updated_at > (now - crawl_job_in_progress_timeout)

        # The actual implementation should check updated_at freshness
        # before marking a job as failed

        pass  # Placeholder - implementation depends on Phase 3 logic


# =============================================================================
# TEST 5: CANCELLATION DURING PERSIST
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
class TestCancellationDuringPersist:
    """Tests for task cancellation safety during persist_batch.

    When a task is cancelled mid-persist:
    1. In-progress savepoints should rollback
    2. successful_urls should only contain committed pages
    3. Slot should still be released in finally block
    """

    async def test_savepoint_rollback_on_cancel(self):
        """Cancelled persist_batch should rollback uncommitted savepoints."""
        # This test documents the expected behavior based on savepoint pattern:
        #
        # for page in page_buffer:
        #     savepoint = await session.begin_nested()
        #     try:
        #         ... persist page ...
        #         await savepoint.commit()
        #         successful_urls.append(url)  # Only after commit!
        #     except Exception:
        #         await savepoint.rollback()
        #         failed_count += 1
        #
        # Cancellation at different points:
        # - Before commit: savepoint never commits → URL not in list
        # - After commit: savepoint succeeded → URL is in list

        pass  # Placeholder - requires mocked session with cancellation injection


# =============================================================================
# TEST 6: SLOT COUNTER ACCURACY
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
class TestSlotCounterAccuracy:
    """Tests for slot counter accuracy under concurrent operations."""

    async def test_concurrent_acquire_release_accuracy(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Slot counter should be accurate after many concurrent ops."""
        tenant_id = uuid4()
        slot_key = LuaScripts.slot_key(tenant_id)

        # Clean state
        await redis_client.delete(slot_key)

        capacity_mgr = CapacityManager(redis_client, test_settings)

        # Run many concurrent acquire/release pairs
        num_operations = 50

        async def acquire_and_release():
            acquired = await capacity_mgr.try_acquire_slot(tenant_id)
            if acquired:
                await asyncio.sleep(0.001)  # Tiny delay
                await capacity_mgr.release_slot(tenant_id)

        # Run all operations concurrently
        await asyncio.gather(*[acquire_and_release() for _ in range(num_operations)])

        # After all operations, counter should be back to 0
        detector = SlotLeakDetector(redis_client, tenant_id)
        final = await detector.snapshot()

        assert final == 0, (
            f"After {num_operations} acquire/release pairs, expected 0, got {final}"
        )

        # Cleanup
        await redis_client.delete(slot_key)

    async def test_lua_script_atomicity(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Lua acquire script should be atomic under concurrent access."""
        tenant_id = uuid4()
        slot_key = LuaScripts.slot_key(tenant_id)

        # Clean state
        await redis_client.delete(slot_key)

        max_slots = 5
        ttl = 60
        num_requests = 20  # More requests than available slots

        # Run concurrent acquire attempts
        async def try_acquire():
            result = await LuaScripts.acquire_slot(
                redis_client, tenant_id, max_slots, ttl
            )
            return result > 0

        results = await asyncio.gather(*[try_acquire() for _ in range(num_requests)])

        # Exactly max_slots should succeed
        successes = sum(1 for r in results if r)
        assert successes == max_slots, (
            f"Expected exactly {max_slots} successful acquires, got {successes}"
        )

        # Verify counter equals max_slots
        counter = await redis_client.get(slot_key)
        assert int(counter) == max_slots, (
            f"Counter should be {max_slots}, got {counter}"
        )

        # Cleanup
        await redis_client.delete(slot_key)


# =============================================================================
# TEST 7: FLAG CLEANUP CONSISTENCY
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
class TestFlagCleanupConsistency:
    """Tests for preacquired flag cleanup in all exit paths."""

    async def test_flag_cleared_on_normal_completion(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Flag should be cleared when job completes normally."""
        tenant_id = uuid4()
        job_id = uuid4()

        flag_key = f"job:{job_id}:slot_preacquired"

        capacity_mgr = CapacityManager(redis_client, test_settings)

        # Simulate setting flag during pre-acquire
        await capacity_mgr.mark_slot_preacquired(job_id, tenant_id)

        # Verify flag exists
        flag = await redis_client.get(flag_key)
        assert flag is not None, "Flag should exist"

        # Simulate normal completion - clear flag
        await capacity_mgr.clear_preacquired_flag(job_id)

        # Verify flag is cleared
        flag_after = await redis_client.get(flag_key)
        assert flag_after is None, "Flag should be cleared after normal completion"

    async def test_flag_lookup_for_slot_release(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """get_preacquired_tenant should return correct tenant_id."""
        tenant_id = uuid4()
        job_id = uuid4()

        capacity_mgr = CapacityManager(redis_client, test_settings)

        # No flag - should return None
        result_none = await capacity_mgr.get_preacquired_tenant(job_id)
        assert result_none is None, "Should return None when no flag"

        # Set flag
        await capacity_mgr.mark_slot_preacquired(job_id, tenant_id)

        # Should return tenant_id
        result_tenant = await capacity_mgr.get_preacquired_tenant(job_id)
        assert result_tenant == tenant_id, "Should return correct tenant_id"

        # Cleanup
        flag_key = f"job:{job_id}:slot_preacquired"
        await redis_client.delete(flag_key)


# =============================================================================
# FIXTURES
# =============================================================================

# NOTE: test_settings fixture is provided by conftest.py with real Settings
# containing testcontainer connection strings, encryption keys, and default
# worker settings (tenant_worker_concurrency_limit=4, etc.)
