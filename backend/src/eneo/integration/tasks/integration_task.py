import asyncio
from typing import TYPE_CHECKING, Any, cast

import redis.asyncio as redis
import sqlalchemy as sa

from eneo.database.tables.model_providers_table import ModelProviders
from eneo.main.config import get_settings
from eneo.main.exceptions import NotFoundException
from eneo.main.logging import get_logger
from eneo.main.models import ChannelType
from eneo.redis.connection import build_redis_auth_kwargs, build_redis_url
from eneo.worker.redis import redis_lease
from eneo.worker.worker import Worker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from eneo.integration.infrastructure.content_service.sharepoint_content_service import (
        SharePointContentService,
    )
    from eneo.integration.presentation.models import (
        ConfluenceContentTaskParam,
        SharepointContentTaskParam,
    )
    from eneo.main.container.container import Container

worker = Worker()
logger = get_logger(__name__)

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

    session = cast("AsyncSession", container.session())
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


# A webhook that arrives while a sync holds the lease leaves this marker; the
# lease holder runs one more delta pass before releasing. Without it the skipped
# task is simply dropped, and because the webhook service has already recorded the
# item's ChangeKey the next identical notification is treated as a duplicate.
SHAREPOINT_SYNC_PENDING_TTL_SECONDS = 3600
_PENDING_RETRY_DELAY_SECONDS = 1.0
# Markers that keep arriving faster than passes complete are left for the
# next sync rather than holding the lease indefinitely.
_PENDING_DRAIN_MAX_PASSES = 3


def _lock_key(knowledge_id: str) -> str:
    return f"sharepoint_sync_lock:{knowledge_id}"


def _pending_key(knowledge_id: str) -> str:
    return f"sharepoint_sync_pending:{knowledge_id}"


async def _open_redis() -> "redis.Redis":
    settings = get_settings()
    return await redis.from_url(  # pyright: ignore[reportUnknownMemberType]  # redis stubs incomplete
        build_redis_url(settings),
        encoding="utf8",
        decode_responses=True,
        **build_redis_auth_kwargs(settings),
    )


async def _prepare_sharepoint_sync(
    container: "Container", params: "SharepointContentTaskParam"
) -> tuple["IntegrationKnowledge", "SharePointContentService"]:
    knowledge = await _get_knowledge_with_retry(
        container, params.integration_knowledge_id
    )
    assert knowledge is not None
    await _validate_embedding_provider(container, knowledge)
    return knowledge, container.sharepoint_content_service()


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
) -> str | None:
    """Run the delta passes skipped tasks asked for, while still holding the lease.

    The knowledge is re-read before each pass: the sync that owned the lease
    may have initialised the delta token, and a knowledge still without one
    has just been fully synced, so a delta pass would only start a second
    full sync. The marker is dropped in that case.
    """
    result: str | None = None
    for _ in range(_PENDING_DRAIN_MAX_PASSES):
        if not await redis_client.delete(_pending_key(knowledge_id_str)):
            break
        knowledge = await container.integration_knowledge_repo().one(
            id=params.integration_knowledge_id
        )
        if not knowledge.delta_token:
            logger.info(
                "Dropping pending delta marker for knowledge %s: no delta token, "
                "the full sync that just ran covers the change",
                knowledge_id_str,
            )
            break
        logger.info(
            "Running pending delta pass for knowledge %s requested while the sync "
            "lease was held",
            knowledge_id_str,
        )
        try:
            result = await _run_delta(service, params, knowledge, record_failure=False)
        except Exception:
            # The sync that owned the lease succeeded and its status stands; the
            # marker goes back so the change is retried by the next notification
            # or scheduled sync, not lost.
            logger.error(
                "Pending delta pass failed for knowledge %s",
                knowledge_id_str,
                exc_info=True,
            )
            await redis_client.set(
                _pending_key(knowledge_id_str),
                "1",
                ex=SHAREPOINT_SYNC_PENDING_TTL_SECONDS,
            )
            break
    return result


@worker.task(channel_type=ChannelType.PULL_SHAREPOINT_CONTENT)
async def pull_sharepoint_content(
    params: "SharepointContentTaskParam", container: "Container", **kw: Any
):
    knowledge_id_str = str(params.integration_knowledge_id)

    try:
        redis_client = await _open_redis()
        try:
            async with redis_lease(
                redis_client,
                _lock_key(knowledge_id_str),
                ttl_seconds=SHAREPOINT_SYNC_LOCK_TTL_SECONDS,
            ) as acquired:
                if not acquired:
                    logger.info(
                        f"Skipping full sync for knowledge {knowledge_id_str} - "
                        f"another sync is already in progress (Redis lock active)"
                    )
                    return "Skipped: Duplicate sync blocked by Redis lock"

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
        finally:
            await redis_client.close()

    except Exception as exc:
        logger.error(
            f"Error in full sync task for knowledge {knowledge_id_str}: {exc}",
            exc_info=True,
        )
        raise


@worker.task(channel_type=ChannelType.SYNC_SHAREPOINT_DELTA)
async def sync_sharepoint_delta(
    params: "SharepointContentTaskParam", container: "Container", **kw: Any
):
    """
    Process incremental SharePoint changes using delta query.
    This is called by webhooks to efficiently sync only changed items.
    """
    knowledge_id_str = str(params.integration_knowledge_id)
    lock_key = _lock_key(knowledge_id_str)

    try:
        redis_client = await _open_redis()
        try:
            async with redis_lease(
                redis_client, lock_key, ttl_seconds=SHAREPOINT_SYNC_LOCK_TTL_SECONDS
            ) as acquired:
                if acquired:
                    logger.info(f"Acquired sync lock for knowledge {knowledge_id_str}")
                    knowledge, service = await _prepare_sharepoint_sync(
                        container, params
                    )
                    result = await _run_delta(service, params, knowledge)
                    await _drain_pending_delta(
                        redis_client, knowledge_id_str, container, service, params
                    )
                    return result

            logger.info(
                f"Sync lease for knowledge {knowledge_id_str} is held by another "
                "sync; leaving a pending marker for the lease holder"
            )
            await redis_client.set(
                _pending_key(knowledge_id_str),
                "1",
                ex=SHAREPOINT_SYNC_PENDING_TTL_SECONDS,
            )
            # The holder may have passed its own pending check and released in the
            # meantime; one short retry closes that window instead of waiting for
            # the next webhook.
            await asyncio.sleep(_PENDING_RETRY_DELAY_SECONDS)
            async with redis_lease(
                redis_client, lock_key, ttl_seconds=SHAREPOINT_SYNC_LOCK_TTL_SECONDS
            ) as acquired:
                # The marker is checked first: when the holder drained it there
                # is nothing to do, and preparing a sync (embedding validation)
                # must not be what fails this job.
                if acquired and await redis_client.get(_pending_key(knowledge_id_str)):
                    _, service = await _prepare_sharepoint_sync(container, params)
                    drained = await _drain_pending_delta(
                        redis_client, knowledge_id_str, container, service, params
                    )
                    if drained is not None:
                        return drained
            return "Skipped: Duplicate sync blocked by Redis lock"
        finally:
            await redis_client.close()

    except Exception as e:
        logger.error(f"Error in sync_sharepoint_delta: {e}", exc_info=True)
        raise
