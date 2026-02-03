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
from typing import TYPE_CHECKING

import sqlalchemy as sa
from dependency_injector import providers
from langchain.text_splitter import RecursiveCharacterTextSplitter

from intric.completion_models.infrastructure.context_builder import count_tokens
from intric.database.tables.info_blob_chunk_table import InfoBlobChunks
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.info_blobs.info_blob import InfoBlobChunk
from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.worker.crawl_context import CrawlContext, EmbeddingModelSpec, FailureReason, PreparedPage

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
_EMBEDDING_SEMAPHORE: asyncio.Semaphore | None = None


def _get_embedding_semaphore() -> asyncio.Semaphore:
    """Get or create the module-level embedding semaphore.

    Lazy initialization ensures we read the correct concurrency limit from
    settings, which may not be available at module import time.

    Returns:
        asyncio.Semaphore with configured concurrency limit
    """
    global _EMBEDDING_SEMAPHORE
    if _EMBEDDING_SEMAPHORE is None:
        settings = get_settings()
        concurrency = getattr(settings, "crawl_embedding_concurrency", 3)
        _EMBEDDING_SEMAPHORE = asyncio.Semaphore(concurrency)
        logger.info(
            "Created embedding semaphore",
            extra={"concurrency_limit": concurrency},
        )
    return _EMBEDDING_SEMAPHORE


async def persist_batch(
    page_buffer: list[dict],
    ctx: CrawlContext,
    embedding_model: EmbeddingModelSpec | None,
    container: "Container",
) -> tuple[int, int, list[str], dict[str, list[str]]]:
    """
    Persist a batch of pages using the TWO-PHASE pattern.

    This function minimizes database connection hold time by separating
    compute from persistence using a two-phase pattern.

    PHASE 1 (Pure Compute - ZERO DB operations):
        - Compute content_hash via SHA-256
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

    Returns:
        Tuple of (success_count, failed_count, successful_urls, failures_by_reason)
        - success_count: Number of pages successfully persisted
        - failed_count: Number of pages that failed to persist
        - successful_urls: List of URLs that were ACTUALLY persisted (for accurate tracking)
        - failures_by_reason: Dict mapping FailureReason codes to lists of failed URLs

    Note:
        - Deduplication uses delete-then-insert pattern (not idempotent across workers)
        - For true idempotency, add UNIQUE constraint on (tenant_id, website_id, title)
        - CRITICAL: Only URLs in successful_urls should be marked as crawled
        - CRITICAL: URLs in failures_by_reason should NOT be deleted as stale
    """
    from intric.database.database import sessionmanager

    if not page_buffer:
        return 0, 0, [], {}

    # Track failures by reason code for detailed reporting
    failures_by_reason: dict[str, list[str]] = {}

    def add_failure(reason: FailureReason, url: str) -> None:
        """Track a failure by reason code."""
        reason_key = reason.value
        if reason_key not in failures_by_reason:
            failures_by_reason[reason_key] = []
        failures_by_reason[reason_key].append(url)

    if embedding_model is None:
        logger.warning(
            "No embedding model configured for website",
            extra={"website_id": str(ctx.website_id), "batch_size": len(page_buffer)},
        )
        for page in page_buffer:
            add_failure(FailureReason.NO_EMBEDDING_MODEL, page.get("url", "unknown"))
        return 0, len(page_buffer), [], failures_by_reason

    # Validate embedding model has required provider_id for credential lookup
    if not getattr(embedding_model, 'provider_id', None):
        logger.error(
            "Embedding model missing provider_id - cannot load API credentials",
            extra={
                "website_id": str(ctx.website_id),
                "embedding_model_name": getattr(embedding_model, 'name', None),
                "embedding_model_id": str(getattr(embedding_model, 'id', None)),
            },
        )
        for page in page_buffer:
            add_failure(FailureReason.MISSING_PROVIDER, page.get("url", "unknown"))
        return 0, len(page_buffer), [], failures_by_reason

    success_count = 0
    failed_count = 0
    successful_urls: list[str] = []
    prepared_pages: list[PreparedPage] = []
    buffer_embedding_bytes = 0

    # Create a short-lived session for embedding service to load provider credentials
    embedding_session = sessionmanager.create_session()
    try:
        await embedding_session.begin()
        container.session.override(providers.Object(embedding_session))
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
        for page in page_buffer:
            add_failure(FailureReason.EMBEDDING_ERROR, page.get("url", "unknown"))
        return 0, len(page_buffer), [], failures_by_reason

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
            "batch_size": len(page_buffer),
            "embedding_model": ctx.embedding_model_name,
        },
    )

    try:
        for page_data in page_buffer:
            url = page_data.get("url", "unknown")
            content = page_data.get("content", "")

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
                failed_count += 1
                add_failure(FailureReason.EMPTY_CONTENT, url)
                continue

            try:
                # 1. Compute content hash (local operation)
                content_hash = hashlib.sha256(content.encode("utf-8")).digest()

                # 2. Chunk the text (local operation)
                raw_chunks = splitter.split_text(content)
                chunks = [chunk.strip() for chunk in raw_chunks if chunk.strip()]

                if not chunks:
                    logger.warning(
                        f"No chunks after splitting for {url}",
                        extra={
                            "website_id": str(ctx.website_id),
                            "url": url,
                            "reason": "no_chunks",
                            "content_length": len(content),
                            "raw_chunks_count": len(raw_chunks),
                        },
                    )
                    failed_count += 1
                    add_failure(FailureReason.NO_CHUNKS, url)
                    continue

                # 3. Create InfoBlobChunk objects for embedding service
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

                # 4. Call embedding API with semaphore limit and timeout
                # This is the expensive network I/O - happens OUTSIDE any DB transaction
                async with _get_embedding_semaphore():
                    try:
                        async with asyncio.timeout(ctx.embedding_timeout_seconds):
                            chunk_embedding_list = await create_embeddings_service.get_embeddings(
                                model=embedding_model,
                                chunks=chunk_objects,
                            )
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Embedding timeout for {url} after {ctx.embedding_timeout_seconds}s",
                            extra={
                                "website_id": str(ctx.website_id),
                                "tenant_id": str(ctx.tenant_id),
                                "url": url,
                                "num_chunks": len(chunks),
                            },
                        )
                        failed_count += 1
                        add_failure(FailureReason.EMBEDDING_TIMEOUT, url)
                        continue

                # 5. Extract embeddings from ChunkEmbeddingList
                embeddings: list[list[float]] = []
                for _, embedding in chunk_embedding_list:
                    # ChunkEmbeddingList returns numpy arrays, convert to list
                    embeddings.append(embedding.tolist() if hasattr(embedding, "tolist") else list(embedding))

                # 6. Track embedding memory for early flush
                embedding_bytes = sum(len(e) * 4 for e in embeddings)  # float32 = 4 bytes
                buffer_embedding_bytes += embedding_bytes

                # 7. Create PreparedPage with all data needed for Phase 2
                prepared = PreparedPage(
                    url=url,
                    title=url,  # URL as title, matching existing crawler pattern
                    content=content,
                    content_hash=content_hash,
                    chunks=chunks,
                    embeddings=embeddings,
                    tenant_id=ctx.tenant_id,
                    website_id=ctx.website_id,
                    user_id=ctx.user_id,
                    embedding_model_id=ctx.embedding_model_id,
                )
                prepared_pages.append(prepared)

                # Check memory cap for early flush
                if buffer_embedding_bytes >= ctx.max_batch_embedding_bytes:
                    logger.info(
                        f"Embedding memory cap reached ({buffer_embedding_bytes} bytes), stopping Phase 1 early",
                        extra={"website_id": str(ctx.website_id), "pages_prepared": len(prepared_pages)},
                    )
                    break

            except Exception as e:
                logger.error(
                    f"Phase 1: Failed to prepare page {url}: {e}",
                    extra={
                        "website_id": str(ctx.website_id),
                        "tenant_id": str(ctx.tenant_id),
                        "url": url,
                        "error": str(e),
                    },
                )
                failed_count += 1
                add_failure(FailureReason.EMBEDDING_ERROR, url)
                continue
    finally:
        # Close embedding session after Phase 1 completes
        # This returns the connection to the pool before Phase 2 starts
        await embedding_session.close()

    if not prepared_pages:
        logger.warning(
            "No pages prepared after Phase 1",
            extra={"website_id": str(ctx.website_id), "failed_count": failed_count},
        )
        return success_count, failed_count, [], failures_by_reason

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
                            insert_chunks_stmt = sa.insert(InfoBlobChunks).values(chunk_values)
                            await session.execute(insert_chunks_stmt)

                        await savepoint.commit()
                        success_count += 1
                        successful_urls.append(prepared.url)  # Track this URL as actually persisted

                    except Exception as e:
                        await savepoint.rollback()
                        failed_count += 1
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

        # Connection returned to pool HERE - typically ~50-300ms total
        logger.debug(
            "Phase 2: Batch persist complete",
            extra={
                "website_id": str(ctx.website_id),
                "success_count": success_count,
                "failed_count": failed_count,
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
            if p.url not in successful_urls:
                add_failure(FailureReason.DB_ERROR, p.url)
        failed_count += len(prepared_pages) - success_count

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
            if p.url not in successful_urls:
                add_failure(FailureReason.DB_ERROR, p.url)
        failed_count += len(prepared_pages) - success_count

    return success_count, failed_count, successful_urls, failures_by_reason
