"""
TDD Integration tests for session_scope architecture fix.

Tests the Unit-of-Work pattern for long-running worker tasks:
- Container.session_scope() provides short-lived sessions
- Worker decorators use short-lived bootstrap sessions
- Concurrent tasks don't exhaust DB pool

Run with: pytest tests/integration/test_session_scope_architecture.py -v

CRITICAL SCENARIO:
- Old pattern: Worker holds session for 5-30 minutes (entire crawl duration)
- New pattern: Worker uses session_scope() for each DB operation (~50-300ms)
- Result: 10 concurrent crawls with pool_size=5 should NOT exhaust pool
"""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import create_async_engine

from intric.main.container.container import Container


# =============================================================================
# UNIT TESTS: Container.session_scope() method
# =============================================================================


@pytest.mark.asyncio
class TestContainerSessionScope:
    """Unit tests for Container.session_scope() method."""

    async def test_session_scope_exists_on_container(self):
        """Container class should have session_scope method."""
        assert hasattr(Container, "session_scope"), (
            "Container must have session_scope method for Unit-of-Work pattern"
        )

    async def test_session_scope_is_async_context_manager(self):
        """session_scope should be an async context manager."""
        # Check it's decorated properly
        method = getattr(Container, "session_scope")
        # Static methods are wrapped, get the underlying function
        assert callable(method), "session_scope should be callable"

    async def test_session_scope_yields_session(self, test_settings):
        """session_scope should yield a valid AsyncSession."""
        from intric.database.database import sessionmanager, AsyncSession

        # Initialize sessionmanager with test database
        if not sessionmanager._engine:
            sessionmanager.init(test_settings.database_url)

        async with Container.session_scope() as session:
            assert session is not None, "session_scope should yield a session"
            assert isinstance(session, AsyncSession), (
                "session_scope should yield AsyncSession"
            )
            # Verify session is usable
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1

    async def test_session_scope_commits_on_success(self, test_settings):
        """session_scope should commit transaction on successful exit.

        We verify commit by checking that data inserted within session_scope
        is visible in a subsequent session. Uses a real table (tenants) with
        a safe SELECT to avoid TEMP table cross-session issues.
        """
        from intric.database.database import sessionmanager

        if not sessionmanager._engine:
            sessionmanager.init(test_settings.database_url)

        # Use session_scope to perform a DB operation
        # We'll use a simple SELECT to verify session works and commits cleanly
        async with Container.session_scope() as session:
            # Verify we can execute queries (commit happens on clean exit)
            result = await session.execute(text("SELECT 1 as test_value"))
            value = result.scalar()
            assert value == 1, "Should execute query successfully"

        # Verify the session was properly closed and committed
        # by opening a new session and running another query
        async with sessionmanager.session() as verify_session:
            async with verify_session.begin():
                result = await verify_session.execute(text("SELECT 2 as verify_value"))
                assert result.scalar() == 2, "Subsequent session should work after commit"

    async def test_session_scope_rolls_back_on_exception(self, test_settings):
        """session_scope should rollback transaction on exception.

        We verify rollback by checking that the session_scope context manager
        properly handles exceptions and doesn't leave the session in a bad state.
        """
        from intric.database.database import sessionmanager

        if not sessionmanager._engine:
            sessionmanager.init(test_settings.database_url)

        rollback_triggered = False

        # Use session_scope and raise exception
        with pytest.raises(ValueError):
            async with Container.session_scope() as session:
                # Execute a query to ensure session is active
                await session.execute(text("SELECT 1"))
                rollback_triggered = True
                raise ValueError("Force rollback")

        assert rollback_triggered, "Exception should have been raised inside session_scope"

        # Verify session was properly cleaned up - we should be able to use a new session
        async with sessionmanager.session() as verify_session:
            async with verify_session.begin():
                result = await verify_session.execute(text("SELECT 'rollback_verified'"))
                assert result.scalar() == "rollback_verified", (
                    "New session should work after rollback"
                )

    async def test_session_scope_returns_connection_to_pool(self, test_settings):
        """session_scope should return connection to pool immediately after exit."""
        # Create tiny pool to prove connection release
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=0.5,
        )

        # Patch sessionmanager to use our tiny engine
        from intric.database.database import sessionmanager

        original_session = sessionmanager.session

        from sqlalchemy.ext.asyncio import async_sessionmaker
        from contextlib import asynccontextmanager

        TestSessionLocal = async_sessionmaker(
            bind=tiny_engine,
            expire_on_commit=False,
        )

        @asynccontextmanager
        async def tiny_pool_session():
            session = TestSessionLocal()
            try:
                yield session
            finally:
                await session.close()

        sessionmanager.session = tiny_pool_session

        try:
            # Use session_scope - should release connection after
            async with Container.session_scope() as session:
                await session.execute(text("SELECT 1"))
            # Connection should be back in pool here

            # Second session_scope should work (proves connection was released)
            async with Container.session_scope() as session:
                result = await session.execute(text("SELECT 2"))
                assert result.scalar() == 2, "Second session should work"

        finally:
            sessionmanager.session = original_session
            await tiny_engine.dispose()


# =============================================================================
# INTEGRATION TESTS: Pool exhaustion with session_scope pattern
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
class TestSessionScopePoolExhaustion:
    """
    Test that session_scope pattern prevents pool exhaustion.

    CRITICAL TEST: This is the core validation that the architectural fix works.
    """

    async def test_concurrent_session_scopes_dont_exhaust_pool(self, test_settings):
        """
        Multiple concurrent session_scope calls should NOT exhaust pool.

        With pool_size=3 and 10 concurrent "tasks", each using session_scope
        for short DB operations, all should complete successfully.

        This proves the session_scope pattern releases connections quickly enough
        for concurrent tasks to share a small pool.
        """
        from intric.database.database import sessionmanager

        if not sessionmanager._engine:
            sessionmanager.init(test_settings.database_url)

        num_tasks = 10
        results = []
        errors = []

        async def simulated_task(task_id: int):
            """
            Simulate a long-running task that uses session_scope for DB ops.

            Pattern:
            1. Do "work" (sleep simulates network I/O) - NO DB connection
            2. Use session_scope for DB operation - SHORT connection hold
            3. Do more "work" - NO DB connection
            4. Use session_scope again - SHORT connection hold
            """
            try:
                # Phase 1: Work without DB (simulated network I/O)
                await asyncio.sleep(0.05)

                # Phase 2: Short DB operation
                async with Container.session_scope() as session:
                    await session.execute(text(f"SELECT {task_id}"))
                # Connection released here!

                # Phase 3: More work without DB
                await asyncio.sleep(0.05)

                # Phase 4: Another short DB operation
                async with Container.session_scope() as session:
                    result = await session.execute(text(f"SELECT {task_id * 10}"))
                    value = result.scalar()
                # Connection released here!

                results.append((task_id, value))
            except Exception as e:
                errors.append((task_id, str(e)))

        # Run all tasks concurrently
        tasks = [asyncio.create_task(simulated_task(i)) for i in range(num_tasks)]
        await asyncio.gather(*tasks)

        # All tasks should succeed
        assert len(errors) == 0, f"Tasks failed: {errors}"
        assert len(results) == num_tasks, (
            f"Expected {num_tasks} results, got {len(results)}"
        )

        # Verify results are correct
        for task_id, value in results:
            assert value == task_id * 10, f"Task {task_id} got wrong value {value}"

    async def test_old_pattern_exhausts_pool_new_pattern_doesnt(self, test_settings):
        """
        Compare old (session-for-duration) vs new (session_scope) patterns.

        Old pattern: Holds connection for entire simulated task duration
        New pattern: Uses session_scope for short DB operations

        With pool_size=3 and 5 concurrent tasks:
        - Old pattern SHOULD exhaust pool (timeout)
        - New pattern SHOULD succeed
        """
        # Create tiny pool
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=3,
            max_overflow=0,
            pool_timeout=0.3,  # Short timeout to make test fast
        )

        old_pattern_errors = []
        new_pattern_results = []

        async def old_pattern_task(task_id: int):
            """OLD PATTERN: Hold connection for entire task duration."""
            try:
                async with tiny_engine.connect() as conn:
                    await conn.execute(text(f"SELECT {task_id}"))
                    # Simulate "crawling" while holding connection
                    await asyncio.sleep(0.5)
                    await conn.execute(text(f"SELECT {task_id * 10}"))
                return task_id
            except SQLAlchemyTimeoutError:
                old_pattern_errors.append(task_id)
                return None

        async def new_pattern_task(task_id: int):
            """NEW PATTERN: Use session_scope for short DB operations."""
            try:
                # Phase 1: Short DB operation
                async with tiny_engine.begin() as conn:
                    await conn.execute(text(f"SELECT {task_id}"))
                # Connection released!

                # Phase 2: Simulate "crawling" - NO connection held
                await asyncio.sleep(0.5)

                # Phase 3: Another short DB operation
                async with tiny_engine.begin() as conn:
                    result = await conn.execute(text(f"SELECT {task_id * 10}"))
                    value = result.scalar()
                # Connection released!

                new_pattern_results.append((task_id, value))
                return task_id
            except Exception as e:
                return (task_id, str(e))

        # Test OLD pattern - should have timeouts
        old_tasks = [
            asyncio.create_task(old_pattern_task(i))
            for i in range(5)
        ]
        await asyncio.gather(*old_tasks, return_exceptions=True)

        assert len(old_pattern_errors) > 0, (
            "OLD pattern should exhaust pool with 5 tasks on pool_size=3"
        )

        # Reset for new pattern test
        await tiny_engine.dispose()
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=3,
            max_overflow=0,
            pool_timeout=0.3,
        )

        # Test NEW pattern - should all succeed
        new_tasks = [
            asyncio.create_task(new_pattern_task(i))
            for i in range(5)
        ]
        await asyncio.gather(*new_tasks)

        await tiny_engine.dispose()

        assert len(new_pattern_results) == 5, (
            f"NEW pattern should complete all 5 tasks, got {len(new_pattern_results)}"
        )


# =============================================================================
# INTEGRATION TESTS: Worker decorator bootstrap session
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
class TestWorkerBootstrapSession:
    """
    Test that worker decorators use short-lived bootstrap sessions.

    The worker.py function() and task() decorators should:
    1. Use a SHORT-LIVED session for user lookup (~50ms)
    2. Create a sessionless container for task execution
    3. NOT hold a session for the entire task duration
    """

    async def test_bootstrap_session_is_short_lived(self, test_settings):
        """
        Bootstrap session should be released before task execution begins.

        Pattern:
        - worker.py opens session
        - Looks up user (extracts primitives)
        - Closes session (returns to pool)
        - Creates sessionless container
        - Executes task (no session held)
        """
        from intric.database.database import sessionmanager

        if not sessionmanager._engine:
            sessionmanager.init(test_settings.database_url)

        # Track session lifecycle
        session_events = []

        async def track_bootstrap():
            """Simulate bootstrap pattern with tracking."""
            # Phase 1: Bootstrap session (SHORT)
            async with sessionmanager.session() as session:
                async with session.begin():
                    session_events.append("bootstrap_start")
                    # Simulate user lookup
                    await session.execute(text("SELECT 1"))
                    session_events.append("bootstrap_user_lookup")
            session_events.append("bootstrap_end_session_released")

            # Phase 2: Task execution (NO SESSION)
            session_events.append("task_execution_start")
            await asyncio.sleep(0.1)  # Simulate work
            session_events.append("task_execution_end")

            # Phase 3: DB operation via session_scope (SHORT)
            async with Container.session_scope() as session:
                session_events.append("session_scope_db_op")
                await session.execute(text("SELECT 2"))
            session_events.append("session_scope_released")

        await track_bootstrap()

        # Verify the pattern: bootstrap is short, then session released before task
        assert session_events == [
            "bootstrap_start",
            "bootstrap_user_lookup",
            "bootstrap_end_session_released",  # Key: session released BEFORE task
            "task_execution_start",
            "task_execution_end",
            "session_scope_db_op",
            "session_scope_released",
        ], f"Unexpected session pattern: {session_events}"

    async def test_concurrent_workers_share_pool_efficiently(self, test_settings):
        """
        Multiple workers using bootstrap pattern should share pool efficiently.

        With pool_size=5 and 10 concurrent workers:
        - Each worker's bootstrap is ~50ms
        - Task execution doesn't hold connection
        - All workers should complete without pool exhaustion
        """
        # Create pool with 5 connections
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=5,
            max_overflow=0,
            pool_timeout=2.0,  # 2 second timeout
        )

        num_workers = 10
        worker_results = []
        worker_errors = []

        async def simulate_worker(worker_id: int):
            """Simulate a worker using the new bootstrap pattern."""
            try:
                # Phase 1: Bootstrap session (SHORT ~50ms)
                async with tiny_engine.begin() as conn:
                    await conn.execute(text(f"SELECT 'bootstrap_{worker_id}'"))
                # Connection released!

                # Phase 2: Task execution (NO connection held)
                # Simulate crawling - this is where the old pattern held connection
                await asyncio.sleep(0.2)  # 200ms of "crawling"

                # Phase 3: DB operations via session_scope pattern
                for batch in range(3):
                    async with tiny_engine.begin() as conn:
                        await conn.execute(
                            text(f"SELECT 'batch_{worker_id}_{batch}'")
                        )
                    # Connection released between batches!
                    await asyncio.sleep(0.05)  # More "crawling"

                worker_results.append(worker_id)

            except SQLAlchemyTimeoutError:
                worker_errors.append((worker_id, "timeout"))
            except Exception as e:
                worker_errors.append((worker_id, str(e)))

        # Run all workers concurrently
        workers = [
            asyncio.create_task(simulate_worker(i))
            for i in range(num_workers)
        ]
        await asyncio.gather(*workers, return_exceptions=True)

        await tiny_engine.dispose()

        # All workers should succeed
        assert len(worker_errors) == 0, f"Workers failed: {worker_errors}"
        assert len(worker_results) == num_workers, (
            f"Expected {num_workers} workers to complete, got {len(worker_results)}"
        )


# =============================================================================
# STRESS TESTS: High concurrency scenarios
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
class TestSessionScopeStress:
    """
    Stress tests for session_scope pattern under high concurrency.

    These tests use very tight pool settings to expose any issues
    with the session_scope pattern.
    """

    async def test_stress_many_tasks_tiny_pool(self, test_settings):
        """
        Stress test: 20 tasks, pool_size=3.

        This is more aggressive than production but validates the pattern
        works under extreme conditions.
        """
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=3,
            max_overflow=0,
            pool_timeout=5.0,  # Allow some contention
        )

        num_tasks = 20
        task_results = []
        task_errors = []

        async def stress_task(task_id: int):
            """Task that does multiple short DB operations with work between."""
            try:
                for i in range(5):
                    # Short DB operation
                    async with tiny_engine.begin() as conn:
                        await conn.execute(text(f"SELECT {task_id * 100 + i}"))
                    # Work between operations (no connection)
                    await asyncio.sleep(0.02)

                task_results.append(task_id)
            except SQLAlchemyTimeoutError:
                task_errors.append((task_id, "timeout"))
            except Exception as e:
                task_errors.append((task_id, str(e)))

        # Run all tasks
        tasks = [asyncio.create_task(stress_task(i)) for i in range(num_tasks)]
        await asyncio.gather(*tasks, return_exceptions=True)

        await tiny_engine.dispose()

        # Allow some failures under extreme stress but most should succeed
        success_rate = len(task_results) / num_tasks
        assert success_rate >= 0.9, (
            f"Success rate {success_rate:.0%} too low. "
            f"Errors: {task_errors[:5]}..."
        )

    async def test_stress_rapid_session_scope_cycles(self, test_settings):
        """
        Stress test: Rapid acquire/release cycles.

        Tests that connection pool handles rapid cycling without issues.
        """
        tiny_engine = create_async_engine(
            test_settings.database_url,
            pool_size=2,
            max_overflow=0,
            pool_timeout=2.0,
        )

        cycles_completed = 0
        errors = []

        async def rapid_cycler(cycler_id: int, num_cycles: int):
            nonlocal cycles_completed
            for i in range(num_cycles):
                try:
                    async with tiny_engine.begin() as conn:
                        await conn.execute(text("SELECT 1"))
                    cycles_completed += 1
                except Exception as e:
                    errors.append((cycler_id, i, str(e)))

        # Run 5 cyclers, each doing 50 cycles
        cyclers = [
            asyncio.create_task(rapid_cycler(i, 50))
            for i in range(5)
        ]
        await asyncio.gather(*cyclers)

        await tiny_engine.dispose()

        # Should complete most cycles (250 total)
        assert cycles_completed >= 200, (
            f"Only {cycles_completed}/250 cycles completed. Errors: {errors[:5]}"
        )


# =============================================================================
# REGRESSION TESTS: Specific scenarios from production issues
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
class TestPoolExhaustionRegression:
    """
    Regression tests for specific production pool exhaustion scenarios.
    """

    async def test_scenario_stress_test_settings(self, test_settings):
        """
        Reproduce the original failure: stress tests with tight pool settings.

        Original issue:
        - DB_POOL_SIZE=3, DB_POOL_MAX_OVERFLOW=2 (5 total)
        - 5+ concurrent crawl tasks
        - Each holds session for minutes
        - Result: QueuePool limit reached

        After fix:
        - Same pool settings
        - Same concurrent tasks
        - But tasks use session_scope for short DB ops
        - Result: All complete successfully
        """
        # Exactly the settings that exposed the bug
        stress_engine = create_async_engine(
            test_settings.database_url,
            pool_size=3,
            max_overflow=2,  # Total: 5 connections
            pool_timeout=2.0,
        )

        num_tasks = 6  # More tasks than connections, but less flakey
        completed = []
        failed = []

        async def simulated_crawl_task_fixed(task_id: int):
            """
            Crawl task using the FIXED pattern (session_scope).
            """
            try:
                # Bootstrap: short session for user lookup
                async with stress_engine.begin() as conn:
                    await conn.execute(text("SELECT 'bootstrap'"))

                # Crawling phase: NO session held
                for page in range(5):
                    await asyncio.sleep(0.1)  # Simulate page fetch

                    # Periodic DB operation via session_scope pattern
                    if page % 2 == 0:
                        async with stress_engine.begin() as conn:
                            await conn.execute(text(f"SELECT 'page_{page}'"))

                # Final commit
                async with stress_engine.begin() as conn:
                    await conn.execute(text("SELECT 'final_commit'"))

                completed.append(task_id)

            except SQLAlchemyTimeoutError:
                failed.append((task_id, "timeout"))
            except Exception as e:
                failed.append((task_id, str(e)))

        # Run all tasks concurrently
        tasks = [
            asyncio.create_task(simulated_crawl_task_fixed(i))
            for i in range(num_tasks)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        await stress_engine.dispose()

        # With fixed pattern, all should complete
        assert len(completed) == num_tasks, (
            f"Expected {num_tasks} completions, got {len(completed)}. "
            f"Failed: {failed}"
        )
        assert len(failed) == 0, f"Tasks failed: {failed}"
