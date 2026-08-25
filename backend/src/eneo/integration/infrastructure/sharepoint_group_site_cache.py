"""Per-tenant cache of the SharePoint group->site map used for site categorization.

The import-dialog preview classifies sites by Teams membership/visibility. Building
that map requires enumerating every M365 group and resolving its root site — far
too slow to do in the request path on large tenants. The preview therefore reads
ONLY from this cache; on miss (or approaching expiry) it schedules a background
rebuild and serves the sites uncategorized.

Keys:
    sharepoint:group_site_map:{tenant_id}           — the cached map (TTL from settings)
    sharepoint:group_site_map:building:{tenant_id}  — anti-spam marker while a rebuild is pending
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, TypedDict, cast
from uuid import NAMESPACE_URL, UUID, uuid5

import orjson
import redis.asyncio as redis

from eneo.main.config import get_settings
from eneo.main.logging import get_logger

logger = get_logger(__name__)

SCHEMA_VERSION = 1
BUILDING_MARKER_TTL_SECONDS = 900


class GroupSiteEntry(TypedDict):
    group_id: str
    visibility: str  # lower-cased; "" when absent
    site_id: str
    web_url: str


class SharePointGroupSiteCache:
    def __init__(self, redis_client: redis.Redis) -> None:
        super().__init__()
        self.redis_client = redis_client

    def _map_key(self, tenant_id: UUID) -> str:
        return f"sharepoint:group_site_map:{tenant_id}"

    def _building_key(self, tenant_id: UUID) -> str:
        return f"sharepoint:group_site_map:building:{tenant_id}"

    @staticmethod
    def rebuild_job_id(tenant_id: UUID) -> UUID:
        # Deterministic so arq dedupes concurrent enqueues; must be a UUID
        # because the worker parses the arq job id as one.
        return uuid5(NAMESPACE_URL, f"eneo:sharepoint-group-site-map:{tenant_id}")

    async def get(
        self, tenant_id: UUID
    ) -> Optional[tuple[list[GroupSiteEntry], datetime]]:
        raw = await self.redis_client.get(self._map_key(tenant_id))
        if raw is None:
            return None

        try:
            payload = orjson.loads(raw)
            if payload.get("v") != SCHEMA_VERSION:
                return None
            built_at = datetime.fromisoformat(payload["built_at"])
            groups = payload["groups"]
            if not isinstance(groups, list):
                return None
            return cast(list[GroupSiteEntry], groups), built_at
        except (orjson.JSONDecodeError, KeyError, TypeError, ValueError):
            logger.warning(
                "Discarding unreadable SharePoint group site map cache entry",
                extra={"tenant_id": str(tenant_id)},
            )
            return None

    async def set(self, tenant_id: UUID, entries: list[GroupSiteEntry]) -> None:
        payload = orjson.dumps(
            {
                "v": SCHEMA_VERSION,
                "built_at": datetime.now(timezone.utc).isoformat(),
                "groups": entries,
            }
        )
        ttl = get_settings().sharepoint_preview_cache_ttl_seconds
        await self.redis_client.setex(
            self._map_key(tenant_id), timedelta(seconds=ttl), payload
        )

    async def clear_building_marker(self, tenant_id: UUID) -> None:
        await self.redis_client.delete(self._building_key(tenant_id))

    async def schedule_rebuild(
        self,
        tenant_id: UUID,
        *,
        tenant_app_id: Optional[UUID] = None,
        user_integration_id: Optional[UUID] = None,
    ) -> bool:
        """Enqueue a background map rebuild, at most once per marker window.

        Never raises: a failed enqueue must not break the preview request.
        Returns True when a job was enqueued.
        """
        if not get_settings().sharepoint_site_categorization_enabled:
            return False

        building_key = self._building_key(tenant_id)
        try:
            marker_set = await self.redis_client.set(
                building_key, b"1", nx=True, ex=BUILDING_MARKER_TTL_SECONDS
            )
            if not marker_set:
                return False

            from eneo.jobs.job_manager import job_manager
            from eneo.jobs.job_models import Task
            from eneo.jobs.task_models import RebuildSharePointGroupSiteMapParams

            await job_manager.enqueue(
                task=Task.REBUILD_SHAREPOINT_GROUP_SITE_MAP,
                job_id=self.rebuild_job_id(tenant_id),
                params=RebuildSharePointGroupSiteMapParams(
                    tenant_id=tenant_id,
                    tenant_app_id=tenant_app_id,
                    user_integration_id=user_integration_id,
                ),
            )
            logger.info(
                "Scheduled SharePoint group site map rebuild",
                extra={"tenant_id": str(tenant_id)},
            )
            return True
        except Exception:
            logger.warning(
                "Could not schedule SharePoint group site map rebuild",
                extra={"tenant_id": str(tenant_id)},
                exc_info=True,
            )
            try:
                await self.redis_client.delete(building_key)
            except Exception:
                pass
            return False
