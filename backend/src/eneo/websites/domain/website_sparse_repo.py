from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa

from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.websites_table import CrawlRuns as CrawlRunsTable
from eneo.database.tables.websites_table import Websites as WebsitesTable
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.websites.domain.crawl_run import CrawlPhase
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
        """Get websites that are due for crawling based on their update_interval.

        Why: Push filtering to database for better performance with 1000+ websites.
        Uses composite index on (update_interval, last_crawled_at) for efficiency.

        Args:
            today: Current date for schedule calculation

        Returns:
            List of websites due for crawling
        """
        # Calculate threshold timestamps using rolling window from current time
        # Why: Use actual elapsed time, not midnight-to-midnight boundaries
        # This ensures websites are scheduled ~24h after last crawl, not at next midnight
        now_utc = datetime.now(timezone.utc)
        one_day_ago = now_utc - timedelta(days=1)
        two_days_ago = now_utc - timedelta(days=2)
        seven_days_ago = now_utc - timedelta(days=7)

        # DAILY: crawl if last_crawled_at is NULL or >= 1 day ago
        cond_daily = sa.and_(
            WebsitesTable.update_interval == UpdateInterval.DAILY,
            sa.or_(
                WebsitesTable.last_crawled_at.is_(None),
                WebsitesTable.last_crawled_at <= one_day_ago,
            ),
        )

        # EVERY_OTHER_DAY: crawl if NULL or >= 2 days ago
        cond_every_other_day = sa.and_(
            WebsitesTable.update_interval == UpdateInterval.EVERY_OTHER_DAY,
            sa.or_(
                WebsitesTable.last_crawled_at.is_(None),
                WebsitesTable.last_crawled_at <= two_days_ago,
            ),
        )

        # WEEKLY: only on Fridays AND >= 7 days ago (or never crawled)
        is_friday = today.weekday() == 4  # 0=Monday, 4=Friday
        if is_friday:
            cond_weekly = sa.and_(
                WebsitesTable.update_interval == UpdateInterval.WEEKLY,
                sa.or_(
                    WebsitesTable.last_crawled_at.is_(None),
                    WebsitesTable.last_crawled_at <= seven_days_ago,
                ),
            )
        else:
            # Not Friday - no weekly websites are due
            cond_weekly = sa.literal(False)

        # Circuit breaker condition: Only crawl sites that are not in backoff period
        # Why: Prevent wasted resources on persistently failing websites
        # NULL = no failures, non-NULL = backoff until this time
        cond_circuit_breaker = sa.or_(
            WebsitesTable.next_retry_at.is_(None),
            WebsitesTable.next_retry_at <= now_utc,
        )

        # CrawlRuns is authoritative even when the compatibility Job is missing.
        active_crawl_exists = (
            sa.select(sa.literal(1))
            .select_from(CrawlRunsTable)
            .where(
                CrawlRunsTable.website_id == WebsitesTable.id,
                CrawlRunsTable.phase != CrawlPhase.TERMINAL.value,
            )
        )
        cond_no_active_crawl = ~sa.exists(active_crawl_exists)

        # Combine all conditions with circuit breaker
        stmt = sa.select(WebsitesTable).where(
            sa.and_(
                sa.or_(cond_daily, cond_every_other_day, cond_weekly),
                cond_circuit_breaker,
                cond_no_active_crawl,
            )
        )

        websites_db = await self.session.scalars(stmt)
        return [WebsiteSparse.to_domain(website_db) for website_db in websites_db]
