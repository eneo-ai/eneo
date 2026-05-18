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
        name=f"Crawler baseline {url_suffix}",
        url=f"https://baseline-{url_suffix}.example.com",
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


async def _create_crawl_run(
    session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    website_id: UUID,
    created_at: datetime,
    status: Status,
    finished_at: datetime | None,
    outcome_code: str | None,
    pages_crawled: int = 0,
    files_downloaded: int = 0,
    pages_failed: int = 0,
    files_failed: int = 0,
    pages_source_retained: int = 0,
    pages_hash_retained: int = 0,
    files_hash_retained: int = 0,
    files_too_large_skipped: int = 0,
    embedding_input_tokens: int | None = None,
    embedding_total_cost_usd: Decimal | None = None,
    create_job: bool = True,
) -> CrawlRuns:
    job_id: UUID | None = None
    if create_job:
        job = Jobs(
            id=uuid4(),
            user_id=user_id,
            task=Task.CRAWL.value,
            status=status.value,
            result_location=None,
            name="Crawler baseline test",
            finished_at=finished_at,
            created_at=created_at,
            updated_at=created_at,
        )
        session.add(job)
        await session.flush()
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
        outcome_code=outcome_code,
        embedding_input_tokens=embedding_input_tokens,
        embedding_total_cost_usd=embedding_total_cost_usd,
    )
    session.add(crawl_run)
    await session.flush()
    return crawl_run


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_baseline_separates_typed_unknown_from_legacy_rows(
    client,
    db_session,
    admin_user,
    tenant_factory,
    user_factory,
    super_admin_token,
):
    until = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    inside_window = until - timedelta(days=1)
    outside_window = until - timedelta(days=10)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        tenant = await tenant_factory(session, name="Crawler baseline tenant")
        user = await user_factory(session, tenant_id=tenant.id)
        other_tenant = await tenant_factory(session, name="Other baseline tenant")
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        tenant_id = tenant.id

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

        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=website.id,
            created_at=inside_window,
            status=Status.FAILED,
            finished_at=inside_window,
            outcome_code=CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR.value,
            pages_crawled=2,
            files_downloaded=1,
            pages_failed=1,
            files_hash_retained=1,
            embedding_input_tokens=20,
            embedding_total_cost_usd=Decimal("0.000002000000"),
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=website.id,
            created_at=inside_window,
            status=Status.FAILED,
            finished_at=inside_window,
            outcome_code=None,
            pages_crawled=3,
            files_downloaded=1,
            pages_failed=2,
            files_failed=1,
            files_too_large_skipped=2,
            embedding_input_tokens=30,
            embedding_total_cost_usd=Decimal("0.000003000000"),
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=website.id,
            created_at=inside_window,
            status=Status.COMPLETE,
            finished_at=inside_window,
            outcome_code=CrawlOutcomeCode.CRAWL_ALL_UNCHANGED.value,
            pages_crawled=5,
            files_downloaded=2,
            pages_hash_retained=5,
            files_hash_retained=2,
            embedding_input_tokens=50,
            embedding_total_cost_usd=Decimal("0.000005000000"),
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=website.id,
            created_at=inside_window,
            status=Status.COMPLETE,
            finished_at=inside_window,
            outcome_code="OLD_GARBAGE_STRING",
            pages_source_retained=4,
            embedding_input_tokens=None,
            embedding_total_cost_usd=None,
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=website.id,
            created_at=inside_window,
            status=Status.FAILED,
            finished_at=inside_window,
            outcome_code=CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED.value,
            pages_crawled=1,
            pages_failed=4,
            embedding_input_tokens=10,
            embedding_total_cost_usd=Decimal("0.000001000000"),
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=website.id,
            created_at=inside_window,
            status=Status.IN_PROGRESS,
            finished_at=None,
            outcome_code=CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR.value,
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=website.id,
            created_at=inside_window,
            status=Status.IN_PROGRESS,
            finished_at=None,
            outcome_code=None,
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=website.id,
            created_at=inside_window,
            status=Status.IN_PROGRESS,
            finished_at=None,
            outcome_code="OLD_GARBAGE_STRING",
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=website.id,
            created_at=inside_window,
            status=Status.COMPLETE,
            finished_at=None,
            outcome_code=CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR.value,
            create_job=False,
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=website.id,
            created_at=until,
            status=Status.COMPLETE,
            finished_at=until,
            outcome_code=CrawlOutcomeCode.CRAWL_ALL_UNCHANGED.value,
            pages_crawled=100,
            pages_failed=100,
        )
        await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            website_id=website.id,
            created_at=outside_window,
            status=Status.FAILED,
            finished_at=outside_window,
            outcome_code=CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR.value,
            pages_failed=99,
        )
        await _create_crawl_run(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            website_id=other_website.id,
            created_at=inside_window,
            status=Status.FAILED,
            finished_at=inside_window,
            outcome_code=CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR.value,
            pages_failed=50,
        )
        await session.commit()

    response = await client.get(
        "/api/v1/sysadmin/crawler/baseline",
        params={
            "tenant_id": str(tenant_id),
            "days": 7,
            "until": until.isoformat(),
        },
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == str(tenant_id)
    assert data["window_days"] == 7
    assert data["total_runs"] == 9
    assert data["terminal_runs"] == 5
    assert data["failed_runs"] == 3
    assert data["failed_runs_without_typed_outcome"] == 1
    assert data["typed_failed_runs"] == 2
    assert data["typed_unknown_failed_runs"] == 1
    assert data["typed_unknown_failed_rate_percent"] == 50.0
    assert data["legacy_null_outcome_runs"] == 1
    assert data["unparseable_outcome_runs"] == 1

    outcome_counts = {item["code"]: item["count"] for item in data["outcome_counts"]}
    assert outcome_counts == {
        CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR.value: 1,
        CrawlOutcomeCode.CRAWL_ALL_UNCHANGED.value: 1,
        CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED.value: 1,
    }
    assert (
        sum(outcome_counts.values())
        + data["legacy_null_outcome_runs"]
        + data["unparseable_outcome_runs"]
        == data["terminal_runs"]
    )

    assert data["processing_totals"] == {
        "pages_crawled": 11,
        "files_downloaded": 4,
        "pages_hash_retained": 5,
        "files_hash_retained": 3,
        "pages_source_retained": 4,
        "files_too_large_skipped": 2,
        "pages_failed": 7,
        "files_failed": 1,
        "embedding_input_tokens": 110,
        "embedding_total_cost_usd": "0.000011000000",
    }

    cross_tenant_response = await client.get(
        "/api/v1/sysadmin/crawler/baseline",
        params={
            "days": 7,
            "until": until.isoformat(),
        },
        headers={"X-API-Key": super_admin_token},
    )

    assert cross_tenant_response.status_code == 200
    cross_tenant_data = cross_tenant_response.json()
    assert cross_tenant_data["tenant_id"] is None
    assert cross_tenant_data["total_runs"] == 10
    assert cross_tenant_data["terminal_runs"] == 6
    assert cross_tenant_data["failed_runs"] == 4
    assert cross_tenant_data["typed_failed_runs"] == 3
    assert cross_tenant_data["typed_unknown_failed_runs"] == 2
    assert cross_tenant_data["typed_unknown_failed_rate_percent"] == 66.67


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_baseline_empty_window_returns_zeroes(
    client,
    db_session,
    tenant_factory,
    super_admin_token,
):
    async with db_session() as session:
        tenant = await tenant_factory(session, name="Empty crawler baseline tenant")
        tenant_id = tenant.id
        await session.commit()

    response = await client.get(
        "/api/v1/sysadmin/crawler/baseline",
        params={
            "tenant_id": str(tenant_id),
            "days": 7,
            "until": datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc).isoformat(),
        },
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_runs"] == 0
    assert data["terminal_runs"] == 0
    assert data["failed_runs"] == 0
    assert data["typed_unknown_failed_rate_percent"] == 0.0
    assert data["outcome_counts"] == []
    assert data["processing_totals"] == {
        "pages_crawled": 0,
        "files_downloaded": 0,
        "pages_hash_retained": 0,
        "files_hash_retained": 0,
        "pages_source_retained": 0,
        "files_too_large_skipped": 0,
        "pages_failed": 0,
        "files_failed": 0,
        "embedding_input_tokens": None,
        "embedding_total_cost_usd": None,
    }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("days", [0, 31])
async def test_sysadmin_crawler_baseline_rejects_unbounded_windows(
    client,
    super_admin_token,
    days,
):
    response = await client.get(
        "/api/v1/sysadmin/crawler/baseline",
        params={"days": days},
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_baseline_requires_super_api_key(client):
    response = await client.get("/api/v1/sysadmin/crawler/baseline")

    assert response.status_code in {401, 403}
