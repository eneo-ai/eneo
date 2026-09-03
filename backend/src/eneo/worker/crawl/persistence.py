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
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import numpy as np
import sqlalchemy as sa
from langchain_text_splitters import RecursiveCharacterTextSplitter
from typing_extensions import NotRequired, TypedDict

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
from eneo.embedding_models.infrastructure.adapters.base import (
    PartialEmbeddingBatchError,
)
from eneo.info_blobs.info_blob import InfoBlobChunk
from eneo.info_blobs.info_blob_repo import InfoBlobRepository
from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.websites.domain.crawl_run import CrawlPhase
from eneo.websites.domain.crawl_run_repo import CrawlRunRepository
from eneo.worker.crawl.heartbeat import CrawlLeaseLostError
from eneo.worker.crawl_context import (
    CrawlContext,
    EmbeddingModelSpec,
    FailureReason,
    Float32Vector,
    PreparedPage,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

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
    title: NotRequired[str]
    content_hash: NotRequired[bytes]
    etag: NotRequired[str | None]
    last_modified: NotRequired[str | None]


@dataclass(frozen=True, slots=True)
class _EmbeddingPagePlan:
    """One changed page and its ordered chunks before provider I/O."""

    page: CrawlPageData
    title: str
    content_hash: bytes
    chunks: list[str]


async def _require_current_publication_lease(
    session: "AsyncSession",
    ctx: CrawlContext,
) -> None:
    current = await CrawlRunRepository(session).lock_attempt_lease(
        ctx.attempt_id,
        lease_owner=ctx.lease_owner,
        expected_phase=CrawlPhase.RUNNING,
    )
    if not current:
        raise CrawlLeaseLostError(
            "Crawl attempt lease was lost before publishing content"
        )


async def _refresh_http_validators(
    *,
    ctx: CrawlContext,
    rows: list[CrawlPageData],
) -> None:
    if not rows:
        return

    from eneo.database.database import sessionmanager

    values = [
        {
            "b_title": row.get("title", row["url"]),
            "b_etag": row.get("etag"),
            "b_last_modified": row.get("last_modified"),
        }
        for row in rows
    ]
    async with sessionmanager.session() as session, session.begin():
        await _require_current_publication_lease(session, ctx)
        # A mapping list on AsyncSession would select ORM bulk-by-primary-key mode.
        connection = await session.connection()
        await connection.execute(
            sa.update(InfoBlobs)
            .where(
                InfoBlobs.website_id == ctx.website_id,
                InfoBlobs.tenant_id == ctx.tenant_id,
                InfoBlobs.title == sa.bindparam("b_title"),
                active_info_blob_version(),
            )
            .values(
                http_etag=sa.bindparam("b_etag"),
                http_last_modified=sa.bindparam("b_last_modified"),
            ),
            values,
        )


async def _publish_prepared_pages(
    *,
    prepared_pages: list[PreparedPage],
    ctx: CrawlContext,
) -> tuple[list[str], dict[str, list[str]]]:
    """Publish one memory-bounded group in a short database transaction."""
    from eneo.database.database import sessionmanager

    successful_identities: list[str] = []
    failures_by_reason: dict[str, list[str]] = {}

    def fail_all() -> None:
        failures_by_reason[FailureReason.DB_ERROR.value] = [
            page.title for page in prepared_pages
        ]

    logger.debug(
        "Phase 2: Persisting batch to database",
        extra={
            "website_id": str(ctx.website_id),
            "pages_to_persist": len(prepared_pages),
            "total_chunks": sum(len(page.chunks) for page in prepared_pages),
        },
    )

    try:
        async with asyncio.timeout(ctx.max_transaction_wall_time_seconds):
            async with sessionmanager.session() as session, session.begin():
                await _require_current_publication_lease(session, ctx)
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
                                    InfoBlobs.embedding_model_id,
                                )
                                .where(
                                    InfoBlobs.title == prepared.title,
                                    InfoBlobs.website_id == prepared.website_id,
                                    InfoBlobs.tenant_id == prepared.tenant_id,
                                    active_info_blob_version(),
                                )
                                .with_for_update()
                            )
                        ).one_or_none()
                        if (
                            existing is not None
                            and existing.content_hash == prepared.content_hash
                            and existing.embedding_model_id
                            == prepared.embedding_model_id
                        ):
                            await session.execute(
                                sa.update(InfoBlobs)
                                .where(
                                    InfoBlobs.id == existing.id,
                                    InfoBlobs.tenant_id == prepared.tenant_id,
                                    active_info_blob_version(),
                                )
                                .values(
                                    http_etag=prepared.http_etag,
                                    http_last_modified=prepared.http_last_modified,
                                )
                            )
                            await savepoint.commit()
                            successful_identities.append(prepared.title)
                            continue

                        chunk_sizes = [
                            len(chunk_text.encode("utf-8")) + embedding.nbytes
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
                                    InfoBlobs.tenant_id == prepared.tenant_id,
                                    active_info_blob_version(),
                                )
                                .values(
                                    version_state=(
                                        InfoBlobVersionState.SUPERSEDED.value
                                    )
                                )
                            )

                        result = await session.execute(
                            sa.insert(InfoBlobs)
                            .values(
                                text=prepared.content,
                                title=prepared.title,
                                url=prepared.url,
                                size=stored_size,
                                content_hash=prepared.content_hash,
                                http_etag=prepared.http_etag,
                                http_last_modified=prepared.http_last_modified,
                                user_id=prepared.user_id,
                                tenant_id=prepared.tenant_id,
                                website_id=prepared.website_id,
                                embedding_model_id=prepared.embedding_model_id,
                                group_id=None,
                                integration_knowledge_id=None,
                                source_id=source_id,
                                version_state=InfoBlobVersionState.ACTIVE.value,
                            )
                            .returning(InfoBlobs.id)
                        )
                        info_blob_id = result.scalar_one()
                        chunk_values = [
                            {
                                "text": chunk_text,
                                "chunk_no": index,
                                "size": chunk_size,
                                "embedding": embedding,
                                "info_blob_id": info_blob_id,
                                "tenant_id": prepared.tenant_id,
                            }
                            for index, (chunk_text, embedding, chunk_size) in enumerate(
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
                        await session.execute(
                            sa.insert(InfoBlobChunks).values(chunk_values)
                        )

                        await savepoint.commit()
                        tenant_usage += stored_size
                        user_usage += stored_size
                        successful_identities.append(prepared.title)
                    except Exception as error:
                        await savepoint.rollback()
                        failures_by_reason.setdefault(
                            FailureReason.DB_ERROR.value, []
                        ).append(prepared.title)
                        logger.error(
                            f"Phase 2: Failed to persist page {prepared.url}: {error}",
                            extra={
                                "website_id": str(ctx.website_id),
                                "tenant_id": str(ctx.tenant_id),
                                "url": prepared.url,
                                "error": str(error),
                            },
                        )

        logger.debug(
            "Phase 2: Batch persist complete",
            extra={
                "website_id": str(ctx.website_id),
                "success_count": len(successful_identities),
                "failed_count": sum(map(len, failures_by_reason.values())),
            },
        )
    except CrawlLeaseLostError:
        raise
    except TimeoutError:
        successful_identities = []
        failures_by_reason = {}
        fail_all()
        logger.error(
            f"Phase 2: Transaction wall-time exceeded ({ctx.max_transaction_wall_time_seconds}s)",
            extra={
                "website_id": str(ctx.website_id),
                "pages_attempted": len(prepared_pages),
            },
        )
    except Exception as error:
        successful_identities = []
        failures_by_reason = {}
        fail_all()
        logger.error(
            f"Phase 2: Session error: {error}",
            extra={
                "website_id": str(ctx.website_id),
                "error": str(error),
            },
        )

    return successful_identities, failures_by_reason


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
    existing_publications: dict[str, tuple[bytes, UUID]] | None = None,
) -> tuple[int, int, list[str], dict[str, list[str]]]:
    """Embed changed pages together and publish complete, memory-bounded groups.

    Chunking and provider I/O happen without a database connection. The model
    adapter owns sequential request batching through max_batch_size. Only pages
    with a complete ordered set of embeddings reach publication. A provider
    failure keeps the previous published versions for the affected page and the
    remaining page-buffer tail so a later crawl can retry them. The embedding
    timeout applies to each provider request; the ARQ job timeout remains the
    aggregate execution bound.
    """
    if not page_buffer:
        return 0, 0, [], {}

    success_count = 0
    failed_count = 0
    successful_identities: list[str] = []
    failures_by_reason: dict[str, list[str]] = {}

    def add_failure(reason: FailureReason, identity: str) -> None:
        failures_by_reason.setdefault(reason.value, []).append(identity)

    if embedding_model is None:
        logger.warning(
            "No embedding model configured for website",
            extra={"website_id": str(ctx.website_id), "batch_size": len(page_buffer)},
        )
        for page in page_buffer:
            add_failure(
                FailureReason.NO_EMBEDDING_MODEL,
                page.get("title", page["url"]),
            )
        return 0, len(page_buffer), [], failures_by_reason

    # Provider data is resolved during the short bootstrap transaction. A
    # fallback here would retain a database connection during provider I/O.
    if (
        embedding_model.provider_id is None
        or not embedding_model.provider_type
        or embedding_model.provider_credentials is None
    ):
        logger.error(
            "Embedding model provider configuration was not resolved",
            extra={
                "website_id": str(ctx.website_id),
                "embedding_model_name": embedding_model.name,
                "embedding_model_id": str(embedding_model.id),
            },
        )
        for page in page_buffer:
            add_failure(
                FailureReason.MISSING_PROVIDER,
                page.get("title", page["url"]),
            )
        return 0, len(page_buffer), [], failures_by_reason

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_CHUNK_OVERLAP,
        length_function=count_tokens,
    )
    plans: list[_EmbeddingPagePlan] = []
    validator_refreshes: list[CrawlPageData] = []

    logger.debug(
        "Planning page embeddings",
        extra={
            "website_id": str(ctx.website_id),
            "batch_size": len(page_buffer),
            "embedding_model": ctx.embedding_model_name,
        },
    )

    for page in page_buffer:
        url = page["url"]
        title = page.get("title", url)
        content = page["content"]

        if not content.strip():
            logger.warning(
                "Skipping page without searchable content",
                extra={
                    "website_id": str(ctx.website_id),
                    "url": url,
                    "reason": FailureReason.EMPTY_CONTENT.value,
                    "content_length": len(content),
                },
            )
            failed_count += 1
            add_failure(FailureReason.EMPTY_CONTENT, title)
            continue

        try:
            content_hash = (
                page.get("content_hash")
                or hashlib.sha256(content.encode("utf-8")).digest()
            )
            if (existing_publications or {}).get(title) == (
                content_hash,
                embedding_model.id,
            ):
                success_count += 1
                successful_identities.append(title)
                if (
                    page.get("etag") is not None
                    or page.get("last_modified") is not None
                ):
                    validator_refreshes.append(page)
                continue

            raw_chunks = splitter.split_text(content)
            chunks = [chunk.strip() for chunk in raw_chunks if chunk.strip()]
            if not chunks:
                logger.warning(
                    "Skipping page without searchable chunks",
                    extra={
                        "website_id": str(ctx.website_id),
                        "url": url,
                        "reason": FailureReason.NO_CHUNKS.value,
                        "content_length": len(content),
                        "raw_chunks_count": len(raw_chunks),
                    },
                )
                failed_count += 1
                add_failure(FailureReason.NO_CHUNKS, title)
                continue

            plans.append(
                _EmbeddingPagePlan(
                    page=page,
                    title=title,
                    content_hash=content_hash,
                    chunks=chunks,
                )
            )
        except Exception as error:
            logger.error(
                "Failed to prepare page text for embeddings",
                extra={
                    "website_id": str(ctx.website_id),
                    "tenant_id": str(ctx.tenant_id),
                    "url": url,
                    "error_type": type(error).__name__,
                },
            )
            failed_count += 1
            add_failure(FailureReason.EMBEDDING_ERROR, title)

    await _refresh_http_validators(ctx=ctx, rows=validator_refreshes)
    if not plans:
        log = logger.debug if successful_identities else logger.warning
        log(
            "No pages require embedding or publication",
            extra={
                "website_id": str(ctx.website_id),
                "unchanged_count": len(successful_identities),
                "failed_count": failed_count,
            },
        )
        return (
            success_count,
            failed_count,
            successful_identities,
            failures_by_reason,
        )

    try:
        embedding_service = container.create_embeddings_service(
            request_semaphore=_get_embedding_semaphore(),
            request_timeout_seconds=ctx.embedding_timeout_seconds,
        )
    except Exception as error:
        logger.error(
            "Failed to initialize embedding service",
            extra={
                "website_id": str(ctx.website_id),
                "error_type": type(error).__name__,
            },
        )
        for plan in plans:
            add_failure(FailureReason.EMBEDDING_ERROR, plan.title)
        return (
            success_count,
            failed_count + len(plans),
            successful_identities,
            failures_by_reason,
        )

    chunks_to_embed = [
        InfoBlobChunk(
            chunk_no=chunk_number,
            text=chunk_text,
            info_blob_id=ctx.website_id,
            tenant_id=ctx.tenant_id,
        )
        for plan in plans
        for chunk_number, chunk_text in enumerate(plan.chunks)
    ]

    provider_failure: Exception | None = None
    completed_count: int | None = None
    try:
        embedding_results = await embedding_service.get_embeddings(
            model=embedding_model,
            chunks=chunks_to_embed,
        )
    except PartialEmbeddingBatchError as error:
        embedding_results = error.completed
        provider_failure = error.cause
        completed_count = error.completed_count
        logger.warning(
            "Embedding provider stopped after a complete chunk prefix",
            extra={
                "website_id": str(ctx.website_id),
                "completed_chunks": error.completed_count,
                "total_chunks": len(chunks_to_embed),
                "error_type": type(error.cause).__name__,
            },
        )
    except Exception as error:
        logger.error(
            "Embedding provider failed before returning a complete prefix",
            extra={
                "website_id": str(ctx.website_id),
                "total_chunks": len(chunks_to_embed),
                "error_type": type(error).__name__,
            },
        )
        for plan in plans:
            add_failure(FailureReason.EMBEDDING_ERROR, plan.title)
        return (
            success_count,
            failed_count + len(plans),
            successful_identities,
            failures_by_reason,
        )

    prepared_pages: list[PreparedPage] = []
    prepared_embedding_bytes = 0

    async def flush_prepared_pages() -> tuple[int, int]:
        nonlocal prepared_embedding_bytes
        if not prepared_pages:
            return 0, 0

        published, publication_failures = await _publish_prepared_pages(
            prepared_pages=prepared_pages,
            ctx=ctx,
        )
        publication_failed_count: int = 0
        for identities in publication_failures.values():
            publication_failed_count += len(identities)
        successful_identities.extend(published)
        for reason, identities in publication_failures.items():
            failures_by_reason.setdefault(reason, []).extend(identities)
        prepared_pages.clear()
        prepared_embedding_bytes = 0
        return len(published), publication_failed_count

    result_iterator = iter(embedding_results)
    next_chunk_index = 0
    incomplete_plan_index: int | None = None

    for plan_index, plan in enumerate(plans):
        page_embeddings: list[Float32Vector] = []
        for _ in plan.chunks:
            try:
                returned_chunk, embedding = next(result_iterator)
                expected_chunk = chunks_to_embed[next_chunk_index]
                if returned_chunk is not expected_chunk:
                    raise ValueError("Embedding results were returned out of order")
                next_chunk_index += 1
                page_embeddings.append(np.asarray(embedding, dtype=np.float32))
            except StopIteration:
                incomplete_plan_index = plan_index
                break
            except Exception as error:
                provider_failure = provider_failure or error
                incomplete_plan_index = plan_index
                logger.error(
                    "Embedding result stream could not be read",
                    extra={
                        "website_id": str(ctx.website_id),
                        "completed_chunks": next_chunk_index,
                        "total_chunks": len(chunks_to_embed),
                        "error_type": type(error).__name__,
                    },
                )
                break

        if incomplete_plan_index is not None:
            break

        page = plan.page
        prepared_page = PreparedPage(
            url=page["url"],
            title=plan.title,
            content=page["content"],
            content_hash=plan.content_hash,
            http_etag=page.get("etag"),
            http_last_modified=page.get("last_modified"),
            chunks=plan.chunks,
            embeddings=page_embeddings,
            tenant_id=ctx.tenant_id,
            website_id=ctx.website_id,
            user_id=ctx.user_id,
            embedding_model_id=embedding_model.id,
        )
        prepared_pages.append(prepared_page)
        prepared_embedding_bytes += sum(
            embedding.nbytes for embedding in page_embeddings
        )

        # The bound is checked after a complete page so partial pages are never
        # published. Overshoot is limited to one page, matching the prior guard.
        if prepared_embedding_bytes >= ctx.max_batch_embedding_bytes:
            logger.info(
                "Embedding memory cap reached; publishing complete pages",
                extra={
                    "website_id": str(ctx.website_id),
                    "pages_prepared": len(prepared_pages),
                    "embedding_bytes": prepared_embedding_bytes,
                },
            )
            published_count, publication_failed_count = await flush_prepared_pages()
            success_count += published_count
            failed_count += publication_failed_count

    # Advance once after an exact successful result set so ChunkEmbeddingList
    # closes its temporary spool at StopIteration.
    if incomplete_plan_index is None:
        try:
            next(result_iterator)
        except StopIteration:
            pass

    published_count, publication_failed_count = await flush_prepared_pages()
    success_count += published_count
    failed_count += publication_failed_count

    if incomplete_plan_index is not None:
        failure_reason = (
            FailureReason.EMBEDDING_TIMEOUT
            if isinstance(provider_failure, TimeoutError)
            else FailureReason.EMBEDDING_ERROR
        )
        failed_plans = plans[incomplete_plan_index:]
        for plan in failed_plans:
            add_failure(failure_reason, plan.title)
        failed_count += len(failed_plans)

        logger.warning(
            "Pages after the completed embedding prefix were not published",
            extra={
                "website_id": str(ctx.website_id),
                "completed_chunks": completed_count or next_chunk_index,
                "total_chunks": len(chunks_to_embed),
                "failed_pages": len(failed_plans),
                "failure_reason": failure_reason.value,
            },
        )

    return success_count, failed_count, successful_identities, failures_by_reason
