from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa

from intric.database.tables.job_table import Jobs
from intric.database.tables.websites_table import CrawlRuns as CrawlRunsTable
from intric.database.tables.websites_table import Websites as WebsitesTable
from intric.main.models import Status
from intric.websites.domain.website import UpdateInterval, WebsiteSparse

if TYPE_CHECKING:
    from intric.database.database import AsyncSession


class WebsiteSparseRepository:
    def __init__(self, session: "AsyncSession"):
        super().__init__()
        self.session = session

    async def get_due_websites(self, as_of: datetime) -> list[WebsiteSparse]:
        """Get websites that are due for crawling based on their update_interval.

        Why: Push filtering to database for better performance with 1000+ websites.
        Uses composite index on (update_interval, last_crawled_at) for efficiency.

        Args:
            as_of: Current scheduler timestamp for interval calculation

        Returns:
            List of websites due for crawling
        """
        # Calculate threshold timestamps using rolling window from current time
        # Why: Use actual elapsed time, not midnight-to-midnight boundaries
        # This ensures websites are scheduled ~24h after last crawl, not at next midnight
        one_day_ago = as_of - timedelta(days=1)
        two_days_ago = as_of - timedelta(days=2)
        seven_days_ago = as_of - timedelta(days=7)

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
        is_friday = as_of.date().weekday() == 4  # 0=Monday, 4=Friday
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
            WebsitesTable.next_retry_at <= as_of,
        )

        # Active job condition: Skip websites that already have queued/in-progress crawls
        # Why: Prevent duplicate scheduled crawls while a crawl is running or queued
        active_job_statuses = [Status.QUEUED.value, Status.IN_PROGRESS.value]
        active_job_exists = (
            sa.select(sa.literal(1))
            .select_from(CrawlRunsTable)
            .join(Jobs, Jobs.id == CrawlRunsTable.job_id)
            .where(
                CrawlRunsTable.website_id == WebsitesTable.id,
                Jobs.status.in_(active_job_statuses),
            )
        )
        cond_no_active_jobs = ~sa.exists(active_job_exists)

        # Combine all conditions with circuit breaker
        stmt = sa.select(WebsitesTable).where(
            sa.and_(
                sa.or_(cond_daily, cond_every_other_day, cond_weekly),
                cond_circuit_breaker,
                cond_no_active_jobs,
            )
        )

        websites_db = await self.session.scalars(stmt)
        return [WebsiteSparse.to_domain(website_db) for website_db in websites_db]

    async def get_for_tenant(
        self,
        *,
        website_id: UUID,
        tenant_id: UUID,
    ) -> WebsiteSparse | None:
        """Tenant-scoped read of one `WebsiteSparse` by id.

        Used by the retry-now admin endpoint to load the website in a
        shape `CrawlService.crawl(website)` accepts (which expects the
        `CrawlableWebsite = Website | WebsiteSparse` domain Protocol).
        The `tenant_id` filter is required — admin permission is
        tenant-wide, not space-wide, so the SQL gate is the canonical
        isolation seam.
        """
        stmt = (
            sa.select(WebsitesTable)
            .where(WebsitesTable.id == website_id)
            .where(WebsitesTable.tenant_id == tenant_id)
        )
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        return WebsiteSparse.to_domain(row)
