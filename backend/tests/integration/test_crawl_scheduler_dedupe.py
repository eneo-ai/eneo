"""Integration tests for crawl scheduler de-duplication."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.websites_table import CrawlAttempts
from eneo.database.tables.websites_table import CrawlRuns as CrawlRunsTable
from eneo.database.tables.websites_table import Websites as WebsitesTable
from eneo.websites.domain.crawl_run import CrawlOrigin, CrawlPhase, CrawlType
from eneo.websites.domain.website import UpdateInterval
from eneo.websites.domain.website_sparse_repo import WebsiteSparseRepository


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scheduler_skips_websites_with_active_crawl_runs(
    db_session,
    admin_user,
    space_factory,
):
    async with db_session() as session:
        embedding_model_id = await session.scalar(
            sa.select(EmbeddingModels.id).limit(1)
        )
        assert embedding_model_id is not None

        space = await space_factory(session, "Scheduler test space")

        website = WebsitesTable(
            name="Scheduler test site",
            url="https://example.com",
            download_files=False,
            crawl_type=CrawlType.CRAWL,
            update_interval=UpdateInterval.DAILY,
            size=0,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            space_id=space.id,
            last_crawled_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        session.add(website)
        await session.flush()
        website_id = website.id

        job = Jobs(
            user_id=admin_user.id,
            task="crawl",
            status="queued",
            name="Scheduled crawl",
        )
        session.add(job)
        await session.flush()
        crawl_run_id = uuid4()
        crawl_run = CrawlRunsTable(
            id=crawl_run_id,
            tenant_id=admin_user.tenant_id,
            website_id=website_id,
            job_id=job.id,
            phase=CrawlPhase.RUNNING.value,
            origin=CrawlOrigin.SCHEDULED.value,
            attempt_count=1,
            pages_crawled=None,
            files_downloaded=None,
            pages_failed=None,
            files_failed=None,
        )
        session.add(crawl_run)
        await session.flush()
        attempt = CrawlAttempts(
            crawl_run_id=crawl_run_id,
            attempt_number=1,
            dispatch_id=job.id,
            dispatch_payload={},
        )
        session.add(attempt)

    async with db_session() as session:
        repo = WebsiteSparseRepository(session)
        due = await repo.get_due_websites(datetime.now(timezone.utc).date())

    due_ids = {site.id for site in due}
    assert website_id not in due_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scheduler_uses_settings_committed_after_due_query(
    db_session, db_container, admin_user, space_factory, monkeypatch
):
    from unittest.mock import AsyncMock

    from dependency_injector import providers

    from eneo.websites.application import crawl_dispatch
    from eneo.websites.domain.website import WebsiteSparse
    from eneo.worker import crawl_tasks

    async with db_session() as session:
        space = await space_factory(session, "Updated scheduler settings")
        embedding_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
        site = WebsitesTable(
            name="Old name", url="https://example.com/old", download_files=False,
            crawl_type=CrawlType.CRAWL, update_interval=UpdateInterval.DAILY,
            size=0, tenant_id=admin_user.tenant_id, user_id=admin_user.id,
            embedding_model_id=embedding_id, space_id=space.id,
        )
        session.add(site)
        await session.flush()
        stale = WebsiteSparse.to_domain(site)

    async def due_query():
        async with db_session() as session:
            await session.execute(
                sa.update(WebsitesTable).where(WebsitesTable.id == stale.id).values(
                    name="Current name", url="https://example.com/new.xml",
                    download_files=True, crawl_type=CrawlType.SITEMAP,
                )
            )
        return [stale]

    monkeypatch.setattr(crawl_dispatch, "reconcile_crawl_work", AsyncMock())
    async with db_container(user=admin_user) as container:
        scheduler = container.crawl_scheduler_service()
        monkeypatch.setattr(scheduler, "get_websites_due_for_crawl", due_query)
        container.crawl_scheduler_service.override(providers.Object(scheduler))
        assert await crawl_tasks.queue_website_crawls(container)

    async with db_session() as session:
        run = await session.scalar(
            sa.select(CrawlRunsTable).where(CrawlRunsTable.website_id == stale.id)
        )
        assert run is not None
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        data = attempt.dispatch_payload
        assert data["url"] == "https://example.com/new.xml"
        assert data["download_files"] is True
        assert data["crawl_type"] == "sitemap"
        job = await session.get(Jobs, run.job_id)
        assert job.name == "Current name"
