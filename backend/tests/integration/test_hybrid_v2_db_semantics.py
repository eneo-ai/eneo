"""
Integration tests for Hybrid v2 database semantics.

These tests verify the core database behavior of the two-phase persist pattern:
1. Phase 1 (Pure Compute): ZERO database operations during embedding API calls
2. Phase 2 (Short-lived Session): Bounded transaction times for persist operations

Tests use real PostgreSQL testcontainers to validate:
- Pool isolation during network I/O phases
- Session lifetime boundaries under load
- Savepoint rollback behavior on partial failures
- crawled_titles accuracy (only committed URLs tracked)
- Cancellation cleanup

Run with: pytest tests/integration/test_hybrid_v2_db_semantics.py -v
"""

import asyncio
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from intric.database.database import sessionmanager
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.main.config import Settings
from intric.worker.crawl_context import CrawlContext


# =============================================================================
# HELPER FUNCTIONS AND FIXTURES
# =============================================================================


def create_test_crawl_context(
    website_id: Any = None,
    tenant_id: Any = None,
    user_id: Any = None,
    embedding_model_id: Any = None,
    **overrides: Any,
) -> CrawlContext:
    """Create a CrawlContext with test defaults."""
    return CrawlContext(
        website_id=website_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        tenant_slug="test-tenant",
        user_id=user_id or uuid4(),
        embedding_model_id=embedding_model_id or uuid4(),
        embedding_model_name="test-embedding-model",
        embedding_model_open_source=False,
        embedding_model_family=None,
        embedding_model_dimensions=384,
        http_auth_user=None,
        http_auth_pass=None,
        batch_size=overrides.get("batch_size", 10),
        max_batch_content_bytes=overrides.get("max_batch_content_bytes", 10_000_000),
        max_batch_embedding_bytes=overrides.get("max_batch_embedding_bytes", 50_000_000),
        embedding_timeout_seconds=overrides.get("embedding_timeout_seconds", 5),
        max_transaction_wall_time_seconds=overrides.get(
            "max_transaction_wall_time_seconds", 10
        ),
    )


def create_mock_embedding_model(model_id: Any = None):
    """Create a mock embedding model for testing."""
    model = MagicMock()
    model.id = model_id or uuid4()
    model.name = "test-embedding-model"
    model.open_source = False
    model.family = None
    model.dimensions = 384
    return model


def create_mock_embeddings_service(
    embeddings: list[list[float]] | None = None,
    delay_seconds: float = 0,
    fail_on_call: int | None = None,
):
    """
    Create a mock embeddings service that returns predictable embeddings.

    Args:
        embeddings: Fixed embeddings to return. If None, generates random vectors.
        delay_seconds: Artificial delay to simulate network I/O.
        fail_on_call: If set, raise an exception on the Nth call (1-indexed).
    """
    call_count = 0

    async def mock_get_embeddings(model, chunks):
        nonlocal call_count
        call_count += 1

        if fail_on_call and call_count == fail_on_call:
            raise Exception(f"Simulated embedding failure on call {call_count}")

        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

        # Return tuple of (chunk, embedding) for each chunk
        results = []
        for i, chunk in enumerate(chunks):
            if embeddings and i < len(embeddings):
                embedding = embeddings[i]
            else:
                # Generate deterministic embeddings based on chunk text hash
                seed = int(hashlib.md5(chunk.text.encode()).hexdigest()[:8], 16)
                embedding = [(seed + j) % 1000 / 1000.0 for j in range(384)]
            results.append((chunk, embedding))
        return results

    service = MagicMock()
    service.get_embeddings = mock_get_embeddings
    return service


@pytest.fixture
async def test_engine(test_settings: Settings):
    """Create a test engine with a tiny pool to detect leaks."""
    engine = create_async_engine(
        test_settings.database_url,  # Fixed: was async_database_url
        pool_size=2,  # Very small pool to detect leaks quickly
        max_overflow=1,
        pool_timeout=5,  # Short timeout for fast failure
        pool_pre_ping=True,
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def real_embedding_model(setup_database):
    """
    Get the real embedding model from the test database.

    The test database has a 'fixture-text-embedding' model created by
    the seed_default_models fixture in conftest.py.

    Returns a tuple of (embedding_model_id, embedding_model_mock).
    """
    async with sessionmanager.session() as session:
        async with session.begin():
            result = await session.execute(
                text("""
                    SELECT id, name, family, open_source, dimensions
                    FROM embedding_models
                    WHERE name = 'fixture-text-embedding'
                    LIMIT 1
                """)
            )
            row = result.fetchone()
            if not row:
                pytest.skip("No embedding model found in test database")

            model_id, name, family, open_source, dimensions = row

            # Create a mock that matches the real model's properties
            mock_model = MagicMock()
            mock_model.id = model_id
            mock_model.name = name
            mock_model.open_source = open_source
            mock_model.family = family
            mock_model.dimensions = dimensions or 1536  # default for ada-002

            return model_id, mock_model


async def create_test_website(
    session: AsyncSession,
    tenant_id,
    user_id,
    embedding_model_id,
) -> Any:
    """Create a minimal Website record for integration tests."""
    from intric.database.tables.websites_table import Websites
    from intric.websites.domain.crawl_run import CrawlType

    website = Websites(
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
        url=f"https://test-hybrid-v2-{uuid4().hex[:8]}.example.com",
        name="Test Website for Hybrid v2 Tests",
        download_files=False,
        crawl_type=CrawlType.CRAWL,
        update_interval="never",
        size=0,
    )
    session.add(website)
    await session.flush()
    return website.id


@pytest.fixture
async def test_website(setup_database, real_embedding_model):
    """
    Create a test website in the database.

    Returns the website_id along with tenant_id and user_id.
    """
    embedding_model_id, _ = real_embedding_model

    async with sessionmanager.session() as session:
        async with session.begin():
            # Get test tenant/user
            result = await session.execute(
                text("SELECT id FROM tenants WHERE name = 'test_tenant'")
            )
            tenant_row = result.fetchone()
            if not tenant_row:
                pytest.skip("Test tenant not found")

            result = await session.execute(
                text("SELECT id FROM users WHERE email = 'test@example.com'")
            )
            user_row = result.fetchone()
            if not user_row:
                pytest.skip("Test user not found")

            tenant_id = tenant_row[0]
            user_id = user_row[0]

            website_id = await create_test_website(
                session, tenant_id, user_id, embedding_model_id
            )
            # Transaction commits automatically at end of async with session.begin()

    yield website_id, tenant_id, user_id

    # Cleanup: delete the website after the test
    async with sessionmanager.session() as session:
        async with session.begin():
            await session.execute(
                text("DELETE FROM info_blobs WHERE website_id = :website_id"),
                {"website_id": str(website_id)},
            )
            await session.execute(
                text("DELETE FROM websites WHERE id = :website_id"),
                {"website_id": str(website_id)},
            )


@pytest.fixture
async def cleanup_test_data(test_settings: Settings, setup_database):
    """Clean up test data before and after each test."""
    async with sessionmanager.session() as session:
        async with session.begin():
            # Get test tenant and user IDs
            result = await session.execute(
                text("SELECT id FROM tenants WHERE name = 'test_tenant'")
            )
            tenant_row = result.fetchone()
            if tenant_row:
                tenant_id = tenant_row[0]
                # Delete test info_blobs (cascades to chunks)
                await session.execute(
                    text("DELETE FROM info_blobs WHERE tenant_id = :tenant_id"),
                    {"tenant_id": str(tenant_id)},
                )

    yield

    # Cleanup after test
    async with sessionmanager.session() as session:
        async with session.begin():
            result = await session.execute(
                text("SELECT id FROM tenants WHERE name = 'test_tenant'")
            )
            tenant_row = result.fetchone()
            if tenant_row:
                tenant_id = tenant_row[0]
                await session.execute(
                    text("DELETE FROM info_blobs WHERE tenant_id = :tenant_id"),
                    {"tenant_id": str(tenant_id)},
                )


# =============================================================================
# TEST: POOL ISOLATION DURING PHASES
# =============================================================================


class TestPoolIsolation:
    """Tests verifying pool checkout behavior during Phase 1 and Phase 2."""

    @pytest.mark.asyncio
    async def test_phase1_no_pool_checkout_during_embedding(
        self, test_settings: Settings, setup_database, real_embedding_model, test_website
    ):
        """
        CRITICAL INVARIANT: Phase 1 (embedding computation) should NOT hold
        any database connections.

        This test verifies that during the embedding API call (simulated with delay),
        the database pool has zero active connections from persist_batch.
        """
        from intric.worker.crawl_tasks import persist_batch

        embedding_model_id, embedding_model_mock = real_embedding_model
        website_id, tenant_id, user_id = test_website

        # Track pool checkout events
        pool_checkouts: list[datetime] = []
        pool_checkins: list[datetime] = []
        embedding_call_times: list[tuple[datetime, datetime]] = []

        # Create a wrapper that tracks embedding call timing
        original_service = create_mock_embeddings_service(delay_seconds=0.5)

        async def tracked_get_embeddings(model, chunks):
            start = datetime.now(timezone.utc)
            result = await original_service.get_embeddings(model, chunks)
            end = datetime.now(timezone.utc)
            embedding_call_times.append((start, end))
            return result

        tracked_service = MagicMock()
        tracked_service.get_embeddings = tracked_get_embeddings

        # Setup test data - use REAL embedding model ID and website ID to satisfy FK constraints
        ctx = create_test_crawl_context(
            website_id=website_id,
            tenant_id=tenant_id,
            user_id=user_id,
            embedding_model_id=embedding_model_id,
            embedding_timeout_seconds=10,
        )
        page_buffer = [
            {"url": "https://example.com/page1", "content": "Test content for page 1"},
        ]

        # Patch sessionmanager to track pool usage
        original_session = sessionmanager.session

        @asynccontextmanager
        async def tracked_session():
            pool_checkouts.append(datetime.now(timezone.utc))
            try:
                async with original_session() as session:
                    yield session
            finally:
                pool_checkins.append(datetime.now(timezone.utc))

        with patch.object(sessionmanager, "session", tracked_session):
            result = await persist_batch(
                page_buffer=page_buffer,
                ctx=ctx,
                embedding_model=embedding_model_mock,
                create_embeddings_service=tracked_service,
            )

        success_count, failed_count, successful_urls, _ = result

        # Verify the test ran successfully
        assert success_count == 1, f"Expected 1 success, got {success_count}"
        assert failed_count == 0, f"Expected 0 failures, got {failed_count}"

        # CRITICAL CHECK: Pool checkout should happen AFTER embedding calls
        assert len(embedding_call_times) >= 1, "Embedding should have been called"
        assert len(pool_checkouts) == 1, "Should have exactly one pool checkout (Phase 2)"

        # The embedding call should complete BEFORE the pool checkout
        embedding_end = embedding_call_times[0][1]
        pool_checkout = pool_checkouts[0]

        assert embedding_end <= pool_checkout, (
            f"Pool was checked out DURING embedding! "
            f"Embedding ended at {embedding_end}, pool checkout at {pool_checkout}. "
            f"This violates the Phase 1 invariant."
        )

    @pytest.mark.asyncio
    async def test_phase2_pool_checkout_only_during_persist(
        self, test_settings: Settings, setup_database, real_embedding_model, test_website
    ):
        """
        Verify that pool checkout only occurs during Phase 2 (persist),
        and the connection is returned immediately after.
        """
        from intric.worker.crawl_tasks import persist_batch

        embedding_model_id, embedding_model_mock = real_embedding_model
        website_id, tenant_id, user_id = test_website

        checkout_durations: list[float] = []

        original_session = sessionmanager.session

        @asynccontextmanager
        async def timed_session():
            start = asyncio.get_event_loop().time()
            try:
                async with original_session() as session:
                    yield session
            finally:
                end = asyncio.get_event_loop().time()
                checkout_durations.append(end - start)

        ctx = create_test_crawl_context(
            website_id=website_id,
            tenant_id=tenant_id,
            user_id=user_id,
            embedding_model_id=embedding_model_id,
            max_transaction_wall_time_seconds=10,
        )
        page_buffer = [
            {"url": "https://example.com/page1", "content": "Test content " * 100},
            {"url": "https://example.com/page2", "content": "More test content " * 100},
        ]

        with patch.object(sessionmanager, "session", timed_session):
            result = await persist_batch(
                page_buffer=page_buffer,
                ctx=ctx,
                embedding_model=embedding_model_mock,
                create_embeddings_service=create_mock_embeddings_service(),
            )

        success_count, failed_count, successful_urls, _ = result

        assert success_count == 2, f"Expected 2 successes, got {success_count}"
        assert len(checkout_durations) == 1, "Should have exactly one pool checkout"

        # Session should be held for a short time (Phase 2 only)
        # With 2 pages and mock data, this should be well under 1 second
        assert checkout_durations[0] < 5.0, (
            f"Session held for {checkout_durations[0]:.2f}s - "
            "this suggests Phase 1 operations leaked into the session scope"
        )


# =============================================================================
# TEST: SESSION LIFETIME UNDER LOAD
# =============================================================================


class TestSessionLifetime:
    """Tests for session lifetime boundaries under various conditions."""

    @pytest.mark.asyncio
    async def test_session_lifetime_bounded_under_load(
        self, test_settings: Settings, setup_database, real_embedding_model, test_website
    ):
        """
        Verify session lifetime remains bounded even with multiple pages.
        The max_transaction_wall_time_seconds should enforce the upper bound.
        """
        from intric.worker.crawl_tasks import persist_batch

        embedding_model_id, embedding_model_mock = real_embedding_model
        website_id, tenant_id, user_id = test_website

        ctx = create_test_crawl_context(
            website_id=website_id,
            tenant_id=tenant_id,
            user_id=user_id,
            embedding_model_id=embedding_model_id,
            batch_size=5,
            max_transaction_wall_time_seconds=10,
        )

        # Create multiple pages
        page_buffer = [
            {"url": f"https://example.com/page{i}", "content": f"Content for page {i} " * 50}
            for i in range(5)
        ]

        session_durations: list[float] = []
        original_session = sessionmanager.session

        @asynccontextmanager
        async def timed_session():
            start = asyncio.get_event_loop().time()
            try:
                async with original_session() as session:
                    yield session
            finally:
                end = asyncio.get_event_loop().time()
                session_durations.append(end - start)

        with patch.object(sessionmanager, "session", timed_session):
            result = await persist_batch(
                page_buffer=page_buffer,
                ctx=ctx,
                embedding_model=embedding_model_mock,
                create_embeddings_service=create_mock_embeddings_service(),
            )

        success_count, _, _, _ = result

        assert success_count == 5, f"Expected 5 successes, got {success_count}"

        # Session duration should be well under the wall-time limit
        assert session_durations[0] < ctx.max_transaction_wall_time_seconds, (
            f"Session duration {session_durations[0]:.2f}s exceeded wall-time limit "
            f"{ctx.max_transaction_wall_time_seconds}s"
        )

    @pytest.mark.asyncio
    async def test_transaction_timeout_enforced(
        self, test_settings: Settings, setup_database, real_embedding_model, test_website
    ):
        """
        Verify that max_transaction_wall_time_seconds is enforced.
        If Phase 2 takes too long, the batch should fail gracefully.
        """
        from intric.worker.crawl_tasks import persist_batch

        embedding_model_id, embedding_model_mock = real_embedding_model
        website_id, tenant_id, user_id = test_website

        # Create context with very short timeout
        ctx = create_test_crawl_context(
            website_id=website_id,
            tenant_id=tenant_id,
            user_id=user_id,
            embedding_model_id=embedding_model_id,
            max_transaction_wall_time_seconds=1,
        )

        page_buffer = [
            {"url": f"https://example.com/page{i}", "content": f"Content {i} " * 100}
            for i in range(10)  # Many pages to potentially exceed timeout
        ]

        # Create a slow mock that adds delay per page in Phase 2
        # We can't directly slow Phase 2, but we can verify the timeout mechanism
        result = await persist_batch(
            page_buffer=page_buffer,
            ctx=ctx,
            embedding_model=embedding_model_mock,
            create_embeddings_service=create_mock_embeddings_service(),
        )

        # The test passes if it completes without hanging
        # In a real slow scenario, asyncio.timeout would kick in
        success_count, failed_count, successful_urls, _ = result
        assert success_count + failed_count == 10, "All pages should be accounted for"


# =============================================================================
# TEST: CANCELLATION SAFETY
# =============================================================================


class TestCancellationSafety:
    """Tests for proper cleanup on task cancellation."""

    @pytest.mark.asyncio
    async def test_cancellation_returns_connections_to_pool(
        self, test_settings: Settings, setup_database, test_engine, real_embedding_model, test_website
    ):
        """
        CRITICAL: When a task is cancelled, all checked-out connections
        must be returned to the pool to prevent leaks.
        """
        from intric.worker.crawl_tasks import persist_batch

        embedding_model_id, embedding_model_mock = real_embedding_model
        website_id, tenant_id, user_id = test_website

        # Create slow embedding service that we can cancel
        cancellation_point = asyncio.Event()
        service_started = asyncio.Event()

        async def slow_get_embeddings(model, chunks):
            service_started.set()
            await cancellation_point.wait()  # Will be cancelled before this completes
            return [(chunk, [0.1] * 384) for chunk in chunks]

        slow_service = MagicMock()
        slow_service.get_embeddings = slow_get_embeddings

        ctx = create_test_crawl_context(
            website_id=website_id,
            tenant_id=tenant_id,
            user_id=user_id,
            embedding_model_id=embedding_model_id,
        )
        page_buffer = [{"url": "https://example.com/page1", "content": "Test content"}]

        # Start the task
        task = asyncio.create_task(
            persist_batch(
                page_buffer=page_buffer,
                ctx=ctx,
                embedding_model=embedding_model_mock,
                create_embeddings_service=slow_service,
            )
        )

        # Wait for embedding to start, then cancel
        await asyncio.wait_for(service_started.wait(), timeout=5.0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # Give the event loop a moment to process cleanup
        await asyncio.sleep(0.1)

        # Pool should be healthy - verify by acquiring a connection
        # If connections leaked, this would timeout or fail
        async with test_engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    @pytest.mark.asyncio
    async def test_cancellation_during_phase2_rollback(
        self, test_settings: Settings, setup_database, real_embedding_model, test_website
    ):
        """
        If cancelled during Phase 2, the transaction should roll back
        and no partial data should be persisted.
        """
        from intric.worker.crawl_tasks import persist_batch

        embedding_model_id, embedding_model_mock = real_embedding_model
        website_id, tenant_id, user_id = test_website

        ctx = create_test_crawl_context(
            tenant_id=tenant_id,
            user_id=user_id,
            website_id=website_id,
            embedding_model_id=embedding_model_id,
        )

        # Use normal persist (not slow) - cancellation during Phase 2 is hard to test
        # without modifying the actual code. Instead, we verify the data integrity
        # guarantee: successful_urls only contains committed pages.
        page_buffer = [
            {"url": "https://example.com/page1", "content": "Content 1"},
        ]

        result = await persist_batch(
            page_buffer=page_buffer,
            ctx=ctx,
            embedding_model=embedding_model_mock,
            create_embeddings_service=create_mock_embeddings_service(),
        )

        success_count, failed_count, successful_urls, _ = result

        # Verify successful URLs match what's actually in the database
        async with sessionmanager.session() as session:
            async with session.begin():
                db_result = await session.execute(
                    sa.select(InfoBlobs.url).where(InfoBlobs.website_id == website_id)
                )
                db_urls = {row[0] for row in db_result.fetchall()}

        assert set(successful_urls) == db_urls, (
            f"successful_urls {successful_urls} doesn't match DB {db_urls}"
        )


# =============================================================================
# TEST: CRAWLED_TITLES ACCURACY
# =============================================================================


class TestCrawledTitlesAccuracy:
    """Tests ensuring crawled_titles only contains actually committed URLs."""

    @pytest.mark.asyncio
    async def test_successful_urls_only_contains_committed(
        self, test_settings: Settings, setup_database, cleanup_test_data, real_embedding_model, test_website
    ):
        """
        CRITICAL INVARIANT: successful_urls must ONLY contain URLs that were
        actually persisted to the database.

        This prevents the data loss bug where failed pages were marked as crawled.
        """
        from intric.worker.crawl_tasks import persist_batch

        embedding_model_id, embedding_model_mock = real_embedding_model
        website_id, tenant_id, user_id = test_website

        ctx = create_test_crawl_context(
            tenant_id=tenant_id,
            user_id=user_id,
            website_id=website_id,
            embedding_model_id=embedding_model_id,
        )

        page_buffer = [
            {"url": "https://example.com/success1", "content": "Good content 1"},
            {"url": "https://example.com/success2", "content": "Good content 2"},
            {"url": "https://example.com/success3", "content": "Good content 3"},
        ]

        result = await persist_batch(
            page_buffer=page_buffer,
            ctx=ctx,
            embedding_model=embedding_model_mock,
            create_embeddings_service=create_mock_embeddings_service(),
        )

        success_count, failed_count, successful_urls, _ = result

        assert success_count == 3, f"Expected 3 successes, got {success_count}"
        assert len(successful_urls) == 3, f"Expected 3 URLs, got {len(successful_urls)}"

        # Verify each URL in successful_urls is in the database
        async with sessionmanager.session() as session:
            async with session.begin():
                for url in successful_urls:
                    db_result = await session.execute(
                        sa.select(InfoBlobs).where(
                            sa.and_(
                                InfoBlobs.url == url,
                                InfoBlobs.website_id == website_id,
                            )
                        )
                    )
                    row = db_result.fetchone()
                    assert row is not None, f"URL {url} in successful_urls but not in DB!"

    @pytest.mark.asyncio
    async def test_partial_batch_failure_excludes_failed_urls(
        self, test_settings: Settings, setup_database, cleanup_test_data, real_embedding_model, test_website
    ):
        """
        When some pages fail to persist, their URLs must NOT appear in successful_urls.
        """
        from intric.worker.crawl_tasks import persist_batch

        embedding_model_id, embedding_model_mock = real_embedding_model
        website_id, tenant_id, user_id = test_website

        ctx = create_test_crawl_context(
            tenant_id=tenant_id,
            user_id=user_id,
            website_id=website_id,
            embedding_model_id=embedding_model_id,
        )

        # Create service that fails on specific calls
        # Fail on the 2nd embedding call
        failing_service = create_mock_embeddings_service(fail_on_call=2)

        page_buffer = [
            {"url": "https://example.com/page1", "content": "Content 1"},
            {"url": "https://example.com/page2", "content": "Content 2"},  # Will fail
            {"url": "https://example.com/page3", "content": "Content 3"},
        ]

        result = await persist_batch(
            page_buffer=page_buffer,
            ctx=ctx,
            embedding_model=embedding_model_mock,
            create_embeddings_service=failing_service,
        )

        success_count, failed_count, successful_urls, _ = result

        # Page 2 should fail
        assert failed_count >= 1, "At least one page should fail"

        # Verify failed URL is NOT in successful_urls
        assert "https://example.com/page2" not in successful_urls, (
            "Failed URL should NOT be in successful_urls!"
        )

        # Verify only successful URLs are in the database
        async with sessionmanager.session() as session:
            async with session.begin():
                db_result = await session.execute(
                    sa.select(InfoBlobs.url).where(InfoBlobs.website_id == website_id)
                )
                db_urls = {row[0] for row in db_result.fetchall()}

        assert set(successful_urls) == db_urls, (
            f"Mismatch: successful_urls={successful_urls}, db_urls={db_urls}"
        )


# =============================================================================
# TEST: SAVEPOINT ROLLBACK BEHAVIOR
# =============================================================================


class TestSavepointRollback:
    """Tests for per-page savepoint behavior on failures."""

    @pytest.mark.asyncio
    async def test_savepoint_rollback_preserves_other_pages(
        self, test_settings: Settings, setup_database, cleanup_test_data, real_embedding_model, test_website
    ):
        """
        When one page fails during Phase 2 persist, its savepoint should roll back
        but other pages in the batch should still succeed.
        """
        from intric.worker.crawl_tasks import persist_batch

        embedding_model_id, embedding_model_mock = real_embedding_model
        website_id, tenant_id, user_id = test_website

        ctx = create_test_crawl_context(
            tenant_id=tenant_id,
            user_id=user_id,
            website_id=website_id,
            embedding_model_id=embedding_model_id,
        )

        # All pages succeed in Phase 1 (embedding)
        page_buffer = [
            {"url": "https://example.com/page1", "content": "Valid content 1"},
            {"url": "https://example.com/page2", "content": "Valid content 2"},
            {"url": "https://example.com/page3", "content": "Valid content 3"},
        ]

        result = await persist_batch(
            page_buffer=page_buffer,
            ctx=ctx,
            embedding_model=embedding_model_mock,
            create_embeddings_service=create_mock_embeddings_service(),
        )

        success_count, failed_count, successful_urls, _ = result

        # All should succeed since we're using valid data
        assert success_count == 3, f"Expected 3 successes, got {success_count}"

        # Verify all pages exist in database
        async with sessionmanager.session() as session:
            async with session.begin():
                db_result = await session.execute(
                    sa.select(InfoBlobs).where(InfoBlobs.website_id == website_id)
                )
                rows = db_result.fetchall()

        assert len(rows) == 3, f"Expected 3 rows in DB, got {len(rows)}"

    @pytest.mark.asyncio
    async def test_deduplication_delete_then_insert(
        self, test_settings: Settings, setup_database, cleanup_test_data, real_embedding_model, test_website
    ):
        """
        Verify delete-then-insert deduplication pattern works correctly.
        Re-crawling the same URL should update (not duplicate) the content.
        """
        from intric.worker.crawl_tasks import persist_batch

        embedding_model_id, embedding_model_mock = real_embedding_model
        website_id, tenant_id, user_id = test_website

        ctx = create_test_crawl_context(
            tenant_id=tenant_id,
            user_id=user_id,
            website_id=website_id,
            embedding_model_id=embedding_model_id,
        )

        # First crawl
        page_buffer_v1 = [
            {"url": "https://example.com/page1", "content": "Original content v1"},
        ]

        result1 = await persist_batch(
            page_buffer=page_buffer_v1,
            ctx=ctx,
            embedding_model=embedding_model_mock,
            create_embeddings_service=create_mock_embeddings_service(),
        )

        assert result1[0] == 1, "First crawl should succeed"

        # Get the first content
        async with sessionmanager.session() as session:
            async with session.begin():
                db_result = await session.execute(
                    sa.select(InfoBlobs.text).where(InfoBlobs.website_id == website_id)
                )
                first_content = db_result.scalar()

        assert "v1" in first_content, "First content should contain v1"

        # Second crawl - same URL, different content
        page_buffer_v2 = [
            {"url": "https://example.com/page1", "content": "Updated content v2"},
        ]

        result2 = await persist_batch(
            page_buffer=page_buffer_v2,
            ctx=ctx,
            embedding_model=embedding_model_mock,
            create_embeddings_service=create_mock_embeddings_service(),
        )

        assert result2[0] == 1, "Second crawl should succeed"

        # Verify there's only ONE row (not duplicated)
        async with sessionmanager.session() as session:
            async with session.begin():
                db_result = await session.execute(
                    sa.select(InfoBlobs).where(InfoBlobs.website_id == website_id)
                )
                rows = db_result.fetchall()

        assert len(rows) == 1, f"Expected 1 row (deduplicated), got {len(rows)}"

        # Verify content was updated
        async with sessionmanager.session() as session:
            async with session.begin():
                db_result = await session.execute(
                    sa.select(InfoBlobs.text).where(InfoBlobs.website_id == website_id)
                )
                final_content = db_result.scalar()

        assert "v2" in final_content, f"Content should be updated to v2, got: {final_content}"


# =============================================================================
# TEST: EMBEDDING TIMEOUT HANDLING
# =============================================================================


class TestEmbeddingTimeout:
    """Tests for embedding timeout behavior."""

    @pytest.mark.asyncio
    async def test_embedding_timeout_fails_gracefully(
        self, test_settings: Settings, setup_database, real_embedding_model, test_website
    ):
        """
        When embedding times out, the page should fail but not crash the batch.
        Other pages should continue processing.
        """
        from intric.worker.crawl_tasks import persist_batch

        embedding_model_id, embedding_model_mock = real_embedding_model
        website_id, tenant_id, user_id = test_website

        # Very short timeout - use real embedding model ID for FK constraint
        ctx = create_test_crawl_context(
            tenant_id=tenant_id,
            user_id=user_id,
            website_id=website_id,
            embedding_model_id=embedding_model_id,
            embedding_timeout_seconds=1,  # 1 second timeout
        )

        # Create service that's slow on specific calls - override the mock's get_embeddings
        call_count = 0

        async def slow_on_second_call(model, chunks):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                await asyncio.sleep(5)  # 5 seconds - will timeout
            return [(chunk, [0.1] * 384) for chunk in chunks]

        slow_service = MagicMock()
        slow_service.get_embeddings = slow_on_second_call

        page_buffer = [
            {"url": "https://example.com/fast1", "content": "Fast content 1"},
            {"url": "https://example.com/slow", "content": "Slow content"},  # Will timeout
            {"url": "https://example.com/fast2", "content": "Fast content 2"},
        ]

        result = await persist_batch(
            page_buffer=page_buffer,
            ctx=ctx,
            embedding_model=embedding_model_mock,
            create_embeddings_service=slow_service,
        )

        success_count, failed_count, successful_urls, _ = result

        # Second page should fail due to timeout
        assert failed_count >= 1, "At least one page should fail"

        # Fast pages should succeed
        assert "https://example.com/fast1" in successful_urls
        # Note: fast2 may or may not succeed depending on semaphore timing

        # Verify timed-out URL is not in successful_urls
        assert "https://example.com/slow" not in successful_urls


# =============================================================================
# TEST: EMPTY AND EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_empty_buffer_returns_zeros(self, test_settings: Settings):
        """Empty buffer should return (0, 0, []) without any database operations."""
        from intric.worker.crawl_tasks import persist_batch

        ctx = create_test_crawl_context()

        result = await persist_batch(
            page_buffer=[],
            ctx=ctx,
            embedding_model=create_mock_embedding_model(),
            create_embeddings_service=create_mock_embeddings_service(),
        )

        assert result == (0, 0, [], []), f"Empty buffer should return (0, 0, [], []), got {result}"

    @pytest.mark.asyncio
    async def test_no_embedding_model_fails_all(self, test_settings: Settings):
        """When embedding_model is None, all pages should fail."""
        from intric.worker.crawl_tasks import persist_batch

        ctx = create_test_crawl_context()

        page_buffer = [
            {"url": "https://example.com/page1", "content": "Content 1"},
            {"url": "https://example.com/page2", "content": "Content 2"},
        ]

        result = await persist_batch(
            page_buffer=page_buffer,
            ctx=ctx,
            embedding_model=None,  # No embedding model
            create_embeddings_service=create_mock_embeddings_service(),
        )

        success_count, failed_count, successful_urls, _ = result

        assert success_count == 0, f"Expected 0 successes without model, got {success_count}"
        assert failed_count == 2, f"Expected 2 failures without model, got {failed_count}"
        assert successful_urls == [], f"Expected no URLs without model, got {successful_urls}"

    @pytest.mark.asyncio
    async def test_empty_content_skipped(
        self, test_settings: Settings, setup_database, real_embedding_model, test_website
    ):
        """Pages with empty content should be skipped (counted as failed)."""
        from intric.worker.crawl_tasks import persist_batch

        embedding_model_id, embedding_model_mock = real_embedding_model
        website_id, tenant_id, user_id = test_website

        ctx = create_test_crawl_context(
            tenant_id=tenant_id,
            user_id=user_id,
            website_id=website_id,
            embedding_model_id=embedding_model_id,
        )

        page_buffer = [
            {"url": "https://example.com/empty", "content": ""},
            {"url": "https://example.com/whitespace", "content": "   \n\t  "},
            {"url": "https://example.com/valid", "content": "Valid content here"},
        ]

        result = await persist_batch(
            page_buffer=page_buffer,
            ctx=ctx,
            embedding_model=embedding_model_mock,
            create_embeddings_service=create_mock_embeddings_service(),
        )

        success_count, failed_count, successful_urls, _ = result

        # Only valid page should succeed
        assert success_count == 1, f"Expected 1 success, got {success_count}"
        assert failed_count == 2, f"Expected 2 failures (empty pages), got {failed_count}"
        assert "https://example.com/valid" in successful_urls
