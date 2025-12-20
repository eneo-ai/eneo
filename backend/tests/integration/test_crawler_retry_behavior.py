"""Integration tests for crawler retry behavior.

Tests the new per-job retry tracking system with real Redis:
- True exponential backoff calculation
- Per-job tracking (not per-tenant)
- Distinction between actual failures and busy signals
- Job age tracking for max_age enforcement
- Concurrent updates and race conditions
- Max retry/age exhaustion behavior
"""

import asyncio
import time
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from intric.worker.crawl.recovery import (
    calculate_exponential_backoff,
    update_job_retry_stats,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_job_retry_stats_tracks_per_job_not_per_tenant(
    redis_client: aioredis.Redis,
):
    """Verify retry stats are tracked per-job, not per-tenant.

    Old system used tenant:{id}:limiter_backoff.
    New system uses job:{id}:start_time and job:{id}:retry_count.

    This ensures jobs within the same tenant have independent retry tracking.
    """
    # Create two jobs for same hypothetical tenant
    job_1 = uuid4()
    job_2 = uuid4()

    # Simulate failures for job_1 (3 failures)
    for _ in range(3):
        await update_job_retry_stats(
            job_id=job_1,
            redis_client=redis_client,
            is_actual_failure=True,
            max_age_seconds=1800,
        )

    # Simulate failures for job_2 (1 failure)
    await update_job_retry_stats(
        job_id=job_2,
        redis_client=redis_client,
        is_actual_failure=True,
        max_age_seconds=1800,
    )

    # Verify independent tracking
    job_1_count = await redis_client.get(f"job:{job_1}:retry_count")
    job_2_count = await redis_client.get(f"job:{job_2}:retry_count")

    assert int(job_1_count) == 3, "Job 1 should have 3 failures"
    assert int(job_2_count) == 1, "Job 2 should have 1 failure (independent)"

    # Cleanup
    await redis_client.delete(
        f"job:{job_1}:start_time",
        f"job:{job_1}:retry_count",
        f"job:{job_2}:start_time",
        f"job:{job_2}:retry_count",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_busy_signal_does_not_increment_retry_count(
    redis_client: aioredis.Redis,
):
    """Verify busy signals (concurrency wait) don't increment retry counter.

    Critical behavior: Jobs waiting for concurrency slots should NOT be
    penalized with retry count increments. Only actual failures (network
    errors, timeouts, etc.) should count.
    """
    job_id = uuid4()

    # Simulate 5 busy signals (waiting for slot)
    for _ in range(5):
        retry_count, job_age = await update_job_retry_stats(
            job_id=job_id,
            redis_client=redis_client,
            is_actual_failure=False,  # Busy signal, not real failure
            max_age_seconds=1800,
        )

    # Retry count should still be 0 (no actual failures)
    count = await redis_client.get(f"job:{job_id}:retry_count")
    assert count is None, "Retry count should not exist after only busy signals"

    # But start_time should be tracked (for max_age enforcement)
    start_time = await redis_client.get(f"job:{job_id}:start_time")
    assert start_time is not None, "Start time should be tracked for max_age"

    # Cleanup
    await redis_client.delete(
        f"job:{job_id}:start_time",
        f"job:{job_id}:retry_count",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_actual_failure_increments_retry_count(
    redis_client: aioredis.Redis,
):
    """Verify actual failures increment the retry counter."""
    job_id = uuid4()

    # Simulate 3 actual failures (network errors, etc.)
    for i in range(3):
        retry_count, job_age = await update_job_retry_stats(
            job_id=job_id,
            redis_client=redis_client,
            is_actual_failure=True,  # Real failure
            max_age_seconds=1800,
        )

    # Retry count should be 3
    count = await redis_client.get(f"job:{job_id}:retry_count")
    assert int(count) == 3, "Should have 3 actual failures"

    # Cleanup
    await redis_client.delete(
        f"job:{job_id}:start_time",
        f"job:{job_id}:retry_count",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mixed_busy_and_failure_only_counts_failures(
    redis_client: aioredis.Redis,
):
    """Verify mixed busy signals and failures only counts actual failures.

    Scenario:
    - Job attempts run, hits concurrency limit (busy signal) 3 times
    - Job finally gets slot, hits network error (actual failure)
    - Job attempts run again, hits concurrency limit 2 times
    - Job finally gets slot, hits another network error
    - Final retry count should be 2 (only the network errors)
    """
    job_id = uuid4()

    # 3 busy signals
    for _ in range(3):
        await update_job_retry_stats(
            job_id=job_id,
            redis_client=redis_client,
            is_actual_failure=False,
            max_age_seconds=1800,
        )

    # 1 actual failure
    await update_job_retry_stats(
        job_id=job_id,
        redis_client=redis_client,
        is_actual_failure=True,
        max_age_seconds=1800,
    )

    # 2 more busy signals
    for _ in range(2):
        await update_job_retry_stats(
            job_id=job_id,
            redis_client=redis_client,
            is_actual_failure=False,
            max_age_seconds=1800,
        )

    # 1 more actual failure
    await update_job_retry_stats(
        job_id=job_id,
        redis_client=redis_client,
        is_actual_failure=True,
        max_age_seconds=1800,
    )

    # Should have exactly 2 failures (ignoring 5 busy signals)
    count = await redis_client.get(f"job:{job_id}:retry_count")
    assert int(count) == 2, "Should have 2 actual failures, ignoring busy signals"

    # Cleanup
    await redis_client.delete(
        f"job:{job_id}:start_time",
        f"job:{job_id}:retry_count",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_job_age_tracking_from_first_attempt(
    redis_client: aioredis.Redis,
):
    """Verify job age is tracked from the first attempt (NX flag behavior)."""
    job_id = uuid4()

    # First attempt - should set start_time
    retry_count_1, job_age_1 = await update_job_retry_stats(
        job_id=job_id,
        redis_client=redis_client,
        is_actual_failure=False,
        max_age_seconds=1800,
    )

    # Initial age should be ~0
    assert job_age_1 < 1.0, "Initial job age should be near 0"

    # Wait a bit
    import asyncio

    await asyncio.sleep(0.5)

    # Second attempt - should NOT update start_time (NX flag)
    retry_count_2, job_age_2 = await update_job_retry_stats(
        job_id=job_id,
        redis_client=redis_client,
        is_actual_failure=False,
        max_age_seconds=1800,
    )

    # Age should be ~0.5s now
    assert 0.4 < job_age_2 < 1.0, f"Job age should be ~0.5s, got {job_age_2}"

    # Cleanup
    await redis_client.delete(
        f"job:{job_id}:start_time",
        f"job:{job_id}:retry_count",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_keys_have_proper_ttl(
    redis_client: aioredis.Redis,
):
    """Verify Redis keys have TTL set (max_age + 1 hour buffer)."""
    job_id = uuid4()
    max_age = 1800  # 30 minutes

    await update_job_retry_stats(
        job_id=job_id,
        redis_client=redis_client,
        is_actual_failure=True,
        max_age_seconds=max_age,
    )

    # Check TTL on keys
    start_ttl = await redis_client.ttl(f"job:{job_id}:start_time")
    count_ttl = await redis_client.ttl(f"job:{job_id}:retry_count")

    # Expected TTL is max_age + 3600 = 5400 seconds
    # Allow some slack for test execution time
    expected_min_ttl = max_age + 3600 - 10

    assert start_ttl >= expected_min_ttl, f"Start time TTL should be ~{max_age + 3600}s"
    assert count_ttl >= expected_min_ttl, f"Retry count TTL should be ~{max_age + 3600}s"

    # Cleanup
    await redis_client.delete(
        f"job:{job_id}:start_time",
        f"job:{job_id}:retry_count",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_exponential_backoff_with_real_calculation(
    redis_client: aioredis.Redis,
):
    """Verify exponential backoff calculation with real values.

    True exponential: base * 2^(attempt-1)
    With full jitter: random.uniform(0, capped_delay)
    """
    base_delay = 60.0
    max_delay = 300.0

    # Test several attempts
    attempt_1_delays = [calculate_exponential_backoff(1, base_delay, max_delay) for _ in range(100)]
    attempt_2_delays = [calculate_exponential_backoff(2, base_delay, max_delay) for _ in range(100)]
    attempt_3_delays = [calculate_exponential_backoff(3, base_delay, max_delay) for _ in range(100)]
    attempt_4_delays = [calculate_exponential_backoff(4, base_delay, max_delay) for _ in range(100)]

    # Verify ranges (with jitter)
    # Attempt 1: 60 * 2^0 = 60 -> [0, 60]
    assert all(0 <= d <= 60 for d in attempt_1_delays)

    # Attempt 2: 60 * 2^1 = 120 -> [0, 120]
    assert all(0 <= d <= 120 for d in attempt_2_delays)

    # Attempt 3: 60 * 2^2 = 240 -> [0, 240]
    assert all(0 <= d <= 240 for d in attempt_3_delays)

    # Attempt 4: 60 * 2^3 = 480, capped at 300 -> [0, 300]
    assert all(0 <= d <= 300 for d in attempt_4_delays)

    # Verify average increases (despite jitter)
    avg_1 = sum(attempt_1_delays) / len(attempt_1_delays)
    avg_2 = sum(attempt_2_delays) / len(attempt_2_delays)
    avg_3 = sum(attempt_3_delays) / len(attempt_3_delays)
    avg_4 = sum(attempt_4_delays) / len(attempt_4_delays)

    assert avg_2 > avg_1, "Attempt 2 average should exceed attempt 1"
    assert avg_3 > avg_2, "Attempt 3 average should exceed attempt 2"
    assert avg_4 > avg_3, "Attempt 4 average should exceed attempt 3"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_job_updates_race_condition(
    redis_client: aioredis.Redis,
):
    """Test concurrent updates to the same job's retry stats.

    Risk: Two workers processing retries for the same job simultaneously
    could corrupt the retry count if not handled atomically.

    This test verifies that concurrent updates don't lose increments.
    """
    job_id = uuid4()
    num_concurrent_updates = 10

    async def update_job_stats():
        """Simulate a worker updating job retry stats."""
        await update_job_retry_stats(
            job_id=job_id,
            redis_client=redis_client,
            is_actual_failure=True,
            max_age_seconds=1800,
        )

    # Run concurrent updates
    tasks = [update_job_stats() for _ in range(num_concurrent_updates)]
    await asyncio.gather(*tasks)

    # Verify all updates were counted (no lost increments)
    final_count = await redis_client.get(f"job:{job_id}:retry_count")
    assert int(final_count) == num_concurrent_updates, (
        f"Expected {num_concurrent_updates} retries, got {final_count}. "
        "Race condition may have caused lost increments."
    )

    # Cleanup
    await redis_client.delete(
        f"job:{job_id}:start_time",
        f"job:{job_id}:retry_count",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_max_retry_count_behavior(
    redis_client: aioredis.Redis,
):
    """Test behavior when job exceeds maximum retry count.

    This verifies the system tracks retry counts correctly even
    when a job fails many times. The actual max_retries enforcement
    should happen in the calling code, but we verify the counter works.
    """
    job_id = uuid4()
    max_retries = 5

    # Simulate exceeding max retries
    for i in range(max_retries + 3):  # Go 3 beyond max
        retry_count, job_age = await update_job_retry_stats(
            job_id=job_id,
            redis_client=redis_client,
            is_actual_failure=True,
            max_age_seconds=1800,
        )

    # Verify final count is tracked correctly
    final_count = await redis_client.get(f"job:{job_id}:retry_count")
    assert int(final_count) == max_retries + 3, (
        f"Expected {max_retries + 3} retries tracked, got {final_count}"
    )

    # The calling code should check: if retry_count > max_retries: abandon job
    # This test just verifies the counter keeps counting

    # Cleanup
    await redis_client.delete(
        f"job:{job_id}:start_time",
        f"job:{job_id}:retry_count",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_job_age_exceeds_max_age(
    redis_client: aioredis.Redis,
):
    """Test behavior when job age exceeds max_age_seconds.

    This verifies job_age is correctly calculated even when it
    exceeds the max_age threshold. The actual abandonment should
    happen in calling code, but we verify age tracking works.
    """
    job_id = uuid4()
    max_age_seconds = 60  # 1 minute for test

    # First update - sets start_time
    retry_count_1, job_age_1 = await update_job_retry_stats(
        job_id=job_id,
        redis_client=redis_client,
        is_actual_failure=False,
        max_age_seconds=max_age_seconds,
    )
    assert job_age_1 < 1.0, "Initial age should be near 0"

    # Manually set start_time to simulate old job (2 minutes ago)
    old_start_time = time.time() - 120  # 2 minutes ago
    await redis_client.set(f"job:{job_id}:start_time", str(old_start_time))

    # Second update - should report age > max_age
    retry_count_2, job_age_2 = await update_job_retry_stats(
        job_id=job_id,
        redis_client=redis_client,
        is_actual_failure=False,
        max_age_seconds=max_age_seconds,
    )

    # Job age should be ~120 seconds (exceeds max_age of 60)
    assert job_age_2 >= 119, f"Job age should be ~120s, got {job_age_2}"
    assert job_age_2 > max_age_seconds, (
        f"Job age {job_age_2} should exceed max_age {max_age_seconds}"
    )

    # The calling code should check: if job_age > max_age_seconds: abandon job

    # Cleanup
    await redis_client.delete(
        f"job:{job_id}:start_time",
        f"job:{job_id}:retry_count",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_count_returned_correctly(
    redis_client: aioredis.Redis,
):
    """Verify update_job_retry_stats returns correct retry_count.

    The returned retry_count should match what's in Redis.
    """
    job_id = uuid4()

    # First failure
    retry_count_1, _ = await update_job_retry_stats(
        job_id=job_id,
        redis_client=redis_client,
        is_actual_failure=True,
        max_age_seconds=1800,
    )
    assert retry_count_1 == 1, "First failure should return retry_count=1"

    # Second failure
    retry_count_2, _ = await update_job_retry_stats(
        job_id=job_id,
        redis_client=redis_client,
        is_actual_failure=True,
        max_age_seconds=1800,
    )
    assert retry_count_2 == 2, "Second failure should return retry_count=2"

    # Busy signal (should not increment)
    retry_count_3, _ = await update_job_retry_stats(
        job_id=job_id,
        redis_client=redis_client,
        is_actual_failure=False,
        max_age_seconds=1800,
    )
    assert retry_count_3 == 2, "Busy signal should return same retry_count=2"

    # Third failure
    retry_count_4, _ = await update_job_retry_stats(
        job_id=job_id,
        redis_client=redis_client,
        is_actual_failure=True,
        max_age_seconds=1800,
    )
    assert retry_count_4 == 3, "Third failure should return retry_count=3"

    # Cleanup
    await redis_client.delete(
        f"job:{job_id}:start_time",
        f"job:{job_id}:retry_count",
    )
