from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from intric.authentication.auth_dependencies import (
    get_current_active_user,
    require_permission,
)
from intric.database.database import AsyncSession, get_session
from intric.roles.permissions import Permission
from intric.users.user import UserInDB
from intric.websites.domain.crawl_run_repo import CrawlRunRepository
from intric.websites.domain.website_admin_repo import WebsiteAdminRepository
from intric.websites.presentation.crawler_admin_models import (
    CrawlerActiveInventoryResponse,
    CrawlerRecentFailuresResponse,
    CrawlerScheduledAggregateResponse,
)

router = APIRouter(
    dependencies=[
        Depends(require_permission(Permission.ADMIN)),
    ],
)


@router.get(
    "/active",
    response_model=CrawlerActiveInventoryResponse,
    summary="Get active and queued crawler runs for the current tenant",
)
async def get_current_tenant_crawler_active_inventory(
    current_user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CrawlerActiveInventoryResponse:
    async with session.begin():
        repo = CrawlRunRepository(session=session)
        inventory = await repo.active_inventory_for_tenant(
            limit=limit,
            offset=offset,
            tenant_id=current_user.tenant_id,
        )
    return CrawlerActiveInventoryResponse.from_domain(inventory)


@router.get(
    "/recent-failures",
    response_model=CrawlerRecentFailuresResponse,
    summary="Get recently failed crawler runs for the current tenant",
)
async def get_current_tenant_crawler_recent_failures(
    current_user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=30)] = 7,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CrawlerRecentFailuresResponse:
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)

    async with session.begin():
        repo = CrawlRunRepository(session=session)
        failures = await repo.recent_failures_for_tenant(
            since=since,
            until=until,
            days=days,
            limit=limit,
            offset=offset,
            tenant_id=current_user.tenant_id,
        )
    return CrawlerRecentFailuresResponse.from_domain(failures)


@router.get(
    "/scheduled",
    response_model=CrawlerScheduledAggregateResponse,
    summary="Get scheduled crawler aggregate for the current tenant",
)
async def get_current_tenant_crawler_scheduled_aggregate(
    current_user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CrawlerScheduledAggregateResponse:
    async with session.begin():
        repo = WebsiteAdminRepository(session=session)
        aggregate = await repo.scheduled_aggregate_for_tenant(
            tenant_id=current_user.tenant_id,
        )
    return CrawlerScheduledAggregateResponse.from_domain(aggregate)
