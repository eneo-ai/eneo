from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.job_table import Jobs
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.websites_table import CrawlRuns, Websites
from intric.jobs.job_models import Task
from intric.main.models import Status
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
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
    org_space = (
        await session.execute(
            sa.select(Spaces).where(
                Spaces.tenant_id == tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
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
    consecutive_failures: int,
    next_retry_at: datetime | None = None,
    name: str | None = None,
    space_id: UUID | None = None,
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
        space_id=space_id,
    )
    session.add(website)
    await session.flush()
    return website


async def _create_job(
    session,
    *,
    user_id: UUID,
    created_at: datetime,
    finished_at: datetime,
) -> Jobs:
    job = Jobs(
        id=uuid4(),
        user_id=user_id,
        task=Task.CRAWL.value,
        status=Status.FAILED.value,
        result_location=None,
        name="Admin crawler failure inventory test",
        finished_at=finished_at,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(job)
    await session.flush()
    return job


async def _create_crawl_run(
    session,
    *,
    tenant_id: UUID,
    website_id: UUID,
    job_id: UUID,
    created_at: datetime,
    outcome_code: CrawlOutcomeCode,
) -> CrawlRuns:
    crawl_run = CrawlRuns(
        id=uuid4(),
        created_at=created_at,
        updated_at=created_at,
        tenant_id=tenant_id,
        website_id=website_id,
        job_id=job_id,
        pages_crawled=0,
        files_downloaded=0,
        pages_failed=0,
        files_failed=0,
        pages_source_retained=0,
        pages_hash_retained=0,
        files_hash_retained=0,
        files_too_large_skipped=0,
        outcome_code=outcome_code.value,
    )
    session.add(crawl_run)
    await session.flush()
    return crawl_run


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
async def test_admin_crawler_failure_inventory_includes_attribution_and_latest_failure(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        space = await _create_space(
            session,
            tenant_id=admin_user.tenant_id,
            name="Blocked website triage space",
        )
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="latest-failure",
            update_interval=UpdateInterval.DAILY,
            consecutive_failures=2,
            next_retry_at=now + timedelta(hours=1),
            space_id=space.id,
        )
        older_job = await _create_job(
            session,
            user_id=admin_user.id,
            created_at=now - timedelta(hours=4),
            finished_at=now - timedelta(hours=4),
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=older_job.id,
            created_at=older_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
        )
        latest_job = await _create_job(
            session,
            user_id=admin_user.id,
            created_at=now - timedelta(minutes=30),
            finished_at=now - timedelta(minutes=30),
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=latest_job.id,
            created_at=latest_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
        )
        website_id = website.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/failure-inventory",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    by_website_id = {item["website_id"]: item for item in response.json()["items"]}
    item = by_website_id[str(website_id)]
    assert item["space_name"] == "Blocked website triage space"
    assert item["owner_email"] == admin_user.email
    assert item["latest_failure_outcome_code"] == "CRAWL_RUNTIME_TIMEOUT"
    assert item["latest_failure_at"] is not None


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
