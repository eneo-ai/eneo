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
        """Get websites with weekly update intervals.

        Why: Preserves existing API for backwards compatibility.
        """
        stmt = sa.select(WebsitesTable).where(
            WebsitesTable.update_interval == UpdateInterval.WEEKLY
        )

        websites_db = await self.session.scalars(stmt)

        return [WebsiteSparse.to_domain(website_db) for website_db in websites_db]

    async def get_websites_with_intervals(self) -> list[WebsiteSparse]:
        """Get all websites that have active update intervals (not NEVER).

        Why: Enables scheduler service to apply interval logic consistently.
        Excludes NEVER websites to avoid unnecessary processing.

        Returns:
            List of websites with DAILY, EVERY_OTHER_DAY, or WEEKLY intervals
        """
        stmt = sa.select(WebsitesTable).where(
            WebsitesTable.update_interval != UpdateInterval.NEVER
        )

        websites_db = await self.session.scalars(stmt)

        return [WebsiteSparse.to_domain(website_db) for website_db in websites_db]
