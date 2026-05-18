import time
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Protocol, assert_never
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.auth_dependencies import (
    get_current_active_user,
    require_permission,
)
from intric.database.database import AsyncSession, get_session
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.roles.permissions import Permission
from intric.server.dependencies.container import get_container
from intric.users.user import UserInDB
from intric.websites.domain.crawl_abort import (
    CrawlAbortConflict,
    CrawlAbortConflictCode,
    CrawlAbortNotFound,
    CrawlAbortSucceeded,
)
from intric.websites.domain.crawl_circuit_reset import (
    CrawlCircuitResetNotFound,
    CrawlCircuitResetSucceeded,
)
from intric.websites.domain.crawl_interval_change import (
    CrawlIntervalChangeApplied,
    CrawlIntervalChangeNotFound,
    CrawlIntervalChangeUnchanged,
    CrawlIntervalChangeWebsite,
)
from intric.websites.domain.crawl_lifecycle import CrawlLifecycle
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawl_retry import CrawlRetryWebsite
from intric.websites.domain.crawl_run_repo import CrawlRunRepository
from intric.websites.domain.crawl_website_delete import (
    CrawlWebsiteDeleteBlocked,
    CrawlWebsiteDeleteNotFound,
    CrawlWebsiteDeleteSucceeded,
)
from intric.websites.domain.crawler_failure_inventory import CrawlerFailureState
from intric.websites.domain.crawler_recent_failures import (
    RECENT_FAILURE_OUTCOME_CODES,
    WATCHDOG_INTERVENTION_OUTCOME_CODES,
)
from intric.websites.domain.crawler_tenant_website_inventory import (
    CrawlerTenantWebsiteInventorySort,
)
from intric.websites.domain.crawler_website_processing_aggregate import (
    CrawlerWebsiteProcessingSort,
)
from intric.websites.domain.website import UpdateInterval
from intric.websites.domain.website_admin_repo import WebsiteAdminRepository
from intric.websites.domain.website_sparse_repo import WebsiteSparseRepository
from intric.websites.presentation.crawler_admin_models import (
    CrawlerAbortConflictResponse,
    CrawlerActiveInventoryResponse,
    CrawlerBulkIntervalRequest,
    CrawlerBulkIntervalResponse,
    CrawlerRecentFailuresResponse,
    CrawlerScheduledAggregateResponse,
    CrawlerTenantFailureInventoryResponse,
    CrawlerTenantWebsiteInventoryResponse,
    CrawlerTenantWebsiteProcessingAggregateResponse,
    CrawlerWebsiteDeleteConflictResponse,
)

router = APIRouter(
    dependencies=[
        Depends(require_permission(Permission.ADMIN)),
    ],
)

AdminContainer = Annotated[Container, Depends(get_container(with_user=True))]

logger = get_logger(__name__)


@asynccontextmanager
async def _admin_crawler_query_telemetry(
    endpoint: str,
    *,
    tenant_id: UUID,
    extra_labels: Mapping[str, object] | None = None,
):
    """Bounded latency telemetry for tenant-admin crawler queries.

    Emits one structured log entry per request with `metric_name` +
    `metric_value` keys so existing log-as-metric ingestion picks it up
    without a new dependency. `extra_labels` lets endpoint-specific
    dimensions (e.g. `has_search`, `has_filters`) ride alongside the
    base shape so a slow-query investigation can split latency by
    filter dimension without re-instrumenting.
    """
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        extra: dict[str, object] = {
            "metric_name": "crawler.admin.query_duration_ms",
            "metric_value": elapsed_ms,
            "endpoint": endpoint,
            "tenant_id": str(tenant_id),
        }
        if extra_labels:
            extra.update(extra_labels)
        logger.info(
            "Admin crawler query completed",
            extra=extra,
        )


def _abort_conflict_detail(code: CrawlAbortConflictCode) -> str:
    match code:
        case CrawlAbortConflictCode.CRAWL_NOT_ABORTABLE:
            return "The crawl job is no longer abortable."
    assert_never(code)


class _AuditableWebsite(Protocol):
    """Shape required by `_log_crawler_admin_website_action`.

    Every domain result type that the crawler admin endpoints emit audit
    events for (CrawlAbortWebsite, CrawlCircuitResetWebsite,
    CrawlIntervalChangeWebsite, ...) exposes an `id` UUID and a `name`
    string. Using a Protocol with read-only attributes keeps the helper
    signature narrow without importing every concrete result type for
    typing purposes, and stays compatible with the `frozen=True`
    dataclasses that back these domain results.
    """

    @property
    def id(self) -> UUID: ...

    @property
    def name(self) -> str: ...


async def _log_crawler_admin_website_action(
    container: "Container",
    *,
    current_user: UserInDB,
    action: ActionType,
    website: _AuditableWebsite,
    description: str,
    extra: Mapping[str, object],
) -> None:
    """Single canonical audit emission for crawler admin website mutations.

    All four write endpoints in this router (abort, circuit-breaker reset,
    interval change, and any future per-website action) share the same
    audit shape: tenant-scoped, actor=current_user, entity=WEBSITE,
    metadata=AuditMetadata.standard with extra payload. Centralising the
    emission here keeps the audit shape and tenant scoping identical
    across endpoints and makes the audit-coverage gate visible at the
    router boundary instead of buried inside three near-identical blocks.
    """
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=action,
        entity_type=EntityType.WEBSITE,
        entity_id=website.id,
        description=description,
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=website,
            extra=extra,
        ),
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
    lifecycle_status: Annotated[CrawlLifecycle | None, Query()] = None,
    website_id: Annotated[UUID | None, Query()] = None,
) -> CrawlerActiveInventoryResponse:
    async with _admin_crawler_query_telemetry(
        "active_inventory", tenant_id=current_user.tenant_id
    ):
        async with session.begin():
            repo = CrawlRunRepository(session=session)
            inventory = await repo.active_inventory_for_tenant(
                limit=limit,
                offset=offset,
                tenant_id=current_user.tenant_id,
                lifecycle_filter=lifecycle_status,
                website_id=website_id,
            )
        return CrawlerActiveInventoryResponse.from_domain(inventory)


@router.get(
    "/failure-inventory",
    response_model=CrawlerTenantFailureInventoryResponse,
    summary="Get crawler websites currently backed off or disabled for the current tenant",
)
async def get_current_tenant_crawler_failure_inventory(
    current_user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    state: Annotated[CrawlerFailureState | None, Query()] = None,
) -> CrawlerTenantFailureInventoryResponse:
    async with _admin_crawler_query_telemetry(
        "failure_inventory", tenant_id=current_user.tenant_id
    ):
        async with session.begin():
            repo = WebsiteAdminRepository(session=session)
            inventory = await repo.crawler_failure_inventory_for_tenant(
                limit=limit,
                offset=offset,
                tenant_id=current_user.tenant_id,
                state_filter=state,
            )
        return CrawlerTenantFailureInventoryResponse.from_domain(inventory)


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
    outcome_code: Annotated[CrawlOutcomeCode | None, Query()] = None,
    website_id: Annotated[UUID | None, Query()] = None,
) -> CrawlerRecentFailuresResponse:
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)

    if outcome_code is not None and outcome_code not in RECENT_FAILURE_OUTCOME_CODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"outcome_code {outcome_code.value!r} is not in the recent-failures "
                f"allowlist; use the watchdog-interventions endpoint for "
                f"watchdog-only outcomes or omit the filter."
            ),
        )

    async with _admin_crawler_query_telemetry(
        "recent_failures", tenant_id=current_user.tenant_id
    ):
        async with session.begin():
            repo = CrawlRunRepository(session=session)
            failures = await repo.recent_failures_for_tenant(
                since=since,
                until=until,
                days=days,
                limit=limit,
                offset=offset,
                tenant_id=current_user.tenant_id,
                outcome_filter=outcome_code,
                website_id=website_id,
            )
        return CrawlerRecentFailuresResponse.from_domain(failures)


@router.get(
    "/watchdog-interventions",
    response_model=CrawlerRecentFailuresResponse,
    summary="Get recently watchdog-terminated crawler runs for the current tenant",
)
async def get_current_tenant_crawler_watchdog_interventions(
    current_user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=30)] = 7,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    outcome_code: Annotated[CrawlOutcomeCode | None, Query()] = None,
    website_id: Annotated[UUID | None, Query()] = None,
) -> CrawlerRecentFailuresResponse:
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)

    if (
        outcome_code is not None
        and outcome_code not in WATCHDOG_INTERVENTION_OUTCOME_CODES
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"outcome_code {outcome_code.value!r} is not a watchdog-driven "
                f"terminal outcome; use the recent-failures endpoint for "
                f"non-watchdog outcomes or omit the filter."
            ),
        )

    async with _admin_crawler_query_telemetry(
        "watchdog_interventions", tenant_id=current_user.tenant_id
    ):
        async with session.begin():
            repo = CrawlRunRepository(session=session)
            interventions = await repo.watchdog_interventions_for_tenant(
                since=since,
                until=until,
                days=days,
                limit=limit,
                offset=offset,
                tenant_id=current_user.tenant_id,
                outcome_filter=outcome_code,
                website_id=website_id,
            )
        return CrawlerRecentFailuresResponse.from_domain(interventions)


@router.get(
    "/scheduled",
    response_model=CrawlerScheduledAggregateResponse,
    summary="Get scheduled crawler aggregate for the current tenant",
)
async def get_current_tenant_crawler_scheduled_aggregate(
    current_user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CrawlerScheduledAggregateResponse:
    async with _admin_crawler_query_telemetry(
        "scheduled_aggregate", tenant_id=current_user.tenant_id
    ):
        async with session.begin():
            repo = WebsiteAdminRepository(session=session)
            aggregate = await repo.scheduled_aggregate_for_tenant(
                tenant_id=current_user.tenant_id,
            )
        return CrawlerScheduledAggregateResponse.from_domain(aggregate)


@router.get(
    "/website-processing",
    response_model=CrawlerTenantWebsiteProcessingAggregateResponse,
    summary="Get crawler processing aggregate by website for the current tenant",
)
async def get_current_tenant_crawler_website_processing_aggregate(
    current_user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=30)] = 7,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    website_id: Annotated[UUID | None, Query()] = None,
    space_id: Annotated[UUID | None, Query()] = None,
    sort: Annotated[
        CrawlerWebsiteProcessingSort, Query()
    ] = CrawlerWebsiteProcessingSort.LOAD_PRESSURE,
    failures_only: Annotated[bool, Query()] = False,
    low_retention_only: Annotated[bool, Query()] = False,
    source_skip_drift_only: Annotated[bool, Query()] = False,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> CrawlerTenantWebsiteProcessingAggregateResponse:
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)

    has_search = search is not None and search.strip() != ""
    has_filters = failures_only or low_retention_only or source_skip_drift_only

    async with _admin_crawler_query_telemetry(
        "website_processing_aggregate",
        tenant_id=current_user.tenant_id,
        extra_labels={
            "has_search": has_search,
            "has_filters": has_filters,
            "has_space_filter": space_id is not None,
            "sort": sort.value,
        },
    ):
        async with session.begin():
            repo = CrawlRunRepository(session=session)
            aggregate = await repo.website_processing_aggregate_for_tenant(
                since=since,
                until=until,
                days=days,
                limit=limit,
                offset=offset,
                tenant_id=current_user.tenant_id,
                website_id=website_id,
                space_id=space_id,
                sort=sort,
                failures_only=failures_only,
                low_retention_only=low_retention_only,
                source_skip_drift_only=source_skip_drift_only,
                search=search,
            )
        return CrawlerTenantWebsiteProcessingAggregateResponse.from_domain(aggregate)


@router.get(
    "/websites",
    response_model=CrawlerTenantWebsiteInventoryResponse,
    summary="List every website in the current tenant for governance + drill-down",
)
async def get_current_tenant_crawler_website_inventory(
    current_user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(max_length=200)] = None,
    update_interval: Annotated[UpdateInterval | None, Query()] = None,
    space_id: Annotated[UUID | None, Query()] = None,
    owner_user_id: Annotated[UUID | None, Query()] = None,
    failure_state: Annotated[CrawlerFailureState | None, Query()] = None,
    sort: Annotated[
        CrawlerTenantWebsiteInventorySort, Query()
    ] = CrawlerTenantWebsiteInventorySort.RECENT_CRAWL,
) -> CrawlerTenantWebsiteInventoryResponse:
    """Tenant-scoped lens on every Website row + its attribution + state.

    The Webbplatser admin tab needs a single read that returns *all*
    websites in the tenant — not the active-inventory subset (queued +
    running) or the failure-inventory subset (broken). Each filter is
    optional; the default (no filters, sort=recent_crawl) shows the page
    layout an admin lands on after clicking the tab.

    No mutation, no audit row required. The router-level telemetry block
    captures the "did the admin look at the inventory" signal.
    """
    async with _admin_crawler_query_telemetry(
        "tenant_website_inventory", tenant_id=current_user.tenant_id
    ):
        async with session.begin():
            repo = WebsiteAdminRepository(session=session)
            inventory = await repo.tenant_website_inventory(
                tenant_id=current_user.tenant_id,
                limit=limit,
                offset=offset,
                search=search,
                update_interval=update_interval,
                space_id=space_id,
                owner_user_id=owner_user_id,
                failure_state=failure_state,
                sort=sort,
            )
        return CrawlerTenantWebsiteInventoryResponse.from_domain(inventory)


@router.post(
    "/jobs/{job_id}/abort",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Crawl job not found"},
        status.HTTP_409_CONFLICT: {"model": CrawlerAbortConflictResponse},
    },
    summary="Abort a queued crawler job for the current tenant",
)
async def abort_current_tenant_queued_crawl(
    job_id: UUID,
    current_user: Annotated[UserInDB, Depends(get_current_active_user)],
    container: AdminContainer,
) -> Response:
    crawl_service = container.crawl_service()
    result = await crawl_service.abort_crawl(
        job_id=job_id,
        tenant_id=current_user.tenant_id,
    )

    match result:
        case CrawlAbortNotFound():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Crawl job not found",
            )
        case CrawlAbortConflict(code=code):
            conflict = CrawlerAbortConflictResponse(
                error_code=code,
                detail=_abort_conflict_detail(code),
            )
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content=conflict.model_dump(mode="json"),
            )
        case CrawlAbortSucceeded(website=website, already_terminal=already):
            await _log_crawler_admin_website_action(
                container,
                current_user=current_user,
                action=ActionType.WEBSITE_CRAWL_ABORTED,
                website=website,
                description="Admin aborted queued website crawl",
                extra={
                    "job_id": str(job_id),
                    "already_terminal": already,
                },
            )
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    assert_never(result)


@router.post(
    "/websites/{website_id}/reset-circuit-breaker",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Website not found"},
    },
    summary="Reset crawler circuit breaker for one website in the current tenant",
)
async def reset_current_tenant_crawler_circuit_breaker(
    website_id: UUID,
    current_user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: AdminContainer,
) -> Response:
    async with session.begin():
        repo = WebsiteAdminRepository(session=session)
        result = await repo.reset_crawl_circuit_breaker_for_tenant(
            website_id=website_id,
            tenant_id=current_user.tenant_id,
        )

    match result:
        case CrawlCircuitResetNotFound():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Website not found",
            )
        case CrawlCircuitResetSucceeded(
            website=website,
            previous_state=previous_state,
            previous_consecutive_failures=prev_failures,
            previous_next_retry_at=prev_next_retry,
        ):
            await _log_crawler_admin_website_action(
                container,
                current_user=current_user,
                action=ActionType.WEBSITE_CRAWL_CIRCUIT_RESET,
                website=website,
                description="Admin reset crawler circuit breaker",
                extra={
                    "prev_state": previous_state.value,
                    "prev_consecutive_failures": prev_failures,
                    "prev_next_retry_at": (
                        prev_next_retry.isoformat()
                        if prev_next_retry is not None
                        else None
                    ),
                },
            )
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    assert_never(result)


class UpdateIntervalRequest(BaseModel):
    update_interval: UpdateInterval


@router.patch(
    "/websites/{website_id}/update-interval",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Website not found"},
    },
    summary="Change the scheduled crawl interval for one website in the current tenant",
)
async def set_current_tenant_crawler_update_interval(
    website_id: UUID,
    body: UpdateIntervalRequest,
    current_user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: AdminContainer,
) -> Response:
    async with session.begin():
        repo = WebsiteAdminRepository(session=session)
        result = await repo.set_crawl_update_interval_for_tenant(
            website_id=website_id,
            tenant_id=current_user.tenant_id,
            new_update_interval=body.update_interval,
        )

    match result:
        case CrawlIntervalChangeNotFound():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Website not found",
            )
        case CrawlIntervalChangeUnchanged():
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        case CrawlIntervalChangeApplied(
            website=website,
            previous_update_interval=previous_interval,
            new_update_interval=new_interval,
            failure_state_cleared=failure_state_cleared,
            previous_consecutive_failures=previous_consecutive_failures,
        ):
            await _log_crawler_admin_website_action(
                container,
                current_user=current_user,
                action=ActionType.WEBSITE_CRAWL_INTERVAL_CHANGED,
                website=website,
                description="Admin changed crawler update interval",
                extra={
                    "previous_update_interval": previous_interval.value,
                    "new_update_interval": new_interval.value,
                    "failure_state_cleared": failure_state_cleared,
                    "previous_consecutive_failures": previous_consecutive_failures,
                },
            )
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    assert_never(result)


@router.post(
    "/websites/{website_id}/retry",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Website not found"},
    },
    summary="Queue an immediate crawl retry for one website in the current tenant",
)
async def retry_current_tenant_crawl(
    website_id: UUID,
    current_user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: AdminContainer,
) -> Response:
    """Re-queue an immediate crawl for a tenant-owned website.

    The retry flow is deliberately lighter than abort/circuit-reset: it
    does not touch circuit-breaker counters, does not change the
    `update_interval`, and does not write a terminal event on prior
    crawl runs. It just queues a fresh crawl through the existing
    `CrawlService.crawl(website)` path (which selects feeder vs direct
    enqueue based on the runtime setting). The audit row records the
    new `crawl_run_id` so the operator audit trail can cross-reference
    the requested retry with the run that actually executed.

    Website lookup goes through `WebsiteSparseRepository.get_for_tenant`
    so the returned shape is the `WebsiteSparse` domain object — which
    satisfies the `CrawlableWebsite = Website | WebsiteSparse` Protocol
    `CrawlService.crawl(...)` accepts without an ORM-row coercion.
    """
    async with session.begin():
        repo = WebsiteSparseRepository(session=session)
        website = await repo.get_for_tenant(
            website_id=website_id,
            tenant_id=current_user.tenant_id,
        )

    if website is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Website not found",
        )

    crawl_service = container.crawl_service()
    crawl_run = await crawl_service.crawl(website)

    display_name = website.name if website.name else website.url
    website_payload = CrawlRetryWebsite(id=website.id, name=str(display_name))
    await _log_crawler_admin_website_action(
        container,
        current_user=current_user,
        action=ActionType.WEBSITE_CRAWL_RETRY_REQUESTED,
        website=website_payload,
        description="Admin requested immediate crawl retry",
        extra={"crawl_run_id": str(crawl_run.id)},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/websites/{website_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Website not found"},
        status.HTTP_409_CONFLICT: {"model": CrawlerWebsiteDeleteConflictResponse},
    },
    summary="Delete one website in the current tenant",
)
async def delete_current_tenant_crawler_website(
    website_id: UUID,
    current_user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: AdminContainer,
) -> Response:
    """Hard-delete one website inside the current tenant scope.

    Refuses when a queued or running crawl job exists for the website
    (409 with `error_code=ACTIVE_JOB_BLOCKING`); the admin must abort
    the active job first via `/jobs/{job_id}/abort`. On success the
    Websites row + all FK-cascaded children (crawl_runs,
    assistants_websites, websites_spaces, info_blobs) are removed in
    one transaction; the audit row records the deleted URL.
    """
    async with session.begin():
        repo = WebsiteAdminRepository(session=session)
        result = await repo.delete_website_for_tenant(
            website_id=website_id,
            tenant_id=current_user.tenant_id,
        )

    match result:
        case CrawlWebsiteDeleteNotFound():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Website not found",
            )
        case CrawlWebsiteDeleteBlocked(code=code):
            payload = CrawlerWebsiteDeleteConflictResponse(
                error_code=code,
                detail=(
                    "Website has a queued or running crawl job; abort it before "
                    "deleting the website."
                ),
            )
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content=payload.model_dump(mode="json"),
            )
        case CrawlWebsiteDeleteSucceeded(website=deleted):
            display_name = deleted.name if deleted.name else deleted.url
            await _log_crawler_admin_website_action(
                container,
                current_user=current_user,
                action=ActionType.WEBSITE_DELETED,
                website=CrawlRetryWebsite(id=deleted.id, name=str(display_name)),
                description="Admin deleted website",
                extra={"url": deleted.url},
            )
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    assert_never(result)


@router.post(
    "/websites/bulk-interval",
    response_model=CrawlerBulkIntervalResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply one update_interval to many websites in the current tenant",
)
async def bulk_set_current_tenant_crawler_update_interval(
    payload: CrawlerBulkIntervalRequest,
    current_user: Annotated[UserInDB, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: AdminContainer,
) -> CrawlerBulkIntervalResponse:
    """Apply one interval to many websites — capped + per-row audited.

    Loops the existing per-row setter (preserving the auto-disabled
    resume invariant) inside one transaction. Each `Applied` row gets
    the same per-website audit emission as the per-row endpoint, so
    audit-log search by `EntityType.WEBSITE` entity_id stays intact.
    `Unchanged` + `Failed` rows surface to the operator but are not
    audited (no state change). Returns 200 with a structured
    `{applied, unchanged, failed}` payload rather than 207 — the
    JS SDK is typed and doesn't benefit from polyglot status codes.

    `website_ids` is capped at 100 by the request model
    `max_length=BULK_INTERVAL_MAX_WEBSITE_IDS`; "select all matching
    filter" is deferred to v3 (audit-by-id under the same transaction
    as the filter run is its own commit — see
    `bulk_crawl_interval_change.py` module docstring).
    """
    async with _admin_crawler_query_telemetry(
        "bulk_set_update_interval", tenant_id=current_user.tenant_id
    ):
        async with session.begin():
            repo = WebsiteAdminRepository(session=session)
            result = await repo.bulk_set_crawl_update_interval_for_tenant(
                website_ids=list(payload.website_ids),
                tenant_id=current_user.tenant_id,
                new_update_interval=payload.update_interval,
            )

        for applied in result.applied:
            await _log_crawler_admin_website_action(
                container,
                current_user=current_user,
                action=ActionType.WEBSITE_CRAWL_INTERVAL_CHANGED,
                website=CrawlIntervalChangeWebsite(
                    id=applied.website_id,
                    name=applied.website_name,
                ),
                description="Admin changed crawler update interval (bulk)",
                extra={
                    "previous_update_interval": applied.previous_update_interval.value,
                    "new_update_interval": applied.new_update_interval.value,
                    "failure_state_cleared": applied.failure_state_cleared,
                    "previous_consecutive_failures": applied.previous_consecutive_failures,
                    "bulk": True,
                },
            )

        return CrawlerBulkIntervalResponse.from_domain(result)
