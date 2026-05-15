from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

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
) -> Websites:
    website = Websites(
        name=name or f"Tenant crawler failure {url_suffix}",
        url=f"https://tenant-failure-{url_suffix}.example.com",
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
async def test_admin_crawler_failure_inventory_is_scoped_to_current_tenant(
    client,
    db_session,
    tenant_factory,
    user_factory,
    admin_user,
    admin_user_api_key,
):
    now = datetime(2026, 5, 15, 8, 0, tzinfo=timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        other_tenant = await tenant_factory(session, name="Other crawler tenant")
        other_user = await user_factory(session, tenant_id=other_tenant.id)

        auto_disabled = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="auto-disabled",
            update_interval=UpdateInterval.NEVER,
            consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
        )
        backed_off = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="backed-off",
            update_interval=UpdateInterval.DAILY,
            consecutive_failures=3,
            next_retry_at=now + timedelta(hours=2),
        )
        other_backed_off = await _create_website(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="other-backed-off",
            update_interval=UpdateInterval.DAILY,
            consecutive_failures=5,
            next_retry_at=now + timedelta(hours=1),
        )
        no_retry = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="no-retry",
            update_interval=UpdateInterval.DAILY,
            consecutive_failures=2,
        )
        manual_never = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="manual-never",
            update_interval=UpdateInterval.NEVER,
            consecutive_failures=0,
        )
        healthy = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="healthy",
            update_interval=UpdateInterval.WEEKLY,
            consecutive_failures=0,
        )

        auto_disabled_id = auto_disabled.id
        backed_off_id = backed_off.id
        other_backed_off_id = other_backed_off.id
        no_retry_id = no_retry.id
        manual_never_id = manual_never.id
        healthy_id = healthy.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/failure-inventory",
        params={"limit": 10, "offset": 0},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["limit"] == 10
    assert data["offset"] == 0

    by_website_id = {item["website_id"]: item for item in data["items"]}
    assert set(by_website_id) == {
        str(auto_disabled_id),
        str(backed_off_id),
    }
    assert str(other_backed_off_id) not in by_website_id
    assert str(no_retry_id) not in by_website_id
    assert str(manual_never_id) not in by_website_id
    assert str(healthy_id) not in by_website_id

    assert by_website_id[str(auto_disabled_id)]["state"] == "AUTO_DISABLED"
    assert by_website_id[str(auto_disabled_id)]["website_name"] == (
        "Tenant crawler failure auto-disabled"
    )
    assert by_website_id[str(auto_disabled_id)]["consecutive_failures"] == (
        WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD
    )
    assert by_website_id[str(auto_disabled_id)]["next_retry_at"] is None
    assert "tenant_id" not in by_website_id[str(auto_disabled_id)]
    assert "tenant_display_name" not in by_website_id[str(auto_disabled_id)]

    assert by_website_id[str(backed_off_id)]["state"] == "BACKED_OFF"
    assert by_website_id[str(backed_off_id)]["consecutive_failures"] == 3
    assert by_website_id[str(backed_off_id)]["next_retry_at"] is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_failure_inventory_rejects_non_admin_user(
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
            email=f"regular-failure-inventory-{uuid4()}@example.com",
        )
        regular_user_id = regular_user.id
        await session.commit()

    async with db_container() as container:
        api_key = await container.auth_service().create_user_api_key(
            prefix="test", user_id=regular_user_id, delete_old=True
        )

    response = await client.get(
        "/api/v1/admin/crawler/failure-inventory",
        headers={"X-API-Key": api_key.key},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_failure_inventory_rejects_unbounded_params(
    client,
    admin_user_api_key,
):
    response = await client.get(
        "/api/v1/admin/crawler/failure-inventory",
        params={"limit": 201},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_failure_inventory_has_no_tenant_id_query_parameter(app):
    operation = app.openapi()["paths"]["/api/v1/admin/crawler/failure-inventory"]["get"]
    query_params = [
        param["name"]
        for param in operation.get("parameters", [])
        if param["in"] == "query"
    ]

    assert "tenant_id" not in query_params
