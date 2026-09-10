from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from eneo.database.tables.info_blobs_table import InfoBlobs, active_info_blob_version
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.users_table import Users
from eneo.database.tables.websites_table import CrawlAttempts, CrawlRunFailures
from eneo.database.tables.websites_table import CrawlRuns as CrawlRunsTable
from eneo.database.tables.websites_table import Websites as WebsitesTable
from eneo.jobs.job_models import Task
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.main.models import Status
from eneo.websites.crawl_dependencies.crawl_models import CrawlTask
from eneo.websites.domain.crawl_run import (
    CrawlFailureCode,
    CrawlOrigin,
    CrawlOutcome,
    CrawlPhase,
    CrawlResourceFailure,
    CrawlResourceKind,
    CrawlRun,
)

LEASE_SWEEP_BATCH_SIZE = 100
DISPATCH_PAGE_SIZE = 50
_DISPATCH_ADVISORY_LOCK = 1_836_472_911
_LEASED_PHASES = (
    CrawlPhase.RUNNING.value,
    CrawlPhase.FINALIZING.value,
    CrawlPhase.STOPPING.value,
)
_SUCCESSFUL_OUTCOMES = {
    CrawlOutcome.SUCCEEDED,
    CrawlOutcome.UNCHANGED,
    CrawlOutcome.EMPTY,
    CrawlOutcome.PARTIAL,
}
_CLEAN_OUTCOMES = {
    CrawlOutcome.SUCCEEDED,
    CrawlOutcome.UNCHANGED,
    CrawlOutcome.EMPTY,
}
_PENDING_TRANSPORT_CLEANUP = sa.and_(
    CrawlAttempts.failure_code.in_(
        (
            CrawlFailureCode.LEASE_EXPIRED.value,
            CrawlFailureCode.CANCELLED.value,
        )
    ),
    CrawlAttempts.transport_cleaned_at.is_(None),
)

if TYPE_CHECKING:
    from eneo.database.database import AsyncSession


@dataclass(frozen=True, slots=True)
class CrawlDispatchCandidate:
    attempt_id: UUID
    attempt_number: int
    run_id: UUID
    dispatch_id: UUID
    payload: dict[str, object]
    website_id: UUID
    tenant_id: UUID
    origin: str


@dataclass(frozen=True, slots=True)
class CrawlCancellation:
    run: CrawlRun
    dispatch_id: UUID | None


@dataclass(frozen=True, slots=True)
class CrawlRunPage:
    items: list[CrawlRun]
    total_count: int
    next_cursor: UUID | None


@dataclass(frozen=True, slots=True)
class CrawlFailurePage:
    items: list[CrawlResourceFailure]
    total_count: int
    next_cursor: UUID | None


@dataclass(frozen=True, slots=True)
class CrawlOverviewItem:
    run: CrawlRun
    website_id: UUID
    website_name: str | None
    website_url: str
    space_name: str | None
    started_at: datetime | None
    last_indexed_at: datetime | None


class CrawlHistoryPeriod(StrEnum):
    LAST_24_HOURS = "last_24_hours"
    TODAY = "today"
    YESTERDAY = "yesterday"


CrawlOverviewStatus = (
    CrawlPhase | CrawlOutcome | Literal["issues", "completed", "unsuccessful"]
)


@dataclass(frozen=True, slots=True)
class CrawlDaySummary:
    date: date
    completed: int
    partial: int
    failed: int
    cancelled: int


@dataclass(frozen=True, slots=True)
class CrawlOverview:
    ongoing: int
    queued: int
    issues: int
    today: CrawlDaySummary
    yesterday: CrawlDaySummary
    items: list[CrawlOverviewItem]
    next_cursor: UUID | None


@dataclass(frozen=True, slots=True)
class CrawlUserMetadata:
    id: UUID
    username: str | None
    email: str


@dataclass(frozen=True, slots=True)
class CrawlDetails:
    item: CrawlOverviewItem
    space_id: UUID | None
    owner: CrawlUserMetadata
    initiated_by: CrawlUserMetadata | None
    indexed_size: int
    stored_resources: int
    update_interval: str
    next_retry_at: datetime | None
    consecutive_failures: int
    active_run: CrawlRun | None
    latest_run: CrawlRun | None


class CrawlDeletionBlocker(StrEnum):
    ACTIVE_CRAWL = "active_crawl"
    TRANSPORT_CLEANUP = "transport_cleanup_pending"


class WebsiteCrawlActiveError(Exception):
    """A website cannot be deleted while its crawl is active."""


class WebsiteCrawlCleanupPendingError(Exception):
    """A website cannot be deleted until durable transport cleanup completes."""


@dataclass(frozen=True, slots=True)
class CrawlLifecycleSnapshot:
    pending_dispatch: int
    queued: int
    running: int
    finalizing: int
    stopping: int
    expired_leases: int
    pending_transport_cleanup: int
    oldest_active_age_seconds: int | None

    @property
    def active_total(self) -> int:
        return (
            self.pending_dispatch
            + self.queued
            + self.running
            + self.finalizing
            + self.stopping
        )


class CrawlRunRepository:
    """Canonical persistence owner for crawl admission and execution state."""

    def __init__(self, session: "AsyncSession"):
        super().__init__()
        self.session = session

    async def one(self, id: UUID) -> CrawlRun:
        crawl_run = await self.one_or_none(id)
        if crawl_run is None:
            raise NotFoundException()
        return crawl_run

    async def one_or_none(self, id: UUID) -> CrawlRun | None:
        record = await self.session.scalar(
            sa.select(CrawlRunsTable)
            .where(CrawlRunsTable.id == id)
            .execution_options(populate_existing=True)
        )
        return CrawlRun.to_domain(record=record) if record is not None else None

    async def one_for_tenant(self, id: UUID, tenant_id: UUID) -> CrawlRun:
        record = await self.session.scalar(
            sa.select(CrawlRunsTable).where(
                CrawlRunsTable.id == id, CrawlRunsTable.tenant_id == tenant_id
            )
        )
        if record is None:
            raise NotFoundException()
        return CrawlRun.to_domain(record)

    async def tenant_overview(
        self,
        tenant_id: UUID,
        *,
        as_of: datetime,
        view: Literal["active", "recent"] = "active",
        status: CrawlOverviewStatus | None = None,
        period: CrawlHistoryPeriod = CrawlHistoryPeriod.LAST_24_HOURS,
        time_zone: ZoneInfo = ZoneInfo("UTC"),
        search: str = "",
        limit: int = 50,
        cursor: UUID | None = None,
    ) -> CrawlOverview:
        if not 1 <= limit <= 100:
            raise BadRequestException("Page size must be between 1 and 100")
        run = CrawlRunsTable
        cutoff = as_of - timedelta(hours=24)
        today_date = as_of.astimezone(time_zone).date()
        yesterday_date = today_date - timedelta(days=1)
        # Construct each local midnight separately: a calendar day can be 23 or 25 hours.
        today_start = datetime.combine(today_date, time.min, time_zone).astimezone(
            timezone.utc
        )
        yesterday_start = datetime.combine(
            yesterday_date, time.min, time_zone
        ).astimezone(timezone.utc)
        active = run.phase != CrawlPhase.TERMINAL
        terminal = sa.and_(run.phase == CrawlPhase.TERMINAL, run.finished_at <= as_of)
        recent = sa.and_(terminal, run.finished_at >= cutoff)
        today = sa.and_(terminal, run.finished_at >= today_start)
        yesterday = sa.and_(
            terminal, run.finished_at >= yesterday_start, run.finished_at < today_start
        )
        history_window = {
            CrawlHistoryPeriod.LAST_24_HOURS: recent,
            CrawlHistoryPeriod.TODAY: today,
            CrawlHistoryPeriod.YESTERDAY: yesterday,
        }[period]
        queued = run.phase.in_((CrawlPhase.PENDING_DISPATCH, CrawlPhase.QUEUED))
        completed = run.outcome.in_(_CLEAN_OUTCOMES)
        partial = run.outcome == CrawlOutcome.PARTIAL
        unsuccessful = run.outcome.in_((CrawlOutcome.FAILED, CrawlOutcome.INTERRUPTED))
        cancelled = run.outcome == CrawlOutcome.CANCELLED
        issues = sa.or_(partial, unsuccessful)
        counts = (
            await self.session.execute(
                sa.select(
                    sa.func.count().filter(run.phase.in_(_LEASED_PHASES)),
                    sa.func.count().filter(queued),
                    sa.func.count().filter(sa.and_(recent, issues)),
                    *[
                        sa.func.count().filter(sa.and_(window, outcome))
                        for window in (today, yesterday)
                        for outcome in (completed, partial, unsuccessful, cancelled)
                    ],
                ).where(
                    run.tenant_id == tenant_id,
                    sa.or_(
                        active,
                        sa.and_(
                            terminal, run.finished_at >= min(cutoff, yesterday_start)
                        ),
                    ),
                )
            )
        ).one()

        # Select metadata columns only: hydrating Spaces would load its content.
        query = (
            sa.select(
                run,
                WebsitesTable.name,
                WebsitesTable.url,
                Spaces.name.label("space_name"),
                CrawlAttempts.started_at,
                WebsitesTable.last_indexed_at,
            )
            .join(
                WebsitesTable,
                sa.and_(
                    WebsitesTable.id == run.website_id,
                    WebsitesTable.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                Spaces,
                sa.and_(
                    Spaces.id == WebsitesTable.space_id, Spaces.tenant_id == tenant_id
                ),
            )
            .outerjoin(
                CrawlAttempts,
                sa.and_(
                    CrawlAttempts.crawl_run_id == run.id,
                    CrawlAttempts.attempt_number == run.attempt_count,
                ),
            )
            .where(
                run.tenant_id == tenant_id,
                active if view == "active" else history_window,
            )
            .limit(limit + 1)
        )
        if status == "issues":
            query = query.where(issues)
        elif status == "completed":
            query = query.where(completed)
        elif status == "unsuccessful":
            query = query.where(unsuccessful)
        elif status == CrawlPhase.QUEUED:
            query = query.where(queued)
        elif isinstance(status, CrawlPhase):
            query = query.where(run.phase == status)
        elif isinstance(status, CrawlOutcome):
            query = query.where(run.outcome == status)
        if search.strip():
            query = query.where(
                sa.or_(
                    WebsitesTable.name.icontains(search.strip(), autoescape=True),
                    WebsitesTable.url.icontains(search.strip(), autoescape=True),
                )
            )
        timestamp = run.created_at if view == "active" else run.finished_at
        if cursor is not None:
            anchor = (
                await self.session.execute(
                    sa.select(timestamp).where(
                        run.id == cursor, run.tenant_id == tenant_id
                    )
                )
            ).one_or_none()
            if anchor is None or anchor[0] is None:
                raise BadRequestException("Invalid crawl overview cursor")
            position = sa.tuple_(timestamp, run.id)
            boundary = sa.tuple_(sa.literal(anchor[0]), sa.literal(cursor))
            query = query.where(
                position > boundary if view == "active" else position < boundary
            )
        query = (
            query.order_by(timestamp, run.id)
            if view == "active"
            else query.order_by(timestamp.desc(), run.id.desc())
        )
        rows = (await self.session.execute(query)).all()
        items = [
            CrawlOverviewItem(
                run=CrawlRun.to_domain(row[0]),
                website_id=row[0].website_id,
                website_name=row[1],
                website_url=row[2],
                space_name=row[3],
                started_at=row[4],
                last_indexed_at=row[5],
            )
            for row in rows[:limit]
        ]
        return CrawlOverview(
            ongoing=counts[0],
            queued=counts[1],
            issues=counts[2],
            today=CrawlDaySummary(
                today_date, counts[3], counts[4], counts[5], counts[6]
            ),
            yesterday=CrawlDaySummary(
                yesterday_date, counts[7], counts[8], counts[9], counts[10]
            ),
            items=items,
            next_cursor=items[-1].run.id if len(rows) > limit else None,
        )

    async def tenant_details(self, id: UUID, tenant_id: UUID) -> CrawlDetails:
        initial_attempt = aliased(CrawlAttempts)
        row = (
            await self.session.execute(
                sa.select(
                    CrawlRunsTable,
                    WebsitesTable.name,
                    WebsitesTable.url,
                    Spaces.name.label("space_name"),
                    CrawlAttempts.started_at,
                    WebsitesTable.last_indexed_at,
                    WebsitesTable.space_id,
                    WebsitesTable.size,
                    WebsitesTable.update_interval,
                    WebsitesTable.next_retry_at,
                    WebsitesTable.consecutive_failures,
                    Users.id.label("owner_id"),
                    Users.username,
                    Users.email,
                    initial_attempt.dispatch_payload["user_id"].astext.label(
                        "initiator_id"
                    ),
                )
                .join(
                    WebsitesTable,
                    sa.and_(
                        WebsitesTable.id == CrawlRunsTable.website_id,
                        WebsitesTable.tenant_id == tenant_id,
                    ),
                )
                .join(
                    Users,
                    sa.and_(
                        Users.id == WebsitesTable.user_id, Users.tenant_id == tenant_id
                    ),
                )
                .outerjoin(
                    Spaces,
                    sa.and_(
                        Spaces.id == WebsitesTable.space_id,
                        Spaces.tenant_id == tenant_id,
                    ),
                )
                .outerjoin(
                    CrawlAttempts,
                    sa.and_(
                        CrawlAttempts.crawl_run_id == CrawlRunsTable.id,
                        CrawlAttempts.attempt_number == CrawlRunsTable.attempt_count,
                    ),
                )
                .outerjoin(
                    initial_attempt,
                    sa.and_(
                        initial_attempt.crawl_run_id == CrawlRunsTable.id,
                        initial_attempt.attempt_number == 1,
                    ),
                )
                .where(CrawlRunsTable.id == id, CrawlRunsTable.tenant_id == tenant_id)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundException()
        run = CrawlRun.to_domain(row[0])
        initiated_by = None
        # Scheduled payloads identify the execution account, not a human request.
        if run.origin == CrawlOrigin.MANUAL and row.initiator_id:
            try:
                initiator_id = UUID(row.initiator_id)
            except ValueError:
                initiator_id = None
            if initiator_id is not None:
                initiator = (
                    await self.session.execute(
                        sa.select(Users.id, Users.username, Users.email).where(
                            Users.id == initiator_id,
                            Users.tenant_id == tenant_id,
                        )
                    )
                ).one_or_none()
                if initiator is not None:
                    initiated_by = CrawlUserMetadata(*initiator)

        stored_resources = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(InfoBlobs)
            .where(
                InfoBlobs.website_id == run.website_id,
                InfoBlobs.tenant_id == tenant_id,
                active_info_blob_version(),
            )
        )
        return CrawlDetails(
            item=CrawlOverviewItem(
                run=run,
                website_id=run.website_id,
                website_name=row.name,
                website_url=row.url,
                space_name=row.space_name,
                started_at=row.started_at,
                last_indexed_at=row.last_indexed_at,
            ),
            space_id=row.space_id,
            owner=CrawlUserMetadata(row.owner_id, row.username, row.email),
            initiated_by=initiated_by,
            indexed_size=row.size,
            stored_resources=stored_resources or 0,
            update_interval=row.update_interval,
            next_retry_at=row.next_retry_at,
            consecutive_failures=row.consecutive_failures,
            active_run=await self.get_active_for_website(run.website_id),
            latest_run=await self.get_latest_for_website(run.website_id),
        )

    async def get_failures(
        self, run_id: UUID, *, limit: int = 100, cursor: UUID | None = None
    ) -> CrawlFailurePage:
        if not 1 <= limit <= 100:
            raise BadRequestException("Failure page size must be between 1 and 100")
        query = (
            sa.select(CrawlRunFailures)
            .where(CrawlRunFailures.crawl_run_id == run_id)
            .order_by(CrawlRunFailures.created_at, CrawlRunFailures.id)
            .limit(limit + 1)
        )
        if cursor is not None:
            cursor_created_at = await self.session.scalar(
                sa.select(CrawlRunFailures.created_at).where(
                    CrawlRunFailures.crawl_run_id == run_id,
                    CrawlRunFailures.id == cursor,
                )
            )
            if cursor_created_at is None:
                raise BadRequestException(
                    "Failure cursor does not belong to this crawl"
                )
            query = query.where(
                sa.tuple_(CrawlRunFailures.created_at, CrawlRunFailures.id)
                > sa.tuple_(sa.literal(cursor_created_at), sa.literal(cursor))
            )
        records = list(await self.session.scalars(query))
        items = [
            CrawlResourceFailure(
                id=row.id,
                url=row.url,
                reason=row.reason,
                kind=CrawlResourceKind(row.kind),
            )
            for row in records[:limit]
        ]
        total_count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(CrawlRunFailures)
            .where(CrawlRunFailures.crawl_run_id == run_id)
        )
        return CrawlFailurePage(
            items=items,
            total_count=total_count or 0,
            next_cursor=items[-1].id if len(records) > limit else None,
        )

    async def _record_failures(
        self, run_id: UUID, failures: Sequence[CrawlResourceFailure]
    ) -> None:
        if failures:
            await self.session.execute(
                pg_insert(CrawlRunFailures)
                .values(
                    [
                        {
                            "id": failure.id,
                            "crawl_run_id": run_id,
                            "url": failure.url,
                            "reason": failure.reason,
                            "kind": failure.kind.value,
                        }
                        for failure in failures
                    ]
                )
                .on_conflict_do_nothing(index_elements=[CrawlRunFailures.id])
            )

    async def health_snapshot(self) -> CrawlLifecycleSnapshot:
        """Return aggregate state using the same current-attempt invariants as repair."""
        phase_rows = (
            await self.session.execute(
                sa.select(
                    CrawlRunsTable.phase,
                    sa.func.count(),
                    sa.func.extract(
                        "epoch",
                        sa.func.now() - sa.func.min(CrawlRunsTable.created_at),
                    ),
                )
                .where(CrawlRunsTable.phase != CrawlPhase.TERMINAL.value)
                .group_by(CrawlRunsTable.phase)
            )
        ).all()
        counts: dict[str, int] = {}
        oldest_active_age_seconds: int | None = None
        for phase, count, oldest_age_seconds in phase_rows:
            counts[str(phase)] = int(count)
            if oldest_age_seconds is not None:
                phase_age_seconds = max(0, int(oldest_age_seconds))
                oldest_active_age_seconds = max(
                    oldest_active_age_seconds or 0,
                    phase_age_seconds,
                )
        expired = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(CrawlAttempts)
            .join(CrawlRunsTable, CrawlRunsTable.id == CrawlAttempts.crawl_run_id)
            .where(CrawlAttempts.finished_at.is_(None))
            .where(CrawlAttempts.lease_expires_at < sa.func.now())
            .where(CrawlRunsTable.phase != CrawlPhase.TERMINAL.value)
            .where(CrawlRunsTable.attempt_count == CrawlAttempts.attempt_number)
        )
        pending_transport_cleanup = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(CrawlAttempts)
            .where(_PENDING_TRANSPORT_CLEANUP)
        )
        return CrawlLifecycleSnapshot(
            pending_dispatch=counts.get(CrawlPhase.PENDING_DISPATCH.value, 0),
            queued=counts.get(CrawlPhase.QUEUED.value, 0),
            running=counts.get(CrawlPhase.RUNNING.value, 0),
            finalizing=counts.get(CrawlPhase.FINALIZING.value, 0),
            stopping=counts.get(CrawlPhase.STOPPING.value, 0),
            expired_leases=int(expired or 0),
            pending_transport_cleanup=int(pending_transport_cleanup or 0),
            oldest_active_age_seconds=oldest_active_age_seconds,
        )

    @staticmethod
    def _values(crawl_run: CrawlRun) -> dict[str, object]:
        assert crawl_run.id is not None
        return {
            "id": crawl_run.id,
            "website_id": crawl_run.website_id,
            "tenant_id": crawl_run.tenant_id,
            "pages_crawled": crawl_run.pages_crawled,
            "files_downloaded": crawl_run.files_downloaded,
            "pages_failed": crawl_run.pages_failed,
            "files_failed": crawl_run.files_failed,
            "failure_summary": crawl_run.failure_summary,
            "phase": crawl_run.phase.value,
            "outcome": crawl_run.outcome.value if crawl_run.outcome else None,
            "origin": crawl_run.origin.value,
            "result_location": crawl_run.result_location,
            "finished_at": crawl_run.finished_at,
            "failure_code": crawl_run.failure_code,
            "failure_detail": crawl_run.failure_detail,
            "cancel_requested_at": crawl_run.cancel_requested_at,
            "attempt_count": crawl_run.attempt_count,
            "job_id": crawl_run.job_id,
        }

    async def add_or_get_active(self, crawl_run: CrawlRun) -> tuple[CrawlRun, bool]:
        for _attempt in range(2):
            statement = (
                pg_insert(CrawlRunsTable)
                .values(**self._values(crawl_run))
                .on_conflict_do_nothing(
                    index_elements=[CrawlRunsTable.website_id],
                    index_where=sa.text("phase <> 'terminal'"),
                )
                .returning(CrawlRunsTable)
            )
            record = await self.session.scalar(statement)
            if record is not None:
                return CrawlRun.to_domain(record=record), True

            record = await self.session.scalar(
                sa.select(CrawlRunsTable)
                .where(CrawlRunsTable.website_id == crawl_run.website_id)
                .where(CrawlRunsTable.phase != CrawlPhase.TERMINAL.value)
                .order_by(CrawlRunsTable.created_at.asc(), CrawlRunsTable.id.asc())
                .limit(1)
            )
            if record is not None:
                return CrawlRun.to_domain(record=record), False

        raise RuntimeError("Active crawl changed repeatedly during admission")

    async def get_crawl_runs(
        self, website_id: UUID, *, limit: int = 100, cursor: UUID | None = None
    ) -> CrawlRunPage:
        if not 1 <= limit <= 100:
            raise BadRequestException("History page size must be between 1 and 100")
        query = (
            sa.select(CrawlRunsTable)
            .where(CrawlRunsTable.website_id == website_id)
            .order_by(CrawlRunsTable.created_at.desc(), CrawlRunsTable.id.desc())
            .limit(limit + 1)
        )
        if cursor is not None:
            cursor_created_at = await self.session.scalar(
                sa.select(CrawlRunsTable.created_at).where(
                    CrawlRunsTable.id == cursor,
                    CrawlRunsTable.website_id == website_id,
                )
            )
            if cursor_created_at is None:
                raise BadRequestException(
                    "History cursor does not belong to this website"
                )
            query = query.where(
                sa.tuple_(CrawlRunsTable.created_at, CrawlRunsTable.id)
                < sa.tuple_(sa.literal(cursor_created_at), sa.literal(cursor))
            )
        records = list(await self.session.scalars(query))
        total_count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(CrawlRunsTable)
            .where(CrawlRunsTable.website_id == website_id)
        )
        items = [CrawlRun.to_domain(record=record) for record in records[:limit]]
        return CrawlRunPage(
            items=items,
            total_count=total_count or 0,
            next_cursor=items[-1].id if len(records) > limit else None,
        )

    async def get_active_for_website(self, website_id: UUID) -> CrawlRun | None:
        record = await self.session.scalar(
            sa.select(CrawlRunsTable)
            .where(CrawlRunsTable.website_id == website_id)
            .where(CrawlRunsTable.phase != CrawlPhase.TERMINAL.value)
            .order_by(CrawlRunsTable.created_at.asc(), CrawlRunsTable.id.asc())
            .limit(1)
        )
        return CrawlRun.to_domain(record=record) if record is not None else None

    async def get_latest_for_website(self, website_id: UUID) -> CrawlRun | None:
        record = await self.session.scalar(
            sa.select(CrawlRunsTable)
            .where(CrawlRunsTable.website_id == website_id)
            .order_by(CrawlRunsTable.created_at.desc(), CrawlRunsTable.id.desc())
            .limit(1)
        )
        return CrawlRun.to_domain(record=record) if record is not None else None

    async def lock_website_deletion(
        self,
        website_id: UUID,
    ) -> CrawlDeletionBlocker | None:
        """Fence new crawl admission and report lifecycle work that blocks deletion."""
        locked_website_id = await self.session.scalar(
            sa.select(WebsitesTable.id)
            .where(WebsitesTable.id == website_id)
            .with_for_update()
        )
        if locked_website_id is None:
            raise NotFoundException()

        has_active_crawl = await self.session.scalar(
            sa.select(
                sa.exists().where(
                    CrawlRunsTable.website_id == website_id,
                    CrawlRunsTable.phase != CrawlPhase.TERMINAL.value,
                )
            )
        )
        if has_active_crawl:
            return CrawlDeletionBlocker.ACTIVE_CRAWL

        has_pending_cleanup = await self.session.scalar(
            sa.select(
                sa.exists()
                .where(CrawlRunsTable.website_id == website_id)
                .where(CrawlAttempts.crawl_run_id == CrawlRunsTable.id)
                .where(_PENDING_TRANSPORT_CLEANUP)
            )
        )
        if has_pending_cleanup:
            return CrawlDeletionBlocker.TRANSPORT_CLEANUP
        return None

    async def request_cancel(self, run_id: UUID) -> CrawlCancellation:
        """Persist a cancellation before Redis is asked to stop its delivery."""
        attempt_id = await self.session.scalar(
            sa.select(CrawlAttempts.id)
            .join(CrawlRunsTable, CrawlRunsTable.id == CrawlAttempts.crawl_run_id)
            .where(CrawlRunsTable.id == run_id)
            .where(CrawlRunsTable.attempt_count == CrawlAttempts.attempt_number)
        )
        pair = (
            await self._lock_current_attempt(attempt_id)
            if attempt_id is not None
            else None
        )
        if pair is None:
            run = await self.session.scalar(
                sa.select(CrawlRunsTable).where(CrawlRunsTable.id == run_id)
            )
            if run is None:
                raise NotFoundException()
            if run.phase == CrawlPhase.TERMINAL.value:
                return CrawlCancellation(
                    run=CrawlRun.to_domain(record=run),
                    dispatch_id=None,
                )
            raise RuntimeError("Active crawl run has no current attempt")
        attempt, run = pair
        if run.id != run_id:
            raise RuntimeError("Crawl attempt does not belong to the requested run")
        if run.phase == CrawlPhase.TERMINAL.value:
            return CrawlCancellation(
                run=CrawlRun.to_domain(record=run),
                dispatch_id=None,
            )
        if attempt.finished_at is not None:
            raise RuntimeError("Active crawl run has no current attempt")

        now = await self._database_now()
        run.cancel_requested_at = run.cancel_requested_at or now
        if run.phase in {
            CrawlPhase.PENDING_DISPATCH.value,
            CrawlPhase.QUEUED.value,
        }:
            detail = "The crawl was stopped by a user"
            self._finish_records(
                attempt,
                run,
                outcome=CrawlOutcome.CANCELLED,
                finished_at=now,
                failure_code=CrawlFailureCode.CANCELLED.value,
                failure_detail=detail,
                result_location=None,
            )
            await self._project_job_terminal(
                attempt.dispatch_id,
                outcome=CrawlOutcome.CANCELLED,
                finished_at=now,
                failure_code=CrawlFailureCode.CANCELLED.value,
                failure_detail=detail,
                result_location=None,
            )
        elif run.phase in {
            CrawlPhase.RUNNING.value,
            CrawlPhase.FINALIZING.value,
            CrawlPhase.STOPPING.value,
        }:
            run.phase = CrawlPhase.STOPPING.value
        else:
            raise RuntimeError(f"Unsupported active crawl phase: {run.phase}")

        await self.session.flush()
        await self.session.refresh(run)
        return CrawlCancellation(
            run=CrawlRun.to_domain(record=run),
            dispatch_id=attempt.dispatch_id,
        )

    async def add_attempt(
        self,
        *,
        run_id: UUID,
        attempt_id: UUID,
        dispatch_id: UUID,
        task: CrawlTask,
    ) -> None:
        run = await self.session.scalar(
            sa.select(CrawlRunsTable)
            .where(CrawlRunsTable.id == run_id)
            .with_for_update()
        )
        if run is None:
            raise NotFoundException()
        if run.phase != CrawlPhase.PENDING_DISPATCH.value:
            raise ValueError("Attempts can only be added to pending crawl runs")

        job = await self.session.scalar(
            sa.select(Jobs).where(Jobs.id == dispatch_id).with_for_update()
        )
        if job is None or job.task != Task.CRAWL.value:
            raise ValueError("A crawl attempt requires its crawl job projection")

        attempt_number = run.attempt_count + 1
        if task.attempt_id != attempt_id or task.attempt_number != attempt_number:
            raise ValueError("Crawl task does not match the admitted attempt")
        if task.run_id != run_id or task.website_id != run.website_id:
            raise ValueError("Crawl task does not match the crawl run")
        if task.origin.value != run.origin or task.user_id != job.user_id:
            raise ValueError("Crawl task identity does not match persisted ownership")

        await self.session.execute(
            sa.insert(CrawlAttempts).values(
                id=attempt_id,
                crawl_run_id=run_id,
                attempt_number=attempt_number,
                dispatch_id=dispatch_id,
                dispatch_payload=task.model_dump(mode="json"),
            )
        )
        run.attempt_count = attempt_number
        run.job_id = dispatch_id
        await self.session.flush()

    async def claim_dispatch_candidates(
        self,
        *,
        concurrency_limit: int,
        retry_after: timedelta,
        redeliver_after: timedelta,
        tenant_concurrency_limit: int | None = None,
    ) -> list[CrawlDispatchCandidate]:
        if concurrency_limit <= 0:
            return []
        if tenant_concurrency_limit is not None and tenant_concurrency_limit <= 0:
            raise ValueError("Per-tenant crawl concurrency limit must be positive")
        if retry_after <= timedelta(0):
            raise ValueError("Dispatch retry interval must be positive")
        if redeliver_after <= retry_after:
            raise ValueError(
                "Queue redelivery interval must exceed the dispatch retry interval"
            )

        # Wait for the short claim transaction so a concurrent completion cannot
        # lose the wake-up that should fill its newly released capacity slot.
        await self.session.execute(
            sa.select(sa.func.pg_advisory_xact_lock(_DISPATCH_ADVISORY_LOCK))
        )

        now = await self._database_now()
        stale_before = now - retry_after
        redeliver_before = now - redeliver_after
        leased_units = sa.select(
            CrawlRunsTable.tenant_id.label("tenant_id"),
            sa.literal(1).label("units"),
        ).where(CrawlRunsTable.phase.in_(_LEASED_PHASES))
        pending_units = (
            sa.select(
                CrawlRunsTable.tenant_id.label("tenant_id"),
                sa.literal(1).label("units"),
            )
            .join(
                CrawlAttempts,
                CrawlAttempts.crawl_run_id == CrawlRunsTable.id,
            )
            .where(CrawlRunsTable.phase == CrawlPhase.PENDING_DISPATCH.value)
            .where(CrawlAttempts.finished_at.is_(None))
            .where(CrawlAttempts.dispatched_at.is_(None))
            .where(CrawlAttempts.dispatch_attempted_at.is_not(None))
        )
        queued_units = (
            sa.select(
                CrawlRunsTable.tenant_id.label("tenant_id"),
                sa.literal(1).label("units"),
            )
            .join(
                CrawlAttempts,
                CrawlAttempts.crawl_run_id == CrawlRunsTable.id,
            )
            .where(CrawlRunsTable.phase == CrawlPhase.QUEUED.value)
            .where(CrawlAttempts.finished_at.is_(None))
            .where(CrawlAttempts.started_at.is_(None))
            .where(CrawlAttempts.dispatch_attempted_at.is_not(None))
        )
        active_units = sa.union_all(
            leased_units,
            pending_units,
            queued_units,
        ).cte("crawl_admission_units")
        tenant_load = (
            sa.select(
                active_units.c.tenant_id,
                sa.func.sum(active_units.c.units).label("units"),
            )
            .group_by(active_units.c.tenant_id)
            .cte("crawl_tenant_load")
        )
        reserved = int(
            await self.session.scalar(
                sa.select(sa.func.count()).select_from(active_units)
            )
            or 0
        )
        # A timed-out enqueue is ambiguous: PostgreSQL cannot prove that the
        # prior Redis delivery disappeared. It therefore continues to reserve
        # one logical slot while the same dispatch ID is repaired. Only work
        # that has never been attempted may consume newly available capacity.
        repair_position = sa.func.row_number().over(
            partition_by=CrawlRunsTable.tenant_id,
            order_by=(CrawlAttempts.created_at.asc(), CrawlAttempts.id.asc()),
        )
        repair_ranked = (
            sa.select(
                CrawlAttempts.id.label("attempt_id"),
                CrawlRunsTable.tenant_id.label("tenant_id"),
                CrawlAttempts.created_at.label("created_at"),
                repair_position.label("tenant_position"),
            )
            .join(CrawlRunsTable, CrawlRunsTable.id == CrawlAttempts.crawl_run_id)
            .where(CrawlAttempts.finished_at.is_(None))
            .where(CrawlAttempts.started_at.is_(None))
            .where(CrawlAttempts.dispatch_attempted_at <= stale_before)
            .where(
                sa.or_(
                    sa.and_(
                        CrawlRunsTable.phase == CrawlPhase.PENDING_DISPATCH.value,
                        CrawlAttempts.dispatched_at.is_(None),
                    ),
                    sa.and_(
                        CrawlRunsTable.phase == CrawlPhase.QUEUED.value,
                        CrawlAttempts.started_at.is_(None),
                        CrawlAttempts.dispatched_at <= redeliver_before,
                    ),
                )
            )
            .cte("ranked_crawl_repairs")
        )
        repair_chosen = (
            sa.select(repair_ranked.c.attempt_id)
            .outerjoin(
                tenant_load,
                tenant_load.c.tenant_id == repair_ranked.c.tenant_id,
            )
            .order_by(
                (
                    sa.func.coalesce(tenant_load.c.units, 0)
                    + repair_ranked.c.tenant_position
                ).asc(),
                repair_ranked.c.created_at.asc(),
                repair_ranked.c.attempt_id.asc(),
            )
            .limit(DISPATCH_PAGE_SIZE)
            .cte("chosen_crawl_repairs")
        )
        repair_rows = (
            await self.session.execute(
                sa.select(CrawlAttempts, CrawlRunsTable)
                .join(
                    repair_chosen,
                    repair_chosen.c.attempt_id == CrawlAttempts.id,
                )
                .join(
                    CrawlRunsTable,
                    CrawlRunsTable.id == CrawlAttempts.crawl_run_id,
                )
                .order_by(CrawlAttempts.created_at.asc(), CrawlAttempts.id.asc())
                .with_for_update(of=CrawlAttempts, skip_locked=True)
            )
        ).all()

        fresh_limit = min(
            max(concurrency_limit - reserved, 0),
            DISPATCH_PAGE_SIZE - len(repair_rows),
        )
        fresh_rows = repair_rows[:0]
        if fresh_limit > 0:
            fresh_position = sa.func.row_number().over(
                partition_by=CrawlRunsTable.tenant_id,
                order_by=(CrawlAttempts.created_at.asc(), CrawlAttempts.id.asc()),
            )
            fresh_ranked = (
                sa.select(
                    CrawlAttempts.id.label("attempt_id"),
                    CrawlRunsTable.tenant_id.label("tenant_id"),
                    CrawlAttempts.created_at.label("created_at"),
                    fresh_position.label("tenant_position"),
                )
                .join(
                    CrawlRunsTable,
                    CrawlRunsTable.id == CrawlAttempts.crawl_run_id,
                )
                .where(
                    CrawlRunsTable.phase == CrawlPhase.PENDING_DISPATCH.value,
                    CrawlAttempts.finished_at.is_(None),
                    CrawlAttempts.started_at.is_(None),
                    CrawlAttempts.dispatched_at.is_(None),
                    CrawlAttempts.dispatch_attempted_at.is_(None),
                )
                .cte("ranked_fresh_crawl_dispatches")
            )
            fresh_selection = sa.select(fresh_ranked.c.attempt_id).outerjoin(
                tenant_load,
                tenant_load.c.tenant_id == fresh_ranked.c.tenant_id,
            )
            if tenant_concurrency_limit is not None:
                # Repairs already own a reservation and bypass this ceiling.
                # Include batch position so a single claim cannot overfill it.
                fresh_selection = fresh_selection.where(
                    sa.func.coalesce(tenant_load.c.units, 0)
                    + fresh_ranked.c.tenant_position
                    <= tenant_concurrency_limit
                )
            fresh_chosen = (
                fresh_selection.order_by(
                    (
                        sa.func.coalesce(tenant_load.c.units, 0)
                        + fresh_ranked.c.tenant_position
                    ).asc(),
                    fresh_ranked.c.created_at.asc(),
                    fresh_ranked.c.attempt_id.asc(),
                )
                .limit(fresh_limit)
                .cte("chosen_fresh_crawl_dispatches")
            )
            fresh_rows = list(
                (
                    await self.session.execute(
                        sa.select(CrawlAttempts, CrawlRunsTable)
                        .join(
                            fresh_chosen,
                            fresh_chosen.c.attempt_id == CrawlAttempts.id,
                        )
                        .join(
                            CrawlRunsTable,
                            CrawlRunsTable.id == CrawlAttempts.crawl_run_id,
                        )
                        .order_by(
                            CrawlAttempts.created_at.asc(),
                            CrawlAttempts.id.asc(),
                        )
                        .with_for_update(of=CrawlAttempts, skip_locked=True)
                    )
                ).all()
            )

        rows = [*repair_rows, *fresh_rows]

        candidates: list[CrawlDispatchCandidate] = []
        for attempt, run in rows:
            attempt.dispatch_attempted_at = now
            candidates.append(
                CrawlDispatchCandidate(
                    attempt_id=attempt.id,
                    attempt_number=attempt.attempt_number,
                    run_id=run.id,
                    dispatch_id=attempt.dispatch_id,
                    payload=cast(dict[str, object], attempt.dispatch_payload),
                    website_id=run.website_id,
                    tenant_id=run.tenant_id,
                    origin=run.origin,
                )
            )
        await self.session.flush()
        return candidates

    async def mark_dispatched(self, attempt_id: UUID) -> bool:
        pair = await self._lock_current_attempt(attempt_id)
        if pair is None:
            return False
        attempt, run = pair
        if attempt.finished_at is not None or run.phase == CrawlPhase.TERMINAL.value:
            return False
        now = await self._database_now()
        attempt.dispatch_attempted_at = attempt.dispatch_attempted_at or now
        attempt.dispatched_at = attempt.dispatched_at or now
        if run.phase == CrawlPhase.PENDING_DISPATCH.value:
            run.phase = CrawlPhase.QUEUED.value
        await self.session.flush()
        return True

    async def reject_pending_attempt(
        self,
        attempt_id: UUID,
        *,
        failure_code: CrawlFailureCode,
        failure_detail: str,
    ) -> bool:
        pair = await self._lock_current_attempt(attempt_id)
        if pair is None:
            return False
        attempt, run = pair
        if (
            attempt.finished_at is not None
            or attempt.started_at is not None
            or run.phase == CrawlPhase.TERMINAL.value
        ):
            return False
        now = await self._database_now()
        detail = failure_detail[:512]
        self._finish_records(
            attempt,
            run,
            outcome=CrawlOutcome.FAILED,
            finished_at=now,
            failure_code=failure_code.value,
            failure_detail=detail,
            result_location=None,
        )
        await self._project_job_terminal(
            attempt.dispatch_id,
            outcome=CrawlOutcome.FAILED,
            finished_at=now,
            failure_code=failure_code.value,
            failure_detail=detail,
            result_location=None,
        )
        await self.session.flush()
        return True

    async def claim_attempt(
        self,
        attempt_id: UUID,
        *,
        dispatch_id: UUID,
        lease_owner: str,
        lease_duration: timedelta,
    ) -> CrawlTask | None:
        if not lease_owner:
            raise ValueError("A crawl lease owner cannot be empty")
        if lease_duration <= timedelta(0):
            raise ValueError("A crawl lease duration must be positive")

        pair = await self._lock_current_attempt(attempt_id)
        if pair is None:
            return None
        attempt, run = pair
        if dispatch_id != attempt.dispatch_id:
            return None
        if (
            attempt.finished_at is not None
            or attempt.lease_owner is not None
            or run.phase == CrawlPhase.TERMINAL.value
            or run.phase
            not in {
                CrawlPhase.PENDING_DISPATCH.value,
                CrawlPhase.QUEUED.value,
            }
        ):
            return None

        task = CrawlTask.model_validate(attempt.dispatch_payload)
        self._validate_execution(attempt, run, task=task)

        now = await self._database_now()
        attempt.dispatch_attempted_at = attempt.dispatch_attempted_at or now
        attempt.dispatched_at = attempt.dispatched_at or now
        attempt.lease_owner = lease_owner
        attempt.lease_expires_at = now + lease_duration
        attempt.started_at = now
        run.phase = CrawlPhase.RUNNING.value
        run.failure_details_available = True
        await self.session.execute(
            sa.update(Jobs)
            .where(Jobs.id == dispatch_id)
            .values(status=Status.IN_PROGRESS.value, updated_at=now)
        )
        await self.session.flush()
        return task

    async def renew_attempt_lease(
        self,
        attempt_id: UUID,
        *,
        lease_owner: str,
        lease_duration: timedelta,
        pages_crawled: int | None = None,
        files_downloaded: int | None = None,
        pages_failed: int | None = None,
        files_failed: int | None = None,
        failures: Sequence[CrawlResourceFailure] = (),
    ) -> bool:
        if lease_duration <= timedelta(0):
            raise ValueError("A crawl lease duration must be positive")
        progress = {
            "pages_crawled": pages_crawled,
            "files_downloaded": files_downloaded,
            "pages_failed": pages_failed,
            "files_failed": files_failed,
        }
        if any(value is not None and value < 0 for value in progress.values()):
            raise ValueError("Crawl counters cannot be negative")
        renewed = (
            await self.session.execute(
                sa.update(CrawlAttempts)
                .where(CrawlAttempts.id == attempt_id)
                .where(CrawlAttempts.finished_at.is_(None))
                .where(CrawlAttempts.lease_owner == lease_owner)
                .where(CrawlAttempts.lease_expires_at > sa.func.now())
                .where(
                    sa.exists(
                        sa.select(1)
                        .select_from(CrawlRunsTable)
                        .where(CrawlRunsTable.id == CrawlAttempts.crawl_run_id)
                        .where(
                            CrawlRunsTable.phase.in_(
                                (
                                    CrawlPhase.RUNNING.value,
                                    CrawlPhase.FINALIZING.value,
                                )
                            )
                        )
                    )
                )
                .values(lease_expires_at=sa.func.now() + lease_duration)
                .returning(
                    CrawlAttempts.dispatch_id,
                    CrawlAttempts.crawl_run_id,
                )
            )
        ).one_or_none()
        if renewed is None:
            return False
        dispatch_id, crawl_run_id = renewed
        await self._record_failures(crawl_run_id, failures)
        progress_values = {
            name: value for name, value in progress.items() if value is not None
        }
        if progress_values:
            await self.session.execute(
                sa.update(CrawlRunsTable)
                .where(CrawlRunsTable.id == crawl_run_id)
                .where(
                    CrawlRunsTable.phase.in_(
                        (
                            CrawlPhase.RUNNING.value,
                            CrawlPhase.FINALIZING.value,
                        )
                    )
                )
                .values(**progress_values)
            )
        await self.session.execute(
            sa.update(Jobs)
            .where(Jobs.id == dispatch_id)
            .values(updated_at=sa.func.now())
        )
        return True

    async def mark_finalizing(
        self,
        attempt_id: UUID,
        *,
        lease_owner: str,
    ) -> bool:
        pair = await self._lock_current_attempt(attempt_id)
        if pair is None:
            return False
        attempt, run = pair
        now = await self._database_now()
        if not self._lease_is_current(attempt, lease_owner=lease_owner, now=now):
            return False
        if run.phase != CrawlPhase.RUNNING.value:
            return False
        run.phase = CrawlPhase.FINALIZING.value
        await self.session.flush()
        return True

    async def lock_attempt_lease(
        self,
        attempt_id: UUID,
        *,
        lease_owner: str,
        expected_phase: CrawlPhase,
    ) -> bool:
        """Fence a crawl mutation to the current worker for this transaction."""
        pair = await self._lock_current_attempt(attempt_id)
        if pair is None:
            return False
        attempt, run = pair
        now = await self._database_now()
        return bool(
            run.phase == expected_phase.value
            and self._lease_is_current(
                attempt,
                lease_owner=lease_owner,
                now=now,
            )
        )

    async def finish_attempt(
        self,
        attempt_id: UUID,
        *,
        lease_owner: str,
        outcome: CrawlOutcome,
        failure_code: CrawlFailureCode | None = None,
        failure_detail: str | None = None,
        result_location: str | None = None,
        pages_crawled: int | None = None,
        files_downloaded: int | None = None,
        pages_failed: int | None = None,
        files_failed: int | None = None,
        failure_summary: dict[str, int] | None = None,
        failures: Sequence[CrawlResourceFailure] = (),
    ) -> bool:
        code = self._validate_terminal_facts(
            outcome,
            failure_code,
            failure_detail,
        )
        counters = (
            pages_crawled,
            files_downloaded,
            pages_failed,
            files_failed,
        )
        if any(value is not None and value < 0 for value in counters):
            raise ValueError("Crawl counters cannot be negative")

        pair = await self._lock_current_attempt(attempt_id)
        if pair is None:
            return False
        attempt, run = pair
        now = await self._database_now()
        if outcome == CrawlOutcome.CANCELLED:
            phase_allows_finish = (
                run.phase == CrawlPhase.STOPPING.value
                and run.cancel_requested_at is not None
            )
        else:
            phase_allows_finish = run.phase in {
                CrawlPhase.RUNNING.value,
                CrawlPhase.FINALIZING.value,
            }
        if not phase_allows_finish or not self._lease_is_current(
            attempt,
            lease_owner=lease_owner,
            now=now,
        ):
            return False

        detail = failure_detail[:512] if failure_detail else None
        self._finish_records(
            attempt,
            run,
            outcome=outcome,
            finished_at=now,
            failure_code=code,
            failure_detail=detail,
            result_location=result_location,
        )
        if pages_crawled is not None:
            run.pages_crawled = pages_crawled
        if files_downloaded is not None:
            run.files_downloaded = files_downloaded
        if pages_failed is not None:
            run.pages_failed = pages_failed
        if files_failed is not None:
            run.files_failed = files_failed
        if failure_summary is not None:
            run.failure_summary = failure_summary
        await self._record_failures(run.id, failures)
        if outcome in _SUCCESSFUL_OUTCOMES:
            await self.session.execute(
                sa.update(WebsitesTable)
                .where(
                    WebsitesTable.id == run.website_id,
                    WebsitesTable.tenant_id == run.tenant_id,
                )
                .values(last_indexed_at=now)
            )
        await self._project_job_terminal(
            attempt.dispatch_id,
            outcome=outcome,
            finished_at=now,
            failure_code=code,
            failure_detail=detail,
            result_location=result_location,
        )
        await self.session.flush()
        return True

    async def interrupt_expired_attempts(self) -> int:
        now = await self._database_now()
        rows = (
            await self.session.execute(
                sa.select(CrawlAttempts, CrawlRunsTable)
                .join(CrawlRunsTable, CrawlRunsTable.id == CrawlAttempts.crawl_run_id)
                .where(CrawlAttempts.finished_at.is_(None))
                .where(CrawlAttempts.lease_expires_at < now)
                .where(CrawlRunsTable.phase != CrawlPhase.TERMINAL.value)
                .where(CrawlRunsTable.attempt_count == CrawlAttempts.attempt_number)
                .order_by(CrawlAttempts.lease_expires_at.asc(), CrawlAttempts.id.asc())
                .limit(LEASE_SWEEP_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for attempt, run in rows:
            cancellation_was_requested = bool(
                run.phase == CrawlPhase.STOPPING.value
                and run.cancel_requested_at is not None
            )
            outcome = (
                CrawlOutcome.CANCELLED
                if cancellation_was_requested
                else CrawlOutcome.INTERRUPTED
            )
            failure_code = (
                CrawlFailureCode.CANCELLED.value
                if cancellation_was_requested
                else CrawlFailureCode.LEASE_EXPIRED.value
            )
            detail = (
                "The crawl was stopped by a user"
                if cancellation_was_requested
                else "Crawler worker lease expired before completion"
            )
            self._finish_records(
                attempt,
                run,
                outcome=outcome,
                finished_at=now,
                failure_code=failure_code,
                failure_detail=detail,
                result_location=None,
            )
            await self._project_job_terminal(
                attempt.dispatch_id,
                outcome=outcome,
                finished_at=now,
                failure_code=failure_code,
                failure_detail=detail,
                result_location=None,
            )
        await self.session.flush()
        return len(rows)

    async def pending_transport_cleanup_candidates(self) -> tuple[UUID, ...]:
        dispatch_ids = await self.session.scalars(
            sa.select(CrawlAttempts.dispatch_id)
            .where(_PENDING_TRANSPORT_CLEANUP)
            .order_by(CrawlAttempts.finished_at.asc(), CrawlAttempts.id.asc())
            .limit(LEASE_SWEEP_BATCH_SIZE)
        )
        return tuple(dispatch_ids.all())

    async def acknowledge_transport_cleanup(
        self,
        dispatch_ids: tuple[UUID, ...],
    ) -> None:
        if not dispatch_ids:
            return
        await self.session.execute(
            sa.update(CrawlAttempts)
            .where(CrawlAttempts.dispatch_id.in_(dispatch_ids))
            .where(_PENDING_TRANSPORT_CLEANUP)
            .values(transport_cleaned_at=sa.func.now())
        )

    async def _lock_current_attempt(
        self,
        attempt_id: UUID,
    ) -> tuple[CrawlAttempts, CrawlRunsTable] | None:
        row = (
            await self.session.execute(
                sa.select(CrawlAttempts, CrawlRunsTable)
                .join(CrawlRunsTable, CrawlRunsTable.id == CrawlAttempts.crawl_run_id)
                .where(CrawlAttempts.id == attempt_id)
                .where(CrawlRunsTable.attempt_count == CrawlAttempts.attempt_number)
                .with_for_update()
            )
        ).one_or_none()
        return (row[0], row[1]) if row is not None else None

    @staticmethod
    def _validate_execution(
        attempt: CrawlAttempts,
        run: CrawlRunsTable,
        *,
        task: CrawlTask,
    ) -> None:
        if (
            task.attempt_id != attempt.id
            or task.attempt_number != attempt.attempt_number
            or task.run_id != run.id
            or task.website_id != run.website_id
            or task.origin.value != run.origin
        ):
            raise ValueError("Crawl execution payload does not match persisted state")

    @staticmethod
    def _lease_is_current(
        attempt: CrawlAttempts,
        *,
        lease_owner: str,
        now: datetime,
    ) -> bool:
        return bool(
            attempt.finished_at is None
            and attempt.lease_owner == lease_owner
            and attempt.lease_expires_at is not None
            and attempt.lease_expires_at > now
        )

    @staticmethod
    def _validate_terminal_facts(
        outcome: CrawlOutcome,
        failure_code: CrawlFailureCode | None,
        failure_detail: str | None,
    ) -> str | None:
        code = failure_code.value if failure_code is not None else None
        if outcome in _CLEAN_OUTCOMES and (
            code is not None or failure_detail is not None
        ):
            raise ValueError("Clean crawl outcomes cannot have failure details")
        if outcome not in _CLEAN_OUTCOMES and code is None:
            raise ValueError("Non-clean crawl outcomes require a failure code")
        return code

    @staticmethod
    def _finish_records(
        attempt: CrawlAttempts,
        run: CrawlRunsTable,
        *,
        outcome: CrawlOutcome,
        finished_at: datetime,
        failure_code: str | None,
        failure_detail: str | None,
        result_location: str | None,
    ) -> None:
        attempt.finished_at = finished_at
        attempt.failure_code = failure_code
        attempt.failure_detail = failure_detail
        attempt.lease_owner = None
        attempt.lease_expires_at = None
        run.phase = CrawlPhase.TERMINAL.value
        run.outcome = outcome.value
        run.finished_at = finished_at
        run.failure_code = failure_code
        run.failure_detail = failure_detail
        run.result_location = result_location

    async def _project_job_terminal(
        self,
        dispatch_id: UUID,
        *,
        outcome: CrawlOutcome,
        finished_at: datetime,
        failure_code: str | None,
        failure_detail: str | None,
        result_location: str | None,
    ) -> None:
        successful = outcome in _SUCCESSFUL_OUTCOMES
        await self.session.execute(
            sa.update(Jobs)
            .where(Jobs.id == dispatch_id)
            .values(
                status=(Status.COMPLETE if successful else Status.FAILED).value,
                finished_at=finished_at,
                failure_code=failure_code,
                result_location=result_location if successful else failure_detail,
                updated_at=finished_at,
            )
        )

    async def _database_now(self) -> datetime:
        now = await self.session.scalar(sa.select(sa.func.now()))
        assert isinstance(now, datetime)
        return now
