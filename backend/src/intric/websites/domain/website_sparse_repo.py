from typing import TYPE_CHECKING

import sqlalchemy as sa

from intric.database.tables.websites_table import Websites as WebsitesTable
from intric.websites.domain.website import UpdateInterval, WebsiteSparse

if TYPE_CHECKING:
    from intric.database.database import AsyncSession


class WebsiteSparseRepository:
    def __init__(self, session: "AsyncSession"):
        self.session = session

    async def get_weekly_websites(self) -> list[WebsiteSparse]:
        stmt = sa.select(WebsitesTable).where(
            WebsitesTable.update_interval == UpdateInterval.WEEKLY
        )

        websites_db = await self.session.scalars(stmt)

        return [WebsiteSparse.to_domain(website_db) for website_db in websites_db]
    
    async def get_websites_by_interval(self, interval: UpdateInterval) -> list[WebsiteSparse]:
        stmt = sa.select(WebsitesTable).where(
            WebsitesTable.update_interval == interval
        )

        websites_db = await self.session.scalars(stmt)

        return [WebsiteSparse.to_domain(website_db) for website_db in websites_db]
