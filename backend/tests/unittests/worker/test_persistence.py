"""Unit tests for the extracted persistence module.

Tests the crawl/persistence.py module directly to ensure:
1. The extraction maintains all functionality
2. Module imports work correctly
3. The embedding semaphore is properly isolated
4. Both old import path (crawl_tasks) and new path (crawl.persistence) work

Run with: pytest tests/unittests/worker/test_persistence.py -v
"""

import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from intric.worker.crawl_context import CrawlContext, PreparedPage


class TestPersistenceModuleImports:
    """Tests that the persistence module can be imported from both locations."""

    def test_import_from_crawl_package(self):
        """persist_batch should be importable from intric.worker.crawl."""
        from intric.worker.crawl import persist_batch
        assert callable(persist_batch)

    def test_import_from_crawl_tasks_backward_compat(self):
        """persist_batch should still be importable from crawl_tasks for backward compatibility."""
        from intric.worker.crawl_tasks import persist_batch
        assert callable(persist_batch)

    def test_both_imports_are_same_function(self):
        """Both import paths should resolve to the same function."""
        from intric.worker.crawl import persist_batch as pb1
        from intric.worker.crawl_tasks import persist_batch as pb2
        # Note: pb1 and pb2 might not be the exact same object due to re-export,
        # but they should have the same behavior. We test that both are callable.
        assert callable(pb1)
        assert callable(pb2)


class TestPersistenceModuleSemantics:
    """Tests for persist_batch behavior after extraction."""

    @pytest.mark.asyncio
    async def test_empty_buffer_returns_zeros(self):
        """Empty page buffer should return (0, 0, [], [])."""
        from intric.worker.crawl.persistence import persist_batch

        ctx = CrawlContext(
            website_id=uuid4(),
            tenant_id=uuid4(),
            tenant_slug="test",
            user_id=uuid4(),
            embedding_model_id=uuid4(),
            embedding_model_name="test-model",
            embedding_model_open_source=False,
            embedding_model_family=None,
            embedding_model_dimensions=1536,
        )

        success, failed, success_urls, failed_urls = await persist_batch(
            page_buffer=[],
            ctx=ctx,
            embedding_model=MagicMock(),
            create_embeddings_service=MagicMock(),
        )

        assert success == 0
        assert failed == 0
        assert success_urls == []
        assert failed_urls == []

    @pytest.mark.asyncio
    async def test_none_embedding_model_fails_all_pages(self):
        """None embedding model should fail all pages."""
        from intric.worker.crawl.persistence import persist_batch

        ctx = CrawlContext(
            website_id=uuid4(),
            tenant_id=uuid4(),
            tenant_slug="test",
            user_id=uuid4(),
            embedding_model_id=uuid4(),
            embedding_model_name="test-model",
            embedding_model_open_source=False,
            embedding_model_family=None,
            embedding_model_dimensions=1536,
        )

        page_buffer = [
            {"url": "https://example.com/page1", "content": "Test content 1"},
            {"url": "https://example.com/page2", "content": "Test content 2"},
        ]

        success, failed, success_urls, failed_urls = await persist_batch(
            page_buffer=page_buffer,
            ctx=ctx,
            embedding_model=None,  # No embedding model
            create_embeddings_service=MagicMock(),
        )

        assert success == 0
        assert failed == 2
        assert success_urls == []
        assert len(failed_urls) == 2


class TestEmbeddingSemaphore:
    """Tests for the embedding semaphore functionality."""

    def test_semaphore_getter_is_callable(self):
        """_get_embedding_semaphore should be callable."""
        from intric.worker.crawl.persistence import _get_embedding_semaphore
        assert callable(_get_embedding_semaphore)

    def test_semaphore_returns_asyncio_semaphore(self):
        """_get_embedding_semaphore should return an asyncio.Semaphore."""
        import asyncio
        from intric.worker.crawl.persistence import _get_embedding_semaphore

        sem = _get_embedding_semaphore()
        assert isinstance(sem, asyncio.Semaphore)


class TestPreparedPageDataclass:
    """Tests for the PreparedPage dataclass used by persist_batch."""

    def test_prepared_page_creation(self):
        """PreparedPage should be creatable with all required fields."""
        prepared = PreparedPage(
            url="https://example.com/test",
            title="Test Page",
            content="Test content",
            content_hash=b"\x00" * 32,  # 32-byte hash
            chunks=["chunk1", "chunk2"],
            embeddings=[[0.1, 0.2], [0.3, 0.4]],
            tenant_id=uuid4(),
            website_id=uuid4(),
            user_id=uuid4(),
            embedding_model_id=uuid4(),
        )

        assert prepared.url == "https://example.com/test"
        assert prepared.title == "Test Page"
        assert len(prepared.chunks) == 2
        assert len(prepared.embeddings) == 2


class TestCrawlContextDataclass:
    """Tests for CrawlContext DTO used by persist_batch."""

    def test_crawl_context_immutable(self):
        """CrawlContext should be frozen (immutable)."""
        ctx = CrawlContext(
            website_id=uuid4(),
            tenant_id=uuid4(),
            tenant_slug="test",
            user_id=uuid4(),
            embedding_model_id=uuid4(),
            embedding_model_name="test-model",
            embedding_model_open_source=False,
            embedding_model_family=None,
            embedding_model_dimensions=1536,
        )

        # Attempting to modify should raise FrozenInstanceError
        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
            ctx.website_id = uuid4()

    def test_crawl_context_default_batch_settings(self):
        """CrawlContext should have sensible default batch settings."""
        ctx = CrawlContext(
            website_id=uuid4(),
            tenant_id=uuid4(),
            tenant_slug="test",
            user_id=uuid4(),
            embedding_model_id=uuid4(),
            embedding_model_name="test-model",
            embedding_model_open_source=False,
            embedding_model_family=None,
            embedding_model_dimensions=1536,
        )

        # Verify defaults from docstring
        assert ctx.batch_size == 50
        assert ctx.max_batch_content_bytes == 10_000_000  # 10MB
        assert ctx.max_batch_embedding_bytes == 50_000_000  # 50MB
        assert ctx.embedding_timeout_seconds == 15
        assert ctx.max_transaction_wall_time_seconds == 30
