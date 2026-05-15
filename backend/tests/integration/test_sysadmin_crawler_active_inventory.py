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
) -> Websites:
    website = Websites(
        name=f"Crawler active {url_suffix}",
        url=f"https://active-{url_suffix}.example.com",
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
    task: Task,
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
        name="Crawler active inventory test",
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
async def test_sysadmin_crawler_active_inventory_empty_result(
    client,
    super_admin_token,
):
    response = await client.get(
        "/api/v1/sysadmin/crawler/active",
        headers={"X-API-Key": super_admin_token},
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
async def test_sysadmin_crawler_active_inventory_lists_lifecycle_and_filters(
    client,
    db_session,
    tenant_factory,
    user_factory,
    super_admin_token,
):
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        tenant = await tenant_factory(session, name="Crawler active tenant")
        tenant.display_name = "Crawler Active Display"
        user = await user_factory(session, tenant_id=tenant.id)
        other_tenant = await tenant_factory(session, name="Other active tenant")
        other_tenant.display_name = "Other Active Display"
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        website = await _create_website(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="primary",
        )
        other_website = await _create_website(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="other",
        )

        orphan_queued_job = await _create_job(
            session,
            user_id=user.id,
            task=Task.CRAWL,
            status=Status.QUEUED,
            created_at=now,
        )
        no_progress_job = await _create_job(
            session,
            user_id=user.id,
            task=Task.CRAWL,
            status=Status.IN_PROGRESS,
            created_at=now - timedelta(minutes=1),
        )
        no_progress_run = await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            website_id=website.id,
            job_id=no_progress_job.id,
            created_at=no_progress_job.created_at,
            pages_crawled=0,
            files_downloaded=0,
        )
        with_progress_job = await _create_job(
            session,
            user_id=user.id,
            task=Task.CRAWL,
            status=Status.IN_PROGRESS,
            created_at=now - timedelta(minutes=2),
        )
        with_progress_run = await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            website_id=website.id,
            job_id=with_progress_job.id,
            created_at=with_progress_job.created_at,
            pages_crawled=3,
            files_hash_retained=1,
        )
        other_tenant_job = await _create_job(
            session,
            user_id=other_user.id,
            task=Task.CRAWL,
            status=Status.IN_PROGRESS,
            created_at=now - timedelta(minutes=3),
        )
        await _create_crawl_run(
            session,
            tenant_id=other_tenant.id,
            website_id=other_website.id,
            job_id=other_tenant_job.id,
            created_at=other_tenant_job.created_at,
            pages_crawled=2,
        )
        terminal_job = await _create_job(
            session,
            user_id=user.id,
            task=Task.CRAWL,
            status=Status.COMPLETE,
            created_at=now - timedelta(minutes=4),
            finished_at=now - timedelta(minutes=3),
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            website_id=website.id,
            job_id=terminal_job.id,
            created_at=terminal_job.created_at,
            pages_crawled=10,
        )
        await _create_job(
            session,
            user_id=user.id,
            task=Task.UPLOAD_FILE,
            status=Status.IN_PROGRESS,
            created_at=now - timedelta(minutes=5),
        )
        orphan_queued_job_id = orphan_queued_job.id
        no_progress_job_id = no_progress_job.id
        no_progress_run_id = no_progress_run.id
        with_progress_job_id = with_progress_job.id
        with_progress_run_id = with_progress_run.id
        other_tenant_job_id = other_tenant_job.id
        tenant_id = tenant.id
        await session.commit()

    response = await client.get(
        "/api/v1/sysadmin/crawler/active",
        params={"limit": 10, "offset": 0},
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 4
    assert [item["job_id"] for item in data["items"]] == [
        str(orphan_queued_job_id),
        str(no_progress_job_id),
        str(with_progress_job_id),
        str(other_tenant_job_id),
    ]

    by_job_id = {item["job_id"]: item for item in data["items"]}
    assert by_job_id[str(orphan_queued_job_id)]["crawl_run_id"] is None
    assert by_job_id[str(orphan_queued_job_id)]["tenant_id"] is None
    assert by_job_id[str(orphan_queued_job_id)]["website_name"] is None
    assert by_job_id[str(orphan_queued_job_id)]["tenant_display_name"] is None
    assert by_job_id[str(orphan_queued_job_id)]["lifecycle_state"] == (
        CrawlLifecycle.QUEUED.value
    )
    assert by_job_id[str(no_progress_job_id)]["crawl_run_id"] == str(no_progress_run_id)
    assert by_job_id[str(no_progress_job_id)]["website_name"] == (
        "Crawler active primary"
    )
    assert by_job_id[str(no_progress_job_id)]["tenant_display_name"] == (
        "Crawler Active Display"
    )
    assert by_job_id[str(no_progress_job_id)]["lifecycle_state"] == (
        CrawlLifecycle.RUNNING_NO_PROGRESS.value
    )
    assert by_job_id[str(with_progress_job_id)]["crawl_run_id"] == str(
        with_progress_run_id
    )
    assert by_job_id[str(with_progress_job_id)]["lifecycle_state"] == (
        CrawlLifecycle.RUNNING_WITH_PROGRESS.value
    )
    assert by_job_id[str(with_progress_job_id)]["pages_crawled"] == 3
    assert by_job_id[str(with_progress_job_id)]["files_hash_retained"] == 1
    assert by_job_id[str(with_progress_job_id)]["website_name"] == (
        "Crawler active primary"
    )
    assert by_job_id[str(with_progress_job_id)]["tenant_display_name"] == (
        "Crawler Active Display"
    )
    assert by_job_id[str(other_tenant_job_id)]["website_name"] == "Crawler active other"
    assert by_job_id[str(other_tenant_job_id)]["tenant_display_name"] == (
        "Other Active Display"
    )

    tenant_response = await client.get(
        "/api/v1/sysadmin/crawler/active",
        params={"tenant_id": str(tenant_id), "limit": 10, "offset": 0},
        headers={"X-API-Key": super_admin_token},
    )

    assert tenant_response.status_code == 200
    tenant_data = tenant_response.json()
    assert tenant_data["total"] == 2
    assert [item["job_id"] for item in tenant_data["items"]] == [
        str(no_progress_job_id),
        str(with_progress_job_id),
    ]
    assert str(orphan_queued_job_id) not in [
        item["job_id"] for item in tenant_data["items"]
    ]

    page_response = await client.get(
        "/api/v1/sysadmin/crawler/active",
        params={"limit": 2, "offset": 1},
        headers={"X-API-Key": super_admin_token},
    )

    assert page_response.status_code == 200
    page_data = page_response.json()
    assert page_data["total"] == 4
    assert page_data["limit"] == 2
    assert page_data["offset"] == 1
    assert [item["job_id"] for item in page_data["items"]] == [
        str(no_progress_job_id),
        str(with_progress_job_id),
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_active_inventory_preserves_null_linked_names(
    client,
    db_session,
    tenant_factory,
    user_factory,
    super_admin_token,
):
    now = datetime(2026, 5, 14, 13, 0, tzinfo=timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        tenant = await tenant_factory(session, name="Crawler active null tenant")
        user = await user_factory(session, tenant_id=tenant.id)
        website = await _create_website(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="null-name",
        )
        website.name = None
        job = await _create_job(
            session,
            user_id=user.id,
            task=Task.CRAWL,
            status=Status.IN_PROGRESS,
            created_at=now,
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            website_id=website.id,
            job_id=job.id,
            created_at=job.created_at,
            pages_crawled=1,
        )
        job_id = job.id
        await session.commit()

    response = await client.get(
        "/api/v1/sysadmin/crawler/active",
        params={"limit": 10, "offset": 0},
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    by_job_id = {item["job_id"]: item for item in response.json()["items"]}
    assert by_job_id[str(job_id)]["website_name"] is None
    assert by_job_id[str(job_id)]["tenant_display_name"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_active_inventory_rejects_unbounded_limit(
    client,
    super_admin_token,
):
    response = await client.get(
        "/api/v1/sysadmin/crawler/active",
        params={"limit": 201},
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_active_inventory_requires_super_api_key(client):
    response = await client.get("/api/v1/sysadmin/crawler/active")

    assert response.status_code in {401, 403}
