"""Integration tests for CrawlFeeder service.

Tests the metered job enqueueing system with real Redis:
- Leader election via Redis locks
- Capacity observation from TenantConcurrencyLimiter
- Pending queue management
- Idempotent job enqueueing
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from intric.worker.crawl_feeder import (
    CrawlFeeder,
    _generate_deterministic_job_id,
)


class TestGenerateDeterministicJobId:
    """Tests for deterministic job ID generation."""

    def test_same_inputs_produce_same_id(self):
        """Same run_id + url should produce same job ID."""
        run_id = uuid4()
        url = "https://example.com/page"

        id_1 = _generate_deterministic_job_id(run_id, url)
        id_2 = _generate_deterministic_job_id(run_id, url)

        assert id_1 == id_2, "Same inputs should produce same job ID"

    def test_different_urls_produce_different_ids(self):
        """Different URLs should produce different job IDs."""
        run_id = uuid4()
        url_1 = "https://example.com/page1"
        url_2 = "https://example.com/page2"

        id_1 = _generate_deterministic_job_id(run_id, url_1)
        id_2 = _generate_deterministic_job_id(run_id, url_2)

        assert id_1 != id_2, "Different URLs should produce different IDs"

    def test_different_run_ids_produce_different_ids(self):
        """Different run IDs should produce different job IDs."""
        run_id_1 = uuid4()
        run_id_2 = uuid4()
        url = "https://example.com/page"

        id_1 = _generate_deterministic_job_id(run_id_1, url)
        id_2 = _generate_deterministic_job_id(run_id_2, url)

        assert id_1 != id_2, "Different run IDs should produce different IDs"

    def test_job_id_format(self):
        """Job ID should follow crawl:{run_id}:{url_hash} format."""
        run_id = uuid4()
        url = "https://example.com/page"

        job_id = _generate_deterministic_job_id(run_id, url)

        assert job_id.startswith(f"crawl:{run_id}:"), "Should start with crawl:{run_id}:"
        parts = job_id.split(":")
        assert len(parts) == 3, "Should have 3 parts"
        assert len(parts[2]) == 8, "URL hash should be 8 characters"


@pytest.mark.integration
@pytest.mark.asyncio
class TestCrawlFeederLeaderElection:
    """Tests for leader election mechanism."""

    async def test_first_feeder_acquires_leader_lock(
        self, redis_client: aioredis.Redis
    ):
        """First feeder should successfully acquire leader lock."""
        # Clean up any existing lock
        await redis_client.delete("crawl_feeder:leader")

        # Create mock container
        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)

        # Should acquire lock
        acquired = await feeder._try_acquire_leader_lock(redis_client)

        assert acquired is True, "First feeder should acquire lock"

        # Verify lock exists
        lock_value = await redis_client.get("crawl_feeder:leader")
        assert lock_value is not None, "Lock should exist in Redis"

        # Cleanup
        await redis_client.delete("crawl_feeder:leader")

    async def test_second_feeder_cannot_acquire_lock(
        self, redis_client: aioredis.Redis
    ):
        """Second feeder should fail to acquire when lock is held."""
        # Clean up and set initial lock
        await redis_client.delete("crawl_feeder:leader")
        await redis_client.set("crawl_feeder:leader", "existing_leader", ex=30)

        # Create mock container
        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)

        # Should NOT acquire lock
        acquired = await feeder._try_acquire_leader_lock(redis_client)

        assert acquired is False, "Second feeder should not acquire lock"

        # Cleanup
        await redis_client.delete("crawl_feeder:leader")

    async def test_leader_lock_has_ttl(
        self, redis_client: aioredis.Redis
    ):
        """Leader lock should have TTL for automatic failover."""
        # Clean up any existing lock
        await redis_client.delete("crawl_feeder:leader")

        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)

        await feeder._try_acquire_leader_lock(redis_client)

        # Check TTL
        ttl = await redis_client.ttl("crawl_feeder:leader")

        # Should have TTL (30 seconds minus test execution time)
        assert 25 <= ttl <= 30, f"Lock should have ~30s TTL, got {ttl}"

        # Cleanup
        await redis_client.delete("crawl_feeder:leader")

    async def test_refresh_leader_lock_extends_ttl(
        self, redis_client: aioredis.Redis
    ):
        """Refreshing lock should extend TTL."""
        # Set lock with short TTL
        await redis_client.set("crawl_feeder:leader", "leader", ex=5)

        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)

        # Refresh lock
        await feeder._refresh_leader_lock(redis_client)

        # Check new TTL
        ttl = await redis_client.ttl("crawl_feeder:leader")

        # Should be refreshed to ~30s
        assert 25 <= ttl <= 30, f"Lock should be refreshed to ~30s TTL, got {ttl}"

        # Cleanup
        await redis_client.delete("crawl_feeder:leader")


@pytest.mark.integration
@pytest.mark.asyncio
class TestCrawlFeederCapacity:
    """Tests for capacity observation."""

    async def test_returns_full_capacity_when_no_active_jobs(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Should return full capacity when no jobs are active.

        Note: _get_available_capacity is a read-only hint for batch sizing.
        Actual slot acquisition is done atomically by _try_acquire_slot().
        Returning full capacity when no key exists is safe.
        """
        tenant_id = uuid4()
        max_concurrent = test_settings.tenant_worker_concurrency_limit

        # Ensure no active jobs key exists
        await redis_client.delete(f"tenant:{tenant_id}:active_jobs")

        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)
        feeder.settings = test_settings

        # Get capacity
        capacity = await feeder._get_available_capacity(tenant_id, redis_client)

        # With no key, return full capacity (safe because _try_acquire_slot does atomic check)
        assert capacity == max_concurrent, "Should return full capacity when no active_jobs key"

    async def test_returns_remaining_capacity(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Should return remaining capacity based on active jobs."""
        tenant_id = uuid4()
        max_concurrent = test_settings.tenant_worker_concurrency_limit

        # Set active jobs
        await redis_client.set(f"tenant:{tenant_id}:active_jobs", "2")

        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)
        feeder.settings = test_settings

        # Get capacity
        capacity = await feeder._get_available_capacity(tenant_id, redis_client)

        # Should be max_concurrent - 2
        expected = max_concurrent - 2
        assert capacity == expected, f"Should have {expected} capacity, got {capacity}"

        # Cleanup
        await redis_client.delete(f"tenant:{tenant_id}:active_jobs")

    async def test_returns_zero_when_at_capacity(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Should return 0 when at max capacity."""
        tenant_id = uuid4()
        max_concurrent = test_settings.tenant_worker_concurrency_limit

        # Set active jobs at max
        await redis_client.set(f"tenant:{tenant_id}:active_jobs", str(max_concurrent))

        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)
        feeder.settings = test_settings

        # Get capacity
        capacity = await feeder._get_available_capacity(tenant_id, redis_client)

        assert capacity == 0, "Should have 0 capacity when at max"

        # Cleanup
        await redis_client.delete(f"tenant:{tenant_id}:active_jobs")

    async def test_handles_invalid_active_jobs_value(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Should handle invalid active_jobs values gracefully."""
        tenant_id = uuid4()

        # Set invalid value
        await redis_client.set(f"tenant:{tenant_id}:active_jobs", "not_a_number")

        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)
        feeder.settings = test_settings

        # Get capacity - should not raise
        capacity = await feeder._get_available_capacity(tenant_id, redis_client)

        # Should return 0 (conservative) on error
        assert capacity == 0, "Should return 0 on invalid value"

        # Cleanup
        await redis_client.delete(f"tenant:{tenant_id}:active_jobs")


@pytest.mark.integration
@pytest.mark.asyncio
class TestCrawlFeederPendingQueue:
    """Tests for pending queue management."""

    async def test_gets_pending_crawls_from_queue(
        self, redis_client: aioredis.Redis
    ):
        """Should retrieve pending crawl jobs from queue."""
        tenant_id = uuid4()
        queue_key = f"tenant:{tenant_id}:crawl_pending"

        # Add jobs to queue
        job_1 = {"job_id": str(uuid4()), "url": "https://example.com/1"}
        job_2 = {"job_id": str(uuid4()), "url": "https://example.com/2"}

        await redis_client.lpush(queue_key, json.dumps(job_1), json.dumps(job_2))

        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)

        # Get pending
        pending = await feeder._get_pending_crawls(tenant_id, redis_client, limit=10)

        # LPUSH adds to left, LRANGE returns left-to-right
        assert len(pending) == 2, "Should have 2 pending jobs"

        # Cleanup
        await redis_client.delete(queue_key)

    async def test_respects_limit_parameter(
        self, redis_client: aioredis.Redis
    ):
        """Should only retrieve up to limit jobs."""
        tenant_id = uuid4()
        queue_key = f"tenant:{tenant_id}:crawl_pending"

        # Add 5 jobs
        for i in range(5):
            job = {"job_id": str(uuid4()), "url": f"https://example.com/{i}"}
            await redis_client.rpush(queue_key, json.dumps(job))

        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)

        # Get only 2
        pending = await feeder._get_pending_crawls(tenant_id, redis_client, limit=2)

        assert len(pending) == 2, "Should respect limit parameter"

        # Cleanup
        await redis_client.delete(queue_key)

    async def test_returns_empty_list_when_no_pending(
        self, redis_client: aioredis.Redis
    ):
        """Should return empty list when no pending jobs."""
        tenant_id = uuid4()
        queue_key = f"tenant:{tenant_id}:crawl_pending"

        # Ensure queue is empty
        await redis_client.delete(queue_key)

        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)

        # Get pending
        pending = await feeder._get_pending_crawls(tenant_id, redis_client, limit=10)

        assert pending == [], "Should return empty list"

    async def test_handles_malformed_json_gracefully(
        self, redis_client: aioredis.Redis
    ):
        """Should skip malformed JSON entries without crashing."""
        tenant_id = uuid4()
        queue_key = f"tenant:{tenant_id}:crawl_pending"

        # Add valid and invalid jobs
        valid_job = {"job_id": str(uuid4()), "url": "https://example.com/valid"}
        await redis_client.rpush(queue_key, json.dumps(valid_job))
        await redis_client.rpush(queue_key, "not valid json {{{")

        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)

        # Get pending - should not raise
        pending = await feeder._get_pending_crawls(tenant_id, redis_client, limit=10)

        # Should have only the valid job
        assert len(pending) == 1, "Should skip malformed JSON"
        assert pending[0]["url"] == "https://example.com/valid"

        # Cleanup
        await redis_client.delete(queue_key)


@pytest.mark.integration
@pytest.mark.asyncio
class TestCrawlFeederMultiTenant:
    """Tests for multi-tenant isolation."""

    async def test_capacity_is_per_tenant(
        self, redis_client: aioredis.Redis, test_settings
    ):
        """Capacity should be tracked per-tenant."""
        tenant_1 = uuid4()
        tenant_2 = uuid4()
        max_concurrent = test_settings.tenant_worker_concurrency_limit

        # Tenant 1 has 3 active jobs
        await redis_client.set(f"tenant:{tenant_1}:active_jobs", "3")

        # Tenant 2 has 0 active jobs
        await redis_client.set(f"tenant:{tenant_2}:active_jobs", "0")

        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)
        feeder.settings = test_settings

        # Check capacities
        cap_1 = await feeder._get_available_capacity(tenant_1, redis_client)
        cap_2 = await feeder._get_available_capacity(tenant_2, redis_client)

        assert cap_1 == max_concurrent - 3, f"Tenant 1 should have {max_concurrent - 3} capacity"
        assert cap_2 == max_concurrent, f"Tenant 2 should have full {max_concurrent} capacity"

        # Cleanup
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

        # Add jobs to tenant 1's queue
        job_1 = {"job_id": str(uuid4()), "url": "https://tenant1.com/page"}
        await redis_client.rpush(f"tenant:{tenant_1}:crawl_pending", json.dumps(job_1))

        # Add jobs to tenant 2's queue
        job_2 = {"job_id": str(uuid4()), "url": "https://tenant2.com/page"}
        await redis_client.rpush(f"tenant:{tenant_2}:crawl_pending", json.dumps(job_2))

        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)

        # Get pending for each tenant
        pending_1 = await feeder._get_pending_crawls(tenant_1, redis_client, limit=10)
        pending_2 = await feeder._get_pending_crawls(tenant_2, redis_client, limit=10)

        assert len(pending_1) == 1, "Tenant 1 should have 1 job"
        assert pending_1[0]["url"] == "https://tenant1.com/page"

        assert len(pending_2) == 1, "Tenant 2 should have 1 job"
        assert pending_2[0]["url"] == "https://tenant2.com/page"

        # Cleanup
        await redis_client.delete(
            f"tenant:{tenant_1}:crawl_pending",
            f"tenant:{tenant_2}:crawl_pending",
        )


@pytest.mark.integration
@pytest.mark.asyncio
class TestCrawlFeederSplitBrain:
    """Tests for split-brain leader election scenarios.

    Risk: Network partitions can cause two nodes to believe they are
    the leader simultaneously. This is a fundamental distributed systems problem.
    """

    async def test_lock_acquisition_is_atomic(
        self, redis_client: aioredis.Redis
    ):
        """Verify lock acquisition uses SET NX (atomic operation).

        If the lock is not atomic, two feeders could both think they
        acquired it in a race condition.
        """
        await redis_client.delete("crawl_feeder:leader")

        mock_container = MagicMock()
        feeder_1 = CrawlFeeder(mock_container)
        feeder_2 = CrawlFeeder(mock_container)

        # Both try to acquire simultaneously using asyncio.gather
        results = await asyncio.gather(
            feeder_1._try_acquire_leader_lock(redis_client),
            feeder_2._try_acquire_leader_lock(redis_client),
        )

        # Exactly ONE should succeed (atomic SET NX)
        assert sum(results) == 1, (
            f"Expected exactly 1 leader, got {sum(results)}. "
            "Lock acquisition may not be atomic."
        )

        # Cleanup
        await redis_client.delete("crawl_feeder:leader")

    async def test_multiple_feeders_race_for_leadership(
        self, redis_client: aioredis.Redis
    ):
        """Test multiple feeders racing for leadership.

        Simulates cluster scenario where N workers start simultaneously.
        Only ONE should become leader.
        """
        await redis_client.delete("crawl_feeder:leader")

        mock_container = MagicMock()
        num_feeders = 5

        feeders = [CrawlFeeder(mock_container) for _ in range(num_feeders)]

        # All try to acquire leadership simultaneously
        results = await asyncio.gather(
            *[f._try_acquire_leader_lock(redis_client) for f in feeders]
        )

        # Exactly ONE should succeed
        winners = sum(results)
        assert winners == 1, (
            f"Expected 1 leader from {num_feeders} feeders, got {winners}. "
            "Split-brain scenario detected!"
        )

        # Cleanup
        await redis_client.delete("crawl_feeder:leader")

    async def test_lock_value_identifies_leader(
        self, redis_client: aioredis.Redis
    ):
        """Verify lock contains identifying information about the leader.

        This helps with debugging split-brain scenarios in production.
        """
        await redis_client.delete("crawl_feeder:leader")

        mock_container = MagicMock()
        feeder = CrawlFeeder(mock_container)

        await feeder._try_acquire_leader_lock(redis_client)

        # Lock should contain identifier
        lock_value = await redis_client.get("crawl_feeder:leader")
        assert lock_value is not None, "Lock should be set"
        assert len(lock_value.decode()) > 0, "Lock should contain identifier"

        # Cleanup
        await redis_client.delete("crawl_feeder:leader")

    async def test_expired_lock_can_be_reacquired(
        self, redis_client: aioredis.Redis
    ):
        """Verify another feeder can acquire expired lock.

        This is important for failover - if leader crashes, another
        worker should be able to take over after TTL expires.
        """
        await redis_client.delete("crawl_feeder:leader")

        mock_container = MagicMock()
        feeder_1 = CrawlFeeder(mock_container)
        feeder_2 = CrawlFeeder(mock_container)

        # Feeder 1 acquires lock
        result_1 = await feeder_1._try_acquire_leader_lock(redis_client)
        assert result_1 is True

        # Feeder 2 cannot acquire while lock is held
        result_2_before = await feeder_2._try_acquire_leader_lock(redis_client)
        assert result_2_before is False

        # Simulate lock expiry by setting very short TTL
        await redis_client.expire("crawl_feeder:leader", 1)
        await asyncio.sleep(1.5)  # Wait for expiry

        # Now feeder 2 can acquire
        result_2_after = await feeder_2._try_acquire_leader_lock(redis_client)
        assert result_2_after is True, "Feeder 2 should acquire after lock expires"

        # Cleanup
        await redis_client.delete("crawl_feeder:leader")

    async def test_lock_refresh_only_if_still_leader(
        self, redis_client: aioredis.Redis
    ):
        """Verify refresh doesn't work if we're no longer the leader.

        Risk: If our lock expired and another node took over, we shouldn't
        be able to refresh and think we're still the leader.

        Note: Current implementation uses simple EXPIRE which doesn't check
        ownership. This test documents the limitation.
        """
        await redis_client.delete("crawl_feeder:leader")

        mock_container = MagicMock()
        feeder_1 = CrawlFeeder(mock_container)
        feeder_2 = CrawlFeeder(mock_container)

        # Feeder 1 acquires lock
        await feeder_1._try_acquire_leader_lock(redis_client)

        # Simulate lock expiry and feeder 2 taking over
        await redis_client.delete("crawl_feeder:leader")
        await feeder_2._try_acquire_leader_lock(redis_client)

        # Feeder 1 tries to refresh (but feeder 2 now owns the lock)
        await feeder_1._refresh_leader_lock(redis_client)

        # Check who actually owns the lock now
        # Note: This documents current behavior - refresh extends ANY lock
        # A more robust implementation would check ownership before refresh
        ttl = await redis_client.ttl("crawl_feeder:leader")
        assert ttl > 0, "Lock should exist with TTL"

        # Cleanup
        await redis_client.delete("crawl_feeder:leader")
