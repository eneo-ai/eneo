"""Unit tests for the CapacityManager module.

Tests per-tenant slot management and settings retrieval.
"""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.worker.redis.lua_scripts import LuaScripts


def _source_tree(relative_path: str) -> ast.Module:
    source_path = Path(__file__).parents[4] / relative_path
    return ast.parse(source_path.read_text())


def _imports_name(tree: ast.AST, *, module: str, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            if any(alias.name == name for alias in node.names):
                return True
    return False


def _calls_attribute(tree: ast.AST, attribute_name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == attribute_name:
                return True
    return False


@pytest.fixture
def mock_settings():
    """Create a mock settings object with test values."""
    settings = MagicMock()
    settings.tenant_worker_concurrency_limit = 10
    settings.tenant_worker_semaphore_ttl_seconds = 300
    settings.crawl_feeder_interval_seconds = 10
    return settings


class TestCapacityManagerInit:
    """Tests for CapacityManager initialization."""

    def test_initializes_with_redis_client(self):
        """Should initialize with provided Redis client."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        manager = CapacityManager(redis_mock)

        assert manager._redis is redis_mock
        assert manager._settings is not None

    def test_accepts_custom_settings(self):
        """Should accept custom settings object."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.tenant_worker_concurrency_limit = 5

        manager = CapacityManager(redis_mock, settings=settings_mock)

        assert manager._settings is settings_mock


class TestGetTenantSettings:
    """Tests for get_tenant_settings method."""

    @pytest.mark.asyncio
    async def test_returns_settings_snapshot_from_database(self):
        """Should fetch tenant overrides and return a settings snapshot."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        tenant_id = uuid4()
        stored_overrides = {"crawl_feeder_batch_size": 10}

        # Mock the session and context managers properly
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = stored_overrides

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Create async context manager mocks for compound 'async with' statement
        mock_begin_cm = AsyncMock()
        mock_begin_cm.__aenter__ = AsyncMock(return_value=None)
        mock_begin_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.begin.return_value = mock_begin_cm

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        mock_sessionmanager = MagicMock()
        mock_sessionmanager.session.return_value = mock_session_cm

        # Patch at the actual import location (database module), not capacity module
        with patch("intric.database.database.sessionmanager", mock_sessionmanager):
            manager = CapacityManager(redis_mock)
            result = await manager.get_tenant_settings(tenant_id)

        assert result.get("crawl_feeder_batch_size") == 10
        assert result.invalid_overrides == ()

    @pytest.mark.asyncio
    async def test_returns_default_snapshot_when_no_settings(self):
        """Should return default settings snapshot when tenant has no overrides."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        tenant_id = uuid4()

        # Mock returns None for scalar_one_or_none
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_begin_cm = AsyncMock()
        mock_begin_cm.__aenter__ = AsyncMock(return_value=None)
        mock_begin_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.begin.return_value = mock_begin_cm

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=None)

        mock_sessionmanager = MagicMock()
        mock_sessionmanager.session.return_value = mock_session_cm

        # Patch at the actual import location (database module), not capacity module
        with patch("intric.database.database.sessionmanager", mock_sessionmanager):
            manager = CapacityManager(redis_mock)
            result = await manager.get_tenant_settings(tenant_id)

        assert result.get("crawl_feeder_batch_size") is not None
        assert result.invalid_overrides == ()

    @pytest.mark.asyncio
    async def test_returns_default_snapshot_on_database_error(self):
        """Should return defaults and log warning on DB error."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        tenant_id = uuid4()

        # Mock session() to raise when entering context
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(
            side_effect=Exception("DB connection failed")
        )

        mock_sessionmanager = MagicMock()
        mock_sessionmanager.session.return_value = mock_session_cm

        # Patch at the actual import location (database module), not capacity module
        with patch("intric.database.database.sessionmanager", mock_sessionmanager):
            manager = CapacityManager(redis_mock)
            result = await manager.get_tenant_settings(tenant_id)

        assert result.get("crawl_feeder_batch_size") is not None


class TestGetMaxConcurrent:
    """Tests for get_max_concurrent method."""

    def test_returns_default_when_no_tenant_settings(self, mock_settings):
        """Should return global default when no tenant settings."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()

        # Patch get_crawler_setting to use our mock settings value
        with patch(
            "intric.worker.feeder.capacity.get_crawler_setting",
            return_value=10,
        ) as mock_get:
            manager = CapacityManager(redis_mock, settings=mock_settings)
            result = manager.get_max_concurrent(None)

            assert result == 10
            mock_get.assert_called_once_with(
                "tenant_worker_concurrency_limit",
                None,
                default=10,
            )

    def test_returns_tenant_override_when_present(self, mock_settings):
        """Should return tenant-specific limit when set."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        tenant_settings = {"tenant_worker_concurrency_limit": 5}

        # Patch get_crawler_setting to return tenant override
        with patch(
            "intric.worker.feeder.capacity.get_crawler_setting",
            return_value=5,
        ):
            manager = CapacityManager(redis_mock, settings=mock_settings)
            result = manager.get_max_concurrent(tenant_settings)

            assert result == 5


class TestGetSlotTtl:
    """Tests for get_slot_ttl method."""

    def test_returns_default_when_no_tenant_settings(self, mock_settings):
        """Should return global default when no tenant settings."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()

        # Patch get_crawler_setting to use our mock settings value
        with patch(
            "intric.worker.feeder.capacity.get_crawler_setting",
            return_value=300,
        ) as mock_get:
            manager = CapacityManager(redis_mock, settings=mock_settings)
            result = manager.get_slot_ttl(None)

            assert result == 300
            mock_get.assert_called_once_with(
                "tenant_worker_semaphore_ttl_seconds",
                None,
                default=300,
            )


class TestTryAcquireSlot:
    """Tests for try_acquire_slot method."""

    @pytest.mark.asyncio
    async def test_returns_true_when_slot_acquired(self, mock_settings):
        """Should return True when Lua script acquires slot."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        tenant_id = uuid4()

        with (
            patch(
                "intric.worker.feeder.capacity.LuaScripts.acquire_slot",
                new_callable=AsyncMock,
                return_value=1,
            ) as mock_acquire,
            patch(
                "intric.worker.feeder.capacity.get_crawler_setting",
                side_effect=[10, 300],  # max_concurrent, then ttl
            ),
        ):
            manager = CapacityManager(redis_mock, settings=mock_settings)
            result = await manager.try_acquire_slot(tenant_id)

            assert result is True
            mock_acquire.assert_called_once_with(redis_mock, tenant_id, 10, 300)

    @pytest.mark.asyncio
    async def test_returns_false_when_at_capacity(self, mock_settings):
        """Should return False when Lua script returns 0."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        tenant_id = uuid4()

        with (
            patch(
                "intric.worker.feeder.capacity.LuaScripts.acquire_slot",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "intric.worker.feeder.capacity.get_crawler_setting",
                side_effect=[10, 300],
            ),
        ):
            manager = CapacityManager(redis_mock, settings=mock_settings)
            result = await manager.try_acquire_slot(tenant_id)

            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_redis_error(self, mock_settings):
        """Should return False on Redis error."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        tenant_id = uuid4()

        with (
            patch(
                "intric.worker.feeder.capacity.LuaScripts.acquire_slot",
                new_callable=AsyncMock,
                side_effect=Exception("Redis error"),
            ),
            patch(
                "intric.worker.feeder.capacity.get_crawler_setting",
                side_effect=[10, 300],
            ),
        ):
            manager = CapacityManager(redis_mock, settings=mock_settings)
            result = await manager.try_acquire_slot(tenant_id)

            assert result is False


class TestReleaseSlot:
    """Tests for release_slot method."""

    @pytest.mark.asyncio
    async def test_calls_lua_script(self, mock_settings):
        """Should call Lua script to release slot."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        tenant_id = uuid4()

        with (
            patch(
                "intric.worker.feeder.capacity.LuaScripts.release_slot",
                new_callable=AsyncMock,
            ) as mock_release,
            patch(
                "intric.worker.feeder.capacity.get_crawler_setting",
                return_value=300,
            ),
        ):
            manager = CapacityManager(redis_mock, settings=mock_settings)
            await manager.release_slot(tenant_id)

            mock_release.assert_called_once_with(redis_mock, tenant_id, 300)

    @pytest.mark.asyncio
    async def test_swallows_redis_error(self, mock_settings):
        """Should not raise on Redis error (best effort)."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        tenant_id = uuid4()

        with (
            patch(
                "intric.worker.feeder.capacity.LuaScripts.release_slot",
                new_callable=AsyncMock,
                side_effect=Exception("Redis error"),
            ),
            patch(
                "intric.worker.feeder.capacity.get_crawler_setting",
                return_value=300,
            ),
        ):
            manager = CapacityManager(redis_mock, settings=mock_settings)
            # Should not raise
            await manager.release_slot(tenant_id)


class TestGetAvailableCapacity:
    """Tests for get_available_capacity method."""

    @pytest.mark.asyncio
    async def test_returns_max_when_no_active_jobs(self, mock_settings):
        """Should return max concurrent when key doesn't exist."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(return_value=None)
        tenant_id = uuid4()

        with (
            patch(
                "intric.worker.feeder.capacity.get_crawler_setting",
                return_value=10,
            ),
            patch(
                "intric.worker.feeder.capacity.LuaScripts.slot_key",
                return_value=f"tenant:{tenant_id}:active_jobs",
            ),
        ):
            manager = CapacityManager(redis_mock, settings=mock_settings)
            result = await manager.get_available_capacity(tenant_id)

            assert result == 10

    @pytest.mark.asyncio
    async def test_returns_remaining_capacity(self, mock_settings):
        """Should return remaining slots when some are in use."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(return_value=b"3")
        tenant_id = uuid4()

        with (
            patch(
                "intric.worker.feeder.capacity.get_crawler_setting",
                return_value=10,
            ),
            patch(
                "intric.worker.feeder.capacity.LuaScripts.slot_key",
                return_value=f"tenant:{tenant_id}:active_jobs",
            ),
        ):
            manager = CapacityManager(redis_mock, settings=mock_settings)
            result = await manager.get_available_capacity(tenant_id)

            assert result == 7  # 10 - 3

    @pytest.mark.asyncio
    async def test_returns_zero_when_at_capacity(self, mock_settings):
        """Should return 0 when at max capacity."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(return_value=b"10")
        tenant_id = uuid4()

        with (
            patch(
                "intric.worker.feeder.capacity.get_crawler_setting",
                return_value=10,
            ),
            patch(
                "intric.worker.feeder.capacity.LuaScripts.slot_key",
                return_value=f"tenant:{tenant_id}:active_jobs",
            ),
        ):
            manager = CapacityManager(redis_mock, settings=mock_settings)
            result = await manager.get_available_capacity(tenant_id)

            assert result == 0

    @pytest.mark.asyncio
    async def test_returns_zero_on_redis_error(self, mock_settings):
        """Should return 0 (conservative) on Redis error."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(side_effect=Exception("Redis error"))
        tenant_id = uuid4()

        with (
            patch(
                "intric.worker.feeder.capacity.get_crawler_setting",
                return_value=10,
            ),
            patch(
                "intric.worker.feeder.capacity.LuaScripts.slot_key",
                return_value=f"tenant:{tenant_id}:active_jobs",
            ),
        ):
            manager = CapacityManager(redis_mock, settings=mock_settings)
            result = await manager.get_available_capacity(tenant_id)

            assert result == 0


class TestMarkSlotPreacquired:
    """Tests for mark_slot_preacquired method."""

    @pytest.mark.asyncio
    async def test_sets_flag_with_ttl(self, mock_settings):
        """Should set flag with tenant_id as value."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.set = AsyncMock()
        job_id = uuid4()
        tenant_id = uuid4()

        with patch(
            "intric.worker.feeder.capacity.get_crawler_setting",
            return_value=300,
        ):
            manager = CapacityManager(redis_mock, settings=mock_settings)
            await manager.mark_slot_preacquired(job_id, tenant_id)

            redis_mock.set.assert_called_once_with(
                LuaScripts.preacquired_slot_key(job_id),
                str(tenant_id),
                ex=300,
            )

    @pytest.mark.asyncio
    async def test_raises_on_redis_error(self, mock_settings):
        """Should raise on Redis error (caller must handle)."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.set = AsyncMock(side_effect=Exception("Redis error"))
        job_id = uuid4()
        tenant_id = uuid4()

        with patch(
            "intric.worker.feeder.capacity.get_crawler_setting",
            return_value=300,
        ):
            manager = CapacityManager(redis_mock, settings=mock_settings)

            with pytest.raises(Exception, match="Redis error"):
                await manager.mark_slot_preacquired(job_id, tenant_id)


class TestClearPreacquiredFlag:
    """Tests for clear_preacquired_flag method."""

    @pytest.mark.asyncio
    async def test_deletes_flag(self):
        """Should delete the flag key."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock()
        job_id = uuid4()

        manager = CapacityManager(redis_mock)
        await manager.clear_preacquired_flag(job_id)

        redis_mock.delete.assert_called_once_with(
            LuaScripts.preacquired_slot_key(job_id)
        )

    @pytest.mark.asyncio
    async def test_swallows_redis_error(self):
        """Should not raise on Redis error (best effort)."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock(side_effect=Exception("Redis error"))
        job_id = uuid4()

        manager = CapacityManager(redis_mock)
        # Should not raise
        await manager.clear_preacquired_flag(job_id)


class TestGetPreacquiredTenant:
    """Tests for get_preacquired_tenant method."""

    @pytest.mark.asyncio
    async def test_returns_tenant_id_from_flag(self):
        """Should return tenant UUID when flag exists."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        tenant_id = uuid4()
        redis_mock.get = AsyncMock(return_value=str(tenant_id).encode())
        job_id = uuid4()

        manager = CapacityManager(redis_mock)
        result = await manager.get_preacquired_tenant(job_id)

        assert result == tenant_id

    @pytest.mark.asyncio
    async def test_returns_none_when_no_flag(self):
        """Should return None when flag doesn't exist."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(return_value=None)
        job_id = uuid4()

        manager = CapacityManager(redis_mock)
        result = await manager.get_preacquired_tenant(job_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self):
        """Should return None on Redis error."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(side_effect=Exception("Redis error"))
        job_id = uuid4()

        manager = CapacityManager(redis_mock)
        result = await manager.get_preacquired_tenant(job_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_tenant_id_from_string_flag(self):
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        tenant_id = uuid4()
        redis_mock.get = AsyncMock(return_value=str(tenant_id))
        job_id = uuid4()

        manager = CapacityManager(redis_mock)
        result = await manager.get_preacquired_tenant(job_id)

        assert result == tenant_id

    @pytest.mark.asyncio
    async def test_returns_none_and_logs_warning_on_invalid_flag(self):
        from intric.worker.feeder import capacity as capacity_module
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(return_value=b"not-a-uuid")
        job_id = uuid4()
        logger = MagicMock()

        manager = CapacityManager(redis_mock)
        with patch.object(capacity_module, "logger", logger):
            result = await manager.get_preacquired_tenant(job_id)

        assert result is None
        logger.warning.assert_called_once()


class TestRefreshSlotTtl:
    @pytest.mark.asyncio
    async def test_refreshes_slot_ttl(self):
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.expire = AsyncMock()
        tenant_id = uuid4()
        job_id = uuid4()

        manager = CapacityManager(redis_mock)
        await manager.refresh_slot_ttl(
            tenant_id=tenant_id,
            ttl_seconds=300,
            job_id=job_id,
        )

        redis_mock.expire.assert_awaited_once_with(
            LuaScripts.slot_key(tenant_id),
            300,
        )

    @pytest.mark.asyncio
    async def test_ttl_refresh_is_best_effort(self):
        from intric.worker.feeder import capacity as capacity_module
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.expire = AsyncMock(side_effect=RuntimeError("expire failed"))
        tenant_id = uuid4()
        job_id = uuid4()
        logger = MagicMock()

        manager = CapacityManager(redis_mock)
        with patch.object(capacity_module, "logger", logger):
            await manager.refresh_slot_ttl(
                tenant_id=tenant_id,
                ttl_seconds=300,
                job_id=job_id,
            )

        logger.debug.assert_called_once_with(
            "Failed to refresh pre-acquired crawl slot TTL",
            extra={
                "job_id": str(job_id),
                "tenant_id": str(tenant_id),
                "error": "expire failed",
            },
        )


class TestRefreshPreacquiredSlotTtls:
    @pytest.mark.asyncio
    async def test_refreshes_counter_and_flag_ttls_atomically(self):
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        pipeline = MagicMock()
        pipeline.__aenter__ = AsyncMock(return_value=pipeline)
        pipeline.__aexit__ = AsyncMock(return_value=None)
        pipeline.expire = MagicMock()
        pipeline.execute = AsyncMock(return_value=[1, 1])
        redis_mock.pipeline = MagicMock(return_value=pipeline)
        tenant_id = uuid4()
        job_id = uuid4()

        manager = CapacityManager(redis_mock)
        result = await manager.refresh_preacquired_slot_ttls(
            job_id=job_id,
            tenant_id=tenant_id,
            ttl_seconds=300,
        )

        assert result.counter_refreshed is True
        assert result.flag_refreshed is True
        pipeline.expire.assert_any_call(LuaScripts.slot_key(tenant_id), 300)
        pipeline.expire.assert_any_call(LuaScripts.preacquired_slot_key(job_id), 300)

    @pytest.mark.asyncio
    async def test_reports_missing_counter_or_flag_without_raising(self):
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        pipeline = MagicMock()
        pipeline.__aenter__ = AsyncMock(return_value=pipeline)
        pipeline.__aexit__ = AsyncMock(return_value=None)
        pipeline.expire = MagicMock()
        pipeline.execute = AsyncMock(return_value=[0, 1])
        redis_mock.pipeline = MagicMock(return_value=pipeline)

        manager = CapacityManager(redis_mock)
        result = await manager.refresh_preacquired_slot_ttls(
            job_id=uuid4(),
            tenant_id=uuid4(),
            ttl_seconds=300,
        )

        assert result.counter_refreshed is False
        assert result.flag_refreshed is True


class TestGetMinimumFeederInterval:
    """Tests for get_minimum_feeder_interval method.

    Tests the core contract:
    - Returns minimum interval across all active tenants
    - Falls back to global default when appropriate
    - Handles errors gracefully (skip failed tenants, continue)
    - Handles edge cases in Redis key parsing
    """

    @pytest.fixture
    def mock_crawler_setting_passthrough(self):
        """Return a mock that passes through tenant settings or uses default."""

        def _mock(name, tenant_settings, default=None):
            if tenant_settings and name in tenant_settings:
                return tenant_settings[name]
            return default

        return _mock

    # --- Core Contract Tests ---

    def test_interval_scan_uses_canonical_redis_boundary(self):
        tree = _source_tree("src/intric/worker/feeder/capacity.py")

        assert not _imports_name(tree, module="typing", name="Any")
        assert _imports_name(
            tree,
            module="intric.worker.redis.client",
            name="redis_scan_match_bytes",
        )
        assert not _calls_attribute(tree, "scan")

    @pytest.mark.asyncio
    async def test_interval_scan_consumes_typed_redis_boundary(
        self, mock_settings, mock_crawler_setting_passthrough
    ):
        from intric.worker.feeder import capacity as capacity_module
        from intric.worker.feeder.capacity import CapacityManager

        tenant_id = uuid4()
        redis_mock = MagicMock()
        scanned_patterns: list[tuple[object, str, int]] = []

        async def scan_keys(redis: object, *, pattern: str, count: int):
            scanned_patterns.append((redis, pattern, count))
            yield f"tenant:{tenant_id}:crawl_pending".encode()

        manager = CapacityManager(redis_mock, settings=mock_settings)

        async def mock_get_settings(tid):
            assert tid == tenant_id
            return {"crawl_feeder_interval_seconds": 5}

        manager.get_tenant_settings = mock_get_settings

        with (
            patch.object(capacity_module, "redis_scan_match_bytes", scan_keys),
            patch(
                "intric.worker.feeder.capacity.get_crawler_setting",
                side_effect=mock_crawler_setting_passthrough,
            ),
        ):
            result = await manager.get_minimum_feeder_interval()

        assert result == 5
        assert scanned_patterns == [(redis_mock, "tenant:*:crawl_pending", 100)]

    @pytest.mark.asyncio
    async def test_returns_default_when_no_pending_queues(self, mock_settings):
        """Should return global default when no tenant queues found."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(return_value=(0, []))

        manager = CapacityManager(redis_mock, settings=mock_settings)
        result = await manager.get_minimum_feeder_interval()

        assert result == 10

    @pytest.mark.asyncio
    async def test_returns_minimum_across_tenants(
        self, mock_settings, mock_crawler_setting_passthrough
    ):
        """Should return shortest interval among active tenants."""
        from intric.worker.feeder.capacity import CapacityManager

        tenant1 = uuid4()
        tenant2 = uuid4()
        tenant3 = uuid4()

        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(
            return_value=(
                0,
                [
                    f"tenant:{tenant1}:crawl_pending".encode(),
                    f"tenant:{tenant2}:crawl_pending".encode(),
                    f"tenant:{tenant3}:crawl_pending".encode(),
                ],
            )
        )

        manager = CapacityManager(redis_mock, settings=mock_settings)

        async def mock_get_settings(tid):
            intervals = {tenant1: 60, tenant2: 15, tenant3: 45}
            return {"crawl_feeder_interval_seconds": intervals.get(tid, 30)}

        manager.get_tenant_settings = mock_get_settings

        with patch(
            "intric.worker.feeder.capacity.get_crawler_setting",
            side_effect=mock_crawler_setting_passthrough,
        ):
            result = await manager.get_minimum_feeder_interval()

        assert result == 10  # min(60, 15, 45, 10) = 10 (global default)

    @pytest.mark.asyncio
    async def test_tenant_override_less_than_default_wins(
        self, mock_settings, mock_crawler_setting_passthrough
    ):
        """Tenant with interval less than global default is respected."""
        from intric.worker.feeder.capacity import CapacityManager

        tenant_id = uuid4()

        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(
            return_value=(0, [f"tenant:{tenant_id}:crawl_pending".encode()])
        )

        manager = CapacityManager(redis_mock, settings=mock_settings)

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 5}

        manager.get_tenant_settings = mock_get_settings

        with patch(
            "intric.worker.feeder.capacity.get_crawler_setting",
            side_effect=mock_crawler_setting_passthrough,
        ):
            result = await manager.get_minimum_feeder_interval()

        assert result == 5

    @pytest.mark.asyncio
    async def test_uses_default_for_tenants_without_override(
        self, mock_settings, mock_crawler_setting_passthrough
    ):
        """Tenants without custom interval use global default in calculation."""
        from intric.worker.feeder.capacity import CapacityManager

        tenant_with_override = uuid4()
        tenant_without_override = uuid4()

        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(
            return_value=(
                0,
                [
                    f"tenant:{tenant_with_override}:crawl_pending".encode(),
                    f"tenant:{tenant_without_override}:crawl_pending".encode(),
                ],
            )
        )

        manager = CapacityManager(redis_mock, settings=mock_settings)

        async def mock_get_settings(tid):
            if tid == tenant_with_override:
                return {"crawl_feeder_interval_seconds": 45}
            return {}  # No override

        manager.get_tenant_settings = mock_get_settings

        with patch(
            "intric.worker.feeder.capacity.get_crawler_setting",
            side_effect=mock_crawler_setting_passthrough,
        ):
            result = await manager.get_minimum_feeder_interval()

        # min(45, 10) = 10 (global default wins)
        assert result == 10

    # --- Error Policy Tests ---

    @pytest.mark.asyncio
    async def test_returns_default_on_scan_error(self, mock_settings):
        """Should return global default on Redis scan error."""
        from intric.worker.feeder.capacity import CapacityManager

        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(side_effect=Exception("Redis error"))

        manager = CapacityManager(redis_mock, settings=mock_settings)
        result = await manager.get_minimum_feeder_interval()

        assert result == 10

    @pytest.mark.asyncio
    async def test_skips_failed_tenant_and_continues(
        self, mock_settings, mock_crawler_setting_passthrough
    ):
        """Should skip tenant on settings fetch error and continue with others."""
        from intric.worker.feeder.capacity import CapacityManager

        tenant_ok = uuid4()
        tenant_fail = uuid4()

        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(
            return_value=(
                0,
                [
                    f"tenant:{tenant_fail}:crawl_pending".encode(),
                    f"tenant:{tenant_ok}:crawl_pending".encode(),
                ],
            )
        )

        manager = CapacityManager(redis_mock, settings=mock_settings)

        async def mock_get_settings(tid):
            if tid == tenant_fail:
                raise Exception("DB connection error")
            return {"crawl_feeder_interval_seconds": 8}

        manager.get_tenant_settings = mock_get_settings

        with patch(
            "intric.worker.feeder.capacity.get_crawler_setting",
            side_effect=mock_crawler_setting_passthrough,
        ):
            result = await manager.get_minimum_feeder_interval()

        # Tenant fail skipped, tenant ok has 8s, global is 10s
        assert result == 8

    @pytest.mark.asyncio
    async def test_returns_default_when_all_tenants_fail(
        self, mock_settings, mock_crawler_setting_passthrough
    ):
        """Should return global default when all tenant settings fetches fail."""
        from intric.worker.feeder.capacity import CapacityManager

        tenant_ids = [uuid4() for _ in range(3)]

        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(
            return_value=(
                0,
                [f"tenant:{tid}:crawl_pending".encode() for tid in tenant_ids],
            )
        )

        manager = CapacityManager(redis_mock, settings=mock_settings)

        async def mock_get_settings(tid):
            raise Exception("All fetches fail")

        manager.get_tenant_settings = mock_get_settings

        with patch(
            "intric.worker.feeder.capacity.get_crawler_setting",
            side_effect=mock_crawler_setting_passthrough,
        ):
            result = await manager.get_minimum_feeder_interval()

        assert result == 10

    # --- Pagination Tests ---

    @pytest.mark.asyncio
    async def test_handles_paginated_scan(
        self, mock_settings, mock_crawler_setting_passthrough
    ):
        """Should correctly process multiple SCAN pages."""
        from intric.worker.feeder.capacity import CapacityManager

        tenant_a = uuid4()
        tenant_b = uuid4()

        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(
            side_effect=[
                (123, [f"tenant:{tenant_a}:crawl_pending".encode()]),  # Page 1
                (0, [f"tenant:{tenant_b}:crawl_pending".encode()]),  # Page 2 (final)
            ]
        )

        manager = CapacityManager(redis_mock, settings=mock_settings)

        async def mock_get_settings(tid):
            if tid == tenant_a:
                return {"crawl_feeder_interval_seconds": 25}
            return {"crawl_feeder_interval_seconds": 7}

        manager.get_tenant_settings = mock_get_settings

        with patch(
            "intric.worker.feeder.capacity.get_crawler_setting",
            side_effect=mock_crawler_setting_passthrough,
        ):
            result = await manager.get_minimum_feeder_interval()

        assert result == 7  # min(25, 7, 10) = 7
        assert redis_mock.scan.call_count == 2

    # --- Key Parsing Edge Cases ---

    @pytest.mark.asyncio
    async def test_skips_invalid_tenant_ids(
        self, mock_settings, mock_crawler_setting_passthrough
    ):
        """Should gracefully skip keys with invalid tenant IDs."""
        from intric.worker.feeder.capacity import CapacityManager

        valid_tenant = uuid4()

        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(
            return_value=(
                0,
                [
                    f"tenant:{valid_tenant}:crawl_pending".encode(),
                    b"tenant:not-a-valid-uuid:crawl_pending",
                    b"malformed-key",
                ],
            )
        )

        manager = CapacityManager(redis_mock, settings=mock_settings)

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 6}

        manager.get_tenant_settings = mock_get_settings

        with patch(
            "intric.worker.feeder.capacity.get_crawler_setting",
            side_effect=mock_crawler_setting_passthrough,
        ):
            result = await manager.get_minimum_feeder_interval()

        assert result == 6

    @pytest.mark.asyncio
    async def test_returns_default_for_string_keys_from_misconfigured_redis(
        self, mock_settings, mock_crawler_setting_passthrough
    ):
        """The canonical Redis boundary requires decode_responses to stay disabled."""
        from intric.worker.feeder.capacity import CapacityManager

        tenant_id = uuid4()

        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(
            return_value=(0, [f"tenant:{tenant_id}:crawl_pending"])  # String, not bytes
        )

        manager = CapacityManager(redis_mock, settings=mock_settings)

        async def mock_get_settings(tid):
            return {"crawl_feeder_interval_seconds": 9}

        manager.get_tenant_settings = mock_get_settings

        with patch(
            "intric.worker.feeder.capacity.get_crawler_setting",
            side_effect=mock_crawler_setting_passthrough,
        ):
            result = await manager.get_minimum_feeder_interval()

        assert result == 10

    @pytest.mark.asyncio
    async def test_handles_null_tenant_settings(
        self, mock_settings, mock_crawler_setting_passthrough
    ):
        """Should use default when get_tenant_settings returns None."""
        from intric.worker.feeder.capacity import CapacityManager

        tenant_id = uuid4()

        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(
            return_value=(0, [f"tenant:{tenant_id}:crawl_pending".encode()])
        )

        manager = CapacityManager(redis_mock, settings=mock_settings)

        async def mock_get_settings(tid):
            return None

        manager.get_tenant_settings = mock_get_settings

        with patch(
            "intric.worker.feeder.capacity.get_crawler_setting",
            side_effect=mock_crawler_setting_passthrough,
        ):
            result = await manager.get_minimum_feeder_interval()

        assert result == 10
