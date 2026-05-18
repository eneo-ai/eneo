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
from intric.websites.domain.crawl_terminal_source import CrawlTerminalSource
from intric.websites.domain.website import UpdateInterval


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
    name: str,
    space_id: UUID | None = None,
) -> Websites:
    website = Websites(
        name=name,
        url=f"https://admin-failure-cluster-{url_suffix}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=UpdateInterval.WEEKLY,
        size=0,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
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
        name="Admin crawler failure cluster test",
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
    pages_crawled: int = 0,
    files_downloaded: int = 0,
    pages_failed: int = 0,
    files_failed: int = 0,
    terminal_source: CrawlTerminalSource | None = None,
) -> CrawlRuns:
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
        pages_source_retained=0,
        pages_hash_retained=0,
        files_hash_retained=0,
        files_too_large_skipped=0,
        outcome_code=outcome_code.value,
        terminal_source=terminal_source.value if terminal_source is not None else None,
    )
    session.add(crawl_run)
    await session.flush()
    return crawl_run


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_failure_clusters_group_failures_with_attribution(
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
        space = await _create_space(
            session,
            tenant_id=admin_user.tenant_id,
            name="Failure triage space",
        )
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="own",
            name="Repeated timeout website",
            space_id=space.id,
        )
        older_job = await _create_job(
            session,
            user_id=admin_user.id,
            created_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=3),
        )
        older_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=older_job.id,
            created_at=older_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
            pages_crawled=2,
            files_downloaded=1,
            pages_failed=1,
        )
        latest_job = await _create_job(
            session,
            user_id=admin_user.id,
            created_at=now - timedelta(hours=1),
            finished_at=now - timedelta(hours=1),
        )
        latest_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=latest_job.id,
            created_at=latest_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
            pages_crawled=3,
            files_downloaded=2,
            files_failed=1,
        )
        empty_output_job = await _create_job(
            session,
            user_id=admin_user.id,
            created_at=now - timedelta(minutes=30),
            finished_at=now - timedelta(minutes=30),
        )
        empty_output_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=empty_output_job.id,
            created_at=empty_output_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
        )

        other_tenant = await tenant_factory(session, name="Other cluster tenant")
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        other_website = await _create_website(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="other",
            name="Other tenant repeated timeout",
        )
        other_job = await _create_job(
            session,
            user_id=other_user.id,
            created_at=now - timedelta(hours=2),
            finished_at=now - timedelta(hours=2),
        )
        other_run = await _create_crawl_run(
            session,
            tenant_id=other_tenant.id,
            website_id=other_website.id,
            job_id=other_job.id,
            created_at=other_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
        )

        website_id = website.id
        latest_run_id = latest_run.id
        older_run_id = older_run.id
        empty_output_run_id = empty_output_run.id
        other_run_id = other_run.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/failure-clusters",
        params={"limit": 10, "offset": 0, "days": 7},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["limit"] == 10
    assert data["offset"] == 0
    assert data["days"] == 7
    assert data["source"] == "all"
    assert data["outcome_category"] is None

    timeout_cluster = data["items"][0]
    assert timeout_cluster["website_id"] == str(website_id)
    assert timeout_cluster["website_name"] == "Repeated timeout website"
    assert timeout_cluster["space_name"] == "Failure triage space"
    assert timeout_cluster["owner_email"] == admin_user.email
    assert timeout_cluster["outcome_code"] == "CRAWL_RUNTIME_TIMEOUT"
    assert timeout_cluster["outcome_category"] == "timeout"
    assert timeout_cluster["occurrences"] == 2
    assert timeout_cluster["watchdog_occurrences"] == 2
    assert timeout_cluster["sample_crawl_run_id"] == str(latest_run_id)
    assert timeout_cluster["pages_crawled"] == 5
    assert timeout_cluster["files_downloaded"] == 3
    assert timeout_cluster["pages_failed"] == 1
    assert timeout_cluster["files_failed"] == 1

    empty_output_cluster = data["items"][1]
    assert empty_output_cluster["outcome_code"] == "CRAWL_NO_PAGES_RETURNED"
    assert empty_output_cluster["outcome_category"] == "empty_output"
    assert empty_output_cluster["occurrences"] == 1
    assert empty_output_cluster["watchdog_occurrences"] == 0
    assert empty_output_cluster["sample_crawl_run_id"] == str(empty_output_run_id)

    returned_run_ids = {item["sample_crawl_run_id"] for item in data["items"]}
    assert str(older_run_id) not in returned_run_ids
    assert str(other_run_id) not in returned_run_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_failure_clusters_filter_category_and_source(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="filters",
            name="Failure cluster filters website",
        )
        watchdog_job = await _create_job(
            session,
            user_id=admin_user.id,
            created_at=now - timedelta(minutes=20),
            finished_at=now - timedelta(minutes=20),
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=watchdog_job.id,
            created_at=watchdog_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
            terminal_source=CrawlTerminalSource.WATCHDOG,
        )
        worker_timeout_job = await _create_job(
            session,
            user_id=admin_user.id,
            created_at=now - timedelta(minutes=15),
            finished_at=now - timedelta(minutes=15),
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=worker_timeout_job.id,
            created_at=worker_timeout_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
            terminal_source=CrawlTerminalSource.CRAWLER,
        )
        empty_output_job = await _create_job(
            session,
            user_id=admin_user.id,
            created_at=now - timedelta(minutes=10),
            finished_at=now - timedelta(minutes=10),
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=empty_output_job.id,
            created_at=empty_output_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
            terminal_source=CrawlTerminalSource.CRAWLER,
        )
        await session.commit()

    watchdog_response = await client.get(
        "/api/v1/admin/crawler/failure-clusters",
        params={"source": "watchdog_only"},
        headers={"X-API-Key": admin_user_api_key.key},
    )
    empty_output_response = await client.get(
        "/api/v1/admin/crawler/failure-clusters",
        params={"outcome_category": "empty_output"},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert watchdog_response.status_code == 200
    watchdog_data = watchdog_response.json()
    assert watchdog_data["source"] == "watchdog_only"
    assert [item["outcome_code"] for item in watchdog_data["items"]] == [
        "CRAWL_RUNTIME_TIMEOUT"
    ]
    assert watchdog_data["items"][0]["occurrences"] == 1
    assert watchdog_data["items"][0]["watchdog_occurrences"] == 1

    assert empty_output_response.status_code == 200
    empty_output_data = empty_output_response.json()
    assert empty_output_data["outcome_category"] == "empty_output"
    assert [item["outcome_code"] for item in empty_output_data["items"]] == [
        "CRAWL_NO_PAGES_RETURNED"
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_failure_clusters_has_no_tenant_id_query_parameter(app):
    operation = app.openapi()["paths"]["/api/v1/admin/crawler/failure-clusters"]["get"]
    query_params = [
        param["name"]
        for param in operation.get("parameters", [])
        if param["in"] == "query"
    ]

    assert "tenant_id" not in query_params
