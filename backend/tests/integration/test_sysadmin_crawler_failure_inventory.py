from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.websites_table import Websites
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import (
    WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    UpdateInterval,
)


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
    consecutive_failures: int,
    next_retry_at: datetime | None = None,
    name: str | None = None,
    use_default_name: bool = True,
) -> Websites:
    website_name = name
    if website_name is None and use_default_name:
        website_name = f"Crawler failure {url_suffix}"
    website = Websites(
        name=website_name,
        url=f"https://failure-{url_suffix}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=update_interval,
        size=0,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
        consecutive_failures=consecutive_failures,
        next_retry_at=next_retry_at,
    )
    session.add(website)
    await session.flush()
    return website


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_failure_inventory_lists_failure_states(
    client,
    db_session,
    tenant_factory,
    user_factory,
    super_admin_token,
):
    now = datetime(2026, 5, 15, 8, 0, tzinfo=timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        tenant = await tenant_factory(session, name="Crawler failure tenant")
        tenant.display_name = "Crawler Failure Display"
        user = await user_factory(session, tenant_id=tenant.id)
        other_tenant = await tenant_factory(
            session, name="Other crawler failure tenant"
        )
        other_user = await user_factory(session, tenant_id=other_tenant.id)

        auto_disabled = await _create_website(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="auto-disabled",
            update_interval=UpdateInterval.NEVER,
            consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
        )
        backed_off = await _create_website(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="backed-off",
            update_interval=UpdateInterval.DAILY,
            consecutive_failures=3,
            next_retry_at=now + timedelta(hours=2),
        )
        null_labels = await _create_website(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="null-labels",
            update_interval=UpdateInterval.DAILY,
            consecutive_failures=1,
            next_retry_at=now + timedelta(hours=1),
            use_default_name=False,
        )
        no_retry = await _create_website(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="no-retry",
            update_interval=UpdateInterval.DAILY,
            consecutive_failures=2,
        )
        manual_never = await _create_website(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="manual-never",
            update_interval=UpdateInterval.NEVER,
            consecutive_failures=0,
        )
        healthy = await _create_website(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="healthy",
            update_interval=UpdateInterval.WEEKLY,
            consecutive_failures=0,
        )

        auto_disabled_id = auto_disabled.id
        backed_off_id = backed_off.id
        null_labels_id = null_labels.id
        no_retry_id = no_retry.id
        manual_never_id = manual_never.id
        healthy_id = healthy.id
        tenant_id = tenant.id
        await session.commit()

    response = await client.get(
        "/api/v1/sysadmin/crawler/failure-inventory",
        params={"limit": 10, "offset": 0},
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    by_website_id = {item["website_id"]: item for item in data["items"]}
    assert set(by_website_id) == {
        str(auto_disabled_id),
        str(backed_off_id),
        str(null_labels_id),
    }
    assert [item["website_id"] for item in data["items"]] == [
        str(auto_disabled_id),
        str(backed_off_id),
        str(null_labels_id),
    ]
    assert str(no_retry_id) not in by_website_id
    assert str(manual_never_id) not in by_website_id
    assert str(healthy_id) not in by_website_id

    assert by_website_id[str(auto_disabled_id)]["state"] == "AUTO_DISABLED"
    assert by_website_id[str(auto_disabled_id)]["website_name"] == (
        "Crawler failure auto-disabled"
    )
    assert by_website_id[str(auto_disabled_id)]["tenant_display_name"] == (
        "Crawler Failure Display"
    )
    assert by_website_id[str(auto_disabled_id)]["consecutive_failures"] == (
        WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD
    )
    assert by_website_id[str(auto_disabled_id)]["next_retry_at"] is None

    assert by_website_id[str(backed_off_id)]["state"] == "BACKED_OFF"
    assert by_website_id[str(backed_off_id)]["consecutive_failures"] == 3
    assert by_website_id[str(backed_off_id)]["next_retry_at"] is not None

    assert by_website_id[str(null_labels_id)]["state"] == "BACKED_OFF"
    assert by_website_id[str(null_labels_id)]["website_name"] is None
    assert by_website_id[str(null_labels_id)]["tenant_display_name"] is None

    tenant_response = await client.get(
        "/api/v1/sysadmin/crawler/failure-inventory",
        params={"tenant_id": str(tenant_id), "limit": 10, "offset": 0},
        headers={"X-API-Key": super_admin_token},
    )

    assert tenant_response.status_code == 200
    tenant_data = tenant_response.json()
    assert tenant_data["total"] == 2
    assert {item["website_id"] for item in tenant_data["items"]} == {
        str(auto_disabled_id),
        str(backed_off_id),
    }

    page_response = await client.get(
        "/api/v1/sysadmin/crawler/failure-inventory",
        params={"limit": 1, "offset": 1},
        headers={"X-API-Key": super_admin_token},
    )

    assert page_response.status_code == 200
    page_data = page_response.json()
    assert page_data["total"] == 3
    assert page_data["limit"] == 1
    assert page_data["offset"] == 1
    assert len(page_data["items"]) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_failure_inventory_rejects_unbounded_limit(
    client,
    super_admin_token,
):
    response = await client.get(
        "/api/v1/sysadmin/crawler/failure-inventory",
        params={"limit": 201},
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_failure_inventory_requires_super_api_key(client):
    response = await client.get("/api/v1/sysadmin/crawler/failure-inventory")

    assert response.status_code in {401, 403}
