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


async def test_due_websites_follow_the_shared_interval_table(
    db_session, admin_user, space_factory
):
    """Daily, every-other-day and weekly thresholds, the Friday gate and the
    circuit breaker all come from crawl_schedule and behave as one table."""
    now = datetime.now(timezone.utc)
    tag = uuid4().hex[:8]
    hours = timedelta(hours=1)
    cases = {
        "daily-25h": ("daily", now - 25 * hours, None, True),
        "daily-23h": ("daily", now - 23 * hours, None, False),
        "eod-49h": ("every_other_day", now - 49 * hours, None, True),
        "eod-47h": ("every_other_day", now - 47 * hours, None, False),
        "weekly-8d": ("weekly", now - 8 * 24 * hours, None, "friday"),
        "weekly-6d": ("weekly", now - 6 * 24 * hours, None, False),
        "never-crawled": ("daily", None, None, True),
        "backoff-future": ("daily", now - 25 * hours, now + hours, False),
        "backoff-past": ("daily", now - 25 * hours, now - hours, True),
        "never": ("never", None, None, False),
    }
    ids: dict[str, object] = {}
    async with db_session() as session:
        embedding_model_id = await session.scalar(
            sa.select(EmbeddingModels.id).limit(1)
        )
        space = await space_factory(session, f"Interval table {tag}")
        for label, (interval, last_crawled_at, next_retry_at, _) in cases.items():
            website = WebsitesTable(
                name=label,
                url=f"https://{tag}-{label}.example",
                download_files=False,
                crawl_type=CrawlType.CRAWL,
                update_interval=interval,
                size=0,
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                embedding_model_id=embedding_model_id,
                space_id=space.id,
                last_crawled_at=last_crawled_at,
                next_retry_at=next_retry_at,
            )
            session.add(website)
            await session.flush()
            ids[label] = website.id

    friday = datetime(2026, 9, 25, tzinfo=timezone.utc).date()
    thursday = datetime(2026, 9, 24, tzinfo=timezone.utc).date()
    async with db_session() as session:
        repo = WebsiteSparseRepository(session)
        due_friday = {site.id for site in await repo.get_due_websites(friday)}
        due_thursday = {site.id for site in await repo.get_due_websites(thursday)}

    for label, (_, _, _, expected) in cases.items():
        on_friday = expected in (True, "friday")
        on_thursday = expected is True
        assert (ids[label] in due_friday) is on_friday, f"{label} on Friday"
        assert (ids[label] in due_thursday) is on_thursday, f"{label} on Thursday"
