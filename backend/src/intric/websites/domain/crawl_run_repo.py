from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.tables.job_table import Jobs
from intric.database.tables.websites_table import CrawlRuns as CrawlRunsTable
from intric.main.exceptions import NotFoundException
from intric.main.models import Status
from intric.websites.domain.crawl_outcome import (
    CrawlOutcomeCode,
    parse_crawl_outcome_code_strict,
)
from intric.websites.domain.crawl_run import CrawlRun
from intric.websites.domain.crawler_baseline import (
    CrawlerBaselineMetrics,
    CrawlerBaselineProcessingTotals,
    CrawlOutcomeBucket,
)

if TYPE_CHECKING:
    from intric.database.database import AsyncSession


def _serialize_crawl_outcome_code(
    outcome_code: CrawlOutcomeCode | None,
) -> str | None:
    return outcome_code.value if outcome_code is not None else None


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
                pages_source_retained=crawl_run.pages_source_retained,
                pages_hash_retained=crawl_run.pages_hash_retained,
                files_hash_retained=crawl_run.files_hash_retained,
                files_too_large_skipped=crawl_run.files_too_large_skipped,
                outcome_code=_serialize_crawl_outcome_code(crawl_run.outcome_code),
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
                pages_source_retained=crawl_run.pages_source_retained,
                pages_hash_retained=crawl_run.pages_hash_retained,
                files_hash_retained=crawl_run.files_hash_retained,
                files_too_large_skipped=crawl_run.files_too_large_skipped,
                outcome_code=_serialize_crawl_outcome_code(crawl_run.outcome_code),
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

    async def aggregate_baseline(
        self,
        *,
        since: datetime,
        until: datetime,
        window_days: int,
        tenant_id: UUID | None,
    ) -> CrawlerBaselineMetrics:
        base_conditions = [
            CrawlRunsTable.created_at >= since,
            CrawlRunsTable.created_at < until,
        ]
        if tenant_id is not None:
            base_conditions.append(CrawlRunsTable.tenant_id == tenant_id)

        terminal_condition = Jobs.finished_at.is_not(None)
        failed_condition = Jobs.status == Status.FAILED.value

        stmt = (
            sa.select(
                CrawlRunsTable.outcome_code.label("outcome_code"),
                sa.func.count(CrawlRunsTable.id).label("total_runs"),
                sa.func.count(CrawlRunsTable.id)
                .filter(terminal_condition)
                .label("terminal_runs"),
                sa.func.count(CrawlRunsTable.id)
                .filter(failed_condition)
                .label("failed_runs"),
                sa.func.coalesce(sa.func.sum(CrawlRunsTable.pages_crawled), 0).label(
                    "pages_crawled"
                ),
                sa.func.coalesce(sa.func.sum(CrawlRunsTable.files_downloaded), 0).label(
                    "files_downloaded"
                ),
                sa.func.coalesce(
                    sa.func.sum(CrawlRunsTable.pages_hash_retained), 0
                ).label("pages_hash_retained"),
                sa.func.coalesce(
                    sa.func.sum(CrawlRunsTable.files_hash_retained), 0
                ).label("files_hash_retained"),
                sa.func.coalesce(
                    sa.func.sum(CrawlRunsTable.pages_source_retained), 0
                ).label("pages_source_retained"),
                sa.func.coalesce(
                    sa.func.sum(CrawlRunsTable.files_too_large_skipped), 0
                ).label("files_too_large_skipped"),
                sa.func.coalesce(sa.func.sum(CrawlRunsTable.pages_failed), 0).label(
                    "pages_failed"
                ),
                sa.func.coalesce(sa.func.sum(CrawlRunsTable.files_failed), 0).label(
                    "files_failed"
                ),
            )
            .select_from(CrawlRunsTable)
            .outerjoin(Jobs, CrawlRunsTable.job_id == Jobs.id)
            .where(*base_conditions)
            .group_by(CrawlRunsTable.outcome_code)
        )
        result = await self.session.execute(stmt)

        total_runs = 0
        terminal_runs = 0
        failed_runs = 0
        failed_runs_without_typed_outcome = 0
        typed_failed_runs = 0
        typed_unknown_failed_runs = 0
        legacy_null_outcome_runs = 0
        unparseable_outcome_runs = 0
        outcome_counts_by_code: dict[CrawlOutcomeCode, int] = {}
        pages_crawled = 0
        files_downloaded = 0
        pages_hash_retained = 0
        files_hash_retained = 0
        pages_source_retained = 0
        files_too_large_skipped = 0
        pages_failed = 0
        files_failed = 0

        for row in result.mappings():
            row_total_runs = int(row["total_runs"])
            row_terminal_runs = int(row["terminal_runs"])
            row_failed_runs = int(row["failed_runs"])
            outcome_code_value = row["outcome_code"]

            total_runs += row_total_runs
            terminal_runs += row_terminal_runs
            failed_runs += row_failed_runs
            pages_crawled += int(row["pages_crawled"])
            files_downloaded += int(row["files_downloaded"])
            pages_hash_retained += int(row["pages_hash_retained"])
            files_hash_retained += int(row["files_hash_retained"])
            pages_source_retained += int(row["pages_source_retained"])
            files_too_large_skipped += int(row["files_too_large_skipped"])
            pages_failed += int(row["pages_failed"])
            files_failed += int(row["files_failed"])

            if outcome_code_value is None:
                legacy_null_outcome_runs += row_terminal_runs
                failed_runs_without_typed_outcome += row_failed_runs
                continue

            try:
                outcome_code = parse_crawl_outcome_code_strict(str(outcome_code_value))
            except ValueError:
                # Historical rows can contain outcome strings that predate the
                # closed enum. Count them without breaking the operator endpoint.
                unparseable_outcome_runs += row_terminal_runs
                continue

            if row_terminal_runs:
                outcome_counts_by_code[outcome_code] = (
                    outcome_counts_by_code.get(outcome_code, 0) + row_terminal_runs
                )
            if row_failed_runs:
                typed_failed_runs += row_failed_runs
            if outcome_code == CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR:
                typed_unknown_failed_runs += row_failed_runs

        return CrawlerBaselineMetrics(
            window_days=window_days,
            since=since,
            until=until,
            tenant_id=tenant_id,
            total_runs=total_runs,
            terminal_runs=terminal_runs,
            failed_runs=failed_runs,
            failed_runs_without_typed_outcome=failed_runs_without_typed_outcome,
            typed_failed_runs=typed_failed_runs,
            typed_unknown_failed_runs=typed_unknown_failed_runs,
            typed_unknown_failed_rate_percent=_percentage(
                numerator=typed_unknown_failed_runs,
                denominator=typed_failed_runs,
            ),
            legacy_null_outcome_runs=legacy_null_outcome_runs,
            unparseable_outcome_runs=unparseable_outcome_runs,
            outcome_counts=tuple(
                CrawlOutcomeBucket(code=code, count=count)
                for code, count in sorted(
                    outcome_counts_by_code.items(), key=lambda item: item[0].value
                )
            ),
            processing_totals=CrawlerBaselineProcessingTotals(
                pages_crawled=pages_crawled,
                files_downloaded=files_downloaded,
                pages_hash_retained=pages_hash_retained,
                files_hash_retained=files_hash_retained,
                pages_source_retained=pages_source_retained,
                files_too_large_skipped=files_too_large_skipped,
                pages_failed=pages_failed,
                files_failed=files_failed,
            ),
        )


def _percentage(*, numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)
