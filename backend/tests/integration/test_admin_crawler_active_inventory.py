from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.job_table import Jobs
from intric.database.tables.websites_table import CrawlRuns, Websites
from intric.jobs.job_models import Task
from intric.main.models import Status
from intric.websites.domain.crawl_lifecycle import CrawlLifecycle
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
        url=f"https://admin-active-{url_suffix}.example.com",
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
    task: Task = Task.CRAWL,
    status: Status,
    created_at: datetime,
    finished_at: datetime | None = None,
) -> Jobs:
    job = Jobs(
        id=uuid4(),
        user_id=user_id,
        task=task.value,
        status=status.value,
        result_location=None,
        name="Admin crawler active inventory test",
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
    pages_crawled: int | None = None,
    files_downloaded: int | None = None,
    pages_failed: int | None = None,
    files_failed: int | None = None,
    pages_source_retained: int | None = None,
    pages_hash_retained: int | None = None,
    files_hash_retained: int | None = None,
    files_too_large_skipped: int | None = None,
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
        pages_source_retained=pages_source_retained,
        pages_hash_retained=pages_hash_retained,
        files_hash_retained=files_hash_retained,
        files_too_large_skipped=files_too_large_skipped,
        outcome_code=None,
    )
    session.add(crawl_run)
    await session.flush()
    return crawl_run


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_active_inventory_empty_result(
    client,
    admin_user_api_key,
):
    response = await client.get(
        "/api/v1/admin/crawler/active",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "limit": 50,
        "offset": 0,
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_active_inventory_is_scoped_to_current_tenant(
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
        other_tenant = await tenant_factory(session, name="Other active admin tenant")
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        own_website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="own",
            name="Own admin active",
        )
        other_website = await _create_website(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="other",
            name="Other admin active",
        )

        own_no_progress_job = await _create_job(
            session,
            user_id=admin_user.id,
            status=Status.IN_PROGRESS,
            created_at=now - timedelta(minutes=1),
        )
        own_no_progress_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=own_website.id,
            job_id=own_no_progress_job.id,
            created_at=own_no_progress_job.created_at,
            pages_crawled=0,
            files_downloaded=0,
        )
        own_with_progress_job = await _create_job(
            session,
            user_id=admin_user.id,
            status=Status.IN_PROGRESS,
            created_at=now - timedelta(minutes=2),
        )
        own_with_progress_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=own_website.id,
            job_id=own_with_progress_job.id,
            created_at=own_with_progress_job.created_at,
            pages_crawled=3,
            files_hash_retained=1,
        )
        own_queued_job = await _create_job(
            session,
            user_id=admin_user.id,
            status=Status.QUEUED,
            created_at=now - timedelta(minutes=3),
        )
        own_queued_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=own_website.id,
            job_id=own_queued_job.id,
            created_at=own_queued_job.created_at,
        )
        other_job = await _create_job(
            session,
            user_id=other_user.id,
            status=Status.IN_PROGRESS,
            created_at=now - timedelta(minutes=4),
        )
        await _create_crawl_run(
            session,
            tenant_id=other_tenant.id,
            website_id=other_website.id,
            job_id=other_job.id,
            created_at=other_job.created_at,
            pages_crawled=5,
        )
        terminal_job = await _create_job(
            session,
            user_id=admin_user.id,
            status=Status.COMPLETE,
            created_at=now - timedelta(minutes=5),
            finished_at=now - timedelta(minutes=4),
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=own_website.id,
            job_id=terminal_job.id,
            created_at=terminal_job.created_at,
            pages_crawled=10,
        )
        await _create_job(
            session,
            user_id=admin_user.id,
            task=Task.UPLOAD_FILE,
            status=Status.IN_PROGRESS,
            created_at=now - timedelta(minutes=6),
        )

        own_no_progress_job_id = own_no_progress_job.id
        own_no_progress_run_id = own_no_progress_run.id
        own_with_progress_job_id = own_with_progress_job.id
        own_with_progress_run_id = own_with_progress_run.id
        own_queued_job_id = own_queued_job.id
        own_queued_run_id = own_queued_run.id
        other_job_id = other_job.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/active",
        params={"limit": 10, "offset": 0},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert [item["job_id"] for item in data["items"]] == [
        str(own_no_progress_job_id),
        str(own_with_progress_job_id),
        str(own_queued_job_id),
    ]

    by_job_id = {item["job_id"]: item for item in data["items"]}
    no_progress_item = by_job_id[str(own_no_progress_job_id)]
    assert no_progress_item["crawl_run_id"] == str(own_no_progress_run_id)
    assert no_progress_item["website_name"] == "Own admin active"
    assert no_progress_item["tenant_id"] == str(admin_user.tenant_id)
    assert (
        no_progress_item["lifecycle_state"] == CrawlLifecycle.RUNNING_NO_PROGRESS.value
    )
    # Running crawls are abortable: the admin endpoint commits a terminal
    # CRAWL_ABORTED event that the worker's heartbeat preemption observes,
    # exiting via the slot-release reactor without unsafe stale cleanup.
    assert no_progress_item["is_abortable"] is True

    with_progress_item = by_job_id[str(own_with_progress_job_id)]
    assert with_progress_item["crawl_run_id"] == str(own_with_progress_run_id)
    assert with_progress_item["lifecycle_state"] == (
        CrawlLifecycle.RUNNING_WITH_PROGRESS.value
    )
    assert with_progress_item["pages_crawled"] == 3
    assert with_progress_item["files_hash_retained"] == 1
    assert with_progress_item["is_abortable"] is True

    queued_item = by_job_id[str(own_queued_job_id)]
    assert queued_item["crawl_run_id"] == str(own_queued_run_id)
    assert queued_item["lifecycle_state"] == CrawlLifecycle.QUEUED.value
    assert queued_item["is_abortable"] is True
    assert str(other_job_id) not in by_job_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_active_inventory_excludes_orphan_queued_jobs(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    async with db_session() as session:
        orphan_job = await _create_job(
            session,
            user_id=admin_user.id,
            status=Status.QUEUED,
            created_at=datetime.now(timezone.utc),
        )
        orphan_job_id = orphan_job.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/active",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert str(orphan_job_id) not in {item["job_id"] for item in data["items"]}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_active_inventory_rejects_non_admin_user(
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
            email=f"regular-active-{uuid4()}@example.com",
        )
        regular_user_id = regular_user.id
        await session.commit()

    async with db_container() as container:
        api_key = await container.auth_service().create_user_api_key(
            prefix="test", user_id=regular_user_id, delete_old=True
        )

    response = await client.get(
        "/api/v1/admin/crawler/active",
        headers={"X-API-Key": api_key.key},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_active_inventory_rejects_unbounded_params(
    client,
    admin_user_api_key,
):
    response = await client.get(
        "/api/v1/admin/crawler/active",
        params={"limit": 201},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_active_inventory_has_no_tenant_id_query_parameter(app):
    operation = app.openapi()["paths"]["/api/v1/admin/crawler/active"]["get"]
    query_parameters = {
        parameter["name"]
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "query"
    }

    assert {"limit", "offset"}.issubset(query_parameters)
    assert "tenant_id" not in query_parameters
