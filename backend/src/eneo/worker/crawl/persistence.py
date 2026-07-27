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
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import sqlalchemy as sa
from dependency_injector import providers
from langchain_text_splitters import RecursiveCharacterTextSplitter
from typing_extensions import TypedDict

from eneo.admin.quota_service import ensure_quota_capacity
from eneo.completion_models.infrastructure.context_builder import count_tokens
from eneo.database.tables.info_blob_chunk_table import InfoBlobChunks
from eneo.database.tables.info_blobs_table import (
    InfoBlobs,
    InfoBlobVersionState,
    active_info_blob_version,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.info_blobs.info_blob import InfoBlobChunk
from eneo.info_blobs.info_blob_repo import InfoBlobRepository
from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.worker.crawl_context import (
    CrawlContext,
    EmbeddingModelSpec,
    FailureReason,
    PreparedPage,
)

if TYPE_CHECKING:
    from eneo.main.container.container import Container

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
    existing_content_hashes: dict[str, bytes] | None = None,
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
            - Lock the page identity
            - Supersede the previous active version
            - Insert the replacement InfoBlob
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
        - successful_urls: List of URLs persisted or confirmed unchanged
        - failures_by_reason: Dict mapping FailureReason codes to lists of failed URLs

    Note:
        - Publication serializes concurrent updates for the same website page.
        - A failed replacement rolls back to the previous active version.
        - CRITICAL: Only URLs in successful_urls should be marked as crawled
        - CRITICAL: URLs in failures_by_reason should NOT be deleted as stale
    """
    from eneo.database.database import sessionmanager

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
            add_failure(FailureReason.NO_EMBEDDING_MODEL, page["url"])
        return 0, len(page_buffer), [], failures_by_reason

    # Validate embedding model has required provider_id for credential lookup
    if not getattr(embedding_model, "provider_id", None):
        logger.error(
            "Embedding model missing provider_id - cannot load API credentials",
            extra={
                "website_id": str(ctx.website_id),
                "embedding_model_name": getattr(embedding_model, "name", None),
                "embedding_model_id": str(getattr(embedding_model, "id", None)),
            },
        )
        for page in page_buffer:
            add_failure(FailureReason.MISSING_PROVIDER, page["url"])
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
        session_provider = cast(Any, container.session)
        session_provider.override(providers.Object(embedding_session))
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
            add_failure(FailureReason.EMBEDDING_ERROR, page["url"])
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
                failed_count += 1
                add_failure(FailureReason.EMPTY_CONTENT, url)
                continue

            try:
                # 1. Compute content hash (local operation)
                content_hash = hashlib.sha256(content.encode("utf-8")).digest()
                if (existing_content_hashes or {}).get(url) == content_hash:
                    success_count += 1
                    successful_urls.append(url)
                    continue

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
                            chunk_embedding_list = (
                                await create_embeddings_service.get_embeddings(
                                    model=cast(Any, embedding_model),
                                    chunks=chunk_objects,
                                )
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
                    embeddings.append(
                        embedding.tolist()  # type: ignore[attr-defined]
                        if hasattr(embedding, "tolist")
                        else list(embedding)
                    )

                # 6. Track embedding memory for early flush
                embedding_bytes = sum(
                    len(e) * 4 for e in embeddings
                )  # float32 = 4 bytes
                buffer_embedding_bytes += embedding_bytes

                # 7. Create PreparedPage with all data needed for Phase 2
                embedding_model_id = ctx.embedding_model_id
                assert embedding_model_id is not None
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
                    embedding_model_id=embedding_model_id,
                )
                prepared_pages.append(prepared)

                # Check memory cap for early flush
                if buffer_embedding_bytes >= ctx.max_batch_embedding_bytes:
                    logger.info(
                        f"Embedding memory cap reached ({buffer_embedding_bytes} bytes), stopping Phase 1 early",
                        extra={
                            "website_id": str(ctx.website_id),
                            "pages_prepared": len(prepared_pages),
                        },
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

    confirmed_unchanged_urls = successful_urls.copy()
    if not prepared_pages:
        log = logger.debug if successful_urls else logger.warning
        log(
            "No pages require publication after Phase 1",
            extra={
                "website_id": str(ctx.website_id),
                "unchanged_count": len(successful_urls),
                "failed_count": failed_count,
            },
        )
        return success_count, failed_count, successful_urls, failures_by_reason

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
                tenant_limit, user_limit = (
                    await session.execute(
                        sa.select(Tenants.quota_limit, Users.quota_limit)
                        .select_from(Users)
                        .join(Tenants, Tenants.id == Users.tenant_id)
                        .where(
                            Users.id == ctx.user_id,
                            Tenants.id == ctx.tenant_id,
                        )
                    )
                ).one()
                quota_repo = InfoBlobRepository(session)
                tenant_usage = await quota_repo.get_retained_size_of_tenant(
                    ctx.tenant_id
                )
                user_usage = (
                    await quota_repo.get_retained_size_of_user(ctx.user_id)
                    if user_limit is not None
                    else 0
                )

                for prepared in prepared_pages:
                    # Per-page savepoint keeps the previous complete version visible
                    # unless the replacement and all of its chunks are ready together.
                    savepoint = await session.begin_nested()
                    try:
                        await session.execute(
                            sa.text(
                                "SELECT pg_advisory_xact_lock("
                                "hashtextextended(:identity, 0))"
                            ),
                            {
                                "identity": (
                                    f"website:{prepared.website_id}:"
                                    f"title:{prepared.title}"
                                )
                            },
                        )

                        existing = (
                            await session.execute(
                                sa.select(
                                    InfoBlobs.id,
                                    InfoBlobs.source_id,
                                    InfoBlobs.content_hash,
                                )
                                .where(
                                    InfoBlobs.title == prepared.title,
                                    InfoBlobs.website_id == prepared.website_id,
                                    active_info_blob_version(),
                                )
                                .with_for_update()
                            )
                        ).one_or_none()
                        if (
                            existing is not None
                            and existing.content_hash == prepared.content_hash
                        ):
                            await savepoint.commit()
                            success_count += 1
                            successful_urls.append(prepared.url)
                            continue

                        chunk_sizes = [
                            len(chunk_text.encode("utf-8")) + len(embedding) * 4
                            for chunk_text, embedding in zip(
                                prepared.chunks,
                                prepared.embeddings,
                            )
                        ]
                        stored_size = len(prepared.content.encode("utf-8")) + sum(
                            chunk_sizes
                        )
                        ensure_quota_capacity(
                            tenant_usage=tenant_usage,
                            tenant_limit=tenant_limit,
                            user_usage=user_usage,
                            user_limit=user_limit,
                            size_in_bytes=stored_size,
                        )
                        source_id = (
                            existing.source_id if existing is not None else uuid4()
                        )
                        if existing is not None:
                            await session.execute(
                                sa.update(InfoBlobs)
                                .where(
                                    InfoBlobs.id == existing.id,
                                    active_info_blob_version(),
                                )
                                .values(
                                    version_state=(
                                        InfoBlobVersionState.SUPERSEDED.value
                                    )
                                )
                            )

                        info_blob_values = {
                            "text": prepared.content,
                            "title": prepared.title,
                            "url": prepared.url,
                            "size": stored_size,
                            "content_hash": prepared.content_hash,
                            "user_id": prepared.user_id,
                            "tenant_id": prepared.tenant_id,
                            "website_id": prepared.website_id,
                            "embedding_model_id": prepared.embedding_model_id,
                            "group_id": None,  # Website crawls don't have group_id
                            "integration_knowledge_id": None,
                            "source_id": source_id,
                            "version_state": InfoBlobVersionState.ACTIVE.value,
                        }

                        insert_blob_stmt = (
                            sa.insert(InfoBlobs)
                            .values(**info_blob_values)
                            .returning(InfoBlobs.id)
                        )
                        result = await session.execute(insert_blob_stmt)
                        info_blob_id = result.scalar_one()

                        chunk_values = [
                            {
                                "text": chunk_text,
                                "chunk_no": i,
                                "size": chunk_size,
                                "embedding": embedding,
                                "info_blob_id": info_blob_id,
                                "tenant_id": prepared.tenant_id,
                            }
                            for i, (chunk_text, embedding, chunk_size) in enumerate(
                                zip(
                                    prepared.chunks,
                                    prepared.embeddings,
                                    chunk_sizes,
                                )
                            )
                        ]

                        if not chunk_values:
                            raise ValueError(
                                f"Crawled page {prepared.url} has no searchable chunks"
                            )
                        insert_chunks_stmt = sa.insert(InfoBlobChunks).values(
                            chunk_values
                        )
                        await session.execute(insert_chunks_stmt)

                        await savepoint.commit()
                        tenant_usage += stored_size
                        user_usage += stored_size
                        success_count += 1
                        successful_urls.append(
                            prepared.url
                        )  # Track this URL as actually persisted

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
        successful_urls = confirmed_unchanged_urls
        success_count = len(confirmed_unchanged_urls)
        for page in prepared_pages:
            add_failure(FailureReason.DB_ERROR, page.url)
        failed_count += len(prepared_pages)

    except Exception as e:
        logger.error(
            f"Phase 2: Session error: {e}",
            extra={
                "website_id": str(ctx.website_id),
                "error": str(e),
            },
        )
        # Mark all unpersisted pages as failed with DB_ERROR
        successful_urls = confirmed_unchanged_urls
        success_count = len(confirmed_unchanged_urls)
        for page in prepared_pages:
            add_failure(FailureReason.DB_ERROR, page.url)
        failed_count += len(prepared_pages)

    return success_count, failed_count, successful_urls, failures_by_reason
