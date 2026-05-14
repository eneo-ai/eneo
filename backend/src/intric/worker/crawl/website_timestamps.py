from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.websites_table import Websites as WebsitesTable
from intric.websites.domain.crawl_run import CrawlType

_WebsiteTimestampField = Literal["last_crawled_at", "last_source_verified_at"]


def _timestamp_fields_after_crawl(
    *,
    crawl_type: CrawlType,
    crawl_is_partial: bool,
    pages_failed: int,
    files_failed: int,
) -> tuple[_WebsiteTimestampField, ...]:
    """Return website timestamp fields advanced after a non-terminal crawl."""
    if (
        crawl_type == CrawlType.SITEMAP
        and not crawl_is_partial
        and pages_failed == 0
        and files_failed == 0
    ):
        return ("last_crawled_at", "last_source_verified_at")

    return ("last_crawled_at",)


async def update_website_timestamps_after_crawl(
    sess: AsyncSession,
    *,
    website_id: UUID,
    tenant_id: UUID,
    crawl_type: CrawlType,
    crawl_is_partial: bool,
    pages_failed: int,
    files_failed: int,
) -> None:
    """Apply the post-crawl website timestamp policy."""
    timestamp_fields = _timestamp_fields_after_crawl(
        crawl_type=crawl_type,
        crawl_is_partial=crawl_is_partial,
        pages_failed=pages_failed,
        files_failed=files_failed,
    )
    timestamp_values = {field: sa.func.now() for field in timestamp_fields}

    stmt = (
        sa.update(WebsitesTable)
        .where(WebsitesTable.id == website_id)
        .where(WebsitesTable.tenant_id == tenant_id)
        .values(**timestamp_values)
    )
    await sess.execute(stmt)
