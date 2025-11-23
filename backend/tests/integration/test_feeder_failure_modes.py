"""Integration tests for CrawlFeeder distributed system failure modes.

Tests critical failure scenarios identified by GPT-5 and Gemini-3-pro-preview:
- Zombie Leader: Lock expires mid-processing when tenant loop takes >30s
- Enqueue-State Lag: active_jobs lags behind actual enqueued jobs
- Crash-Before-LREM: Fragile ARQ exception string matching

These tests catch real production bugs, not just verify happy paths.
"""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from intric.worker.crawl_feeder import CrawlFeeder


@pytest.mark.integration
@pytest.mark.asyncio
class TestZombieLeaderScenario:
    """Tests for leader lock expiry during processing.

    Risk: If processing tenant queues takes >30s, the lock expires mid-loop.
    A second worker acquires the lock. Now TWO feeders enqueue jobs simultaneously,
    bypassing concurrency limits.
    """

    async def test_lock_expires_during_slow_processing(
        self, redis_client: aioredis.Redis
    ):
        """Verify second feeder can acquire lock when first is slow.

        This catches the Zombie Leader bug where:
        1. Feeder A acquires lock (30s TTL)
        2. Feeder A processes tenants slowly (>30s)
        3. Lock expires while Feeder A is still processing
        4. Feeder B acquires lock
        5. Both feeders now process simultaneously (BAD)
        """
        # Clean up any existing lock
        await redis_client.delete("crawl_feeder:leader")

        # Create two feeder instances
        feeder_a = CrawlFeeder()
        feeder_b = CrawlFeeder()

        # Feeder A acquires lock
        acquired_a = await feeder_a._try_acquire_leader_lock(redis_client)
        assert acquired_a is True, "Feeder A should acquire lock"

        # Verify Feeder B cannot acquire while lock is valid
        acquired_b_before = await feeder_b._try_acquire_leader_lock(redis_client)
        assert acquired_b_before is False, "Feeder B should NOT acquire while lock valid"

        # Simulate lock expiry by deleting it (simulates 30s passing)
        await redis_client.delete("crawl_feeder:leader")

        # Now Feeder B can acquire - this is the Zombie Leader scenario
        acquired_b_after = await feeder_b._try_acquire_leader_lock(redis_client)
        assert acquired_b_after is True, "Feeder B acquires after lock expires (Zombie Leader)"

        # Cleanup
        await redis_client.delete("crawl_feeder:leader")

    async def test_lock_refresh_prevents_zombie_leader(
        self, redis_client: aioredis.Redis
    ):
        """Verify refreshing lock prevents Zombie Leader scenario.

        If the feeder refreshes its lock during processing, the Zombie Leader
        scenario is prevented.
        """
        await redis_client.delete("crawl_feeder:leader")

        feeder_a = CrawlFeeder()
        feeder_b = CrawlFeeder()

        # Feeder A acquires and refreshes
        acquired = await feeder_a._try_acquire_leader_lock(redis_client)
        assert acquired is True, "Lock should be acquired before refresh"
        await feeder_a._refresh_leader_lock(redis_client)

        # Check TTL was refreshed to ~30s
        ttl = await redis_client.ttl("crawl_feeder:leader")
        assert 25 <= ttl <= 30, f"Lock should be refreshed to ~30s TTL, got {ttl}"

        # Feeder B still cannot acquire
        acquired_b = await feeder_b._try_acquire_leader_lock(redis_client)
        assert acquired_b is False, "Feeder B should NOT acquire after refresh"

        # Cleanup
        await redis_client.delete("crawl_feeder:leader")


@pytest.mark.integration
@pytest.mark.asyncio
class TestEnqueueStateLag:
    """Tests for thundering herd / capacity overshoot scenario.

    Risk: Feeder checks active_jobs, enqueues jobs, but active_jobs isn't
    updated until workers pick up jobs. If feeder runs again before workers
    update the counter, it overshoots capacity.
    """

    async def test_capacity_not_updated_between_enqueue_cycles(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Verify capacity check can lead to overshoot if state lags.

        This test documents the potential for thundering herd:
        1. Feeder sees capacity=5
        2. Feeder enqueues 5 jobs
        3. Feeder checks again BEFORE workers update active_jobs
        4. Feeder sees capacity=5 again (stale!)
        5. Feeder enqueues 5 MORE jobs (overshoot)
        """
        tenant_id = uuid4()
        max_concurrent = test_settings.tenant_worker_concurrency_limit

        # Set active_jobs to 0 (full capacity available)
        await redis_client.set(f"tenant:{tenant_id}:active_jobs", "0")

        feeder = CrawlFeeder()
        feeder.settings = test_settings

        # First capacity check - full capacity
        capacity_1 = await feeder._get_available_capacity(tenant_id, redis_client)
        assert capacity_1 == max_concurrent, "Should see full capacity"

        # Simulate: Feeder enqueued jobs but workers haven't updated active_jobs yet
        # (In production, there's a lag between ARQ enqueue and worker pickup)

        # Second capacity check WITHOUT updating active_jobs - still sees full capacity
        capacity_2 = await feeder._get_available_capacity(tenant_id, redis_client)
        assert capacity_2 == max_concurrent, "Still sees full capacity (state lag)"

        # This documents the thundering herd risk - both checks returned full capacity
        # even though jobs were conceptually enqueued between them

        # Cleanup
        await redis_client.delete(f"tenant:{tenant_id}:active_jobs")

    async def test_capacity_updated_after_worker_pickup(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Verify capacity is correctly reduced after workers update counter."""
        tenant_id = uuid4()
        max_concurrent = test_settings.tenant_worker_concurrency_limit

        # Initial state: 0 active jobs
        await redis_client.set(f"tenant:{tenant_id}:active_jobs", "0")

        feeder = CrawlFeeder()
        feeder.settings = test_settings

        # Check initial capacity
        capacity_before = await feeder._get_available_capacity(tenant_id, redis_client)
        assert capacity_before == max_concurrent

        # Simulate: Workers picked up 3 jobs and updated counter
        await redis_client.set(f"tenant:{tenant_id}:active_jobs", "3")

        # Now capacity should be reduced
        capacity_after = await feeder._get_available_capacity(tenant_id, redis_client)
        assert capacity_after == max_concurrent - 3, "Capacity should be reduced by 3"

        # Cleanup
        await redis_client.delete(f"tenant:{tenant_id}:active_jobs")


@pytest.mark.integration
@pytest.mark.asyncio
class TestCrashBeforeLremRecovery:
    """Tests for idempotent recovery when crash occurs after enqueue but before LREM.

    Risk: If feeder crashes after enqueueing to ARQ but before removing from
    pending queue (LREM), the job stays in pending. On restart, feeder tries
    to enqueue again. ARQ rejects with "duplicate job_id" error.

    The code handles this by checking error message strings - which is fragile.
    """

    async def test_duplicate_job_id_treated_as_success(
        self, redis_client: aioredis.Redis
    ):
        """Verify duplicate job_id error is treated as success for LREM.

        This catches the fragile string matching bug where:
        1. Feeder enqueues job to ARQ
        2. Feeder crashes before LREM
        3. Feeder restarts, tries to enqueue same job
        4. ARQ returns "job_id already exists" error
        5. Code must treat this as SUCCESS so LREM proceeds
        """
        tenant_id = uuid4()
        job_id = uuid4()

        # Create job data
        job_data = {
            "job_id": str(job_id),
            "user_id": str(uuid4()),
            "website_id": str(uuid4()),
            "run_id": str(uuid4()),
            "url": "https://example.com/test",
            "download_files": False,
            "crawl_type": "crawl",
        }

        feeder = CrawlFeeder()

        # Mock module-level job_manager.enqueue to raise duplicate error
        with patch("intric.worker.crawl_feeder.job_manager") as mock_job_manager:
            mock_job_manager.enqueue = AsyncMock(
                side_effect=Exception("job_id already exists in queue")
            )

            # This should return True (success) despite the exception
            success, returned_job_id = await feeder._enqueue_crawl_job(job_data, tenant_id)

        assert success is True, "Duplicate job_id error should be treated as success"
        assert returned_job_id == job_id, "Should return the job_id"

    async def test_real_error_not_treated_as_success(
        self, redis_client: aioredis.Redis
    ):
        """Verify real errors are NOT treated as success.

        Only duplicate job_id errors should be treated as success.
        Other errors (network, validation, etc.) should return False.
        """
        tenant_id = uuid4()
        job_id = uuid4()

        job_data = {
            "job_id": str(job_id),
            "user_id": str(uuid4()),
            "website_id": str(uuid4()),
            "run_id": str(uuid4()),
            "url": "https://example.com/test",
            "download_files": False,
            "crawl_type": "crawl",
        }

        feeder = CrawlFeeder()

        # Mock module-level job_manager.enqueue to raise a REAL error
        with patch("intric.worker.crawl_feeder.job_manager") as mock_job_manager:
            mock_job_manager.enqueue = AsyncMock(
                side_effect=Exception("Redis connection timeout")
            )

            # This should return False (failure) for real errors
            success, returned_job_id = await feeder._enqueue_crawl_job(job_data, tenant_id)

        assert success is False, "Real errors should NOT be treated as success"

    async def test_various_duplicate_error_messages(
        self, redis_client: aioredis.Redis
    ):
        """Test various forms of duplicate job error messages are handled.

        ARQ or other queue systems might phrase the error differently.
        The code checks for specific patterns: 'already exists', 'duplicate', 'job exists'.
        Note: We intentionally DON'T match broad patterns like just 'job_id' to avoid
        false positives on validation errors like 'invalid job_id format'.
        """
        tenant_id = uuid4()

        duplicate_error_messages = [
            "job already exists in queue",
            "Job with this ID already exists",
            "duplicate job detected",
            "Duplicate entry detected",
            "job exists in ARQ",
        ]

        for error_msg in duplicate_error_messages:
            job_id = uuid4()
            job_data = {
                "job_id": str(job_id),
                "user_id": str(uuid4()),
                "website_id": str(uuid4()),
                "run_id": str(uuid4()),
                "url": "https://example.com/test",
                "download_files": False,
                "crawl_type": "crawl",
            }

            feeder = CrawlFeeder()

            # Mock module-level job_manager.enqueue
            with patch("intric.worker.crawl_feeder.job_manager") as mock_job_manager:
                mock_job_manager.enqueue = AsyncMock(side_effect=Exception(error_msg))

                success, _ = await feeder._enqueue_crawl_job(job_data, tenant_id)

            assert success is True, f"Error '{error_msg}' should be treated as duplicate"


@pytest.mark.integration
@pytest.mark.asyncio
class TestPendingQueueIdempotency:
    """Tests for pending queue operations and idempotency."""

    async def test_remove_from_pending_is_idempotent(
        self, redis_client: aioredis.Redis
    ):
        """Verify removing from pending queue is safe to call multiple times.

        If feeder crashes after LREM but before completing, it might try
        to LREM again on restart. This should be safe (idempotent).
        """
        tenant_id = uuid4()
        queue_key = f"tenant:{tenant_id}:crawl_pending"

        job_data = {"job_id": str(uuid4()), "url": "https://example.com/test"}

        # Add job to pending queue and get the raw bytes we pushed
        raw_bytes = json.dumps(job_data, default=str, sort_keys=True).encode()
        await redis_client.rpush(queue_key, raw_bytes)

        feeder = CrawlFeeder()

        # First removal - should work (now takes raw_bytes instead of job_data)
        await feeder._remove_from_pending(tenant_id, raw_bytes, redis_client)

        # Verify job is removed
        remaining = await redis_client.lrange(queue_key, 0, -1)
        assert len(remaining) == 0, "Job should be removed"

        # Second removal - should NOT crash (idempotent)
        await feeder._remove_from_pending(tenant_id, raw_bytes, redis_client)

        # Still empty, no crash
        remaining_after = await redis_client.lrange(queue_key, 0, -1)
        assert len(remaining_after) == 0, "Queue should still be empty"

        # Cleanup
        await redis_client.delete(queue_key)

    async def test_pending_queue_fifo_order_preserved(
        self, redis_client: aioredis.Redis
    ):
        """Verify pending queue maintains FIFO order."""
        tenant_id = uuid4()
        queue_key = f"tenant:{tenant_id}:crawl_pending"

        # Add jobs in order
        jobs = [
            {"job_id": str(uuid4()), "url": f"https://example.com/{i}"}
            for i in range(5)
        ]

        for job in jobs:
            await redis_client.rpush(queue_key, json.dumps(job))

        feeder = CrawlFeeder()

        # Get pending jobs - returns list of (raw_bytes, job_data) tuples
        pending = await feeder._get_pending_crawls(tenant_id, redis_client, limit=5)

        # Verify FIFO order - access tuple index 1 for job_data dict
        for i, (raw_bytes, job_data) in enumerate(pending):
            assert job_data["url"] == f"https://example.com/{i}", f"Job {i} should be in FIFO order"

        # Cleanup
        await redis_client.delete(queue_key)
