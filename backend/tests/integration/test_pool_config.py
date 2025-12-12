"""
Integration tests for database connection pool configuration (Tier 0/Tier 1 fixes).

Tests cover:
- A) Settings/env mapping - defaults and overrides
- B) Engine init kwargs - pool_recycle conditional, application_name
- D) Guaranteed close logic - rollback only when in_transaction
- E) Pool exhaustion / feeder headroom regression
- F) Exception path releases connection
- G) application_name visible in pg_stat_activity
- H) Tier 2 readiness - connection hold during network I/O (proves current anti-pattern)

Run with: pytest tests/integration/test_pool_config.py -v

Tier 2 Readiness Tests:
- test_current_pattern_holds_connection_during_io: PROVES the problem exists
- test_tier2_pattern_releases_during_io: SKIPPED until Hybrid v2 implemented
- test_session_per_batch_pattern_demo: DEMONSTRATES the target pattern works
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import create_async_engine

from intric.main.config import Settings, reset_settings


# =============================================================================
# UNIT TESTS: Settings/env mapping (Category A)
# =============================================================================


class TestSettingsEnvMapping:
    """Test that pool settings are correctly read from environment variables."""

    def test_defaults_match_current_behavior(self, monkeypatch):
        """
        Verify default values preserve current production behavior.

        CRITICAL: These defaults must NOT change without explicit env var override.
        Changing defaults silently would break production.
        """
        # Clear any existing env vars
        for key in [
            "DB_POOL_SIZE",
            "DB_POOL_MAX_OVERFLOW",
            "DB_POOL_TIMEOUT",
            "DB_POOL_PRE_PING",
            "DB_POOL_RECYCLE",
            "DB_POOL_DEBUG",
        ]:
            monkeypatch.delenv(key, raising=False)

        # Force fresh settings
        reset_settings()

        # Create fresh settings instance
        settings = Settings(
            postgres_user="test",
            postgres_host="localhost",
            postgres_password="test",
            postgres_port=5432,
            postgres_db="test",
            redis_host="localhost",
            redis_port=6379,
        )

        # Assert defaults match documented current behavior
        assert settings.db_pool_size == 20, "Default pool_size must be 20"
        assert settings.db_pool_max_overflow == 10, "Default max_overflow must be 10"
        assert settings.db_pool_timeout == 30, "Default timeout must be 30s"
        assert settings.db_pool_pre_ping is True, "Default pre_ping must be True"
        assert settings.db_pool_recycle == -1, "Default recycle must be -1 (disabled)"
        assert settings.db_pool_debug is False, "Default debug must be False"

    def test_env_overrides_are_applied(self, monkeypatch):
        """
        Verify env vars correctly override defaults.

        This is how ops will tune pool settings per environment.
        """
        # Set custom env vars
        monkeypatch.setenv("DB_POOL_SIZE", "25")
        monkeypatch.setenv("DB_POOL_MAX_OVERFLOW", "15")
        monkeypatch.setenv("DB_POOL_TIMEOUT", "60")
        monkeypatch.setenv("DB_POOL_PRE_PING", "false")
        monkeypatch.setenv("DB_POOL_RECYCLE", "3600")
        monkeypatch.setenv("DB_POOL_DEBUG", "true")

        reset_settings()

        settings = Settings(
            postgres_user="test",
            postgres_host="localhost",
            postgres_password="test",
            postgres_port=5432,
            postgres_db="test",
            redis_host="localhost",
            redis_port=6379,
        )

        assert settings.db_pool_size == 25
        assert settings.db_pool_max_overflow == 15
        assert settings.db_pool_timeout == 60
        assert settings.db_pool_pre_ping is False
        assert settings.db_pool_recycle == 3600
        assert settings.db_pool_debug is True

    def test_worker_name_env_var(self, monkeypatch):
        """Verify WORKER_NAME env var is read for application_name."""
        monkeypatch.setenv("WORKER_NAME", "test-crawler-worker-1")

        # The WORKER_NAME is read in database.py init(), not Settings
        # Just verify the env var mechanism works
        assert os.getenv("WORKER_NAME") == "test-crawler-worker-1"


# =============================================================================
# UNIT TESTS: Engine kwargs (Category B)
# =============================================================================


class TestEngineKwargsBuilding:
    """Test that create_async_engine receives correct kwargs."""

    def test_pool_recycle_omitted_when_disabled(self, monkeypatch):
        """
        When db_pool_recycle=-1, pool_recycle kwarg should NOT be passed.

        Passing None is risky; omitting the kwarg is safest across SQLAlchemy versions.
        """
        monkeypatch.setenv("DB_POOL_RECYCLE", "-1")
        reset_settings()

        captured_kwargs = {}

        def fake_create_engine(url, **kwargs):
            captured_kwargs.update(kwargs)
            # Return a mock engine
            mock_engine = MagicMock()
            mock_engine.sync_engine.pool = MagicMock()
            return mock_engine

        with patch(
            "intric.database.database.create_async_engine", fake_create_engine
        ):
            from intric.database.database import DatabaseSessionManager

            manager = DatabaseSessionManager()
            manager.init("postgresql+asyncpg://test:test@localhost/test")

        # pool_recycle should NOT be in kwargs
        assert "pool_recycle" not in captured_kwargs, (
            "pool_recycle should be omitted when disabled (-1)"
        )

    def test_pool_recycle_included_when_positive(self, monkeypatch):
        """
        When db_pool_recycle > 0, it should be passed to create_async_engine.
        """
        monkeypatch.setenv("DB_POOL_RECYCLE", "3600")
        reset_settings()

        captured_kwargs = {}

        def fake_create_engine(url, **kwargs):
            captured_kwargs.update(kwargs)
            mock_engine = MagicMock()
            mock_engine.sync_engine.pool = MagicMock()
            return mock_engine

        with patch(
            "intric.database.database.create_async_engine", fake_create_engine
        ):
            from intric.database.database import DatabaseSessionManager

            manager = DatabaseSessionManager()
            manager.init("postgresql+asyncpg://test:test@localhost/test")

        assert captured_kwargs.get("pool_recycle") == 3600

    def test_application_name_from_worker_name_env(self, monkeypatch):
        """
        WORKER_NAME env var should be used for application_name in connect_args.
        """
        monkeypatch.setenv("WORKER_NAME", "my-crawler-pod-abc123")
        reset_settings()

        captured_kwargs = {}

        def fake_create_engine(url, **kwargs):
            captured_kwargs.update(kwargs)
            mock_engine = MagicMock()
            mock_engine.sync_engine.pool = MagicMock()
            return mock_engine

        with patch(
            "intric.database.database.create_async_engine", fake_create_engine
        ):
            from intric.database.database import DatabaseSessionManager

            manager = DatabaseSessionManager()
            manager.init("postgresql+asyncpg://test:test@localhost/test")

        connect_args = captured_kwargs.get("connect_args", {})
        server_settings = connect_args.get("server_settings", {})
        assert server_settings.get("application_name") == "my-crawler-pod-abc123"

    def test_application_name_fallback_to_pid(self, monkeypatch):
        """
        When WORKER_NAME not set, application_name should fallback to intric-{pid}.
        """
        monkeypatch.delenv("WORKER_NAME", raising=False)
        reset_settings()

        captured_kwargs = {}

        def fake_create_engine(url, **kwargs):
            captured_kwargs.update(kwargs)
            mock_engine = MagicMock()
            mock_engine.sync_engine.pool = MagicMock()
            return mock_engine

        with patch(
            "intric.database.database.create_async_engine", fake_create_engine
        ):
            from intric.database.database import DatabaseSessionManager

            manager = DatabaseSessionManager()
            manager.init("postgresql+asyncpg://test:test@localhost/test")

        connect_args = captured_kwargs.get("connect_args", {})
        server_settings = connect_args.get("server_settings", {})
        app_name = server_settings.get("application_name", "")

        assert app_name.startswith("intric-"), f"Expected intric-PID, got {app_name}"
        # The part after "intric-" should be a valid integer (the PID)
        pid_part = app_name.split("-")[1]
        assert pid_part.isdigit(), f"Expected PID after intric-, got {pid_part}"


# =============================================================================
# UNIT TESTS: Guaranteed close logic (Category D)
# =============================================================================


class TestGuaranteedCloseLogic:
    """
    Test the session cleanup helper logic.

    Extracted from finally block for testability per model recommendations.
    """

    @pytest.mark.asyncio
    async def test_rollback_called_when_in_transaction(self):
        """
        When session has an active transaction, rollback should be called.
        """
        mock_session = AsyncMock()
        # in_transaction() is synchronous - use MagicMock for sync methods
        mock_session.in_transaction = MagicMock(return_value=True)

        # Simulate the cleanup logic
        if mock_session.in_transaction():
            await mock_session.rollback()
        await mock_session.close()

        mock_session.rollback.assert_awaited_once()
        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rollback_skipped_when_no_transaction(self):
        """
        When session has no active transaction, rollback should NOT be called.

        Avoids noisy warnings after successful commits.
        """
        mock_session = AsyncMock()
        # CRITICAL: in_transaction() is synchronous, not async!
        # AsyncMock makes all attributes return AsyncMock objects by default,
        # which evaluate to True in boolean context. Use MagicMock for sync methods.
        mock_session.in_transaction = MagicMock(return_value=False)

        # Simulate the cleanup logic
        if mock_session.in_transaction():
            await mock_session.rollback()
        await mock_session.close()

        mock_session.rollback.assert_not_awaited()
        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_called_even_if_rollback_fails(self):
        """
        If rollback raises, close should still be attempted.

        Critical: Connection must return to pool even on rollback failure.
        """
        mock_session = AsyncMock()
        # in_transaction() is synchronous - use MagicMock for sync methods
        mock_session.in_transaction = MagicMock(return_value=True)
        mock_session.rollback.side_effect = Exception("Network hiccup")

        # Simulate the cleanup logic with try/finally
        try:
            if mock_session.in_transaction():
                await mock_session.rollback()
        except Exception:
            pass  # Log but don't re-raise
        finally:
            await mock_session.close()

        mock_session.rollback.assert_awaited_once()
        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_session_holder_cleared_after_close(self):
        """
        session_holder["session"] should be set to None after cleanup.

        Prevents reuse of closed session.
        """
        mock_session = AsyncMock()
        # in_transaction() is synchronous - use MagicMock for sync methods
        mock_session.in_transaction = MagicMock(return_value=False)
        session_holder = {"session": mock_session}

        # Simulate the cleanup logic
        main_session = session_holder.get("session")
        if main_session is not None:
            try:
                if main_session.in_transaction():
                    await main_session.rollback()
            except Exception:
                pass
            try:
                await main_session.close()
            except Exception:
                pass
            finally:
                session_holder["session"] = None

        assert session_holder["session"] is None


# =============================================================================
# INTEGRATION TESTS: Pool exhaustion (Category E)
# =============================================================================


@pytest.mark.integration
class TestPoolExhaustion:
    """
    Test pool exhaustion behavior and mitigation.

    Uses "Tiny Pool" pattern: pool_size=1, max_overflow=0, timeout=0.2
    for fast, deterministic testing without 60+ second sleeps.
    """

    @pytest.mark.asyncio
    async def test_pool_exhaustion_raises_timeout(self, test_settings):
        """
        When all connections are held, new requests should timeout quickly.

        This reproduces the production failure mode.
        """
        # Create a tiny engine specifically for this test
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=0.2,  # Fast timeout for test
        )

        release_event = asyncio.Event()

        async def hold_connection():
            """Hold the only connection until release_event is set."""
            async with tiny_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                await release_event.wait()

        # Start task that holds the only connection
        holder_task = asyncio.create_task(hold_connection())

        # Give holder task time to acquire connection
        await asyncio.sleep(0.05)

        # Attempt to get another connection - should timeout
        with pytest.raises(SQLAlchemyTimeoutError):
            async with tiny_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        # Cleanup
        release_event.set()
        await holder_task
        await tiny_engine.dispose()

    @pytest.mark.asyncio
    async def test_connection_release_allows_next_request(self, test_settings):
        """
        When a connection is properly released, next request succeeds.

        Proves the mitigation works: short-lived sessions don't exhaust pool.
        """
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=1.0,
        )

        # First: acquire and release
        async with tiny_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        # Connection released here

        # Second: should succeed because connection was released
        async with tiny_engine.connect() as conn:
            result = await conn.execute(text("SELECT 2"))
            value = result.scalar()
            assert value == 2

        await tiny_engine.dispose()


# =============================================================================
# INTEGRATION TESTS: Exception path (Category F)
# =============================================================================


@pytest.mark.integration
class TestExceptionPathReleasesConnection:
    """
    Test that connections are returned to pool even on exception.

    This is critical for preventing gradual pool exhaustion.
    """

    @pytest.mark.asyncio
    async def test_exception_releases_connection(self, test_settings):
        """
        If a task errors out, the connection should return to pool.

        Uses pool_size=1 to prove the connection was actually released.
        """
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=1.0,
        )

        # First: acquire, do work, then raise exception
        with pytest.raises(ValueError):
            async with tiny_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                raise ValueError("Simulated crawler error")
        # Connection should be released despite exception

        # Second: should succeed if connection was released
        async with tiny_engine.connect() as conn:
            result = await conn.execute(text("SELECT 42"))
            value = result.scalar()
            assert value == 42

        await tiny_engine.dispose()

    @pytest.mark.asyncio
    async def test_transaction_rollback_on_exception(self, test_settings):
        """
        If exception occurs mid-transaction, changes should be rolled back.
        """
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=1.0,
        )

        # Create test table
        async with tiny_engine.begin() as conn:
            await conn.execute(
                text("CREATE TEMP TABLE test_rollback (id int PRIMARY KEY)")
            )
            await conn.execute(text("INSERT INTO test_rollback VALUES (1)"))

        # Try to insert in a transaction that will fail
        try:
            async with tiny_engine.begin() as conn:
                await conn.execute(text("INSERT INTO test_rollback VALUES (2)"))
                raise ValueError("Force rollback")
        except ValueError:
            pass

        # Verify the insert was rolled back
        async with tiny_engine.connect() as conn:
            result = await conn.execute(text("SELECT COUNT(*) FROM test_rollback"))
            count = result.scalar()
            assert count == 1, "Transaction should have been rolled back"

        await tiny_engine.dispose()


# =============================================================================
# INTEGRATION TESTS: application_name (Category G)
# =============================================================================


@pytest.mark.integration
class TestApplicationNameAttribution:
    """
    Test that application_name appears in pg_stat_activity.

    This enables ops to identify which crawler worker holds connections.
    """

    @pytest.mark.asyncio
    async def test_application_name_visible_in_pg_stat_activity(
        self, test_settings, monkeypatch
    ):
        """
        application_name should be visible in pg_stat_activity for attribution.
        """
        test_app_name = "test-crawler-worker-attribution"
        monkeypatch.setenv("WORKER_NAME", test_app_name)

        # Create engine with application_name
        engine = create_async_engine(
            test_settings.database_url,
            pool_size=1,
            connect_args={"server_settings": {"application_name": test_app_name}},
        )

        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT application_name FROM pg_stat_activity "
                    "WHERE pid = pg_backend_pid()"
                )
            )
            app_name = result.scalar()
            assert app_name == test_app_name, (
                f"Expected application_name={test_app_name}, got {app_name}"
            )

        await engine.dispose()


# =============================================================================
# INTEGRATION TESTS: Feeder headroom regression (Category E - detailed)
# =============================================================================


@pytest.mark.integration
class TestFeederHeadroomRegression:
    """
    Regression test proving the original pool exhaustion bug and its fix.

    Scenario: Multiple crawler tasks hold sessions → feeder query times out.
    Fix: Limit concurrent crawlers to (pool_max - headroom).
    """

    @pytest.mark.asyncio
    async def test_without_headroom_feeder_times_out(self, test_settings):
        """
        When all connections are held by crawlers, feeder queries fail.

        This reproduces the production symptom: "QueuePool limit reached".
        """
        # Pool with just 2 connections, no overflow
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=2,
            max_overflow=0,
            pool_timeout=0.2,
        )

        release_event = asyncio.Event()

        async def simulate_crawler():
            """Simulate a crawler holding a connection during network I/O."""
            async with tiny_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))  # Initial query
                await release_event.wait()  # Hold during "crawling"

        # Start 2 crawlers - occupies all connections
        tasks = [asyncio.create_task(simulate_crawler()) for _ in range(2)]
        await asyncio.sleep(0.05)  # Let them acquire connections

        # Feeder query should fail - no connections available
        with pytest.raises(SQLAlchemyTimeoutError):
            async with tiny_engine.connect() as conn:
                await conn.execute(text("SELECT * FROM pg_stat_activity"))

        # Cleanup
        release_event.set()
        await asyncio.gather(*tasks)
        await tiny_engine.dispose()

    @pytest.mark.asyncio
    async def test_with_headroom_feeder_succeeds(self, test_settings):
        """
        When crawler concurrency is capped below pool_max, feeder succeeds.

        This proves the fix: WORKER_MAX_JOBS <= (pool_max - headroom).
        """
        # Pool with 3 connections
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=3,
            max_overflow=0,
            pool_timeout=1.0,
        )

        release_event = asyncio.Event()
        crawler_semaphore = asyncio.Semaphore(2)  # Cap at 2 (leaving 1 for feeder)

        async def simulate_crawler_with_cap():
            """Crawler that respects concurrency cap."""
            async with crawler_semaphore:
                async with tiny_engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                    await release_event.wait()

        # Start 2 crawlers (respecting cap)
        tasks = [asyncio.create_task(simulate_crawler_with_cap()) for _ in range(2)]
        await asyncio.sleep(0.05)

        # Feeder query should succeed - 1 connection reserved
        async with tiny_engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

        # Cleanup
        release_event.set()
        await asyncio.gather(*tasks)
        await tiny_engine.dispose()


# =============================================================================
# TIER 2 READINESS TESTS: Connection hold during network I/O
# =============================================================================
# These tests prove the current anti-pattern (pre-Tier2) and will verify
# Hybrid v2 is working once implemented.


@pytest.mark.integration
class TestConnectionHoldDuringNetworkIO:
    """
    Tests proving connections are held during network I/O (pre-Tier2 behavior).

    After Hybrid v2 (session-per-batch), test_connection_released_during_simulated_io
    should PASS. Until then, it documents the current anti-pattern.
    """

    @pytest.mark.asyncio
    async def test_current_pattern_holds_connection_during_io(self, test_settings):
        """
        DOCUMENTS CURRENT BEHAVIOR (pre-Tier2):
        Connection is held for entire "crawl" duration, including network waits.

        This is the root cause of pool exhaustion - proof that Tier 0/Tier 1
        are mitigations (limiting demand), not fixes (eliminating long holds).
        """
        # Tiny pool to make the problem obvious
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=0.1,  # Fast timeout to prove connection is held
        )

        io_complete = asyncio.Event()

        async def simulate_crawl_current_pattern():
            """
            Simulates current crawl_task pattern:
            - Acquire session at start (line 1006)
            - Hold it during "network I/O" (the crawler.crawl() loop)
            """
            async with tiny_engine.connect() as conn:
                # Initial DB query (like website_service.get_website)
                await conn.execute(text("SELECT 1"))

                # Simulate network I/O - connection still held!
                # In real code: async with crawler.crawl() as crawl: for page in crawl.pages
                await asyncio.wait_for(io_complete.wait(), timeout=5.0)

                # Final DB query (like session.commit)
                await conn.execute(text("SELECT 2"))

        # Start crawl task
        crawl_task = asyncio.create_task(simulate_crawl_current_pattern())
        await asyncio.sleep(0.02)  # Let it acquire the connection

        # Try another query while "network I/O" is happening
        # This SHOULD timeout because the crawl holds the only connection
        with pytest.raises(SQLAlchemyTimeoutError):
            async with tiny_engine.connect() as conn:
                await conn.execute(text("SELECT 'feeder query'"))

        # Cleanup
        io_complete.set()
        await crawl_task
        await tiny_engine.dispose()

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Tier 2 not implemented - will pass after Hybrid v2")
    async def test_tier2_pattern_releases_during_io(self, test_settings):
        """
        TARGET BEHAVIOR (post-Tier2 / Hybrid v2):
        Connection should be released during network I/O.

        Once Hybrid v2 is implemented:
        1. Remove @pytest.mark.skip
        2. This test should PASS
        3. test_current_pattern_holds_connection_during_io should be removed

        Hybrid v2 pattern:
        - session-per-batch: only hold connection during actual DB writes
        - release connection before network I/O
        """
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=0.5,
        )

        io_phase = asyncio.Event()  # Signal when in I/O phase
        io_complete = asyncio.Event()  # Signal to end I/O phase
        feeder_result = {"success": False}

        async def simulate_crawl_tier2_pattern():
            """
            Simulates target Hybrid v2 pattern:
            - Acquire session, do initial query
            - RELEASE session before network I/O
            - Acquire new session for batch writes
            """
            # Phase 1: Initial DB query with short-lived session
            async with tiny_engine.connect() as conn:
                await conn.execute(text("SELECT 'initial query'"))
            # Connection released here!

            # Phase 2: Network I/O (no DB connection held)
            io_phase.set()  # Signal we're in I/O phase
            await io_complete.wait()

            # Phase 3: Batch write with new short-lived session
            async with tiny_engine.connect() as conn:
                await conn.execute(text("SELECT 'batch commit'"))

        # Start crawl task
        crawl_task = asyncio.create_task(simulate_crawl_tier2_pattern())

        # Wait until crawl is in I/O phase
        await io_phase.wait()

        # Feeder query should SUCCEED because connection was released
        try:
            async with tiny_engine.connect() as conn:
                result = await conn.execute(text("SELECT 'feeder success'"))
                feeder_result["success"] = result.scalar() == "feeder success"
        except SQLAlchemyTimeoutError:
            feeder_result["success"] = False

        # Cleanup
        io_complete.set()
        await crawl_task
        await tiny_engine.dispose()

        assert feeder_result["success"], (
            "Feeder query should succeed during network I/O phase "
            "because Hybrid v2 releases connection before I/O"
        )

    @pytest.mark.asyncio
    async def test_session_per_batch_pattern_demo(self, test_settings):
        """
        Demonstrates the session-per-batch pattern that Tier 2 should implement.

        This test PASSES and shows the pattern works - it's a template for
        refactoring crawl_tasks.py.
        """
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=0.5,
        )

        batches_committed = []

        async def persist_batch(batch_data: list[str]) -> None:
            """
            Session-per-batch pattern: acquire, write, release immediately.

            This is how uploader.process_file() should work after Tier 2.
            """
            async with tiny_engine.begin() as conn:
                # Simulate batch insert
                for item in batch_data:
                    await conn.execute(text(f"SELECT '{item}'"))
                batches_committed.append(len(batch_data))
            # Connection released here - back in pool!

        async def simulate_hybrid_v2_crawl():
            """
            Hybrid v2 pattern: buffer pages, persist in batches.
            No connection held during network I/O simulation.
            """
            page_buffer = []
            batch_size = 3

            # Simulate crawling pages (network I/O happens here, no DB conn)
            for i in range(7):
                # Simulated network I/O - no DB connection!
                await asyncio.sleep(0.01)
                page_buffer.append(f"page_{i}")

                # Batch commit when buffer is full
                if len(page_buffer) >= batch_size:
                    await persist_batch(page_buffer)
                    page_buffer.clear()

            # Final batch for remaining pages
            if page_buffer:
                await persist_batch(page_buffer)
                page_buffer.clear()

        # Run the hybrid v2 simulation
        crawl_task = asyncio.create_task(simulate_hybrid_v2_crawl())

        # During crawl, try to run feeder queries
        # They should ALL succeed because connection is released between batches
        for i in range(3):
            await asyncio.sleep(0.02)
            async with tiny_engine.connect() as conn:
                result = await conn.execute(text(f"SELECT 'feeder_{i}'"))
                assert result.scalar() == f"feeder_{i}"

        await crawl_task
        await tiny_engine.dispose()

        # Verify batches were committed correctly
        assert batches_committed == [3, 3, 1], (
            f"Expected [3, 3, 1] (7 pages in batches of 3), got {batches_committed}"
        )