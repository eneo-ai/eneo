from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa

from intric.database.tables.tenant_table import Tenants
from intric.database.tables.websites_table import Websites as WebsitesTable
from intric.websites.domain.crawl_circuit_reset import (
    CrawlCircuitResetNotFound,
    CrawlCircuitResetPreviousState,
    CrawlCircuitResetResult,
    CrawlCircuitResetSucceeded,
    CrawlCircuitResetWebsite,
)
from intric.websites.domain.crawler_failure_inventory import (
    CrawlerFailureInventory,
    CrawlerFailureInventoryItem,
    CrawlerFailureState,
)
from intric.websites.domain.crawler_scheduled_aggregate import (
    CrawlerScheduledAggregate,
    CrawlerScheduledIntervalBucket,
)
from intric.websites.domain.website import (
    WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    UpdateInterval,
)

if TYPE_CHECKING:
    from intric.database.database import AsyncSession


class WebsiteAdminRepository:
    def __init__(self, session: "AsyncSession"):
        self.session = session

    async def crawler_failure_inventory(
        self,
        *,
        limit: int,
        offset: int,
        tenant_id: UUID | None,
    ) -> CrawlerFailureInventory:
        return await self._crawler_failure_inventory(
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
        )

    async def crawler_failure_inventory_for_tenant(
        self,
        *,
        limit: int,
        offset: int,
        tenant_id: UUID,
    ) -> CrawlerFailureInventory:
        return await self._crawler_failure_inventory(
            limit=limit,
            offset=offset,
            tenant_id=tenant_id,
        )

    async def _crawler_failure_inventory(
        self,
        *,
        limit: int,
        offset: int,
        tenant_id: UUID | None,
    ) -> CrawlerFailureInventory:
        auto_disabled_condition = sa.and_(
            WebsitesTable.update_interval == UpdateInterval.NEVER,
            WebsitesTable.consecutive_failures
            >= WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
        )
        backed_off_condition = sa.and_(
            WebsitesTable.consecutive_failures > 0,
            WebsitesTable.next_retry_at.is_not(None),
            WebsitesTable.update_interval != UpdateInterval.NEVER,
        )
        failure_state = sa.case(
            (auto_disabled_condition, CrawlerFailureState.AUTO_DISABLED.value),
            (backed_off_condition, CrawlerFailureState.BACKED_OFF.value),
        ).label("failure_state")
        failure_conditions = [sa.or_(auto_disabled_condition, backed_off_condition)]
        if tenant_id is not None:
            failure_conditions.append(WebsitesTable.tenant_id == tenant_id)

        total_stmt = (
            sa.select(sa.func.count(WebsitesTable.id))
            .select_from(WebsitesTable)
            .where(*failure_conditions)
        )
        total = int(await self.session.scalar(total_stmt) or 0)

        rows_from = sa.outerjoin(
            WebsitesTable,
            Tenants,
            WebsitesTable.tenant_id == Tenants.id,
        )
        rows_stmt = (
            sa.select(
                WebsitesTable.id.label("website_id"),
                WebsitesTable.url.label("website_url"),
                WebsitesTable.name.label("website_name"),
                WebsitesTable.tenant_id.label("tenant_id"),
                Tenants.display_name.label("tenant_display_name"),
                failure_state,
                WebsitesTable.update_interval.label("update_interval"),
                WebsitesTable.consecutive_failures.label("consecutive_failures"),
                WebsitesTable.next_retry_at.label("next_retry_at"),
                WebsitesTable.last_crawled_at.label("last_crawled_at"),
                WebsitesTable.updated_at.label("updated_at"),
            )
            .select_from(rows_from)
            .where(*failure_conditions)
            .order_by(
                WebsitesTable.consecutive_failures.desc(),
                WebsitesTable.updated_at.desc(),
                WebsitesTable.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(rows_stmt)
        items: list[CrawlerFailureInventoryItem] = []
        for row in result.mappings():
            update_interval = UpdateInterval(str(row["update_interval"]))
            consecutive_failures = int(row["consecutive_failures"])
            failure_state_value = row["failure_state"]
            if failure_state_value is None:
                raise RuntimeError("Crawler failure inventory row has no failure state")
            items.append(
                CrawlerFailureInventoryItem(
                    website_id=row["website_id"],
                    website_url=str(row["website_url"]),
                    website_name=row["website_name"],
                    tenant_id=row["tenant_id"],
                    tenant_display_name=row["tenant_display_name"],
                    state=CrawlerFailureState(str(failure_state_value)),
                    update_interval=update_interval,
                    consecutive_failures=consecutive_failures,
                    next_retry_at=row["next_retry_at"],
                    last_crawled_at=row["last_crawled_at"],
                    updated_at=row["updated_at"],
                )
            )

        return CrawlerFailureInventory(
            items=tuple(items),
            total=total,
            limit=limit,
            offset=offset,
        )

    async def scheduled_aggregate_for_tenant(
        self,
        *,
        tenant_id: UUID,
    ) -> CrawlerScheduledAggregate:
        return await self._scheduled_aggregate(tenant_id=tenant_id)

    async def scheduled_aggregate_for_sysadmin(
        self,
        *,
        tenant_id: UUID | None,
    ) -> CrawlerScheduledAggregate:
        return await self._scheduled_aggregate(tenant_id=tenant_id)

    async def _scheduled_aggregate(
        self,
        *,
        tenant_id: UUID | None,
    ) -> CrawlerScheduledAggregate:
        stmt = (
            sa.select(
                WebsitesTable.update_interval.label("update_interval"),
                sa.func.count(WebsitesTable.id).label("website_count"),
                sa.func.coalesce(sa.func.sum(WebsitesTable.size), 0).label(
                    "total_size_bytes"
                ),
            )
            .select_from(WebsitesTable)
            .group_by(WebsitesTable.update_interval)
        )
        if tenant_id is not None:
            stmt = stmt.where(WebsitesTable.tenant_id == tenant_id)

        result = await self.session.execute(stmt)

        counts_by_interval = {update_interval: 0 for update_interval in UpdateInterval}
        sizes_by_interval = {update_interval: 0 for update_interval in UpdateInterval}
        unparseable_update_interval_website_count = 0
        unparseable_update_interval_total_size_bytes = 0
        for row in result.mappings():
            website_count = int(row["website_count"])
            total_size_bytes = int(row["total_size_bytes"])
            try:
                update_interval = UpdateInterval(str(row["update_interval"]))
            except ValueError:
                unparseable_update_interval_website_count += website_count
                unparseable_update_interval_total_size_bytes += total_size_bytes
                continue

            counts_by_interval[update_interval] = website_count
            sizes_by_interval[update_interval] = total_size_bytes

        buckets = tuple(
            CrawlerScheduledIntervalBucket(
                update_interval=update_interval,
                website_count=counts_by_interval[update_interval],
                total_size_bytes=sizes_by_interval[update_interval],
            )
            for update_interval in sorted(UpdateInterval, key=lambda item: item.value)
        )

        return CrawlerScheduledAggregate(
            buckets=buckets,
            total_websites=(
                sum(bucket.website_count for bucket in buckets)
                + unparseable_update_interval_website_count
            ),
            total_size_bytes=(
                sum(bucket.total_size_bytes for bucket in buckets)
                + unparseable_update_interval_total_size_bytes
            ),
            unparseable_update_interval_website_count=(
                unparseable_update_interval_website_count
            ),
            unparseable_update_interval_total_size_bytes=(
                unparseable_update_interval_total_size_bytes
            ),
            tenant_id=tenant_id,
        )

    async def reset_crawl_circuit_breaker_for_tenant(
        self,
        *,
        website_id: UUID,
        tenant_id: UUID,
    ) -> CrawlCircuitResetResult:
        """Clear circuit-breaker counters for one website inside the tenant scope.

        Why: Operators currently recover from backed-off or auto-disabled websites
        only by editing the database directly. This method commits the same fields
        the worker reactor writes on a successful crawl, scoped strictly to one
        tenant, so the caller can replace DB surgery with a typed audited action.
        update_interval is intentionally untouched — a separate website-edit flow
        owns scheduling decisions for previously auto-disabled rows.
        """
        select_stmt = (
            sa.select(
                WebsitesTable.id,
                WebsitesTable.name,
                WebsitesTable.url,
                WebsitesTable.update_interval,
                WebsitesTable.consecutive_failures,
                WebsitesTable.next_retry_at,
            )
            .where(WebsitesTable.id == website_id)
            .where(WebsitesTable.tenant_id == tenant_id)
        )
        row = (await self.session.execute(select_stmt)).first()
        if row is None:
            return CrawlCircuitResetNotFound(website_id=website_id)

        previous_state = _classify_circuit_breaker_state(
            update_interval=UpdateInterval(str(row.update_interval)),
            consecutive_failures=int(row.consecutive_failures),
            next_retry_at=row.next_retry_at,
        )

        update_stmt = (
            sa.update(WebsitesTable)
            .where(WebsitesTable.id == website_id)
            .where(WebsitesTable.tenant_id == tenant_id)
            .values(consecutive_failures=0, next_retry_at=None)
        )
        await self.session.execute(update_stmt)

        display_name = row.name if row.name is not None else row.url
        return CrawlCircuitResetSucceeded(
            website=CrawlCircuitResetWebsite(
                id=row.id,
                name=str(display_name),
            ),
            previous_state=previous_state,
            previous_consecutive_failures=int(row.consecutive_failures),
            previous_next_retry_at=row.next_retry_at,
        )


def _classify_circuit_breaker_state(
    *,
    update_interval: UpdateInterval,
    consecutive_failures: int,
    next_retry_at: object | None,
) -> CrawlCircuitResetPreviousState:
    """Mirror the failure-inventory classifier so audit metadata matches the UI."""
    is_auto_disabled = (
        update_interval == UpdateInterval.NEVER
        and consecutive_failures >= WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD
    )
    if is_auto_disabled:
        return CrawlCircuitResetPreviousState.AUTO_DISABLED

    is_backed_off = (
        consecutive_failures > 0
        and next_retry_at is not None
        and update_interval != UpdateInterval.NEVER
    )
    if is_backed_off:
        return CrawlCircuitResetPreviousState.BACKED_OFF

    return CrawlCircuitResetPreviousState.HEALTHY
