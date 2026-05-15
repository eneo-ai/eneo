from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.info_blobs_table import InfoBlobs as InfoBlobsTable
from intric.database.tables.websites_table import Websites as WebsitesTable


async def update_website_size_after_crawl(
    sess: AsyncSession,
    *,
    website_id: UUID,
    tenant_id: UUID,
) -> None:
    size_subquery = (
        sa.select(sa.func.coalesce(sa.func.sum(InfoBlobsTable.size), 0))
        .where(InfoBlobsTable.website_id == website_id)
        .where(InfoBlobsTable.tenant_id == tenant_id)
        .scalar_subquery()
    )
    stmt = (
        sa.update(WebsitesTable)
        .where(WebsitesTable.id == website_id)
        .where(WebsitesTable.tenant_id == tenant_id)
        .values(size=size_subquery)
    )
    await sess.execute(stmt)
