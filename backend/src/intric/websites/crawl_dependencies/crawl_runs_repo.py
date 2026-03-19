from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.websites_table import CrawlRuns
from intric.websites.crawl_dependencies.crawl_models import (
    CrawlRun,
    CrawlRunCreate,
    CrawlRunUpdate,
)


class CrawlRunRepository:
    def __init__(self, session: AsyncSession):
        self.delegate: BaseRepositoryDelegate[CrawlRun] = BaseRepositoryDelegate(
            session=session,
            table=CrawlRuns,
            in_db_model=CrawlRun,
            with_options=self._get_options(),
        )

    @staticmethod
    def _get_options():
        return [
            selectinload(CrawlRuns.job),
        ]

    async def add(self, crawl: CrawlRunCreate) -> CrawlRun:
        return await self.delegate.add(crawl)

    async def get(self, id: UUID) -> CrawlRun | None:
        return await self.delegate.get(id)

    async def get_by_website(self, website_id: UUID) -> list[CrawlRun]:
        return await self.delegate.filter_by(
            conditions={CrawlRuns.website_id: website_id}
        )

    async def get_latest_run_for_website(self, website_id: UUID) -> CrawlRun | None:
        stmt = (
            sa.select(CrawlRuns)
            .where(CrawlRuns.website_id == website_id)
            .order_by(CrawlRuns.created_at.desc())
            .limit(1)
        )

        return await self.delegate.get_model_from_query(stmt)

    async def update(self, crawl: CrawlRunUpdate) -> CrawlRun | None:
        return await self.delegate.update(crawl)
