from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.job_table import Jobs
from intric.database.tables.websites_table import CrawlRuns, Websites
from intric.jobs.job_models import Task
from intric.main.models import Status
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode, FailureReason
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
    tenant_id: UUID,
    user_id: UUID,
    embedding_model_id: UUID,
    url_suffix: str,
    name: str | None,
) -> Websites:
    website = Websites(
        name=name,
        url=f"https://recent-failure-{url_suffix}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=UpdateInterval.NEVER,
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
        name="Crawler recent failures test",
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
    outcome_code: CrawlOutcomeCode | None,
    failure_summary: dict[str, int] | None = None,
    pages_crawled: int | None = None,
    pages_failed: int | None = None,
) -> CrawlRuns:
    crawl_run = CrawlRuns(
        id=uuid4(),
        created_at=created_at,
        updated_at=created_at,
        tenant_id=tenant_id,
        website_id=website_id,
        job_id=job_id,
        pages_crawled=pages_crawled,
        files_downloaded=0,
        pages_failed=pages_failed,
        files_failed=0,
        pages_source_retained=0,
        pages_hash_retained=0,
        files_hash_retained=0,
        files_too_large_skipped=0,
        outcome_code=outcome_code.value if outcome_code is not None else None,
        failure_summary=failure_summary,
    )
    session.add(crawl_run)
    await session.flush()
    return crawl_run


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_recent_failures_empty_window(
    client,
    super_admin_token,
):
    response = await client.get(
        "/api/v1/sysadmin/crawler/recent-failures",
        params={"days": 7},
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert data["days"] == 7
    assert _parse_response_datetime(data["since"]) < _parse_response_datetime(
        data["until"]
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_recent_failures_lists_terminal_failures(
    client,
    db_session,
    tenant_factory,
    user_factory,
    super_admin_token,
):
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        tenant = await tenant_factory(session, name="Crawler recent failure tenant")
        tenant.display_name = "Recent Failure Display"
        user = await user_factory(session, tenant_id=tenant.id)
        other_tenant = await tenant_factory(
            session, name="Other crawler recent failure tenant"
        )
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        website = await _create_website(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="primary",
            name="Recent failure primary",
        )
        null_label_website = await _create_website(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="null-labels",
            name=None,
        )

        newest_job = await _create_job(
            session,
            user_id=user.id,
            status=Status.FAILED,
            created_at=now - timedelta(minutes=1),
            finished_at=now - timedelta(minutes=1),
        )
        newest_run = await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            website_id=website.id,
            job_id=newest_job.id,
            created_at=newest_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
            failure_summary={
                FailureReason.DB_ERROR.value: 2,
                "LEGACY_UNKNOWN": 3,
            },
            pages_failed=2,
        )
        middle_job = await _create_job(
            session,
            user_id=user.id,
            status=Status.FAILED,
            created_at=now - timedelta(minutes=2),
            finished_at=now - timedelta(minutes=2),
        )
        middle_run = await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            website_id=website.id,
            job_id=middle_job.id,
            created_at=middle_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
        )
        other_job = await _create_job(
            session,
            user_id=other_user.id,
            status=Status.FAILED,
            created_at=now - timedelta(minutes=3),
            finished_at=now - timedelta(minutes=3),
        )
        other_run = await _create_crawl_run(
            session,
            tenant_id=other_tenant.id,
            website_id=null_label_website.id,
            job_id=other_job.id,
            created_at=other_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_PARTIAL_TIMEOUT,
        )
        success_job = await _create_job(
            session,
            user_id=user.id,
            status=Status.COMPLETE,
            created_at=now - timedelta(minutes=4),
            finished_at=now - timedelta(minutes=4),
        )
        success_run = await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            website_id=website.id,
            job_id=success_job.id,
            created_at=success_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_ALL_UNCHANGED,
            pages_crawled=3,
        )
        in_progress_job = await _create_job(
            session,
            user_id=user.id,
            status=Status.IN_PROGRESS,
            created_at=now - timedelta(minutes=5),
            finished_at=None,
        )
        in_progress_run = await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            website_id=website.id,
            job_id=in_progress_job.id,
            created_at=in_progress_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
        )
        stale_job = await _create_job(
            session,
            user_id=user.id,
            status=Status.FAILED,
            created_at=now - timedelta(days=8),
            finished_at=now - timedelta(days=8),
        )
        stale_run = await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            website_id=website.id,
            job_id=stale_job.id,
            created_at=stale_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
        )
        future_job = await _create_job(
            session,
            user_id=user.id,
            status=Status.FAILED,
            created_at=now + timedelta(days=1),
            finished_at=now + timedelta(days=1),
        )
        future_run = await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            website_id=website.id,
            job_id=future_job.id,
            created_at=future_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
        )

        newest_run_id = newest_run.id
        middle_run_id = middle_run.id
        other_run_id = other_run.id
        success_run_id = success_run.id
        in_progress_run_id = in_progress_run.id
        stale_run_id = stale_run.id
        future_run_id = future_run.id
        tenant_id = tenant.id
        await session.commit()

    response = await client.get(
        "/api/v1/sysadmin/crawler/recent-failures",
        params={"days": 7, "limit": 10, "offset": 0},
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert [item["crawl_run_id"] for item in data["items"]] == [
        str(newest_run_id),
        str(middle_run_id),
        str(other_run_id),
    ]
    by_run_id = {item["crawl_run_id"]: item for item in data["items"]}
    assert by_run_id[str(newest_run_id)]["outcome_code"] == (
        CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT.value
    )
    assert by_run_id[str(newest_run_id)]["failure_summary"] == {
        FailureReason.DB_ERROR.value: 2
    }
    assert by_run_id[str(newest_run_id)]["website_name"] == "Recent failure primary"
    assert by_run_id[str(newest_run_id)]["tenant_display_name"] == (
        "Recent Failure Display"
    )
    assert by_run_id[str(other_run_id)]["website_name"] is None
    assert by_run_id[str(other_run_id)]["tenant_display_name"] is None
    assert str(success_run_id) not in by_run_id
    assert str(in_progress_run_id) not in by_run_id
    assert str(stale_run_id) not in by_run_id
    assert str(future_run_id) not in by_run_id
    assert _parse_response_datetime(data["since"]) < _parse_response_datetime(
        data["until"]
    )

    tenant_response = await client.get(
        "/api/v1/sysadmin/crawler/recent-failures",
        params={"tenant_id": str(tenant_id), "days": 7, "limit": 10, "offset": 0},
        headers={"X-API-Key": super_admin_token},
    )

    assert tenant_response.status_code == 200
    tenant_data = tenant_response.json()
    assert tenant_data["total"] == 2
    assert [item["crawl_run_id"] for item in tenant_data["items"]] == [
        str(newest_run_id),
        str(middle_run_id),
    ]

    page_response = await client.get(
        "/api/v1/sysadmin/crawler/recent-failures",
        params={"days": 7, "limit": 1, "offset": 1},
        headers={"X-API-Key": super_admin_token},
    )

    assert page_response.status_code == 200
    page_data = page_response.json()
    assert page_data["total"] == 3
    assert page_data["limit"] == 1
    assert page_data["offset"] == 1
    assert [item["crawl_run_id"] for item in page_data["items"]] == [str(middle_run_id)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_recent_failures_rejects_unbounded_params(
    client,
    super_admin_token,
):
    limit_response = await client.get(
        "/api/v1/sysadmin/crawler/recent-failures",
        params={"limit": 201},
        headers={"X-API-Key": super_admin_token},
    )
    days_response = await client.get(
        "/api/v1/sysadmin/crawler/recent-failures",
        params={"days": 31},
        headers={"X-API-Key": super_admin_token},
    )

    assert limit_response.status_code == 422
    assert days_response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_recent_failures_requires_super_api_key(client):
    response = await client.get("/api/v1/sysadmin/crawler/recent-failures")

    assert response.status_code in {401, 403}
