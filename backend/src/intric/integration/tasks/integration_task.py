import asyncio
from typing import TYPE_CHECKING, Any, cast

import redis.asyncio as redis
import sqlalchemy as sa

from intric.database.tables.model_providers_table import ModelProviders
from intric.main.config import get_settings
from intric.main.exceptions import NotFoundException
from intric.main.logging import get_logger
from intric.main.models import ChannelType
from intric.worker.redis import redis_lease
from intric.worker.worker import Worker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from intric.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from intric.integration.presentation.models import (
        ConfluenceContentTaskParam,
        SharepointContentTaskParam,
    )
    from intric.main.container.container import Container

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


@worker.task(channel_type=ChannelType.PULL_SHAREPOINT_CONTENT)
async def pull_sharepoint_content(
    params: "SharepointContentTaskParam", container: "Container", **kw: Any
):
    # Redis-based deduplication to prevent duplicate syncs from concurrent webhooks
    knowledge_id_str = str(params.integration_knowledge_id)
    lock_key = f"sharepoint_sync_lock:{knowledge_id_str}"

    try:
        settings = get_settings()
        redis_client = await redis.from_url(  # pyright: ignore[reportUnknownMemberType]  # redis stubs incomplete
            f"redis://{settings.redis_host}:{settings.redis_port}",
            encoding="utf8",
            decode_responses=True,
        )

        try:
            async with redis_lease(
                redis_client,
                lock_key,
                ttl_seconds=SHAREPOINT_SYNC_LOCK_TTL_SECONDS,
            ) as acquired:
                if not acquired:
                    logger.info(
                        f"Skipping full sync for knowledge {knowledge_id_str} - "
                        f"another sync is already in progress (Redis lock active)"
                    )
                    return "Skipped: Duplicate sync blocked by Redis lock"

                logger.info(f"Acquired sync lock for knowledge {knowledge_id_str}")

                knowledge = await _get_knowledge_with_retry(
                    container, params.integration_knowledge_id
                )
                assert knowledge is not None
                await _validate_embedding_provider(container, knowledge)
                service = container.sharepoint_content_service()

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
    # Redis-based deduplication to prevent duplicate syncs from concurrent webhooks
    # This lock persists across the webhook handler and worker task boundary
    knowledge_id_str = str(params.integration_knowledge_id)
    lock_key = f"sharepoint_sync_lock:{knowledge_id_str}"

    try:
        settings = get_settings()
        redis_client = await redis.from_url(  # pyright: ignore[reportUnknownMemberType]  # redis stubs incomplete
            f"redis://{settings.redis_host}:{settings.redis_port}",
            encoding="utf8",
            decode_responses=True,
        )

        try:
            async with redis_lease(
                redis_client,
                lock_key,
                ttl_seconds=SHAREPOINT_SYNC_LOCK_TTL_SECONDS,
            ) as acquired:
                if not acquired:
                    logger.info(
                        f"Skipping sync for knowledge {knowledge_id_str} - "
                        f"another sync is already in progress (Redis lock active)"
                    )
                    return "Skipped: Duplicate sync blocked by Redis lock"

                logger.info(f"Acquired sync lock for knowledge {knowledge_id_str}")

                knowledge = await _get_knowledge_with_retry(
                    container, params.integration_knowledge_id
                )
                assert knowledge is not None
                await _validate_embedding_provider(container, knowledge)
                service = container.sharepoint_content_service()

                result = await service.process_delta_changes(
                    token_id=params.token_id,
                    tenant_app_id=params.tenant_app_id,
                    integration_knowledge_id=knowledge.id,
                    site_id=params.site_id,
                    drive_id=params.drive_id,
                    resource_type=params.resource_type,
                )
                return result
        finally:
            await redis_client.close()

    except Exception as e:
        logger.error(f"Error in sync_sharepoint_delta: {e}")
        raise
