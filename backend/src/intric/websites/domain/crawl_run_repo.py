from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.tables.websites_table import CrawlRuns as CrawlRunsTable
from intric.main.exceptions import NotFoundException
from intric.websites.domain.crawl_run import CrawlRun

if TYPE_CHECKING:
    from intric.database.database import AsyncSession


class CrawlRunRepository:
    def __init__(self, session: "AsyncSession"):
        super().__init__()
        self.session = session

    async def one(self, id: UUID) -> CrawlRun:
        crawl_run = await self.one_or_none(id)

        if crawl_run is None:
            raise NotFoundException()

        return crawl_run

    async def one_or_none(self, id: UUID) -> CrawlRun | None:
        stmt = (
            sa.select(CrawlRunsTable)
            .where(CrawlRunsTable.id == id)
            .options(selectinload(CrawlRunsTable.job))
        )
        record = await self.session.scalar(stmt)

        if record is None:
            return None

        return CrawlRun.to_domain(record=record)

    async def add(self, crawl_run: CrawlRun) -> CrawlRun:
        stmt = (
            sa.insert(CrawlRunsTable)
            .values(
                website_id=crawl_run.website_id,
                tenant_id=crawl_run.tenant_id,
                pages_crawled=crawl_run.pages_crawled,
                files_downloaded=crawl_run.files_downloaded,
                pages_failed=crawl_run.pages_failed,
                files_failed=crawl_run.files_failed,
                job_id=crawl_run.job_id,
            )
            .options(selectinload(CrawlRunsTable.job))
            .returning(CrawlRunsTable)
        )
        record = await self.session.scalar(stmt)
        if record is None:
            raise RuntimeError("Insert into crawl_runs did not return a record")
        return CrawlRun.to_domain(record=record)

    async def update(self, crawl_run: CrawlRun) -> CrawlRun:
        stmt = (
            sa.update(CrawlRunsTable)
            .values(
                pages_crawled=crawl_run.pages_crawled,
                files_downloaded=crawl_run.files_downloaded,
                pages_failed=crawl_run.pages_failed,
                files_failed=crawl_run.files_failed,
                job_id=crawl_run.job_id,
            )
            .where(CrawlRunsTable.id == crawl_run.id)
            .options(selectinload(CrawlRunsTable.job))
            .returning(CrawlRunsTable)
        )
        record = await self.session.scalar(stmt)
        if record is None:
            raise RuntimeError("Update of crawl_run did not return a record")
        return CrawlRun.to_domain(record=record)

    async def get_crawl_runs(self, website_id: UUID) -> list[CrawlRun]:
        stmt = (
            sa.select(CrawlRunsTable)
            .where(CrawlRunsTable.website_id == website_id)
            .options(selectinload(CrawlRunsTable.job))
        )
        records = await self.session.scalars(stmt)
        return [CrawlRun.to_domain(record=record) for record in records]
