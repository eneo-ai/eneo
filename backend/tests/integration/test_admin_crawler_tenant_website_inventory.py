"""Integration tests for the tenant-wide website governance inventory.

The /admin/crawler/websites endpoint underpins the admin Webbplatser tab.
Unlike the failure inventory (only websites currently broken) or the
website-processing aggregate (only websites with activity in the last N
days), this endpoint returns *every* website in the tenant so an admin
can search, filter by interval, and drill into a website's details
regardless of recent activity.

Tests cover:
- tenant isolation (websites from another tenant are not visible)
- search OR-matches url/name/owner_email
- update_interval filter narrows to one bucket
- space_id filter narrows to one space
- owner_user_id filter narrows to one creator
- failure_state filter mirrors the existing CrawlerFailureState classification
- pagination contract (limit/offset/total)
- the endpoint has no tenant_id query parameter (forces current-tenant scope)
- non-admin users are forbidden
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.spaces_table import Spaces
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


async def _create_space(session, *, tenant_id: UUID, name: str) -> Spaces:
    """Create a child space inside the given tenant.

    Spaces inside the same tenant need a parent ``tenant_space_id`` to avoid
    the (tenant_id, NULL, NULL) uniqueness constraint on org spaces. The
    helper guarantees an org space exists for ``tenant_id`` and threads the
    new space under it.
    """
    org_space = (
        await session.execute(
            sa.select(Spaces).where(
                (Spaces.tenant_id == tenant_id)
                & (Spaces.user_id.is_(None))
                & (Spaces.tenant_space_id.is_(None))
            )
        )
    ).scalar_one_or_none()
    if org_space is None:
        org_space = Spaces(
            name=f"Org Space for {tenant_id}",
            tenant_id=tenant_id,
            user_id=None,
            tenant_space_id=None,
        )
        session.add(org_space)
        await session.flush()

    space = Spaces(
        name=name,
        tenant_id=tenant_id,
        tenant_space_id=org_space.id,
    )
    session.add(space)
    await session.flush()
    return space


async def _create_website(
    session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    embedding_model_id: UUID,
    url_suffix: str,
    update_interval: UpdateInterval,
    consecutive_failures: int = 0,
    next_retry_at: datetime | None = None,
    last_crawled_at: datetime | None = None,
    size_bytes: int = 0,
    name: str | None = None,
    space_id: UUID | None = None,
) -> Websites:
    website = Websites(
        name=name,
        url=f"https://tenant-inventory-{url_suffix}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=update_interval,
        size=size_bytes,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
        consecutive_failures=consecutive_failures,
        next_retry_at=next_retry_at,
        last_crawled_at=last_crawled_at,
        space_id=space_id,
    )
    session.add(website)
    await session.flush()
    return website


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_tenant_website_inventory_scopes_to_current_tenant(
    client,
    db_session,
    tenant_factory,
    user_factory,
    admin_user,
    admin_user_api_key,
):
    """Default-filter response only returns websites owned by the admin's tenant.

    The admin's tenant gets three websites (one daily, one weekly, one
    paused). A second tenant gets two websites. The endpoint must return
    exactly three items with `total == 3`.
    """
    now = datetime(2026, 5, 15, 8, 0, tzinfo=timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        other_tenant = await tenant_factory(session, name="Other inventory tenant")
        other_user = await user_factory(session, tenant_id=other_tenant.id)

        admin_daily = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="admin-daily",
            update_interval=UpdateInterval.DAILY,
            last_crawled_at=now - timedelta(hours=2),
            size_bytes=10_240,
            name="Admin daily",
        )
        admin_weekly = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="admin-weekly",
            update_interval=UpdateInterval.WEEKLY,
            last_crawled_at=now - timedelta(days=4),
            size_bytes=512_000,
            name="Admin weekly",
        )
        admin_paused = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="admin-paused",
            update_interval=UpdateInterval.NEVER,
            size_bytes=0,
            name="Admin paused",
        )
        other_daily = await _create_website(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="other-daily",
            update_interval=UpdateInterval.DAILY,
        )
        other_weekly = await _create_website(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="other-weekly",
            update_interval=UpdateInterval.WEEKLY,
        )

        admin_daily_id = admin_daily.id
        admin_weekly_id = admin_weekly.id
        admin_paused_id = admin_paused.id
        other_daily_id = other_daily.id
        other_weekly_id = other_weekly.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/websites",
        params={"limit": 25, "offset": 0},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 3
    assert data["limit"] == 25
    assert data["offset"] == 0

    by_id = {item["website_id"]: item for item in data["items"]}
    assert set(by_id) == {
        str(admin_daily_id),
        str(admin_weekly_id),
        str(admin_paused_id),
    }
    assert str(other_daily_id) not in by_id
    assert str(other_weekly_id) not in by_id

    daily_item = by_id[str(admin_daily_id)]
    assert daily_item["url"].endswith("admin-daily.example.com")
    assert daily_item["name"] == "Admin daily"
    assert daily_item["update_interval"] == UpdateInterval.DAILY.value
    assert daily_item["size"] == 10_240
    assert daily_item["owner_user_id"] == str(admin_user.id)
    assert daily_item["owner_email"] == admin_user.email
    assert daily_item["failure_state"] is None
    # tenant_id of other tenant must not leak via attribution columns
    assert "tenant_id" not in daily_item


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_tenant_website_inventory_filters_by_update_interval(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """`update_interval=daily` narrows to daily-only websites.

    Seeds one daily and one weekly website. Asserts the daily filter returns
    only the daily row.
    """
    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        daily = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"filter-daily-{uuid4()}",
            update_interval=UpdateInterval.DAILY,
        )
        weekly = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"filter-weekly-{uuid4()}",
            update_interval=UpdateInterval.WEEKLY,
        )
        daily_id = daily.id
        weekly_id = weekly.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/websites",
        params={"limit": 25, "update_interval": UpdateInterval.DAILY.value},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    returned = {item["website_id"] for item in data["items"]}
    assert str(daily_id) in returned
    assert str(weekly_id) not in returned


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_tenant_website_inventory_search_or_matches_url_and_name(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """`search=foo` returns rows where URL OR name contain `foo` (case-insensitive).

    Seeds a website whose URL contains "kommunhuset" and a separate one
    whose name contains "Kommunhuset" but with a different URL. Both
    should match the same search term.
    """
    suffix = uuid4().hex[:8]
    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        url_match = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"kommunhuset-{suffix}",
            update_interval=UpdateInterval.WEEKLY,
            name=None,
        )
        name_match = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"other-{suffix}",
            update_interval=UpdateInterval.WEEKLY,
            name=f"Kommunhuset extern {suffix}",
        )
        unrelated = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"library-{suffix}",
            update_interval=UpdateInterval.WEEKLY,
            name="Library",
        )
        url_match_id = url_match.id
        name_match_id = name_match.id
        unrelated_id = unrelated.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/websites",
        params={"limit": 25, "search": "kommunhuset"},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    returned = {item["website_id"] for item in data["items"]}
    assert str(url_match_id) in returned
    assert str(name_match_id) in returned
    assert str(unrelated_id) not in returned


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_tenant_website_inventory_filters_by_failure_state(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """`failure_state=AUTO_DISABLED` narrows to auto-disabled rows only.

    Seeds an auto-disabled (NEVER + ≥threshold consecutive failures) row,
    a backed-off (counter > 0, has next_retry_at) row, and a healthy row.
    Each filter value must return exactly its matching row.
    """
    now = datetime(2026, 5, 15, 8, 0, tzinfo=timezone.utc)
    suffix = uuid4().hex[:8]
    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        auto_disabled = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"state-disabled-{suffix}",
            update_interval=UpdateInterval.NEVER,
            consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
        )
        backed_off = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"state-backed-{suffix}",
            update_interval=UpdateInterval.DAILY,
            consecutive_failures=2,
            next_retry_at=now + timedelta(hours=2),
        )
        healthy = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"state-healthy-{suffix}",
            update_interval=UpdateInterval.WEEKLY,
            consecutive_failures=0,
        )
        auto_id = auto_disabled.id
        backed_id = backed_off.id
        healthy_id = healthy.id
        await session.commit()

    auto_resp = await client.get(
        "/api/v1/admin/crawler/websites",
        params={"limit": 25, "failure_state": "AUTO_DISABLED"},
        headers={"X-API-Key": admin_user_api_key.key},
    )
    assert auto_resp.status_code == 200, auto_resp.text
    auto_ids = {item["website_id"] for item in auto_resp.json()["items"]}
    assert str(auto_id) in auto_ids
    assert str(backed_id) not in auto_ids
    assert str(healthy_id) not in auto_ids

    backed_resp = await client.get(
        "/api/v1/admin/crawler/websites",
        params={"limit": 25, "failure_state": "BACKED_OFF"},
        headers={"X-API-Key": admin_user_api_key.key},
    )
    assert backed_resp.status_code == 200, backed_resp.text
    backed_ids = {item["website_id"] for item in backed_resp.json()["items"]}
    assert str(backed_id) in backed_ids
    assert str(auto_id) not in backed_ids
    assert str(healthy_id) not in backed_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_tenant_website_inventory_filters_by_space(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """`space_id` narrows to websites attached to the given space.

    The admin's tenant gets two spaces. One website goes to space A, one to
    space B. The filter must return only the matching space's website.
    """
    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        space_a = await _create_space(
            session, tenant_id=admin_user.tenant_id, name=f"Space A {uuid4()}"
        )
        space_b = await _create_space(
            session, tenant_id=admin_user.tenant_id, name=f"Space B {uuid4()}"
        )
        in_a = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"space-a-{uuid4()}",
            update_interval=UpdateInterval.DAILY,
            space_id=space_a.id,
        )
        in_b = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"space-b-{uuid4()}",
            update_interval=UpdateInterval.DAILY,
            space_id=space_b.id,
        )
        in_a_id = in_a.id
        in_b_id = in_b.id
        space_a_id = space_a.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/websites",
        params={"limit": 25, "space_id": str(space_a_id)},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    returned = {item["website_id"] for item in data["items"]}
    assert str(in_a_id) in returned
    assert str(in_b_id) not in returned

    in_a_item = next(
        item for item in data["items"] if item["website_id"] == str(in_a_id)
    )
    assert in_a_item["space_id"] == str(space_a_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_tenant_website_inventory_filters_by_owner(
    client,
    db_session,
    user_factory,
    admin_user,
    admin_user_api_key,
):
    """`owner_user_id` narrows to websites registered by the given user.

    Seeds one website owned by the admin and another owned by a freshly
    created user in the same tenant. The filter must return the second
    user's website only, and the admin's website must NOT appear in
    that filter.
    """
    suffix = uuid4().hex[:8]
    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        other_user = await user_factory(
            session,
            tenant_id=admin_user.tenant_id,
            email=f"other-owner-{uuid4()}@example.com",
        )
        admin_owned = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"owner-admin-{suffix}",
            update_interval=UpdateInterval.DAILY,
        )
        other_owned = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"owner-other-{suffix}",
            update_interval=UpdateInterval.DAILY,
        )
        admin_owned_id = admin_owned.id
        other_owned_id = other_owned.id
        other_user_id = other_user.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/websites",
        params={"limit": 25, "owner_user_id": str(other_user_id)},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    returned = {item["website_id"] for item in data["items"]}
    assert str(other_owned_id) in returned
    assert str(admin_owned_id) not in returned

    other_item = next(
        item for item in data["items"] if item["website_id"] == str(other_owned_id)
    )
    assert other_item["owner_user_id"] == str(other_user_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_tenant_website_inventory_rejects_non_admin_user(
    client,
    db_container,
    db_session,
    user_factory,
    admin_user,
):
    """Non-admin user gets 403, not the inventory."""
    async with db_session() as session:
        regular_user = await user_factory(
            session,
            tenant_id=admin_user.tenant_id,
            email=f"regular-inventory-{uuid4()}@example.com",
        )
        regular_user_id = regular_user.id
        await session.commit()

    async with db_container() as container:
        api_key = await container.auth_service().create_user_api_key(
            prefix="test", user_id=regular_user_id, delete_old=True
        )

    response = await client.get(
        "/api/v1/admin/crawler/websites",
        headers={"X-API-Key": api_key.key},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_tenant_website_inventory_has_no_tenant_id_query_parameter(
    app,
):
    """The endpoint must NOT accept a tenant_id query — current-user tenant only.

    Catches accidental exposure of `tenant_id` as a query parameter if a
    future refactor forgets to keep the route scope-locked.
    """
    operation = app.openapi()["paths"]["/api/v1/admin/crawler/websites"]["get"]
    query_params = [
        param["name"]
        for param in operation.get("parameters", [])
        if param["in"] == "query"
    ]

    assert "tenant_id" not in query_params
