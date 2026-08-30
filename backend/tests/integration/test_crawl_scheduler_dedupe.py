"""Integration tests for crawl scheduler de-duplication."""

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import EmbeddingModels
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

        crawl_run = CrawlRunsTable(
            tenant_id=admin_user.tenant_id,
            website_id=website_id,
            phase=CrawlPhase.RUNNING.value,
            origin=CrawlOrigin.SCHEDULED.value,
            attempt_count=1,
            pages_crawled=None,
            files_downloaded=None,
            pages_failed=None,
            files_failed=None,
        )
        session.add(crawl_run)

    async with db_session() as session:
        repo = WebsiteSparseRepository(session)
        due = await repo.get_due_websites(datetime.now(timezone.utc).date())

    due_ids = {site.id for site in due}
    assert website_id not in due_ids
