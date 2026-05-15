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
        url=f"https://admin-recent-failure-{url_suffix}.example.com",
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
        name="Admin crawler recent failures test",
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
        outcome_code=outcome_code.value if outcome_code is not None else None,
        failure_summary=failure_summary,
    )
    session.add(crawl_run)
    await session.flush()
    return crawl_run


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_recent_failures_empty_window(
    client,
    admin_user_api_key,
):
    response = await client.get(
        "/api/v1/admin/crawler/recent-failures",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert data["days"] == 7


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_recent_failures_is_scoped_to_current_tenant(
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
        other_tenant = await tenant_factory(session, name="Other crawler admin tenant")
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        own_website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="own",
            name="Own admin recent failure",
        )
        other_website = await _create_website(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="other",
            name="Other admin recent failure",
        )
        own_job = await _create_job(
            session,
            user_id=admin_user.id,
            status=Status.FAILED,
            created_at=now - timedelta(minutes=1),
            finished_at=now - timedelta(minutes=1),
        )
        own_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=own_website.id,
            job_id=own_job.id,
            created_at=own_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
            failure_summary={
                FailureReason.DB_ERROR.value: 2,
                "LEGACY_UNKNOWN": 3,
            },
        )
        other_job = await _create_job(
            session,
            user_id=other_user.id,
            status=Status.FAILED,
            created_at=now - timedelta(minutes=2),
            finished_at=now - timedelta(minutes=2),
        )
        other_run = await _create_crawl_run(
            session,
            tenant_id=other_tenant.id,
            website_id=other_website.id,
            job_id=other_job.id,
            created_at=other_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
        )
        own_run_id = own_run.id
        other_run_id = other_run.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/recent-failures",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert [item["crawl_run_id"] for item in data["items"]] == [str(own_run_id)]
    assert data["items"][0]["failure_summary"] == {FailureReason.DB_ERROR.value: 2}
    assert str(other_run_id) not in {item["crawl_run_id"] for item in data["items"]}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_recent_failures_rejects_non_admin_user(
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
            email=f"regular-{uuid4()}@example.com",
        )
        regular_user_id = regular_user.id
        await session.commit()

    async with db_container() as container:
        api_key = await container.auth_service().create_user_api_key(
            prefix="test", user_id=regular_user_id, delete_old=True
        )

    response = await client.get(
        "/api/v1/admin/crawler/recent-failures",
        headers={"X-API-Key": api_key.key},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_recent_failures_has_no_tenant_id_query_parameter(app):
    operation = app.openapi()["paths"]["/api/v1/admin/crawler/recent-failures"]["get"]
    query_parameters = {
        parameter["name"]
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "query"
    }

    assert {"days", "limit", "offset"}.issubset(query_parameters)
    assert "tenant_id" not in query_parameters
