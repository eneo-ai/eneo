from typing import TYPE_CHECKING

import sqlalchemy as sa

from intric.database.tables.info_blobs_table import InfoBlobs as InfoBlobsTable
from intric.database.tables.websites_table import Websites as WebsitesTable

if TYPE_CHECKING:
    from uuid import UUID

    from intric.database.database import AsyncSession


class UpdateWebsiteSizeService:
    def __init__(self, session: "AsyncSession"):
        super().__init__()
        self.session = session

    async def update_website_size(self, website_id: "UUID") -> None:
        update_size_stmt = (
            sa.select(sa.func.coalesce(sa.func.sum(InfoBlobsTable.size), 0))
            .where(InfoBlobsTable.website_id == website_id)
            .scalar_subquery()
        )

        stmt = (
            sa.update(WebsitesTable)
            .where(WebsitesTable.id == website_id)
            .values(size=update_size_stmt)
        )

        await self.session.execute(stmt)
