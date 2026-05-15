import json
from dataclasses import asdict
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
from intric.worker.feeder.watchdog import CleanupMetrics, WatchdogLifecycleCounts
from intric.worker.redis.client import (
    WATCHDOG_LAST_METRICS_KEY,
    WATCHDOG_LAST_SUCCESS_EPOCH_KEY,
)


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
        url=f"https://watchdog-status-{url_suffix}.example.com",
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
        name="Crawler watchdog status test",
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
        failure_summary=None,
    )
    session.add(crawl_run)
    await session.flush()
    return crawl_run


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_watchdog_status_requires_super_api_key(client):
    response = await client.get("/api/v1/sysadmin/crawler/watchdog-status")

    assert response.status_code in {401, 403}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_watchdog_status_handles_empty_snapshot(
    client,
    redis_client,
    super_admin_token,
):
    await redis_client.delete(
        WATCHDOG_LAST_SUCCESS_EPOCH_KEY,
        WATCHDOG_LAST_METRICS_KEY,
    )

    response = await client.get(
        "/api/v1/sysadmin/crawler/watchdog-status",
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["last_cleanup_at"] is None
    assert data["metrics"] is None
    assert data["recent_interventions"]["items"] == []
    assert data["recent_interventions"]["total"] == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_watchdog_status_surfaces_redis_metrics(
    client,
    redis_client,
    super_admin_token,
):
    observed_at = datetime(2026, 5, 12, 14, 15, 16, tzinfo=timezone.utc)
    last_cleanup_at = datetime(2026, 5, 12, 14, 16, 17, tzinfo=timezone.utc)
    await redis_client.set(
        WATCHDOG_LAST_SUCCESS_EPOCH_KEY,
        str(int(last_cleanup_at.timestamp())),
    )
    metrics = CleanupMetrics(
        zombies_reconciled=2,
        expired_killed=3,
        rescued=4,
        early_zombies_failed=5,
        long_running_failed=6,
        slots_released=7,
        lifecycle_observed=WatchdogLifecycleCounts(
            queued=8,
            running_no_progress=9,
            running_with_progress=10,
            terminal=11,
        ),
    )
    await redis_client.set(
        WATCHDOG_LAST_METRICS_KEY,
        json.dumps(
            {
                "timestamp": observed_at.isoformat(),
                **asdict(metrics),
            }
        ),
    )

    response = await client.get(
        "/api/v1/sysadmin/crawler/watchdog-status",
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert _parse_response_datetime(data["last_cleanup_at"]) == last_cleanup_at
    assert data["metrics"] == {
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "zombies_reconciled": 2,
        "expired_killed": 3,
        "rescued": 4,
        "early_zombies_failed": 5,
        "long_running_failed": 6,
        "slots_released": 7,
        "lifecycle_observed": {
            "queued": 8,
            "running_no_progress": 9,
            "running_with_progress": 10,
            "terminal": 11,
        },
    }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "raw_metrics",
    [
        "not-json",
        json.dumps({"timestamp": "2026-05-12T14:15:16+00:00"}),
    ],
)
async def test_sysadmin_crawler_watchdog_status_denies_malformed_redis_metrics(
    client,
    redis_client,
    super_admin_token,
    raw_metrics: str,
):
    last_cleanup_at = datetime(2026, 5, 12, 14, 16, 17, tzinfo=timezone.utc)
    await redis_client.set(
        WATCHDOG_LAST_SUCCESS_EPOCH_KEY,
        str(int(last_cleanup_at.timestamp())),
    )
    await redis_client.set(WATCHDOG_LAST_METRICS_KEY, raw_metrics)

    response = await client.get(
        "/api/v1/sysadmin/crawler/watchdog-status",
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert _parse_response_datetime(data["last_cleanup_at"]) == last_cleanup_at
    assert data["metrics"] is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sysadmin_crawler_watchdog_status_lists_bounded_interventions(
    client,
    db_session,
    tenant_factory,
    user_factory,
    redis_client,
    super_admin_token,
):
    await redis_client.delete(
        WATCHDOG_LAST_SUCCESS_EPOCH_KEY,
        WATCHDOG_LAST_METRICS_KEY,
    )
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        tenant = await tenant_factory(session, name="Watchdog status tenant")
        user = await user_factory(session, tenant_id=tenant.id)
        other_tenant = await tenant_factory(session, name="Other watchdog tenant")
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        website = await _create_website(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="primary",
            name="Watchdog primary",
        )
        other_website = await _create_website(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix="other",
            name="Watchdog other",
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
            outcome_code=CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES,
        )
        old_job = await _create_job(
            session,
            user_id=user.id,
            status=Status.FAILED,
            created_at=now - timedelta(minutes=3),
            finished_at=now - timedelta(minutes=3),
        )
        old_run = await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            website_id=website.id,
            job_id=old_job.id,
            created_at=old_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED,
        )
        non_watchdog_job = await _create_job(
            session,
            user_id=user.id,
            status=Status.FAILED,
            created_at=now - timedelta(minutes=4),
            finished_at=now - timedelta(minutes=4),
        )
        non_watchdog_run = await _create_crawl_run(
            session,
            tenant_id=tenant.id,
            website_id=website.id,
            job_id=non_watchdog_job.id,
            created_at=non_watchdog_job.created_at,
            outcome_code=CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
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
        )
        newest_run_id = newest_run.id
        middle_run_id = middle_run.id
        old_run_id = old_run.id
        non_watchdog_run_id = non_watchdog_run.id
        other_tenant_run_id = other_tenant_run.id
        tenant_id = tenant.id
        await session.commit()

    response = await client.get(
        "/api/v1/sysadmin/crawler/watchdog-status",
        params={"days": 7, "limit": 2, "offset": 0},
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200
    data = response.json()
    interventions = data["recent_interventions"]
    assert interventions["total"] == 4
    assert interventions["limit"] == 2
    assert interventions["offset"] == 0
    assert [item["crawl_run_id"] for item in interventions["items"]] == [
        str(newest_run_id),
        str(middle_run_id),
    ]
    assert {item["outcome_code"] for item in interventions["items"]} <= {
        CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT.value,
        CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES.value,
        CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED.value,
    }
    returned_ids = {item["crawl_run_id"] for item in interventions["items"]}
    assert str(non_watchdog_run_id) not in returned_ids

    second_page_response = await client.get(
        "/api/v1/sysadmin/crawler/watchdog-status",
        params={"days": 7, "limit": 2, "offset": 2},
        headers={"X-API-Key": super_admin_token},
    )

    assert second_page_response.status_code == 200
    second_page_interventions = second_page_response.json()["recent_interventions"]
    assert [item["crawl_run_id"] for item in second_page_interventions["items"]] == [
        str(old_run_id),
        str(other_tenant_run_id),
    ]

    tenant_response = await client.get(
        "/api/v1/sysadmin/crawler/watchdog-status",
        params={"tenant_id": str(tenant_id), "days": 7, "limit": 10, "offset": 0},
        headers={"X-API-Key": super_admin_token},
    )

    assert tenant_response.status_code == 200
    tenant_interventions = tenant_response.json()["recent_interventions"]
    assert tenant_interventions["total"] == 3
    assert [item["crawl_run_id"] for item in tenant_interventions["items"]] == [
        str(newest_run_id),
        str(middle_run_id),
        str(old_run_id),
    ]
    tenant_returned_ids = {
        item["crawl_run_id"] for item in tenant_interventions["items"]
    }
    assert str(non_watchdog_run_id) not in tenant_returned_ids
    assert str(other_tenant_run_id) not in tenant_returned_ids
