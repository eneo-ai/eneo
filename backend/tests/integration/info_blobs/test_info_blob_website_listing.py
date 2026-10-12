from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import sqlalchemy as sa

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.websites_table import Websites
from eneo.websites.domain.crawl_run import CrawlType


async def test_get_by_website_loads_website_without_lazy_load(db_container) -> None:
    """Regression: listing a website's info-blobs from a fresh session must not
    trigger a lazy load of ``InfoBlobs.website`` (MissingGreenlet under asyncio)."""
    text = "Crawled page content"

    async with db_container() as container:
        session = container.session()
        user = container.user()
        embedding_model_id = await session.scalar(
            sa.select(EmbeddingModels.id).limit(1)
        )
        assert embedding_model_id is not None
        website = Websites(
            name="Listing website",
            url="https://listing.example.com",
            download_files=False,
            crawl_type=CrawlType.CRAWL,
            update_interval="never",
            size=0,
            tenant_id=user.tenant_id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
        )
        session.add(website)
        await session.flush()
        session.add(
            InfoBlobs(
                title="page.html",
                text=text,
                size=len(text.encode("utf-8")),
                content_hash=sha256(text.encode("utf-8")).digest(),
                source_id=uuid4(),
                version_state=InfoBlobVersionState.ACTIVE.value,
                user_id=user.id,
                tenant_id=user.tenant_id,
                website_id=website.id,
                embedding_model_id=embedding_model_id,
            )
        )
        await session.flush()
        website_id = website.id

    async with db_container() as container:
        blobs = await container.info_blob_repo().get_by_website(website_id)

    assert [blob.website.id for blob in blobs if blob.website] == [website_id]
