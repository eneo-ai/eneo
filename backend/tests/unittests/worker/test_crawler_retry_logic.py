"""Unit tests for crawler retry logic.

Tests the new per-job retry tracking system with:
- True exponential backoff with full jitter
- Per-job tracking (vs old per-tenant tracking)
- Distinction between actual failures and busy signals
"""

import random
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.worker.crawl_tasks import (
    _calculate_exponential_backoff,
    _update_job_retry_stats,
)


class TestCalculateExponentialBackoff:
    """Unit tests for _calculate_exponential_backoff function."""

    def test_first_attempt_returns_within_base_delay(self):
        """First attempt (attempt=1) should return delay in [0, base_delay]."""
        random.seed(42)  # For reproducibility
        base_delay = 60.0
        max_delay = 300.0

        delays = [_calculate_exponential_backoff(1, base_delay, max_delay) for _ in range(100)]

        # All delays should be between 0 and base_delay (with full jitter)
        assert all(0 <= d <= base_delay for d in delays), "First attempt should use base_delay"
        # Should have variety (full jitter means not all values are the same)
        assert len(set(round(d, 1) for d in delays)) > 1, "Should have jitter variety"

    def test_second_attempt_doubles_max_delay(self):
        """Second attempt (attempt=2) should return delay in [0, 2*base_delay]."""
        random.seed(42)
        base_delay = 60.0
        max_delay = 300.0

        delays = [_calculate_exponential_backoff(2, base_delay, max_delay) for _ in range(100)]

        # Max possible delay is 2 * base_delay = 120
        assert all(0 <= d <= base_delay * 2 for d in delays), "Second attempt uses 2x base"
        # Some delays should exceed base_delay (2^1 = 2 multiplier)
        assert any(d > base_delay for d in delays), "Some delays should exceed base"

    def test_exponential_growth_2_to_power_attempt_minus_1(self):
        """Verify true exponential: base * 2^(attempt-1)."""
        base_delay = 10.0
        max_delay = 1000.0  # High cap to avoid capping

        # Test multiple attempts with seed for determinism
        random.seed(123)

        # Attempt 3: 10 * 2^2 = 40s max
        delays_3 = [_calculate_exponential_backoff(3, base_delay, max_delay) for _ in range(50)]
        assert all(0 <= d <= 40 for d in delays_3), "Attempt 3 max should be 40s"

        # Attempt 4: 10 * 2^3 = 80s max
        delays_4 = [_calculate_exponential_backoff(4, base_delay, max_delay) for _ in range(50)]
        assert all(0 <= d <= 80 for d in delays_4), "Attempt 4 max should be 80s"

        # Attempt 5: 10 * 2^4 = 160s max
        delays_5 = [_calculate_exponential_backoff(5, base_delay, max_delay) for _ in range(50)]
        assert all(0 <= d <= 160 for d in delays_5), "Attempt 5 max should be 160s"

    def test_max_delay_caps_exponential_growth(self):
        """Verify max_delay caps the exponential growth."""
        base_delay = 60.0
        max_delay = 100.0

        random.seed(42)

        # Attempt 4: 60 * 2^3 = 480s, but capped at 100s
        delays = [_calculate_exponential_backoff(4, base_delay, max_delay) for _ in range(100)]

        assert all(0 <= d <= max_delay for d in delays), "All delays should be capped"
        # Some delays should approach max_delay (since full jitter is [0, capped])
        assert any(d > max_delay * 0.5 for d in delays), "Should see values in upper range"

    def test_very_high_attempt_stays_capped(self):
        """Very high attempt numbers should still respect max_delay cap."""
        base_delay = 60.0
        max_delay = 300.0

        random.seed(42)

        # Attempt 100 would be 60 * 2^99, but should cap at 300
        delays = [_calculate_exponential_backoff(100, base_delay, max_delay) for _ in range(50)]

        assert all(0 <= d <= max_delay for d in delays), "High attempts should stay capped"

    def test_full_jitter_returns_non_negative(self):
        """Full jitter should always return non-negative values."""
        base_delay = 60.0
        max_delay = 300.0

        random.seed(42)

        for attempt in range(1, 20):
            delays = [_calculate_exponential_backoff(attempt, base_delay, max_delay) for _ in range(50)]
            assert all(d >= 0 for d in delays), f"Attempt {attempt} had negative delay"

    def test_jitter_distribution_covers_range(self):
        """Full jitter should distribute values across [0, max] range."""
        random.seed(42)
        base_delay = 100.0
        max_delay = 100.0

        delays = [_calculate_exponential_backoff(1, base_delay, max_delay) for _ in range(1000)]

        # Check distribution covers full range (roughly)
        min_delay = min(delays)
        max_seen = max(delays)

        assert min_delay < 20, "Should have low values in distribution"
        assert max_seen > 80, "Should have high values in distribution"

    def test_attempt_zero_boundary(self):
        """Attempt=0 should be handled safely (edge case).

        If code uses 2^(attempt-1), attempt=0 gives 2^(-1) = 0.5
        This should still return a valid non-negative delay.
        """
        random.seed(42)
        base_delay = 60.0
        max_delay = 300.0

        # This should NOT crash and should return valid delay
        delays = [_calculate_exponential_backoff(0, base_delay, max_delay) for _ in range(50)]

        # All delays should be non-negative
        assert all(d >= 0 for d in delays), "Attempt 0 should return non-negative delays"

        # With 2^(-1) = 0.5, max delay is 60 * 0.5 = 30
        # With full jitter: [0, 30]
        assert all(d <= base_delay for d in delays), "Attempt 0 delays should be reasonable"

    def test_negative_attempt_boundary(self):
        """Negative attempt should be handled safely (edge case).

        If code doesn't validate input, negative attempts could cause issues.
        """
        random.seed(42)
        base_delay = 60.0
        max_delay = 300.0

        # This should NOT crash
        try:
            delays = [_calculate_exponential_backoff(-1, base_delay, max_delay) for _ in range(50)]
            # If it doesn't crash, delays should still be non-negative
            assert all(d >= 0 for d in delays), "Negative attempt should return non-negative delays"
        except (ValueError, OverflowError):
            # If the function validates and raises, that's also acceptable
            pass

    def test_very_large_base_delay(self):
        """Very large base_delay should be capped by max_delay."""
        random.seed(42)
        base_delay = 10000.0  # Unreasonably large
        max_delay = 300.0

        delays = [_calculate_exponential_backoff(1, base_delay, max_delay) for _ in range(50)]

        # All delays should be capped at max_delay
        assert all(0 <= d <= max_delay for d in delays), "Large base_delay should be capped"

    def test_zero_max_delay(self):
        """Zero max_delay should return zero delays."""
        random.seed(42)
        base_delay = 60.0
        max_delay = 0.0

        delays = [_calculate_exponential_backoff(1, base_delay, max_delay) for _ in range(50)]

        # With max_delay=0, all delays should be 0
        assert all(d == 0 for d in delays), "Zero max_delay should return zero delays"


class TestUpdateJobRetryStats:
    """Unit tests for _update_job_retry_stats function."""

    def _create_mock_redis_pipeline(self, execute_results: list):
        """Helper to create properly mocked Redis client with pipeline.

        Redis pipeline pattern:
        - pipeline() returns a context manager
        - Context manager's __aenter__ returns the pipe
        - Pipe methods (set, get, incr, expire) are SYNC (queue commands)
        - Only execute() is ASYNC (sends commands to Redis)
        """
        # Pipeline methods are sync (they queue commands, don't execute)
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=execute_results)

        # Context manager for `async with redis.pipeline() as pipe:`
        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        # Redis client
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_context)

        return mock_redis, mock_pipe

    @pytest.mark.asyncio
    async def test_returns_defaults_when_redis_is_none(self):
        """Graceful degradation: no Redis returns (0, 0.0)."""
        job_id = uuid4()

        retry_count, job_age = await _update_job_retry_stats(
            job_id=job_id,
            redis_client=None,
            is_actual_failure=True,
            max_age_seconds=1800,
        )

        assert retry_count == 0
        assert job_age == 0.0

    @pytest.mark.asyncio
    async def test_actual_failure_increments_counter(self):
        """is_actual_failure=True should increment the retry counter."""
        job_id = uuid4()

        # Results for: SET NX, GET start_time, INCR, EXPIRE
        mock_redis, mock_pipe = self._create_mock_redis_pipeline([
            True,       # SET NX result (set succeeded)
            b"1000.0",  # GET start_time
            2,          # INCR result
            True,       # EXPIRE result
        ])

        with patch("intric.worker.crawl_tasks.time.time", return_value=1100.0):
            await _update_job_retry_stats(
                job_id=job_id,
                redis_client=mock_redis,
                is_actual_failure=True,
                max_age_seconds=1800,
            )

        # Should have called incr (is_actual_failure=True)
        assert mock_pipe.incr.called, "Should increment counter for actual failure"

    @pytest.mark.asyncio
    async def test_busy_signal_does_not_increment_counter(self):
        """is_actual_failure=False should NOT increment the retry counter."""
        job_id = uuid4()

        # Results for: SET NX, GET start_time, GET retry_count (no INCR)
        mock_redis, mock_pipe = self._create_mock_redis_pipeline([
            True,       # SET NX result
            b"1000.0",  # GET start_time
            b"0",       # GET retry_count (existing)
        ])

        with patch("intric.worker.crawl_tasks.time.time", return_value=1050.0):
            await _update_job_retry_stats(
                job_id=job_id,
                redis_client=mock_redis,
                is_actual_failure=False,  # Just busy signal
                max_age_seconds=1800,
            )

        # Should NOT have called incr (is_actual_failure=False)
        assert not mock_pipe.incr.called, "Should NOT increment counter for busy signal"

    @pytest.mark.asyncio
    async def test_uses_correct_redis_keys(self):
        """Verify Redis keys follow job:{id}:* pattern."""
        job_id = uuid4()

        mock_redis, mock_pipe = self._create_mock_redis_pipeline([
            True, b"1000.0", 1, True
        ])

        with patch("intric.worker.crawl_tasks.time.time", return_value=1100.0):
            await _update_job_retry_stats(
                job_id=job_id,
                redis_client=mock_redis,
                is_actual_failure=True,
                max_age_seconds=1800,
            )

        # Check the keys used
        expected_start_key = f"job:{job_id}:start_time"

        # Verify set was called with start_time key
        assert mock_pipe.set.called, "Should call set on pipeline"
        set_calls = [str(c) for c in mock_pipe.set.call_args_list]
        assert any(expected_start_key in c for c in set_calls), f"Should use {expected_start_key}"

    @pytest.mark.asyncio
    async def test_handles_redis_error_gracefully(self):
        """Redis errors should not crash, return defaults."""
        job_id = uuid4()

        mock_redis = MagicMock()
        mock_redis.pipeline.side_effect = Exception("Redis connection failed")

        # Should not raise, should return defaults
        retry_count, job_age = await _update_job_retry_stats(
            job_id=job_id,
            redis_client=mock_redis,
            is_actual_failure=True,
            max_age_seconds=1800,
        )

        # Graceful degradation
        assert retry_count == 0
        assert job_age == 0.0

    @pytest.mark.asyncio
    async def test_first_attempt_sets_start_time_with_nx(self):
        """First attempt should set start_time with NX flag (only if not exists)."""
        job_id = uuid4()

        mock_redis, mock_pipe = self._create_mock_redis_pipeline([
            True, b"1000.0", 1, True
        ])

        with patch("intric.worker.crawl_tasks.time.time", return_value=1000.0):
            await _update_job_retry_stats(
                job_id=job_id,
                redis_client=mock_redis,
                is_actual_failure=True,
                max_age_seconds=1800,
            )

        # Check that set was called with nx=True
        assert mock_pipe.set.called, "Should call set on pipeline"
        call_kwargs = mock_pipe.set.call_args
        assert call_kwargs.kwargs.get("nx") is True, "Should use NX flag"

    @pytest.mark.asyncio
    async def test_ttl_includes_buffer_over_max_age(self):
        """TTL should be max_age_seconds + 3600 (1 hour buffer)."""
        job_id = uuid4()
        max_age = 1800  # 30 minutes

        mock_redis, mock_pipe = self._create_mock_redis_pipeline([
            True, b"1000.0", 1, True
        ])

        with patch("intric.worker.crawl_tasks.time.time", return_value=1000.0):
            await _update_job_retry_stats(
                job_id=job_id,
                redis_client=mock_redis,
                is_actual_failure=True,
                max_age_seconds=max_age,
            )

        # Check TTL in set call
        assert mock_pipe.set.called, "Should call set on pipeline"
        call_kwargs = mock_pipe.set.call_args
        expected_ttl = max_age + 3600
        assert call_kwargs.kwargs.get("ex") == expected_ttl, f"TTL should be {expected_ttl}"

    @pytest.mark.asyncio
    async def test_redis_pipeline_execute_failure(self):
        """Test graceful handling when pipeline execute() fails.

        Risk: If Redis fails mid-pipeline (after commands are queued but
        during execute()), we should return defaults, not crash.
        """
        job_id = uuid4()

        # Create mock that fails on execute
        mock_pipe = MagicMock()
        mock_pipe.execute = AsyncMock(side_effect=Exception("Redis connection lost"))

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_context)

        # Should not crash, should return defaults
        retry_count, job_age = await _update_job_retry_stats(
            job_id=job_id,
            redis_client=mock_redis,
            is_actual_failure=True,
            max_age_seconds=1800,
        )

        assert retry_count == 0, "Should return default retry_count on failure"
        assert job_age == 0.0, "Should return default job_age on failure"

    @pytest.mark.asyncio
    async def test_redis_pipeline_partial_results(self):
        """Test handling of partial/incomplete pipeline results.

        Risk: Pipeline returns fewer results than expected due to
        partial execution or Redis issues.
        """
        job_id = uuid4()

        # Return fewer results than expected (missing some pipeline results)
        mock_redis, mock_pipe = self._create_mock_redis_pipeline([
            True,  # Only SET result, missing GET and INCR results
        ])

        with patch("intric.worker.crawl_tasks.time.time", return_value=1000.0):
            # This should handle incomplete results gracefully
            retry_count, job_age = await _update_job_retry_stats(
                job_id=job_id,
                redis_client=mock_redis,
                is_actual_failure=True,
                max_age_seconds=1800,
            )

        # Should return some form of result without crashing
        # The specific behavior depends on implementation
        assert isinstance(retry_count, int), "Should return int retry_count"
        assert isinstance(job_age, float), "Should return float job_age"

    @pytest.mark.asyncio
    async def test_multiple_concurrent_mock_calls(self):
        """Test that mocked pipeline can handle multiple sequential calls.

        This verifies our mock setup is correct for tests that make
        multiple calls to _update_job_retry_stats.
        """
        job_id = uuid4()

        # First call
        mock_redis_1, mock_pipe_1 = self._create_mock_redis_pipeline([
            True, b"1000.0", 1, True
        ])

        with patch("intric.worker.crawl_tasks.time.time", return_value=1000.0):
            retry_count_1, _ = await _update_job_retry_stats(
                job_id=job_id,
                redis_client=mock_redis_1,
                is_actual_failure=True,
                max_age_seconds=1800,
            )

        # Second call with fresh mock
        mock_redis_2, mock_pipe_2 = self._create_mock_redis_pipeline([
            False, b"1000.0", 2, True  # SET returns False (key exists), INCR returns 2
        ])

        with patch("intric.worker.crawl_tasks.time.time", return_value=1050.0):
            retry_count_2, _ = await _update_job_retry_stats(
                job_id=job_id,
                redis_client=mock_redis_2,
                is_actual_failure=True,
                max_age_seconds=1800,
            )

        # Both calls should have worked
        assert mock_pipe_1.incr.called, "First call should have incremented"
        assert mock_pipe_2.incr.called, "Second call should have incremented"
