import asyncio
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import redis.asyncio as redis
import sqlalchemy as sa
from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import sessionmanager
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.transaction_callbacks import after_outer_transaction
from eneo.integration.infrastructure.detached_tasks import run_detached
from eneo.integration.infrastructure.sharepoint_sync_keys import (
    leave_marker,
    release_sync_queue_slot,
)
from eneo.integration.infrastructure.sharepoint_sync_keys import (
    sync_lock_key as _lock_key,
)
from eneo.integration.infrastructure.sharepoint_sync_keys import (
    sync_pending_full_key as _pending_full_key,
)
from eneo.integration.infrastructure.sharepoint_sync_keys import (
    sync_pending_key as _pending_key,
)
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import NotFoundException
from eneo.main.logging import get_logger
from eneo.main.models import ChannelType
from eneo.observability.error_text import user_visible_error
from eneo.redis.connection import build_redis_auth_kwargs, build_redis_url
from eneo.worker.redis import redis_lease
from eneo.worker.worker import Worker

if TYPE_CHECKING:
    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from eneo.integration.domain.task_params import (
        ConfluenceContentTaskParam,
        SharepointContentTaskParam,
    )
    from eneo.integration.infrastructure.content_service.sharepoint_content_service import (
        SharePointContentService,
    )

worker = Worker()
logger = get_logger(__name__)


class IntegrationSyncError(Exception):
    """A failed sync as its job reports it to the person who started it.

    The job keeps this message; the cause, with its URLs and SQL, stays in
    the logs only.
    """

    def __init__(self, cause: Exception) -> None:
        super().__init__(user_visible_error(cause))


# Lock TTL is a crash-detection window, not a cap on sync duration: a watchdog
# in redis_lease keeps refreshing it while the sync runs (which can take longer
# under Graph throttling), and it only lapses if the worker dies.
SHAREPOINT_SYNC_LOCK_TTL_SECONDS = 300


async def _get_knowledge_with_retry(
    container: "Container",
    knowledge_id: Any,
    *,
    retries: int = 20,
    delay: float = 1.0,
):
    repo = container.integration_knowledge_repo()

    for attempt in range(1, retries + 1):
        try:
            return await repo.one(id=knowledge_id)
        except NotFoundException:
            if attempt == retries:
                raise

            logger.debug(
                "IntegrationKnowledge %s not yet visible (attempt %s/%s); retrying in %.1fs",
                knowledge_id,
                attempt,
                retries,
                delay,
            )
            await asyncio.sleep(delay)


async def _validate_embedding_provider(
    container: "Container", knowledge: "IntegrationKnowledge"
):
    provider_id = knowledge.embedding_model.provider_id
    if provider_id is None:
        return

    session = cast(AsyncSession, container.session())
    result = await session.execute(
        sa.select(ModelProviders.is_active).where(ModelProviders.id == provider_id)
    )
    row = result.one_or_none()

    if row is None or not row.is_active:
        raise ValueError(
            f"Embedding model provider (id={provider_id}) for knowledge '{knowledge.name}' "
            f"is not available. Please ensure the provider is configured and active "
            f"before syncing content."
        )


@worker.task(channel_type=ChannelType.PULL_CONFLUENCE_CONTENT)
async def pull_confluence_content(
    params: "ConfluenceContentTaskParam", container: "Container", **kw: Any
):
    try:
        knowledge = await _get_knowledge_with_retry(
            container, params.integration_knowledge_id
        )
        assert knowledge is not None
        await _validate_embedding_provider(container, knowledge)

        service = container.confluence_content_service()

        await service.pull_content(
            token_id=params.token_id,
            space_key=params.space_key,
            integration_knowledge_id=knowledge.id,
        )
    except Exception as exc:
        raise IntegrationSyncError(exc) from exc


# Markers that keep arriving faster than passes complete are left for the
# follow-up job queued after the lease is released, rather than holding the
# lease indefinitely.
_PENDING_DRAIN_MAX_PASSES = 3


async def _open_redis() -> "redis.Redis":
    settings = get_settings()
    return await redis.from_url(  # pyright: ignore[reportUnknownMemberType]  # redis stubs incomplete
        build_redis_url(settings),
        encoding="utf8",
        decode_responses=True,
        **build_redis_auth_kwargs(settings),
    )


async def _queue_sync_job(knowledge_id: UUID, *, full: bool) -> None:
    """Queue a sync for the knowledge in a transaction of its own."""
    async with sessionmanager.session() as session, session.begin():
        container = Container(session=providers.Object(session))
        await container.sharepoint_webhook_service().queue_sync_for_knowledge(
            knowledge_id, full=full
        )


async def _leave_marker_or_fail(
    redis_client: "redis.Redis", knowledge_id_str: str, *, full: bool = False
) -> None:
    """Leave the marker for the follow-up queued once the lease is released.

    Unlike a webhook, a task leaves a marker only when it cannot serve the
    change itself (another sync holds the lease, or its own pending pass
    failed), so a marker it cannot leave fails its job rather than report
    the change as handled.
    """
    if not await leave_marker(redis_client, knowledge_id_str, full=full):
        raise RuntimeError("Could not leave the pending sync marker")


async def _queue_follow_up(redis_client: "redis.Redis", knowledge_id: UUID) -> None:
    """Queue a job for the markers still left once the lease is released.

    A marker is left here by a sync requested during the lease that the
    holder did not run: one set after its last pending pass, one put back
    by a failed pending pass or past the pass limit, one a pass without a
    delta token cannot serve, a manual full sync, or any marker when the
    holder's own sync failed. Whoever sets a marker checks the lease again
    afterwards, so one set after this check finds the lease free and is
    served by its setter.
    """
    knowledge_id_str = str(knowledge_id)
    full = bool(await redis_client.exists(_pending_full_key(knowledge_id_str)))
    if not full and not await redis_client.exists(_pending_key(knowledge_id_str)):
        return
    logger.info(
        "Queuing a follow-up %s sync for knowledge %s requested during the lease",
        "full" if full else "delta",
        knowledge_id_str,
    )
    await _queue_sync_job(knowledge_id, full=full)


@asynccontextmanager
async def _sync_lease(
    container: "Container", params: "SharepointContentTaskParam"
) -> AsyncGenerator[tuple["redis.Redis", bool]]:
    """Open Redis and take the knowledge's sync lease for the block.

    The worker commits the task's transaction only after the task has
    returned. A lease released when the block ends would let the next holder
    read this sync's rows before they are visible: its delta pass would start
    from the superseded delta token, and after a first full sync it would drop
    its pending marker because the token is not there yet. A lease that was
    acquired is therefore released, and the Redis client closed, once the
    task's transaction has ended, however it ends; a worker that dies first
    leaves it to the TTL. After the release, a job is queued for the markers
    left during the lease (``_queue_follow_up``).

    A task that starts clears the queued-sync marker first: from here on a
    new notification either finds the lease taken and leaves a marker, or
    queues a job of its own.
    """
    knowledge_id_str = str(params.integration_knowledge_id)
    lease = AsyncExitStack()
    redis_client = await _open_redis()
    try:
        await release_sync_queue_slot(redis_client, knowledge_id_str)
        acquired = await lease.enter_async_context(
            redis_lease(
                redis_client,
                _lock_key(knowledge_id_str),
                ttl_seconds=SHAREPOINT_SYNC_LOCK_TTL_SECONDS,
            )
        )
    except BaseException:
        await redis_client.close()
        raise
    if not acquired:
        try:
            yield redis_client, False
        finally:
            await lease.aclose()
            await redis_client.close()
        return

    async def release() -> None:
        # The lease goes before the markers are read: a marker's setter checks
        # the lease after setting it and relies on this order.
        try:
            await lease.aclose()
        except Exception:
            logger.warning(
                "Could not release the sync lease of knowledge %s",
                knowledge_id_str,
                exc_info=True,
            )
        try:
            await _queue_follow_up(redis_client, params.integration_knowledge_id)
        except Exception:
            logger.error(
                "Could not queue the follow-up sync of knowledge %s; the periodic "
                "catch-up picks its markers up",
                knowledge_id_str,
                exc_info=True,
            )
        finally:
            await redis_client.close()

    def release_detached() -> None:
        run_detached(release())

    try:
        yield redis_client, True
    finally:
        session = container.session()
        if isinstance(session, AsyncSession):
            try:
                after_outer_transaction(
                    session.sync_session,
                    on_commit=release,
                    on_rollback=release_detached,
                )
            except Exception:
                await release()
                raise
        else:
            # Tests hand the task a fake session with no transaction to wait for.
            await release()


async def _prepare_sharepoint_sync(
    container: "Container", params: "SharepointContentTaskParam"
) -> tuple["IntegrationKnowledge", "SharePointContentService"]:
    knowledge = await _get_knowledge_with_retry(
        container, params.integration_knowledge_id
    )
    assert knowledge is not None
    await _validate_embedding_provider(container, knowledge)
    await _link_subscription_if_missing(container, knowledge)
    return knowledge, container.sharepoint_content_service()


async def _link_subscription_if_missing(
    container: "Container", knowledge: "IntegrationKnowledge"
) -> None:
    """Point the knowledge at its site's subscription when nothing else could.

    Notifications reach a knowledge row only through this link. An import or
    resync skips writing it while a sync holds the row; this sync holds it
    now. A failure here never fails the sync.
    """
    if knowledge.sharepoint_subscription_id is not None:
        return
    # OneDrive subscriptions store the drive id as their site.
    resource_id = knowledge.site_id or knowledge.drive_id
    if not resource_id:
        return
    session = cast(AsyncSession, container.session())
    try:
        async with session.begin_nested():
            subscription = (
                await container.sharepoint_subscription_repo().get_by_user_and_site(
                    user_integration_id=knowledge.user_integration.id,
                    site_id=resource_id,
                )
            )
            if subscription is None:
                return
            if await container.integration_knowledge_repo().link_subscription(
                knowledge.id, subscription.id
            ):
                knowledge.sharepoint_subscription_id = subscription.id
                logger.info(
                    "Linked knowledge %s to SharePoint subscription %s",
                    knowledge.id,
                    subscription.subscription_id,
                )
    except Exception:
        logger.warning(
            "Could not link knowledge %s to its SharePoint subscription",
            knowledge.id,
            exc_info=True,
        )


async def _run_delta(
    service: "SharePointContentService",
    params: "SharepointContentTaskParam",
    knowledge: "IntegrationKnowledge",
    *,
    record_failure: bool = True,
) -> str:
    return await service.process_delta_changes(
        token_id=params.token_id,
        tenant_app_id=params.tenant_app_id,
        integration_knowledge_id=knowledge.id,
        site_id=params.site_id,
        drive_id=params.drive_id,
        resource_type=params.resource_type,
        record_failure=record_failure,
    )


async def _drain_pending_delta(
    redis_client: "redis.Redis",
    knowledge_id_str: str,
    container: "Container",
    service: "SharePointContentService",
    params: "SharepointContentTaskParam",
    *,
    owned: bool = True,
) -> str | None:
    """Run the delta passes skipped tasks asked for, while still holding the lease.

    The knowledge is re-read before each pass: the sync that owned the lease
    may have initialised the delta token. A full sync mints its baseline
    before it enumerates, so a delta pass from that token sees the change the
    marker stands for. A knowledge still without a token had a full sync that
    failed or could not mint one; a delta pass would start a second full sync
    inside this lease, so the marker is left for the follow-up job queued
    once the lease is released.

    ``owned`` is false for a task that took the lease only on its retry: no
    sync of its own ran, so its passes are ordinary ones whose failure is the
    knowledge's status and the job's outcome.
    """
    pending_key = _pending_key(knowledge_id_str)
    result: str | None = None
    for _ in range(_PENDING_DRAIN_MAX_PASSES):
        if not await redis_client.exists(pending_key):
            break
        knowledge = await container.integration_knowledge_repo().one(
            id=params.integration_knowledge_id
        )
        if not knowledge.delta_token:
            logger.info(
                "Leaving the pending marker of knowledge %s for a full sync after "
                "the lease: it has no delta token",
                knowledge_id_str,
            )
            break
        await redis_client.delete(pending_key)
        logger.info(
            "Running pending delta pass for knowledge %s requested while the sync "
            "lease was held",
            knowledge_id_str,
        )
        if not owned:
            result = await _run_delta(service, params, knowledge)
            continue
        try:
            result = await _run_delta(service, params, knowledge, record_failure=False)
        except Exception:
            # The sync that owned the lease succeeded and its status stands; the
            # marker goes back for the follow-up job queued after the release.
            logger.error(
                "Pending delta pass failed for knowledge %s",
                knowledge_id_str,
                exc_info=True,
            )
            await _leave_marker_or_fail(redis_client, knowledge_id_str)
            break
    return result


DEFERRED_FULL_SYNC_RESULT = (
    "Deferred: another sync of this source is running; "
    "a full sync starts when it finishes"
)
SKIPPED_DELTA_SYNC_RESULT = (
    "Skipped: another sync of this source is running and applies these changes"
)


async def _run_full_sync(
    redis_client: "redis.Redis",
    knowledge_id_str: str,
    container: "Container",
    params: "SharepointContentTaskParam",
) -> str:
    # This sync starts after every change announced so far, so it serves the
    # markers already left; a job that fails before reading them must not
    # queue itself again.
    await redis_client.delete(
        _pending_full_key(knowledge_id_str), _pending_key(knowledge_id_str)
    )
    logger.info(f"Acquired sync lock for knowledge {knowledge_id_str}")
    knowledge, service = await _prepare_sharepoint_sync(container, params)

    result = await service.pull_content(
        token_id=params.token_id,
        tenant_app_id=params.tenant_app_id,
        integration_knowledge_id=knowledge.id,
        site_id=params.site_id,
        drive_id=params.drive_id,
        folder_id=params.folder_id,
        folder_path=params.folder_path,
        resource_type=params.resource_type,
    )

    logger.info(f"Completed full sync for knowledge {knowledge_id_str}")
    await _drain_pending_delta(
        redis_client, knowledge_id_str, container, service, params
    )
    return result


@worker.task(channel_type=ChannelType.PULL_SHAREPOINT_CONTENT)
async def pull_sharepoint_content(
    params: "SharepointContentTaskParam", container: "Container", **kw: Any
):
    """Run a full sync, or leave it for after the sync holding the lease.

    A full sync asked for while another sync runs (typically a manual one
    during a webhook's delta) leaves the full-sync marker; the holder queues
    the full sync once it releases the lease, and this job reports that.
    """
    knowledge_id_str = str(params.integration_knowledge_id)

    try:
        async with _sync_lease(container, params) as (redis_client, acquired):
            if acquired:
                return await _run_full_sync(
                    redis_client, knowledge_id_str, container, params
                )
            await _leave_marker_or_fail(redis_client, knowledge_id_str, full=True)
        # The holder reads the markers after releasing the lease; one that
        # released before the marker was set is caught by taking it here.
        async with _sync_lease(container, params) as (redis_client, acquired):
            if acquired:
                return await _run_full_sync(
                    redis_client, knowledge_id_str, container, params
                )
        logger.info(
            "Sync lease for knowledge %s is held by another sync; the full sync "
            "is queued after it",
            knowledge_id_str,
        )
        return DEFERRED_FULL_SYNC_RESULT

    except Exception as exc:
        logger.error(
            f"Error in full sync task for knowledge {knowledge_id_str}: {exc}",
            exc_info=True,
        )
        raise IntegrationSyncError(exc) from exc


@worker.task(channel_type=ChannelType.SYNC_SHAREPOINT_DELTA)
async def sync_sharepoint_delta(
    params: "SharepointContentTaskParam", container: "Container", **kw: Any
):
    """
    Process incremental SharePoint changes using delta query.
    This is called by webhooks to efficiently sync only changed items.
    """
    knowledge_id_str = str(params.integration_knowledge_id)
    pending_key = _pending_key(knowledge_id_str)

    try:
        async with _sync_lease(container, params) as (redis_client, acquired):
            if acquired:
                # This pass starts after every change announced so far.
                await redis_client.delete(pending_key)
                logger.info(f"Acquired sync lock for knowledge {knowledge_id_str}")
                knowledge, service = await _prepare_sharepoint_sync(container, params)
                result = await _run_delta(service, params, knowledge)
                await _drain_pending_delta(
                    redis_client, knowledge_id_str, container, service, params
                )
                return result

            logger.info(
                f"Sync lease for knowledge {knowledge_id_str} is held by another "
                "sync; leaving a pending marker for the lease holder"
            )
            await _leave_marker_or_fail(redis_client, knowledge_id_str)
        # The holder reads the markers after releasing the lease; one that
        # released before the marker was set is caught by taking it here.
        async with _sync_lease(container, params) as (redis_client, acquired):
            # The marker is checked first: when someone else served it there
            # is nothing to do, and preparing a sync (embedding validation)
            # must not be what fails this job.
            if acquired and await redis_client.exists(pending_key):
                _, service = await _prepare_sharepoint_sync(container, params)
                drained = await _drain_pending_delta(
                    redis_client,
                    knowledge_id_str,
                    container,
                    service,
                    params,
                    owned=False,
                )
                if drained is not None:
                    return drained
        return SKIPPED_DELTA_SYNC_RESULT

    except Exception as e:
        logger.error(f"Error in sync_sharepoint_delta: {e}", exc_info=True)
        raise IntegrationSyncError(e) from e
