from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import aliased, selectinload
from sqlalchemy.sql.elements import ColumnElement

from intric.audit.infrastructure.audit_log_repo_impl import escape_like
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.job_table import Jobs
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.database.tables.websites_table import CrawlRuns as CrawlRunsTable
from intric.database.tables.websites_table import Websites
from intric.embedding_models.domain.embedding_batch import EmbeddingUsageSource
from intric.jobs.job_models import Task
from intric.main.exceptions import NotFoundException
from intric.main.models import Status
from intric.websites.domain.crawl_abort import is_crawl_abortable_target
from intric.websites.domain.crawl_lifecycle import (
    CrawlLifecycle,
    derive_crawl_lifecycle_from_counters,
    lifecycle_predicate_for_active_query,
)
from intric.websites.domain.crawl_outcome import (
    CRAWL_OUTCOME_CATEGORY_CODES,
    CrawlOutcomeCategory,
    CrawlOutcomeCode,
    crawl_outcome_category,
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
from intric.websites.domain.crawler_failure_clusters import (
    CrawlerFailureClusterItem,
    CrawlerFailureClusters,
    CrawlerFailureClusterSource,
)
from intric.websites.domain.crawler_recent_failures import (
    RECENT_FAILURE_OUTCOME_CODES,
    WATCHDOG_INTERVENTION_OUTCOME_CODES,
    CrawlerRecentFailureItem,
    CrawlerRecentFailures,
)
from intric.websites.domain.crawler_website_processing_aggregate import (
    LOW_RETENTION_THRESHOLD,
    SCHEDULE_FREQUENCY_WEIGHTS,
    SOURCE_SKIP_DRIFT_MIN_INDEXED,
    CrawlerWebsiteProcessingAggregate,
    CrawlerWebsiteProcessingAggregateItem,
    CrawlerWebsiteProcessingAggregateSummary,
    CrawlerWebsiteProcessingSort,
    CrawlerWebsiteProcessingSpaceRollupItem,
    cost_pressure_score,
    parse_update_interval_for_cost_score,
    retention_rate,
    schedule_frequency_weight,
)
from intric.websites.domain.website import UpdateInterval

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
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    raise TypeError(f"Expected integer crawl counter, got {type(value).__name__}")


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    raise TypeError(f"Expected decimal crawl counter, got {type(value).__name__}")


def _optional_embedding_usage_source(value: object) -> EmbeddingUsageSource | None:
    if value is None:
        return None
    if value == "provider_reported":
        return "provider_reported"
    if value == "missing":
        return "missing"
    raise ValueError(f"Unexpected embedding usage source {value!r}")


def _failure_cluster_outcome_codes(
    *,
    source: CrawlerFailureClusterSource,
    outcome_category: CrawlOutcomeCategory | None,
) -> frozenset[CrawlOutcomeCode]:
    source_codes = (
        WATCHDOG_INTERVENTION_OUTCOME_CODES
        if source is CrawlerFailureClusterSource.WATCHDOG_ONLY
        else RECENT_FAILURE_OUTCOME_CODES
    )
    if outcome_category is None:
        return source_codes
    category_codes = CRAWL_OUTCOME_CATEGORY_CODES[outcome_category]
    return frozenset(code for code in source_codes if code in category_codes)


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
                embedding_model_id=crawl_run.embedding_model_id,
                embedding_model_name_snapshot=(crawl_run.embedding_model_name_snapshot),
                embedding_model_litellm_name_snapshot=(
                    crawl_run.embedding_model_litellm_name_snapshot
                ),
                embedding_model_provider_snapshot=(
                    crawl_run.embedding_model_provider_snapshot
                ),
                embedding_input_cost_per_token_snapshot=(
                    crawl_run.embedding_input_cost_per_token_snapshot
                ),
                embedding_input_tokens=crawl_run.embedding_input_tokens,
                embedding_usage_source=crawl_run.embedding_usage_source,
                embedding_total_cost_usd=crawl_run.embedding_total_cost_usd,
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

    async def record_indexed_embedding_usage(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        token_delta: int,
        cost_delta: Decimal | None,
        usage_source: EmbeddingUsageSource,
    ) -> None:
        values: dict[str, object] = {
            "embedding_usage_source": sa.case(
                (
                    CrawlRunsTable.embedding_usage_source == "provider_reported",
                    "provider_reported",
                ),
                else_=usage_source,
            )
        }
        if token_delta > 0:
            values["embedding_input_tokens"] = (
                sa.func.coalesce(CrawlRunsTable.embedding_input_tokens, 0) + token_delta
            )
        if cost_delta is not None:
            values["embedding_total_cost_usd"] = (
                sa.func.coalesce(CrawlRunsTable.embedding_total_cost_usd, 0)
                + cost_delta
            )

        stmt = (
            sa.update(CrawlRunsTable)
            .where(CrawlRunsTable.id == run_id)
            .where(CrawlRunsTable.tenant_id == tenant_id)
            .values(**values)
        )
        await self.session.execute(stmt)

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
        lifecycle_filter: CrawlLifecycle | None = None,
        website_id: UUID | None = None,
    ) -> CrawlerActiveInventory:
        return await self._active_inventory(
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
            lifecycle_filter=lifecycle_filter,
            website_id=website_id,
        )

    async def active_inventory_for_sysadmin(
        self,
        *,
        limit: int,
        offset: int,
        tenant_id: UUID | None,
        lifecycle_filter: CrawlLifecycle | None = None,
        website_id: UUID | None = None,
    ) -> CrawlerActiveInventory:
        return await self._active_inventory(
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
            lifecycle_filter=lifecycle_filter,
            website_id=website_id,
        )

    async def _active_inventory(
        self,
        *,
        limit: int,
        offset: int,
        tenant_id: UUID | None,
        lifecycle_filter: CrawlLifecycle | None = None,
        website_id: UUID | None = None,
    ) -> CrawlerActiveInventory:
        active_conditions = [
            Jobs.task == Task.CRAWL.value,
            Jobs.status.in_([Status.QUEUED.value, Status.IN_PROGRESS.value]),
            # Defensive: a Jobs row with status=IN_PROGRESS but finished_at!=NULL
            # is an inconsistent terminal state — the worker should have flipped
            # status before setting finished_at. Excluding such rows here keeps
            # `derive_crawl_lifecycle_from_counters(finished_at=row.finished_at)`
            # from disagreeing with the SQL filter at the row level (the canonical
            # classifier treats finished_at!=NULL as TERMINAL regardless of
            # status, so any row that surfaces here with finished_at set would
            # be classified TERMINAL in Python but pass the active-query SQL).
            Jobs.finished_at.is_(None),
        ]
        if lifecycle_filter is not None:
            # The SQL classifier mirrors `derive_crawl_lifecycle_from_counters`
            # so the filter agrees with the row-rendered lifecycle_state.
            active_conditions.append(
                lifecycle_predicate_for_active_query(
                    job_status_column=Jobs.status,
                    pages_crawled_column=CrawlRunsTable.pages_crawled,
                    files_downloaded_column=CrawlRunsTable.files_downloaded,
                    pages_failed_column=CrawlRunsTable.pages_failed,
                    files_failed_column=CrawlRunsTable.files_failed,
                    pages_source_retained_column=CrawlRunsTable.pages_source_retained,
                    pages_hash_retained_column=CrawlRunsTable.pages_hash_retained,
                    files_hash_retained_column=CrawlRunsTable.files_hash_retained,
                    files_too_large_skipped_column=(
                        CrawlRunsTable.files_too_large_skipped
                    ),
                    lifecycle=lifecycle_filter,
                )
            )
        if tenant_id is not None:
            # Orphan queued jobs have no crawl run yet; filtering on the
            # outer-joined crawl run tenant column intentionally excludes them.
            active_conditions.append(CrawlRunsTable.tenant_id == tenant_id)
        if website_id is not None:
            # Narrows the result to one website. Combined with the
            # tenant predicate above, this is the authoritative source
            # for "is there an active job for this website?" — the
            # frontend uses it to gate the drawer's Abort affordance
            # without relying on the loaded inventory page.
            active_conditions.append(CrawlRunsTable.website_id == website_id)

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
                # Select the real finished_at column so the renderer can pass
                # it through to `derive_crawl_lifecycle_from_counters` instead
                # of hardcoding `finished_at=None`. The active-conditions WHERE
                # clause already guards `Jobs.finished_at IS NULL` so this
                # column is always NULL in practice — but routing the actual
                # value through removes a load-bearing assumption that a
                # future maintainer would otherwise have to remember.
                Jobs.finished_at.label("job_finished_at"),
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
                # `update_interval` is read from the already-joined
                # Websites row (the same LEFT JOIN that resolves the
                # website_name + space attribution) so the admin
                # active-inventory row can show + change the schedule
                # without an extra round trip. Nullable when the
                # Websites row didn't join (orphan queued job).
                Websites.update_interval.label("update_interval"),
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
                CrawlRunsTable.embedding_model_name_snapshot.label(
                    "embedding_model_name_snapshot"
                ),
                CrawlRunsTable.embedding_model_litellm_name_snapshot.label(
                    "embedding_model_litellm_name_snapshot"
                ),
                CrawlRunsTable.embedding_model_provider_snapshot.label(
                    "embedding_model_provider_snapshot"
                ),
                CrawlRunsTable.embedding_input_tokens.label("embedding_input_tokens"),
                CrawlRunsTable.embedding_total_cost_usd.label(
                    "embedding_total_cost_usd"
                ),
                CrawlRunsTable.embedding_usage_source.label("embedding_usage_source"),
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
                finished_at=row["job_finished_at"],
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
                    update_interval=(
                        UpdateInterval(str(row["update_interval"]))
                        if row["update_interval"] is not None
                        else None
                    ),
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
        website_id: UUID | None = None,
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
            website_id=website_id,
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
        website_id: UUID | None = None,
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
            website_id=website_id,
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

    async def failure_clusters_for_tenant(
        self,
        *,
        since: datetime,
        until: datetime,
        days: int,
        limit: int,
        offset: int,
        tenant_id: UUID,
        source: CrawlerFailureClusterSource = CrawlerFailureClusterSource.ALL,
        outcome_category: CrawlOutcomeCategory | None = None,
    ) -> CrawlerFailureClusters:
        applied_outcomes = _failure_cluster_outcome_codes(
            source=source,
            outcome_category=outcome_category,
        )
        if not applied_outcomes:
            return CrawlerFailureClusters(
                items=(),
                total=0,
                limit=limit,
                offset=offset,
                days=days,
                since=since,
                until=until,
                source=source,
                outcome_category=outcome_category,
            )

        latest_crawl_run = aliased(CrawlRunsTable)
        latest_job = aliased(Jobs)
        latest_conditions = [
            latest_job.finished_at.is_not(None),
            latest_job.finished_at >= since,
            latest_job.finished_at < until,
            latest_crawl_run.tenant_id == tenant_id,
            latest_crawl_run.outcome_code.in_(
                [code.value for code in applied_outcomes]
            ),
        ]
        latest_ranked = (
            sa.select(
                latest_crawl_run.website_id.label("website_id"),
                latest_crawl_run.outcome_code.label("outcome_code"),
                latest_crawl_run.id.label("sample_crawl_run_id"),
                sa.func.row_number()
                .over(
                    partition_by=(
                        latest_crawl_run.website_id,
                        latest_crawl_run.outcome_code,
                    ),
                    order_by=(
                        latest_job.finished_at.desc(),
                        latest_crawl_run.id.desc(),
                    ),
                )
                .label("cluster_rank"),
            )
            .select_from(
                sa.join(
                    latest_crawl_run,
                    latest_job,
                    latest_crawl_run.job_id == latest_job.id,
                )
            )
            .where(*latest_conditions)
            .subquery()
        )

        failure_conditions = [
            Jobs.finished_at.is_not(None),
            Jobs.finished_at >= since,
            Jobs.finished_at < until,
            CrawlRunsTable.tenant_id == tenant_id,
            CrawlRunsTable.outcome_code.in_([code.value for code in applied_outcomes]),
        ]

        base_from = sa.join(
            sa.join(CrawlRunsTable, Jobs, CrawlRunsTable.job_id == Jobs.id),
            Websites,
            sa.and_(
                CrawlRunsTable.website_id == Websites.id,
                Websites.tenant_id == CrawlRunsTable.tenant_id,
            ),
        )
        rows_from = sa.outerjoin(
            base_from, Tenants, CrawlRunsTable.tenant_id == Tenants.id
        )
        rows_from = sa.outerjoin(
            rows_from,
            Spaces,
            sa.and_(
                Websites.space_id == Spaces.id,
                Spaces.tenant_id == CrawlRunsTable.tenant_id,
            ),
        )
        rows_from = sa.outerjoin(
            rows_from,
            Users,
            sa.and_(
                Websites.user_id == Users.id,
                Users.tenant_id == CrawlRunsTable.tenant_id,
            ),
        )
        rows_from = sa.outerjoin(
            rows_from,
            latest_ranked,
            sa.and_(
                latest_ranked.c.website_id == CrawlRunsTable.website_id,
                latest_ranked.c.outcome_code == CrawlRunsTable.outcome_code,
                latest_ranked.c.cluster_rank == 1,
            ),
        )

        watchdog_occurrence = sa.case(
            (
                CrawlRunsTable.outcome_code.in_(
                    [code.value for code in WATCHDOG_INTERVENTION_OUTCOME_CODES]
                ),
                1,
            ),
            else_=0,
        )
        grouped_stmt = (
            sa.select(
                CrawlRunsTable.website_id.label("website_id"),
                Websites.url.label("website_url"),
                Websites.name.label("website_name"),
                CrawlRunsTable.tenant_id.label("tenant_id"),
                Tenants.display_name.label("tenant_display_name"),
                Spaces.id.label("space_id"),
                Spaces.name.label("space_name"),
                Users.id.label("owner_user_id"),
                Users.email.label("owner_email"),
                CrawlRunsTable.outcome_code.label("outcome_code"),
                sa.func.count(CrawlRunsTable.id).label("occurrences"),
                sa.func.coalesce(sa.func.sum(watchdog_occurrence), 0).label(
                    "watchdog_occurrences"
                ),
                sa.func.min(Jobs.finished_at).label("first_failed_at"),
                sa.func.max(Jobs.finished_at).label("latest_failed_at"),
                latest_ranked.c.sample_crawl_run_id.label("sample_crawl_run_id"),
                sa.func.coalesce(sa.func.sum(CrawlRunsTable.pages_crawled), 0).label(
                    "pages_crawled"
                ),
                sa.func.coalesce(sa.func.sum(CrawlRunsTable.files_downloaded), 0).label(
                    "files_downloaded"
                ),
                sa.func.coalesce(sa.func.sum(CrawlRunsTable.pages_failed), 0).label(
                    "pages_failed"
                ),
                sa.func.coalesce(sa.func.sum(CrawlRunsTable.files_failed), 0).label(
                    "files_failed"
                ),
            )
            .select_from(rows_from)
            .where(*failure_conditions)
            .group_by(
                CrawlRunsTable.website_id,
                Websites.url,
                Websites.name,
                CrawlRunsTable.tenant_id,
                Tenants.display_name,
                Spaces.id,
                Spaces.name,
                Users.id,
                Users.email,
                CrawlRunsTable.outcome_code,
                latest_ranked.c.sample_crawl_run_id,
            )
        )
        grouped = grouped_stmt.subquery()
        total = int(
            await self.session.scalar(sa.select(sa.func.count()).select_from(grouped))
            or 0
        )

        rows_stmt = (
            sa.select(grouped)
            .order_by(
                grouped.c.occurrences.desc(),
                grouped.c.latest_failed_at.desc(),
                grouped.c.website_id.asc(),
                grouped.c.outcome_code.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(rows_stmt)

        items: list[CrawlerFailureClusterItem] = []
        for row in result.mappings():
            sample_crawl_run_id = row["sample_crawl_run_id"]
            if sample_crawl_run_id is None:
                raise RuntimeError("Failure cluster has no representative crawl run")
            outcome_code = parse_crawl_outcome_code_strict(row["outcome_code"])
            items.append(
                CrawlerFailureClusterItem(
                    website_id=row["website_id"],
                    website_url=str(row["website_url"]),
                    website_name=row["website_name"],
                    tenant_id=row["tenant_id"],
                    tenant_display_name=row["tenant_display_name"],
                    space_id=row["space_id"],
                    space_name=row["space_name"],
                    owner_user_id=row["owner_user_id"],
                    owner_email=row["owner_email"],
                    outcome_code=outcome_code,
                    outcome_category=crawl_outcome_category(outcome_code),
                    occurrences=int(row["occurrences"]),
                    watchdog_occurrences=int(row["watchdog_occurrences"]),
                    first_failed_at=row["first_failed_at"],
                    latest_failed_at=row["latest_failed_at"],
                    sample_crawl_run_id=sample_crawl_run_id,
                    pages_crawled=int(row["pages_crawled"]),
                    files_downloaded=int(row["files_downloaded"]),
                    pages_failed=int(row["pages_failed"]),
                    files_failed=int(row["files_failed"]),
                )
            )

        return CrawlerFailureClusters(
            items=tuple(items),
            total=total,
            limit=limit,
            offset=offset,
            days=days,
            since=since,
            until=until,
            source=source,
            outcome_category=outcome_category,
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
        website_id: UUID | None = None,
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
        if website_id is not None:
            # Tenant-scoped narrowing to one website. The
            # `crawl_runs.website_id` column carries the FK; combined with
            # the existing tenant predicate, an admin can only see their
            # own tenant's runs for this website even if a UUID guess
            # collides with another tenant's row (FK is per-tenant via
            # the cascading delete tree).
            recent_failure_conditions.append(CrawlRunsTable.website_id == website_id)

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
                CrawlRunsTable.embedding_model_name_snapshot.label(
                    "embedding_model_name_snapshot"
                ),
                CrawlRunsTable.embedding_model_litellm_name_snapshot.label(
                    "embedding_model_litellm_name_snapshot"
                ),
                CrawlRunsTable.embedding_model_provider_snapshot.label(
                    "embedding_model_provider_snapshot"
                ),
                CrawlRunsTable.embedding_input_tokens.label("embedding_input_tokens"),
                CrawlRunsTable.embedding_total_cost_usd.label(
                    "embedding_total_cost_usd"
                ),
                CrawlRunsTable.embedding_usage_source.label("embedding_usage_source"),
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
                    embedding_model_name_snapshot=row["embedding_model_name_snapshot"],
                    embedding_model_litellm_name_snapshot=row[
                        "embedding_model_litellm_name_snapshot"
                    ],
                    embedding_model_provider_snapshot=row[
                        "embedding_model_provider_snapshot"
                    ],
                    embedding_input_tokens=_optional_int(row["embedding_input_tokens"]),
                    embedding_total_cost_usd=_optional_decimal(
                        row["embedding_total_cost_usd"]
                    ),
                    embedding_usage_source=_optional_embedding_usage_source(
                        row["embedding_usage_source"]
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
        website_id: UUID | None = None,
        space_id: UUID | None = None,
        sort: CrawlerWebsiteProcessingSort = (
            CrawlerWebsiteProcessingSort.LOAD_PRESSURE
        ),
        failures_only: bool = False,
        low_retention_only: bool = False,
        source_skip_drift_only: bool = False,
        search: str | None = None,
    ) -> CrawlerWebsiteProcessingAggregate:
        base_conditions = [
            CrawlRunsTable.created_at >= since,
            CrawlRunsTable.created_at < until,
        ]
        if tenant_id is not None:
            base_conditions.append(CrawlRunsTable.tenant_id == tenant_id)
        if website_id is not None:
            # Narrows the aggregate to one website. The Webbplatser
            # detail Dialog uses this to render real per-website
            # history without re-fetching the full tenant-wide top-N.
            base_conditions.append(CrawlRunsTable.website_id == website_id)
        if space_id is not None:
            base_conditions.append(Websites.space_id == space_id)

        # ILIKE OR-clause on Websites.name / url / owner email. escape_like treats
        # user-typed `%` and `_` as literal characters so a search for
        # "100%" does not silently widen the result set. pg_trgm GIN
        # indexes on websites.url + websites.name keep the website arms indexed.
        has_search = bool(search and search.strip())
        if has_search:
            assert search is not None
            safe = escape_like(search.strip())
            pattern = f"%{safe}%"
            base_conditions.append(
                sa.or_(
                    Websites.url.ilike(pattern, escape="\\"),
                    Websites.name.ilike(pattern, escape="\\"),
                    Users.email.ilike(pattern, escape="\\"),
                )
            )

        latest_crawl_run = aliased(CrawlRunsTable)
        latest_conditions = [
            latest_crawl_run.created_at >= since,
            latest_crawl_run.created_at < until,
        ]
        if tenant_id is not None:
            latest_conditions.append(latest_crawl_run.tenant_id == tenant_id)
        if website_id is not None:
            latest_conditions.append(latest_crawl_run.website_id == website_id)
        latest_run_subquery = (
            sa.select(
                latest_crawl_run.website_id.label("website_id"),
                latest_crawl_run.embedding_model_name_snapshot.label(
                    "latest_embedding_model_name_snapshot"
                ),
                latest_crawl_run.embedding_model_litellm_name_snapshot.label(
                    "latest_embedding_model_litellm_name_snapshot"
                ),
                latest_crawl_run.embedding_model_provider_snapshot.label(
                    "latest_embedding_model_provider_snapshot"
                ),
                latest_crawl_run.embedding_input_tokens.label(
                    "latest_embedding_input_tokens"
                ),
                latest_crawl_run.embedding_total_cost_usd.label(
                    "latest_embedding_total_cost_usd"
                ),
                latest_crawl_run.embedding_usage_source.label(
                    "latest_embedding_usage_source"
                ),
                sa.func.row_number()
                .over(
                    partition_by=latest_crawl_run.website_id,
                    order_by=(
                        latest_crawl_run.created_at.desc(),
                        latest_crawl_run.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(*latest_conditions)
            .subquery()
        )

        rows_from = sa.outerjoin(
            sa.outerjoin(
                sa.outerjoin(
                    sa.outerjoin(
                        sa.outerjoin(
                            sa.outerjoin(
                                sa.outerjoin(
                                    CrawlRunsTable,
                                    Jobs,
                                    CrawlRunsTable.job_id == Jobs.id,
                                ),
                                Websites,
                                CrawlRunsTable.website_id == Websites.id,
                            ),
                            Users,
                            sa.and_(
                                Users.id == Websites.user_id,
                                Users.tenant_id == Websites.tenant_id,
                            ),
                        ),
                        Spaces,
                        sa.and_(
                            Spaces.id == Websites.space_id,
                            Spaces.tenant_id == Websites.tenant_id,
                        ),
                    ),
                    CollectionsTable,
                    sa.and_(
                        CollectionsTable.id == Websites.group_id,
                        CollectionsTable.tenant_id == Websites.tenant_id,
                    ),
                ),
                Tenants,
                CrawlRunsTable.tenant_id == Tenants.id,
            ),
            latest_run_subquery,
            sa.and_(
                latest_run_subquery.c.website_id == CrawlRunsTable.website_id,
                latest_run_subquery.c.row_number == 1,
            ),
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
        embedding_input_tokens = sa.func.sum(
            CrawlRunsTable.embedding_input_tokens
        ).label("embedding_input_tokens")
        embedding_total_cost_usd = sa.func.sum(
            CrawlRunsTable.embedding_total_cost_usd
        ).label("embedding_total_cost_usd")
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
        latest_run_at = sa.func.max(CrawlRunsTable.created_at).label("latest_run_at")
        total_runs_count = sa.func.count(CrawlRunsTable.id).label("total_runs")
        terminal_runs_count = (
            sa.func.count(CrawlRunsTable.id)
            .filter(Jobs.finished_at.is_not(None))
            .label("terminal_runs")
        )
        failed_runs_count = (
            sa.func.count(CrawlRunsTable.id)
            .filter(Jobs.status == Status.FAILED.value)
            .label("failed_runs")
        )
        # Re-build the aggregated retained / fetched expressions without
        # the .label() wrappers; bare arithmetic on labelled columns
        # would push the alias into the HAVING clause and confuse the
        # SQL generator. The values are identical to the labelled ones
        # because SUM(coalesce(...)) is deterministic.
        retained_expr = (
            sa.func.coalesce(sa.func.sum(CrawlRunsTable.pages_hash_retained), 0)
            + sa.func.coalesce(sa.func.sum(CrawlRunsTable.files_hash_retained), 0)
            + sa.func.coalesce(sa.func.sum(CrawlRunsTable.pages_source_retained), 0)
        )
        fetched_expr = sa.func.coalesce(
            sa.func.sum(CrawlRunsTable.pages_crawled), 0
        ) + sa.func.coalesce(sa.func.sum(CrawlRunsTable.files_downloaded), 0)
        indexed_expr = retained_expr + fetched_expr

        having_clauses: list[ColumnElement[bool]] = []
        if failures_only:
            # A row has failures when either the run-level failure
            # counter is non-zero, or per-item page/file failures were
            # recorded. The two signals diverge in practice: a watchdog
            # timeout aborts a run without emitting per-page errors, and
            # vice versa for partial fetch failures inside a terminal-
            # OK run. Operators want both.
            having_clauses.append(
                sa.or_(
                    sa.func.count(CrawlRunsTable.id).filter(
                        Jobs.status == Status.FAILED.value
                    )
                    > 0,
                    sa.func.coalesce(sa.func.sum(CrawlRunsTable.pages_failed), 0) > 0,
                    sa.func.coalesce(sa.func.sum(CrawlRunsTable.files_failed), 0) > 0,
                )
            )
        if low_retention_only:
            # retention_rate < LOW_RETENTION_THRESHOLD rewritten in
            # multiplied form to avoid a division in HAVING:
            #   retained / indexed < threshold
            # ⇔ retained < threshold * indexed (when indexed > 0).
            having_clauses.append(
                sa.and_(
                    indexed_expr > 0,
                    retained_expr < (LOW_RETENTION_THRESHOLD * indexed_expr),
                )
            )
        if source_skip_drift_only:
            # Source-skip drift: enough indexed work to call the signal
            # meaningful AND zero source-skip retentions. Mirrors the
            # frontend `isCrawlerWebsiteProcessingSourceSkipDrift` flag.
            having_clauses.append(
                sa.and_(
                    indexed_expr >= SOURCE_SKIP_DRIFT_MIN_INDEXED,
                    sa.func.coalesce(
                        sa.func.sum(CrawlRunsTable.pages_source_retained), 0
                    )
                    == 0,
                )
            )

        # The aggregated SELECT before ORDER BY / LIMIT / OFFSET. Both
        # the rows_stmt and total_stmt derive from this so the
        # `total` and the visible page always reference the same
        # filtered set.
        aggregated_stmt = (
            sa.select(
                CrawlRunsTable.website_id.label("website_id"),
                Websites.name.label("website_name"),
                Websites.url.label("website_url"),
                CrawlRunsTable.tenant_id.label("tenant_id"),
                Tenants.display_name.label("tenant_display_name"),
                Websites.space_id.label("space_id"),
                Spaces.name.label("space_name"),
                Websites.group_id.label("collection_id"),
                CollectionsTable.name.label("collection_name"),
                Websites.user_id.label("owner_user_id"),
                Users.email.label("owner_email"),
                Websites.update_interval.label("update_interval"),
                sa.func.coalesce(Websites.size, 0).label("indexed_size_bytes"),
                total_runs_count,
                terminal_runs_count,
                failed_runs_count,
                pages_crawled,
                files_downloaded,
                pages_hash_retained,
                files_hash_retained,
                pages_source_retained,
                files_too_large_skipped,
                pages_failed,
                files_failed,
                embedding_input_tokens,
                embedding_total_cost_usd,
                latest_run_subquery.c.latest_embedding_model_name_snapshot,
                latest_run_subquery.c.latest_embedding_model_litellm_name_snapshot,
                latest_run_subquery.c.latest_embedding_model_provider_snapshot,
                latest_run_subquery.c.latest_embedding_input_tokens,
                latest_run_subquery.c.latest_embedding_total_cost_usd,
                latest_run_subquery.c.latest_embedding_usage_source,
                indexed_content_count,
                cost_pressure_for_ordering.label("cost_pressure_score_for_ordering"),
                latest_run_at,
            )
            .select_from(rows_from)
            .where(*base_conditions)
            .group_by(
                CrawlRunsTable.website_id,
                Websites.name,
                Websites.url,
                CrawlRunsTable.tenant_id,
                Tenants.display_name,
                Websites.space_id,
                Spaces.name,
                Websites.group_id,
                CollectionsTable.name,
                Websites.user_id,
                Users.email,
                Websites.update_interval,
                Websites.size,
                latest_run_subquery.c.latest_embedding_model_name_snapshot,
                latest_run_subquery.c.latest_embedding_model_litellm_name_snapshot,
                latest_run_subquery.c.latest_embedding_model_provider_snapshot,
                latest_run_subquery.c.latest_embedding_input_tokens,
                latest_run_subquery.c.latest_embedding_total_cost_usd,
                latest_run_subquery.c.latest_embedding_usage_source,
            )
        )
        if having_clauses:
            aggregated_stmt = aggregated_stmt.having(*having_clauses)

        aggregate_scope = aggregated_stmt.subquery()
        scope_retained_count = (
            aggregate_scope.c.pages_hash_retained
            + aggregate_scope.c.files_hash_retained
            + aggregate_scope.c.pages_source_retained
        )
        scope_failed_item_count = (
            aggregate_scope.c.pages_failed + aggregate_scope.c.files_failed
        )
        scope_low_retention = sa.and_(
            aggregate_scope.c.indexed_content_count > 0,
            scope_retained_count
            < (LOW_RETENTION_THRESHOLD * aggregate_scope.c.indexed_content_count),
        )
        scope_source_skip_drift = sa.and_(
            aggregate_scope.c.indexed_content_count >= SOURCE_SKIP_DRIFT_MIN_INDEXED,
            aggregate_scope.c.pages_source_retained == 0,
        )
        scope_requires_action = sa.case(
            (
                sa.or_(
                    aggregate_scope.c.failed_runs > 0,
                    scope_failed_item_count > 0,
                    aggregate_scope.c.files_too_large_skipped > 0,
                    scope_low_retention,
                    scope_source_skip_drift,
                ),
                1,
            ),
            else_=0,
        )
        summary_stmt = sa.select(
            sa.func.count().label("website_count"),
            sa.func.coalesce(sa.func.sum(aggregate_scope.c.total_runs), 0).label(
                "total_runs"
            ),
            sa.func.coalesce(sa.func.sum(aggregate_scope.c.terminal_runs), 0).label(
                "terminal_runs"
            ),
            sa.func.coalesce(sa.func.sum(aggregate_scope.c.failed_runs), 0).label(
                "failed_runs"
            ),
            sa.func.coalesce(sa.func.sum(aggregate_scope.c.pages_crawled), 0).label(
                "pages_crawled"
            ),
            sa.func.coalesce(sa.func.sum(aggregate_scope.c.files_downloaded), 0).label(
                "files_downloaded"
            ),
            sa.func.coalesce(sa.func.sum(scope_retained_count), 0).label(
                "retained_content_count"
            ),
            sa.func.coalesce(
                sa.func.sum(aggregate_scope.c.files_too_large_skipped), 0
            ).label("files_too_large_skipped"),
            sa.func.coalesce(sa.func.sum(scope_failed_item_count), 0).label(
                "failed_item_count"
            ),
            sa.func.coalesce(
                sa.func.sum(aggregate_scope.c.indexed_size_bytes), 0
            ).label("indexed_size_bytes"),
            sa.func.sum(aggregate_scope.c.embedding_input_tokens).label(
                "embedding_input_tokens"
            ),
            sa.func.sum(aggregate_scope.c.embedding_total_cost_usd).label(
                "embedding_total_cost_usd"
            ),
            sa.func.coalesce(sa.func.sum(scope_requires_action), 0).label(
                "action_required_count"
            ),
        ).select_from(aggregate_scope)
        summary_row = (await self.session.execute(summary_stmt)).mappings().one()
        summary = CrawlerWebsiteProcessingAggregateSummary(
            website_count=int(summary_row["website_count"]),
            total_runs=int(summary_row["total_runs"]),
            terminal_runs=int(summary_row["terminal_runs"]),
            failed_runs=int(summary_row["failed_runs"]),
            pages_crawled=int(summary_row["pages_crawled"]),
            files_downloaded=int(summary_row["files_downloaded"]),
            retained_content_count=int(summary_row["retained_content_count"]),
            files_too_large_skipped=int(summary_row["files_too_large_skipped"]),
            failed_item_count=int(summary_row["failed_item_count"]),
            indexed_size_bytes=int(summary_row["indexed_size_bytes"]),
            embedding_input_tokens=_optional_int(summary_row["embedding_input_tokens"]),
            embedding_total_cost_usd=_optional_decimal(
                summary_row["embedding_total_cost_usd"]
            ),
            action_required_count=int(summary_row["action_required_count"]),
        )

        space_retained_count = sa.func.coalesce(sa.func.sum(scope_retained_count), 0)
        space_indexed_content_count = sa.func.coalesce(
            sa.func.sum(aggregate_scope.c.indexed_content_count), 0
        )
        space_failed_item_count = sa.func.coalesce(
            sa.func.sum(scope_failed_item_count), 0
        )
        space_latest_run_at = sa.func.max(aggregate_scope.c.latest_run_at)
        space_embedding_tokens = sa.func.sum(aggregate_scope.c.embedding_input_tokens)
        space_indexed_size = sa.func.coalesce(
            sa.func.sum(aggregate_scope.c.indexed_size_bytes), 0
        )
        space_total_runs = sa.func.coalesce(
            sa.func.sum(aggregate_scope.c.total_runs), 0
        )
        if sort is CrawlerWebsiteProcessingSort.FAILURES:
            space_rollup_order_by = (
                (
                    sa.func.coalesce(sa.func.sum(aggregate_scope.c.failed_runs), 0)
                    + space_failed_item_count
                ).desc(),
                space_latest_run_at.desc(),
                aggregate_scope.c.space_name.asc().nulls_last(),
            )
        elif sort is CrawlerWebsiteProcessingSort.RUNS:
            space_rollup_order_by = (
                space_total_runs.desc(),
                space_latest_run_at.desc(),
                aggregate_scope.c.space_name.asc().nulls_last(),
            )
        elif sort is CrawlerWebsiteProcessingSort.TOKENS:
            space_rollup_order_by = (
                sa.func.coalesce(space_embedding_tokens, 0).desc(),
                space_latest_run_at.desc(),
                aggregate_scope.c.space_name.asc().nulls_last(),
            )
        elif sort is CrawlerWebsiteProcessingSort.INDEXED_SIZE:
            space_rollup_order_by = (
                space_indexed_size.desc(),
                space_latest_run_at.desc(),
                aggregate_scope.c.space_name.asc().nulls_last(),
            )
        elif sort is CrawlerWebsiteProcessingSort.LOW_RETENTION:
            space_retention_for_ordering = sa.case(
                (
                    space_indexed_content_count > 0,
                    space_retained_count
                    / sa.func.nullif(space_indexed_content_count, 0),
                ),
                else_=1.0,
            )
            space_rollup_order_by = (
                space_retention_for_ordering.asc(),
                (
                    sa.func.coalesce(sa.func.sum(aggregate_scope.c.pages_crawled), 0)
                    + sa.func.coalesce(
                        sa.func.sum(aggregate_scope.c.files_downloaded), 0
                    )
                ).desc(),
                aggregate_scope.c.space_name.asc().nulls_last(),
            )
        elif sort is CrawlerWebsiteProcessingSort.RECENT:
            space_rollup_order_by = (
                space_latest_run_at.desc(),
                aggregate_scope.c.space_name.asc().nulls_last(),
            )
        else:
            space_rollup_order_by = (
                sa.func.coalesce(
                    sa.func.sum(aggregate_scope.c.cost_pressure_score_for_ordering), 0
                ).desc(),
                (
                    sa.func.coalesce(sa.func.sum(aggregate_scope.c.pages_crawled), 0)
                    + sa.func.coalesce(
                        sa.func.sum(aggregate_scope.c.files_downloaded), 0
                    )
                ).desc(),
                aggregate_scope.c.space_name.asc().nulls_last(),
            )

        space_rollup_stmt = (
            sa.select(
                aggregate_scope.c.space_id,
                aggregate_scope.c.space_name,
                sa.func.count().label("website_count"),
                space_total_runs.label("total_runs"),
                sa.func.coalesce(sa.func.sum(aggregate_scope.c.pages_crawled), 0).label(
                    "pages_crawled"
                ),
                sa.func.coalesce(
                    sa.func.sum(aggregate_scope.c.files_downloaded), 0
                ).label("files_downloaded"),
                space_indexed_size.label("indexed_size_bytes"),
                space_embedding_tokens.label("embedding_input_tokens"),
                sa.func.sum(aggregate_scope.c.embedding_total_cost_usd).label(
                    "embedding_total_cost_usd"
                ),
                sa.func.coalesce(sa.func.sum(scope_requires_action), 0).label(
                    "action_required_count"
                ),
                space_latest_run_at.label("latest_run_at"),
            )
            .select_from(aggregate_scope)
            .group_by(aggregate_scope.c.space_id, aggregate_scope.c.space_name)
            .order_by(*space_rollup_order_by)
            .limit(5)
        )
        space_rollup_result = await self.session.execute(space_rollup_stmt)
        space_rollup = tuple(
            CrawlerWebsiteProcessingSpaceRollupItem(
                space_id=row["space_id"],
                space_name=row["space_name"],
                website_count=int(row["website_count"]),
                total_runs=int(row["total_runs"]),
                pages_crawled=int(row["pages_crawled"]),
                files_downloaded=int(row["files_downloaded"]),
                indexed_size_bytes=int(row["indexed_size_bytes"]),
                embedding_input_tokens=_optional_int(row["embedding_input_tokens"]),
                embedding_total_cost_usd=_optional_decimal(
                    row["embedding_total_cost_usd"]
                ),
                action_required_count=int(row["action_required_count"]),
                latest_run_at=row["latest_run_at"],
            )
            for row in space_rollup_result.mappings()
        )

        if sort is CrawlerWebsiteProcessingSort.FAILURES:
            order_by = (
                failed_runs_count.desc(),
                (
                    sa.func.coalesce(sa.func.sum(CrawlRunsTable.pages_failed), 0)
                    + sa.func.coalesce(sa.func.sum(CrawlRunsTable.files_failed), 0)
                ).desc(),
                CrawlRunsTable.website_id.asc(),
            )
        elif sort is CrawlerWebsiteProcessingSort.RUNS:
            order_by = (
                total_runs_count.desc(),
                CrawlRunsTable.website_id.asc(),
            )
        elif sort is CrawlerWebsiteProcessingSort.TOKENS:
            order_by = (
                sa.func.coalesce(
                    sa.func.sum(CrawlRunsTable.embedding_input_tokens), 0
                ).desc(),
                latest_run_at.desc(),
                CrawlRunsTable.website_id.asc(),
            )
        elif sort is CrawlerWebsiteProcessingSort.INDEXED_SIZE:
            order_by = (
                sa.func.coalesce(Websites.size, 0).desc(),
                latest_run_at.desc(),
                CrawlRunsTable.website_id.asc(),
            )
        elif sort is CrawlerWebsiteProcessingSort.LOW_RETENTION:
            retention_for_ordering = sa.case(
                (
                    indexed_expr > 0,
                    retained_expr / sa.func.nullif(indexed_expr, 0),
                ),
                else_=1.0,
            )
            order_by = (
                retention_for_ordering.asc(),
                throughput.desc(),
                CrawlRunsTable.website_id.asc(),
            )
        elif sort is CrawlerWebsiteProcessingSort.RECENT:
            order_by = (
                latest_run_at.desc(),
                CrawlRunsTable.website_id.asc(),
            )
        else:
            # LOAD_PRESSURE — the historical default.
            order_by = (
                cost_pressure_for_ordering.desc(),
                throughput.desc(),
                CrawlRunsTable.website_id.asc(),
            )

        rows_stmt = aggregated_stmt.order_by(*order_by).limit(limit).offset(offset)
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
                    website_url=str(row["website_url"]),
                    tenant_id=row["tenant_id"],
                    tenant_display_name=row["tenant_display_name"],
                    space_id=row["space_id"],
                    space_name=row["space_name"],
                    collection_id=row["collection_id"],
                    collection_name=row["collection_name"],
                    owner_user_id=row["owner_user_id"],
                    owner_email=row["owner_email"],
                    update_interval=update_interval,
                    indexed_size_bytes=int(row["indexed_size_bytes"]),
                    latest_run_at=row["latest_run_at"],
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
                    embedding_input_tokens=_optional_int(row["embedding_input_tokens"]),
                    embedding_total_cost_usd=_optional_decimal(
                        row["embedding_total_cost_usd"]
                    ),
                    latest_embedding_model_name_snapshot=row[
                        "latest_embedding_model_name_snapshot"
                    ],
                    latest_embedding_model_litellm_name_snapshot=row[
                        "latest_embedding_model_litellm_name_snapshot"
                    ],
                    latest_embedding_model_provider_snapshot=row[
                        "latest_embedding_model_provider_snapshot"
                    ],
                    latest_embedding_input_tokens=_optional_int(
                        row["latest_embedding_input_tokens"]
                    ),
                    latest_embedding_total_cost_usd=_optional_decimal(
                        row["latest_embedding_total_cost_usd"]
                    ),
                    latest_embedding_usage_source=_optional_embedding_usage_source(
                        row["latest_embedding_usage_source"]
                    ),
                )
            )

        return CrawlerWebsiteProcessingAggregate(
            items=tuple(items),
            summary=summary,
            space_rollup=space_rollup,
            total=summary.website_count,
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
        website_id: UUID | None = None,
        space_id: UUID | None = None,
        sort: CrawlerWebsiteProcessingSort = (
            CrawlerWebsiteProcessingSort.LOAD_PRESSURE
        ),
        failures_only: bool = False,
        low_retention_only: bool = False,
        source_skip_drift_only: bool = False,
        search: str | None = None,
    ) -> CrawlerWebsiteProcessingAggregate:
        return await self.website_processing_aggregate(
            since=since,
            until=until,
            days=days,
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
            website_id=website_id,
            space_id=space_id,
            sort=sort,
            failures_only=failures_only,
            low_retention_only=low_retention_only,
            source_skip_drift_only=source_skip_drift_only,
            search=search,
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
                sa.func.sum(CrawlRunsTable.embedding_input_tokens).label(
                    "embedding_input_tokens"
                ),
                sa.func.sum(CrawlRunsTable.embedding_total_cost_usd).label(
                    "embedding_total_cost_usd"
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
        embedding_input_tokens: int | None = None
        embedding_total_cost_usd: Decimal | None = None

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
            row_embedding_input_tokens = _optional_int(row["embedding_input_tokens"])
            if row_embedding_input_tokens is not None:
                embedding_input_tokens = (
                    row_embedding_input_tokens
                    if embedding_input_tokens is None
                    else embedding_input_tokens + row_embedding_input_tokens
                )
            row_embedding_total_cost_usd = _optional_decimal(
                row["embedding_total_cost_usd"]
            )
            if row_embedding_total_cost_usd is not None:
                embedding_total_cost_usd = (
                    row_embedding_total_cost_usd
                    if embedding_total_cost_usd is None
                    else embedding_total_cost_usd + row_embedding_total_cost_usd
                )

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
                embedding_input_tokens=embedding_input_tokens,
                embedding_total_cost_usd=embedding_total_cost_usd,
            ),
        )


def _percentage(*, numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)
