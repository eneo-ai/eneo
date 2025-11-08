"""FastAPI routes for audit logging."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response

from intric.api.audit.schemas import (
    AuditLogListResponse,
    AuditLogResponse,
)
from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    actor_id: Optional[UUID] = Query(None, description="Filter by actor"),
    action: Optional[ActionType] = Query(None, description="Filter by action type"),
    from_date: Optional[datetime] = Query(None, description="Filter from date"),
    to_date: Optional[datetime] = Query(None, description="Filter to date"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=1000, description="Page size"),
    container: Container = Depends(get_container(with_user=True)),
):
    """
    List audit logs for the authenticated user's tenant.

    Access Control:
    - Regular users: See only their own actions
    - Admins: See all actions in their tenant
    - Compliance officers: See all actions in their tenant

    Requires: Authentication (JWT token or API key)
    """
    current_user = container.user()
    session = container.session()
    
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    logs, total_count = await audit_service.get_logs(
        tenant_id=current_user.tenant_id,
        actor_id=actor_id,
        action=action,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )

    total_pages = (total_count + page_size - 1) // page_size

    return AuditLogListResponse(
        logs=[AuditLogResponse.model_validate(log) for log in logs],
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/logs/user/{user_id}", response_model=AuditLogListResponse)
async def get_user_logs(
    user_id: UUID = Path(..., description="User ID for GDPR export"),
    from_date: Optional[datetime] = Query(None, description="Filter from date"),
    to_date: Optional[datetime] = Query(None, description="Filter to date"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=1000, description="Page size"),
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Get all logs where user is actor OR target (GDPR Article 15 export).

    Returns audit logs involving the user in any capacity.

    Requires: Authentication (JWT token or API key via X-API-Key header)
    Security: Only returns logs for the authenticated user's tenant
    """
    current_user = container.user()
    session = container.session()
    
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    logs, total_count = await audit_service.get_user_logs(
        tenant_id=current_user.tenant_id,
        user_id=user_id,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )

    total_pages = (total_count + page_size - 1) // page_size

    return AuditLogListResponse(
        logs=[AuditLogResponse.model_validate(log) for log in logs],
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/logs/export")
async def export_audit_logs(
    user_id: Optional[UUID] = Query(None, description="User ID for GDPR export"),
    actor_id: Optional[UUID] = Query(None, description="Filter by actor"),
    action: Optional[ActionType] = Query(None, description="Filter by action type"),
    from_date: Optional[datetime] = Query(None, description="Filter from date"),
    to_date: Optional[datetime] = Query(None, description="Filter to date"),
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Export audit logs to CSV format.

    Use user_id for GDPR Article 15 data subject access requests.

    Requires: Authentication (JWT token or API key via X-API-Key header)
    Security: Only exports logs for the authenticated user's tenant
    """
    current_user = container.user()
    session = container.session()
    
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    csv_content = await audit_service.export_csv(
        tenant_id=current_user.tenant_id,
        user_id=user_id,
        actor_id=actor_id,
        action=action,
        from_date=from_date,
        to_date=to_date,
    )

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=audit_logs_{datetime.utcnow().isoformat()}.csv"
        },
    )



@router.get("/retention-policy", response_model=dict)
async def get_retention_policy(
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Get the current retention policy for your tenant.

    Returns the number of days audit logs are retained before automatic purging.

    Requires: Authentication (JWT token or API key via X-API-Key header)
    """
    from intric.audit.application.retention_service import RetentionService

    current_user = container.user()
    session = container.session()

    retention_service = RetentionService(session)
    policy = await retention_service.get_policy(current_user.tenant_id)

    # policy is already a Pydantic model, just return its dict
    return policy.model_dump()


@router.put("/retention-policy", response_model=dict)
async def update_retention_policy(
    retention_days: int = Query(
        ...,
        ge=1,
        le=2555,
        description="Days to retain logs (1 min, 2555 max = 7 years). Recommended: 90+ days",
    ),
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Update the retention policy for your tenant.

    Configure how long audit logs are kept before automatic purging.

    Constraints:
    - Minimum: 1 day (Recommended: 90+ days for compliance)
    - Maximum: 2555 days (~7 years, Swedish statute of limitations)
    - Default: 365 days (Swedish Arkivlagen)

    The system automatically runs a daily job to soft-delete logs older than
    the retention period.

    Requires: Authentication (JWT token or API key via X-API-Key header)
    Requires: Admin permissions
    """
    from intric.audit.application.retention_service import RetentionService

    current_user = container.user()
    session = container.session()

    retention_service = RetentionService(session)
    policy = await retention_service.update_policy(current_user.tenant_id, retention_days)

    # policy is already a Pydantic model, just return its dict
    return policy.model_dump()
