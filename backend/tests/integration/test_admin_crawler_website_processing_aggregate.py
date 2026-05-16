from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.job_table import Jobs
from intric.database.tables.websites_table import CrawlRuns, Websites
from intric.jobs.job_models import Task
from intric.main.models import Status
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import UpdateInterval


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
    name: str | None,
    update_interval: UpdateInterval = UpdateInterval.NEVER,
) -> Websites:
    website = Websites(
        id=uuid4(),
        name=name,
        url=f"https://tenant-processing-{uuid4()}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=update_interval,
        size=0,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
    )
    session.add(website)
    await session.flush()
    return website


async def _create_job(
    session,
    *,
    user_id: UUID,
    status: Status,
    created_at: datetime,
    finished_at: datetime | None,
) -> Jobs:
    job = Jobs(
        id=uuid4(),
        user_id=user_id,
        task=Task.CRAWL.value,
        status=status.value,
        result_location=None,
        name="Tenant crawler processing aggregate test",
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
    user_id: UUID,
    website_id: UUID,
    created_at: datetime,
    status: Status,
    pages_crawled: int = 0,
    files_downloaded: int = 0,
    pages_failed: int = 0,
    files_failed: int = 0,
    pages_source_retained: int = 0,
    pages_hash_retained: int = 0,
    files_hash_retained: int = 0,
    files_too_large_skipped: int = 0,
) -> CrawlRuns:
    finished_at = created_at + timedelta(seconds=10)
    job = await _create_job(
        session,
        user_id=user_id,
        status=status,
        created_at=created_at,
        finished_at=finished_at,
    )
    crawl_run = CrawlRuns(
        id=uuid4(),
        created_at=created_at,
        updated_at=created_at,
        tenant_id=tenant_id,
        website_id=website_id,
        job_id=job.id,
        pages_crawled=pages_crawled,
        files_downloaded=files_downloaded,
        pages_failed=pages_failed,
        files_failed=files_failed,
        pages_source_retained=pages_source_retained,
        pages_hash_retained=pages_hash_retained,
        files_hash_retained=files_hash_retained,
        files_too_large_skipped=files_too_large_skipped,
    )
    session.add(crawl_run)
    await session.flush()
    return crawl_run


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_website_processing_aggregate_is_tenant_scoped(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    tenant_factory,
    user_factory,
):
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name="Expensive crawler website",
            update_interval=UpdateInterval.DAILY,
        )
        other_website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name=None,
        )
        outside_tenant = await tenant_factory(session, name="Outside crawler tenant")
        outside_user = await user_factory(session, tenant_id=outside_tenant.id)
        outside_website = await _create_website(
            session,
            tenant_id=outside_tenant.id,
            user_id=outside_user.id,
            embedding_model_id=embedding_model_id,
            name="Outside tenant website",
        )

        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=website.id,
            created_at=now - timedelta(hours=2),
            status=Status.COMPLETE,
            pages_crawled=10,
            files_downloaded=2,
            pages_hash_retained=8,
            files_hash_retained=1,
            files_too_large_skipped=3,
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=website.id,
            created_at=now - timedelta(hours=1),
            status=Status.FAILED,
            pages_crawled=1,
            pages_failed=1,
            files_failed=2,
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=other_website.id,
            created_at=now - timedelta(minutes=30),
            status=Status.COMPLETE,
            pages_source_retained=4,
        )
        await _create_crawl_run(
            session,
            tenant_id=outside_tenant.id,
            user_id=outside_user.id,
            website_id=outside_website.id,
            created_at=now - timedelta(minutes=15),
            status=Status.COMPLETE,
            pages_crawled=99,
        )
        website_id = website.id
        other_website_id = other_website.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/website-processing",
        params={"days": 7, "limit": 10, "offset": 0},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["limit"] == 10
    assert data["offset"] == 0
    assert data["days"] == 7
    assert "tenant_id" not in data
    assert [item["website_id"] for item in data["items"]] == [
        str(website_id),
        str(other_website_id),
    ]

    primary = data["items"][0]
    assert primary["website_name"] == "Expensive crawler website"
    assert "tenant_id" not in primary
    assert primary["total_runs"] == 2
    assert primary["terminal_runs"] == 2
    assert primary["failed_runs"] == 1
    assert primary["pages_crawled"] == 11
    assert primary["files_downloaded"] == 2
    assert primary["pages_hash_retained"] == 8
    assert primary["files_hash_retained"] == 1
    assert primary["files_too_large_skipped"] == 3
    assert primary["pages_failed"] == 1
    assert primary["files_failed"] == 2
    assert primary["update_interval"] == UpdateInterval.DAILY.value
    assert primary["schedule_frequency_weight"] == 7.0
    assert primary["indexed_content_count"] == 22
    assert primary["retention_rate"] == pytest.approx(9 / 22)
    assert primary["cost_pressure_score"] == pytest.approx(91.0)

    secondary = data["items"][1]
    assert secondary["website_name"] is None
    assert secondary["pages_source_retained"] == 4


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_website_processing_aggregate_rejects_invalid_bounds(
    client,
    admin_user_api_key,
):
    invalid_days_response = await client.get(
        "/api/v1/admin/crawler/website-processing",
        params={"days": 31},
        headers={"X-API-Key": admin_user_api_key.key},
    )
    invalid_limit_response = await client.get(
        "/api/v1/admin/crawler/website-processing",
        params={"limit": 201},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert invalid_days_response.status_code == 422
    assert invalid_limit_response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_website_processing_aggregate_filters_by_website_id(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """`?website_id=` narrows the per-website 7-day aggregate.

    Seeds two websites in the same tenant, each with one finished
    crawl run. The filter must return exactly the requested website's
    bucket; the other website's stats must not bleed in. Combined
    with the existing tenant predicate the filter never widens the
    visibility scope. Uses real time so the seeded `created_at`
    stays inside the rolling 7-day window.
    """
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website_a = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name="Website A",
        )
        website_b = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name="Website B",
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=website_a.id,
            created_at=now - timedelta(hours=4),
            status=Status.COMPLETE,
            pages_crawled=10,
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=website_b.id,
            created_at=now - timedelta(hours=3),
            status=Status.COMPLETE,
            pages_crawled=5,
        )
        website_a_id = website_a.id
        website_b_id = website_b.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/website-processing",
        params={"days": 7, "limit": 50, "website_id": str(website_a_id)},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    returned = {item["website_id"] for item in data["items"]}
    assert str(website_a_id) in returned
    assert str(website_b_id) not in returned
