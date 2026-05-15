from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.job_table import Jobs
from intric.database.tables.websites_table import CrawlRuns, Websites
from intric.jobs.job_models import Task
from intric.main.models import Status
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import UpdateInterval


def _parse_response_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _embedding_model_id(session) -> UUID:
    embedding_model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
    assert embedding_model_id is not None
    return embedding_model_id


async def _create_website(
    session,
    *,
    website_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    embedding_model_id: UUID,
    url_suffix: str,
    name: str | None,
    update_interval: UpdateInterval = UpdateInterval.NEVER,
) -> Websites:
    website = Websites(
        id=website_id,
        name=name,
        url=f"https://website-processing-{url_suffix}.example.com",
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
        name="Crawler website processing aggregate test",
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
    status: Status | None,
    finished_at: datetime | None,
    pages_crawled: int | None = 0,
    files_downloaded: int | None = 0,
    pages_failed: int | None = 0,
    files_failed: int | None = 0,
    pages_source_retained: int | None = 0,
    pages_hash_retained: int | None = 0,
    files_hash_retained: int | None = 0,
    files_too_large_skipped: int | None = 0,
) -> CrawlRuns:
    job_id: UUID | None = None
    if status is not None:
        job = await _create_job(
            session,
            user_id=user_id,
            status=status,
            created_at=created_at,
            finished_at=finished_at,
        )
        job_id = job.id

    crawl_run = CrawlRuns(
        id=uuid4(),
        created_at=created_at,
        updated_at=created_at,
        tenant_id=tenant_id,
        website_id=website_id,
        job_id=job_id,
        pages_crawled=pages_crawled,
        files_downloaded=files_downloaded,
        pages_failed=pages_failed,
        files_failed=files_failed,
        pages_source_retained=pages_source_retained,
        pages_hash_retained=pages_hash_retained,
        files_hash_retained=files_hash_retained,
        files_too_large_skipped=files_too_large_skipped,
        outcome_code=(
            CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR.value
            if status == Status.FAILED
            else CrawlOutcomeCode.CRAWL_ALL_UNCHANGED.value
            if status == Status.COMPLETE
            else None
        ),
    )
    session.add(crawl_run)
    await session.flush()
    return crawl_run


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_website_processing_aggregate_empty(
    client,
    super_admin_token,
):
    response = await client.get(
        "/api/v1/sysadmin/crawler/website-processing",
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert data["days"] == 7
    assert data["tenant_id"] is None
    assert _parse_response_datetime(data["since"]) < _parse_response_datetime(
        data["until"]
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_website_processing_aggregate_groups_by_website(
    client,
    db_session,
    tenant_factory,
    user_factory,
    super_admin_token,
):
    now = datetime.now(timezone.utc)
    tenant_website_a = UUID("00000000-0000-0000-0000-000000000010")
    tenant_website_b = UUID("00000000-0000-0000-0000-000000000020")
    tenant_website_orphan = UUID("00000000-0000-0000-0000-000000000030")

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        tenant = await tenant_factory(session, name="Website processing tenant")
        tenant.display_name = "Website Processing Display"
        user = await user_factory(session, tenant_id=tenant.id)
        other_tenant = await tenant_factory(
            session, name="Other website processing tenant"
        )
        other_user = await user_factory(session, tenant_id=other_tenant.id)

        await _create_website(
            session,
            website_id=tenant_website_a,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="a",
            name="Website processing A",
            update_interval=UpdateInterval.DAILY,
        )
        await _create_website(
            session,
            website_id=tenant_website_b,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="b",
            name=None,
            update_interval=UpdateInterval.WEEKLY,
        )
        await _create_website(
            session,
            website_id=tenant_website_orphan,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="orphan",
            name="Website processing orphan",
        )
        other_website = await _create_website(
            session,
            website_id=UUID("00000000-0000-0000-0000-000000000100"),
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="other",
            name="Website processing other",
        )

        inside = now - timedelta(hours=1)
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=tenant_website_a,
            created_at=inside,
            status=Status.COMPLETE,
            finished_at=inside,
            pages_crawled=5,
            files_downloaded=1,
            pages_hash_retained=2,
            files_hash_retained=1,
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=tenant_website_a,
            created_at=inside + timedelta(minutes=1),
            status=Status.FAILED,
            finished_at=inside + timedelta(minutes=1),
            pages_crawled=1,
            files_downloaded=3,
            pages_failed=4,
            files_failed=1,
            pages_source_retained=2,
            files_too_large_skipped=2,
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=tenant_website_b,
            created_at=inside,
            status=Status.COMPLETE,
            finished_at=inside,
            pages_crawled=10,
            files_downloaded=0,
            pages_hash_retained=10,
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=tenant_website_orphan,
            created_at=inside,
            status=None,
            finished_at=None,
            pages_crawled=None,
            files_downloaded=None,
            pages_failed=None,
            files_failed=None,
            pages_source_retained=None,
            pages_hash_retained=None,
            files_hash_retained=None,
            files_too_large_skipped=None,
        )
        await _create_crawl_run(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            website_id=other_website.id,
            created_at=inside,
            status=Status.COMPLETE,
            finished_at=inside,
            pages_crawled=100,
            files_downloaded=100,
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=tenant_website_a,
            created_at=now - timedelta(days=8),
            status=Status.COMPLETE,
            finished_at=now - timedelta(days=8),
            pages_crawled=100,
            files_downloaded=100,
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=tenant_website_a,
            created_at=now + timedelta(days=1),
            status=Status.COMPLETE,
            finished_at=now + timedelta(days=1),
            pages_crawled=100,
            files_downloaded=100,
        )

        tenant_id = tenant.id
        await session.commit()

    response = await client.get(
        "/api/v1/sysadmin/crawler/website-processing",
        params={"tenant_id": str(tenant_id), "limit": 2},
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["limit"] == 2
    assert data["offset"] == 0
    assert data["tenant_id"] == str(tenant_id)
    assert [item["website_id"] for item in data["items"]] == [
        str(tenant_website_a),
        str(tenant_website_b),
    ]
    assert data["items"][0] == {
        "website_id": str(tenant_website_a),
        "website_name": "Website processing A",
        "tenant_id": str(tenant_id),
        "tenant_display_name": "Website Processing Display",
        "total_runs": 2,
        "terminal_runs": 2,
        "failed_runs": 1,
        "pages_crawled": 6,
        "files_downloaded": 4,
        "pages_hash_retained": 2,
        "files_hash_retained": 1,
        "pages_source_retained": 2,
        "files_too_large_skipped": 2,
        "pages_failed": 4,
        "files_failed": 1,
        "update_interval": UpdateInterval.DAILY.value,
        "schedule_frequency_weight": 7.0,
        "indexed_content_count": 15,
        "retention_rate": pytest.approx(5 / 15),
        "cost_pressure_score": pytest.approx(70.0),
    }
    assert data["items"][1]["website_name"] is None
    assert data["items"][1]["total_runs"] == 1
    assert data["items"][1]["terminal_runs"] == 1
    assert data["items"][1]["failed_runs"] == 0
    assert data["items"][1]["pages_crawled"] == 10
    assert data["items"][1]["files_downloaded"] == 0
    assert data["items"][1]["update_interval"] == UpdateInterval.WEEKLY.value
    assert data["items"][1]["schedule_frequency_weight"] == 1.0
    assert data["items"][1]["indexed_content_count"] == 20
    assert data["items"][1]["retention_rate"] == pytest.approx(10 / 20)
    assert data["items"][1]["cost_pressure_score"] == pytest.approx(10.0)

    next_page = await client.get(
        "/api/v1/sysadmin/crawler/website-processing",
        params={"tenant_id": str(tenant_id), "limit": 2, "offset": 2},
        headers={"X-API-Key": super_admin_token},
    )

    assert next_page.status_code == 200
    next_data = next_page.json()
    assert next_data["total"] == 3
    assert next_data["offset"] == 2
    assert [item["website_id"] for item in next_data["items"]] == [
        str(tenant_website_orphan)
    ]
    assert next_data["items"][0]["total_runs"] == 1
    assert next_data["items"][0]["terminal_runs"] == 0
    assert next_data["items"][0]["failed_runs"] == 0
    assert next_data["items"][0]["pages_crawled"] == 0
    assert next_data["items"][0]["files_downloaded"] == 0
    assert next_data["items"][0]["retention_rate"] == 0.0
    assert next_data["items"][0]["cost_pressure_score"] == 0.0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_website_processing_aggregate_rejects_invalid_bounds(
    client,
    super_admin_token,
):
    too_many_days = await client.get(
        "/api/v1/sysadmin/crawler/website-processing",
        params={"days": 31},
        headers={"X-API-Key": super_admin_token},
    )
    too_large_limit = await client.get(
        "/api/v1/sysadmin/crawler/website-processing",
        params={"limit": 201},
        headers={"X-API-Key": super_admin_token},
    )

    assert too_many_days.status_code == 422
    assert too_large_limit.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_website_processing_aggregate_requires_super_api_key(
    client,
):
    response = await client.get("/api/v1/sysadmin/crawler/website-processing")

    assert response.status_code in {401, 403}
