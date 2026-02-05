import asyncio
from typing import TYPE_CHECKING
import redis.asyncio as redis

from intric.main.exceptions import NotFoundException
from intric.main.logging import get_logger
from intric.main.models import ChannelType
from intric.main.config import get_settings
from intric.worker.worker import Worker

if TYPE_CHECKING:
    from intric.integration.presentation.models import (
        ConfluenceContentTaskParam,
        SharepointContentTaskParam,
    )
    from intric.main.container.container import Container

worker = Worker()
logger = get_logger(__name__)


async def _get_knowledge_with_retry(container: "Container", knowledge_id, *, retries: int = 20, delay: float = 1.0):
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


@worker.task(channel_type=ChannelType.PULL_CONFLUENCE_CONTENT)
async def pull_confluence_content(
    params: "ConfluenceContentTaskParam", container: "Container", **kw
):
    knowledge = await _get_knowledge_with_retry(container, params.integration_knowledge_id)

    service = container.confluence_content_service()

    await service.pull_content(
        token_id=params.token_id,
        space_key=params.space_key,
        integration_knowledge_id=knowledge.id,
    )


@worker.task(channel_type=ChannelType.PULL_SHAREPOINT_CONTENT)
async def pull_sharepoint_content(
    params: "SharepointContentTaskParam", container: "Container", **kw
):
    # Redis-based deduplication to prevent duplicate syncs from concurrent webhooks
    knowledge_id_str = str(params.integration_knowledge_id)
    lock_key = f"sharepoint_sync_lock:{knowledge_id_str}"
    lock_ttl_seconds = 300  # Lock expires after 5 minutes

    try:
        # Try to acquire the lock in Redis (SET only if not exists)
        settings = get_settings()
        redis_client = await redis.from_url(
            f"redis://{settings.redis_host}:{settings.redis_port}",
            encoding="utf8",
            decode_responses=True
        )

        # SET NX EX - Set if Not eXists with EXpiration
        lock_acquired = await redis_client.set(
            lock_key,
            "locked",
            nx=True,
            ex=lock_ttl_seconds
        )

        if not lock_acquired:
            logger.info(
                f"Skipping full sync for knowledge {knowledge_id_str} - "
                f"another sync is already in progress (Redis lock active)"
            )
            await redis_client.close()
            return "Skipped: Duplicate sync blocked by Redis lock"

        logger.info(f"Acquired sync lock for knowledge {knowledge_id_str}")

        try:
            knowledge = await _get_knowledge_with_retry(container, params.integration_knowledge_id)
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
            # Release lock after sync completes (or fails)
            await redis_client.delete(lock_key)
            logger.info(f"Released sync lock for knowledge {knowledge_id_str}")
            await redis_client.close()

    except Exception as exc:
        logger.error(
            f"Error in full sync task for knowledge {knowledge_id_str}: {exc}",
            exc_info=True
        )
        raise


@worker.task(channel_type=ChannelType.SYNC_SHAREPOINT_DELTA)
async def sync_sharepoint_delta(
    params: "SharepointContentTaskParam", container: "Container", **kw
):
    """
    Process incremental SharePoint changes using delta query.
    This is called by webhooks to efficiently sync only changed items.
    """
    # Redis-based deduplication to prevent duplicate syncs from concurrent webhooks
    # This lock persists across the webhook handler and worker task boundary
    knowledge_id_str = str(params.integration_knowledge_id)
    lock_key = f"sharepoint_sync_lock:{knowledge_id_str}"
    lock_ttl_seconds = 300  # Lock expires after 5 minutes (longer than any sync should take)

    try:
        # Try to acquire the lock in Redis (SET only if not exists)
        settings = get_settings()
        redis_client = await redis.from_url(
            f"redis://{settings.redis_host}:{settings.redis_port}",
            encoding="utf8",
            decode_responses=True
        )

        # SET NX EX - Set if Not eXists with EXpiration
        lock_acquired = await redis_client.set(
            lock_key,
            "locked",
            nx=True,
            ex=lock_ttl_seconds
        )

        if not lock_acquired:
            logger.info(
                f"Skipping sync for knowledge {knowledge_id_str} - "
                f"another sync is already in progress (Redis lock active)"
            )
            await redis_client.close()
            return "Skipped: Duplicate sync blocked by Redis lock"

        logger.info(f"Acquired sync lock for knowledge {knowledge_id_str}")

        try:
            knowledge = await _get_knowledge_with_retry(container, params.integration_knowledge_id)
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
            # Release the lock
            await redis_client.delete(lock_key)
            await redis_client.close()
            logger.info(f"Released sync lock for knowledge {knowledge_id_str}")

    except Exception as e:
        logger.error(f"Error in sync_sharepoint_delta: {e}")
        raise
