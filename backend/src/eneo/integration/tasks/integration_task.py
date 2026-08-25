import asyncio
from typing import TYPE_CHECKING, Any, cast

import redis.asyncio as redis
import sqlalchemy as sa

from eneo.database.tables.model_providers_table import ModelProviders
from eneo.main.config import get_settings
from eneo.main.exceptions import NotFoundException
from eneo.main.logging import get_logger
from eneo.main.models import ChannelType
from eneo.worker.redis import redis_lease
from eneo.worker.worker import Worker

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from eneo.integration.presentation.models import (
        ConfluenceContentTaskParam,
        SharepointContentTaskParam,
    )
    from eneo.jobs.task_models import RebuildSharePointGroupSiteMapParams
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


GRAPH_BASE_URL = "https://graph.microsoft.com"


async def _get_rebuild_access_token(
    container: "Container", params: "RebuildSharePointGroupSiteMapParams"
) -> tuple[str | None, str]:
    """Acquire a Graph access token for the map rebuild, via tenant app or user OAuth."""
    async with container.session_scope():
        if params.tenant_app_id:
            repo = container.tenant_sharepoint_app_repo()
            tenant_app = await repo.one(id=params.tenant_app_id)
            if not tenant_app.is_active:
                return None, GRAPH_BASE_URL

            if tenant_app.is_service_account():
                service_account_auth_service = container.service_account_auth_service()
                token_data = await service_account_auth_service.refresh_access_token(
                    tenant_app
                )
                new_refresh_token = token_data.get("refresh_token")
                if (
                    new_refresh_token
                    and new_refresh_token != tenant_app.service_account_refresh_token
                ):
                    tenant_app.update_refresh_token(new_refresh_token)
                    await repo.update(tenant_app)
                return token_data["access_token"], GRAPH_BASE_URL

            tenant_app_auth_service = container.tenant_app_auth_service()
            access_token = await tenant_app_auth_service.get_access_token(tenant_app)
            return access_token, GRAPH_BASE_URL

        if params.user_integration_id:
            from eneo.integration.domain.entities.oauth_token import SharePointToken

            oauth_token_service = container.oauth_token_service()
            token = await oauth_token_service.get_oauth_token_by_user_integration(
                user_integration_id=params.user_integration_id
            )
            if not token or not token.token_type.is_sharepoint:
                return None, GRAPH_BASE_URL

            token = await oauth_token_service.refresh_and_update_token(
                token_id=token.id
            )
            if not isinstance(token, SharePointToken):
                return None, GRAPH_BASE_URL
            return token.access_token, token.base_url

    return None, GRAPH_BASE_URL


@worker.long_running_function(with_user=False, keep_result=0)
async def rebuild_sharepoint_group_site_map(
    job_id: "UUID",
    params: "RebuildSharePointGroupSiteMapParams",
    container: "Container",
):
    """Build the per-tenant group->site map used to categorize preview sites.

    Enumerates all M365 groups, resolves their root sites via Graph $batch and
    stores the result in Redis (SharePointGroupSiteCache). The freshly refreshed
    access token (~1h validity) is not refreshed mid-run; a rebuild that somehow
    outlives it fails and is rescheduled by the next preview request.
    """
    from eneo.integration.infrastructure.clients.sharepoint_content_client import (
        SharePointContentClient,
    )
    from eneo.integration.infrastructure.sharepoint_group_site_cache import (
        GroupSiteEntry,
    )

    settings = get_settings()
    if not settings.sharepoint_site_categorization_enabled:
        return "Skipped: site categorization disabled"

    redis_client = container.redis_client()
    cache = container.sharepoint_group_site_cache()
    tenant_id_str = str(params.tenant_id)
    lock_key = f"sharepoint:group_site_map:lock:{params.tenant_id}"

    try:
        async with redis_lease(
            redis_client,
            lock_key,
            ttl_seconds=SHAREPOINT_SYNC_LOCK_TTL_SECONDS,
        ) as acquired:
            if not acquired:
                return "Skipped: rebuild already in progress"

            access_token, base_url = await _get_rebuild_access_token(container, params)
            if not access_token:
                logger.warning(
                    "No usable credentials for SharePoint group site map rebuild",
                    extra={"tenant_id": tenant_id_str},
                )
                return "Skipped: no usable credentials"

            async with SharePointContentClient(
                base_url=base_url,
                api_token=access_token,
                token_id=None,
                token_refresh_callback=None,
            ) as client:
                teams = await client.get_m365_groups()
                group_ids = [
                    gid
                    for team in teams
                    if isinstance(gid := team.get("id"), str) and gid
                ]
                site_map = await client.get_group_root_sites_batched(group_ids)

            entries: list[GroupSiteEntry] = []
            for team in teams:
                group_id = team.get("id")
                if not isinstance(group_id, str):
                    continue
                site = site_map.get(group_id)
                if not site:
                    continue
                visibility = team.get("visibility")
                entries.append(
                    {
                        "group_id": group_id,
                        "visibility": (
                            visibility.lower() if isinstance(visibility, str) else ""
                        ),
                        "site_id": site["id"],
                        "web_url": site["webUrl"],
                    }
                )

            await cache.set(params.tenant_id, entries)
            logger.info(
                "Rebuilt SharePoint group site map",
                extra={
                    "tenant_id": tenant_id_str,
                    "groups": len(group_ids),
                    "sites_mapped": len(entries),
                },
            )
            return {"groups": len(group_ids), "sites_mapped": len(entries)}
    except Exception as exc:
        logger.error(
            f"Error rebuilding SharePoint group site map for tenant {tenant_id_str}: {exc}",
            exc_info=True,
        )
        raise
    finally:
        # Allow the next preview to reschedule immediately after success or failure.
        await cache.clear_building_marker(params.tenant_id)


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
