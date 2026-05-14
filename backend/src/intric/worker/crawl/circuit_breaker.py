from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.websites_table import Websites as WebsitesTable
from intric.main.logging import get_logger
from intric.websites.domain.website import (
    WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    UpdateInterval,
)

logger = get_logger(__name__)


async def update_crawl_circuit_breaker(
    sess: AsyncSession,
    *,
    website_id: UUID,
    tenant_id: UUID,
    website_url: str,
    crawl_successful: bool,
    observed_at: datetime | None = None,
) -> None:
    if crawl_successful:
        logger.info(
            f"Crawl successful, resetting circuit breaker for website {website_id}"
        )
        reset_stmt = (
            sa.update(WebsitesTable)
            .where(WebsitesTable.id == website_id)
            .where(WebsitesTable.tenant_id == tenant_id)
            .values(consecutive_failures=0, next_retry_at=None)
        )
        await sess.execute(reset_stmt)
        return

    current_failures_stmt = (
        sa.select(WebsitesTable.consecutive_failures)
        .where(WebsitesTable.id == website_id)
        .where(WebsitesTable.tenant_id == tenant_id)
    )
    # Preserves the historical read-then-update policy; making this increment
    # atomic is a separate behavior-changing hardening slice.
    current_failures = await sess.scalar(current_failures_stmt)
    new_failures = (current_failures or 0) + 1

    if new_failures >= WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD:
        logger.error(
            f"Website {website_id} auto-disabled after {new_failures} consecutive failures. "
            "User action required to re-enable.",
            extra={
                "website_id": str(website_id),
                "url": website_url,
                "consecutive_failures": new_failures,
            },
        )
        disable_stmt = (
            sa.update(WebsitesTable)
            .where(WebsitesTable.id == website_id)
            .where(WebsitesTable.tenant_id == tenant_id)
            .values(
                consecutive_failures=new_failures,
                update_interval=UpdateInterval.NEVER,
                next_retry_at=None,
            )
        )
        await sess.execute(disable_stmt)
        return

    backoff_hours = min(2 ** (new_failures - 1), 24)
    reference_time = observed_at or datetime.now(timezone.utc)
    next_retry = reference_time + timedelta(hours=backoff_hours)
    logger.warning(
        f"Crawl failed for website {website_id}. "
        f"Failure {new_failures}/{WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD}, "
        f"backoff {backoff_hours}h until {next_retry.isoformat()}",
        extra={
            "website_id": str(website_id),
            "consecutive_failures": new_failures,
            "backoff_hours": backoff_hours,
            "next_retry_at": next_retry.isoformat(),
        },
    )
    backoff_stmt = (
        sa.update(WebsitesTable)
        .where(WebsitesTable.id == website_id)
        .where(WebsitesTable.tenant_id == tenant_id)
        .values(
            consecutive_failures=new_failures,
            next_retry_at=next_retry,
        )
    )
    await sess.execute(backoff_stmt)
