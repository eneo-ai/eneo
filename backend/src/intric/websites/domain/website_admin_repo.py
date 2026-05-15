from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa

from intric.database.tables.tenant_table import Tenants
from intric.database.tables.websites_table import Websites as WebsitesTable
from intric.websites.domain.crawler_failure_inventory import (
    CrawlerFailureInventory,
    CrawlerFailureInventoryItem,
    CrawlerFailureState,
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
