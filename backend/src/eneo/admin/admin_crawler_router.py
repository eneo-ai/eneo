from datetime import date, datetime, timezone
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import require_user_for_creation
from eneo.main.container.container import Container
from eneo.main.exceptions import BadRequestException
from eneo.main.models import CursorPaginatedResponse
from eneo.roles.permissions import Permission, validate_permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.websites.domain.crawl_run import CrawlResourceKind, CrawlRun
from eneo.websites.domain.crawl_run_repo import CrawlHistoryPeriod, CrawlOverviewStatus
from eneo.websites.domain.website import UpdateInterval, WebsiteSparse
from eneo.websites.presentation.website_models import (
    CrawlFailurePagePublic,
    CrawlResourceFailurePublic,
    CrawlRunPublic,
)

router = APIRouter()
AdminContainer = Annotated[Container, Depends(get_container(with_user=True))]
AdminMutationContainer = Annotated[
    Container, Depends(get_container(with_user=True, transaction_scope="function"))
]


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


class AdminCrawlerDaySummary(BaseModel):
    date: date
    completed: int
    partial: int
    failed: int
    cancelled: int


class AdminCrawlerCalendar(BaseModel):
    time_zone: str
    today: AdminCrawlerDaySummary
    yesterday: AdminCrawlerDaySummary


class AdminCrawlerOverview(BaseModel):
    as_of: datetime
    summary: AdminCrawlerSummary
    calendar: AdminCrawlerCalendar
    items: list[AdminCrawlerItem]
    next_cursor: UUID | None


class AdminCrawlerUser(BaseModel):
    id: UUID
    username: str | None
    email: str


class AdminCrawlerDetails(AdminCrawlerItem):
    space_id: UUID | None
    owner: AdminCrawlerUser
    initiated_by: AdminCrawlerUser | None
    indexed_size: int
    stored_resources: int
    update_interval: UpdateInterval
    next_retry_at: datetime | None
    consecutive_failures: int
    active_run: CrawlRunPublic | None
    latest_run: CrawlRunPublic | None


class AdminCrawlerRelatedWebsite(BaseModel):
    website_id: UUID
    website_name: str | None
    website_url: str
    space_id: UUID | None
    space_name: str | None
    indexed_size: int
    last_indexed_at: datetime | None
    latest_run_id: UUID | None


class AdminCrawlerRelatedPage(BaseModel):
    items: list[AdminCrawlerRelatedWebsite]
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
    status: CrawlOverviewStatus | None = None,
    period: CrawlHistoryPeriod = CrawlHistoryPeriod.LAST_24_HOURS,
    time_zone: Annotated[
        str,
        Query(
            max_length=100, description="IANA time zone used for today and yesterday."
        ),
    ] = "UTC",
    search: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: UUID | None = None,
) -> AdminCrawlerOverview:
    """Read tenant-wide crawl metadata, including spaces the Owner cannot open."""
    user = container.user()
    validate_permission(user, Permission.ADMIN)
    try:
        zone = ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise BadRequestException("Invalid IANA time zone") from error
    as_of = datetime.now(timezone.utc)
    overview = await container.crawl_run_repo().tenant_overview(
        user.tenant_id,
        as_of=as_of,
        view=view,
        status=status,
        period=period,
        time_zone=zone,
        search=search,
        limit=limit,
        cursor=cursor,
    )
    return AdminCrawlerOverview(
        as_of=as_of,
        summary=AdminCrawlerSummary(
            ongoing=overview.ongoing, queued=overview.queued, issues=overview.issues
        ),
        calendar=AdminCrawlerCalendar(
            time_zone=zone.key,
            today=AdminCrawlerDaySummary.model_validate(
                overview.today, from_attributes=True
            ),
            yesterday=AdminCrawlerDaySummary.model_validate(
                overview.yesterday, from_attributes=True
            ),
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
    "/runs/{id}/",
    response_model=AdminCrawlerDetails,
    description="Read a crawl's owning space, source owner, recorded manual initiator, indexed storage and current source state. Requires tenant admin permission; does not grant access to indexed content.",
    responses=responses.get_responses([403, 404]),
)
async def get_crawler_details(
    id: UUID, container: AdminContainer
) -> AdminCrawlerDetails:
    user = container.user()
    validate_permission(user, Permission.ADMIN)
    details = await container.crawl_run_repo().tenant_details(id, user.tenant_id)
    item = details.item
    return AdminCrawlerDetails(
        run=CrawlRunPublic.from_domain(item.run),
        website_id=item.website_id,
        website_name=item.website_name,
        website_url=item.website_url,
        space_name=item.space_name,
        started_at=item.started_at,
        last_indexed_at=item.last_indexed_at,
        space_id=details.space_id,
        owner=AdminCrawlerUser.model_validate(details.owner, from_attributes=True),
        initiated_by=AdminCrawlerUser.model_validate(
            details.initiated_by, from_attributes=True
        )
        if details.initiated_by
        else None,
        indexed_size=details.indexed_size,
        stored_resources=details.stored_resources,
        update_interval=UpdateInterval(details.update_interval),
        next_retry_at=details.next_retry_at,
        consecutive_failures=details.consecutive_failures,
        active_run=CrawlRunPublic.from_domain(details.active_run)
        if details.active_run
        else None,
        latest_run=CrawlRunPublic.from_domain(details.latest_run)
        if details.latest_run
        else None,
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
    kind: CrawlResourceKind | None = None,
) -> CrawlFailurePagePublic:
    user = container.user()
    validate_permission(user, Permission.ADMIN)
    repo = container.crawl_run_repo()
    run = await repo.one_for_tenant(id, user.tenant_id)
    page = await repo.get_failures(id, limit=limit, cursor=cursor, kind=kind)
    return CrawlFailurePagePublic(
        run=CrawlRunPublic.from_domain(run),
        details_available=run.failure_details_available,
        items=[
            CrawlResourceFailurePublic(
                id=item.id, url=item.url, reason=item.reason, kind=item.kind
            )
            for item in page.items
        ],
        limit=limit,
        total_count=page.total_count,
        next_cursor=str(page.next_cursor) if page.next_cursor else None,
    )


@router.get(
    "/websites/{id}/runs/",
    response_model=CursorPaginatedResponse[CrawlRunPublic],
    description="Read paginated crawl history for one website in the administrator's tenant, including runs older than 24 hours. Does not grant private content access.",
    responses=responses.get_responses([400, 403, 404]),
)
async def get_admin_website_runs(
    id: UUID,
    container: AdminContainer,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    cursor: UUID | None = None,
) -> CursorPaginatedResponse[CrawlRunPublic]:
    user = container.user()
    validate_permission(user, Permission.ADMIN)
    await container.website_sparse_repo().one_for_tenant(id, user.tenant_id)
    page = await container.crawl_run_repo().get_crawl_runs(
        id, limit=limit, cursor=cursor
    )
    return CursorPaginatedResponse(
        items=[CrawlRunPublic.from_domain(run) for run in page.items],
        limit=limit,
        total_count=page.total_count,
        next_cursor=str(page.next_cursor) if page.next_cursor else None,
    )


@router.get(
    "/websites/{id}/matches/",
    response_model=AdminCrawlerRelatedPage,
    description="Read a bounded page of other source registrations with this exact website address in the administrator's tenant. Matching addresses do not imply identical indexed content.",
    responses=responses.get_responses([403, 404]),
)
async def get_admin_website_matches(
    id: UUID,
    container: AdminContainer,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    cursor: UUID | None = None,
) -> AdminCrawlerRelatedPage:
    user = container.user()
    validate_permission(user, Permission.ADMIN)
    repo = container.website_sparse_repo()
    website = await repo.one_for_tenant(id, user.tenant_id)
    page = await repo.same_address(website, limit=limit, cursor=cursor)
    return AdminCrawlerRelatedPage(
        items=[
            AdminCrawlerRelatedWebsite.model_validate(item, from_attributes=True)
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


async def _audit_crawler_action(
    container: Container, website: WebsiteSparse, run: CrawlRun, action: ActionType
) -> None:
    user = container.user()
    assert website.id is not None
    operation = (
        "crawl"
        if action == ActionType.WEBSITE_CRAWL_REQUESTED
        else "crawl cancellation"
    )
    await container.audit_service().log(
        tenant_id=user.tenant_id,
        user=user,
        action=action,
        entity_type=EntityType.WEBSITE,
        entity_id=website.id,
        description=f"Requested {operation} for website '{website.url}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=website,
            extra={
                "crawl_run_id": str(run.id),
                "phase": run.phase.value,
                "outcome": run.outcome.value if run.outcome else None,
            },
        ),
    )


@router.post(
    "/websites/{id}/run/",
    response_model=CrawlRunPublic,
    description="Request a crawl with the website's current settings. Tenant admin permission permits this operation in private spaces without granting content access. Returns the existing active run when present. Requires a user identity; retry starts a new full crawl. A new run executes as the requesting administrator, whose storage quota covers newly published content versions.",
    responses=responses.get_responses([403, 404]),
)
async def request_admin_crawl(
    id: UUID, container: AdminMutationContainer
) -> CrawlRunPublic:
    user = container.user()
    validate_permission(user, Permission.ADMIN)
    await require_user_for_creation(user)
    website = await container.website_sparse_repo().one_for_tenant(id, user.tenant_id)
    run = await container.crawl_service().crawl(website)
    await _audit_crawler_action(
        container, website, run, ActionType.WEBSITE_CRAWL_REQUESTED
    )
    return CrawlRunPublic.from_domain(run)


@router.post(
    "/runs/{id}/cancel/",
    response_model=CrawlRunPublic,
    description="Request cancellation of this exact run. Tenant admin permission permits this operation in private spaces without granting content access. Queued work cancels immediately; running work enters stopping. An already finished run is returned unchanged.",
    responses=responses.get_responses([403, 404]),
)
async def cancel_admin_crawl(
    id: UUID, container: AdminMutationContainer
) -> CrawlRunPublic:
    user = container.user()
    validate_permission(user, Permission.ADMIN)
    run = await container.crawl_run_repo().one_for_tenant(id, user.tenant_id)
    website = await container.website_sparse_repo().one_for_tenant(
        run.website_id, user.tenant_id
    )
    stopped = await container.crawl_service().cancel(id)
    await _audit_crawler_action(
        container, website, stopped, ActionType.WEBSITE_CRAWL_STOP_REQUESTED
    )
    return CrawlRunPublic.from_domain(stopped)
