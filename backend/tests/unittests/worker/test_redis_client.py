"""Unit tests for worker redis client utilities."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch


from intric.worker.redis.client import parse_arq_health_string


class TestParseArqHealthString:
    """Tests for parse_arq_health_string function."""

    def test_empty_string_returns_defaults(self):
        """Empty string should return default values."""
        result = parse_arq_health_string("")
        assert result["raw"] == ""
        assert result["timestamp"] is None
        assert result["arq_health_age_seconds"] is None
        assert result["j_complete"] == 0
        assert result["j_failed"] == 0
        assert result["queued"] == 0

    def test_none_like_empty_returns_defaults(self):
        """None-coerced empty string should return defaults."""
        result = parse_arq_health_string("")
        assert result["arq_health_age_seconds"] is None

    def test_arq_default_format_parses_correctly(self):
        """ARQ default format 'Jan-09 14:35:50' should parse correctly."""
        raw = "Jan-09 14:35:50 j_complete=100 j_failed=2 j_retried=5 j_ongoing=3 queued=10"
        result = parse_arq_health_string(raw)

        assert result["raw"] == raw
        assert result["timestamp"] == "Jan-09 14:35:50"
        assert result["j_complete"] == 100
        assert result["j_failed"] == 2
        assert result["j_retried"] == 5
        assert result["j_ongoing"] == 3
        assert result["queued"] == 10
        assert result["arq_health_age_seconds"] is not None

    def test_iso8601_format_parses_correctly(self):
        """ISO-8601 format should parse with timezone awareness."""
        now = datetime.now(timezone.utc)
        iso_time = now.isoformat()
        raw = f"{iso_time} j_complete=50 j_failed=1 j_retried=2 j_ongoing=5 queued=20"

        result = parse_arq_health_string(raw)

        assert result["timestamp"] == iso_time
        assert result["j_complete"] == 50
        assert result["j_failed"] == 1
        assert result["queued"] == 20
        # Age should be very small (just parsed)
        assert result["arq_health_age_seconds"] is not None
        assert result["arq_health_age_seconds"] < 5  # Less than 5 seconds

    def test_iso8601_with_z_suffix(self):
        """ISO-8601 with Z suffix should parse correctly."""
        raw = "2025-01-09T14:35:50Z j_complete=100 queued=5"
        result = parse_arq_health_string(raw)

        assert result["timestamp"] == "2025-01-09T14:35:50Z"
        assert result["j_complete"] == 100
        assert result["queued"] == 5

    def test_iso8601_naive_no_timezone(self):
        """ISO-8601 without timezone should not raise TypeError."""
        # This tests the fix for naive/aware datetime subtraction bug
        now_local = datetime.now()
        past_local = now_local - timedelta(seconds=30)
        naive_iso = past_local.strftime("%Y-%m-%dT%H:%M:%S")

        raw = f"{naive_iso} j_complete=50 queued=10"
        # Should not raise TypeError
        result = parse_arq_health_string(raw)

        assert result["timestamp"] == naive_iso
        assert result["j_complete"] == 50
        assert result["arq_health_age_seconds"] is not None
        # Age should be approximately 30 seconds
        assert 25 <= result["arq_health_age_seconds"] <= 35

    def test_age_calculation_uses_local_time_for_arq_format(self):
        """ARQ format should use local time comparison (not UTC)."""
        # Create a timestamp 60 seconds ago in local time
        now_local = datetime.now()
        past_local = now_local - timedelta(seconds=60)
        timestamp_str = past_local.strftime("%b-%d %H:%M:%S")

        raw = f"{timestamp_str} j_complete=10 queued=5"
        result = parse_arq_health_string(raw)

        # Age should be approximately 60 seconds (with some tolerance)
        assert result["arq_health_age_seconds"] is not None
        assert 55 <= result["arq_health_age_seconds"] <= 65

    def test_year_boundary_december_in_january(self):
        """December timestamp parsed in January should use previous year."""
        # Mock datetime.now() to return January 2, 2026
        mock_now = datetime(2026, 1, 2, 10, 0, 0)

        with patch("intric.worker.redis.client.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.strptime = datetime.strptime
            mock_datetime.fromisoformat = datetime.fromisoformat

            # December 31 timestamp - should be interpreted as 2025, not 2026
            raw = "Dec-31 23:30:00 j_complete=100 queued=5"
            result = parse_arq_health_string(raw)

            # The parsed timestamp should be Dec 31, 2025 (previous year)
            # not Dec 31, 2026 (which would be ~364 days in the future)
            assert result["timestamp"] == "Dec-31 23:30:00"
            assert result["arq_health_age_seconds"] is not None

            # Age should be about 10.5 hours (Jan 2 10:00 - Dec 31 23:30)
            # = 34.5 hours = 124,200 seconds (approximately)
            # If it incorrectly used 2026, age would be negative (clamped to 0)
            # or about 364 days
            expected_age = (
                mock_now - datetime(2025, 12, 31, 23, 30, 0)
            ).total_seconds()
            assert abs(result["arq_health_age_seconds"] - expected_age) < 5

    def test_year_boundary_same_month_no_adjustment(self):
        """Same month timestamp should not trigger year adjustment."""
        # Mock datetime.now() to return January 15, 2026
        mock_now = datetime(2026, 1, 15, 10, 0, 0)

        with patch("intric.worker.redis.client.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_now
            mock_datetime.strptime = datetime.strptime
            mock_datetime.fromisoformat = datetime.fromisoformat

            # January 14 timestamp - should use current year 2026
            raw = "Jan-14 10:00:00 j_complete=100 queued=5"
            result = parse_arq_health_string(raw)

            assert result["arq_health_age_seconds"] is not None
            # Should be about 24 hours = 86400 seconds
            expected_age = 24 * 3600
            assert abs(result["arq_health_age_seconds"] - expected_age) < 5

    def test_future_timestamp_within_day_not_adjusted(self):
        """Timestamp slightly in future (< 1 day) should not be adjusted."""
        # This can happen due to clock skew between machines
        now_local = datetime.now()
        # 30 minutes in the future
        future_local = now_local + timedelta(minutes=30)
        timestamp_str = future_local.strftime("%b-%d %H:%M:%S")

        raw = f"{timestamp_str} j_complete=10 queued=5"
        result = parse_arq_health_string(raw)

        # Age should be clamped to 0 (not adjusted to previous year)
        assert result["arq_health_age_seconds"] == 0

    def test_partial_kv_pairs_parsed(self):
        """Should handle partial key=value pairs gracefully."""
        raw = "Jan-09 14:35:50 j_complete=100 invalid queued=5"
        result = parse_arq_health_string(raw)

        assert result["j_complete"] == 100
        assert result["queued"] == 5
        # Other fields should remain default
        assert result["j_failed"] == 0

    def test_non_integer_values_ignored(self):
        """Non-integer values should be ignored."""
        raw = "Jan-09 14:35:50 j_complete=abc j_failed=2 queued=5"
        result = parse_arq_health_string(raw)

        assert result["j_complete"] == 0  # Default, since 'abc' couldn't parse
        assert result["j_failed"] == 2
        assert result["queued"] == 5

    def test_unknown_keys_ignored(self):
        """Unknown keys should be ignored."""
        raw = "Jan-09 14:35:50 j_complete=100 unknown_key=999 queued=5"
        result = parse_arq_health_string(raw)

        assert result["j_complete"] == 100
        assert result["queued"] == 5
        assert "unknown_key" not in result

    def test_malformed_timestamp_falls_through(self):
        """Malformed timestamp should not crash, just skip parsing."""
        raw = "NotADate j_complete=100 queued=5"
        result = parse_arq_health_string(raw)

        assert result["raw"] == raw
        assert result["timestamp"] is None
        assert result["arq_health_age_seconds"] is None
        # Key-value pairs might still be parsed if they're in the right position
        # but timestamp parsing failed, so kv_start_idx remains 0

    def test_different_months_parse_correctly(self):
        """Various month abbreviations should parse correctly."""
        months = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]

        for month in months:
            raw = f"{month}-15 12:00:00 j_complete=10 queued=1"
            result = parse_arq_health_string(raw)
            assert result["timestamp"] == f"{month}-15 12:00:00", f"Failed for {month}"
            assert result["j_complete"] == 10
