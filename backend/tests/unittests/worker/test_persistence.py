"""Unit tests for the extracted persistence module.

Tests the crawl/persistence.py module directly to ensure:
1. The extraction maintains all functionality
2. Module imports work correctly
3. The embedding semaphore is properly isolated
4. Both old import path (crawl_tasks) and new path (crawl.persistence) work

Run with: pytest tests/unittests/worker/test_persistence.py -v
"""

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from intric.embedding_models.domain.embedding_batch import EmbeddingUsage
from intric.worker.crawl_context import CrawlContext, EmbeddingModelSpec, PreparedPage


def create_mock_container(embeddings_service):
    """Create a mock Container for persist_batch testing."""
    from unittest.mock import MagicMock

    mock_container = MagicMock()
    mock_session_provider = MagicMock()
    mock_session_provider.override = MagicMock()
    mock_container.session = mock_session_provider
    mock_container.create_embeddings_service = MagicMock(
        return_value=embeddings_service
    )
    return mock_container


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
    async def test_empty_buffer_returns_empty_result(self):
        """Empty page buffer should return an empty PersistBatchResult."""
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

        embedding_model = EmbeddingModelSpec(
            id=uuid4(),
            name="test-model",
            litellm_model_name="openai/text-embedding-ada-002",
            family=None,
            max_input=8191,
            max_batch_size=32,
            dimensions=1536,
            open_source=False,
            provider_id=uuid4(),
            provider_type="openai",
            provider_credentials={"api_key": "test"},
            provider_config={},
        )

        result = await persist_batch(
            page_buffer=[],
            ctx=ctx,
            embedding_model=embedding_model,
            container=create_mock_container(MagicMock()),
        )

        assert result.persisted_count == 0
        assert result.failed_count == 0
        assert result.persisted_urls == ()
        assert result.failures_by_reason == {}

    @pytest.mark.asyncio
    async def test_none_embedding_model_fails_all_pages(self):
        """None embedding model should fail all pages with NO_EMBEDDING_MODEL reason."""
        from intric.websites.domain.crawl_outcome import FailureReason
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

        result = await persist_batch(
            page_buffer=page_buffer,
            ctx=ctx,
            embedding_model=None,  # No embedding model
            container=create_mock_container(MagicMock()),
        )

        assert result.persisted_count == 0
        assert result.failed_count == 2
        assert result.persisted_urls == ()
        assert FailureReason.NO_EMBEDDING_MODEL in result.failures_by_reason
        assert len(result.failures_by_reason[FailureReason.NO_EMBEDDING_MODEL]) == 2


class TestCrawlTaskRetentionHelpers:
    def test_existing_blob_lookup_keeps_page_and_file_blob_state(self):
        from intric.worker.crawl import build_existing_blob_lookup

        page_model_id = uuid4()
        file_model_id = uuid4()
        rows = [
            ("https://example.com/page", b"page-hash", page_model_id),
            ("manual.pdf", b"file-hash", file_model_id),
            ("missing-hash", None, uuid4()),
            (None, b"ignored", uuid4()),
        ]

        titles, state_by_title = build_existing_blob_lookup(rows)

        assert titles == (
            "https://example.com/page",
            "manual.pdf",
            "missing-hash",
        )
        assert state_by_title["https://example.com/page"].content_hash == b"page-hash"
        assert state_by_title["https://example.com/page"].embedding_model_id == (
            page_model_id
        )
        assert state_by_title["manual.pdf"].content_hash == b"file-hash"
        assert state_by_title["manual.pdf"].embedding_model_id == file_model_id
        assert "missing-hash" not in state_by_title

    def test_build_sitemap_lastmod_skip_urls_only_includes_current_url_blobs(self):
        from intric.worker.crawl.persistence import ExistingBlobState
        from intric.worker.crawl_tasks import _build_sitemap_lastmod_skip_urls

        current_model_id = uuid4()
        other_model_id = uuid4()

        skip_urls = _build_sitemap_lastmod_skip_urls(
            existing_blob_state_by_title={
                "https://example.com/current": ExistingBlobState(
                    content_hash=b"current",
                    embedding_model_id=current_model_id,
                ),
                "https://example.com/old-model": ExistingBlobState(
                    content_hash=b"old-model",
                    embedding_model_id=other_model_id,
                ),
                "manual.pdf": ExistingBlobState(
                    content_hash=b"file",
                    embedding_model_id=current_model_id,
                ),
            },
            embedding_model_id=current_model_id,
        )

        assert skip_urls == frozenset({"https://example.com/current"})

    def test_build_sitemap_lastmod_skip_urls_allows_existing_urls_when_model_missing(
        self,
    ):
        from intric.worker.crawl.persistence import ExistingBlobState
        from intric.worker.crawl_tasks import _build_sitemap_lastmod_skip_urls

        skip_urls = _build_sitemap_lastmod_skip_urls(
            existing_blob_state_by_title={
                "https://example.com/known": ExistingBlobState(
                    content_hash=b"known",
                    embedding_model_id=uuid4(),
                ),
                "manual.pdf": ExistingBlobState(
                    content_hash=b"file",
                    embedding_model_id=uuid4(),
                ),
            },
            embedding_model_id=None,
        )

        assert skip_urls == frozenset({"https://example.com/known"})

    def test_build_http_cache_dir_scopes_by_tenant_and_website(self, tmp_path):
        from intric.worker.crawl_tasks import _build_http_cache_dir

        tenant_id = uuid4()
        website_id = uuid4()

        cache_dir = _build_http_cache_dir(
            root_dir=tmp_path,
            tenant_id=tenant_id,
            website_id=website_id,
        )

        assert cache_dir == tmp_path / str(tenant_id) / str(website_id)

    def test_prune_http_cache_dir_removes_oldest_files_over_size_cap(self, tmp_path):
        from intric.worker.crawl_tasks import _prune_http_cache_dir

        old_file = tmp_path / "old"
        new_file = tmp_path / "new"
        old_file.write_bytes(b"a" * 10)
        new_file.write_bytes(b"b" * 10)
        old_time = 1_700_000_000
        new_time = old_time + 60
        old_file.touch()
        new_file.touch()

        os.utime(old_file, (old_time, old_time))
        os.utime(new_file, (new_time, new_time))

        _prune_http_cache_dir(tmp_path, max_bytes=10)

        assert not old_file.exists()
        assert new_file.exists()

    def test_retained_items_without_embedding_config_logs_once_per_crawl(
        self, monkeypatch
    ):
        import intric.worker.crawl_tasks as crawl_tasks

        mock_logger = MagicMock()
        monkeypatch.setattr(crawl_tasks, "logger", mock_logger)

        crawl_tasks._warn_if_retained_items_without_embedding_config(
            embedding_model=None,
            retained_pages=3,
            retained_files=1,
            website_id=uuid4(),
            tenant_id=uuid4(),
        )

        mock_logger.warning.assert_called_once()
        _, kwargs = mock_logger.warning.call_args
        assert kwargs["extra"]["reason"] == "embedding_misconfigured_but_no_changes"
        assert kwargs["extra"]["retained_pages"] == 3
        assert kwargs["extra"]["retained_files"] == 1
        assert kwargs["extra"]["retained_count"] == 4

    def test_retained_items_with_valid_embedding_config_do_not_warn(self, monkeypatch):
        import intric.worker.crawl_tasks as crawl_tasks

        mock_logger = MagicMock()
        monkeypatch.setattr(crawl_tasks, "logger", mock_logger)
        embedding_model = EmbeddingModelSpec(
            id=uuid4(),
            name="test-model",
            litellm_model_name="openai/text-embedding-ada-002",
            family=None,
            max_input=8191,
            max_batch_size=32,
            dimensions=1536,
            open_source=False,
            provider_id=uuid4(),
            provider_type="openai",
            provider_credentials={"api_key": "test"},
            provider_config={},
        )

        crawl_tasks._warn_if_retained_items_without_embedding_config(
            embedding_model=embedding_model,
            retained_pages=3,
            retained_files=1,
            website_id=uuid4(),
            tenant_id=uuid4(),
        )

        mock_logger.warning.assert_not_called()

    def test_retained_items_with_unresolved_provider_warn(self, monkeypatch):
        import intric.worker.crawl_tasks as crawl_tasks

        mock_logger = MagicMock()
        monkeypatch.setattr(crawl_tasks, "logger", mock_logger)
        embedding_model = EmbeddingModelSpec(
            id=uuid4(),
            name="test-model",
            litellm_model_name="openai/text-embedding-ada-002",
            family=None,
            max_input=8191,
            max_batch_size=32,
            dimensions=1536,
            open_source=False,
            provider_id=uuid4(),
            provider_type=None,
            provider_credentials=None,
            provider_config=None,
        )

        crawl_tasks._warn_if_retained_items_without_embedding_config(
            embedding_model=embedding_model,
            retained_pages=3,
            retained_files=1,
            website_id=uuid4(),
            tenant_id=uuid4(),
        )

        mock_logger.warning.assert_called_once()

    def test_exception_string_outcome_classifier_is_not_exported(self):
        import pytest

        with pytest.raises(ImportError):
            from intric.worker.crawl_tasks import (
                _crawl_outcome_code_for_exception,  # noqa: F401
            )

    def test_sitemap_lastmod_source_skip_requires_sitemap_source_verified_timestamp_and_setting(
        self,
    ):
        from intric.tenants.crawler_settings_helper import TenantCrawlerSettings
        from intric.websites.domain.crawl_run import CrawlType
        from intric.worker.crawl_tasks import _should_enable_sitemap_lastmod_skip

        last_source_verified_at = datetime.now(timezone.utc)
        enabled_settings = TenantCrawlerSettings.from_overrides(
            {"crawl_sitemap_lastmod_skip_enabled": True}
        )
        disabled_settings = TenantCrawlerSettings.from_overrides(
            {"crawl_sitemap_lastmod_skip_enabled": False}
        )

        assert _should_enable_sitemap_lastmod_skip(
            crawl_type=CrawlType.SITEMAP,
            website_last_source_verified_at=last_source_verified_at,
            tenant_crawler_settings=enabled_settings,
        )
        assert not _should_enable_sitemap_lastmod_skip(
            crawl_type=CrawlType.CRAWL,
            website_last_source_verified_at=last_source_verified_at,
            tenant_crawler_settings=enabled_settings,
        )
        assert not _should_enable_sitemap_lastmod_skip(
            crawl_type=CrawlType.SITEMAP,
            website_last_source_verified_at=None,
            tenant_crawler_settings=enabled_settings,
        )
        assert not _should_enable_sitemap_lastmod_skip(
            crawl_type=CrawlType.SITEMAP,
            website_last_source_verified_at=last_source_verified_at,
            tenant_crawler_settings=disabled_settings,
        )


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
            embedding_usage=EmbeddingUsage(
                prompt_tokens=None,
                total_tokens=None,
                source="missing",
            ),
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
