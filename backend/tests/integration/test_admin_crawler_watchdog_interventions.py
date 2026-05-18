from datetime import datetime, timedelta, timezone
from decimal import Decimal
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
from intric.websites.domain.crawl_terminal_source import CrawlTerminalSource
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
        url=f"https://admin-watchdog-{url_suffix}.example.com",
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
        name="Admin crawler watchdog interventions test",
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
    embedding_model_name_snapshot: str | None = None,
    embedding_model_litellm_name_snapshot: str | None = None,
    embedding_model_provider_snapshot: str | None = None,
    embedding_input_tokens: int | None = None,
    embedding_total_cost_usd: Decimal | None = None,
    embedding_usage_source: str | None = None,
    terminal_source: CrawlTerminalSource | None = None,
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
        terminal_source=terminal_source.value if terminal_source is not None else None,
        failure_summary=None,
        embedding_model_name_snapshot=embedding_model_name_snapshot,
        embedding_model_litellm_name_snapshot=embedding_model_litellm_name_snapshot,
        embedding_model_provider_snapshot=embedding_model_provider_snapshot,
        embedding_input_tokens=embedding_input_tokens,
        embedding_total_cost_usd=embedding_total_cost_usd,
        embedding_usage_source=embedding_usage_source,
    )
    session.add(crawl_run)
    await session.flush()
    return crawl_run


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_watchdog_interventions_empty_window(
    client,
    admin_user_api_key,
):
    response = await client.get(
        "/api/v1/admin/crawler/watchdog-interventions",
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
async def test_admin_crawler_watchdog_interventions_are_tenant_scoped_and_allowlisted(
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
        other_tenant = await tenant_factory(session, name="Other watchdog admin tenant")
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        own_website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="own",
            name="Own watchdog intervention",
        )
        other_website = await _create_website(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="other",
            name="Other watchdog intervention",
        )

        runtime_job = await _create_job(
            session,
            user_id=admin_user.id,
            status=Status.FAILED,
            created_at=now - timedelta(minutes=1),
            finished_at=now - timedelta(minutes=1),
        )
        runtime_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=own_website.id,
            job_id=runtime_job.id,
            created_at=runtime_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
            terminal_source=CrawlTerminalSource.WATCHDOG,
            embedding_model_name_snapshot="text-embedding-3-small",
            embedding_model_litellm_name_snapshot="openai/text-embedding-3-small",
            embedding_model_provider_snapshot="openai",
            embedding_input_tokens=17,
            embedding_total_cost_usd=Decimal("0.000000340000"),
            embedding_usage_source="provider_reported",
        )
        max_age_job = await _create_job(
            session,
            user_id=admin_user.id,
            status=Status.FAILED,
            created_at=now - timedelta(minutes=2),
            finished_at=now - timedelta(minutes=2),
        )
        max_age_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=own_website.id,
            job_id=max_age_job.id,
            created_at=max_age_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED,
            terminal_source=CrawlTerminalSource.WATCHDOG,
        )
        worker_timeout_job = await _create_job(
            session,
            user_id=admin_user.id,
            status=Status.FAILED,
            created_at=now - timedelta(minutes=3),
            finished_at=now - timedelta(minutes=3),
        )
        worker_timeout_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=own_website.id,
            job_id=worker_timeout_job.id,
            created_at=worker_timeout_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
            terminal_source=CrawlTerminalSource.CRAWLER,
        )
        recent_failure_job = await _create_job(
            session,
            user_id=admin_user.id,
            status=Status.FAILED,
            created_at=now - timedelta(minutes=4),
            finished_at=now - timedelta(minutes=4),
        )
        recent_failure_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=own_website.id,
            job_id=recent_failure_job.id,
            created_at=recent_failure_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
            terminal_source=CrawlTerminalSource.CRAWLER,
        )
        other_tenant_job = await _create_job(
            session,
            user_id=other_user.id,
            status=Status.FAILED,
            created_at=now - timedelta(minutes=5),
            finished_at=now - timedelta(minutes=5),
        )
        other_tenant_run = await _create_crawl_run(
            session,
            tenant_id=other_tenant.id,
            website_id=other_website.id,
            job_id=other_tenant_job.id,
            created_at=other_tenant_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
            terminal_source=CrawlTerminalSource.WATCHDOG,
        )
        runtime_run_id = runtime_run.id
        max_age_run_id = max_age_run.id
        worker_timeout_run_id = worker_timeout_run.id
        recent_failure_run_id = recent_failure_run.id
        other_tenant_run_id = other_tenant_run.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/watchdog-interventions",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert [item["crawl_run_id"] for item in data["items"]] == [
        str(runtime_run_id),
        str(max_age_run_id),
    ]
    runtime_item = data["items"][0]
    assert runtime_item["embedding_model_name_snapshot"] == "text-embedding-3-small"
    assert runtime_item["embedding_model_litellm_name_snapshot"] == (
        "openai/text-embedding-3-small"
    )
    assert runtime_item["embedding_model_provider_snapshot"] == "openai"
    assert runtime_item["embedding_input_tokens"] == 17
    assert Decimal(runtime_item["embedding_total_cost_usd"]) == Decimal(
        "0.000000340000"
    )
    assert runtime_item["embedding_usage_source"] == "provider_reported"
    returned_ids = {item["crawl_run_id"] for item in data["items"]}
    assert str(worker_timeout_run_id) not in returned_ids
    assert str(recent_failure_run_id) not in returned_ids
    assert str(other_tenant_run_id) not in returned_ids

    recent_failures_response = await client.get(
        "/api/v1/admin/crawler/recent-failures",
        headers={"X-API-Key": admin_user_api_key.key},
    )
    assert recent_failures_response.status_code == 200
    recent_failure_ids = {
        item["crawl_run_id"] for item in recent_failures_response.json()["items"]
    }
    assert str(runtime_run_id) in recent_failure_ids
    assert str(worker_timeout_run_id) in recent_failure_ids
    assert str(recent_failure_run_id) in recent_failure_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_watchdog_interventions_rejects_non_admin_user(
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
            email=f"regular-watchdog-{uuid4()}@example.com",
        )
        regular_user_id = regular_user.id
        await session.commit()

    async with db_container() as container:
        api_key = await container.auth_service().create_user_api_key(
            prefix="test", user_id=regular_user_id, delete_old=True
        )

    response = await client.get(
        "/api/v1/admin/crawler/watchdog-interventions",
        headers={"X-API-Key": api_key.key},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_watchdog_interventions_has_no_tenant_id_query_parameter(
    app,
):
    operation = app.openapi()["paths"]["/api/v1/admin/crawler/watchdog-interventions"][
        "get"
    ]
    query_parameters = {
        parameter["name"]
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "query"
    }

    assert {"days", "limit", "offset"}.issubset(query_parameters)
    assert "tenant_id" not in query_parameters
