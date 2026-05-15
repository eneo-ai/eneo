from uuid import UUID

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.websites_table import Websites
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import UpdateInterval

EXPECTED_INTERVAL_ORDER = ["daily", "every_other_day", "never", "weekly"]


async def _embedding_model_id(session) -> UUID:
    embedding_model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
    assert embedding_model_id is not None
    return embedding_model_id


async def _create_website(
    session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    embedding_model_id: UUID,
    url_suffix: str,
    update_interval: UpdateInterval,
    size: int,
) -> Websites:
    website = Websites(
        name=f"Scheduled aggregate {url_suffix}",
        url=f"https://scheduled-{url_suffix}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=update_interval,
        size=size,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
    )
    session.add(website)
    await session.flush()
    return website


def _empty_buckets() -> list[dict[str, int | str]]:
    return [
        {
            "update_interval": update_interval,
            "website_count": 0,
            "total_size_bytes": 0,
        }
        for update_interval in EXPECTED_INTERVAL_ORDER
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_scheduled_aggregate_empty(
    client,
    super_admin_token,
):
    response = await client.get(
        "/api/v1/sysadmin/crawler/scheduled",
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    assert response.json() == {
        "buckets": _empty_buckets(),
        "total_websites": 0,
        "total_size_bytes": 0,
        "unparseable_update_interval_website_count": 0,
        "unparseable_update_interval_total_size_bytes": 0,
        "tenant_id": None,
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_scheduled_aggregate_groups_by_update_interval(
    client,
    db_session,
    tenant_factory,
    user_factory,
    super_admin_token,
):
    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        tenant = await tenant_factory(session, name="Scheduled aggregate tenant")
        user = await user_factory(session, tenant_id=tenant.id)
        other_tenant = await tenant_factory(
            session, name="Other scheduled aggregate tenant"
        )
        other_user = await user_factory(session, tenant_id=other_tenant.id)

        await _create_website(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="daily-one",
            update_interval=UpdateInterval.DAILY,
            size=100,
        )
        await _create_website(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="daily-two",
            update_interval=UpdateInterval.DAILY,
            size=250,
        )
        await _create_website(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="never",
            update_interval=UpdateInterval.NEVER,
            size=50,
        )
        await _create_website(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="weekly-other",
            update_interval=UpdateInterval.WEEKLY,
            size=700,
        )
        legacy_unknown = Websites(
            name="Scheduled aggregate legacy",
            url="https://scheduled-legacy.example.com",
            download_files=True,
            crawl_type=CrawlType.CRAWL,
            update_interval="monthly",
            size=900,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
        )
        session.add(legacy_unknown)

        tenant_id = tenant.id
        await session.commit()

    response = await client.get(
        "/api/v1/sysadmin/crawler/scheduled",
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_websites"] == 5
    assert data["total_size_bytes"] == 2000
    assert data["unparseable_update_interval_website_count"] == 1
    assert data["unparseable_update_interval_total_size_bytes"] == 900
    assert [bucket["update_interval"] for bucket in data["buckets"]] == (
        EXPECTED_INTERVAL_ORDER
    )
    by_interval = {bucket["update_interval"]: bucket for bucket in data["buckets"]}
    assert by_interval[UpdateInterval.DAILY.value] == {
        "update_interval": UpdateInterval.DAILY.value,
        "website_count": 2,
        "total_size_bytes": 350,
    }
    assert by_interval[UpdateInterval.NEVER.value] == {
        "update_interval": UpdateInterval.NEVER.value,
        "website_count": 1,
        "total_size_bytes": 50,
    }
    assert by_interval[UpdateInterval.EVERY_OTHER_DAY.value] == {
        "update_interval": UpdateInterval.EVERY_OTHER_DAY.value,
        "website_count": 0,
        "total_size_bytes": 0,
    }
    assert by_interval[UpdateInterval.WEEKLY.value] == {
        "update_interval": UpdateInterval.WEEKLY.value,
        "website_count": 1,
        "total_size_bytes": 700,
    }

    tenant_response = await client.get(
        "/api/v1/sysadmin/crawler/scheduled",
        params={"tenant_id": str(tenant_id)},
        headers={"X-API-Key": super_admin_token},
    )

    assert tenant_response.status_code == 200
    tenant_data = tenant_response.json()
    assert tenant_data["tenant_id"] == str(tenant_id)
    assert tenant_data["total_websites"] == 4
    assert tenant_data["total_size_bytes"] == 1300
    assert tenant_data["unparseable_update_interval_website_count"] == 1
    assert tenant_data["unparseable_update_interval_total_size_bytes"] == 900
    tenant_by_interval = {
        bucket["update_interval"]: bucket for bucket in tenant_data["buckets"]
    }
    assert tenant_by_interval[UpdateInterval.DAILY.value]["website_count"] == 2
    assert tenant_by_interval[UpdateInterval.WEEKLY.value] == {
        "update_interval": UpdateInterval.WEEKLY.value,
        "website_count": 0,
        "total_size_bytes": 0,
    }

    missing_tenant_response = await client.get(
        "/api/v1/sysadmin/crawler/scheduled",
        params={"tenant_id": str(UUID("00000000-0000-0000-0000-000000000001"))},
        headers={"X-API-Key": super_admin_token},
    )

    assert missing_tenant_response.status_code == 200
    missing_tenant_data = missing_tenant_response.json()
    assert missing_tenant_data["buckets"] == _empty_buckets()
    assert missing_tenant_data["total_websites"] == 0
    assert missing_tenant_data["total_size_bytes"] == 0
    assert missing_tenant_data["unparseable_update_interval_website_count"] == 0
    assert missing_tenant_data["unparseable_update_interval_total_size_bytes"] == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_scheduled_aggregate_requires_super_api_key(client):
    response = await client.get("/api/v1/sysadmin/crawler/scheduled")

    assert response.status_code in {401, 403}
