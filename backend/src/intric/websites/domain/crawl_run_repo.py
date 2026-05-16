from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.job_table import Jobs
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.database.tables.websites_table import CrawlRuns as CrawlRunsTable
from intric.database.tables.websites_table import Websites
from intric.jobs.job_models import Task
from intric.main.exceptions import NotFoundException
from intric.main.models import Status
from intric.websites.domain.crawl_abort import is_crawl_abortable_target
from intric.websites.domain.crawl_lifecycle import derive_crawl_lifecycle_from_counters
from intric.websites.domain.crawl_outcome import (
    CrawlOutcomeCode,
    parse_crawl_outcome_code_lenient,
    parse_crawl_outcome_code_strict,
    parse_failure_summary_lenient,
    report_legacy_failure_summary_key_dropped,
)
from intric.websites.domain.crawl_run import (
    CrawlRun,
    serialize_crawl_file_too_large_samples,
)
from intric.websites.domain.crawl_terminal import (
    TerminalCommitResult,
    TerminalEvent,
    commit_terminal,
)
from intric.websites.domain.crawler_active_inventory import (
    CrawlerActiveInventory,
    CrawlerActiveInventoryItem,
)
from intric.websites.domain.crawler_baseline import (
    CrawlerBaselineMetrics,
    CrawlerBaselineProcessingTotals,
    CrawlOutcomeBucket,
)
from intric.websites.domain.crawler_recent_failures import (
    RECENT_FAILURE_OUTCOME_CODES,
    WATCHDOG_INTERVENTION_OUTCOME_CODES,
    CrawlerRecentFailureItem,
    CrawlerRecentFailures,
)
from intric.websites.domain.crawler_website_processing_aggregate import (
    SCHEDULE_FREQUENCY_WEIGHTS,
    CrawlerWebsiteProcessingAggregate,
    CrawlerWebsiteProcessingAggregateItem,
    cost_pressure_score,
    parse_update_interval_for_cost_score,
    retention_rate,
    schedule_frequency_weight,
)

if TYPE_CHECKING:
    from intric.database.database import AsyncSession


def _serialize_crawl_outcome_code(
    outcome_code: CrawlOutcomeCode | None,
) -> str | None:
    return outcome_code.value if outcome_code is not None else None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    raise TypeError(f"Expected integer crawl counter, got {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class CrawlAbortTarget:
    job_id: UUID
    crawl_run_id: UUID
    website_id: UUID
    website_name: str | None
    website_url: str
    tenant_id: UUID
    status: Status
    outcome_code: CrawlOutcomeCode | None


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
                files_too_large_download_limit_bytes=(
                    crawl_run.files_too_large_download_limit_bytes
                ),
                files_too_large_samples=serialize_crawl_file_too_large_samples(
                    crawl_run.files_too_large_samples
                ),
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
                files_too_large_download_limit_bytes=(
                    crawl_run.files_too_large_download_limit_bytes
                ),
                files_too_large_samples=serialize_crawl_file_too_large_samples(
                    crawl_run.files_too_large_samples
                ),
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

    async def commit_terminal(self, event: TerminalEvent) -> TerminalCommitResult:
        """Multi-table terminal write delegated to crawl_terminal; this repo owns the session."""
        return await commit_terminal(self.session, event)

    async def abort_target_for_tenant(
        self,
        *,
        job_id: UUID,
        tenant_id: UUID,
    ) -> CrawlAbortTarget | None:
        stmt = (
            sa.select(
                Jobs.id.label("job_id"),
                Jobs.status.label("job_status"),
                CrawlRunsTable.id.label("crawl_run_id"),
                CrawlRunsTable.website_id,
                Websites.name.label("website_name"),
                Websites.url.label("website_url"),
                CrawlRunsTable.tenant_id,
                CrawlRunsTable.outcome_code,
            )
            .select_from(Jobs)
            .join(CrawlRunsTable, CrawlRunsTable.job_id == Jobs.id)
            .join(Websites, CrawlRunsTable.website_id == Websites.id)
            .where(
                Jobs.id == job_id,
                Jobs.task == Task.CRAWL.value,
                CrawlRunsTable.tenant_id == tenant_id,
            )
        )
        row = (await self.session.execute(stmt)).mappings().first()
        if row is None:
            return None

        return CrawlAbortTarget(
            job_id=row["job_id"],
            crawl_run_id=row["crawl_run_id"],
            website_id=row["website_id"],
            website_name=row["website_name"],
            website_url=row["website_url"],
            tenant_id=row["tenant_id"],
            status=Status(str(row["job_status"])),
            outcome_code=parse_crawl_outcome_code_lenient(row["outcome_code"]),
        )

    async def get_crawl_runs(self, website_id: UUID) -> list[CrawlRun]:
        stmt = (
            sa.select(CrawlRunsTable)
            .where(CrawlRunsTable.website_id == website_id)
            .options(selectinload(CrawlRunsTable.job))
        )
        records = await self.session.scalars(stmt)
        return [CrawlRun.to_domain(record=record) for record in records]

    async def active_inventory_for_tenant(
        self,
        *,
        limit: int,
        offset: int,
        tenant_id: UUID,
    ) -> CrawlerActiveInventory:
        return await self._active_inventory(
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
        )

    async def active_inventory_for_sysadmin(
        self,
        *,
        limit: int,
        offset: int,
        tenant_id: UUID | None,
    ) -> CrawlerActiveInventory:
        return await self._active_inventory(
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
        )

    async def _active_inventory(
        self,
        *,
        limit: int,
        offset: int,
        tenant_id: UUID | None,
    ) -> CrawlerActiveInventory:
        active_conditions = [
            Jobs.task == Task.CRAWL.value,
            Jobs.status.in_([Status.QUEUED.value, Status.IN_PROGRESS.value]),
        ]
        if tenant_id is not None:
            # Orphan queued jobs have no crawl run yet; filtering on the
            # outer-joined crawl run tenant column intentionally excludes them.
            active_conditions.append(CrawlRunsTable.tenant_id == tenant_id)

        base_from = sa.outerjoin(Jobs, CrawlRunsTable, Jobs.id == CrawlRunsTable.job_id)
        # Attribution LEFT JOINs are PK-equality lookups and cannot multiply
        # rows; they are kept off the count query because the count only
        # needs Jobs ∪ CrawlRuns and the planner can skip them entirely.
        # Each join predicate is tenant-qualified so a malformed cross-tenant
        # FK (admin import, recovery path bug, backfill regression) fails
        # closed — all six attribution fields render as null together rather
        # than leaking another tenant's space/collection name or user email.
        rows_from = sa.outerjoin(
            sa.outerjoin(
                sa.outerjoin(
                    sa.outerjoin(
                        sa.outerjoin(
                            base_from,
                            Websites,
                            sa.and_(
                                CrawlRunsTable.website_id == Websites.id,
                                Websites.tenant_id == CrawlRunsTable.tenant_id,
                            ),
                        ),
                        Tenants,
                        CrawlRunsTable.tenant_id == Tenants.id,
                    ),
                    Spaces,
                    sa.and_(
                        Websites.space_id == Spaces.id,
                        Spaces.tenant_id == CrawlRunsTable.tenant_id,
                    ),
                ),
                CollectionsTable,
                sa.and_(
                    Websites.group_id == CollectionsTable.id,
                    CollectionsTable.tenant_id == CrawlRunsTable.tenant_id,
                ),
            ),
            Users,
            sa.and_(
                Jobs.user_id == Users.id,
                Users.tenant_id == CrawlRunsTable.tenant_id,
                Users.deleted_at.is_(None),
            ),
        )
        total_stmt = (
            sa.select(sa.func.count(Jobs.id))
            .select_from(base_from)
            .where(*active_conditions)
        )
        total = int(await self.session.scalar(total_stmt) or 0)

        rows_stmt = (
            sa.select(
                Jobs.id.label("job_id"),
                Jobs.status.label("job_status"),
                Jobs.created_at.label("job_created_at"),
                Jobs.updated_at.label("job_updated_at"),
                CrawlRunsTable.id.label("crawl_run_id"),
                CrawlRunsTable.website_id.label("website_id"),
                Websites.name.label("website_name"),
                # Project the joined-row IDs (not the raw FK columns) so the
                # six attribution fields share one fail-closed contract:
                # when a join predicate filters out a cross-tenant or
                # soft-deleted row the ID renders null alongside the name.
                Spaces.id.label("space_id"),
                Spaces.name.label("space_name"),
                CollectionsTable.id.label("collection_id"),
                CollectionsTable.name.label("collection_name"),
                Users.id.label("user_started_by_id"),
                Users.email.label("user_started_by_email"),
                CrawlRunsTable.tenant_id.label("tenant_id"),
                Tenants.display_name.label("tenant_display_name"),
                CrawlRunsTable.created_at.label("crawl_run_created_at"),
                CrawlRunsTable.pages_crawled.label("pages_crawled"),
                CrawlRunsTable.files_downloaded.label("files_downloaded"),
                CrawlRunsTable.pages_failed.label("pages_failed"),
                CrawlRunsTable.files_failed.label("files_failed"),
                CrawlRunsTable.pages_source_retained.label("pages_source_retained"),
                CrawlRunsTable.pages_hash_retained.label("pages_hash_retained"),
                CrawlRunsTable.files_hash_retained.label("files_hash_retained"),
                CrawlRunsTable.files_too_large_skipped.label("files_too_large_skipped"),
            )
            .select_from(rows_from)
            .where(*active_conditions)
            .order_by(Jobs.created_at.desc(), Jobs.id.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(rows_stmt)
        items: list[CrawlerActiveInventoryItem] = []
        for row in result.mappings():
            status = Status(str(row["job_status"]))
            counters = {
                "pages_crawled": _optional_int(row["pages_crawled"]),
                "files_downloaded": _optional_int(row["files_downloaded"]),
                "pages_failed": _optional_int(row["pages_failed"]),
                "files_failed": _optional_int(row["files_failed"]),
                "pages_source_retained": _optional_int(row["pages_source_retained"]),
                "pages_hash_retained": _optional_int(row["pages_hash_retained"]),
                "files_hash_retained": _optional_int(row["files_hash_retained"]),
                "files_too_large_skipped": _optional_int(
                    row["files_too_large_skipped"]
                ),
            }
            lifecycle_state = derive_crawl_lifecycle_from_counters(
                status=status,
                finished_at=None,
                **counters,
            )
            items.append(
                CrawlerActiveInventoryItem(
                    job_id=row["job_id"],
                    crawl_run_id=row["crawl_run_id"],
                    website_id=row["website_id"],
                    website_name=row["website_name"],
                    space_id=row["space_id"],
                    space_name=row["space_name"],
                    collection_id=row["collection_id"],
                    collection_name=row["collection_name"],
                    user_started_by_id=row["user_started_by_id"],
                    user_started_by_email=row["user_started_by_email"],
                    tenant_id=row["tenant_id"],
                    tenant_display_name=row["tenant_display_name"],
                    status=status,
                    lifecycle_state=lifecycle_state,
                    is_abortable=is_crawl_abortable_target(
                        status=status,
                        has_crawl_run=row["crawl_run_id"] is not None,
                    ),
                    job_created_at=row["job_created_at"],
                    job_updated_at=row["job_updated_at"],
                    crawl_run_created_at=row["crawl_run_created_at"],
                    **counters,
                )
            )

        return CrawlerActiveInventory(
            items=tuple(items),
            total=total,
            limit=limit,
            offset=offset,
        )

    async def recent_failures_for_tenant(
        self,
        *,
        since: datetime,
        until: datetime,
        days: int,
        limit: int,
        offset: int,
        tenant_id: UUID,
        outcome_filter: CrawlOutcomeCode | None = None,
    ) -> CrawlerRecentFailures:
        return await self._recent_terminal_outcomes(
            since=since,
            until=until,
            days=days,
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
            outcome_codes=RECENT_FAILURE_OUTCOME_CODES,
            outcome_filter=outcome_filter,
        )

    async def recent_failures_for_sysadmin(
        self,
        *,
        since: datetime,
        until: datetime,
        days: int,
        limit: int,
        offset: int,
        tenant_id: UUID | None,
        outcome_filter: CrawlOutcomeCode | None = None,
    ) -> CrawlerRecentFailures:
        return await self._recent_terminal_outcomes(
            since=since,
            until=until,
            days=days,
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
            outcome_codes=RECENT_FAILURE_OUTCOME_CODES,
            outcome_filter=outcome_filter,
        )

    async def watchdog_interventions_for_tenant(
        self,
        *,
        since: datetime,
        until: datetime,
        days: int,
        limit: int,
        offset: int,
        tenant_id: UUID,
        outcome_filter: CrawlOutcomeCode | None = None,
    ) -> CrawlerRecentFailures:
        return await self._recent_terminal_outcomes(
            since=since,
            until=until,
            days=days,
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
            outcome_codes=WATCHDOG_INTERVENTION_OUTCOME_CODES,
            outcome_filter=outcome_filter,
        )

    async def watchdog_interventions_for_sysadmin(
        self,
        *,
        since: datetime,
        until: datetime,
        days: int,
        limit: int,
        offset: int,
        tenant_id: UUID | None,
        outcome_filter: CrawlOutcomeCode | None = None,
    ) -> CrawlerRecentFailures:
        return await self._recent_terminal_outcomes(
            since=since,
            until=until,
            days=days,
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
            outcome_codes=WATCHDOG_INTERVENTION_OUTCOME_CODES,
            outcome_filter=outcome_filter,
        )

    async def _recent_terminal_outcomes(
        self,
        *,
        since: datetime,
        until: datetime,
        days: int,
        limit: int,
        offset: int,
        tenant_id: UUID | None,
        outcome_codes: frozenset[CrawlOutcomeCode],
        outcome_filter: CrawlOutcomeCode | None = None,
    ) -> CrawlerRecentFailures:
        if outcome_filter is not None and outcome_filter not in outcome_codes:
            raise ValueError(
                f"outcome_filter {outcome_filter.value!r} is not within the "
                f"allowed outcome set for this query — caller must validate "
                f"against the endpoint's allowlist before reaching the repo."
            )
        applied_outcomes: frozenset[CrawlOutcomeCode] = (
            frozenset({outcome_filter}) if outcome_filter is not None else outcome_codes
        )

        recent_failure_conditions = [
            Jobs.finished_at.is_not(None),
            Jobs.finished_at >= since,
            Jobs.finished_at < until,
            CrawlRunsTable.outcome_code.in_([code.value for code in applied_outcomes]),
        ]
        if tenant_id is not None:
            recent_failure_conditions.append(CrawlRunsTable.tenant_id == tenant_id)

        base_from = sa.join(CrawlRunsTable, Jobs, CrawlRunsTable.job_id == Jobs.id)
        rows_from = sa.outerjoin(
            sa.outerjoin(
                base_from,
                Websites,
                CrawlRunsTable.website_id == Websites.id,
            ),
            Tenants,
            CrawlRunsTable.tenant_id == Tenants.id,
        )
        total_stmt = (
            sa.select(sa.func.count(CrawlRunsTable.id))
            .select_from(base_from)
            .where(*recent_failure_conditions)
        )
        total = int(await self.session.scalar(total_stmt) or 0)

        rows_stmt = (
            sa.select(
                CrawlRunsTable.id.label("crawl_run_id"),
                CrawlRunsTable.job_id.label("job_id"),
                CrawlRunsTable.website_id.label("website_id"),
                Websites.name.label("website_name"),
                CrawlRunsTable.tenant_id.label("tenant_id"),
                Tenants.display_name.label("tenant_display_name"),
                CrawlRunsTable.outcome_code.label("outcome_code"),
                CrawlRunsTable.failure_summary.label("failure_summary"),
                Jobs.finished_at.label("finished_at"),
                CrawlRunsTable.pages_crawled.label("pages_crawled"),
                CrawlRunsTable.files_downloaded.label("files_downloaded"),
                CrawlRunsTable.pages_failed.label("pages_failed"),
                CrawlRunsTable.files_failed.label("files_failed"),
                CrawlRunsTable.pages_source_retained.label("pages_source_retained"),
                CrawlRunsTable.pages_hash_retained.label("pages_hash_retained"),
                CrawlRunsTable.files_hash_retained.label("files_hash_retained"),
                CrawlRunsTable.files_too_large_skipped.label("files_too_large_skipped"),
            )
            .select_from(rows_from)
            .where(*recent_failure_conditions)
            .order_by(Jobs.finished_at.desc(), CrawlRunsTable.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(rows_stmt)

        items: list[CrawlerRecentFailureItem] = []
        for row in result.mappings():
            items.append(
                CrawlerRecentFailureItem(
                    crawl_run_id=row["crawl_run_id"],
                    job_id=row["job_id"],
                    website_id=row["website_id"],
                    website_name=row["website_name"],
                    tenant_id=row["tenant_id"],
                    tenant_display_name=row["tenant_display_name"],
                    outcome_code=parse_crawl_outcome_code_strict(row["outcome_code"]),
                    failure_summary=parse_failure_summary_lenient(
                        row["failure_summary"],
                        on_unknown_key=report_legacy_failure_summary_key_dropped,
                    ),
                    finished_at=row["finished_at"],
                    pages_crawled=_optional_int(row["pages_crawled"]),
                    files_downloaded=_optional_int(row["files_downloaded"]),
                    pages_failed=_optional_int(row["pages_failed"]),
                    files_failed=_optional_int(row["files_failed"]),
                    pages_source_retained=_optional_int(row["pages_source_retained"]),
                    pages_hash_retained=_optional_int(row["pages_hash_retained"]),
                    files_hash_retained=_optional_int(row["files_hash_retained"]),
                    files_too_large_skipped=_optional_int(
                        row["files_too_large_skipped"]
                    ),
                )
            )

        return CrawlerRecentFailures(
            items=tuple(items),
            total=total,
            limit=limit,
            offset=offset,
            days=days,
            since=since,
            until=until,
        )

    async def website_processing_aggregate(
        self,
        *,
        since: datetime,
        until: datetime,
        days: int,
        limit: int,
        offset: int,
        tenant_id: UUID | None,
    ) -> CrawlerWebsiteProcessingAggregate:
        base_conditions = [
            CrawlRunsTable.created_at >= since,
            CrawlRunsTable.created_at < until,
        ]
        if tenant_id is not None:
            base_conditions.append(CrawlRunsTable.tenant_id == tenant_id)

        total_stmt = (
            sa.select(sa.func.count(sa.distinct(CrawlRunsTable.website_id)))
            .select_from(CrawlRunsTable)
            .where(*base_conditions)
        )
        total = int(await self.session.scalar(total_stmt) or 0)

        rows_from = sa.outerjoin(
            sa.outerjoin(
                sa.outerjoin(
                    CrawlRunsTable,
                    Jobs,
                    CrawlRunsTable.job_id == Jobs.id,
                ),
                Websites,
                CrawlRunsTable.website_id == Websites.id,
            ),
            Tenants,
            CrawlRunsTable.tenant_id == Tenants.id,
        )
        pages_crawled = sa.func.coalesce(
            sa.func.sum(CrawlRunsTable.pages_crawled), 0
        ).label("pages_crawled")
        files_downloaded = sa.func.coalesce(
            sa.func.sum(CrawlRunsTable.files_downloaded), 0
        ).label("files_downloaded")
        pages_hash_retained = sa.func.coalesce(
            sa.func.sum(CrawlRunsTable.pages_hash_retained), 0
        ).label("pages_hash_retained")
        files_hash_retained = sa.func.coalesce(
            sa.func.sum(CrawlRunsTable.files_hash_retained), 0
        ).label("files_hash_retained")
        pages_source_retained = sa.func.coalesce(
            sa.func.sum(CrawlRunsTable.pages_source_retained), 0
        ).label("pages_source_retained")
        files_too_large_skipped = sa.func.coalesce(
            sa.func.sum(CrawlRunsTable.files_too_large_skipped), 0
        ).label("files_too_large_skipped")
        pages_failed = sa.func.coalesce(
            sa.func.sum(CrawlRunsTable.pages_failed), 0
        ).label("pages_failed")
        files_failed = sa.func.coalesce(
            sa.func.sum(CrawlRunsTable.files_failed), 0
        ).label("files_failed")
        retained_content_count = (
            pages_hash_retained + files_hash_retained + pages_source_retained
        )
        indexed_content_count = (
            pages_crawled + files_downloaded + retained_content_count
        ).label("indexed_content_count")
        schedule_weight = sa.case(
            *(
                (Websites.update_interval == update_interval.value, weight)
                for update_interval, weight in SCHEDULE_FREQUENCY_WEIGHTS.items()
            ),
            else_=0.0,
        )
        # Algebraically matches the public score formula after aggregation:
        # weight * indexed_count * (1 - retention_rate) == weight * fetched_count.
        cost_pressure_for_ordering = schedule_weight * (
            pages_crawled + files_downloaded
        )
        throughput = pages_crawled + files_downloaded

        rows_stmt = (
            sa.select(
                CrawlRunsTable.website_id.label("website_id"),
                Websites.name.label("website_name"),
                CrawlRunsTable.tenant_id.label("tenant_id"),
                Tenants.display_name.label("tenant_display_name"),
                Websites.update_interval.label("update_interval"),
                sa.func.count(CrawlRunsTable.id).label("total_runs"),
                sa.func.count(CrawlRunsTable.id)
                .filter(Jobs.finished_at.is_not(None))
                .label("terminal_runs"),
                sa.func.count(CrawlRunsTable.id)
                .filter(Jobs.status == Status.FAILED.value)
                .label("failed_runs"),
                pages_crawled,
                files_downloaded,
                pages_hash_retained,
                files_hash_retained,
                pages_source_retained,
                files_too_large_skipped,
                pages_failed,
                files_failed,
                indexed_content_count,
            )
            .select_from(rows_from)
            .where(*base_conditions)
            .group_by(
                CrawlRunsTable.website_id,
                Websites.name,
                CrawlRunsTable.tenant_id,
                Tenants.display_name,
                Websites.update_interval,
            )
            .order_by(
                cost_pressure_for_ordering.desc(),
                throughput.desc(),
                CrawlRunsTable.website_id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(rows_stmt)

        items: list[CrawlerWebsiteProcessingAggregateItem] = []
        for row in result.mappings():
            update_interval = parse_update_interval_for_cost_score(
                row["update_interval"]
            )
            schedule_weight_value = schedule_frequency_weight(update_interval)
            indexed_content_count_value = int(row["indexed_content_count"])
            retained_content_count_value = (
                int(row["pages_hash_retained"])
                + int(row["files_hash_retained"])
                + int(row["pages_source_retained"])
            )
            items.append(
                CrawlerWebsiteProcessingAggregateItem(
                    website_id=row["website_id"],
                    website_name=row["website_name"],
                    tenant_id=row["tenant_id"],
                    tenant_display_name=row["tenant_display_name"],
                    update_interval=update_interval,
                    total_runs=int(row["total_runs"]),
                    terminal_runs=int(row["terminal_runs"]),
                    failed_runs=int(row["failed_runs"]),
                    pages_crawled=int(row["pages_crawled"]),
                    files_downloaded=int(row["files_downloaded"]),
                    pages_hash_retained=int(row["pages_hash_retained"]),
                    files_hash_retained=int(row["files_hash_retained"]),
                    pages_source_retained=int(row["pages_source_retained"]),
                    files_too_large_skipped=int(row["files_too_large_skipped"]),
                    pages_failed=int(row["pages_failed"]),
                    files_failed=int(row["files_failed"]),
                    schedule_frequency_weight=schedule_weight_value,
                    indexed_content_count=indexed_content_count_value,
                    retention_rate=retention_rate(
                        retained_count=retained_content_count_value,
                        indexed_content_count=indexed_content_count_value,
                    ),
                    cost_pressure_score=cost_pressure_score(
                        schedule_weight=schedule_weight_value,
                        indexed_content_count=indexed_content_count_value,
                        retained_count=retained_content_count_value,
                    ),
                )
            )

        return CrawlerWebsiteProcessingAggregate(
            items=tuple(items),
            total=total,
            limit=limit,
            offset=offset,
            days=days,
            since=since,
            until=until,
            tenant_id=tenant_id,
        )

    async def website_processing_aggregate_for_tenant(
        self,
        *,
        since: datetime,
        until: datetime,
        days: int,
        limit: int,
        offset: int,
        tenant_id: UUID,
    ) -> CrawlerWebsiteProcessingAggregate:
        return await self.website_processing_aggregate(
            since=since,
            until=until,
            days=days,
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
        )

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
