from uuid import UUID, uuid4

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
    update_interval: UpdateInterval | str,
    size: int,
) -> Websites:
    website = Websites(
        name=f"Admin scheduled aggregate {url_suffix}",
        url=f"https://admin-scheduled-{url_suffix}.example.com",
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
async def test_admin_crawler_scheduled_aggregate_empty_result(
    client,
    admin_user_api_key,
    admin_user,
):
    response = await client.get(
        "/api/v1/admin/crawler/scheduled",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    assert response.json() == {
        "buckets": _empty_buckets(),
        "total_websites": 0,
        "total_size_bytes": 0,
        "unparseable_update_interval_website_count": 0,
        "unparseable_update_interval_total_size_bytes": 0,
        "tenant_id": str(admin_user.tenant_id),
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_scheduled_aggregate_is_scoped_to_current_tenant(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    tenant_factory,
    user_factory,
):
    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        other_tenant = await tenant_factory(session, name="Other admin scheduled")
        other_user = await user_factory(session, tenant_id=other_tenant.id)

        await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="daily",
            update_interval=UpdateInterval.DAILY,
            size=100,
        )
        await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="never",
            update_interval=UpdateInterval.NEVER,
            size=250,
        )
        await _create_website(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="other-weekly",
            update_interval=UpdateInterval.WEEKLY,
            size=900,
        )
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/scheduled",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == str(admin_user.tenant_id)
    assert data["total_websites"] == 2
    assert data["total_size_bytes"] == 350
    assert [bucket["update_interval"] for bucket in data["buckets"]] == (
        EXPECTED_INTERVAL_ORDER
    )
    by_interval = {bucket["update_interval"]: bucket for bucket in data["buckets"]}
    assert by_interval[UpdateInterval.DAILY.value] == {
        "update_interval": UpdateInterval.DAILY.value,
        "website_count": 1,
        "total_size_bytes": 100,
    }
    assert by_interval[UpdateInterval.NEVER.value] == {
        "update_interval": UpdateInterval.NEVER.value,
        "website_count": 1,
        "total_size_bytes": 250,
    }
    assert by_interval[UpdateInterval.WEEKLY.value] == {
        "update_interval": UpdateInterval.WEEKLY.value,
        "website_count": 0,
        "total_size_bytes": 0,
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_scheduled_aggregate_counts_unparseable_intervals(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="legacy",
            update_interval="monthly",
            size=700,
        )
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/scheduled",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["buckets"] == _empty_buckets()
    assert data["total_websites"] == 1
    assert data["total_size_bytes"] == 700
    assert data["unparseable_update_interval_website_count"] == 1
    assert data["unparseable_update_interval_total_size_bytes"] == 700


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_scheduled_aggregate_rejects_non_admin_user(
    client,
    db_container,
    db_session,
    user_factory,
    admin_user,
):
    async with db_session() as session:
        regular_user = await user_factory(
            session,
            tenant_id=admin_user.tenant_id,
            email=f"regular-scheduled-{uuid4()}@example.com",
        )
        regular_user_id = regular_user.id
        await session.commit()

    async with db_container() as container:
        api_key = await container.auth_service().create_user_api_key(
            prefix="test", user_id=regular_user_id, delete_old=True
        )

    response = await client.get(
        "/api/v1/admin/crawler/scheduled",
        headers={"X-API-Key": api_key.key},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_scheduled_aggregate_has_no_tenant_id_query_parameter(app):
    operation = app.openapi()["paths"]["/api/v1/admin/crawler/scheduled"]["get"]
    query_parameters = {
        parameter["name"]
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "query"
    }

    assert "tenant_id" not in query_parameters
