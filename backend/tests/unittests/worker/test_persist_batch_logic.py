"""
Unit tests for persist_batch two-phase logic.

These tests verify RUNTIME BEHAVIOR of the two-phase pattern, NOT source code structure.
Each test validates a specific invariant of the implementation.

Core Invariants Tested:
1. Phase 1 (embedding) completes BEFORE any DB session is opened
2. Embedding semaphore limits concurrent API calls
3. Semaphore is released even when embedding fails with exception
4. Embedding bytes cap triggers early Phase 1 exit
5. Each page gets its own savepoint in Phase 2
6. Delete and insert happen within the same savepoint (atomic)
7. successful_urls contains ONLY URLs that committed successfully

Run with: pytest tests/unittests/worker/test_persist_batch_logic.py -v
"""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.worker.crawl_context import CrawlContext


# =============================================================================
# HELPER: Mock Session Manager
# =============================================================================


class AwaitableContextManager:
    """A mock object that can be both awaited AND used as an async context manager."""

    def __await__(self):
        async def _await():
            return None
        return _await().__await__()

    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        return None


def create_mock_session():
    """
    Create a properly structured mock session for sessionmanager.

    Supports two usage patterns:
    1. async with sessionmanager.session() as session, session.begin(): ...
    2. session = sessionmanager.create_session(); await session.begin(); await session.close()

    Returns:
        MagicMock configured to work with both patterns.
    """
    mock_session = MagicMock()

    # session.begin() needs to support BOTH patterns:
    # Pattern 1: async with session.begin(): ... (returns async context manager)
    # Pattern 2: await session.begin() (returns awaitable)
    # Solution: Return AwaitableContextManager which supports both
    mock_session.begin = MagicMock(side_effect=lambda: AwaitableContextManager())

    # These methods ARE coroutines, so use AsyncMock
    mock_session.execute = AsyncMock()
    mock_session.begin_nested = AsyncMock(return_value=AsyncMock())
    mock_session.close = AsyncMock()

    return mock_session


def create_mock_sessionmanager(mock_session):
    """
    Create a properly structured mock for sessionmanager.

    Supports both patterns:
    1. async with sessionmanager.session() as session, session.begin():
    2. session = sessionmanager.create_session(); await session.begin()

    CRITICAL: We use side_effect with a factory function so that EACH call to
    sessionmanager.session() returns a FRESH async context manager. Using
    return_value would return the same exhausted context manager on every call.

    Args:
        mock_session: A session mock created by create_mock_session(). MUST be
                     a MagicMock, not AsyncMock, for begin() to work correctly.
    """
    mock_sm = MagicMock()

    @asynccontextmanager
    async def mock_session_context():
        yield mock_session

    # Use side_effect with a lambda that creates fresh context managers
    mock_sm.session.side_effect = lambda: mock_session_context()

    # Support for create_session() - returns the session directly (not context manager)
    mock_sm.create_session.return_value = mock_session

    return mock_sm


def create_mock_container(mock_embeddings_service):
    """
    Create a mock container for persist_batch testing.

    The persist_batch function now takes a container instead of a service directly.
    The container needs to support:
    1. session.override(providers.Object(session)) - to set the session
    2. create_embeddings_service() - to return the embedding service

    Args:
        mock_embeddings_service: The mock embedding service to return from container.

    Returns:
        MagicMock configured to work with persist_batch.
    """
    mock_container = MagicMock()

    # session.override() should be callable and do nothing (it's for DI)
    mock_container.session.override = MagicMock()

    # create_embeddings_service() returns the mock service
    mock_container.create_embeddings_service.return_value = mock_embeddings_service

    return mock_container


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def crawl_context():
    """Create a minimal CrawlContext for testing."""
    return CrawlContext(
        website_id=uuid4(),
        tenant_id=uuid4(),
        tenant_slug="test-tenant",
        user_id=uuid4(),
        embedding_model_id=uuid4(),
        embedding_model_name="test-embedding-model",
        embedding_model_open_source=False,
        embedding_model_family=None,
        embedding_model_dimensions=384,
        http_auth_user=None,
        http_auth_pass=None,
        batch_size=50,
        max_batch_content_bytes=10_000_000,
        max_batch_embedding_bytes=50_000_000,
        embedding_timeout_seconds=15,
        max_transaction_wall_time_seconds=30,
    )


@pytest.fixture
def mock_embedding_model():
    """Create a mock embedding model."""
    model = MagicMock()
    model.id = uuid4()
    model.name = "test-embedding-model"
    model.open_source = False
    model.family = None
    model.dimensions = 384
    return model


@pytest.fixture
def mock_embeddings_service():
    """Create a mock CreateEmbeddingsService that returns fake embeddings."""
    service = MagicMock()

    async def mock_get_embeddings(model, chunks):
        # Return list of (chunk, embedding) tuples
        return [(chunk, [0.1, 0.2, 0.3] * 128) for chunk in chunks]

    service.get_embeddings = AsyncMock(side_effect=mock_get_embeddings)
    return service


# =============================================================================
# TEST CLASS: Embedding Semaphore Behavior
# =============================================================================


class TestEmbeddingSemaphoreBehavior:
    """Tests for the module-level embedding semaphore that limits concurrent API calls."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_embedding_calls(
        self, crawl_context, mock_embedding_model
    ):
        """
        INVARIANT: Embedding semaphore must limit concurrent API calls.

        Scenario: 5 pages with semaphore limit of 2
        Expected: At most 2 embedding calls execute concurrently at any time
        """
        concurrent_calls = []
        max_concurrent = 0
        current_concurrent = 0

        async def mock_get_embeddings_with_tracking(model, chunks):
            nonlocal current_concurrent, max_concurrent
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
            concurrent_calls.append(current_concurrent)
            await asyncio.sleep(0.05)  # Simulate API latency
            current_concurrent -= 1
            return [(chunk, [0.1] * 384) for chunk in chunks]

        # Create a service with tracking
        service = MagicMock()
        service.get_embeddings = AsyncMock(side_effect=mock_get_embeddings_with_tracking)

        # Patch the semaphore to have limit of 2
        semaphore = asyncio.Semaphore(2)

        page_buffer = [
            {"url": f"https://example.com/page{i}", "content": f"Content for page {i}"}
            for i in range(5)
        ]

        # Mock session to avoid actual DB operations
        # CRITICAL: Use create_mock_session() NOT AsyncMock() - see helper docstring
        mock_session = create_mock_session()
        mock_sm = create_mock_sessionmanager(mock_session)

        with patch(
            "intric.worker.crawl.persistence._get_embedding_semaphore", return_value=semaphore
        ), patch("intric.database.database.sessionmanager", mock_sm):
            from intric.worker.crawl_tasks import persist_batch

            await persist_batch(
                page_buffer=page_buffer,
                ctx=crawl_context,
                embedding_model=mock_embedding_model,
                container=create_mock_container(service),
            )

        # Verify semaphore limited concurrency
        assert max_concurrent <= 2, (
            f"Semaphore should limit to 2 concurrent calls, but saw {max_concurrent}"
        )

    @pytest.mark.asyncio
    async def test_semaphore_released_on_embedding_exception(
        self, crawl_context, mock_embedding_model
    ):
        """
        INVARIANT: Semaphore must be released even when embedding API throws exception.

        Scenario: Embedding API raises exception for page 2
        Expected: Semaphore is released, subsequent pages can still be processed
        """
        call_count = 0

        async def mock_get_embeddings_with_failure(model, chunks):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Simulated embedding API failure")
            return [(chunk, [0.1] * 384) for chunk in chunks]

        service = MagicMock()
        service.get_embeddings = AsyncMock(side_effect=mock_get_embeddings_with_failure)

        # Use semaphore with limit 1 to ensure sequential execution
        semaphore = asyncio.Semaphore(1)

        page_buffer = [
            {"url": f"https://example.com/page{i}", "content": f"Content for page {i}"}
            for i in range(3)
        ]

        # CRITICAL: Use create_mock_session() NOT AsyncMock() - see helper docstring
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: uuid4()))
        mock_sm = create_mock_sessionmanager(mock_session)

        with patch(
            "intric.worker.crawl.persistence._get_embedding_semaphore", return_value=semaphore
        ), patch("intric.database.database.sessionmanager", mock_sm):
            from intric.worker.crawl_tasks import persist_batch

            success, failed, urls, _ = await persist_batch(
                page_buffer=page_buffer,
                ctx=crawl_context,
                embedding_model=mock_embedding_model,
                container=create_mock_container(service),
            )

        # Verify all pages were attempted (semaphore was released after failure)
        assert call_count == 3, (
            f"All 3 pages should be attempted, but only {call_count} were tried"
        )
        # Page 2 should have failed
        assert failed >= 1, "At least one page should have failed"

    @pytest.mark.asyncio
    async def test_semaphore_released_on_timeout(
        self, crawl_context, mock_embedding_model
    ):
        """
        INVARIANT: Semaphore must be released when embedding times out.

        Scenario: Page 2 embedding takes longer than timeout
        Expected: Timeout occurs, semaphore released, page 3 processes normally
        """
        call_count = 0

        async def mock_get_embeddings_with_slow_page(model, chunks):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                await asyncio.sleep(10)  # Will timeout (ctx timeout is 15s, but we'll patch shorter)
            return [(chunk, [0.1] * 384) for chunk in chunks]

        service = MagicMock()
        service.get_embeddings = AsyncMock(side_effect=mock_get_embeddings_with_slow_page)

        semaphore = asyncio.Semaphore(1)

        # Create context with very short timeout
        short_timeout_ctx = CrawlContext(
            website_id=crawl_context.website_id,
            tenant_id=crawl_context.tenant_id,
            tenant_slug=crawl_context.tenant_slug,
            user_id=crawl_context.user_id,
            embedding_model_id=crawl_context.embedding_model_id,
            embedding_model_name=crawl_context.embedding_model_name,
            embedding_model_open_source=crawl_context.embedding_model_open_source,
            embedding_model_family=crawl_context.embedding_model_family,
            embedding_model_dimensions=crawl_context.embedding_model_dimensions,
            http_auth_user=None,
            http_auth_pass=None,
            embedding_timeout_seconds=1,  # 1 second timeout
            max_transaction_wall_time_seconds=30,
        )

        page_buffer = [
            {"url": f"https://example.com/page{i}", "content": f"Content for page {i}"}
            for i in range(3)
        ]

        # CRITICAL: Use create_mock_session() NOT AsyncMock() - see helper docstring
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: uuid4()))

        mock_sm = create_mock_sessionmanager(mock_session)

        with patch(
            "intric.worker.crawl.persistence._get_embedding_semaphore", return_value=semaphore
        ), patch("intric.database.database.sessionmanager", mock_sm):
            from intric.worker.crawl_tasks import persist_batch

            success, failed, urls, _ = await persist_batch(
                page_buffer=page_buffer,
                ctx=short_timeout_ctx,
                embedding_model=mock_embedding_model,
                container=create_mock_container(service),
            )

        # Page 2 timed out, but page 3 should have been attempted
        assert call_count == 3, (
            f"All 3 pages should be attempted after timeout, got {call_count}"
        )


# =============================================================================
# TEST CLASS: Memory Caps Enforcement
# =============================================================================


class TestMemoryCapsEnforcement:
    """Tests for memory cap enforcement during Phase 1."""

    @pytest.mark.asyncio
    async def test_embedding_bytes_cap_triggers_early_exit(
        self, crawl_context, mock_embedding_model
    ):
        """
        INVARIANT: When embedding bytes exceed max_batch_embedding_bytes,
        Phase 1 should exit early and process only prepared pages.

        Scenario: 10 pages, but embedding cap set very low (1KB)
        Expected: Only first few pages prepared before cap triggers exit
        """
        # Each embedding is ~1536 floats * 4 bytes = 6KB per chunk
        # With multiple chunks per page, cap should trigger quickly

        async def mock_get_embeddings(model, chunks):
            # Return large embeddings to trigger cap quickly
            return [(chunk, [0.1] * 1536) for chunk in chunks]

        service = MagicMock()
        service.get_embeddings = AsyncMock(side_effect=mock_get_embeddings)

        # Create context with very small embedding cap
        small_cap_ctx = CrawlContext(
            website_id=crawl_context.website_id,
            tenant_id=crawl_context.tenant_id,
            tenant_slug=crawl_context.tenant_slug,
            user_id=crawl_context.user_id,
            embedding_model_id=crawl_context.embedding_model_id,
            embedding_model_name=crawl_context.embedding_model_name,
            embedding_model_open_source=crawl_context.embedding_model_open_source,
            embedding_model_family=crawl_context.embedding_model_family,
            embedding_model_dimensions=1536,
            http_auth_user=None,
            http_auth_pass=None,
            max_batch_embedding_bytes=10000,  # 10KB cap - will trigger after ~1-2 pages
            embedding_timeout_seconds=15,
            max_transaction_wall_time_seconds=30,
        )

        # Create 10 pages with substantial content
        page_buffer = [
            {
                "url": f"https://example.com/page{i}",
                "content": f"Content for page {i}. " * 100,  # ~2KB content per page
            }
            for i in range(10)
        ]

        pages_embedded = 0

        original_mock = service.get_embeddings

        async def counting_mock(model, chunks):
            nonlocal pages_embedded
            pages_embedded += 1
            return await original_mock(model, chunks)

        service.get_embeddings = AsyncMock(side_effect=counting_mock)

        # CRITICAL: Use create_mock_session() NOT AsyncMock() - see helper docstring
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: uuid4()))

        mock_sm = create_mock_sessionmanager(mock_session)

        with patch(
            "intric.worker.crawl.persistence._get_embedding_semaphore",
            return_value=asyncio.Semaphore(10),
        ), patch("intric.database.database.sessionmanager", mock_sm):
            from intric.worker.crawl_tasks import persist_batch

            await persist_batch(
                page_buffer=page_buffer,
                ctx=small_cap_ctx,
                embedding_model=mock_embedding_model,
                container=create_mock_container(service),
            )

        # Should have stopped early due to embedding bytes cap
        assert pages_embedded < 10, (
            f"Expected early exit due to embedding cap, but processed {pages_embedded} pages"
        )


# =============================================================================
# TEST CLASS: Phase 2 Savepoint Behavior
# =============================================================================


class TestPhase2SavepointBehavior:
    """Tests for per-page savepoint creation and atomic operations in Phase 2."""

    @pytest.mark.asyncio
    async def test_each_page_gets_own_savepoint(
        self, crawl_context, mock_embedding_model, mock_embeddings_service
    ):
        """
        INVARIANT: Each page must get its own savepoint for atomic delete+insert.

        Scenario: 3 pages in batch
        Expected: session.begin_nested() called 3 times (once per page)
        """
        page_buffer = [
            {"url": f"https://example.com/page{i}", "content": f"Content for page {i}"}
            for i in range(3)
        ]

        savepoint_mock = AsyncMock()
        savepoint_mock.commit = AsyncMock()
        savepoint_mock.rollback = AsyncMock()

        # CRITICAL: Use create_mock_session() NOT AsyncMock() - see helper docstring
        mock_session = create_mock_session()
        mock_session.begin_nested = AsyncMock(return_value=savepoint_mock)
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: uuid4()))

        mock_sm = create_mock_sessionmanager(mock_session)

        with patch(
            "intric.worker.crawl.persistence._get_embedding_semaphore",
            return_value=asyncio.Semaphore(10),
        ), patch("intric.database.database.sessionmanager", mock_sm):
            from intric.worker.crawl_tasks import persist_batch

            await persist_batch(
                page_buffer=page_buffer,
                ctx=crawl_context,
                embedding_model=mock_embedding_model,
                container=create_mock_container(mock_embeddings_service),
            )

        # Verify begin_nested was called once per page
        assert mock_session.begin_nested.call_count == 3, (
            f"Expected 3 savepoints, got {mock_session.begin_nested.call_count}"
        )

    @pytest.mark.asyncio
    async def test_delete_and_insert_within_same_savepoint(
        self, crawl_context, mock_embedding_model, mock_embeddings_service
    ):
        """
        INVARIANT: Delete (deduplication) and insert must happen within same savepoint.

        This ensures atomic operation: either both succeed or both rollback.

        Scenario: 1 page
        Expected: DELETE and INSERT execute between begin_nested() and commit()
        """
        page_buffer = [
            {"url": "https://example.com/page1", "content": "Test content"}
        ]

        operation_order = []

        savepoint_mock = AsyncMock()

        async def track_commit():
            operation_order.append("COMMIT")

        savepoint_mock.commit = AsyncMock(side_effect=track_commit)

        async def track_execute(stmt):
            stmt_str = str(stmt)
            if "DELETE" in stmt_str:
                operation_order.append("DELETE")
            elif "INSERT" in stmt_str:
                operation_order.append("INSERT")
            return MagicMock(scalar_one=lambda: uuid4())

        # CRITICAL: Use create_mock_session() NOT AsyncMock() - see helper docstring
        mock_session = create_mock_session()

        async def track_begin_nested():
            operation_order.append("BEGIN_NESTED")
            return savepoint_mock

        mock_session.begin_nested = AsyncMock(side_effect=track_begin_nested)
        mock_session.execute = AsyncMock(side_effect=track_execute)

        mock_sm = create_mock_sessionmanager(mock_session)

        with patch(
            "intric.worker.crawl.persistence._get_embedding_semaphore",
            return_value=asyncio.Semaphore(10),
        ), patch("intric.database.database.sessionmanager", mock_sm):
            from intric.worker.crawl_tasks import persist_batch

            await persist_batch(
                page_buffer=page_buffer,
                ctx=crawl_context,
                embedding_model=mock_embedding_model,
                container=create_mock_container(mock_embeddings_service),
            )

        # Verify order: BEGIN_NESTED -> DELETE -> INSERT (blob) -> INSERT (chunks) -> COMMIT
        assert operation_order[0] == "BEGIN_NESTED", "Savepoint must start first"
        assert "DELETE" in operation_order, "DELETE must occur"
        assert "INSERT" in operation_order, "INSERT must occur"
        delete_idx = operation_order.index("DELETE")
        first_insert_idx = next(i for i, op in enumerate(operation_order) if op == "INSERT")
        commit_idx = operation_order.index("COMMIT")

        assert delete_idx > 0, "DELETE must be after BEGIN_NESTED"
        assert first_insert_idx > delete_idx, "INSERT must be after DELETE"
        assert commit_idx > first_insert_idx, "COMMIT must be after INSERTs"


# =============================================================================
# TEST CLASS: successful_urls Tracking
# =============================================================================


class TestSuccessfulUrlsTracking:
    """Tests for accurate tracking of successfully persisted URLs."""

    @pytest.mark.asyncio
    async def test_successful_urls_only_contains_committed_pages(
        self, crawl_context, mock_embedding_model, mock_embeddings_service
    ):
        """
        INVARIANT: successful_urls must contain ONLY URLs that were actually committed.

        This is the core data integrity fix for the slot leak issue.

        Scenario: 3 pages, page 2 fails during insert
        Expected: successful_urls = [page1, page3], not [page1, page2, page3]
        """
        page_buffer = [
            {"url": "https://example.com/success1", "content": "Content 1"},
            {"url": "https://example.com/fails", "content": "Content 2"},
            {"url": "https://example.com/success2", "content": "Content 3"},
        ]

        call_count = 0
        savepoint_instances = []

        def create_savepoint():
            nonlocal call_count
            call_count += 1
            current_call = call_count

            savepoint = AsyncMock()

            async def commit_with_failure():
                if current_call == 2:  # Second page fails on commit
                    raise Exception("Simulated constraint violation")

            savepoint.commit = AsyncMock(side_effect=commit_with_failure)
            savepoint.rollback = AsyncMock()
            savepoint_instances.append(savepoint)
            return savepoint

        # CRITICAL: Use create_mock_session() NOT AsyncMock() - see helper docstring
        mock_session = create_mock_session()
        mock_session.begin_nested = AsyncMock(side_effect=create_savepoint)
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: uuid4()))

        mock_sm = create_mock_sessionmanager(mock_session)

        with patch(
            "intric.worker.crawl.persistence._get_embedding_semaphore",
            return_value=asyncio.Semaphore(10),
        ), patch("intric.database.database.sessionmanager", mock_sm):
            from intric.worker.crawl_tasks import persist_batch

            success_count, failed_count, successful_urls, _ = await persist_batch(
                page_buffer=page_buffer,
                ctx=crawl_context,
                embedding_model=mock_embedding_model,
                container=create_mock_container(mock_embeddings_service),
            )

        # Verify correct tracking
        assert success_count == 2, f"Expected 2 successes, got {success_count}"
        assert failed_count == 1, f"Expected 1 failure, got {failed_count}"
        assert len(successful_urls) == 2, f"Expected 2 URLs, got {len(successful_urls)}"
        assert "https://example.com/success1" in successful_urls
        assert "https://example.com/success2" in successful_urls
        assert "https://example.com/fails" not in successful_urls, (
            "Failed URL must NOT be in successful_urls"
        )

    @pytest.mark.asyncio
    async def test_empty_buffer_returns_empty_urls(self, crawl_context, mock_embedding_model):
        """
        INVARIANT: Empty page_buffer should return (0, 0, [], {}).
        """
        from intric.worker.crawl_tasks import persist_batch

        result = await persist_batch(
            page_buffer=[],
            ctx=crawl_context,
            embedding_model=mock_embedding_model,
            container=create_mock_container(MagicMock()),
        )

        assert result == (0, 0, [], {}), f"Empty buffer should return (0, 0, [], {{}}), got {result}"

    @pytest.mark.asyncio
    async def test_no_embedding_model_fails_all_pages(self, crawl_context):
        """
        INVARIANT: When embedding_model is None, all pages fail with NO_EMBEDDING_MODEL reason.
        """
        from intric.worker.crawl_tasks import persist_batch
        from intric.worker.crawl_context import FailureReason

        page_buffer = [
            {"url": "https://example.com/page1", "content": "Content 1"},
            {"url": "https://example.com/page2", "content": "Content 2"},
        ]

        success, failed, urls, failures_by_reason = await persist_batch(
            page_buffer=page_buffer,
            ctx=crawl_context,
            embedding_model=None,  # No model
            container=create_mock_container(MagicMock()),
        )

        assert success == 0, f"Expected 0 successes with no embedding model, got {success}"
        assert failed == 2, f"Expected 2 failures with no embedding model, got {failed}"
        assert urls == [], f"Expected empty URLs with no embedding model, got {urls}"
        assert FailureReason.NO_EMBEDDING_MODEL.value in failures_by_reason
        assert len(failures_by_reason[FailureReason.NO_EMBEDDING_MODEL.value]) == 2

    @pytest.mark.asyncio
    async def test_savepoint_rollback_excludes_url_from_successful(
        self, crawl_context, mock_embedding_model, mock_embeddings_service
    ):
        """
        INVARIANT: When savepoint.rollback() is called, the URL must NOT appear in successful_urls.

        This is critical: rollback means the data was NOT persisted.
        """
        from intric.worker.crawl_context import FailureReason

        page_buffer = [
            {"url": "https://example.com/will-rollback", "content": "Content"}
        ]

        savepoint = AsyncMock()

        async def always_fail_commit():
            raise Exception("Force rollback")

        savepoint.commit = AsyncMock(side_effect=always_fail_commit)
        savepoint.rollback = AsyncMock()

        # CRITICAL: Use create_mock_session() NOT AsyncMock() - see helper docstring
        mock_session = create_mock_session()
        mock_session.begin_nested = AsyncMock(return_value=savepoint)
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: uuid4()))

        mock_sm = create_mock_sessionmanager(mock_session)

        with patch(
            "intric.worker.crawl.persistence._get_embedding_semaphore",
            return_value=asyncio.Semaphore(10),
        ), patch("intric.database.database.sessionmanager", mock_sm):
            from intric.worker.crawl_tasks import persist_batch

            success, failed, urls, failures_by_reason = await persist_batch(
                page_buffer=page_buffer,
                ctx=crawl_context,
                embedding_model=mock_embedding_model,
                container=create_mock_container(mock_embeddings_service),
            )

        # Verify rollback was called
        savepoint.rollback.assert_called_once()

        # Verify URL is NOT in successful_urls
        assert success == 0
        assert failed == 1
        assert urls == [], "Rolled-back URL must NOT appear in successful_urls"
        # DB error should be tracked
        assert FailureReason.DB_ERROR.value in failures_by_reason


# =============================================================================
# TEST CLASS: Phase Isolation (No DB in Phase 1)
# =============================================================================


class TestPhaseIsolation:
    """Tests that verify Phase 1 and Phase 2 use separate, short-lived sessions."""

    @pytest.mark.asyncio
    async def test_phase1_session_closed_before_phase2_session(
        self, crawl_context, mock_embedding_model
    ):
        """
        INVARIANT: Phase 1's embedding session must be closed before Phase 2's
        persistence session is opened.

        Architecture:
        - Phase 1: Short-lived session for loading provider credentials + embedding
        - Phase 2: Separate short-lived session for DB persistence

        This ensures neither session is held for extended periods.
        """
        phase1_session_closed_at = None
        phase2_session_opened_at = None
        operation_timeline = []

        async def mock_get_embeddings(model, chunks):
            operation_timeline.append(("EMBEDDING", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.01)  # Small delay to simulate API call
            return [(chunk, [0.1] * 384) for chunk in chunks]

        service = MagicMock()
        service.get_embeddings = AsyncMock(side_effect=mock_get_embeddings)

        page_buffer = [
            {"url": "https://example.com/page1", "content": "Content 1"}
        ]

        # Track Phase 1 session (create_session)
        phase1_session = MagicMock()
        phase1_session.begin = MagicMock(side_effect=lambda: AwaitableContextManager())

        async def track_phase1_close():
            nonlocal phase1_session_closed_at
            phase1_session_closed_at = asyncio.get_event_loop().time()
            operation_timeline.append(("PHASE1_SESSION_CLOSED", phase1_session_closed_at))

        phase1_session.close = AsyncMock(side_effect=track_phase1_close)

        # Track Phase 2 session (session context manager)
        phase2_session = MagicMock()
        phase2_session.begin_nested = AsyncMock(return_value=AsyncMock())
        phase2_session.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: uuid4()))
        phase2_session.begin = MagicMock(side_effect=lambda: AwaitableContextManager())

        class TrackingContextManager:
            """Tracks when Phase 2 session context is entered."""

            def __init__(self, session):
                self.session = session

            async def __aenter__(self):
                nonlocal phase2_session_opened_at
                phase2_session_opened_at = asyncio.get_event_loop().time()
                operation_timeline.append(("PHASE2_SESSION_OPENED", phase2_session_opened_at))
                return self.session

            async def __aexit__(self, *args):
                operation_timeline.append(("PHASE2_SESSION_CLOSED", asyncio.get_event_loop().time()))

        with patch(
            "intric.worker.crawl.persistence._get_embedding_semaphore",
            return_value=asyncio.Semaphore(10),
        ), patch("intric.database.database.sessionmanager") as mock_sm:
            # create_session() returns Phase 1 session
            mock_sm.create_session.return_value = phase1_session
            # session() context manager returns Phase 2 session
            mock_sm.session.return_value = TrackingContextManager(phase2_session)

            from intric.worker.crawl_tasks import persist_batch

            await persist_batch(
                page_buffer=page_buffer,
                ctx=crawl_context,
                embedding_model=mock_embedding_model,
                container=create_mock_container(service),
            )

        # Verify Phase 1 session closed BEFORE Phase 2 session opened
        assert phase1_session_closed_at is not None, "Phase 1 session should have been closed"
        assert phase2_session_opened_at is not None, "Phase 2 session should have been opened"
        assert phase1_session_closed_at < phase2_session_opened_at, (
            f"Phase 1 session must close before Phase 2 session opens. "
            f"Phase 1 closed at {phase1_session_closed_at}, Phase 2 opened at {phase2_session_opened_at}. "
            f"Timeline: {operation_timeline}"
        )


# =============================================================================
# TEST CLASS: Transaction Wall-Time Guard
# =============================================================================


class TestTransactionWallTimeGuard:
    """Tests for the transaction wall-time timeout in Phase 2."""

    @pytest.mark.asyncio
    async def test_transaction_timeout_fails_remaining_pages(
        self, crawl_context, mock_embedding_model, mock_embeddings_service
    ):
        """
        INVARIANT: When Phase 2 exceeds max_transaction_wall_time_seconds,
        all remaining uncommitted pages should be marked as failed.
        """
        # Create context with very short transaction timeout
        short_timeout_ctx = CrawlContext(
            website_id=crawl_context.website_id,
            tenant_id=crawl_context.tenant_id,
            tenant_slug=crawl_context.tenant_slug,
            user_id=crawl_context.user_id,
            embedding_model_id=crawl_context.embedding_model_id,
            embedding_model_name=crawl_context.embedding_model_name,
            embedding_model_open_source=crawl_context.embedding_model_open_source,
            embedding_model_family=crawl_context.embedding_model_family,
            embedding_model_dimensions=crawl_context.embedding_model_dimensions,
            http_auth_user=None,
            http_auth_pass=None,
            embedding_timeout_seconds=15,
            max_transaction_wall_time_seconds=1,  # 1 second timeout
        )

        page_buffer = [
            {"url": f"https://example.com/page{i}", "content": f"Content {i}"}
            for i in range(5)
        ]

        persist_count = 0

        async def slow_execute(stmt):
            nonlocal persist_count
            persist_count += 1
            if persist_count >= 2:
                await asyncio.sleep(2)  # Will trigger timeout
            return MagicMock(scalar_one=lambda: uuid4())

        # CRITICAL: Use create_mock_session() NOT AsyncMock() - see helper docstring
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock(side_effect=slow_execute)

        mock_sm = create_mock_sessionmanager(mock_session)

        with patch(
            "intric.worker.crawl.persistence._get_embedding_semaphore",
            return_value=asyncio.Semaphore(10),
        ), patch("intric.database.database.sessionmanager", mock_sm):
            from intric.worker.crawl_tasks import persist_batch

            success, failed, urls, _ = await persist_batch(
                page_buffer=page_buffer,
                ctx=short_timeout_ctx,
                embedding_model=mock_embedding_model,
                container=create_mock_container(mock_embeddings_service),
            )

        # Due to timeout, not all pages could be persisted
        total = success + failed
        assert total == 5, f"Total should be 5, got {total}"
        assert failed > 0, "Some pages should have failed due to timeout"
