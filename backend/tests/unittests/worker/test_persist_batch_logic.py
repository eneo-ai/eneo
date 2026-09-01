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
7. successful_urls contains only published or confirmed-unchanged URLs

Run with: pytest tests/unittests/worker/test_persist_batch_logic.py -v
"""

import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import numpy as np
import pytest

from eneo.embedding_models.infrastructure.adapters.base import (
    PartialEmbeddingBatchError,
)
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.worker.crawl_context import (
    CrawlContext,
    EmbeddingModelSpec,
    FailureReason,
)


@pytest.fixture(autouse=True)
def current_crawl_lease():
    with patch(
        "eneo.websites.domain.crawl_run_repo.CrawlRunRepository.lock_attempt_lease",
        AsyncMock(return_value=True),
    ):
        yield


# =============================================================================
# HELPER: Mock Session Manager
# =============================================================================


def create_mock_session():
    """
    Create a properly structured mock session for sessionmanager.session().

    CRITICAL: The session MUST be a MagicMock, NOT an AsyncMock!

    Why? Python's AsyncMock wraps ALL method calls as coroutines, even when
    you set side_effect to return something different (like an async context
    manager). This breaks the pattern:

        async with sessionmanager.session() as session, session.begin():

    Here, session.begin() must return an async context manager (with __aenter__
    and __aexit__), NOT a coroutine. Using MagicMock lets side_effect return
    the async context manager directly.

    Returns:
        MagicMock configured to work with the combined async context manager pattern.
    """
    # MUST be MagicMock, not AsyncMock - see docstring
    mock_session = MagicMock()

    # session.begin() returns an async context manager (for transactions)
    @asynccontextmanager
    async def mock_begin_context():
        yield None

    mock_session.begin.side_effect = lambda: mock_begin_context()

    # These methods ARE coroutines, so use AsyncMock
    mock_session.execute = AsyncMock()
    mock_session.scalar = AsyncMock(return_value=0)
    mock_session.begin_nested = AsyncMock(return_value=AsyncMock())

    return mock_session


def create_mock_result():
    return MagicMock(
        one=lambda: (1_000_000, None),
        one_or_none=lambda: None,
        scalar_one=lambda: uuid4(),
    )


def create_mock_sessionmanager(mock_session):
    """
    Create a properly structured mock for sessionmanager.session().

    The real pattern is: async with sessionmanager.session() as session, session.begin():
    This requires sessionmanager.session() to return an async context manager,
    and session.begin() to also return an async context manager.

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

    return mock_sm


def create_mock_container(embeddings_service):
    """
    Create a mock Container for persist_batch testing.

    The container provides create_embeddings_service(), which returns the supplied
    session-independent mock service.

    Args:
        embeddings_service: Mock CreateEmbeddingsService to return

    Returns:
        Mock container with properly configured session override and service factory
    """
    mock_container = MagicMock()

    # Mock create_embeddings_service() to return the provided service
    mock_container.create_embeddings_service = MagicMock(
        return_value=embeddings_service
    )

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
        attempt_id=uuid4(),
        lease_owner="test-worker",
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
def embedding_model_spec():
    """Create an EmbeddingModelSpec for testing."""
    return EmbeddingModelSpec(
        id=uuid4(),
        name="test-embedding-model",
        litellm_model_name="openai/text-embedding-ada-002",
        family=None,
        max_input=8191,
        max_batch_size=32,
        dimensions=384,
        open_source=False,
        provider_id=uuid4(),
        provider_type="openai",
        provider_credentials={"api_key": "test-key"},
        provider_config={},
    )


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


class TestEmbeddingRequestPolicy:
    """Crawler policy is passed to the adapter that owns provider requests."""

    @pytest.mark.asyncio
    async def test_request_limit_and_timeout_reach_the_embedding_service(
        self, crawl_context, embedding_model_spec
    ):
        async def mock_get_embeddings(model, chunks):
            return [(chunk, [0.1] * 384) for chunk in chunks]

        service = MagicMock()
        service.get_embeddings = AsyncMock(side_effect=mock_get_embeddings)
        container = create_mock_container(service)
        semaphore = asyncio.Semaphore(2)
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock(return_value=create_mock_result())
        mock_sm = create_mock_sessionmanager(mock_session)

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=semaphore,
            ),
            patch("eneo.database.database.sessionmanager", mock_sm),
        ):
            from eneo.worker.crawl_tasks import persist_batch

            success, failed, _, _ = await persist_batch(
                page_buffer=[
                    {
                        "url": "https://example.com/one",
                        "content": "First municipal page",
                    },
                    {
                        "url": "https://example.com/two",
                        "content": "Second municipal page",
                    },
                ],
                ctx=crawl_context,
                embedding_model=embedding_model_spec,
                container=container,
            )

        assert success == 2
        assert failed == 0
        container.create_embeddings_service.assert_called_once_with(
            request_semaphore=semaphore,
            request_timeout_seconds=crawl_context.embedding_timeout_seconds,
        )


# =============================================================================
# TEST CLASS: Packed Embedding Requests
# =============================================================================


class TestPackedEmbeddingRequests:
    """Pages share the model-owned provider batches without changing output."""

    @pytest.mark.asyncio
    async def test_small_pages_share_one_embedding_operation(
        self, crawl_context, embedding_model_spec
    ):
        async def mock_get_embeddings(model, chunks):
            return [(chunk, [float(index), 0.5]) for index, chunk in enumerate(chunks)]

        service = MagicMock()
        service.get_embeddings = AsyncMock(side_effect=mock_get_embeddings)
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock(return_value=create_mock_result())
        mock_sm = create_mock_sessionmanager(mock_session)

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=asyncio.Semaphore(2),
            ),
            patch("eneo.database.database.sessionmanager", mock_sm),
        ):
            from eneo.worker.crawl_tasks import persist_batch

            success, failed, persisted, _ = await persist_batch(
                page_buffer=[
                    {
                        "url": f"https://example.com/page-{index}",
                        "content": f"Distinct municipal page {index}.",
                    }
                    for index in range(3)
                ],
                ctx=crawl_context,
                embedding_model=embedding_model_spec,
                container=create_mock_container(service),
            )

        assert success == 3
        assert failed == 0
        assert persisted == [
            "https://example.com/page-0",
            "https://example.com/page-1",
            "https://example.com/page-2",
        ]
        service.get_embeddings.assert_awaited_once()
        assert len(service.get_embeddings.await_args.kwargs["chunks"]) == 3

    @pytest.mark.asyncio
    async def test_timeout_publishes_only_complete_page_prefix(
        self, crawl_context, embedding_model_spec
    ):
        async def fail_after_first_page(model, chunks):
            completed = ChunkEmbeddingList()
            completed.add(chunks[:1], [[0.25, 0.5]])
            raise PartialEmbeddingBatchError(
                completed=completed,
                completed_count=1,
                cause=TimeoutError("provider request timed out"),
            )

        service = MagicMock()
        service.get_embeddings = AsyncMock(side_effect=fail_after_first_page)
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock(return_value=create_mock_result())
        mock_sm = create_mock_sessionmanager(mock_session)

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=asyncio.Semaphore(1),
            ),
            patch("eneo.database.database.sessionmanager", mock_sm),
        ):
            from eneo.worker.crawl_tasks import persist_batch

            success, failed, persisted, failures = await persist_batch(
                page_buffer=[
                    {
                        "url": f"https://example.com/page-{index}",
                        "content": f"Distinct municipal page {index}.",
                    }
                    for index in range(3)
                ],
                ctx=crawl_context,
                embedding_model=embedding_model_spec,
                container=create_mock_container(service),
            )

        assert success == 1
        assert failed == 2
        assert persisted == ["https://example.com/page-0"]
        assert failures == {
            FailureReason.EMBEDDING_TIMEOUT.value: [
                "https://example.com/page-1",
                "https://example.com/page-2",
            ]
        }
        assert mock_session.begin_nested.call_count == 1

    @pytest.mark.asyncio
    async def test_incomplete_page_is_never_published(
        self, crawl_context, embedding_model_spec
    ):
        async def fail_inside_first_page(model, chunks):
            assert len(chunks) > 1
            completed = ChunkEmbeddingList()
            completed.add(chunks[:1], [[0.25, 0.5]])
            raise PartialEmbeddingBatchError(
                completed=completed,
                completed_count=1,
                cause=RuntimeError("provider unavailable"),
            )

        service = MagicMock()
        service.get_embeddings = AsyncMock(side_effect=fail_inside_first_page)
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock(return_value=create_mock_result())
        mock_sm = create_mock_sessionmanager(mock_session)

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=asyncio.Semaphore(1),
            ),
            patch("eneo.database.database.sessionmanager", mock_sm),
        ):
            from eneo.worker.crawl_tasks import persist_batch

            success, failed, persisted, failures = await persist_batch(
                page_buffer=[
                    {
                        "url": "https://example.com/large",
                        "content": "municipal information " * 600,
                    },
                    {
                        "url": "https://example.com/after-large",
                        "content": "A later page must also remain unpublished.",
                    },
                ],
                ctx=crawl_context,
                embedding_model=embedding_model_spec,
                container=create_mock_container(service),
            )

        assert success == 0
        assert failed == 2
        assert persisted == []
        assert failures == {
            FailureReason.EMBEDDING_ERROR.value: [
                "https://example.com/large",
                "https://example.com/after-large",
            ]
        }
        mock_session.begin_nested.assert_not_awaited()


# =============================================================================
# TEST CLASS: Memory Caps Enforcement
# =============================================================================


class TestMemoryCapsEnforcement:
    """Tests for memory cap enforcement during Phase 1."""

    @pytest.mark.asyncio
    async def test_prepared_embeddings_are_retained_as_float32(
        self, crawl_context, embedding_model_spec
    ):
        """The database seam receives compact vectors with truthful byte size."""
        source_embedding = [0.123456789, -0.25, 4.5]

        async def mock_get_embeddings(model, chunks):
            return [(chunk, source_embedding) for chunk in chunks]

        service = MagicMock()
        service.get_embeddings = AsyncMock(side_effect=mock_get_embeddings)
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock(return_value=create_mock_result())
        mock_sm = create_mock_sessionmanager(mock_session)

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=asyncio.Semaphore(1),
            ),
            patch("eneo.database.database.sessionmanager", mock_sm),
        ):
            from eneo.worker.crawl_tasks import persist_batch

            success, failed, _, _ = await persist_batch(
                page_buffer=[
                    {
                        "url": "https://example.com/page",
                        "content": "A compact vector must keep its exact float32 value.",
                    }
                ],
                ctx=crawl_context,
                embedding_model=embedding_model_spec,
                container=create_mock_container(service),
            )

        chunk_insert = next(
            call.args[0]
            for call in mock_session.execute.await_args_list
            if getattr(getattr(call.args[0], "table", None), "name", None)
            == "info_blob_chunks"
        )
        retained_embedding = chunk_insert.compile().params["embedding_m0"]

        assert success == 1
        assert failed == 0
        assert isinstance(retained_embedding, np.ndarray)
        assert retained_embedding.dtype == np.float32
        assert retained_embedding.nbytes == len(source_embedding) * 4
        np.testing.assert_array_equal(
            retained_embedding,
            np.asarray(source_embedding, dtype=np.float32),
        )

    @pytest.mark.asyncio
    async def test_embedding_bytes_cap_flushes_without_dropping_tail(
        self, crawl_context, embedding_model_spec
    ):
        """
        INVARIANT: When embedding bytes exceed max_batch_embedding_bytes,
        the prepared subset is flushed and every remaining page is continued.

        Scenario: 10 pages, but embedding cap set very low (10KB)
        Expected: One packed embedding operation, then bounded DB publications
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
            attempt_id=crawl_context.attempt_id,
            lease_owner=crawl_context.lease_owner,
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

        # CRITICAL: Use create_mock_session() NOT AsyncMock() - see helper docstring
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock(return_value=create_mock_result())

        mock_sm = create_mock_sessionmanager(mock_session)

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=asyncio.Semaphore(10),
            ),
            patch("eneo.database.database.sessionmanager", mock_sm),
        ):
            from eneo.worker.crawl_tasks import persist_batch

            success, failed, persisted, _ = await persist_batch(
                page_buffer=page_buffer,
                ctx=small_cap_ctx,
                embedding_model=embedding_model_spec,
                container=create_mock_container(service),
            )

        assert success == 10
        assert failed == 0
        assert len(persisted) == 10
        service.get_embeddings.assert_awaited_once()
        assert mock_sm.session.call_count > 1


# =============================================================================
# TEST CLASS: Phase 2 Savepoint Behavior
# =============================================================================


class TestPhase2SavepointBehavior:
    """Tests for per-page savepoint creation and atomic operations in Phase 2."""

    @pytest.mark.asyncio
    async def test_each_page_gets_own_savepoint(
        self, crawl_context, embedding_model_spec, mock_embeddings_service
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
        mock_session.execute = AsyncMock(return_value=create_mock_result())

        mock_sm = create_mock_sessionmanager(mock_session)

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=asyncio.Semaphore(10),
            ),
            patch("eneo.database.database.sessionmanager", mock_sm),
        ):
            from eneo.worker.crawl_tasks import persist_batch

            await persist_batch(
                page_buffer=page_buffer,
                ctx=crawl_context,
                embedding_model=embedding_model_spec,
                container=create_mock_container(mock_embeddings_service),
            )

        # Verify begin_nested was called once per page
        assert mock_session.begin_nested.call_count == 3, (
            f"Expected 3 savepoints, got {mock_session.begin_nested.call_count}"
        )

    @pytest.mark.asyncio
    async def test_supersede_and_insert_within_same_savepoint(
        self, crawl_context, embedding_model_spec, mock_embeddings_service
    ):
        """
        INVARIANT: Version lookup, demotion and insert happen within one savepoint.

        This ensures atomic operation: either both succeed or both rollback.

        Scenario: 1 page
        Expected: SELECT and INSERT execute between begin_nested() and commit()
        """
        page_buffer = [{"url": "https://example.com/page1", "content": "Test content"}]

        operation_order = []

        savepoint_mock = AsyncMock()

        async def track_commit():
            operation_order.append("COMMIT")

        savepoint_mock.commit = AsyncMock(side_effect=track_commit)

        async def track_execute(stmt, params=None):
            stmt_str = str(stmt)
            if "SELECT" in stmt_str and "info_blobs" in stmt_str:
                operation_order.append("SELECT")
                return MagicMock(one_or_none=lambda: None)
            elif "INSERT" in stmt_str:
                operation_order.append("INSERT")
            return create_mock_result()

        # CRITICAL: Use create_mock_session() NOT AsyncMock() - see helper docstring
        mock_session = create_mock_session()

        async def track_begin_nested():
            operation_order.append("BEGIN_NESTED")
            return savepoint_mock

        mock_session.begin_nested = AsyncMock(side_effect=track_begin_nested)
        mock_session.execute = AsyncMock(side_effect=track_execute)

        mock_sm = create_mock_sessionmanager(mock_session)

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=asyncio.Semaphore(10),
            ),
            patch("eneo.database.database.sessionmanager", mock_sm),
        ):
            from eneo.worker.crawl_tasks import persist_batch

            await persist_batch(
                page_buffer=page_buffer,
                ctx=crawl_context,
                embedding_model=embedding_model_spec,
                container=create_mock_container(mock_embeddings_service),
            )

        # Verify order: BEGIN_NESTED -> SELECT -> INSERTs -> COMMIT
        assert operation_order[0] == "BEGIN_NESTED", "Savepoint must start first"
        assert "SELECT" in operation_order, "Active-version lookup must occur"
        assert "INSERT" in operation_order, "INSERT must occur"
        select_idx = operation_order.index("SELECT")
        first_insert_idx = next(
            i for i, op in enumerate(operation_order) if op == "INSERT"
        )
        commit_idx = operation_order.index("COMMIT")

        assert select_idx > 0, "SELECT must be after BEGIN_NESTED"
        assert first_insert_idx > select_idx, "INSERT must be after SELECT"
        assert commit_idx > first_insert_idx, "COMMIT must be after INSERTs"

    @pytest.mark.asyncio
    async def test_retained_quota_rejects_page_before_publication(
        self, crawl_context, embedding_model_spec, mock_embeddings_service
    ):
        page_buffer = [
            {
                "url": "https://example.com/over-quota",
                "content": "Content that cannot fit",
            }
        ]
        statements: list[str] = []
        savepoint = AsyncMock()
        savepoint.commit = AsyncMock()
        savepoint.rollback = AsyncMock()
        mock_session = create_mock_session()
        mock_session.begin_nested = AsyncMock(return_value=savepoint)
        mock_session.scalar = AsyncMock(side_effect=[9, 0])

        async def execute(stmt, params=None):
            statement = str(stmt)
            statements.append(statement)
            if "tenants" in statement and "users" in statement:
                return MagicMock(one=lambda: (10, None))
            if "FROM info_blobs" in statement:
                return MagicMock(one_or_none=lambda: None)
            return create_mock_result()

        mock_session.execute = AsyncMock(side_effect=execute)
        mock_sm = create_mock_sessionmanager(mock_session)

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=asyncio.Semaphore(10),
            ),
            patch("eneo.database.database.sessionmanager", mock_sm),
        ):
            from eneo.worker.crawl_tasks import persist_batch

            success, failed, urls, _ = await persist_batch(
                page_buffer=page_buffer,
                ctx=crawl_context,
                embedding_model=embedding_model_spec,
                container=create_mock_container(mock_embeddings_service),
            )

        assert (success, failed, urls) == (0, 1, [])
        assert not any(
            "INSERT INTO info_blobs" in statement for statement in statements
        )
        savepoint.rollback.assert_awaited_once()


# =============================================================================
# TEST CLASS: successful_urls Tracking
# =============================================================================


class TestSuccessfulUrlsTracking:
    """Tests for accurate tracking of successfully persisted URLs."""

    @pytest.mark.asyncio
    async def test_successful_urls_only_contains_committed_pages(
        self, crawl_context, embedding_model_spec, mock_embeddings_service
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
        mock_session.execute = AsyncMock(return_value=create_mock_result())

        mock_sm = create_mock_sessionmanager(mock_session)

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=asyncio.Semaphore(10),
            ),
            patch("eneo.database.database.sessionmanager", mock_sm),
        ):
            from eneo.worker.crawl_tasks import persist_batch

            success_count, failed_count, successful_urls, _ = await persist_batch(
                page_buffer=page_buffer,
                ctx=crawl_context,
                embedding_model=embedding_model_spec,
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
    async def test_empty_buffer_returns_empty_urls(
        self, crawl_context, embedding_model_spec
    ):
        """
        INVARIANT: Empty page_buffer should return (0, 0, [], {}).
        """
        from eneo.worker.crawl_tasks import persist_batch

        result = await persist_batch(
            page_buffer=[],
            ctx=crawl_context,
            embedding_model=embedding_model_spec,
            container=create_mock_container(MagicMock()),
        )

        assert result == (0, 0, [], {}), (
            f"Empty buffer should return (0, 0, [], {{}}), got {result}"
        )

    @pytest.mark.asyncio
    async def test_no_embedding_model_fails_all_pages(self, crawl_context):
        """
        INVARIANT: When embedding_model is None, all pages fail with NO_EMBEDDING_MODEL reason.
        """
        from eneo.worker.crawl_context import FailureReason
        from eneo.worker.crawl_tasks import persist_batch

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

        assert success == 0, (
            f"Expected 0 successes with no embedding model, got {success}"
        )
        assert failed == 2, f"Expected 2 failures with no embedding model, got {failed}"
        assert urls == [], f"Expected empty URLs with no embedding model, got {urls}"
        assert FailureReason.NO_EMBEDDING_MODEL.value in failures_by_reason
        assert len(failures_by_reason[FailureReason.NO_EMBEDDING_MODEL.value]) == 2

    @pytest.mark.asyncio
    async def test_savepoint_rollback_excludes_url_from_successful(
        self, crawl_context, embedding_model_spec, mock_embeddings_service
    ):
        """
        INVARIANT: When savepoint.rollback() is called, the URL must NOT appear in successful_urls.

        This is critical: rollback means the data was NOT persisted.
        """
        from eneo.worker.crawl_context import FailureReason

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
        mock_session.execute = AsyncMock(return_value=create_mock_result())

        mock_sm = create_mock_sessionmanager(mock_session)

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=asyncio.Semaphore(10),
            ),
            patch("eneo.database.database.sessionmanager", mock_sm),
        ):
            from eneo.worker.crawl_tasks import persist_batch

            success, failed, urls, failures_by_reason = await persist_batch(
                page_buffer=page_buffer,
                ctx=crawl_context,
                embedding_model=embedding_model_spec,
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
    """Tests that verify Phase 1 has ZERO database operations."""

    @pytest.mark.asyncio
    async def test_lost_attempt_lease_prevents_page_publication(
        self, crawl_context, embedding_model_spec, mock_embeddings_service
    ):
        mock_session = create_mock_session()
        mock_sm = create_mock_sessionmanager(mock_session)

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=asyncio.Semaphore(1),
            ),
            patch(
                "eneo.websites.domain.crawl_run_repo.CrawlRunRepository.lock_attempt_lease",
                AsyncMock(return_value=False),
            ),
            patch("eneo.database.database.sessionmanager", mock_sm),
        ):
            from eneo.worker.crawl.heartbeat import CrawlLeaseLostError
            from eneo.worker.crawl_tasks import persist_batch

            with pytest.raises(CrawlLeaseLostError):
                await persist_batch(
                    page_buffer=[
                        {
                            "url": "https://example.com/stale-worker",
                            "content": "Content from a worker whose lease expired",
                        }
                    ],
                    ctx=crawl_context,
                    embedding_model=embedding_model_spec,
                    container=create_mock_container(mock_embeddings_service),
                )

        mock_session.execute.assert_not_awaited()
        mock_session.begin_nested.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unchanged_page_skips_embedding_and_database_write(
        self, crawl_context, embedding_model_spec, mock_embeddings_service
    ):
        url = "https://example.com/unchanged"
        content = "Already published content"
        mock_session = create_mock_session()
        mock_sm = create_mock_sessionmanager(mock_session)

        with patch("eneo.database.database.sessionmanager", mock_sm):
            from eneo.worker.crawl_tasks import persist_batch

            success, failed, persisted_urls, failures = await persist_batch(
                page_buffer=[{"url": url, "content": content}],
                ctx=crawl_context,
                embedding_model=embedding_model_spec,
                container=create_mock_container(mock_embeddings_service),
                existing_publications={
                    url: (
                        sha256(content.encode("utf-8")).digest(),
                        embedding_model_spec.id,
                    )
                },
            )

        assert (success, failed, persisted_urls, failures) == (1, 0, [url], {})
        mock_embeddings_service.get_embeddings.assert_not_awaited()
        mock_sm.session.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_identity_can_use_title_and_extracted_content_hash(
        self, crawl_context, embedding_model_spec, mock_embeddings_service
    ):
        source_url = "https://example.com/files/agenda.pdf"
        title = "agenda"
        content = "Extracted meeting agenda"
        content_hash = sha256(content.encode("utf-8")).digest()
        mock_session = create_mock_session()
        mock_sm = create_mock_sessionmanager(mock_session)

        with patch("eneo.database.database.sessionmanager", mock_sm):
            from eneo.worker.crawl_tasks import persist_batch

            success, failed, persisted_titles, failures = await persist_batch(
                page_buffer=[
                    {
                        "url": source_url,
                        "title": title,
                        "content": content,
                        "content_hash": content_hash,
                    }
                ],
                ctx=crawl_context,
                embedding_model=embedding_model_spec,
                container=create_mock_container(mock_embeddings_service),
                existing_publications={title: (content_hash, embedding_model_spec.id)},
            )

        assert (success, failed, persisted_titles, failures) == (1, 0, [title], {})
        mock_embeddings_service.get_embeddings.assert_not_awaited()
        mock_sm.session.assert_not_called()

    @pytest.mark.asyncio
    async def test_matching_content_with_a_new_model_is_reembedded(
        self, crawl_context, embedding_model_spec, mock_embeddings_service
    ):
        url = "https://example.com/model-change"
        content = "Content published with an older embedding model"
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock(return_value=create_mock_result())
        mock_sm = create_mock_sessionmanager(mock_session)

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=asyncio.Semaphore(10),
            ),
            patch("eneo.database.database.sessionmanager", mock_sm),
        ):
            from eneo.worker.crawl_tasks import persist_batch

            success, failed, persisted_urls, failures = await persist_batch(
                page_buffer=[{"url": url, "content": content}],
                ctx=crawl_context,
                embedding_model=embedding_model_spec,
                container=create_mock_container(mock_embeddings_service),
                existing_publications={
                    url: (
                        sha256(content.encode("utf-8")).digest(),
                        uuid4(),
                    )
                },
            )

        assert (success, failed, persisted_urls, failures) == (1, 0, [url], {})
        mock_embeddings_service.get_embeddings.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_session_opened_during_phase_1(
        self, crawl_context, embedding_model_spec
    ):
        """
        INVARIANT: No database session should be opened during Phase 1 (embedding).

        Phase 1 should complete ALL embedding work before any DB session is created.
        """
        session_opened_at = None
        embedding_completed_at = None
        operation_timeline = []

        async def mock_get_embeddings(model, chunks):
            nonlocal embedding_completed_at
            operation_timeline.append(
                ("EMBEDDING_START", asyncio.get_event_loop().time())
            )
            await asyncio.sleep(0.01)  # Small delay to simulate API call
            operation_timeline.append(
                ("EMBEDDING_END", asyncio.get_event_loop().time())
            )
            embedding_completed_at = asyncio.get_event_loop().time()
            return [(chunk, [0.1] * 384) for chunk in chunks]

        service = MagicMock()
        service.get_embeddings = AsyncMock(side_effect=mock_get_embeddings)

        page_buffer = [{"url": "https://example.com/page1", "content": "Content 1"}]

        class TrackingContextManager:
            """Tracks when session context is entered."""

            def __init__(self, session):
                self.session = session

            async def __aenter__(self):
                nonlocal session_opened_at
                session_opened_at = asyncio.get_event_loop().time()
                operation_timeline.append(("SESSION_OPENED", session_opened_at))
                return self.session

            async def __aexit__(self, *args):
                operation_timeline.append(
                    ("SESSION_CLOSED", asyncio.get_event_loop().time())
                )

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=asyncio.Semaphore(10),
            ),
            patch("eneo.database.database.sessionmanager") as mock_sm,
        ):
            # CRITICAL: Use MagicMock for session (not AsyncMock) - see create_mock_session() docstring
            mock_session = MagicMock()
            mock_session.begin_nested = AsyncMock(return_value=AsyncMock())
            mock_session.execute = AsyncMock(return_value=create_mock_result())

            # session.begin() returns an async context manager
            @asynccontextmanager
            async def mock_begin_context():
                yield None

            mock_session.begin.side_effect = lambda: mock_begin_context()

            # Use tracking context manager for sessionmanager.session()
            mock_sm.session.return_value = TrackingContextManager(mock_session)

            from eneo.worker.crawl_tasks import persist_batch

            await persist_batch(
                page_buffer=page_buffer,
                ctx=crawl_context,
                embedding_model=embedding_model_spec,
                container=create_mock_container(service),
            )

        # Verify embedding completed BEFORE session was opened
        assert embedding_completed_at is not None, "Embedding should have completed"
        assert session_opened_at is not None, "Session should have been opened"
        mock_sm.create_session.assert_not_called()
        assert embedding_completed_at < session_opened_at, (
            f"Embedding must complete before session opens. "
            f"Embedding ended at {embedding_completed_at}, session opened at {session_opened_at}. "
            f"Timeline: {operation_timeline}"
        )


# =============================================================================
# TEST CLASS: Transaction Wall-Time Guard
# =============================================================================


class TestTransactionWallTimeGuard:
    """Tests for the transaction wall-time timeout in Phase 2."""

    @pytest.mark.asyncio
    async def test_transaction_timeout_fails_remaining_pages(
        self, crawl_context, embedding_model_spec, mock_embeddings_service
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
            attempt_id=crawl_context.attempt_id,
            lease_owner=crawl_context.lease_owner,
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
            return create_mock_result()

        # CRITICAL: Use create_mock_session() NOT AsyncMock() - see helper docstring
        mock_session = create_mock_session()
        mock_session.execute = AsyncMock(side_effect=slow_execute)

        mock_sm = create_mock_sessionmanager(mock_session)

        with (
            patch(
                "eneo.worker.crawl.persistence._get_embedding_semaphore",
                return_value=asyncio.Semaphore(10),
            ),
            patch("eneo.database.database.sessionmanager", mock_sm),
        ):
            from eneo.worker.crawl_tasks import persist_batch

            success, failed, urls, _ = await persist_batch(
                page_buffer=page_buffer,
                ctx=short_timeout_ctx,
                embedding_model=embedding_model_spec,
                container=create_mock_container(mock_embeddings_service),
            )

        # Due to timeout, not all pages could be persisted
        total = success + failed
        assert total == 5, f"Total should be 5, got {total}"
        assert failed > 0, "Some pages should have failed due to timeout"
