"""Integration tests for CrawlFeeder components.

Tests the modular feeder components with real Redis:
- LeaderElection: Redis locks for singleton coordination
- CapacityManager: Per-tenant concurrency slot management
- PendingQueue: FIFO job queue operations
"""

import asyncio
import json
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from intric.worker.feeder.capacity import CapacityManager
from intric.worker.feeder.election import LeaderElection
from intric.worker.feeder.queues import PendingQueue


@pytest.mark.integration
@pytest.mark.asyncio
class TestLeaderElection:
    """Tests for leader election mechanism."""

    async def test_first_feeder_acquires_leader_lock(
        self, redis_client: aioredis.Redis
    ):
        """First feeder should successfully acquire leader lock."""
        await redis_client.delete("crawl_feeder:leader")

        worker_id = f"test-worker-{uuid4().hex[:8]}"
        election = LeaderElection(redis_client, worker_id)

        acquired = await election.try_acquire()

        assert acquired is True, "First feeder should acquire lock"

        lock_value = await redis_client.get("crawl_feeder:leader")
        assert lock_value is not None, "Lock should exist in Redis"

        await redis_client.delete("crawl_feeder:leader")

    async def test_second_feeder_cannot_acquire_lock(
        self, redis_client: aioredis.Redis
    ):
        """Second feeder should fail to acquire when lock is held."""
        await redis_client.delete("crawl_feeder:leader")
        await redis_client.set("crawl_feeder:leader", "existing_leader", ex=30)

        worker_id = f"test-worker-{uuid4().hex[:8]}"
        election = LeaderElection(redis_client, worker_id)

        acquired = await election.try_acquire()

        assert acquired is False, "Second feeder should not acquire lock"

        await redis_client.delete("crawl_feeder:leader")

    async def test_leader_lock_has_ttl(
        self, redis_client: aioredis.Redis
    ):
        """Leader lock should have TTL for automatic failover."""
        await redis_client.delete("crawl_feeder:leader")

        worker_id = f"test-worker-{uuid4().hex[:8]}"
        election = LeaderElection(redis_client, worker_id)

        await election.try_acquire()

        ttl = await redis_client.ttl("crawl_feeder:leader")

        assert 25 <= ttl <= 30, f"Lock should have ~30s TTL, got {ttl}"

        await redis_client.delete("crawl_feeder:leader")

    async def test_refresh_leader_lock_extends_ttl(
        self, redis_client: aioredis.Redis
    ):
        """Refreshing lock should extend TTL."""
        worker_id = f"test-worker-{uuid4().hex[:8]}"
        election = LeaderElection(redis_client, worker_id)

        # Set lock with short TTL but CORRECT owner
        await redis_client.set("crawl_feeder:leader", worker_id, ex=5)

        await election.refresh()

        ttl = await redis_client.ttl("crawl_feeder:leader")

        assert 25 <= ttl <= 30, f"Lock should be refreshed to ~30s TTL, got {ttl}"

        await redis_client.delete("crawl_feeder:leader")


@pytest.mark.integration
@pytest.mark.asyncio
class TestCapacityManager:
    """Tests for capacity observation."""

    async def test_returns_full_capacity_when_no_active_jobs(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Should return full capacity when no jobs are active."""
        tenant_id = uuid4()
        max_concurrent = test_settings.tenant_worker_concurrency_limit

        await redis_client.delete(f"tenant:{tenant_id}:active_jobs")

        capacity_mgr = CapacityManager(redis_client, test_settings)

        capacity = await capacity_mgr.get_available_capacity(tenant_id)

        assert capacity == max_concurrent, "Should return full capacity when no active_jobs key"

    async def test_returns_remaining_capacity(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Should return remaining capacity based on active jobs."""
        tenant_id = uuid4()
        max_concurrent = test_settings.tenant_worker_concurrency_limit

        await redis_client.set(f"tenant:{tenant_id}:active_jobs", "2")

        capacity_mgr = CapacityManager(redis_client, test_settings)

        capacity = await capacity_mgr.get_available_capacity(tenant_id)

        expected = max_concurrent - 2
        assert capacity == expected, f"Should have {expected} capacity, got {capacity}"

        await redis_client.delete(f"tenant:{tenant_id}:active_jobs")

    async def test_returns_zero_when_at_capacity(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Should return 0 when at max capacity."""
        tenant_id = uuid4()
        max_concurrent = test_settings.tenant_worker_concurrency_limit

        await redis_client.set(f"tenant:{tenant_id}:active_jobs", str(max_concurrent))

        capacity_mgr = CapacityManager(redis_client, test_settings)

        capacity = await capacity_mgr.get_available_capacity(tenant_id)

        assert capacity == 0, "Should have 0 capacity when at max"

        await redis_client.delete(f"tenant:{tenant_id}:active_jobs")

    async def test_handles_invalid_active_jobs_value(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Should handle invalid active_jobs values gracefully."""
        tenant_id = uuid4()

        await redis_client.set(f"tenant:{tenant_id}:active_jobs", "not_a_number")

        capacity_mgr = CapacityManager(redis_client, test_settings)

        capacity = await capacity_mgr.get_available_capacity(tenant_id)

        assert capacity == 0, "Should return 0 on invalid value"

        await redis_client.delete(f"tenant:{tenant_id}:active_jobs")


@pytest.mark.integration
@pytest.mark.asyncio
class TestPendingQueue:
    """Tests for pending queue management."""

    async def test_gets_pending_crawls_from_queue(
        self, redis_client: aioredis.Redis
    ):
        """Should retrieve pending crawl jobs from queue."""
        tenant_id = uuid4()
        queue_key = f"tenant:{tenant_id}:crawl_pending"

        job_1 = {"job_id": str(uuid4()), "url": "https://example.com/1"}
        job_2 = {"job_id": str(uuid4()), "url": "https://example.com/2"}

        await redis_client.lpush(queue_key, json.dumps(job_1), json.dumps(job_2))

        pending_queue = PendingQueue(redis_client)

        pending = await pending_queue.get_pending(tenant_id, limit=10)

        assert len(pending) == 2, "Should have 2 pending jobs"

        await redis_client.delete(queue_key)

    async def test_respects_limit_parameter(
        self, redis_client: aioredis.Redis
    ):
        """Should only retrieve up to limit jobs."""
        tenant_id = uuid4()
        queue_key = f"tenant:{tenant_id}:crawl_pending"

        for i in range(5):
            job = {"job_id": str(uuid4()), "url": f"https://example.com/{i}"}
            await redis_client.rpush(queue_key, json.dumps(job))

        pending_queue = PendingQueue(redis_client)

        pending = await pending_queue.get_pending(tenant_id, limit=2)

        assert len(pending) == 2, "Should respect limit parameter"

        await redis_client.delete(queue_key)

    async def test_returns_empty_list_when_no_pending(
        self, redis_client: aioredis.Redis
    ):
        """Should return empty list when no pending jobs."""
        tenant_id = uuid4()
        queue_key = f"tenant:{tenant_id}:crawl_pending"

        await redis_client.delete(queue_key)

        pending_queue = PendingQueue(redis_client)

        pending = await pending_queue.get_pending(tenant_id, limit=10)

        assert pending == [], "Should return empty list"

    async def test_handles_malformed_json_gracefully(
        self, redis_client: aioredis.Redis
    ):
        """Should skip malformed JSON entries without crashing."""
        tenant_id = uuid4()
        queue_key = f"tenant:{tenant_id}:crawl_pending"

        valid_job = {"job_id": str(uuid4()), "url": "https://example.com/valid"}
        await redis_client.rpush(queue_key, json.dumps(valid_job))
        await redis_client.rpush(queue_key, "not valid json {{{")

        pending_queue = PendingQueue(redis_client)

        pending = await pending_queue.get_pending(tenant_id, limit=10)

        assert len(pending) == 1, "Should skip malformed JSON"
        assert pending[0][1]["url"] == "https://example.com/valid"

        await redis_client.delete(queue_key)


@pytest.mark.integration
@pytest.mark.asyncio
class TestMultiTenantIsolation:
    """Tests for multi-tenant isolation."""

    async def test_capacity_is_per_tenant(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Capacity should be tracked per-tenant."""
        tenant_1 = uuid4()
        tenant_2 = uuid4()
        max_concurrent = test_settings.tenant_worker_concurrency_limit

        await redis_client.set(f"tenant:{tenant_1}:active_jobs", "3")
        await redis_client.set(f"tenant:{tenant_2}:active_jobs", "0")

        capacity_mgr = CapacityManager(redis_client, test_settings)

        cap_1 = await capacity_mgr.get_available_capacity(tenant_1)
        cap_2 = await capacity_mgr.get_available_capacity(tenant_2)

        assert cap_1 == max_concurrent - 3, f"Tenant 1 should have {max_concurrent - 3} capacity"
        assert cap_2 == max_concurrent, f"Tenant 2 should have full {max_concurrent} capacity"

        await redis_client.delete(
            f"tenant:{tenant_1}:active_jobs",
            f"tenant:{tenant_2}:active_jobs",
        )

    async def test_pending_queues_are_per_tenant(
        self, redis_client: aioredis.Redis
    ):
        """Pending queues should be isolated per-tenant."""
        tenant_1 = uuid4()
        tenant_2 = uuid4()

        job_1 = {"job_id": str(uuid4()), "url": "https://tenant1.com/page"}
        await redis_client.rpush(f"tenant:{tenant_1}:crawl_pending", json.dumps(job_1))

        job_2 = {"job_id": str(uuid4()), "url": "https://tenant2.com/page"}
        await redis_client.rpush(f"tenant:{tenant_2}:crawl_pending", json.dumps(job_2))

        pending_queue = PendingQueue(redis_client)

        pending_1 = await pending_queue.get_pending(tenant_1, limit=10)
        pending_2 = await pending_queue.get_pending(tenant_2, limit=10)

        assert len(pending_1) == 1, "Tenant 1 should have 1 job"
        assert pending_1[0][1]["url"] == "https://tenant1.com/page"

        assert len(pending_2) == 1, "Tenant 2 should have 1 job"
        assert pending_2[0][1]["url"] == "https://tenant2.com/page"

        await redis_client.delete(
            f"tenant:{tenant_1}:crawl_pending",
            f"tenant:{tenant_2}:crawl_pending",
        )


@pytest.mark.integration
@pytest.mark.asyncio
class TestSplitBrainPrevention:
    """Tests for split-brain leader election scenarios."""

    async def test_lock_acquisition_is_atomic(
        self, redis_client: aioredis.Redis
    ):
        """Verify lock acquisition uses SET NX (atomic operation)."""
        await redis_client.delete("crawl_feeder:leader")

        election_1 = LeaderElection(redis_client, f"worker-{uuid4().hex[:8]}")
        election_2 = LeaderElection(redis_client, f"worker-{uuid4().hex[:8]}")

        results = await asyncio.gather(
            election_1.try_acquire(),
            election_2.try_acquire(),
        )

        assert sum(results) == 1, (
            f"Expected exactly 1 leader, got {sum(results)}. "
            "Lock acquisition may not be atomic."
        )

        await redis_client.delete("crawl_feeder:leader")

    async def test_multiple_feeders_race_for_leadership(
        self, redis_client: aioredis.Redis
    ):
        """Test multiple feeders racing for leadership."""
        await redis_client.delete("crawl_feeder:leader")

        num_feeders = 5
        elections = [
            LeaderElection(redis_client, f"worker-{uuid4().hex[:8]}")
            for _ in range(num_feeders)
        ]

        results = await asyncio.gather(
            *[e.try_acquire() for e in elections]
        )

        winners = sum(results)
        assert winners == 1, (
            f"Expected 1 leader from {num_feeders} feeders, got {winners}. "
            "Split-brain scenario detected!"
        )

        await redis_client.delete("crawl_feeder:leader")

    async def test_lock_value_identifies_leader(
        self, redis_client: aioredis.Redis
    ):
        """Verify lock contains identifying information about the leader."""
        await redis_client.delete("crawl_feeder:leader")

        worker_id = f"test-worker-{uuid4().hex[:8]}"
        election = LeaderElection(redis_client, worker_id)

        await election.try_acquire()

        lock_value = await redis_client.get("crawl_feeder:leader")
        assert lock_value is not None, "Lock should be set"
        assert lock_value.decode() == worker_id, "Lock value should be worker_id"

        await redis_client.delete("crawl_feeder:leader")

    async def test_expired_lock_can_be_reacquired(
        self, redis_client: aioredis.Redis
    ):
        """Verify another feeder can acquire expired lock."""
        await redis_client.delete("crawl_feeder:leader")

        election_1 = LeaderElection(redis_client, f"worker-{uuid4().hex[:8]}")
        election_2 = LeaderElection(redis_client, f"worker-{uuid4().hex[:8]}")

        result_1 = await election_1.try_acquire()
        assert result_1 is True

        result_2_before = await election_2.try_acquire()
        assert result_2_before is False

        # Simulate lock expiry by setting very short TTL
        await redis_client.expire("crawl_feeder:leader", 1)

        # Poll until key actually expires
        for _ in range(10):
            await asyncio.sleep(0.5)
            if not await redis_client.exists("crawl_feeder:leader"):
                break

        assert not await redis_client.exists("crawl_feeder:leader"), "Lock should have expired"

        result_2_after = await election_2.try_acquire()
        assert result_2_after is True, "Feeder 2 should acquire after lock expires"

        await redis_client.delete("crawl_feeder:leader")

    async def test_lock_refresh_only_if_still_leader(
        self, redis_client: aioredis.Redis
    ):
        """Verify refresh doesn't work if we're no longer the leader."""
        await redis_client.delete("crawl_feeder:leader")

        worker_1 = f"worker-{uuid4().hex[:8]}"
        worker_2 = f"worker-{uuid4().hex[:8]}"

        election_1 = LeaderElection(redis_client, worker_1)
        election_2 = LeaderElection(redis_client, worker_2)

        await election_1.try_acquire()

        # Simulate lock expiry and feeder 2 taking over
        await redis_client.delete("crawl_feeder:leader")
        await election_2.try_acquire()

        # Feeder 1 tries to refresh (but feeder 2 now owns the lock)
        refresh_result = await election_1.refresh()

        # Should NOT refresh since we're not the owner
        assert refresh_result is False, "Refresh should fail if not owner"

        # Verify feeder 2 still owns the lock
        lock_value = await redis_client.get("crawl_feeder:leader")
        assert lock_value.decode() == worker_2, "Feeder 2 should still own lock"

        await redis_client.delete("crawl_feeder:leader")
