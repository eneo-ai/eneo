from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.websites_table import CrawlRuns as CrawlRunsTable
from eneo.database.tables.websites_table import Websites as WebsitesTable
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.websites.domain.crawl_run import CrawlPhase, CrawlRun
from eneo.websites.domain.crawl_schedule import (
    SCHEDULE_INTERVALS,
    WEEKLY_CRAWL_WEEKDAY,
    ScheduleProjection,
    compute_schedule,
)
from eneo.websites.domain.website import UpdateInterval, WebsiteSparse

if TYPE_CHECKING:
    from eneo.database.database import AsyncSession


@dataclass(frozen=True, slots=True)
class RelatedWebsite:
    website_id: UUID
    website_name: str | None
    website_url: str
    space_id: UUID | None
    space_name: str | None
    indexed_size: int
    last_indexed_at: datetime | None
    latest_run_id: UUID | None


@dataclass(frozen=True, slots=True)
class RelatedWebsitePage:
    items: list[RelatedWebsite]
    next_cursor: UUID | None


ScheduleFilter = Literal["due", "waiting", "blocked"]
ScheduledSort = Literal["next_due", "last_crawled", "url"]


@dataclass(frozen=True, slots=True)
class ScheduledWebsite:
    website_id: UUID
    website_name: str | None
    website_url: str
    space_id: UUID | None
    space_name: str | None
    update_interval: UpdateInterval
    last_crawled_at: datetime | None
    last_indexed_at: datetime | None
    consecutive_failures: int
    next_retry_at: datetime | None
    latest_run: CrawlRun | None
    active_run_id: UUID | None
    schedule: ScheduleProjection


@dataclass(frozen=True, slots=True)
class ScheduledWebsitePage:
    items: list[ScheduledWebsite]
    total_count: int
    next_cursor: UUID | None


def _scheduled_interval() -> sa.ColumnElement[bool]:
    """Websites that have an automatic crawl interval at all."""
    return WebsitesTable.update_interval.in_(
        [interval.value for interval in SCHEDULE_INTERVALS]
    )


def _interval_elapsed(now: datetime, today: date) -> sa.ColumnElement[bool]:
    """Interval since the last crawl has passed, or the site was never crawled.

    Weekly websites only qualify on Fridays. Written as an OR of per-interval
    branches so the (update_interval, last_crawled_at) index stays usable.
    """
    branches: list[sa.ColumnElement[bool]] = []
    for interval, delta in SCHEDULE_INTERVALS.items():
        if (
            interval is UpdateInterval.WEEKLY
            and today.weekday() != WEEKLY_CRAWL_WEEKDAY
        ):
            continue
        branches.append(
            sa.and_(
                WebsitesTable.update_interval == interval.value,
                sa.or_(
                    WebsitesTable.last_crawled_at.is_(None),
                    WebsitesTable.last_crawled_at <= now - delta,
                ),
            )
        )
    return sa.or_(*branches) if branches else sa.false()


def _backoff_clear(now: datetime) -> sa.ColumnElement[bool]:
    """Circuit breaker is idle: no failures recorded, or the backoff has passed."""
    return sa.or_(
        WebsitesTable.next_retry_at.is_(None), WebsitesTable.next_retry_at <= now
    )


def _active_run_exists() -> sa.ColumnElement[bool]:
    """A non-terminal crawl run holds the website; crawl_runs is authoritative."""
    return sa.exists(
        sa.select(sa.literal(1))
        .select_from(CrawlRunsTable)
        .where(
            CrawlRunsTable.website_id == WebsitesTable.id,
            CrawlRunsTable.phase != CrawlPhase.TERMINAL.value,
        )
    )


def _interval_due_at() -> sa.ColumnElement[datetime]:
    """When the crawl interval elapses, as a stable sort key.

    Never-crawled websites fall back to their registration time rather than
    ``now`` so keyset pagination sees the same value on every page.
    """
    interval = sa.case(
        *[
            (
                WebsitesTable.update_interval == update_interval.value,
                sa.literal(delta, type_=sa.Interval()),
            )
            for update_interval, delta in SCHEDULE_INTERVALS.items()
        ],
        else_=sa.null(),
    )
    return sa.func.coalesce(
        WebsitesTable.last_crawled_at + interval, WebsitesTable.created_at
    )


class WebsiteSparseRepository:
    def __init__(self, session: "AsyncSession"):
        super().__init__()
        self.session = session

    async def one_for_tenant(self, id: UUID, tenant_id: UUID) -> WebsiteSparse:
        record = await self.session.scalar(
            sa.select(WebsitesTable).where(
                WebsitesTable.id == id, WebsitesTable.tenant_id == tenant_id
            )
        )
        if record is None:
            raise NotFoundException()
        return WebsiteSparse.to_domain(record)

    async def same_address(
        self, website: WebsiteSparse, *, limit: int = 10, cursor: UUID | None = None
    ) -> RelatedWebsitePage:
        if not 1 <= limit <= 100:
            raise BadRequestException("Page size must be between 1 and 100")
        latest_run = (
            sa.select(CrawlRunsTable.id)
            .where(
                CrawlRunsTable.website_id == WebsitesTable.id,
                CrawlRunsTable.tenant_id == website.tenant_id,
            )
            .order_by(CrawlRunsTable.created_at.desc(), CrawlRunsTable.id.desc())
            .limit(1)
            .correlate(WebsitesTable)
            .scalar_subquery()
        )
        # Match registration addresses exactly, as the existing organization
        # lookup does. This is not a claim that their indexed content is equal.
        query = (
            sa.select(
                WebsitesTable.id,
                WebsitesTable.name,
                WebsitesTable.url,
                WebsitesTable.space_id,
                Spaces.name.label("space_name"),
                WebsitesTable.size,
                WebsitesTable.last_indexed_at,
                latest_run,
            )
            .outerjoin(
                Spaces,
                sa.and_(
                    Spaces.id == WebsitesTable.space_id,
                    Spaces.tenant_id == website.tenant_id,
                ),
            )
            .where(
                WebsitesTable.tenant_id == website.tenant_id,
                WebsitesTable.url == website.url,
                WebsitesTable.id != website.id,
            )
            .order_by(WebsitesTable.id)
            .limit(limit + 1)
        )
        if cursor is not None:
            query = query.where(WebsitesTable.id > cursor)
        rows = (await self.session.execute(query)).all()
        items = [RelatedWebsite(*row) for row in rows[:limit]]
        return RelatedWebsitePage(
            items=items, next_cursor=items[-1].website_id if len(rows) > limit else None
        )

    async def scheduled_for_tenant(
        self,
        tenant_id: UUID,
        *,
        as_of: datetime,
        search: str = "",
        interval: UpdateInterval | None = None,
        state: ScheduleFilter | None = None,
        sort: ScheduledSort = "next_due",
        limit: int = 50,
        cursor: UUID | None = None,
    ) -> ScheduledWebsitePage:
        """Page through a tenant's websites with their scheduling state.

        ``interval=None`` lists every website with an automatic interval;
        ``UpdateInterval.NEVER`` lists the disabled ones instead. The state
        filter uses the same predicates as the scheduler query, and each row
        is projected with ``compute_schedule`` at ``as_of``.
        """
        if not 1 <= limit <= 100:
            raise BadRequestException("Page size must be between 1 and 100")
        today = as_of.astimezone(timezone.utc).date()
        interval_due_at = _interval_due_at()

        conditions: list[sa.ColumnElement[bool]] = [
            WebsitesTable.tenant_id == tenant_id
        ]
        if interval is None:
            conditions.append(_scheduled_interval())
        else:
            conditions.append(WebsitesTable.update_interval == interval.value)
        elapsed = _interval_elapsed(as_of, today)
        active = _active_run_exists()
        if state == "due":
            conditions += [
                _scheduled_interval(),
                elapsed,
                ~active,
                _backoff_clear(as_of),
            ]
        elif state == "waiting":
            conditions += [_scheduled_interval(), ~elapsed]
        elif state == "blocked":
            conditions += [
                _scheduled_interval(),
                elapsed,
                sa.or_(active, WebsitesTable.next_retry_at > as_of),
            ]
        term = search.strip()
        if term:
            conditions.append(
                sa.or_(
                    WebsitesTable.name.icontains(term, autoescape=True),
                    WebsitesTable.url.icontains(term, autoescape=True),
                )
            )

        total_count = await self.session.scalar(
            sa.select(sa.func.count()).select_from(WebsitesTable).where(*conditions)
        )

        sort_key: sa.ColumnElement[Any]
        if sort == "next_due":
            sort_key, descending = interval_due_at, False
        elif sort == "last_crawled":
            sort_key = sa.func.coalesce(
                WebsitesTable.last_crawled_at, WebsitesTable.created_at
            )
            descending = True
        else:
            sort_key = sa.type_coerce(WebsitesTable.url, sa.String())
            descending = False

        latest_run = aliased(
            CrawlRunsTable,
            sa.select(CrawlRunsTable)
            .where(
                CrawlRunsTable.website_id == WebsitesTable.id,
                CrawlRunsTable.tenant_id == tenant_id,
            )
            .order_by(CrawlRunsTable.created_at.desc(), CrawlRunsTable.id.desc())
            .limit(1)
            .correlate(WebsitesTable)
            .lateral("latest_run"),
        )
        active_run_id = (
            sa.select(CrawlRunsTable.id)
            .where(
                CrawlRunsTable.website_id == WebsitesTable.id,
                CrawlRunsTable.phase != CrawlPhase.TERMINAL.value,
            )
            .limit(1)
            .correlate(WebsitesTable)
            .scalar_subquery()
        )
        query = (
            sa.select(
                WebsitesTable.id,
                WebsitesTable.name,
                WebsitesTable.url,
                WebsitesTable.space_id,
                Spaces.name.label("space_name"),
                WebsitesTable.update_interval,
                WebsitesTable.last_crawled_at,
                WebsitesTable.last_indexed_at,
                WebsitesTable.consecutive_failures,
                WebsitesTable.next_retry_at,
                interval_due_at.label("interval_due_at"),
                active_run_id.label("active_run_id"),
                latest_run,
            )
            .outerjoin(
                Spaces,
                sa.and_(
                    Spaces.id == WebsitesTable.space_id,
                    Spaces.tenant_id == tenant_id,
                ),
            )
            .outerjoin(latest_run, sa.true())
            .where(*conditions)
            .limit(limit + 1)
        )
        if cursor is not None:
            anchor = (
                await self.session.execute(
                    sa.select(sort_key).where(
                        WebsitesTable.id == cursor,
                        WebsitesTable.tenant_id == tenant_id,
                    )
                )
            ).one_or_none()
            if anchor is None:
                raise BadRequestException("Invalid scheduled website cursor")
            position = sa.tuple_(sort_key, WebsitesTable.id)
            boundary = sa.tuple_(sa.literal(anchor[0]), sa.literal(cursor))
            query = query.where(
                position < boundary if descending else position > boundary
            )
        if descending:
            query = query.order_by(sort_key.desc(), WebsitesTable.id.desc())
        else:
            query = query.order_by(sort_key, WebsitesTable.id)

        rows = (await self.session.execute(query)).all()
        items: list[ScheduledWebsite] = []
        for row in rows[:limit]:
            (
                website_id,
                name,
                url,
                space_id,
                space_name,
                update_interval,
                last_crawled_at,
                last_indexed_at,
                consecutive_failures,
                next_retry_at,
                due_at,
                run_id,
                latest,
            ) = row
            update_interval = UpdateInterval(update_interval)
            items.append(
                ScheduledWebsite(
                    website_id=website_id,
                    website_name=name,
                    website_url=url,
                    space_id=space_id,
                    space_name=space_name,
                    update_interval=update_interval,
                    last_crawled_at=last_crawled_at,
                    last_indexed_at=last_indexed_at,
                    consecutive_failures=consecutive_failures,
                    next_retry_at=next_retry_at,
                    latest_run=CrawlRun.to_domain(latest)
                    if latest is not None
                    else None,
                    active_run_id=run_id,
                    schedule=compute_schedule(
                        update_interval=update_interval,
                        interval_due_at=due_at,
                        next_retry_at=next_retry_at,
                        has_active_run=run_id is not None,
                        consecutive_failures=consecutive_failures,
                        now=as_of,
                    ),
                )
            )
        return ScheduledWebsitePage(
            items=items,
            total_count=total_count or 0,
            next_cursor=items[-1].website_id if len(rows) > limit else None,
        )

    async def get_weekly_websites(self) -> list[WebsiteSparse]:
        """Get websites with weekly update intervals.

        Why: Preserves existing API for backwards compatibility.
        Deprecated: Use get_websites_with_intervals() with scheduler service instead.
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

    async def get_due_websites(self, today: date) -> list[WebsiteSparse]:
        """Websites the scheduler should admit right now.

        Filtering happens in the database so the hourly cron stays cheap with
        thousands of websites. The rules live in ``crawl_schedule`` and are
        shared with the admin schedule listing.

        Args:
            today: UTC date, which decides whether weekly websites qualify.
        """
        now_utc = datetime.now(timezone.utc)
        stmt = sa.select(WebsitesTable).where(
            _interval_elapsed(now_utc, today),
            _backoff_clear(now_utc),
            ~_active_run_exists(),
        )
        websites_db = await self.session.scalars(stmt)
        return [WebsiteSparse.to_domain(website_db) for website_db in websites_db]
