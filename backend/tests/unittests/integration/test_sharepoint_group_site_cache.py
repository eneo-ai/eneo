from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import orjson
import pytest

from eneo.integration.infrastructure.sharepoint_group_site_cache import (
    SCHEMA_VERSION,
    SharePointGroupSiteCache,
)

TENANT_ID = uuid4()

SETTINGS_PATCH = (
    "eneo.integration.infrastructure.sharepoint_group_site_cache.get_settings"
)
ENQUEUE_PATCH = "eneo.jobs.job_manager.job_manager.enqueue"


def _settings(enabled: bool = True, ttl: int = 21600) -> MagicMock:
    return MagicMock(
        sharepoint_site_categorization_enabled=enabled,
        sharepoint_preview_cache_ttl_seconds=ttl,
    )


def _make_cache() -> tuple[SharePointGroupSiteCache, MagicMock]:
    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.set = AsyncMock(return_value=True)
    redis_client.setex = AsyncMock()
    redis_client.delete = AsyncMock()
    return SharePointGroupSiteCache(redis_client=redis_client), redis_client


ENTRIES = [
    {
        "group_id": "group-1",
        "visibility": "public",
        "site_id": "site-1",
        "web_url": "https://contoso.sharepoint.com/sites/one",
    }
]


def _payload(version: int = SCHEMA_VERSION) -> bytes:
    return orjson.dumps(
        {
            "v": version,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "groups": ENTRIES,
        }
    )


@pytest.mark.asyncio
async def test_get_returns_entries_and_built_at():
    cache, redis_client = _make_cache()
    redis_client.get = AsyncMock(return_value=_payload())

    result = await cache.get(TENANT_ID)

    assert result is not None
    entries, built_at = result
    assert entries == ENTRIES
    assert built_at.tzinfo is not None


@pytest.mark.asyncio
async def test_get_returns_none_on_miss_version_mismatch_and_corrupt_payload():
    cache, redis_client = _make_cache()

    redis_client.get = AsyncMock(return_value=None)
    assert await cache.get(TENANT_ID) is None

    redis_client.get = AsyncMock(return_value=_payload(version=SCHEMA_VERSION + 1))
    assert await cache.get(TENANT_ID) is None

    redis_client.get = AsyncMock(return_value=b"not json")
    assert await cache.get(TENANT_ID) is None


@pytest.mark.asyncio
async def test_set_stores_versioned_payload_with_ttl():
    cache, redis_client = _make_cache()

    with patch(SETTINGS_PATCH, return_value=_settings(ttl=1234)):
        await cache.set(TENANT_ID, ENTRIES)  # type: ignore[arg-type]

    redis_client.setex.assert_awaited_once()
    key, ttl, payload = redis_client.setex.await_args.args
    assert key == f"sharepoint:group_site_map:{TENANT_ID}"
    assert ttl.total_seconds() == 1234
    decoded = orjson.loads(payload)
    assert decoded["v"] == SCHEMA_VERSION
    assert decoded["groups"] == ENTRIES


@pytest.mark.asyncio
async def test_schedule_rebuild_enqueues_with_deterministic_job_id():
    cache, redis_client = _make_cache()

    with (
        patch(SETTINGS_PATCH, return_value=_settings()),
        patch(ENQUEUE_PATCH, new_callable=AsyncMock) as enqueue,
    ):
        scheduled = await cache.schedule_rebuild(TENANT_ID, user_integration_id=uuid4())

    assert scheduled is True
    redis_client.set.assert_awaited_once()
    assert redis_client.set.await_args.kwargs.get("nx") is True
    enqueue.assert_awaited_once()
    assert enqueue.await_args.kwargs[
        "job_id"
    ] == SharePointGroupSiteCache.rebuild_job_id(TENANT_ID)
    params = enqueue.await_args.kwargs["params"]
    assert params.tenant_id == TENANT_ID


@pytest.mark.asyncio
async def test_schedule_rebuild_dedupes_on_existing_building_marker():
    cache, redis_client = _make_cache()
    redis_client.set = AsyncMock(return_value=None)  # NX not acquired

    with (
        patch(SETTINGS_PATCH, return_value=_settings()),
        patch(ENQUEUE_PATCH, new_callable=AsyncMock) as enqueue,
    ):
        scheduled = await cache.schedule_rebuild(TENANT_ID)

    assert scheduled is False
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_rebuild_skips_when_categorization_disabled():
    cache, redis_client = _make_cache()

    with (
        patch(SETTINGS_PATCH, return_value=_settings(enabled=False)),
        patch(ENQUEUE_PATCH, new_callable=AsyncMock) as enqueue,
    ):
        scheduled = await cache.schedule_rebuild(TENANT_ID)

    assert scheduled is False
    redis_client.set.assert_not_awaited()
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_rebuild_swallows_enqueue_failure_and_clears_marker():
    cache, redis_client = _make_cache()

    with (
        patch(SETTINGS_PATCH, return_value=_settings()),
        patch(
            ENQUEUE_PATCH,
            new_callable=AsyncMock,
            side_effect=RuntimeError("arq down"),
        ),
    ):
        scheduled = await cache.schedule_rebuild(TENANT_ID)

    assert scheduled is False
    redis_client.delete.assert_awaited_once_with(
        f"sharepoint:group_site_map:building:{TENANT_ID}"
    )
