"""Unit tests for tenant-aware feeder interval (crawl_feeder_interval_seconds).

Tests the _get_minimum_feeder_interval() helper that enables per-tenant
interval customization in the singleton CrawlFeeder.

Test categories:
- Minimum interval calculation: Verifies correct min across tenants
- Fallback behavior: Uses global default when appropriate
- Edge cases: No tenants, errors, partial settings

Note: Tests patch get_settings in TWO locations because:
1. CrawlFeeder imports it from intric.worker.crawl_feeder
2. get_crawler_setting() imports it from intric.tenants.crawler_settings_helper
Both must return consistent values to match production behavior.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.worker.crawl_feeder import CrawlFeeder


# Define global default for consistency across all tests
GLOBAL_DEFAULT_INTERVAL = 30


@pytest.fixture
def feeder():
    """Create a CrawlFeeder instance with mocked settings.

    Patches get_settings in BOTH locations to ensure consistent behavior:
    - intric.worker.crawl_feeder (for CrawlFeeder.settings)
    - intric.tenants.crawler_settings_helper (for get_crawler_setting fallback)

    This matches production where both imports resolve to the same singleton.
    """
    settings = MagicMock()
    settings.crawl_feeder_interval_seconds = GLOBAL_DEFAULT_INTERVAL
    settings.crawl_feeder_batch_size = 10
    settings.tenant_worker_concurrency_limit = 4
    settings.tenant_worker_semaphore_ttl_seconds = 3600
    settings.redis_host = "localhost"
    settings.redis_port = 6379

    with patch("intric.worker.crawl_feeder.get_settings") as mock_feeder_settings, \
         patch("intric.tenants.crawler_settings_helper.get_settings") as mock_helper_settings:
        mock_feeder_settings.return_value = settings
        mock_helper_settings.return_value = settings

        feeder = CrawlFeeder()
        feeder.settings = settings
        yield feeder


class TestGetMinimumFeederInterval:
    """Tests for _get_minimum_feeder_interval() helper method."""

    @pytest.mark.asyncio
    async def test_returns_global_default_when_no_pending_tenants(self, feeder):
        """When no tenants have pending jobs, use global default."""
        mock_redis = AsyncMock()
        # SCAN returns empty - no pending queues
        mock_redis.scan.return_value = (0, [])

        result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == GLOBAL_DEFAULT_INTERVAL, "Should return global default when no tenants"
        mock_redis.scan.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_minimum_across_tenants(self, feeder):
        """Returns the minimum interval when multiple tenants have different settings."""
        tenant_a_id = uuid4()
        tenant_b_id = uuid4()
        tenant_c_id = uuid4()

        mock_redis = AsyncMock()
        # Three tenants with pending queues
        mock_redis.scan.return_value = (
            0,
            [
                f"tenant:{tenant_a_id}:crawl_pending".encode(),
                f"tenant:{tenant_b_id}:crawl_pending".encode(),
                f"tenant:{tenant_c_id}:crawl_pending".encode(),
            ],
        )

        # Mock tenant settings
        async def mock_get_settings(tenant_id):
            if tenant_id == tenant_a_id:
                return {"crawl_feeder_interval_seconds": 60}  # 60s
            elif tenant_id == tenant_b_id:
                return {"crawl_feeder_interval_seconds": 15}  # 15s - MINIMUM
            elif tenant_id == tenant_c_id:
                return {"crawl_feeder_interval_seconds": 45}  # 45s
            return {}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == 15, "Should return minimum interval (15s)"

    @pytest.mark.asyncio
    async def test_uses_global_default_for_tenants_without_override(self, feeder):
        """Tenants without custom interval use global default in calculation."""
        tenant_a_id = uuid4()  # Has custom setting
        tenant_b_id = uuid4()  # No custom setting

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [
                f"tenant:{tenant_a_id}:crawl_pending".encode(),
                f"tenant:{tenant_b_id}:crawl_pending".encode(),
            ],
        )

        async def mock_get_settings(tenant_id):
            if tenant_id == tenant_a_id:
                return {"crawl_feeder_interval_seconds": 45}  # 45s
            return {}  # No override

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        # Tenant B has no override, so uses global default (30s)
        # min(45, 30) = 30
        assert result == GLOBAL_DEFAULT_INTERVAL, "Should use global default for tenant without override"

    @pytest.mark.asyncio
    async def test_handles_single_tenant(self, feeder):
        """Works correctly with single active tenant."""
        tenant_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [f"tenant:{tenant_id}:crawl_pending".encode()],
        )

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 20}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == 20, "Should use single tenant's interval"

    @pytest.mark.asyncio
    async def test_handles_tenant_settings_fetch_error(self, feeder):
        """Continues with other tenants when one tenant's settings fetch fails."""
        tenant_a_id = uuid4()
        tenant_b_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [
                f"tenant:{tenant_a_id}:crawl_pending".encode(),
                f"tenant:{tenant_b_id}:crawl_pending".encode(),
            ],
        )

        async def mock_get_settings(tenant_id):
            if tenant_id == tenant_a_id:
                raise Exception("Database connection error")
            return {"crawl_feeder_interval_seconds": 20}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        # Tenant A failed, so only Tenant B's 20s is considered
        assert result == 20, "Should skip failed tenant and use other's interval"

    @pytest.mark.asyncio
    async def test_handles_redis_scan_error(self, feeder):
        """Falls back to global default when Redis scan fails."""
        mock_redis = AsyncMock()
        mock_redis.scan.side_effect = Exception("Redis connection lost")

        result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == GLOBAL_DEFAULT_INTERVAL, "Should return global default on Redis error"

    @pytest.mark.asyncio
    async def test_handles_paginated_scan(self, feeder):
        """Correctly processes multiple SCAN pages."""
        tenant_a_id = uuid4()
        tenant_b_id = uuid4()

        mock_redis = AsyncMock()
        # First scan returns cursor != 0 (more pages)
        # Second scan returns cursor = 0 (done)
        mock_redis.scan.side_effect = [
            (123, [f"tenant:{tenant_a_id}:crawl_pending".encode()]),  # Page 1
            (0, [f"tenant:{tenant_b_id}:crawl_pending".encode()]),  # Page 2 (final)
        ]

        async def mock_get_settings(tenant_id):
            if tenant_id == tenant_a_id:
                return {"crawl_feeder_interval_seconds": 25}
            return {"crawl_feeder_interval_seconds": 10}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        # Should find both tenants across pages and use min
        assert result == 10, "Should find minimum across paginated results"
        assert mock_redis.scan.call_count == 2, "Should call scan twice for pagination"

    @pytest.mark.asyncio
    async def test_skips_invalid_tenant_ids(self, feeder):
        """Gracefully skips keys with invalid tenant IDs."""
        valid_tenant_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [
                f"tenant:{valid_tenant_id}:crawl_pending".encode(),
                b"tenant:not-a-valid-uuid:crawl_pending",  # Invalid UUID
                b"malformed-key",  # Malformed key
            ],
        )

        async def mock_get_settings(tenant_id):
            return {"crawl_feeder_interval_seconds": 15}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        # Should only process valid tenant and return its interval
        assert result == 15, "Should skip invalid tenant IDs"

    @pytest.mark.asyncio
    async def test_handles_string_keys_from_redis(self, feeder):
        """Works with both bytes and string keys from Redis."""
        tenant_id = uuid4()

        mock_redis = AsyncMock()
        # Some Redis clients return strings, not bytes
        mock_redis.scan.return_value = (
            0,
            [f"tenant:{tenant_id}:crawl_pending"],  # String, not bytes
        )

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 22}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == 22, "Should handle string keys from Redis"


class TestFeederIntervalIsolation:
    """Tests ensuring tenant interval settings are properly isolated."""

    @pytest.mark.asyncio
    async def test_different_tenants_different_intervals(self, feeder):
        """Each tenant's interval is evaluated independently."""
        fast_tenant = uuid4()
        slow_tenant = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [
                f"tenant:{fast_tenant}:crawl_pending".encode(),
                f"tenant:{slow_tenant}:crawl_pending".encode(),
            ],
        )

        async def mock_get_settings(tenant_id):
            if tenant_id == fast_tenant:
                return {"crawl_feeder_interval_seconds": 5}  # Fast polling
            return {"crawl_feeder_interval_seconds": 120}  # Slow polling

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        # Should use fastest tenant's interval
        assert result == 5, "Should use fastest tenant's interval"

    @pytest.mark.asyncio
    async def test_all_tenants_use_default(self, feeder):
        """When no tenant has overrides, returns global default."""
        tenant_a_id = uuid4()
        tenant_b_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [
                f"tenant:{tenant_a_id}:crawl_pending".encode(),
                f"tenant:{tenant_b_id}:crawl_pending".encode(),
            ],
        )

        async def mock_get_settings(tenant_id):
            return {}  # No overrides

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == GLOBAL_DEFAULT_INTERVAL, "Should return global default when no overrides"


class TestFeederIntervalEdgeCases:
    """Edge case tests for feeder interval calculation."""

    @pytest.mark.asyncio
    async def test_tenant_interval_less_than_global(self, feeder):
        """Tenant with interval less than global is respected."""
        tenant_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [f"tenant:{tenant_id}:crawl_pending".encode()],
        )

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 5}  # Less than 30s default

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == 5, "Should use tenant's shorter interval"

    @pytest.mark.asyncio
    async def test_tenant_interval_greater_than_global(self, feeder):
        """When tenant interval exceeds global, global wins as minimum."""
        tenant_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [f"tenant:{tenant_id}:crawl_pending".encode()],
        )

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 120}  # More than 30s default

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        # Global default (30s) is the minimum
        assert result == GLOBAL_DEFAULT_INTERVAL, "Should use global default when tenant interval is higher"

    @pytest.mark.asyncio
    async def test_null_tenant_settings_uses_default(self, feeder):
        """When _get_tenant_crawler_settings returns None, use default."""
        tenant_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [f"tenant:{tenant_id}:crawl_pending".encode()],
        )

        async def mock_get_settings(tid):
            return None  # Settings fetch returned None

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == GLOBAL_DEFAULT_INTERVAL, "Should use default when tenant settings is None"


class TestFeederIntervalBoundaryConditions:
    """Boundary and invalid value tests for production robustness."""

    @pytest.mark.asyncio
    async def test_zero_interval_setting(self, feeder):
        """Zero interval from tenant settings - potential infinite loop bug.

        If a tenant somehow has 0 as their interval, the feeder would
        sleep(0) which causes busy-looping and CPU exhaustion.
        """
        tenant_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [f"tenant:{tenant_id}:crawl_pending".encode()],
        )

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 0}  # Invalid: zero interval

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        # Zero should still be returned - validation happens elsewhere
        # Test documents current behavior for awareness
        assert result == 0, "Zero interval is returned as-is (no floor enforcement)"

    @pytest.mark.asyncio
    async def test_negative_interval_setting(self, feeder):
        """Negative interval from tenant settings - invalid data handling.

        Negative intervals could cause asyncio.sleep() issues or
        unexpected behavior in comparison operations.
        """
        tenant_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [f"tenant:{tenant_id}:crawl_pending".encode()],
        )

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": -10}  # Invalid: negative

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        # min(-10, 30) = -10 - documents current behavior
        assert result == -10, "Negative interval is returned (no validation in min())"

    @pytest.mark.asyncio
    async def test_minimum_spec_interval(self, feeder):
        """Test with minimum allowed interval (5s per CRAWLER_SETTING_SPECS)."""
        tenant_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [f"tenant:{tenant_id}:crawl_pending".encode()],
        )

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 5}  # Minimum per spec

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == 5, "Should accept minimum spec value (5s)"

    @pytest.mark.asyncio
    async def test_maximum_spec_interval(self, feeder):
        """Test with maximum allowed interval (300s per CRAWLER_SETTING_SPECS)."""
        tenant_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [f"tenant:{tenant_id}:crawl_pending".encode()],
        )

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 300}  # Maximum per spec

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        # min(300, 30) = 30 (global default wins)
        assert result == GLOBAL_DEFAULT_INTERVAL, "Maximum spec (300s) loses to global default"


class TestFeederIntervalManyTenants:
    """Tests for correct behavior with many tenants."""

    @pytest.mark.asyncio
    async def test_many_tenants_finds_minimum(self, feeder):
        """With many tenants, correctly identifies the minimum interval."""
        tenant_ids = [uuid4() for _ in range(10)]
        # Intervals: 25, 35, 45, 55, 65, 75, 85, 95, 105, 115
        # Minimum should be 25 (less than global 30)

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [f"tenant:{tid}:crawl_pending".encode() for tid in tenant_ids],
        )

        async def mock_get_settings(tid):
            idx = tenant_ids.index(tid)
            return {"crawl_feeder_interval_seconds": 25 + (idx * 10)}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == 25, "Should find minimum (25s) among 10 tenants"

    @pytest.mark.asyncio
    async def test_many_tenants_minimum_in_middle(self, feeder):
        """Minimum interval is in the middle of the tenant list."""
        tenant_ids = [uuid4() for _ in range(5)]
        # tenant_ids[2] will have the minimum

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [f"tenant:{tid}:crawl_pending".encode() for tid in tenant_ids],
        )

        async def mock_get_settings(tid):
            idx = tenant_ids.index(tid)
            # [40, 35, 10, 50, 45] - minimum is at index 2
            intervals = [40, 35, 10, 50, 45]
            return {"crawl_feeder_interval_seconds": intervals[idx]}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == 10, "Should find minimum even when not first/last"

    @pytest.mark.asyncio
    async def test_all_tenants_same_interval(self, feeder):
        """All tenants have identical intervals."""
        tenant_ids = [uuid4() for _ in range(5)]

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [f"tenant:{tid}:crawl_pending".encode() for tid in tenant_ids],
        )

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 20}  # All same

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == 20, "Should return common interval when all same"


class TestFeederIntervalErrorRecovery:
    """Tests for graceful error handling and recovery."""

    @pytest.mark.asyncio
    async def test_partial_tenant_failures(self, feeder):
        """Some tenants fail, others succeed - uses minimum from successful ones."""
        tenant_a_id = uuid4()
        tenant_b_id = uuid4()
        tenant_c_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [
                f"tenant:{tenant_a_id}:crawl_pending".encode(),
                f"tenant:{tenant_b_id}:crawl_pending".encode(),
                f"tenant:{tenant_c_id}:crawl_pending".encode(),
            ],
        )

        call_count = {"value": 0}

        async def mock_get_settings(tid):
            call_count["value"] += 1
            if tid == tenant_a_id:
                raise ConnectionError("DB connection lost")  # Fail first
            if tid == tenant_b_id:
                return {"crawl_feeder_interval_seconds": 15}  # Success: 15s
            if tid == tenant_c_id:
                raise TimeoutError("Query timeout")  # Fail third
            return {}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        # Only tenant_b succeeded with 15s, which is less than global 30s
        assert result == 15, "Should use successful tenant's interval"
        assert call_count["value"] == 3, "Should attempt all tenants despite failures"

    @pytest.mark.asyncio
    async def test_all_tenant_settings_fail(self, feeder):
        """All tenant settings fetches fail - falls back to global default."""
        tenant_ids = [uuid4() for _ in range(3)]

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [f"tenant:{tid}:crawl_pending".encode() for tid in tenant_ids],
        )

        async def mock_get_settings(tid):
            raise Exception("All settings fetches fail")

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == GLOBAL_DEFAULT_INTERVAL, "Should fall back to global default when all fail"

    @pytest.mark.asyncio
    async def test_redis_scan_partial_failure(self, feeder):
        """Redis scan succeeds first page, fails second - uses what we have."""
        tenant_a_id = uuid4()

        mock_redis = AsyncMock()
        # First scan works, second fails
        mock_redis.scan.side_effect = [
            (123, [f"tenant:{tenant_a_id}:crawl_pending".encode()]),  # Page 1
            Exception("Redis connection lost"),  # Page 2 fails
        ]

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 20}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        # Should fall back to default because scan failed mid-way
        assert result == GLOBAL_DEFAULT_INTERVAL, "Should fall back to default on partial scan failure"


class TestFeederIntervalKeyParsing:
    """Tests for Redis key parsing edge cases."""

    @pytest.mark.asyncio
    async def test_empty_tenant_id_in_key(self, feeder):
        """Key with empty tenant ID segment."""
        valid_tenant_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [
                f"tenant:{valid_tenant_id}:crawl_pending".encode(),
                b"tenant::crawl_pending",  # Empty tenant ID
            ],
        )

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 15}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == 15, "Should skip empty tenant ID and use valid one"

    @pytest.mark.asyncio
    async def test_extra_colons_in_key(self, feeder):
        """Key with extra colons that could break parsing."""
        valid_tenant_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [
                f"tenant:{valid_tenant_id}:crawl_pending".encode(),
                b"tenant:not:a:uuid:crawl_pending",  # Multiple colons
            ],
        )

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 15}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == 15, "Should handle keys with extra colons gracefully"

    @pytest.mark.asyncio
    async def test_uppercase_uuid_in_key(self, feeder):
        """Key with uppercase UUID (should still work)."""
        tenant_id = uuid4()
        uppercase_uuid = str(tenant_id).upper()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [f"tenant:{uppercase_uuid}:crawl_pending".encode()],
        )

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 15}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        # UUID parsing should handle case-insensitively
        assert result == 15, "Should handle uppercase UUID in key"


class TestFeederIntervalConcurrencyBehavior:
    """Tests to verify behavior under concurrent conditions."""

    @pytest.mark.asyncio
    async def test_duplicate_tenant_ids(self, feeder):
        """Same tenant ID appears multiple times in scan results."""
        tenant_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [
                f"tenant:{tenant_id}:crawl_pending".encode(),
                f"tenant:{tenant_id}:crawl_pending".encode(),  # Duplicate
                f"tenant:{tenant_id}:crawl_pending".encode(),  # Duplicate
            ],
        )

        call_count = {"value": 0}

        async def mock_get_settings(tid):
            call_count["value"] += 1
            return {"crawl_feeder_interval_seconds": 20}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        # Current implementation doesn't dedupe - documents behavior
        assert result == 20, "Should return correct interval despite duplicates"
        # Note: This test documents that duplicates cause extra DB calls
        # Could be optimized if this becomes a performance issue

    @pytest.mark.asyncio
    async def test_tenant_removed_during_iteration(self, feeder):
        """Simulates tenant being removed while iterating.

        If a tenant's settings are deleted between scan and fetch,
        the fetch should fail gracefully.
        """
        tenant_a_id = uuid4()
        tenant_b_id = uuid4()

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (
            0,
            [
                f"tenant:{tenant_a_id}:crawl_pending".encode(),
                f"tenant:{tenant_b_id}:crawl_pending".encode(),
            ],
        )

        async def mock_get_settings(tid):
            if tid == tenant_a_id:
                # Tenant A was deleted during iteration
                raise KeyError("Tenant not found")
            return {"crawl_feeder_interval_seconds": 20}

        with patch.object(
            feeder, "_get_tenant_crawler_settings", side_effect=mock_get_settings
        ):
            result = await feeder._get_minimum_feeder_interval(mock_redis)

        assert result == 20, "Should continue with remaining tenants"
