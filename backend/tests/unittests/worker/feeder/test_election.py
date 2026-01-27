"""Unit tests for the LeaderElection module.

Tests the Redis-based distributed lock for singleton feeder election.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestLeaderElectionInit:
    """Tests for LeaderElection initialization."""

    def test_initializes_with_defaults(self):
        """Should initialize with sensible defaults."""
        from intric.worker.feeder.election import LeaderElection

        redis_mock = MagicMock()
        leader = LeaderElection(redis_mock, worker_id="worker-1")

        assert leader._redis is redis_mock
        assert leader._worker_id == "worker-1"
        assert leader._lock_key == "crawl_feeder:leader"
        assert leader._ttl == 30

    def test_accepts_custom_lock_key_and_ttl(self):
        """Should accept custom lock key and TTL."""
        from intric.worker.feeder.election import LeaderElection

        redis_mock = MagicMock()
        leader = LeaderElection(
            redis_mock,
            worker_id="worker-2",
            lock_key="custom:leader:key",
            ttl_seconds=60,
        )

        assert leader._lock_key == "custom:leader:key"
        assert leader._ttl == 60


class TestTryAcquire:
    """Tests for try_acquire method."""

    @pytest.mark.asyncio
    async def test_returns_true_when_lock_acquired(self):
        """Should return True when SET NX succeeds."""
        from intric.worker.feeder.election import LeaderElection

        redis_mock = MagicMock()
        redis_mock.set = AsyncMock(return_value=True)

        leader = LeaderElection(redis_mock, worker_id="worker-1")
        result = await leader.try_acquire()

        assert result is True
        redis_mock.set.assert_called_once_with(
            "crawl_feeder:leader",
            "worker-1",
            nx=True,
            ex=30,
        )

    @pytest.mark.asyncio
    async def test_returns_false_when_lock_held_by_another(self):
        """Should return False when another process holds the lock."""
        from intric.worker.feeder.election import LeaderElection

        redis_mock = MagicMock()
        redis_mock.set = AsyncMock(return_value=None)

        leader = LeaderElection(redis_mock, worker_id="worker-1")
        result = await leader.try_acquire()

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_redis_error(self):
        """Should return False and log warning on Redis error."""
        from intric.worker.feeder.election import LeaderElection

        redis_mock = MagicMock()
        redis_mock.set = AsyncMock(side_effect=Exception("Connection refused"))

        leader = LeaderElection(redis_mock, worker_id="worker-1")
        result = await leader.try_acquire()

        assert result is False


class TestRefresh:
    """Tests for refresh method."""

    @pytest.mark.asyncio
    async def test_returns_true_when_still_owner(self):
        """Should return True when Lua script confirms ownership."""
        from intric.worker.feeder.election import LeaderElection

        redis_mock = MagicMock()

        with patch(
            "intric.worker.feeder.election.LuaScripts.refresh_leader_lock",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_refresh:
            leader = LeaderElection(redis_mock, worker_id="worker-1")
            result = await leader.refresh()

            assert result is True
            mock_refresh.assert_called_once_with(
                redis_mock,
                "crawl_feeder:leader",
                "worker-1",
                30,
            )

    @pytest.mark.asyncio
    async def test_returns_false_when_not_owner(self):
        """Should return False when another process owns the lock."""
        from intric.worker.feeder.election import LeaderElection

        redis_mock = MagicMock()

        with patch(
            "intric.worker.feeder.election.LuaScripts.refresh_leader_lock",
            new_callable=AsyncMock,
            return_value=False,
        ):
            leader = LeaderElection(redis_mock, worker_id="worker-1")
            result = await leader.refresh()

            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        """Should return False on Lua script error."""
        from intric.worker.feeder.election import LeaderElection

        redis_mock = MagicMock()

        with patch(
            "intric.worker.feeder.election.LuaScripts.refresh_leader_lock",
            new_callable=AsyncMock,
            side_effect=Exception("Script error"),
        ):
            leader = LeaderElection(redis_mock, worker_id="worker-1")
            result = await leader.refresh()

            assert result is False


class TestRelease:
    """Tests for release method."""

    @pytest.mark.asyncio
    async def test_returns_true_when_released(self):
        """Should return True when Lua script releases lock."""
        from intric.worker.feeder.election import LeaderElection

        redis_mock = MagicMock()

        with patch(
            "intric.worker.feeder.election.LuaScripts.release_leader_lock",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_release:
            leader = LeaderElection(redis_mock, worker_id="worker-1")
            result = await leader.release()

            assert result is True
            mock_release.assert_called_once_with(
                redis_mock,
                "crawl_feeder:leader",
                "worker-1",
            )

    @pytest.mark.asyncio
    async def test_returns_false_when_not_owner(self):
        """Should return False when another process owns the lock."""
        from intric.worker.feeder.election import LeaderElection

        redis_mock = MagicMock()

        with patch(
            "intric.worker.feeder.election.LuaScripts.release_leader_lock",
            new_callable=AsyncMock,
            return_value=False,
        ):
            leader = LeaderElection(redis_mock, worker_id="worker-1")
            result = await leader.release()

            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        """Should return False on Lua script error."""
        from intric.worker.feeder.election import LeaderElection

        redis_mock = MagicMock()

        with patch(
            "intric.worker.feeder.election.LuaScripts.release_leader_lock",
            new_callable=AsyncMock,
            side_effect=Exception("Script error"),
        ):
            leader = LeaderElection(redis_mock, worker_id="worker-1")
            result = await leader.release()

            assert result is False
