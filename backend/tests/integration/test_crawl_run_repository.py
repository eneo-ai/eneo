"""Integration coverage for crawl-run repository persistence."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.websites_table import Websites as WebsitesTable
from intric.main.models import Status
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawl_run import CrawlRun, CrawlType
from intric.websites.domain.crawl_run_repo import CrawlRunRepository
from intric.websites.domain.website import UpdateInterval


def _crawl_run_for_website(
    *,
    website_id: UUID,
    tenant_id: UUID,
    pages_source_retained: int,
    pages_hash_retained: int,
    files_hash_retained: int,
    files_too_large_skipped: int,
    outcome_code: CrawlOutcomeCode,
) -> CrawlRun:
    return CrawlRun(
        id=None,
        created_at=None,
        updated_at=None,
        website_id=website_id,
        tenant_id=tenant_id,
        pages_crawled=5,
        files_downloaded=0,
        pages_failed=1,
        files_failed=0,
        pages_source_retained=pages_source_retained,
        pages_hash_retained=pages_hash_retained,
        files_hash_retained=files_hash_retained,
        files_too_large_skipped=files_too_large_skipped,
        status=Status.QUEUED,
        result_location=None,
        finished_at=None,
        job_id=None,
        outcome_code=outcome_code,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_crawl_run_repository_round_trips_source_retention_fields(
    db_session,
    admin_user,
    space_factory,
):
    async with db_session() as session:
        embedding_model_id = await session.scalar(
            sa.select(EmbeddingModels.id).limit(1)
        )
        assert embedding_model_id is not None

        space = await space_factory(session, "Crawl run source retention space")
        website = WebsitesTable(
            name="Crawl run source retention site",
            url="https://example.com/source-retained",
            download_files=False,
            crawl_type=CrawlType.SITEMAP,
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

        repo = CrawlRunRepository(session)
        inserted = await repo.add(
            _crawl_run_for_website(
                website_id=website.id,
                tenant_id=admin_user.tenant_id,
                pages_source_retained=12,
                pages_hash_retained=4,
                files_hash_retained=1,
                files_too_large_skipped=2,
                outcome_code=CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY,
            )
        )
        assert inserted.id is not None
        inserted_id = inserted.id
        assert inserted.pages_source_retained == 12
        assert inserted.pages_hash_retained == 4
        assert inserted.files_hash_retained == 1
        assert inserted.files_too_large_skipped == 2
        assert inserted.outcome_code == CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY

    async with db_session() as session:
        repo = CrawlRunRepository(session)
        loaded = await repo.one(inserted_id)
        assert loaded.pages_source_retained == 12
        assert loaded.pages_hash_retained == 4
        assert loaded.files_hash_retained == 1
        assert loaded.files_too_large_skipped == 2
        assert loaded.outcome_code == CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY

        loaded.update(
            pages_source_retained=15,
            pages_hash_retained=8,
            files_hash_retained=2,
            files_too_large_skipped=3,
            outcome_code=CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES,
        )
        updated = await repo.update(loaded)
        assert updated.pages_source_retained == 15
        assert updated.pages_hash_retained == 8
        assert updated.files_hash_retained == 2
        assert updated.files_too_large_skipped == 3
        assert (
            updated.outcome_code == CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES
        )

    async with db_session() as session:
        repo = CrawlRunRepository(session)
        reloaded = await repo.one(inserted_id)
        assert reloaded.pages_source_retained == 15
        assert reloaded.pages_hash_retained == 8
        assert reloaded.files_hash_retained == 2
        assert reloaded.files_too_large_skipped == 3
        assert (
            reloaded.outcome_code == CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES
        )
