from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.database.tables.websites_table import Websites as WebsitesTable
from intric.info_blobs.info_blob_repo import InfoBlobRepository
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import UpdateInterval


async def _blob_exists(session, blob_id: UUID) -> bool:
    count = await session.scalar(
        sa.select(sa.func.count()).select_from(InfoBlobs).where(InfoBlobs.id == blob_id)
    )
    return count == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_website_blob_deletes_require_matching_tenant(db_session, admin_user):
    async with db_session() as session:
        embedding_model_id = await session.scalar(
            sa.select(EmbeddingModels.id).limit(1)
        )
        assert embedding_model_id is not None

        tenant = Tenants(
            name=f"tenant-scope-{uuid4().hex}",
            display_name="Tenant scoped delete",
            slug=f"tenant-scope-{uuid4().hex[:20]}",
            quota_limit=1_000_000,
        )
        session.add(tenant)
        await session.flush()

        user = Users(
            email=f"tenant-scope-{uuid4().hex}@example.com",
            tenant_id=tenant.id,
            state="active",
        )
        session.add(user)
        await session.flush()

        website = WebsitesTable(
            name="Tenant scoped website",
            url="https://example.com",
            download_files=False,
            crawl_type=CrawlType.CRAWL,
            update_interval=UpdateInterval.WEEKLY,
            size=0,
            tenant_id=tenant.id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
        )
        session.add(website)
        await session.flush()

        title = "https://example.com/shared-page"
        blob = InfoBlobs(
            text="same content",
            title=title,
            url=title,
            size=12,
            content_hash=b"x" * 32,
            user_id=user.id,
            tenant_id=tenant.id,
            website_id=website.id,
            embedding_model_id=embedding_model_id,
        )
        session.add(blob)
        await session.flush()

        repo = InfoBlobRepository(session)

        single_delete_result = await repo.delete_by_title_and_website(
            title=title,
            website_id=website.id,
            tenant_id=admin_user.tenant_id,
        )
        assert single_delete_result is None
        assert await _blob_exists(session, blob.id)

        batch_deleted = await repo.batch_delete_by_titles_and_website(
            titles=[title],
            website_id=website.id,
            tenant_id=admin_user.tenant_id,
        )
        assert batch_deleted == 0
        assert await _blob_exists(session, blob.id)

        batch_deleted = await repo.batch_delete_by_titles_and_website(
            titles=[title],
            website_id=website.id,
            tenant_id=tenant.id,
        )
        assert batch_deleted == 1
        assert not await _blob_exists(session, blob.id)
