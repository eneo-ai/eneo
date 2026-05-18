"""Tenant admin filters for crawler failure investigation surfaces."""

from __future__ import annotations

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
from intric.websites.domain.crawl_terminal_source import CrawlTerminalSource
from intric.websites.domain.crawler_failure_inventory import CrawlerFailureState
from intric.websites.domain.website import (
    WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    UpdateInterval,
)


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
    update_interval: UpdateInterval = UpdateInterval.NEVER,
    consecutive_failures: int = 0,
    next_retry_at: datetime | None = None,
    name: str | None = None,
) -> Websites:
    website = Websites(
        name=name,
        url=f"https://filter-{uuid4()}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=update_interval,
        size=0,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
        consecutive_failures=consecutive_failures,
        next_retry_at=next_retry_at,
    )
    session.add(website)
    await session.flush()
    return website


async def _create_failed_crawl_run(
    session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    website_id: UUID,
    outcome_code: CrawlOutcomeCode,
    finished_at: datetime,
    terminal_source: CrawlTerminalSource | None = None,
) -> CrawlRuns:
    job = Jobs(
        id=uuid4(),
        user_id=user_id,
        task=Task.CRAWL.value,
        status=Status.FAILED.value,
        name="Filter set crawl",
        result_location=None,
        finished_at=finished_at,
        created_at=finished_at - timedelta(minutes=5),
        updated_at=finished_at,
    )
    session.add(job)
    await session.flush()

    crawl_run = CrawlRuns(
        id=uuid4(),
        created_at=finished_at - timedelta(minutes=5),
        updated_at=finished_at,
        tenant_id=tenant_id,
        website_id=website_id,
        job_id=job.id,
        outcome_code=outcome_code.value,
        terminal_source=terminal_source.value if terminal_source is not None else None,
    )
    session.add(crawl_run)
    await session.flush()
    return crawl_run


@pytest.mark.asyncio
@pytest.mark.integration
async def test_recent_failures_outcome_filter_narrows_response(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """Recent failures with `outcome_code=CRAWL_NO_PAGES_RETURNED` returns
    only that subset; other failure outcomes are excluded."""
    finished_now = datetime.now(timezone.utc) - timedelta(hours=1)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
        )
        no_pages_run = await _create_failed_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=website.id,
            outcome_code=CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
            finished_at=finished_now,
        )
        await _create_failed_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=website.id,
            outcome_code=CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR,
            finished_at=finished_now - timedelta(minutes=10),
        )
        no_pages_run_id = no_pages_run.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/recent-failures",
        params={"outcome_code": CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED.value},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["crawl_run_id"] == str(no_pages_run_id)
    assert (
        data["items"][0]["outcome_code"]
        == CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED.value
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_recent_failures_rejects_unknown_outcome_filter(
    client,
    admin_user_api_key,
):
    response = await client.get(
        "/api/v1/admin/crawler/recent-failures",
        params={"outcome_code": "not-a-real-outcome"},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_watchdog_interventions_outcome_filter_narrows_response(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    finished_now = datetime.now(timezone.utc) - timedelta(hours=1)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
        )
        await _create_failed_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=website.id,
            outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
            finished_at=finished_now,
            terminal_source=CrawlTerminalSource.WATCHDOG,
        )
        zombie_run = await _create_failed_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=website.id,
            outcome_code=CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES,
            finished_at=finished_now - timedelta(minutes=10),
            terminal_source=CrawlTerminalSource.WATCHDOG,
        )
        zombie_run_id = zombie_run.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/watchdog-interventions",
        params={"outcome_code": CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES.value},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["crawl_run_id"] == str(zombie_run_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_recent_failures_rejects_non_failure_outcome(
    client,
    admin_user_api_key,
):
    """Filtering recent-failures by a non-failure outcome (e.g. duplicate skip
    or all-unchanged) must reject the request rather than silently returning
    zero rows so the operator gets immediate feedback that the filter is not
    meaningful here. The allowlist `RECENT_FAILURE_OUTCOME_CODES` is the
    contract."""
    response = await client.get(
        "/api/v1/admin/crawler/recent-failures",
        params={"outcome_code": CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED.value},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_failure_inventory_state_filter_returns_only_backed_off(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    next_retry = datetime.now(timezone.utc) + timedelta(hours=4)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        backed_off_website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
            consecutive_failures=3,
            next_retry_at=next_retry,
            name="Backed-off filter target",
        )
        await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.NEVER,
            consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
            next_retry_at=None,
            name="Auto-disabled filter target",
        )
        backed_off_website_id = backed_off_website.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/failure-inventory",
        params={"state": CrawlerFailureState.BACKED_OFF.value},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["website_id"] == str(backed_off_website_id)
    assert data["items"][0]["state"] == CrawlerFailureState.BACKED_OFF.value


@pytest.mark.asyncio
@pytest.mark.integration
async def test_failure_inventory_state_filter_returns_only_auto_disabled(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
            consecutive_failures=3,
            next_retry_at=datetime.now(timezone.utc) + timedelta(hours=2),
            name="Backed-off filter target",
        )
        paused_website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.NEVER,
            consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
            next_retry_at=None,
            name="Auto-disabled filter target",
        )
        paused_website_id = paused_website.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/failure-inventory",
        params={"state": CrawlerFailureState.AUTO_DISABLED.value},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["website_id"] == str(paused_website_id)
    assert data["items"][0]["state"] == CrawlerFailureState.AUTO_DISABLED.value


@pytest.mark.asyncio
@pytest.mark.integration
async def test_failure_inventory_state_filter_omitted_returns_both(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
            consecutive_failures=3,
            next_retry_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.NEVER,
            consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
            next_retry_at=None,
        )
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/failure-inventory",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert {item["state"] for item in data["items"]} == {
        CrawlerFailureState.BACKED_OFF.value,
        CrawlerFailureState.AUTO_DISABLED.value,
    }
