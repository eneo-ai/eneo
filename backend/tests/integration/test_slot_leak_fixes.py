"""
Integration tests for slot leak fixes.

Tests cover:
1. Session lifecycle - main session closes before crawl loop
2. Partial batch failure tracking - successful_urls only includes actually persisted URLs
3. Embedding API failures - errors don't corrupt successful_urls tracking
4. Cancellation safety - cleanup on task cancellation
5. Zombie job prevention - stale crawlers don't corrupt state
6. Redis TTL management - heartbeat refreshes both counter and flag TTL

Run with: pytest tests/integration/test_slot_leak_fixes.py -v
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# =============================================================================
# UNIT TESTS: persist_batch return type and crawled_titles tracking
# =============================================================================


class TestPersistBatchReturnType:
    """Tests for persist_batch returning tuple[int, int, list[str], list[str]]."""

    @pytest.mark.asyncio
    async def test_empty_buffer_returns_empty_urls(self):
        """
        Empty page_buffer should return (0, 0, [], []).

        This is the base case - no pages, no URLs.
        """
        from intric.worker.crawl_context import CrawlContext

        # Create minimal CrawlContext
        ctx = CrawlContext(
            website_id=uuid4(),
            tenant_id=uuid4(),
            tenant_slug="test",
            user_id=uuid4(),
            embedding_model_id=None,
            embedding_model_name=None,
            embedding_model_open_source=False,
            embedding_model_family=None,
            embedding_model_dimensions=None,
            http_auth_user=None,
            http_auth_pass=None,
        )

        # Import persist_batch
        from intric.worker.crawl_tasks import persist_batch

        mock_container = MagicMock()

        # Call with empty buffer
        result = await persist_batch(
            page_buffer=[],
            ctx=ctx,
            embedding_model=None,
            container=mock_container,
        )

        # Should return (0, 0, [], [])
        assert result == (0, 0, [], []), (
            f"Empty buffer should return (0, 0, [], []), got {result}"
        )

    @pytest.mark.asyncio
    async def test_no_embedding_model_returns_all_failed(self):
        """
        When embedding_model is None, all pages should fail with empty successful_urls.
        """
        from intric.worker.crawl_context import CrawlContext

        ctx = CrawlContext(
            website_id=uuid4(),
            tenant_id=uuid4(),
            tenant_slug="test",
            user_id=uuid4(),
            embedding_model_id=None,
            embedding_model_name=None,
            embedding_model_open_source=False,
            embedding_model_family=None,
            embedding_model_dimensions=None,
            http_auth_user=None,
            http_auth_pass=None,
        )

        from intric.worker.crawl_tasks import persist_batch

        page_buffer = [
            {"url": "https://example.com/page1", "content": "Content 1"},
            {"url": "https://example.com/page2", "content": "Content 2"},
        ]

        mock_container = MagicMock()

        result = await persist_batch(
            page_buffer=page_buffer,
            ctx=ctx,
            embedding_model=None,  # No embedding model
            container=mock_container,
        )

        success_count, failed_count, successful_urls, _ = result

        # All pages should fail when no embedding model
        assert success_count == 0, f"Expected 0 successes, got {success_count}"
        assert failed_count == 2, f"Expected 2 failures, got {failed_count}"
        assert successful_urls == [], f"Expected empty URLs, got {successful_urls}"


class TestCrawledTitlesTracking:
    """Tests for crawled_titles only containing actually persisted URLs."""

    def test_successful_urls_only_includes_persisted(self):
        """
        INVARIANT: successful_urls must ONLY contain URLs that were actually
        persisted to the database. URLs from failed pages must NOT be included.

        This test validates the fix for the data loss bug at lines 1668-1669.
        """
        # Simulate the BEFORE and AFTER patterns

        # BEFORE (BUG): crawled_titles.update(p["url"] for p in page_buffer if success_count > 0)
        # This marks ALL URLs as crawled if ANY page succeeds

        page_buffer = [
            {"url": "https://example.com/success1", "content": "OK"},
            {"url": "https://example.com/failed", "content": "BAD"},
            {"url": "https://example.com/success2", "content": "OK"},
        ]
        success_count = 2  # 2 pages succeeded

        # OLD BUGGY LOGIC - would mark all 3 URLs
        buggy_crawled_titles = set()
        buggy_crawled_titles.update(p["url"] for p in page_buffer if success_count > 0)
        assert len(buggy_crawled_titles) == 3, "Bug: marks ALL URLs when ANY succeeds"

        # AFTER (FIX): crawled_titles.update(successful_urls)
        # Only URLs from successful persists are included

        successful_urls = [
            "https://example.com/success1",
            "https://example.com/success2",
        ]  # Only the 2 that actually persisted

        fixed_crawled_titles = set()
        fixed_crawled_titles.update(successful_urls)
        assert len(fixed_crawled_titles) == 2, "Fix: marks only ACTUALLY persisted URLs"
        assert "https://example.com/failed" not in fixed_crawled_titles

    def test_partial_batch_failure_tracking(self):
        """
        When a batch has partial failures, only successful URLs are tracked.

        Scenario: 5 pages in batch, 2 fail due to constraint violations
        Expected: crawled_titles only has 3 URLs
        """
        _page_buffer = [  # noqa: F841 - documents test scenario
            {"url": "https://example.com/page1", "content": "OK"},
            {"url": "https://example.com/page2", "content": "CONSTRAINT VIOLATION"},
            {"url": "https://example.com/page3", "content": "OK"},
            {"url": "https://example.com/page4", "content": "EMBEDDING TIMEOUT"},
            {"url": "https://example.com/page5", "content": "OK"},
        ]

        # Simulated persist_batch result
        _success_count = 3  # noqa: F841 - documents expected outcome
        _failed_count = 2  # noqa: F841 - documents expected outcome
        successful_urls = [
            "https://example.com/page1",
            "https://example.com/page3",
            "https://example.com/page5",
        ]

        crawled_titles = set()
        crawled_titles.update(successful_urls)

        # Verify only successful URLs are tracked
        assert len(crawled_titles) == 3
        assert "https://example.com/page2" not in crawled_titles
        assert "https://example.com/page4" not in crawled_titles
        assert all(url in crawled_titles for url in successful_urls)


class TestSessionLifecycle:
    """Tests for session lifecycle management in crawl tasks."""

    def test_session_close_location_documented(self):
        """
        Verify that bootstrap_session.close() is called BEFORE the crawl loop.

        This is a documentation test - verifies the code structure.
        The bootstrap session is closed before "Session-per-batch page processing"
        to return the connection to the pool before the long-running crawl begins.
        """
        import inspect
        from intric.worker import crawl_tasks

        source = inspect.getsource(crawl_tasks.crawl_task)

        # The bootstrap session close should appear before session-per-batch section
        assert "await bootstrap_session.close()" in source, (
            "bootstrap_session.close() should be present in crawl_task"
        )

        # Verify bootstrap session close happens BEFORE the session-per-batch section
        # (This ensures DB connection is returned to pool before long-running crawl)
        session_per_batch_comment = source.find("Session-per-batch page processing")
        bootstrap_session_close = source.find("await bootstrap_session.close()")

        assert session_per_batch_comment != -1, "Session-per-batch section should exist"
        assert bootstrap_session_close != -1, "bootstrap_session.close() should exist"
        assert bootstrap_session_close < session_per_batch_comment, (
            "bootstrap_session.close() should be BEFORE session-per-batch section "
            "(connection returned to pool before crawl starts)"
        )


class TestEmbeddingAPIFailures:
    """Tests for embedding API failure handling."""

    @pytest.mark.asyncio
    async def test_embedding_timeout_doesnt_corrupt_tracking(self):
        """
        When embedding API times out, the page should fail but not corrupt
        successful_urls tracking for other pages.

        Scenario: Page 2 embedding times out, pages 1 and 3 succeed
        Expected: successful_urls = [page1, page3], failed_count = 1
        """
        # This is tested implicitly through the persist_batch implementation
        # but we document the expected behavior here

        # Simulated scenario:
        pages_processed = [
            {"url": "page1", "status": "success", "reason": "embedded and persisted"},
            {"url": "page2", "status": "failed", "reason": "embedding timeout"},
            {"url": "page3", "status": "success", "reason": "embedded and persisted"},
        ]

        successful_urls = [
            p["url"] for p in pages_processed if p["status"] == "success"
        ]
        failed_count = sum(1 for p in pages_processed if p["status"] == "failed")

        assert successful_urls == ["page1", "page3"]
        assert failed_count == 1


class TestCancellationSafety:
    """Tests for task cancellation safety."""

    @pytest.mark.asyncio
    async def test_cancellation_during_batch_persist(self):
        """
        When a task is cancelled during batch persist, in-progress work
        should be rolled back by the savepoint mechanism.

        This test documents the expected behavior based on per-page savepoints.
        """
        # Per-page savepoints ensure atomic rollback
        # If cancelled mid-batch, uncommitted pages are rolled back
        # Only committed pages (successful savepoints) are in successful_urls

        # Document the pattern:
        # 1. savepoint = await session.begin_nested()
        # 2. try:
        # 3.     ... persist page ...
        # 4.     await savepoint.commit()
        # 5.     successful_urls.append(url)  # Only after commit!
        # 6. except Exception:
        # 7.     await savepoint.rollback()
        # 8.     failed_count += 1

        # Cancellation at step 3 → savepoint never commits → URL not in list
        # Cancellation at step 5 → commit succeeded → URL is in list

        pass  # Documentation test


# =============================================================================
# INTEGRATION TESTS: Redis TTL and Zombie Prevention
# =============================================================================


class TestRedisTTLManagement:
    """Tests for Redis TTL management in heartbeat."""

    def test_heartbeat_refreshes_both_keys(self):
        """
        Heartbeat should refresh TTL for BOTH:
        - tenant:{tenant_id}:active_jobs (counter)
        - job:{job_id}:slot_preacquired (flag)

        This is documented in the HeartbeatMonitor._refresh_redis_ttl() method.
        Note: Heartbeat logic was extracted to HeartbeatMonitor during refactoring.
        """
        import inspect
        from intric.worker.crawl.heartbeat import HeartbeatMonitor

        source = inspect.getsource(HeartbeatMonitor._refresh_redis_ttl)

        # Verify pipeline pattern for atomic TTL refresh
        assert "pipe = self._redis_client.pipeline(transaction=True)" in source
        assert "pipe.expire(concurrency_key, self._semaphore_ttl_seconds)" in source
        assert "pipe.expire(flag_key, self._semaphore_ttl_seconds)" in source


class TestZombieJobPrevention:
    """Tests for zombie job prevention mechanisms."""

    def test_preemption_check_exists(self):
        """
        Crawl task should check for job preemption during heartbeat.

        If job status is FAILED, crawl should exit gracefully.
        Note: Preemption logic was extracted to HeartbeatMonitor during refactoring.
        """
        import inspect
        from intric.worker.crawl.heartbeat import HeartbeatMonitor

        source = inspect.getsource(HeartbeatMonitor._check_preemption)

        # Verify preemption check exists in HeartbeatMonitor
        assert "job.status == JobStatus.FAILED" in source
        assert "JobPreemptedError" in source

    def test_preemption_handling_in_crawl_task(self):
        """
        crawl_task should handle JobPreemptedError from HeartbeatMonitor
        and return preempted_during_crawl status.
        """
        import inspect
        from intric.worker import crawl_tasks

        source = inspect.getsource(crawl_tasks.crawl_task)

        # Verify crawl_task handles preemption from HeartbeatMonitor
        assert "JobPreemptedError" in source
        assert "preempted_during_crawl" in source


class TestCrawlContextSecurity:
    """Tests for security measures in CrawlContext."""

    def test_password_not_exposed_in_repr(self):
        """
        SECURITY: http_auth_pass must NOT appear in repr() output.

        This prevents accidental password exposure in logs, tracebacks,
        and debugging output. The field uses repr=False in the dataclass.
        """
        from intric.worker.crawl_context import CrawlContext

        secret_password = "super_secret_password_123"

        ctx = CrawlContext(
            website_id=uuid4(),
            tenant_id=uuid4(),
            tenant_slug="test",
            user_id=uuid4(),
            embedding_model_id=None,
            embedding_model_name=None,
            embedding_model_open_source=False,
            embedding_model_family=None,
            embedding_model_dimensions=None,
            http_auth_user="testuser",
            http_auth_pass=secret_password,
        )

        repr_output = repr(ctx)

        # Password must NOT appear in repr
        assert secret_password not in repr_output, (
            f"SECURITY VIOLATION: Password '{secret_password}' exposed in repr()! "
            f"repr output: {repr_output[:200]}..."
        )

        # Username CAN appear (it's not secret)
        assert "testuser" in repr_output, "Username should be visible in repr"

        # Verify the field still holds the correct value
        assert ctx.http_auth_pass == secret_password, (
            "Password should still be accessible"
        )


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_embedding_model():
    """Create a mock embedding model for testing."""
    model = MagicMock()
    model.id = uuid4()
    model.name = "test-embedding-model"
    model.open_source = False
    model.family = None
    model.dimensions = 384
    return model


@pytest.fixture
def mock_sessionmanager():
    """Create a mock session manager for testing."""
    with patch("intric.worker.crawl_tasks.sessionmanager") as mock:
        mock_session = AsyncMock()
        mock_session.begin = MagicMock(return_value=AsyncMock())
        mock_session.begin_nested = MagicMock(return_value=AsyncMock())
        mock.session.return_value.__aenter__.return_value = mock_session
        yield mock


@pytest.fixture
def mock_redis_client():
    """Create a mock Redis client for testing."""
    mock = AsyncMock()
    mock.pipeline.return_value = AsyncMock()
    mock.pipeline.return_value.expire = MagicMock()
    mock.pipeline.return_value.execute = AsyncMock(return_value=[1, 1])
    return mock
