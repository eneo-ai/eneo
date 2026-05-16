"""Integration tests for crawl scheduler de-duplication."""

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.job_table import Jobs
from intric.database.tables.websites_table import CrawlRuns as CrawlRunsTable
from intric.database.tables.websites_table import Websites as WebsitesTable
from intric.jobs.job_models import Task
from intric.main.models import Status
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import UpdateInterval
from intric.websites.domain.website_sparse_repo import WebsiteSparseRepository
from intric.worker.crawl.duplicate_guard import find_primary_active_job_id


async def _create_scheduled_website(
    session,
    *,
    admin_user,
    space_factory,
    name: str,
    url: str,
    update_interval: UpdateInterval,
    last_crawled_at: datetime | None,
    next_retry_at: datetime | None = None,
) -> WebsitesTable:
    embedding_model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
    assert embedding_model_id is not None

    space = await space_factory(session, f"{name} space")

    website = WebsitesTable(
        name=name,
        url=url,
        download_files=False,
        crawl_type=CrawlType.CRAWL,
        update_interval=update_interval,
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
    return website


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("update_interval", "last_crawled_delta", "expected_due"),
    [
        (UpdateInterval.DAILY, timedelta(hours=23, minutes=59), False),
        (UpdateInterval.DAILY, timedelta(hours=24, minutes=1), True),
        (UpdateInterval.EVERY_OTHER_DAY, timedelta(hours=47, minutes=59), False),
        (UpdateInterval.EVERY_OTHER_DAY, timedelta(hours=48, minutes=1), True),
        (UpdateInterval.WEEKLY, timedelta(days=6, hours=23, minutes=59), False),
        (UpdateInterval.WEEKLY, timedelta(days=7, minutes=1), True),
    ],
)
async def test_scheduler_uses_one_as_of_timestamp_for_interval_thresholds(
    db_session,
    admin_user,
    space_factory,
    update_interval: UpdateInterval,
    last_crawled_delta: timedelta,
    expected_due: bool,
):
    as_of = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)  # Friday

    async with db_session() as session:
        website = await _create_scheduled_website(
            session,
            admin_user=admin_user,
            space_factory=space_factory,
            name=f"Scheduler interval {update_interval.value}",
            url=f"https://example.com/scheduler/{update_interval.value}/{expected_due}",
            update_interval=update_interval,
            last_crawled_at=as_of - last_crawled_delta,
        )
        website_id = website.id

    async with db_session() as session:
        repo = WebsiteSparseRepository(session)
        due = await repo.get_due_websites(as_of)

    due_ids = {site.id for site in due}
    assert (website_id in due_ids) is expected_due


@pytest.mark.integration
@pytest.mark.asyncio
async def test_weekly_scheduler_only_runs_on_fridays(
    db_session,
    admin_user,
    space_factory,
):
    thursday = datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc)

    async with db_session() as session:
        website = await _create_scheduled_website(
            session,
            admin_user=admin_user,
            space_factory=space_factory,
            name="Scheduler weekly Thursday",
            url="https://example.com/scheduler/weekly-thursday",
            update_interval=UpdateInterval.WEEKLY,
            last_crawled_at=thursday - timedelta(days=14),
        )
        website_id = website.id

    async with db_session() as session:
        repo = WebsiteSparseRepository(session)
        due = await repo.get_due_websites(thursday)

    due_ids = {site.id for site in due}
    assert website_id not in due_ids


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("next_retry_delta", "expected_due"),
    [
        (timedelta(minutes=1), False),
        (timedelta(seconds=0), True),
        (timedelta(minutes=-1), True),
    ],
)
async def test_scheduler_respects_circuit_breaker_retry_timestamp(
    db_session,
    admin_user,
    space_factory,
    next_retry_delta: timedelta,
    expected_due: bool,
):
    as_of = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)

    async with db_session() as session:
        website = await _create_scheduled_website(
            session,
            admin_user=admin_user,
            space_factory=space_factory,
            name="Scheduler circuit breaker",
            url=f"https://example.com/scheduler/backoff/{expected_due}",
            update_interval=UpdateInterval.DAILY,
            last_crawled_at=as_of - timedelta(days=2),
            next_retry_at=as_of + next_retry_delta,
        )
        website_id = website.id

    async with db_session() as session:
        repo = WebsiteSparseRepository(session)
        due = await repo.get_due_websites(as_of)

    due_ids = {site.id for site in due}
    assert (website_id in due_ids) is expected_due


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scheduler_skips_websites_with_active_jobs(
    db_session,
    admin_user,
    space_factory,
):
    as_of = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)

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
            last_crawled_at=as_of - timedelta(days=2),
        )
        session.add(website)
        await session.flush()
        website_id = website.id

        job = Jobs(
            user_id=admin_user.id,
            task=Task.CRAWL,
            status=Status.IN_PROGRESS.value,
            name="Scheduler crawl",
        )
        session.add(job)
        await session.flush()

        crawl_run = CrawlRunsTable(
            tenant_id=admin_user.tenant_id,
            website_id=website_id,
            job_id=job.id,
            pages_crawled=None,
            files_downloaded=None,
            pages_failed=None,
            files_failed=None,
        )
        session.add(crawl_run)

    async with db_session() as session:
        repo = WebsiteSparseRepository(session)
        due = await repo.get_due_websites(as_of)

    due_ids = {site.id for site in due}
    assert website_id not in due_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_primary_active_job_id_selects_oldest_active_job(
    db_session,
    admin_user,
    space_factory,
):
    async with db_session() as session:
        embedding_model_id = await session.scalar(
            sa.select(EmbeddingModels.id).limit(1)
        )
        assert embedding_model_id is not None

        space = await space_factory(session, "Scheduler dedupe space")
        website = WebsitesTable(
            name="Scheduler dedupe site",
            url="https://example.com/dedupe",
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

        job_1 = Jobs(
            user_id=admin_user.id,
            task=Task.CRAWL,
            status=Status.QUEUED.value,
            name="Scheduler job 1",
        )
        session.add(job_1)
        await session.flush()

        await session.execute(
            sa.update(Jobs)
            .where(Jobs.id == job_1.id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(hours=1))
        )

        job_2 = Jobs(
            user_id=admin_user.id,
            task=Task.CRAWL,
            status=Status.QUEUED.value,
            name="Scheduler job 2",
        )
        session.add(job_2)
        await session.flush()

        crawl_run_1 = CrawlRunsTable(
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=job_1.id,
            pages_crawled=None,
            files_downloaded=None,
            pages_failed=None,
            files_failed=None,
        )
        crawl_run_2 = CrawlRunsTable(
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=job_2.id,
            pages_crawled=None,
            files_downloaded=None,
            pages_failed=None,
            files_failed=None,
        )
        session.add(crawl_run_1)
        session.add(crawl_run_2)

        website_id = website.id
        job_1_id = job_1.id

    async with db_session() as session:
        primary_job_id = await find_primary_active_job_id(
            session,
            website_id=website_id,
        )

    assert primary_job_id == job_1_id
