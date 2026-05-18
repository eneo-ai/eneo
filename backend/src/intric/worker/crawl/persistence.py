"""Batch persistence for crawled pages using the TWO-PHASE pattern.

This module contains the core persistence logic for crawling:
- Phase 1: Pure compute (embeddings) outside any DB transaction
- Phase 2: Short-lived DB session (~50-300ms) for persistence

The two-phase pattern minimizes database connection hold time by
separating expensive network I/O from database operations.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from langchain.text_splitter import RecursiveCharacterTextSplitter
from typing_extensions import TypedDict

from intric.completion_models.infrastructure.context_builder import count_tokens
from intric.database.tables.info_blob_chunk_table import InfoBlobChunks
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.info_blobs.info_blob import InfoBlobChunk
from intric.main.config import get_settings
from intric.main.container.container_overrides import scoped_container_overrides
from intric.main.logging import get_logger
from intric.websites.domain.crawl_outcome import FailureReason
from intric.websites.domain.crawl_run_repo import CrawlRunRepository
from intric.worker.crawl_context import (
    CrawlContext,
    EmbeddingModelSpec,
    PreparedPage,
)

if TYPE_CHECKING:
    from intric.main.container.container import Container

logger = get_logger(__name__)

# Chunking settings (matching datastore.py pattern)
_CHUNK_SIZE = 200
_CHUNK_OVERLAP = 40

# EMBEDDING SEMAPHORE: Module-level bounded concurrency
#
# This semaphore limits concurrent embedding API calls across ALL crawl tasks
# in this worker process. Without this, N concurrent crawls could each fire
# embedding requests simultaneously, overwhelming the embedding API or hitting
# rate limits.
#
# The semaphore is created lazily on first use to ensure it uses the correct
# concurrency limit from settings.
_embedding_semaphore: asyncio.Semaphore | None = None


class CrawlPageData(TypedDict):
    url: str
    content: str


@dataclass(frozen=True, slots=True)
class ExistingBlobState:
    content_hash: bytes
    embedding_model_id: UUID | None

    def is_current_for(
        self,
        *,
        content_hash: bytes,
        embedding_model_id: UUID | None,
    ) -> bool:
        if self.content_hash != content_hash:
            return False
        if embedding_model_id is None:
            return True
        return self.embedding_model_id == embedding_model_id


@dataclass(frozen=True, slots=True)
class _PageToEmbed:
    url: str
    content: str
    content_hash: bytes


def _empty_failures() -> dict[FailureReason, tuple[str, ...]]:
    return {}


@dataclass(frozen=True)
class PersistBatchResult:
    """Result of one page persistence batch."""

    persisted_urls: tuple[str, ...] = ()
    retained_urls: tuple[str, ...] = ()
    failures_by_reason: dict[FailureReason, tuple[str, ...]] = field(
        default_factory=_empty_failures
    )

    @property
    def persisted_count(self) -> int:
        return len(self.persisted_urls)

    @property
    def retained_count(self) -> int:
        return len(self.retained_urls)

    @property
    def failed_count(self) -> int:
        return sum(len(urls) for urls in self.failures_by_reason.values())

    @property
    def failed_urls(self) -> frozenset[str]:
        return frozenset(
            url for urls in self.failures_by_reason.values() for url in urls
        )

    @property
    def cleanup_protected_titles(self) -> frozenset[str]:
        return frozenset(self.persisted_urls) | frozenset(self.retained_urls)


def _build_result(
    *,
    persisted_urls: list[str] | None = None,
    retained_urls: list[str] | None = None,
    failures_by_reason: dict[FailureReason, list[str]] | None = None,
) -> PersistBatchResult:
    frozen_failures: dict[FailureReason, tuple[str, ...]] = {}
    if failures_by_reason is not None:
        frozen_failures = {
            reason: tuple(urls) for reason, urls in failures_by_reason.items()
        }

    return PersistBatchResult(
        persisted_urls=tuple(persisted_urls or ()),
        retained_urls=tuple(retained_urls or ()),
        failures_by_reason=frozen_failures,
    )


def _get_embedding_semaphore() -> asyncio.Semaphore:
    """Get or create the module-level embedding semaphore.

    Lazy initialization ensures we read the correct concurrency limit from
    settings, which may not be available at module import time.

    Returns:
        asyncio.Semaphore with configured concurrency limit
    """
    global _embedding_semaphore
    if _embedding_semaphore is None:
        settings = get_settings()
        concurrency = getattr(settings, "crawl_embedding_concurrency", 3)
        _embedding_semaphore = asyncio.Semaphore(concurrency)
        logger.info(
            "Created embedding semaphore",
            extra={"concurrency_limit": concurrency},
        )
    return _embedding_semaphore


async def persist_batch(
    page_buffer: list[CrawlPageData],
    ctx: CrawlContext,
    embedding_model: EmbeddingModelSpec | None,
    container: "Container",
    existing_blob_state_by_title: Mapping[str, ExistingBlobState] | None = None,
) -> PersistBatchResult:
    """
    Persist a batch of pages using the TWO-PHASE pattern.

    This function minimizes database connection hold time by separating
    compute from persistence using a two-phase pattern. Pages whose stored
    content hash and embedding model already match the current crawl are
    retained without chunking, embedding, or database writes.

    Hash prepass:
        - Compute content_hash via SHA-256
        - Retain unchanged pages that are compatible with the current model
        - Reject empty content as a page-level failure

    PHASE 1 (Pure Compute - ZERO DB operations):
        - Chunk text using RecursiveCharacterTextSplitter
        - Call embedding API with concurrency limit (semaphore)
        - Create PreparedPage objects with pre-computed data
        - Network I/O happens HERE, outside any DB transaction

    PHASE 2 (Short-lived Session - ~50-300ms):
        - Open fresh session from pool
        - For each prepared page:
            - Create savepoint for atomic delete+insert
            - Delete existing by (title, website_id) for deduplication
            - Insert InfoBlob
            - Bulk insert InfoBlobChunks with embeddings
            - Commit savepoint
        - Return connection to pool immediately

    Args:
        page_buffer: List of page dicts with 'url' and 'content' keys
        ctx: CrawlContext DTO with all primitives (no ORM objects!)
        embedding_model: EmbeddingModelSpec frozen dataclass (session-independent)
        container: DI container for creating embedding service with proper session
        existing_blob_state_by_title: Existing blob state keyed by title/URL

    Returns:
        PersistBatchResult with persisted, retained, and failed URLs.

    Note:
        - Deduplication uses delete-then-insert pattern (not idempotent across workers)
        - For true idempotency, add UNIQUE constraint on (tenant_id, website_id, title)
        - CRITICAL: Only cleanup_protected_titles should be protected as successful work
        - CRITICAL: failed_urls should be excluded from stale deletion separately
    """
    from intric.database.database import sessionmanager

    if not page_buffer:
        return _build_result()

    existing_blob_states: Mapping[str, ExistingBlobState] = (
        existing_blob_state_by_title if existing_blob_state_by_title is not None else {}
    )

    failures_by_reason: dict[FailureReason, list[str]] = {}
    retained_urls: list[str] = []
    pages_to_embed: list[_PageToEmbed] = []
    prepared_pages: list[PreparedPage] = []
    persisted_urls: list[str] = []
    buffer_embedding_bytes = 0

    def add_failure(reason: FailureReason, url: str) -> None:
        failures_by_reason.setdefault(reason, []).append(url)

    for page_data in page_buffer:
        url = page_data["url"]
        content = page_data["content"]

        if not content.strip():
            logger.warning(
                f"Skipping empty page {url}",
                extra={
                    "website_id": str(ctx.website_id),
                    "url": url,
                    "reason": "empty_content",
                    "content_length": len(content) if content else 0,
                },
            )
            add_failure(FailureReason.EMPTY_CONTENT, url)
            continue

        content_hash = hashlib.sha256(content.encode("utf-8")).digest()
        existing_blob_state = existing_blob_states.get(url)
        if existing_blob_state is not None and existing_blob_state.is_current_for(
            content_hash=content_hash,
            embedding_model_id=ctx.embedding_model_id,
        ):
            retained_urls.append(url)
            continue

        pages_to_embed.append(
            _PageToEmbed(url=url, content=content, content_hash=content_hash)
        )

    if not pages_to_embed:
        return _build_result(
            retained_urls=retained_urls,
            failures_by_reason=failures_by_reason,
        )

    if embedding_model is None:
        logger.warning(
            "No embedding model configured for website",
            extra={
                "website_id": str(ctx.website_id),
                "batch_size": len(pages_to_embed),
                "retained_count": len(retained_urls),
            },
        )
        for page in pages_to_embed:
            add_failure(FailureReason.NO_EMBEDDING_MODEL, page.url)
        return _build_result(
            retained_urls=retained_urls,
            failures_by_reason=failures_by_reason,
        )

    if ctx.embedding_model_id is None:
        logger.warning(
            "Embedding model context missing model id",
            extra={
                "website_id": str(ctx.website_id),
                "embedding_model_name": getattr(embedding_model, "name", None),
                "retained_count": len(retained_urls),
            },
        )
        for page in pages_to_embed:
            add_failure(FailureReason.NO_EMBEDDING_MODEL, page.url)
        return _build_result(
            retained_urls=retained_urls,
            failures_by_reason=failures_by_reason,
        )

    # Validate embedding model has required provider_id for credential lookup
    if not getattr(embedding_model, "provider_id", None):
        logger.error(
            "Embedding model missing provider_id - cannot load API credentials",
            extra={
                "website_id": str(ctx.website_id),
                "embedding_model_name": getattr(embedding_model, "name", None),
                "embedding_model_id": str(getattr(embedding_model, "id", None)),
                "retained_count": len(retained_urls),
            },
        )
        for page in pages_to_embed:
            add_failure(FailureReason.MISSING_PROVIDER, page.url)
        return _build_result(
            retained_urls=retained_urls,
            failures_by_reason=failures_by_reason,
        )

    # Create a short-lived session for embedding service to load provider credentials
    embedding_session = sessionmanager.create_session()
    try:
        await embedding_session.begin()
        with scoped_container_overrides(container, session=embedding_session):
            create_embeddings_service = container.create_embeddings_service()
    except Exception as e:
        logger.error(
            "Failed to initialize embedding service",
            extra={
                "website_id": str(ctx.website_id),
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        await embedding_session.close()
        for page in pages_to_embed:
            add_failure(FailureReason.EMBEDDING_ERROR, page.url)
        return _build_result(
            retained_urls=retained_urls,
            failures_by_reason=failures_by_reason,
        )

    # Create text splitter (matching datastore.py pattern)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
        length_function=count_tokens,
    )

    # PHASE 1: Compute embeddings (uses embedding_session for provider credentials)
    # The embedding session is used to load API credentials from DB, but the actual
    # embedding API calls are external network I/O, not DB operations.
    logger.debug(
        "Phase 1: Computing embeddings for batch",
        extra={
            "website_id": str(ctx.website_id),
            "batch_size": len(pages_to_embed),
            "retained_count": len(retained_urls),
            "embedding_model": ctx.embedding_model_name,
        },
    )

    try:
        for page_index, page in enumerate(pages_to_embed):
            try:
                # 1. Chunk the text (local operation)
                raw_chunks = splitter.split_text(page.content)
                chunks = [chunk.strip() for chunk in raw_chunks if chunk.strip()]

                if not chunks:
                    logger.warning(
                        f"No chunks after splitting for {page.url}",
                        extra={
                            "website_id": str(ctx.website_id),
                            "url": page.url,
                            "reason": "no_chunks",
                            "content_length": len(page.content),
                            "raw_chunks_count": len(raw_chunks),
                        },
                    )
                    add_failure(FailureReason.NO_CHUNKS, page.url)
                    continue

                # 2. Create InfoBlobChunk objects for embedding service
                # Note: info_blob_id is a placeholder - will be set in Phase 2
                chunk_objects = [
                    InfoBlobChunk(
                        chunk_no=i,
                        text=chunk_text,
                        info_blob_id=ctx.website_id,  # Placeholder, not used by embedding service
                        tenant_id=ctx.tenant_id,
                    )
                    for i, chunk_text in enumerate(chunks)
                ]

                # 3. Call embedding API with semaphore limit and timeout
                # This is the expensive network I/O - happens OUTSIDE any DB transaction
                async with _get_embedding_semaphore():
                    try:
                        async with asyncio.timeout(ctx.embedding_timeout_seconds):
                            embedding_batch = (
                                await create_embeddings_service.get_embeddings(
                                    model=embedding_model,
                                    chunks=chunk_objects,
                                )
                            )
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Embedding timeout for {page.url} after {ctx.embedding_timeout_seconds}s",
                            extra={
                                "website_id": str(ctx.website_id),
                                "tenant_id": str(ctx.tenant_id),
                                "url": page.url,
                                "num_chunks": len(chunks),
                            },
                        )
                        add_failure(FailureReason.EMBEDDING_TIMEOUT, page.url)
                        continue

                # 4. Extract embeddings from ChunkEmbeddingList
                embeddings: list[list[float]] = []
                for _, embedding in embedding_batch.embeddings:
                    # ChunkEmbeddingList returns numpy arrays, convert to list
                    embeddings.append(
                        embedding.tolist()  # type: ignore[attr-defined]
                        if hasattr(embedding, "tolist")
                        else list(embedding)
                    )

                # 5. Track embedding memory for early flush
                embedding_bytes = sum(
                    len(e) * 4 for e in embeddings
                )  # float32 = 4 bytes
                buffer_embedding_bytes += embedding_bytes

                # 6. Create PreparedPage with all data needed for Phase 2
                embedding_model_id = ctx.embedding_model_id
                prepared = PreparedPage(
                    url=page.url,
                    title=page.url,  # URL as title, matching existing crawler pattern
                    content=page.content,
                    content_hash=page.content_hash,
                    chunks=chunks,
                    embeddings=embeddings,
                    embedding_usage=embedding_batch.usage,
                    tenant_id=ctx.tenant_id,
                    website_id=ctx.website_id,
                    user_id=ctx.user_id,
                    embedding_model_id=embedding_model_id,
                )
                prepared_pages.append(prepared)

                # Check memory cap for early flush
                if buffer_embedding_bytes >= ctx.max_batch_embedding_bytes:
                    for unprocessed_page in pages_to_embed[page_index + 1 :]:
                        add_failure(
                            FailureReason.EMBEDDING_BATCH_LIMIT,
                            unprocessed_page.url,
                        )
                    logger.info(
                        f"Embedding memory cap reached ({buffer_embedding_bytes} bytes), stopping Phase 1 early",
                        extra={
                            "website_id": str(ctx.website_id),
                            "pages_prepared": len(prepared_pages),
                            "pages_unprocessed": len(pages_to_embed) - page_index - 1,
                        },
                    )
                    break

            except Exception as e:
                logger.error(
                    f"Phase 1: Failed to prepare page {page.url}: {e}",
                    extra={
                        "website_id": str(ctx.website_id),
                        "tenant_id": str(ctx.tenant_id),
                        "url": page.url,
                        "error": str(e),
                    },
                )
                add_failure(FailureReason.EMBEDDING_ERROR, page.url)
                continue
    finally:
        # Close embedding session after Phase 1 completes
        # This returns the connection to the pool before Phase 2 starts
        await embedding_session.close()

    if not prepared_pages:
        logger.warning(
            "No pages prepared after Phase 1",
            extra={
                "website_id": str(ctx.website_id),
                "failed_count": sum(len(urls) for urls in failures_by_reason.values()),
                "retained_count": len(retained_urls),
            },
        )
        return _build_result(
            retained_urls=retained_urls,
            failures_by_reason=failures_by_reason,
        )

    # PHASE 2: Persist to DB (SHORT-LIVED SESSION)
    # This is the only part that holds a database connection.
    # Target: ~50-300ms total, returned to pool immediately after.
    logger.debug(
        "Phase 2: Persisting batch to database",
        extra={
            "website_id": str(ctx.website_id),
            "pages_to_persist": len(prepared_pages),
            "total_chunks": sum(len(p.chunks) for p in prepared_pages),
        },
    )

    try:
        async with asyncio.timeout(ctx.max_transaction_wall_time_seconds):
            async with sessionmanager.session() as session, session.begin():
                indexed_token_delta = 0
                indexed_cost_delta = Decimal("0")
                saw_indexed_cost = False
                saw_provider_usage = False
                saw_missing_usage = False
                for prepared in prepared_pages:
                    # Per-page savepoint for atomic delete+insert
                    savepoint = await session.begin_nested()
                    try:
                        # 1. DEDUPLICATION: Delete existing by (title, website_id)
                        # This matches the existing _delete_if_same_title() pattern
                        delete_stmt = sa.delete(InfoBlobs).where(
                            sa.and_(
                                InfoBlobs.title == prepared.title,
                                InfoBlobs.website_id == prepared.website_id,
                                InfoBlobs.tenant_id == prepared.tenant_id,
                            )
                        )
                        await session.execute(delete_stmt)

                        # 2. Insert new InfoBlob
                        info_blob_values = {
                            "text": prepared.content,
                            "title": prepared.title,
                            "url": prepared.url,
                            "size": len(prepared.content.encode("utf-8")),
                            "content_hash": prepared.content_hash,
                            "user_id": prepared.user_id,
                            "tenant_id": prepared.tenant_id,
                            "website_id": prepared.website_id,
                            "embedding_model_id": prepared.embedding_model_id,
                            "group_id": None,  # Website crawls don't have group_id
                            "integration_knowledge_id": None,
                        }

                        insert_blob_stmt = (
                            sa.insert(InfoBlobs)
                            .values(**info_blob_values)
                            .returning(InfoBlobs.id)
                        )
                        result = await session.execute(insert_blob_stmt)
                        info_blob_id = result.scalar_one()

                        # 3. Bulk insert chunks with embeddings
                        chunk_values = [
                            {
                                "text": chunk_text,
                                "chunk_no": i,
                                "size": len(chunk_text.encode("utf-8")),
                                "embedding": embedding,
                                "info_blob_id": info_blob_id,
                                "tenant_id": prepared.tenant_id,
                            }
                            for i, (chunk_text, embedding) in enumerate(
                                zip(prepared.chunks, prepared.embeddings)
                            )
                        ]

                        if chunk_values:
                            insert_chunks_stmt = sa.insert(InfoBlobChunks).values(
                                chunk_values
                            )
                            await session.execute(insert_chunks_stmt)

                        await savepoint.commit()
                        persisted_urls.append(
                            prepared.url
                        )  # Track this URL as actually persisted
                        if prepared.embedding_usage.source == "provider_reported":
                            saw_provider_usage = True
                            total_tokens = prepared.embedding_usage.total_tokens or 0
                            indexed_token_delta += total_tokens
                            if embedding_model.input_cost_per_token is not None:
                                saw_indexed_cost = True
                                indexed_cost_delta += (
                                    Decimal(total_tokens)
                                    * embedding_model.input_cost_per_token
                                )
                        else:
                            saw_missing_usage = True

                    except Exception as e:
                        await savepoint.rollback()
                        add_failure(FailureReason.DB_ERROR, prepared.url)
                        logger.error(
                            f"Phase 2: Failed to persist page {prepared.url}: {e}",
                            extra={
                                "website_id": str(ctx.website_id),
                                "tenant_id": str(ctx.tenant_id),
                                "url": prepared.url,
                                "error": str(e),
                            },
                        )

                if saw_provider_usage or saw_missing_usage:
                    usage_source = (
                        "provider_reported" if saw_provider_usage else "missing"
                    )
                    await CrawlRunRepository(session).record_indexed_embedding_usage(
                        run_id=ctx.run_id,
                        tenant_id=ctx.tenant_id,
                        token_delta=indexed_token_delta,
                        cost_delta=indexed_cost_delta if saw_indexed_cost else None,
                        usage_source=usage_source,
                    )

        # Connection returned to pool HERE - typically ~50-300ms total
        logger.debug(
            "Phase 2: Batch persist complete",
            extra={
                "website_id": str(ctx.website_id),
                "persisted_count": len(persisted_urls),
                "retained_count": len(retained_urls),
                "failed_count": sum(len(urls) for urls in failures_by_reason.values()),
            },
        )

    except asyncio.TimeoutError:
        logger.error(
            f"Phase 2: Transaction wall-time exceeded ({ctx.max_transaction_wall_time_seconds}s)",
            extra={
                "website_id": str(ctx.website_id),
                "pages_attempted": len(prepared_pages),
            },
        )
        # Mark all unpersisted pages as failed with DB_ERROR
        for p in prepared_pages:
            if p.url not in persisted_urls:
                add_failure(FailureReason.DB_ERROR, p.url)

    except Exception as e:
        logger.error(
            f"Phase 2: Session error: {e}",
            extra={
                "website_id": str(ctx.website_id),
                "error": str(e),
            },
        )
        # Mark all unpersisted pages as failed with DB_ERROR
        for p in prepared_pages:
            if p.url not in persisted_urls:
                add_failure(FailureReason.DB_ERROR, p.url)

    return _build_result(
        persisted_urls=persisted_urls,
        retained_urls=retained_urls,
        failures_by_reason=failures_by_reason,
    )
