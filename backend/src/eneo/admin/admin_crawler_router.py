from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from eneo.main.container.container import Container
from eneo.roles.permissions import Permission, validate_permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.websites.domain.crawl_run import CrawlOutcome, CrawlPhase
from eneo.websites.presentation.website_models import (
    CrawlFailurePagePublic,
    CrawlResourceFailurePublic,
    CrawlRunPublic,
)

router = APIRouter()
AdminContainer = Annotated[Container, Depends(get_container(with_user=True))]


class AdminCrawlerSummary(BaseModel):
    ongoing: int
    queued: int
    issues: int


class AdminCrawlerItem(BaseModel):
    run: CrawlRunPublic
    website_id: UUID
    website_name: str | None
    website_url: str
    space_name: str | None
    started_at: datetime | None
    last_indexed_at: datetime | None


class AdminCrawlerOverview(BaseModel):
    as_of: datetime
    summary: AdminCrawlerSummary
    items: list[AdminCrawlerItem]
    next_cursor: UUID | None


@router.get(
    "/",
    response_model=AdminCrawlerOverview,
    description="Read tenant-wide crawl metadata and totals. Requires admin permission; includes private-space operational metadata without granting content access.",
    responses=responses.get_responses([400, 403]),
)
async def get_crawler_overview(
    container: AdminContainer,
    view: Literal["active", "recent"] = "active",
    status: CrawlPhase | CrawlOutcome | Literal["issues"] | None = None,
    search: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: UUID | None = None,
) -> AdminCrawlerOverview:
    """Read tenant-wide crawl metadata, including spaces the Owner cannot open."""
    user = container.user()
    validate_permission(user, Permission.ADMIN)
    as_of = datetime.now(timezone.utc)
    overview = await container.crawl_run_repo().tenant_overview(
        user.tenant_id,
        as_of=as_of,
        view=view,
        status=status,
        search=search,
        limit=limit,
        cursor=cursor,
    )
    return AdminCrawlerOverview(
        as_of=as_of,
        summary=AdminCrawlerSummary(
            ongoing=overview.ongoing, queued=overview.queued, issues=overview.issues
        ),
        items=[
            AdminCrawlerItem(
                run=CrawlRunPublic.from_domain(item.run),
                website_id=item.website_id,
                website_name=item.website_name,
                website_url=item.website_url,
                space_name=item.space_name,
                started_at=item.started_at,
                last_indexed_at=item.last_indexed_at,
            )
            for item in overview.items
        ],
        next_cursor=overview.next_cursor,
    )


@router.get(
    "/runs/{id}/failures/",
    response_model=CrawlFailurePagePublic,
    description="Read recorded failure addresses for a crawl in the administrator's tenant.",
    responses=responses.get_responses([400, 403, 404]),
)
async def get_crawler_failures(
    id: UUID,
    container: AdminContainer,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: UUID | None = None,
) -> CrawlFailurePagePublic:
    user = container.user()
    validate_permission(user, Permission.ADMIN)
    repo = container.crawl_run_repo()
    run = await repo.one_for_tenant(id, user.tenant_id)
    page = await repo.get_failures(id, limit=limit, cursor=cursor)
    return CrawlFailurePagePublic(
        run=CrawlRunPublic.from_domain(run),
        details_available=run.failure_details_available,
        items=[
            CrawlResourceFailurePublic(
                id=item.id, url=item.url, reason=item.reason, kind=item.kind
            )
            for item in page.items
        ],
        total_count=page.total_count,
        next_cursor=str(page.next_cursor) if page.next_cursor else None,
    )
