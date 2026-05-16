from datetime import datetime, timedelta, timezone
from typing import Annotated, assert_never
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
)
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawl_run_repo import CrawlRunRepository
from intric.websites.domain.crawler_failure_inventory import CrawlerFailureState
from intric.websites.domain.crawler_recent_failures import (
    RECENT_FAILURE_OUTCOME_CODES,
    WATCHDOG_INTERVENTION_OUTCOME_CODES,
)
from intric.websites.domain.website import UpdateInterval
from intric.websites.domain.website_admin_repo import WebsiteAdminRepository
from intric.websites.presentation.crawler_admin_models import (
    CrawlerAbortConflictResponse,
    CrawlerActiveInventoryResponse,
    CrawlerRecentFailuresResponse,
    CrawlerScheduledAggregateResponse,
    CrawlerTenantFailureInventoryResponse,
    CrawlerTenantWebsiteProcessingAggregateResponse,
)

router = APIRouter(
    dependencies=[
        Depends(require_permission(Permission.ADMIN)),
    ],
)

AdminContainer = Annotated[Container, Depends(get_container(with_user=True))]


def _abort_conflict_detail(code: CrawlAbortConflictCode) -> str:
    match code:
        case CrawlAbortConflictCode.CRAWL_NOT_ABORTABLE:
            return "The crawl job is no longer abortable."
    assert_never(code)


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
) -> CrawlerRecentFailuresResponse:
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)

    if outcome_code is not None and outcome_code not in WATCHDOG_INTERVENTION_OUTCOME_CODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"outcome_code {outcome_code.value!r} is not a watchdog-driven "
                f"terminal outcome; use the recent-failures endpoint for "
                f"non-watchdog outcomes or omit the filter."
            ),
        )

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
) -> CrawlerTenantWebsiteProcessingAggregateResponse:
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)

    async with session.begin():
        repo = CrawlRunRepository(session=session)
        aggregate = await repo.website_processing_aggregate_for_tenant(
            since=since,
            until=until,
            days=days,
            limit=limit,
            offset=offset,
            tenant_id=current_user.tenant_id,
        )
    return CrawlerTenantWebsiteProcessingAggregateResponse.from_domain(aggregate)


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
            audit_service = container.audit_service()
            await audit_service.log_async(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action=ActionType.WEBSITE_CRAWL_ABORTED,
                entity_type=EntityType.WEBSITE,
                entity_id=website.id,
                description="Admin aborted queued website crawl",
                metadata=AuditMetadata.standard(
                    actor=current_user,
                    target=website,
                    extra={
                        "job_id": str(job_id),
                        "already_terminal": already,
                    },
                ),
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
            audit_service = container.audit_service()
            await audit_service.log_async(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action=ActionType.WEBSITE_CRAWL_CIRCUIT_RESET,
                entity_type=EntityType.WEBSITE,
                entity_id=website.id,
                description="Admin reset crawler circuit breaker",
                metadata=AuditMetadata.standard(
                    actor=current_user,
                    target=website,
                    extra={
                        "prev_state": previous_state.value,
                        "prev_consecutive_failures": prev_failures,
                        "prev_next_retry_at": (
                            prev_next_retry.isoformat()
                            if prev_next_retry is not None
                            else None
                        ),
                    },
                ),
            )
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    assert_never(result)


class _UpdateIntervalRequest(BaseModel):
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
    body: _UpdateIntervalRequest,
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
            audit_service = container.audit_service()
            await audit_service.log_async(
                tenant_id=current_user.tenant_id,
                actor_id=current_user.id,
                action=ActionType.WEBSITE_CRAWL_INTERVAL_CHANGED,
                entity_type=EntityType.WEBSITE,
                entity_id=website.id,
                description="Admin changed crawler update interval",
                metadata=AuditMetadata.standard(
                    actor=current_user,
                    target=website,
                    extra={
                        "previous_update_interval": previous_interval.value,
                        "new_update_interval": new_interval.value,
                        "failure_state_cleared": failure_state_cleared,
                        "previous_consecutive_failures": previous_consecutive_failures,
                    },
                ),
            )
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    assert_never(result)
