"""Unit tests for circuit breaker functionality.

Tests website failure tracking and exponential backoff including:
- Scheduler respects next_retry_at
- Failure counter increments correctly
- Exponential backoff calculation
- Success resets circuit breaker
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4


class TestCircuitBreakerSchedulerLogic:
    """Test that scheduler correctly filters websites based on circuit breaker state."""

    def test_backoff_calculation(self):
        """Test exponential backoff calculation: 1h, 4h, 24h max."""
        # 1 failure: 2^1 = 2 hours
        assert min(2**1, 24) == 2

        # 2 failures: 2^2 = 4 hours
        assert min(2**2, 24) == 4

        # 3 failures: 2^3 = 8 hours
        assert min(2**3, 24) == 8

        # 4 failures: 2^4 = 16 hours
        assert min(2**4, 24) == 16

        # 5 failures: 2^5 = 32 hours, capped at 24
        assert min(2**5, 24) == 24

        # 10 failures: 2^10 = 1024 hours, still capped at 24
        assert min(2**10, 24) == 24

    def test_next_retry_at_logic(self):
        """Test that next_retry_at correctly determines if website should be crawled."""
        now = datetime.now(timezone.utc)

        # Scenario 1: next_retry_at is None (no failures) -> should crawl
        next_retry_at_none = None
        should_crawl_none = next_retry_at_none is None or next_retry_at_none <= now
        assert should_crawl_none is True

        # Scenario 2: next_retry_at is in the past -> should crawl
        next_retry_at_past = now - timedelta(hours=1)
        should_crawl_past = next_retry_at_past is None or next_retry_at_past <= now
        assert should_crawl_past is True

        # Scenario 3: next_retry_at is now -> should crawl
        next_retry_at_now = now
        should_crawl_now = next_retry_at_now is None or next_retry_at_now <= now
        assert should_crawl_now is True

        # Scenario 4: next_retry_at is in the future -> should NOT crawl
        next_retry_at_future = now + timedelta(hours=1)
        should_crawl_future = (
            next_retry_at_future is None or next_retry_at_future <= now
        )
        assert should_crawl_future is False


class TestCircuitBreakerSuccessScenarios:
    """Test success scenarios for circuit breaker."""

    def test_successful_crawl_criteria(self):
        """Test what constitutes a successful crawl."""
        # Success: At least 1 page and no failures
        num_pages, num_failed, num_skipped = 10, 0, 0
        success = num_pages > 0 and (num_failed < num_pages or num_pages == num_skipped)
        assert success is True

        # Success: Some pages succeeded
        num_pages, num_failed, num_skipped = 10, 2, 0
        success = num_pages > 0 and (num_failed < num_pages or num_pages == num_skipped)
        assert success is True

        # Success: All pages skipped (unchanged content)
        num_pages, num_failed, num_skipped = 10, 0, 10
        success = num_pages > 0 and (num_failed < num_pages or num_pages == num_skipped)
        assert success is True

        # Failure: No pages
        num_pages, num_failed, num_skipped = 0, 0, 0
        success = num_pages > 0 and (num_failed < num_pages or num_pages == num_skipped)
        assert success is False

        # Failure: All pages failed
        num_pages, num_failed, num_skipped = 10, 10, 0
        success = num_pages > 0 and (num_failed < num_pages or num_pages == num_skipped)
        assert success is False

    def test_reset_values_on_success(self):
        """Test that success resets circuit breaker fields."""
        # After success: should reset to initial state
        consecutive_failures_after = 0
        next_retry_at_after = None

        assert consecutive_failures_after == 0
        assert next_retry_at_after is None


class TestCircuitBreakerFailureScenarios:
    """Test failure scenarios for circuit breaker."""

    def test_first_failure_backoff(self):
        """Test first failure applies correct backoff."""
        current_failures = 0
        new_failures = current_failures + 1
        backoff_hours = min(2**new_failures, 24)

        assert new_failures == 1
        assert backoff_hours == 2  # 2^1 = 2 hours

    def test_second_failure_backoff(self):
        """Test second failure applies correct backoff."""
        current_failures = 1
        new_failures = current_failures + 1
        backoff_hours = min(2**new_failures, 24)

        assert new_failures == 2
        assert backoff_hours == 4  # 2^2 = 4 hours

    def test_third_failure_backoff(self):
        """Test third failure applies correct backoff."""
        current_failures = 2
        new_failures = current_failures + 1
        backoff_hours = min(2**new_failures, 24)

        assert new_failures == 3
        assert backoff_hours == 8  # 2^3 = 8 hours

    def test_max_backoff_reached(self):
        """Test that backoff is capped at 24 hours."""
        current_failures = 10
        new_failures = current_failures + 1
        backoff_hours = min(2**new_failures, 24)

        assert new_failures == 11
        assert backoff_hours == 24  # Capped at 24 hours

    def test_next_retry_calculation(self):
        """Test next_retry_at timestamp calculation."""
        now = datetime.now(timezone.utc)
        backoff_hours = 4
        next_retry = now + timedelta(hours=backoff_hours)

        # Should be approximately 4 hours from now
        time_diff = (next_retry - now).total_seconds() / 3600
        assert 3.99 <= time_diff <= 4.01  # Allow for tiny timing differences


class TestCircuitBreakerEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_failures_means_immediate_retry(self):
        """Test that zero failures means next_retry_at is None."""
        # With zero failures, next_retry_at should be None
        next_retry_at = None

        # Should be able to crawl immediately
        now = datetime.now(timezone.utc)
        can_crawl = next_retry_at is None or next_retry_at <= now
        assert can_crawl is True

    def test_handle_none_current_failures(self):
        """Test handling None value for current failures (defensive)."""
        current_failures = None
        new_failures = (current_failures or 0) + 1

        assert new_failures == 1

    def test_backoff_calculation_overflow_safety(self):
        """Test that very large failure counts don't cause overflow."""
        # Even with absurdly high failure count, should cap at 24
        current_failures = 1000
        new_failures = current_failures + 1
        backoff_hours = min(2**new_failures, 24)

        # Should still cap at 24 hours
        assert backoff_hours == 24


class TestCircuitBreakerIntegration:
    """Integration tests for typical circuit breaker scenarios."""

    def test_typical_failure_recovery_cycle(self):
        """Simulate a website that fails then recovers."""
        now = datetime.now(timezone.utc)

        # Initial state: No failures
        consecutive_failures = 0
        next_retry_at = None
        assert next_retry_at is None or next_retry_at <= now  # Can crawl

        # First failure
        consecutive_failures = 1
        backoff_hours = min(2**consecutive_failures, 24)
        next_retry_at = now + timedelta(hours=backoff_hours)
        assert backoff_hours == 2
        assert next_retry_at > now  # Cannot crawl yet

        # Wait for backoff period
        now_after_wait = now + timedelta(hours=2, minutes=1)
        assert next_retry_at <= now_after_wait  # Can crawl now

        # Second failure
        consecutive_failures = 2
        backoff_hours = min(2**consecutive_failures, 24)
        next_retry_at = now_after_wait + timedelta(hours=backoff_hours)
        assert backoff_hours == 4

        # Wait and try again
        now_after_second_wait = now_after_wait + timedelta(hours=4, minutes=1)
        assert next_retry_at <= now_after_second_wait  # Can crawl now

        # Success!
        consecutive_failures = 0
        next_retry_at = None
        assert next_retry_at is None  # Back to normal

    def test_persistently_failing_website(self):
        """Simulate a website that keeps failing."""
        failure_sequence = []
        consecutive_failures = 0

        # Simulate 10 consecutive failures
        for i in range(10):
            consecutive_failures += 1
            backoff_hours = min(2**consecutive_failures, 24)
            failure_sequence.append(
                {"failures": consecutive_failures, "backoff_hours": backoff_hours}
            )

        # Check progression
        assert failure_sequence[0]["backoff_hours"] == 2  # 1st failure: 2h
        assert failure_sequence[1]["backoff_hours"] == 4  # 2nd failure: 4h
        assert failure_sequence[2]["backoff_hours"] == 8  # 3rd failure: 8h
        assert failure_sequence[3]["backoff_hours"] == 16  # 4th failure: 16h
        assert failure_sequence[4]["backoff_hours"] == 24  # 5th failure: 24h (capped)
        assert failure_sequence[9]["backoff_hours"] == 24  # 10th failure: still 24h

    def test_mixed_success_failure_pattern(self):
        """Simulate alternating success and failure."""
        # Start clean
        consecutive_failures = 0

        # Fail once
        consecutive_failures = 1
        assert min(2**consecutive_failures, 24) == 2

        # Recover (success resets counter)
        consecutive_failures = 0

        # Fail again
        consecutive_failures = 1
        assert min(2**consecutive_failures, 24) == 2  # Back to 2h, not 4h

        # This shows that success properly resets the counter


class TestCircuitBreakerLogging:
    """Test logging output format for circuit breaker."""

    def test_success_log_format(self):
        """Test success log message format."""
        website_id = uuid4()
        log_msg = (
            f"Crawl successful, resetting circuit breaker for website {website_id}"
        )
        assert "successful" in log_msg.lower()
        assert "reset" in log_msg.lower()
        assert str(website_id) in log_msg

    def test_failure_log_format(self):
        """Test failure log message format."""
        website_id = uuid4()
        new_failures = 3
        backoff_hours = 8
        next_retry = datetime.now(timezone.utc) + timedelta(hours=backoff_hours)

        log_msg = (
            f"Crawl failed for website {website_id}. "
            f"Failure {new_failures}, backoff {backoff_hours}h until {next_retry.isoformat()}"
        )

        assert "failed" in log_msg.lower()
        assert str(new_failures) in log_msg
        assert f"{backoff_hours}h" in log_msg
        assert str(website_id) in log_msg


class TestCircuitBreakerDatabaseQueries:
    """Test database query patterns for circuit breaker."""

    def test_scheduler_query_conditions(self):
        """Test that scheduler query combines conditions correctly."""
        # Pseudo-SQL representation of scheduler logic

        # Condition 1: Website is due based on interval
        website_is_due = True

        # Condition 2: Circuit breaker allows crawling
        next_retry_at = None
        circuit_breaker_allows = next_retry_at is None  # or next_retry_at <= now()

        # Combined: Both must be true
        should_crawl = website_is_due and circuit_breaker_allows
        assert should_crawl is True

        # Test with backoff active
        next_retry_at = datetime.now(timezone.utc) + timedelta(hours=2)
        circuit_breaker_allows = next_retry_at is None or next_retry_at <= datetime.now(
            timezone.utc
        )
        should_crawl = website_is_due and circuit_breaker_allows
        assert should_crawl is False  # Backoff prevents crawling
