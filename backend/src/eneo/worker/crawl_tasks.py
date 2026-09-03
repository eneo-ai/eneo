import asyncio
import contextlib
import hashlib
import os
import secrets
import socket
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Generic, Protocol, TypeVar, cast
from uuid import UUID

import sqlalchemy as sa
from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.crawler.engine import (
    ConditionalGet,
    CrawlFinished,
    CrawlLimits,
    CrawlRequest,
    FileDownloaded,
    FileFailed,
    PageCrawled,
    PageFailed,
    PageUnchanged,
)
from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.logging import get_logger
from eneo.main.observability import redact_url_query
from eneo.model_providers.infrastructure.litellm_provider import (
    ResolvedLiteLLMProvider,
    load_active_litellm_provider,
)
from eneo.tenants.crawler_settings_helper import get_crawler_setting
from eneo.websites.crawl_dependencies.crawl_models import CrawlTask
from eneo.websites.domain.crawl_run import (
    CrawlFailureCode,
    CrawlOrigin,
    CrawlOutcome,
    CrawlPhase,
    CrawlType,
)
from eneo.worker.crawl import (
    CrawlLeaseLostError,
    HeartbeatFailedError,
    HeartbeatMonitor,
    SessionHolder,
    execute_with_recovery,
    persist_batch,
)
from eneo.worker.crawl.persistence import CrawlPageData
from eneo.worker.crawl_context import CrawlContext, EmbeddingModelSpec

logger = get_logger(__name__)

QueueItem = TypeVar("QueueItem")


class _ProviderLoader(Protocol):
    async def __call__(
        self,
        *,
        session: AsyncSession,
        provider_id: UUID,
        tenant_id: UUID,
    ) -> ResolvedLiteLLMProvider: ...


async def _build_embedding_model_spec(
    *,
    session: AsyncSession,
    embedding_model: EmbeddingModels,
    tenant_id: UUID,
    load_provider: _ProviderLoader = load_active_litellm_provider,
) -> EmbeddingModelSpec:
    provider: ResolvedLiteLLMProvider | None = None
    if embedding_model.provider_id is not None:
        provider = await load_provider(
            session=session,
            provider_id=embedding_model.provider_id,
            tenant_id=tenant_id,
        )

    max_input = embedding_model.max_input
    if max_input is None:
        raise ValueError("The crawl embedding model has no input limit")

    return EmbeddingModelSpec(
        id=embedding_model.id,
        name=embedding_model.name,
        litellm_model_name=(
            f"{provider.provider_type}/{embedding_model.name}"
            if provider is not None
            else embedding_model.litellm_model_name
        ),
        family=embedding_model.family or None,
        max_input=max_input,
        max_batch_size=embedding_model.max_batch_size,
        dimensions=embedding_model.dimensions,
        open_source=embedding_model.open_source,
        provider_id=embedding_model.provider_id,
        provider_type=provider.provider_type if provider is not None else None,
        provider_credentials=provider.credentials if provider is not None else None,
        provider_config=provider.config if provider is not None else None,
    )


class _QueueClosed:
    __slots__ = ()


_QUEUE_CLOSED = _QueueClosed()


class _ByteBoundedQueue(Generic[QueueItem]):
    """Async queue bounded by both event count and retained content bytes."""

    def __init__(self, *, max_items: int, max_bytes: int) -> None:
        if max_items <= 0 or max_bytes <= 0:
            raise ValueError("queue limits must be positive")
        self._max_items = max_items
        self._max_bytes = max_bytes
        self._items: deque[tuple[QueueItem, int]] = deque()
        self._retained_bytes = 0
        self._closed = False
        self._condition = asyncio.Condition()

    async def put(self, item: QueueItem, *, weight: int = 0) -> None:
        if weight < 0:
            raise ValueError("queue item weight cannot be negative")
        async with self._condition:
            await self._condition.wait_for(
                lambda: self._closed
                or (
                    len(self._items) < self._max_items
                    and (
                        not self._items
                        or self._retained_bytes + weight <= self._max_bytes
                    )
                )
            )
            if self._closed:
                raise RuntimeError("Cannot add events to a closed crawl stream")
            self._items.append((item, weight))
            self._retained_bytes += weight
            self._condition.notify_all()

    async def get(self) -> QueueItem | _QueueClosed:
        async with self._condition:
            await self._condition.wait_for(lambda: bool(self._items) or self._closed)
            if not self._items:
                return _QUEUE_CLOSED
            item, weight = self._items.popleft()
            self._retained_bytes -= weight
            self._condition.notify_all()
            return item

    async def close(self) -> None:
        """Wake the consumer without waiting for capacity in the data buffer."""
        async with self._condition:
            self._closed = True
            self._condition.notify_all()


def _classify_crawl_outcome(
    *,
    published_pages: int,
    unchanged_pages: int,
    published_files: int,
    unchanged_files: int,
    failed_pages: int,
    failed_files: int,
    partial: bool,
) -> CrawlOutcome:
    useful_items = published_pages + unchanged_pages + published_files + unchanged_files
    failed_items = failed_pages + failed_files
    if useful_items == 0:
        return (
            CrawlOutcome.FAILED if failed_items > 0 or partial else CrawlOutcome.EMPTY
        )
    if failed_items > 0 or partial:
        return CrawlOutcome.PARTIAL
    if published_pages == 0 and published_files == 0:
        return CrawlOutcome.UNCHANGED
    return CrawlOutcome.SUCCEEDED


def _crawl_has_usable_result(outcome: CrawlOutcome) -> bool:
    return outcome in {
        CrawlOutcome.SUCCEEDED,
        CrawlOutcome.UNCHANGED,
        CrawlOutcome.EMPTY,
        CrawlOutcome.PARTIAL,
    }


def _crawl_counts_as_scheduled_run(
    outcome: CrawlOutcome,
    *,
    useful_items: int,
    failed_items: int,
) -> bool:
    if outcome in {
        CrawlOutcome.SUCCEEDED,
        CrawlOutcome.UNCHANGED,
        CrawlOutcome.EMPTY,
    }:
        return True
    return outcome == CrawlOutcome.PARTIAL and useful_items > failed_items


def _failure_code_for_crawl(
    failure_counts: dict[str, int],
    termination_reason: str,
) -> CrawlFailureCode:
    reasons = {reason.lower() for reason in failure_counts}
    reasons.add(termination_reason.lower())
    if any(
        reason == "robots_disallowed"
        or reason.startswith(
            ("http_401", "http_403", "http_407", "http_429", "http_451")
        )
        for reason in reasons
    ):
        return CrawlFailureCode.REMOTE_BLOCKED
    if any("timeout" in reason for reason in reasons):
        return CrawlFailureCode.TIMED_OUT
    if any(
        marker in reason
        for reason in reasons
        for marker in ("connector", "connection", "dns", "ssl", "certificate")
    ):
        return CrawlFailureCode.REMOTE_UNREACHABLE
    return CrawlFailureCode.PROCESSING_FAILED


def _failure_detail(code: CrawlFailureCode, outcome: CrawlOutcome) -> str:
    if outcome == CrawlOutcome.PARTIAL:
        return {
            CrawlFailureCode.REMOTE_BLOCKED: (
                "The crawl finished with partial results because some resources "
                "blocked the crawler"
            ),
            CrawlFailureCode.REMOTE_UNREACHABLE: (
                "The crawl finished with partial results because some resources "
                "could not be reached"
            ),
            CrawlFailureCode.TIMED_OUT: (
                "The crawl finished with partial results after reaching a time limit"
            ),
            CrawlFailureCode.PROCESSING_FAILED: (
                "The crawl finished with partial results because some resources "
                "could not be processed"
            ),
        }[code]
    return {
        CrawlFailureCode.REMOTE_BLOCKED: "The website blocked the crawler",
        CrawlFailureCode.REMOTE_UNREACHABLE: "The website could not be reached",
        CrawlFailureCode.TIMED_OUT: "The website did not respond within the crawl limit",
        CrawlFailureCode.PROCESSING_FAILED: "The crawl produced no usable content",
    }[code]


def _should_store_sitemap_state(
    *,
    has_new_state: bool,
    crawl_is_partial: bool,
    outcome: CrawlOutcome,
    total_failed: int,
) -> bool:
    return (
        has_new_state
        and not crawl_is_partial
        and outcome
        in {
            CrawlOutcome.SUCCEEDED,
            CrawlOutcome.UNCHANGED,
            CrawlOutcome.EMPTY,
        }
        and total_failed == 0
    )


async def queue_website_crawls(container: Container):
    """Persist due crawls in short transactions, then reconcile one batch."""
    from eneo.database.database import sessionmanager

    async with sessionmanager.session() as query_session, query_session.begin():
        crawl_scheduler_service = container.crawl_scheduler_service()
        crawl_scheduler_service.website_sparse_repo.session = query_session
        websites = await crawl_scheduler_service.get_websites_due_for_crawl()

    logger.info(
        "Admitting websites due for crawling",
        extra={"website_count": len(websites)},
    )
    admitted = 0
    failed = 0
    for website in websites:
        try:
            async with (
                sessionmanager.session() as website_session,
                website_session.begin(),
            ):
                user_repo = container.user_repo()
                user_repo.session = website_session
                user = await user_repo.get_user_by_id(website.user_id)
                assert user is not None
                website_container = Container(
                    session=providers.Object(website_session),
                    user=providers.Object(user),
                    tenant=providers.Object(user.tenant),
                )

                from eneo.websites.domain.website import Website

                await website_container.crawl_service().crawl(
                    cast(Website, website),
                    origin=CrawlOrigin.SCHEDULED,
                    reconcile_after_commit=False,
                )
            admitted += 1
        except Exception:
            failed += 1
            logger.exception(
                "Failed to admit scheduled crawl",
                extra={
                    "website_id": str(website.id),
                    "tenant_id": str(website.tenant_id),
                    "space_id": str(website.space_id),
                    "user_id": str(website.user_id),
                },
            )

    from eneo.websites.application.crawl_dispatch import reconcile_crawl_work

    await reconcile_crawl_work()
    logger.info(
        "Scheduled crawl admission completed",
        extra={"admitted": admitted, "failed": failed},
    )
    return failed == 0


async def crawl_task(*, job_id: UUID, params: CrawlTask, container: Container):
    from eneo.database.database import sessionmanager
    from eneo.websites.domain.crawl_run_repo import CrawlRunRepository

    job_id = UUID(str(job_id))
    if params.attempt_id is None or params.attempt_number is None:
        raise ValueError("Crawl execution requires a persisted attempt identity")

    attempt_id = params.attempt_id
    settings = get_settings()
    heartbeat_interval_seconds = settings.crawl_heartbeat_interval_seconds
    lease_duration = timedelta(
        seconds=max(
            heartbeat_interval_seconds * (settings.crawl_heartbeat_max_failures + 1),
            120,
        )
    )
    lease_owner = f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(16)}"
    created_sessions: list[AsyncSession] = []
    session_holder: SessionHolder = {"session": None, "uploader": None}
    terminalized = False
    heartbeat_stop: asyncio.Event | None = None
    heartbeat_task: asyncio.Task[None] | None = None

    async def _stop_heartbeat(*, propagate_failure: bool = False) -> None:
        if heartbeat_stop is not None:
            heartbeat_stop.set()
        if heartbeat_task is None:
            return
        if not heartbeat_task.done():
            heartbeat_task.cancel()
        result = (await asyncio.gather(heartbeat_task, return_exceptions=True))[0]
        if (
            propagate_failure
            and isinstance(result, BaseException)
            and not isinstance(result, asyncio.CancelledError)
        ):
            raise result

    try:
        async with sessionmanager.session() as claim_session, claim_session.begin():
            claimed_task = await CrawlRunRepository(claim_session).claim_attempt(
                attempt_id,
                dispatch_id=job_id,
                lease_owner=lease_owner,
                lease_duration=lease_duration,
            )
    except ValueError:
        # The failed claim transaction must roll back before terminalizing the
        # invalid durable payload, otherwise the rejection is rolled back too.
        async with sessionmanager.session() as reject_session, reject_session.begin():
            await CrawlRunRepository(reject_session).reject_pending_attempt(
                attempt_id,
                failure_code=CrawlFailureCode.INVALID_DISPATCH,
                failure_detail="Stored crawl execution data is invalid",
            )
        raise

    if claimed_task is None:
        logger.warning(
            "Ignoring crawl delivery because its attempt is no longer claimable",
            extra={
                "job_id": str(job_id),
                "attempt_id": str(attempt_id),
                "run_id": str(params.run_id),
            },
        )
        return {"status": "stale_delivery", "job_id": str(job_id)}

    # The durable attempt payload is the execution identity. The Redis payload
    # only identifies which attempt delivery arrived and is never trusted for
    # user, tenant, website, or crawl configuration.
    params = claimed_task

    async def _finish_attempt(
        outcome: CrawlOutcome,
        *,
        failure_code: CrawlFailureCode | None = None,
        failure_detail: str | None = None,
        result_location: str | None = None,
        pages_crawled: int | None = None,
        files_downloaded: int | None = None,
        pages_failed: int | None = None,
        files_failed: int | None = None,
        failure_summary: dict[str, int] | None = None,
    ) -> bool:
        nonlocal terminalized
        if terminalized:
            return True
        async with sessionmanager.session() as finish_session, finish_session.begin():
            finished = await CrawlRunRepository(finish_session).finish_attempt(
                attempt_id,
                lease_owner=lease_owner,
                outcome=outcome,
                failure_code=failure_code,
                failure_detail=failure_detail,
                result_location=result_location,
                pages_crawled=pages_crawled,
                files_downloaded=files_downloaded,
                pages_failed=pages_failed,
                files_failed=files_failed,
                failure_summary=failure_summary,
            )
        terminalized = finished
        return finished

    async def _require_current_lease(
        session: AsyncSession,
        *,
        expected_phase: CrawlPhase,
    ) -> None:
        current = await CrawlRunRepository(session).lock_attempt_lease(
            attempt_id,
            lease_owner=lease_owner,
            expected_phase=expected_phase,
        )
        if not current:
            raise CrawlLeaseLostError(
                "Crawl attempt lease was lost before a database mutation"
            )

    num_pages = 0
    num_published_pages = 0
    num_not_modified_pages = 0
    num_files = 0
    num_published_files = 0
    num_failed_pages = 0
    num_failed_files = 0
    num_deleted_blobs = 0
    num_skipped_files = 0
    failure_counts: dict[str, int] = defaultdict(int)

    try:
        async with Container.session_scope():
            user = await container.user_repo().get_user_by_id(params.user_id)
        if user is None:
            raise ValueError("The crawl attempt user no longer exists")

        from eneo.main.container.container_overrides import override_user

        override_user(container=container, user=user)
        tenant = container.tenant()
        tenant_crawler_settings = tenant.crawler_settings
        item_limit = get_crawler_setting(
            "closespider_itemcount", tenant_crawler_settings
        )
        heartbeat_interval_seconds = get_crawler_setting(
            "crawl_heartbeat_interval_seconds",
            tenant_crawler_settings,
        )
        lease_duration = timedelta(
            seconds=max(
                heartbeat_interval_seconds
                * (settings.crawl_heartbeat_max_failures + 1),
                120,
            )
        )
        async with contextlib.AsyncExitStack():
            # Initialize timing tracking for performance analysis
            timings = {
                "fetch_existing_titles": 0.0,
                "crawl_and_parse": 0.0,
                "process_pages": 0.0,
                "process_files": 0.0,
                "cleanup_deleted": 0.0,
                "update_size": 0.0,
            }

            # Resolve the execution engine. File extraction is initialized only
            # when a downloaded file is actually processed.
            crawler = container.crawler()

            # Initialize session holder for recovery support
            # NOTE: Starts with None - sessions are created on-demand by execute_with_recovery
            # This is the "sessionless container" pattern for long-running tasks
            # Each DB operation creates its own short-lived session (~50-300ms)
            session_holder["session"] = None

            # BOOTSTRAP PHASE: Short-lived session for initial queries (~50-100ms)
            # Extract all needed data as primitives BEFORE the long crawl so the
            # session returns to pool immediately. This prevents holding a connection
            # for 5-30 minutes during the actual crawl operation.
            from eneo.database.database import sessionmanager
            from eneo.database.tables.info_blobs_table import (
                InfoBlobs,
                active_info_blob_version,
            )
            from eneo.database.tables.websites_table import Websites as WebsitesTable

            # These will be populated by bootstrap
            crawl_context: CrawlContext
            existing_titles: list[str] = []
            existing_publications: dict[str, tuple[bytes, UUID]] = {}
            existing_validators: dict[str, tuple[str | None, str | None]] = {}
            conditional_gets_truncated = False
            website_url: str = ""  # For logging after session closes

            start = time.time()
            # Bootstrap phase: Short-lived session for extracting ORM → DTO
            # All data is converted to EmbeddingModelSpec/CrawlContext DTOs before session closes,
            # preventing DetachedInstanceError when embedding APIs are called later.
            bootstrap_session = sessionmanager.create_session()
            try:
                await bootstrap_session.begin()
                # Get website with eager loading of embedding_model
                from sqlalchemy.orm import selectinload

                from eneo.database.tables.websites_table import Websites

                current_tenant = container.tenant()
                website_stmt = (
                    sa.select(Websites)
                    .where(
                        Websites.id == params.website_id,
                        Websites.tenant_id == current_tenant.id,
                    )
                    .options(selectinload(Websites.embedding_model))
                )
                result = await bootstrap_session.execute(website_stmt)
                website_row = result.scalar_one_or_none()

                if website_row is None:
                    raise Exception(f"Website {params.website_id} not found")

                website = website_row
                website_url = website_row.url  # Save for logging after session closes

                # Extract HTTP auth credentials if present
                # NOTE: Using ORM columns directly (http_auth_username, encrypted_auth_password)
                # because we're working with the raw Websites table, not the domain model
                http_user: str | None = None
                http_pass: str | None = None
                has_auth_in_db = bool(
                    website_row.http_auth_username
                    and website_row.encrypted_auth_password
                )

                if has_auth_in_db:
                    # Decrypt the password using HttpAuthEncryptionService (NOT encryption_service)
                    # HttpAuthEncryptionService uses its own Fernet encryption format
                    # while encryption_service expects 'enc:' prefix format
                    try:
                        http_auth_encryption = container.http_auth_encryption_service()
                        http_user = website_row.http_auth_username
                        encrypted_auth_password = website_row.encrypted_auth_password
                        assert encrypted_auth_password is not None
                        http_pass = http_auth_encryption.decrypt_password(
                            encrypted_auth_password
                        )
                        logger.info(
                            "HTTP auth configured for website",
                            extra={
                                "website_id": str(params.website_id),
                                "tenant_id": str(website_row.tenant_id),
                            },
                        )
                    except Exception as decrypt_err:
                        logger.error(
                            "Cannot crawl website: HTTP auth decryption failed. "
                            "Check encryption_key setting is correct.",
                            extra={
                                "website_id": str(params.website_id),
                                "tenant_id": str(website_row.tenant_id),
                                "error": str(decrypt_err),
                            },
                        )
                        raise Exception(
                            f"HTTP auth decryption failed for website {params.website_id}. "
                            "Check encryption_key configuration."
                        )

                # Extract embedding model into EmbeddingModelSpec DTO
                # This extracts ALL primitives from ORM while session is active,
                # preventing DetachedInstanceError when session closes.
                # Provider credentials are pre-resolved here so that embedding
                # calls in Phase 1 (sessionless) don't need a DB lookup.
                orm_embedding_model = website_row.embedding_model
                embedding_model_spec: EmbeddingModelSpec | None = None
                if orm_embedding_model:
                    embedding_model_spec = await _build_embedding_model_spec(
                        session=bootstrap_session,
                        embedding_model=orm_embedding_model,
                        tenant_id=current_tenant.id,
                    )

                # Build CrawlContext DTO from ORM objects
                # Extract ALL fields as primitives to avoid DetachedInstanceError
                crawl_context = CrawlContext(
                    website_id=website.id,
                    tenant_id=website.tenant_id,
                    tenant_slug=tenant.slug if tenant else None,
                    user_id=container.user().id,
                    attempt_id=attempt_id,
                    lease_owner=lease_owner,
                    # Embedding model - use EmbeddingModelSpec DTO (already extracted)
                    embedding_model_id=embedding_model_spec.id
                    if embedding_model_spec
                    else None,
                    embedding_model_name=embedding_model_spec.name
                    if embedding_model_spec
                    else None,
                    embedding_model_open_source=embedding_model_spec.open_source
                    if embedding_model_spec
                    else False,
                    embedding_model_family=(
                        embedding_model_spec.family
                        if embedding_model_spec and embedding_model_spec.family
                        else None
                    ),
                    embedding_model_dimensions=(
                        embedding_model_spec.dimensions
                        if embedding_model_spec
                        else None
                    ),
                    # HTTP Auth - primitives only
                    http_auth_user=http_user,
                    http_auth_pass=http_pass,
                    # Batch settings from tenant config with defaults
                    batch_size=get_crawler_setting(
                        "crawl_page_batch_size",
                        tenant.crawler_settings if tenant else None,
                    ),
                )

                # Fetch existing titles for stale detection and file hashes for skip optimization
                # A 304 page carries no file links, so file crawls must re-observe
                # HTML before stale content can be removed.
                reuse_page_validators = not params.download_files
                stmt = (
                    sa.select(
                        InfoBlobs.title,
                        InfoBlobs.content_hash,
                        InfoBlobs.embedding_model_id,
                        InfoBlobs.http_etag,
                        InfoBlobs.http_last_modified,
                    )
                    .where(
                        InfoBlobs.website_id == params.website_id,
                        InfoBlobs.tenant_id == current_tenant.id,
                        active_info_blob_version(),
                    )
                    .order_by(InfoBlobs.id.asc())
                )
                blob_result = await bootstrap_session.execute(stmt)

                # Build lookups for O(1) operations
                for title, hash_bytes, model_id, etag, last_modified in blob_result:
                    if title is None:
                        continue
                    existing_titles.append(title)
                    if hash_bytes is not None and model_id is not None:
                        existing_publications[title] = (hash_bytes, model_id)
                    if reuse_page_validators and (
                        etag is not None or last_modified is not None
                    ):
                        if (
                            title in existing_validators
                            or len(existing_validators) < item_limit
                        ):
                            existing_validators[title] = (etag, last_modified)
                        else:
                            conditional_gets_truncated = True

            finally:
                # Always close the bootstrap session to return connection to pool
                await bootstrap_session.close()

            # Session returned to pool HERE - bootstrap complete (~50-100ms)
            timings["fetch_existing_titles"] = time.time() - start

            logger.info(
                "Bootstrap phase complete - session returned to pool",
                extra={
                    "website_id": str(params.website_id),
                    "tenant_id": str(crawl_context.tenant_id),
                    "batch_size": crawl_context.batch_size,
                    "embedding_model": crawl_context.embedding_model_name,
                    "existing_titles_count": len(existing_titles),
                    "bootstrap_duration_ms": int(
                        timings["fetch_existing_titles"] * 1000
                    ),
                },
            )

            logger.info(
                "Starting crawl execution",
                extra={
                    "run_id": str(params.run_id),
                    "attempt_id": str(params.attempt_id),
                    "website_id": str(params.website_id),
                    "url": redact_url_query(params.url),
                    "crawl_type": params.crawl_type.value,
                    "download_files": params.download_files,
                    "origin": params.origin.value,
                },
            )

            # Use set for O(1) membership tests
            crawled_titles: set[str] = set()
            failed_titles: set[str] = set()  # Failed URLs excluded from stale deletion

            current_tenant = container.tenant()

            async def _renew_lease() -> bool:
                async with (
                    sessionmanager.session() as heartbeat_session,
                    heartbeat_session.begin(),
                ):
                    return await CrawlRunRepository(
                        heartbeat_session
                    ).renew_attempt_lease(
                        attempt_id,
                        lease_owner=lease_owner,
                        lease_duration=lease_duration,
                        pages_crawled=num_published_pages,
                        files_downloaded=num_published_files,
                        pages_failed=num_failed_pages,
                        files_failed=num_failed_files,
                    )

            heartbeat_monitor = HeartbeatMonitor(
                renew_lease=_renew_lease,
                interval_seconds=heartbeat_interval_seconds,
                max_failures=settings.crawl_heartbeat_max_failures,
            )

            crawl_request = CrawlRequest(
                url=params.url,
                crawl_type=params.crawl_type,
                download_files=params.download_files,
                obey_robots=get_crawler_setting("obey_robots", tenant_crawler_settings),
                http_user=crawl_context.http_auth_user,
                http_pass=crawl_context.http_auth_pass,
                conditional_gets=tuple(
                    ConditionalGet(
                        url=url,
                        etag=validators[0],
                        last_modified=validators[1],
                    )
                    for url, validators in existing_validators.items()
                ),
                conditional_gets_truncated=conditional_gets_truncated,
                limits=CrawlLimits(
                    max_items=item_limit,
                    max_seconds=get_crawler_setting(
                        "crawl_max_length", tenant_crawler_settings
                    ),
                    request_timeout_seconds=get_crawler_setting(
                        "download_timeout", tenant_crawler_settings
                    ),
                    max_response_bytes=settings.crawl_page_max_size,
                    max_file_bytes=get_crawler_setting(
                        "download_max_size", tenant_crawler_settings
                    ),
                    dns_timeout_seconds=get_crawler_setting(
                        "dns_timeout", tenant_crawler_settings
                    ),
                    concurrency=settings.crawl_fetch_concurrency,
                    request_delay_seconds=max(
                        settings.crawl_request_delay_seconds,
                        0.1
                        if get_crawler_setting(
                            "autothrottle_enabled", tenant_crawler_settings
                        )
                        else 0.0,
                    ),
                    retries=get_crawler_setting("retry_times", tenant_crawler_settings),
                ),
            )

            crawl_is_partial = False
            crawl_termination_reason = "completed"
            new_sitemap_state: dict[str, Any] | None = None

            # Session-per-batch page processing: persist_batch opens a fresh,
            # short-lived persistence session for each flushed batch. The
            # bootstrap session has already been returned to the pool above.
            page_buffer: list[CrawlPageData] = []
            page_buffer_bytes = 0
            processing_page_seconds = 0.0
            processing_file_seconds = 0.0

            async def _flush_pages() -> None:
                nonlocal num_failed_pages, num_published_pages
                nonlocal page_buffer_bytes, processing_page_seconds
                if not page_buffer:
                    return
                batch = list(page_buffer)
                page_buffer.clear()
                page_buffer_bytes = 0
                flush_started = time.time()
                (
                    success_count,
                    failed_count,
                    successful_titles,
                    batch_failures_by_reason,
                ) = await persist_batch(
                    page_buffer=batch,
                    ctx=crawl_context,
                    embedding_model=embedding_model_spec,
                    container=container,
                    existing_publications=existing_publications,
                )
                processing_page_seconds += time.time() - flush_started
                num_published_pages += success_count
                crawled_titles.update(successful_titles)
                for reason, titles in batch_failures_by_reason.items():
                    failure_counts[reason] += len(titles)
                    failed_titles.update(titles)
                num_failed_pages += failed_count
                logger.debug(
                    "Flushed crawled page batch",
                    extra={
                        "job_id": str(job_id),
                        "batch_size": len(batch),
                        "success": success_count,
                        "failed": failed_count,
                        "total_pages": num_pages,
                    },
                )

            async def _process_file(event: FileDownloaded) -> None:
                nonlocal num_files, num_published_files
                nonlocal num_failed_files, num_skipped_files
                nonlocal processing_file_seconds
                file_started = time.time()
                num_files += 1
                filename = event.path.stem
                try:
                    extracted_text = await asyncio.to_thread(
                        container.text_extractor().extract,
                        event.path,
                        None,
                        event.path.name,
                    )
                    new_file_hash = hashlib.sha256(
                        extracted_text.encode("utf-8")
                    ).digest()
                    existing_file = existing_publications.get(filename)
                    if embedding_model_spec is not None and existing_file == (
                        new_file_hash,
                        embedding_model_spec.id,
                    ):
                        num_skipped_files += 1
                        crawled_titles.add(filename)
                        return

                    (
                        success_count,
                        failed_count,
                        successful_titles,
                        file_failures,
                    ) = await persist_batch(
                        page_buffer=[
                            {
                                "url": event.url,
                                "title": filename,
                                "content": extracted_text,
                                "content_hash": new_file_hash,
                            }
                        ],
                        ctx=crawl_context,
                        embedding_model=embedding_model_spec,
                        container=container,
                        existing_publications=existing_publications,
                    )
                    num_published_files += success_count
                    if success_count:
                        crawled_titles.update(successful_titles)
                    if failed_count:
                        num_failed_files += failed_count
                        for reason, titles in file_failures.items():
                            failure_counts[reason] += len(titles)
                            failed_titles.update(titles)
                except CrawlLeaseLostError:
                    raise
                except Exception:
                    failed_titles.add(filename)
                    num_failed_files += 1
                    logger.exception(
                        "Exception while uploading crawled file",
                        extra={
                            "website_id": str(params.website_id),
                            "tenant_id": str(crawl_context.tenant_id),
                            "file_url": event.url,
                            "filename": filename,
                        },
                    )
                finally:
                    processing_file_seconds += time.time() - file_started

            queue = _ByteBoundedQueue[tuple[object, asyncio.Event | None]](
                max_items=max(crawl_context.batch_size * 2, 2),
                max_bytes=crawl_context.max_batch_content_bytes,
            )

            async def _produce_events() -> None:
                try:
                    async with contextlib.aclosing(
                        crawler.crawl(crawl_request)
                    ) as event_stream:
                        async for event in event_stream:
                            acknowledgement = (
                                asyncio.Event()
                                if isinstance(event, FileDownloaded)
                                else None
                            )
                            event_weight = (
                                len(event.content.encode("utf-8"))
                                if isinstance(event, PageCrawled)
                                else 0
                            )
                            await queue.put(
                                (event, acknowledgement), weight=event_weight
                            )
                            if acknowledgement is not None:
                                await acknowledgement.wait()
                finally:
                    await queue.close()

            heartbeat_stop = asyncio.Event()

            async def _heartbeat_loop() -> None:
                while not heartbeat_stop.is_set():
                    await heartbeat_monitor.tick()
                    try:
                        await asyncio.wait_for(
                            heartbeat_stop.wait(),
                            timeout=float(heartbeat_interval_seconds),
                        )
                    except TimeoutError:
                        pass

            crawl_started = time.time()
            producer_task = asyncio.create_task(_produce_events())
            heartbeat_task = asyncio.create_task(_heartbeat_loop())
            try:
                while True:
                    queue_get_task = asyncio.create_task(queue.get())
                    done, _ = await asyncio.wait(
                        {queue_get_task, heartbeat_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if heartbeat_task in done:
                        queue_get_task.cancel()
                        await asyncio.gather(queue_get_task, return_exceptions=True)
                        heartbeat_task.result()
                    queue_item = queue_get_task.result()
                    if isinstance(queue_item, _QueueClosed):
                        break
                    event, acknowledgement = queue_item
                    try:
                        if isinstance(event, PageCrawled):
                            num_pages += 1
                            page_content_bytes = len(event.content.encode("utf-8"))
                            page_buffer.append(
                                {
                                    "url": event.url,
                                    "content": event.content,
                                    "etag": event.etag,
                                    "last_modified": event.last_modified,
                                }
                            )
                            page_buffer_bytes += page_content_bytes
                            if (
                                len(page_buffer) >= crawl_context.batch_size
                                or page_buffer_bytes
                                >= crawl_context.max_batch_content_bytes
                            ):
                                await _flush_pages()
                        elif isinstance(event, PageUnchanged):
                            num_not_modified_pages += 1
                            crawled_titles.add(event.url)
                        elif isinstance(event, PageFailed):
                            num_failed_pages += 1
                            failed_titles.add(event.url)
                            failure_counts[event.reason] += 1
                        elif isinstance(event, FileDownloaded):
                            await _process_file(event)
                        elif isinstance(event, FileFailed):
                            num_failed_files += 1
                            failure_counts[event.reason] += 1
                        elif isinstance(event, CrawlFinished):
                            crawl_is_partial = event.status == "partial"
                            crawl_termination_reason = event.reason or event.status
                            if event.sitemap_fingerprint is not None:
                                new_sitemap_state = {
                                    "fingerprint": event.sitemap_fingerprint,
                                    "entry_count": event.sitemap_entries,
                                    "captured_at": datetime.now(
                                        timezone.utc
                                    ).isoformat(),
                                }
                    finally:
                        if acknowledgement is not None:
                            acknowledgement.set()

                await producer_task
                await _flush_pages()
            finally:
                if not producer_task.done():
                    producer_task.cancel()
                await asyncio.gather(producer_task, return_exceptions=True)

            total_crawl_seconds = time.time() - crawl_started
            timings["process_pages"] = processing_page_seconds
            timings["process_files"] = processing_file_seconds
            timings["crawl_and_parse"] = max(
                total_crawl_seconds - processing_page_seconds - processing_file_seconds,
                0.0,
            )

            crawl_outcome = _classify_crawl_outcome(
                published_pages=num_published_pages,
                unchanged_pages=num_not_modified_pages,
                published_files=num_published_files,
                unchanged_files=num_skipped_files,
                failed_pages=num_failed_pages,
                failed_files=num_failed_files,
                partial=crawl_is_partial,
            )
            crawl_has_usable_result = _crawl_has_usable_result(crawl_outcome)
            useful_items = (
                num_published_pages
                + num_not_modified_pages
                + num_published_files
                + num_skipped_files
            )
            failed_items = num_failed_pages + num_failed_files
            crawl_counts_as_scheduled_run = _crawl_counts_as_scheduled_run(
                crawl_outcome,
                useful_items=useful_items,
                failed_items=failed_items,
            )
            crawl_failure_code = (
                _failure_code_for_crawl(failure_counts, crawl_termination_reason)
                if crawl_outcome in {CrawlOutcome.FAILED, CrawlOutcome.PARTIAL}
                else None
            )
            crawl_failure_detail = (
                _failure_detail(crawl_failure_code, crawl_outcome)
                if crawl_failure_code is not None
                else None
            )

            async with (
                sessionmanager.session() as finalizing_session,
                finalizing_session.begin(),
            ):
                finalizing = await CrawlRunRepository(
                    finalizing_session
                ).mark_finalizing(attempt_id, lease_owner=lease_owner)
            if not finalizing:
                raise CrawlLeaseLostError(
                    "Crawl attempt lease was lost before finalization"
                )

            # Cleanup phase: delete stale blobs (batch for performance)
            cleanup_start = time.time()
            authoritative_empty_sitemap = bool(
                crawl_outcome == CrawlOutcome.EMPTY
                and params.crawl_type == CrawlType.SITEMAP
                and new_sitemap_state is not None
            )
            cleanup_is_safe = (
                crawl_outcome
                in {
                    CrawlOutcome.SUCCEEDED,
                    CrawlOutcome.UNCHANGED,
                }
                or authoritative_empty_sitemap
            )
            stale_titles = (
                []
                if not cleanup_is_safe
                else [
                    title
                    for title in existing_titles
                    if title not in crawled_titles and title not in failed_titles
                ]
            )

            # Batch delete using session-per-operation pattern
            if stale_titles:

                async def _do_stale_blob_cleanup(sess: AsyncSession) -> int:
                    await _require_current_lease(
                        sess,
                        expected_phase=CrawlPhase.FINALIZING,
                    )
                    # Get fresh repo with this session
                    session_provider = cast(Any, container.session)
                    session_provider.override(providers.Object(sess))
                    cleanup_repo = container.info_blob_repo()
                    return await cleanup_repo.batch_delete_by_titles_and_website(
                        titles=stale_titles, website_id=params.website_id
                    )

                num_deleted_blobs = await execute_with_recovery(
                    container=container,
                    session_holder=session_holder,
                    created_sessions=created_sessions,
                    operation_name="stale_blob_cleanup",
                    operation=_do_stale_blob_cleanup,
                )
                if num_deleted_blobs > 0:
                    logger.info(
                        f"Batch deleted {num_deleted_blobs} stale blobs",
                        extra={
                            "website_id": str(params.website_id),
                            "num_stale": len(stale_titles),
                            "num_deleted": num_deleted_blobs,
                        },
                    )
            else:
                num_deleted_blobs = 0
            timings["cleanup_deleted"] = time.time() - cleanup_start

            # Measure website size update with recovery wrapper
            update_start = time.time()

            async def _do_update_size(sess: AsyncSession) -> None:
                await _require_current_lease(
                    sess,
                    expected_phase=CrawlPhase.FINALIZING,
                )
                # Session provided by execute_with_recovery (session-per-operation pattern)
                # NOTE: Use crawl_context primitives, NOT detached ORM website object
                from eneo.database.tables.info_blobs_table import (
                    InfoBlobs as InfoBlobsTable,
                )
                from eneo.database.tables.info_blobs_table import (
                    active_info_blob_version,
                )

                update_size_stmt = (
                    sa.select(sa.func.coalesce(sa.func.sum(InfoBlobsTable.size), 0))
                    .where(
                        InfoBlobsTable.website_id == crawl_context.website_id,
                        InfoBlobsTable.tenant_id == crawl_context.tenant_id,
                        active_info_blob_version(),
                    )
                    .scalar_subquery()
                )
                stmt = (
                    sa.update(WebsitesTable)
                    .where(
                        WebsitesTable.id == crawl_context.website_id,
                        WebsitesTable.tenant_id == crawl_context.tenant_id,
                    )
                    .values(size=update_size_stmt)
                )
                await sess.execute(stmt)

            await execute_with_recovery(
                container=container,
                session_holder=session_holder,
                created_sessions=created_sessions,
                operation_name="website_size_update",
                operation=_do_update_size,
            )
            timings["update_size"] = time.time() - update_start

            # Update last_crawled_at timestamp with recovery wrapper
            # Why: Track crawl completion time independently from record updates
            # Use database server time for timezone correctness
            # NOTE: WebsitesTable already imported above for bootstrap phase

            last_crawled_stmt = (
                sa.update(WebsitesTable)
                .where(WebsitesTable.id == params.website_id)
                .where(
                    WebsitesTable.tenant_id == crawl_context.tenant_id
                )  # Tenant isolation
                .values(last_crawled_at=sa.func.now())
            )

            async def _do_timestamp_update(sess: AsyncSession) -> None:
                await _require_current_lease(
                    sess,
                    expected_phase=CrawlPhase.FINALIZING,
                )
                # Session provided by execute_with_recovery (session-per-operation pattern)
                # No need for transaction check - execute_with_recovery handles it
                await sess.execute(last_crawled_stmt)

            if crawl_counts_as_scheduled_run:
                await execute_with_recovery(
                    container=container,
                    session_holder=session_holder,
                    created_sessions=created_sessions,
                    operation_name="last_crawled_at_update",
                    operation=_do_timestamp_update,
                )

            # Calculate file skip rate for performance analysis
            file_skip_rate = (
                (num_skipped_files / num_files * 100) if num_files > 0 else 0
            )

            # Structured crawl summary for easy log scanning
            status_label = (
                f"CRAWL PARTIAL ({crawl_termination_reason})"
                if crawl_is_partial
                else "CRAWL FINISHED"
            )
            summary = [
                "=" * 60,
                f"{status_label}: {params.url}",
                "-" * 60,
                f"Pages:   {num_pages} fetched, {num_not_modified_pages} not modified, "
                f"{num_failed_pages} failed",
                f"Files:   {num_files} downloaded, {num_failed_files} failed, {num_skipped_files} skipped ({file_skip_rate:.1f}%)",
                f"Cleanup: {num_deleted_blobs} stale entries removed",
            ]
            if crawl_is_partial:
                summary.append(
                    f"⚠️  Partial completion due to: {crawl_termination_reason}"
                )
            summary.append("=" * 60)
            logger.info("\n".join(summary))

            # Performance breakdown log for analysis
            total_time = sum(timings.values())
            logger.info(
                f"Performance breakdown: "
                f"fetch_existing={timings['fetch_existing_titles']:.2f}s, "
                f"crawl_parse={timings['crawl_and_parse']:.2f}s, "
                f"process_pages={timings['process_pages']:.2f}s, "
                f"process_files={timings['process_files']:.2f}s, "
                f"cleanup={timings['cleanup_deleted']:.2f}s, "
                f"update_size={timings['update_size']:.2f}s, "
                f"total_measured={total_time:.2f}s",
                extra={
                    "timings": timings,
                    "pages_crawled": num_published_pages,
                    "pages_not_modified": num_not_modified_pages,
                    "pages_failed": num_failed_pages,
                    "files_crawled": num_published_files,
                    "files_failed": num_failed_files,
                    "files_skipped": num_skipped_files,
                    "file_skip_rate_percent": file_skip_rate,
                    "blobs_deleted": num_deleted_blobs,
                },
            )

            failure_summary = dict(failure_counts) if failure_counts else None
            total_failed = num_failed_pages + num_failed_files

            if _should_store_sitemap_state(
                has_new_state=new_sitemap_state is not None,
                crawl_is_partial=crawl_is_partial,
                outcome=crawl_outcome,
                total_failed=total_failed,
            ):
                assert new_sitemap_state is not None

                async def _store_sitemap_state(sess: AsyncSession) -> None:
                    await _require_current_lease(
                        sess,
                        expected_phase=CrawlPhase.FINALIZING,
                    )
                    await sess.execute(
                        sa.update(WebsitesTable)
                        .where(
                            WebsitesTable.id == params.website_id,
                            WebsitesTable.tenant_id == crawl_context.tenant_id,
                        )
                        .values(sitemap_state=new_sitemap_state)
                    )

                await execute_with_recovery(
                    container=container,
                    session_holder=session_holder,
                    created_sessions=created_sessions,
                    operation_name="sitemap_state_update",
                    operation=_store_sitemap_state,
                )

            async def _do_circuit_breaker_update(sess: AsyncSession) -> None:
                """Update circuit breaker state with appropriate backoff/reset."""
                await _require_current_lease(
                    sess,
                    expected_phase=CrawlPhase.FINALIZING,
                )
                # Session provided by execute_with_recovery (session-per-operation pattern)
                # NOTE: Use crawl_context primitives, NOT detached ORM website object
                if crawl_counts_as_scheduled_run:
                    # A useful partial result is healthy enough to remain scheduled.
                    # Failure-dominated results still enter backoff.
                    logger.info(
                        "Crawl counts as scheduled; resetting failure backoff",
                        extra={"website_id": str(params.website_id)},
                    )
                    reset_stmt = (
                        sa.update(WebsitesTable)
                        .where(WebsitesTable.id == params.website_id)
                        .where(WebsitesTable.tenant_id == crawl_context.tenant_id)
                        .values(consecutive_failures=0, next_retry_at=None)
                    )
                    await sess.execute(reset_stmt)
                else:
                    # Failure: Increment counter and apply exponential backoff
                    # Get current failure count (with tenant filter for security)
                    current_failures_stmt = (
                        sa.select(WebsitesTable.consecutive_failures)
                        .where(WebsitesTable.id == params.website_id)
                        .where(WebsitesTable.tenant_id == crawl_context.tenant_id)
                    )
                    current_failures: int = (
                        await sess.scalar(current_failures_stmt)
                    ) or 0
                    new_failures = current_failures + 1

                    # Auto-disable threshold: Stop trying after too many failures
                    MAX_FAILURES_BEFORE_DISABLE = 10

                    if new_failures >= MAX_FAILURES_BEFORE_DISABLE:
                        # Auto-disable: Set update_interval to NEVER
                        from eneo.websites.domain.website import UpdateInterval

                        logger.error(
                            f"Website {params.website_id} auto-disabled after {new_failures} consecutive failures. "
                            f"User action required to re-enable.",
                            extra={
                                "website_id": str(params.website_id),
                                "url": website_url,  # Use primitive captured during bootstrap
                                "consecutive_failures": new_failures,
                            },
                        )

                        disable_stmt = (
                            sa.update(WebsitesTable)
                            .where(WebsitesTable.id == params.website_id)
                            .where(WebsitesTable.tenant_id == crawl_context.tenant_id)
                            .values(
                                consecutive_failures=new_failures,
                                update_interval=UpdateInterval.NEVER,  # Auto-disable
                                next_retry_at=None,  # Clear retry time
                            )
                        )
                        await sess.execute(disable_stmt)
                    else:
                        # Normal exponential backoff: 1h, 2h, 4h, 8h, 16h, 24h max
                        backoff_hours = min(2 ** (new_failures - 1), 24)
                        next_retry = datetime.now(timezone.utc) + timedelta(
                            hours=backoff_hours
                        )

                        logger.warning(
                            f"Crawl failed for website {params.website_id}. "
                            f"Failure {new_failures}/{MAX_FAILURES_BEFORE_DISABLE}, "
                            f"backoff {backoff_hours}h until {next_retry.isoformat()}",
                            extra={
                                "website_id": str(params.website_id),
                                "consecutive_failures": new_failures,
                                "backoff_hours": backoff_hours,
                                "next_retry_at": next_retry.isoformat(),
                            },
                        )

                        backoff_stmt = (
                            sa.update(WebsitesTable)
                            .where(WebsitesTable.id == params.website_id)
                            .where(WebsitesTable.tenant_id == crawl_context.tenant_id)
                            .values(
                                consecutive_failures=new_failures,
                                next_retry_at=next_retry,
                            )
                        )
                        await sess.execute(backoff_stmt)

            await execute_with_recovery(
                container=container,
                session_holder=session_holder,
                created_sessions=created_sessions,
                operation_name="circuit_breaker_update",
                operation=_do_circuit_breaker_update,
            )

            await _stop_heartbeat(propagate_failure=True)
            result_location = f"/api/v1/websites/{params.website_id}/info-blobs/"
            finished = await _finish_attempt(
                crawl_outcome,
                failure_code=crawl_failure_code,
                failure_detail=crawl_failure_detail,
                result_location=result_location if crawl_has_usable_result else None,
                pages_crawled=num_published_pages,
                files_downloaded=num_published_files,
                pages_failed=num_failed_pages,
                files_failed=num_failed_files,
                failure_summary=failure_summary,
            )
            if not finished:
                raise CrawlLeaseLostError(
                    "Crawl attempt lease was lost during terminalization"
                )

            # Audit delivery is secondary to the authoritative crawl transition.
            # It must not reverse a crawl after content and lifecycle have committed.
            try:
                from eneo.audit.domain.action_types import ActionType
                from eneo.audit.domain.entity_types import EntityType
                from eneo.audit.domain.outcome import Outcome

                audit_failed = crawl_outcome == CrawlOutcome.FAILED

                async with Container.session_scope():
                    await container.audit_service().log_async(
                        tenant_id=current_tenant.id,
                        user=user,
                        action=ActionType.WEBSITE_CRAWLED,
                        entity_type=EntityType.WEBSITE,
                        entity_id=params.website_id,
                        description=(
                            f"Website crawled: {website.url} - {crawl_outcome.value}"
                        ),
                        metadata={
                            "target": {
                                "website_id": str(params.website_id),
                                "url": website.url,
                                "name": website.name or website.url,
                            },
                            "crawl_stats": {
                                "pages_crawled": num_published_pages,
                                "pages_failed": num_failed_pages,
                                "files_downloaded": num_published_files,
                                "files_failed": num_failed_files,
                                "files_skipped": num_skipped_files,
                                "blobs_deleted": num_deleted_blobs,
                                "outcome": crawl_outcome.value,
                            },
                        },
                        outcome=(Outcome.FAILURE if audit_failed else Outcome.SUCCESS),
                        error_message=crawl_failure_detail if audit_failed else None,
                    )
            except Exception:
                logger.exception(
                    "Crawl completed but its audit event could not be recorded",
                    extra={
                        "attempt_id": str(attempt_id),
                        "website_id": str(params.website_id),
                    },
                )

        return {
            "status": crawl_outcome.value,
            "pages_crawled": num_published_pages,
            "files_downloaded": num_published_files,
        }
    except CrawlLeaseLostError:
        await _stop_heartbeat()
        if await _finish_attempt(
            CrawlOutcome.CANCELLED,
            failure_code=CrawlFailureCode.CANCELLED,
            failure_detail="The crawl was stopped by a user",
            pages_crawled=num_published_pages,
            files_downloaded=num_published_files,
            pages_failed=num_failed_pages,
            files_failed=num_failed_files,
            failure_summary=dict(failure_counts) if failure_counts else None,
        ):
            logger.info(
                "Crawl stopped after a persisted cancellation request",
                extra={"job_id": str(job_id), "attempt_id": str(attempt_id)},
            )
            return {
                "status": CrawlOutcome.CANCELLED.value,
                "pages_crawled": num_published_pages,
                "files_downloaded": num_published_files,
            }
        logger.warning(
            "Crawl worker stopped after losing its attempt lease",
            extra={"job_id": str(job_id), "attempt_id": str(attempt_id)},
        )
        raise
    except HeartbeatFailedError:
        await _stop_heartbeat()
        await _finish_attempt(
            CrawlOutcome.INTERRUPTED,
            failure_code=CrawlFailureCode.WORKER_INTERRUPTED,
            failure_detail="The crawler could not renew its database lease",
            pages_crawled=num_published_pages,
            files_downloaded=num_published_files,
            pages_failed=num_failed_pages,
            files_failed=num_failed_files,
            failure_summary=dict(failure_counts) if failure_counts else None,
        )
        raise
    except asyncio.CancelledError:
        await _stop_heartbeat()
        cancelled = await _finish_attempt(
            CrawlOutcome.CANCELLED,
            failure_code=CrawlFailureCode.CANCELLED,
            failure_detail="The crawl was stopped by a user",
            pages_crawled=num_published_pages,
            files_downloaded=num_published_files,
            pages_failed=num_failed_pages,
            files_failed=num_failed_files,
            failure_summary=dict(failure_counts) if failure_counts else None,
        )
        if cancelled:
            logger.info(
                "Crawl stopped after a persisted cancellation request",
                extra={"job_id": str(job_id), "attempt_id": str(attempt_id)},
            )
        else:
            interrupted = await _finish_attempt(
                CrawlOutcome.INTERRUPTED,
                failure_code=CrawlFailureCode.WORKER_INTERRUPTED,
                failure_detail="The crawler worker stopped before completion",
                pages_crawled=num_published_pages,
                files_downloaded=num_published_files,
                pages_failed=num_failed_pages,
                files_failed=num_failed_files,
                failure_summary=dict(failure_counts) if failure_counts else None,
            )
            if interrupted:
                logger.warning(
                    "Crawl worker stopped before completion",
                    extra={"job_id": str(job_id), "attempt_id": str(attempt_id)},
                )
        raise
    except Exception:
        await _stop_heartbeat()
        await _finish_attempt(
            CrawlOutcome.FAILED,
            failure_code=CrawlFailureCode.PROCESSING_FAILED,
            failure_detail="The crawler stopped because of an internal processing error",
            pages_crawled=num_published_pages,
            files_downloaded=num_published_files,
            pages_failed=num_failed_pages,
            files_failed=num_failed_files,
            failure_summary=dict(failure_counts) if failure_counts else None,
        )
        raise
    finally:
        await _stop_heartbeat()
        # Clean up recovery sessions to prevent connection pool exhaustion
        for recovery_session in created_sessions:
            try:
                await recovery_session.close()
            except Exception:
                pass  # Best effort cleanup

        # Guaranteed close with rollback for main session
        main_session = session_holder.get("session")
        if main_session is not None:
            try:
                # Only rollback if there's an active transaction
                if main_session.in_transaction():
                    await main_session.rollback()
            except Exception as rollback_exc:
                # Log at debug level - may be expected if session already closed
                logger.debug(
                    "Session rollback in finally block (may be expected)",
                    extra={"error": str(rollback_exc)},
                )
            try:
                await main_session.close()
            except Exception:
                pass  # Best effort - connection may already be closed
            finally:
                # Clear session_holder to prevent reuse of closed session
                session_holder["session"] = None
