"""FastAPI routes for audit logging."""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

import redis.exceptions
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from intric.api.audit.retention_schemas import (
    RetentionPolicyResponse,
    RetentionPolicyUpdateRequest,
)
from intric.api.audit.schemas import (
    AccessJustificationRequest,
    AccessJustificationResponse,
    AuditLogListResponse,
    AuditLogResponse,
    ExportJobRequest,
    ExportJobResponse,
    ExportJobStatusResponse,
)
from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from intric.database.tables.users_table import Users
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
import sqlalchemy as sa

# Import config routes
from intric.api.audit.config_routes import router as config_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["audit"])

# Include config routes
router.include_router(config_router)


async def _enrich_logs_with_actor_info(logs: list, session) -> list[dict]:
    """
    Enrich audit logs with actor information (name/email).

    This adds actor details to the metadata for display in the UI.
    """
    if not logs:
        return []

    # Get unique actor IDs from logs
    actor_ids = list(set(log.actor_id for log in logs if log.actor_id))

    # Fetch user information for all actors
    user_map = {}
    if actor_ids:
        query = sa.select(Users.id, Users.email, Users.username).where(
            Users.id.in_(actor_ids)
        )
        results = await session.execute(query)
        for user_id, email, username in results:
            # Handle NULL email safely - use username, email prefix, or "Unknown"
            if username:
                display_name = username
            elif email:
                display_name = email.split('@')[0]
            else:
                display_name = "Unknown"

            user_map[user_id] = {
                "id": str(user_id),
                "email": email,
                "name": display_name,
            }

    # Convert logs to response models and enrich with actor info
    enriched_logs = []
    for log in logs:
        log_dict = AuditLogResponse.model_validate(log).model_dump()

        # Add actor information to metadata if we have it
        if log.actor_id in user_map:
            if "metadata" not in log_dict:
                log_dict["metadata"] = {}
            log_dict["metadata"]["actor"] = user_map[log.actor_id]

        enriched_logs.append(log_dict)

    return enriched_logs


@router.delete("/access-session/rate-limit", status_code=204)
async def reset_rate_limit(
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Admin utility: Reset audit session rate limit for current user.

    This endpoint is only available in development/testing environments.
    Use when you get rate limited during testing.

    Requires: Authentication (JWT token or API key)
    Requires: Development/testing environment

    Note: Permission check intentionally removed to allow clearing rate limit
    even when locked out. User is still authenticated via JWT.
    """
    from intric.worker.redis import get_redis

    current_user = container.user()

    # Permission check removed - endpoint needs to work even if rate limited
    # User is already authenticated via get_container(with_user=True)

    # Safety: Only allow in development/testing environments
    settings = get_settings()
    if not settings.testing:
        raise HTTPException(status_code=404, detail="Not found")

    redis_client = get_redis()
    rate_limit_key = f"rate_limit:audit_session:{current_user.id}:{current_user.tenant_id}"

    try:
        deleted = await redis_client.delete(rate_limit_key)
        if deleted:
            logger.info(f"Rate limit reset for user {current_user.id}")
        else:
            logger.info(f"No rate limit found for user {current_user.id}")
    except redis.exceptions.RedisError as e:
        logger.error(f"Failed to reset rate limit: {e}", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Rate limiting service temporarily unavailable. Please try again."
        )

    return Response(status_code=204)


@router.post("/access-session", response_model=AccessJustificationResponse)
async def create_access_session(
    request: AccessJustificationRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Create an audit access session with justification.

    Stores the access justification securely in Redis (server-side) instead of
    exposing it in URL parameters. Returns an HTTP-only cookie with session ID.

    Security Features:
    - Justification never appears in URLs or browser history
    - Session ID stored in HTTP-only cookie (prevents XSS)
    - Automatic expiration after 1 hour
    - Tenant isolation validation
    - Instant revocation capability

    Requires: Authentication (JWT token or API key)
    Requires: Admin permissions

    Returns: Session creation confirmation with HTTP-only cookie set
    """
    from intric.roles.permissions import Permission, validate_permission
    from intric.worker.redis import get_redis

    current_user = container.user()

    # Validate admin permissions
    validate_permission(current_user, Permission.ADMIN)

    # Input validation for security and resource protection
    if len(request.category) > 64:
        raise HTTPException(
            status_code=400,
            detail="Category too long (maximum 64 characters)"
        )
    if len(request.description) > 2048:
        raise HTTPException(
            status_code=400,
            detail="Description too long (maximum 2048 characters)"
        )
    if len(request.description.strip()) < 10:
        raise HTTPException(
            status_code=400,
            detail="Description too short (minimum 10 characters)"
        )

    # Rate limiting: 5 sessions per hour per user (atomic operation to prevent race conditions)
    redis_client = get_redis()  # Renamed to avoid shadowing redis module
    rate_limit_key = f"rate_limit:audit_session:{current_user.id}:{current_user.tenant_id}"

    # Lua script for atomic INCR + EXPIRE to prevent zombie keys
    rate_limit_script = """
    local count = redis.call('INCR', KEYS[1])
    if count == 1 then
        redis.call('EXPIRE', KEYS[1], ARGV[1])
    end
    return count
    """

    try:
        # Execute Lua script atomically - prevents zombie keys if EXPIRE fails
        count = await redis_client.eval(
            rate_limit_script,
            1,  # number of keys
            rate_limit_key,  # KEYS[1]
            3600  # ARGV[1] - TTL in seconds
        )

        # Check limit after increment
        if count > 5:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Maximum 5 audit session creations per hour allowed."
            )
    except redis.exceptions.RedisError as e:
        logger.error(f"Rate limit Redis error: {e}", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Rate limiting service temporarily unavailable. Please try again."
        )

    # Create session in Redis (using injected service)
    session_service = container.audit_session_service()
    session_id = await session_service.create_session(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        category=request.category,
        description=request.description,
    )

    # Sanitize inputs for audit logging (prevent log injection)
    safe_category = request.category.replace("\n", " ").replace("\r", " ")
    safe_description = request.description.replace("\n", " ").replace("\r", " ")

    # Audit log session creation for compliance (with error handling to prevent orphaned sessions)
    audit_service = container.audit_service()
    try:
        await audit_service.log(
            tenant_id=current_user.tenant_id,
            actor_id=current_user.id,
            action=ActionType.AUDIT_SESSION_CREATED,
            entity_type=EntityType.AUDIT_LOG,
            entity_id=current_user.tenant_id,
            description=f"Created audit access session: {safe_category}",
            metadata={
                "session_id": session_id,
                "justification": {
                    "category": safe_category,
                    "description": safe_description,
                },
                "rate_limit": {
                    "count": count,
                    "max": 5,
                    "period_seconds": 3600,
                }
            }
        )
    except Exception as e:
        # If audit logging fails, revoke the session to prevent orphaned sessions
        logger.error(f"Audit logging failed, revoking session: {e}", exc_info=True)
        await session_service.revoke_session(session_id)
        raise HTTPException(
            status_code=503,
            detail="Audit logging service temporarily unavailable. Please try again."
        )

    # Create response with session cookie
    response = JSONResponse(
        content={
            "status": "session_created",
            "message": "Access session created successfully",
        }
    )

    # Environment-aware cookie configuration
    settings = get_settings()
    is_dev = settings.testing

    # Set HTTP-only cookie with session ID
    response.set_cookie(
        key="audit_session_id",
        value=session_id,
        httponly=True,  # Always prevents JavaScript access (XSS protection)
        secure=not is_dev,  # False for localhost HTTP, True for production HTTPS
        samesite="lax" if is_dev else "none",  # Lax works for same-domain cross-port
        max_age=3600,  # 1 hour (matches Redis TTL)
        path="/api/v1",
    )

    return response


@router.get("/logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    request: Request,
    actor_id: Optional[UUID] = Query(None, description="Filter by actor"),
    action: Optional[ActionType] = Query(None, description="Filter by action type"),
    from_date: Optional[datetime] = Query(None, description="Filter from date"),
    to_date: Optional[datetime] = Query(None, description="Filter to date"),
    search: Optional[str] = Query(
        None,
        min_length=3,
        max_length=100,
        description="Search entity names in log descriptions (min 3 chars)"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=1000, description="Page size"),
    container: Container = Depends(get_container(with_user=True)),
):
    """
    List audit logs for the authenticated user's tenant.

    Security:
    - Requires active audit access session (via HTTP-only cookie)
    - Session must contain valid justification
    - Justification stored server-side (Redis) - never in URLs

    Access Control:
    - Admins only: View all actions in their tenant

    Requires: Authentication (JWT token or API key)
    Requires: Admin permissions
    Requires: Active audit access session with justification
    """
    from intric.roles.permissions import Permission, validate_permission

    current_user = container.user()
    session = container.session()

    # DEBUG: Log user info before permission check
    logger.info(
        f"Audit access attempt - User: {current_user.id}, "
        f"Email: {current_user.email}, Permissions: {list(current_user.permissions)}"
    )

    # Validate admin permissions
    validate_permission(current_user, Permission.ADMIN)
    logger.info("✓ Permission check passed")

    # Get and validate audit access session (using injected service)
    session_id = request.cookies.get("audit_session_id")

    # DEBUG: Log cookie status
    logger.info(
        f"Cookie check - session_id present: {session_id is not None}, "
        f"all cookies: {list(request.cookies.keys())}"
    )

    if not session_id:
        logger.warning("✗ 401 at line 323: No audit_session_id cookie in request")
        raise HTTPException(
            status_code=401,  # Changed from 403 for better frontend handling
            detail="Audit access requires justification. Please provide an access reason.",
            headers={"X-Error-Code": "AUDIT_SESSION_REQUIRED"}
        )

    # DEBUG: Log before session validation
    logger.info(f"Validating session {session_id[:8]}... for user {current_user.id}")

    session_service = container.audit_session_service()
    audit_session = await session_service.validate_session(
        session_id, current_user.id, current_user.tenant_id
    )

    if not audit_session:
        logger.warning(f"✗ 401 at line 335: Session validation failed for {session_id[:8]}...")
        raise HTTPException(
            status_code=401,  # Changed from 403 for better frontend handling
            detail="Invalid or expired session. Please re-authenticate with justification.",
            headers={"X-Error-Code": "AUDIT_SESSION_EXPIRED"}
        )

    logger.info(f"✓ Session validation passed for {session_id[:8]}...")

    # Extend session TTL to keep active users logged in
    await session_service.extend_session(session_id)

    audit_service = container.audit_service()

    # Get the logs first to know how many records were actually returned
    logs, total_count = await audit_service.get_logs(
        tenant_id=current_user.tenant_id,
        actor_id=actor_id,
        action=action,
        from_date=from_date,
        to_date=to_date,
        search=search,
        page=page,
        page_size=page_size,
    )

    total_pages = (total_count + page_size - 1) // page_size
    records_returned = len(logs)

    # Build comprehensive metadata for compliance tracking
    metadata = {
        # Core access information
        "records_returned": records_returned,
        "total_matching_records": total_count,
        "viewing_page": page,
        "total_pages": total_pages,
        "has_more_pages": page < total_pages,
    }

    # Add applied filters (only non-default values to show intent)
    filters_applied = {}
    if actor_id:
        filters_applied["actor_id"] = str(actor_id)
    if action:
        filters_applied["action_type"] = action.value
    if from_date:
        filters_applied["from_date"] = from_date.isoformat()
    if to_date:
        filters_applied["to_date"] = to_date.isoformat()
    if search:
        filters_applied["search"] = search

    if filters_applied:
        metadata["filters_applied"] = filters_applied
        metadata["filtered_view"] = True
    else:
        metadata["filtered_view"] = False
        metadata["access_type"] = "full_audit_review"

    # Add context about what period of logs they're seeing
    if logs:
        oldest_log_date = logs[-1].created_at
        newest_log_date = logs[0].created_at
        metadata["date_range_viewed"] = {
            "oldest": oldest_log_date.isoformat(),
            "newest": newest_log_date.isoformat()
        }

    # Add access justification from session (always present due to validation above)
    metadata["access_justification"] = {
        "category": audit_session["category"],
        "description": audit_session["description"],
        "timestamp": audit_session["created_at"],
        "session_id": session_id,  # For audit trail
    }

    # Build concise, human-readable description
    description_parts = ["Viewed audit logs"]
    if filters_applied:
        description_parts.append("(filtered")
        if page > 1:
            description_parts.append(f", page {page}")
        description_parts.append(")")
    elif page > 1:
        description_parts.append(f"(page {page})")
    description = " ".join(description_parts)

    # Log the audit access with comprehensive metadata
    await audit_service.log(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.AUDIT_LOG_VIEWED,
        entity_type=EntityType.AUDIT_LOG,
        entity_id=current_user.tenant_id,  # Use tenant_id as entity_id for audit logs
        description=description,
        metadata=metadata
    )

    # Enrich logs with actor information for UI display
    enriched_logs = await _enrich_logs_with_actor_info(logs, session)

    # Create response object
    response_data = AuditLogListResponse(
        logs=enriched_logs,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )

    # Convert to JSON response so we can set cookie
    response = JSONResponse(
        content=response_data.model_dump(mode='json'),
        status_code=200
    )

    # Environment-aware cookie configuration
    settings = get_settings()
    is_dev = settings.testing

    # Re-set cookie to extend browser expiry (matches server-side TTL extension)
    # This prevents unexpected logout despite active use
    response.set_cookie(
        key="audit_session_id",
        value=session_id,
        httponly=True,  # Always prevents JavaScript access (XSS protection)
        secure=not is_dev,  # False for localhost HTTP, True for production HTTPS
        samesite="lax" if is_dev else "none",  # Lax works for same-domain cross-port
        max_age=3600,  # Fresh 1 hour window
        path="/api/v1",
    )

    return response


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
    Requires: Admin permissions
    Security: Only returns logs for the authenticated user's tenant
    """
    from intric.roles.permissions import Permission, validate_permission

    current_user = container.user()
    session = container.session()

    # Validate admin permissions
    validate_permission(current_user, Permission.ADMIN)

    audit_service = container.audit_service()

    # Get the logs first to know actual results
    logs, total_count = await audit_service.get_user_logs(
        tenant_id=current_user.tenant_id,
        user_id=user_id,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )

    total_pages = (total_count + page_size - 1) // page_size
    records_returned = len(logs)

    # Build comprehensive metadata for compliance tracking
    metadata = {
        "target_user_id": str(user_id),
        "purpose": "GDPR Article 15 data subject access request",
        "records_returned": records_returned,
        "total_matching_records": total_count,
        "viewing_page": page,
        "total_pages": total_pages,
        "has_more_pages": page < total_pages,
    }

    if from_date:
        metadata["from_date"] = from_date.isoformat()
    if to_date:
        metadata["to_date"] = to_date.isoformat()

    # Add context about what period of logs they're seeing
    if logs:
        oldest_log_date = logs[-1].created_at
        newest_log_date = logs[0].created_at
        metadata["date_range_viewed"] = {
            "oldest": oldest_log_date.isoformat(),
            "newest": newest_log_date.isoformat()
        }

    # Build concise description for GDPR access
    description = "GDPR export: Viewed user audit logs"
    if page > 1:
        description += f" (page {page})"

    # Log the GDPR export access
    await audit_service.log(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.AUDIT_LOG_VIEWED,
        entity_type=EntityType.USER,
        entity_id=user_id,
        description=description,
        metadata=metadata
    )

    # Enrich logs with actor information for UI display
    enriched_logs = await _enrich_logs_with_actor_info(logs, session)

    return AuditLogListResponse(
        logs=enriched_logs,
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
    format: str = Query("csv", description="Export format: csv or json"),
    max_records: Optional[int] = Query(
        None,
        ge=1,
        le=100000,
        description="Maximum records to export (default: 50000, max: 100000)"
    ),
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Export audit logs to CSV or JSON Lines format.

    Supported formats:
    - csv: Comma-separated values (default, Excel-compatible)
    - json: JSON Lines format (one JSON object per line, for large exports)

    Use user_id for GDPR Article 15 data subject access requests.

    Memory Protection:
    - Default limit: 50,000 records (configurable via max_records parameter)
    - Response includes X-Records-Truncated header if limit was hit
    - Response includes X-Total-Records header with total matching count

    Requires: Authentication (JWT token or API key via X-API-Key header)
    Requires: Admin permissions
    Security: Only exports logs for the authenticated user's tenant
    """
    from intric.audit.domain.constants import MAX_EXPORT_RECORDS_DEFAULT
    from intric.roles.permissions import Permission, validate_permission

    current_user = container.user()

    # Validate admin permissions
    validate_permission(current_user, Permission.ADMIN)

    audit_service = container.audit_service()

    # Normalize format
    export_format = format.lower().strip()
    if export_format not in ["csv", "json"]:
        export_format = "csv"  # Default to CSV for invalid formats

    # Apply default export limit if not specified
    effective_max_records = max_records if max_records is not None else MAX_EXPORT_RECORDS_DEFAULT

    # Build comprehensive metadata for compliance tracking
    metadata = {
        "export_format": export_format.upper(),
        "export_type": "GDPR_EXPORT" if user_id else "AUDIT_EXPORT",
    }

    # Add applied filters to show what was exported
    filters_applied = {}
    if user_id:
        filters_applied["user_id"] = str(user_id)
        metadata["purpose"] = "GDPR Article 15 data portability"
    if actor_id:
        filters_applied["actor_id"] = str(actor_id)
    if action:
        filters_applied["action_type"] = action.value
    if from_date:
        filters_applied["from_date"] = from_date.isoformat()
    if to_date:
        filters_applied["to_date"] = to_date.isoformat()

    if filters_applied:
        metadata["filters_applied"] = filters_applied
        metadata["filtered_export"] = True
    else:
        metadata["filtered_export"] = False
        metadata["export_scope"] = "full_audit_trail"

    # Count records that will be exported (for compliance tracking)
    if user_id:
        export_logs, export_count = await audit_service.get_user_logs(
            tenant_id=current_user.tenant_id,
            user_id=user_id,
            from_date=from_date,
            to_date=to_date,
            page=1,
            page_size=1,  # Just get count
        )
    else:
        export_logs, export_count = await audit_service.get_logs(
            tenant_id=current_user.tenant_id,
            actor_id=actor_id,
            action=action,
            from_date=from_date,
            to_date=to_date,
            page=1,
            page_size=1,  # Just get count
        )

    # Determine if truncation will occur
    is_truncated = export_count > effective_max_records
    records_exported = min(export_count, effective_max_records)

    metadata["total_records_exported"] = records_exported
    metadata["total_records_matching"] = export_count
    metadata["was_truncated"] = is_truncated
    metadata["max_records_limit"] = effective_max_records

    # Build concise description for export
    if user_id:
        description = f"GDPR export: User audit logs ({export_format.upper()})"
    else:
        description = f"Exported audit logs ({export_format.upper()}"
        if filters_applied:
            description += ", filtered"
        description += ")"

    if is_truncated:
        description += f" [truncated to {effective_max_records} of {export_count}]"

    # Log the export with comprehensive metadata
    await audit_service.log(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.AUDIT_LOG_EXPORTED,
        entity_type=EntityType.AUDIT_LOG,
        entity_id=current_user.tenant_id,
        description=description,
        metadata=metadata
    )

    # Generate timestamp for filename
    timestamp = datetime.now().isoformat().split('T')[0]

    # Build response headers for truncation info
    response_headers = {
        "X-Total-Records": str(export_count),
        "X-Records-Truncated": "true" if is_truncated else "false",
        "X-Max-Records-Limit": str(effective_max_records),
    }

    if export_format == "json":
        content = await audit_service.export_jsonl(
            tenant_id=current_user.tenant_id,
            user_id=user_id,
            actor_id=actor_id,
            action=action,
            from_date=from_date,
            to_date=to_date,
            max_records=effective_max_records,
        )
        response_headers["Content-Disposition"] = f"attachment; filename=audit_logs_{timestamp}.jsonl"
        return Response(
            content=content,
            media_type="application/x-ndjson",
            headers=response_headers,
        )
    else:
        content = await audit_service.export_csv(
            tenant_id=current_user.tenant_id,
            user_id=user_id,
            actor_id=actor_id,
            action=action,
            from_date=from_date,
            to_date=to_date,
            max_records=effective_max_records,
        )
        response_headers["Content-Disposition"] = f"attachment; filename=audit_logs_{timestamp}.csv"
        return Response(
            content=content,
            media_type="text/csv",
            headers=response_headers,
        )


# ============================================================================
# Async Export Endpoints (Background Job with Progress Tracking)
# ============================================================================


@router.post("/logs/export/async", response_model=ExportJobResponse)
async def request_async_export(
    request: ExportJobRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Request async export of audit logs.

    Returns immediately with a job_id. Poll /logs/export/{job_id}/status for progress.
    Download via /logs/export/{job_id}/download when complete.

    Advantages over sync export:
    - Handles 1M-10M+ records without timeout
    - Progress tracking for long exports
    - Cancellation support
    - Constant memory usage (~50MB)

    Limitations:
    - Max 2 concurrent exports per tenant
    - Files auto-deleted after 24 hours

    Requires: Authentication (JWT token or API key via X-API-Key header)
    Requires: Admin permissions
    """
    from uuid import uuid4

    from intric.audit.application.audit_task_params import AuditExportTaskParams, ExportFormat
    from intric.audit.infrastructure.export_job_manager import ExportJobManager
    from intric.jobs.job_manager import job_manager
    from intric.roles.permissions import Permission, validate_permission

    current_user = container.user()
    settings = get_settings()

    # Validate admin permissions
    validate_permission(current_user, Permission.ADMIN)

    # Get Redis client and create job manager
    redis = container.redis_client()
    export_job_manager = ExportJobManager(redis)

    # Check concurrent export limit
    active_jobs = await export_job_manager.count_active_jobs(current_user.tenant_id)
    if active_jobs >= settings.export_max_concurrent_per_tenant:
        raise HTTPException(
            status_code=429,
            detail=f"Maximum {settings.export_max_concurrent_per_tenant} concurrent exports allowed. "
                   f"Please wait for existing exports to complete or cancel them.",
        )

    # Validate and normalize format
    export_format = request.format.lower().strip()
    if export_format == "json":
        export_format = "jsonl"  # Accept "json" as alias for "jsonl"
    if export_format not in ["csv", "jsonl"]:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid export format: '{request.format}'. Supported formats: csv, json, jsonl",
        )

    # Generate job ID
    job_id = uuid4()

    # Create job in Redis
    await export_job_manager.create_job(
        job_id=job_id,
        tenant_id=current_user.tenant_id,
        format=export_format,
    )

    # Build task params
    task_params = AuditExportTaskParams(
        tenant_id=current_user.tenant_id,
        user_id=request.user_id,
        actor_id=request.actor_id,
        action=request.action.value if request.action else None,
        from_date=request.from_date,
        to_date=request.to_date,
        format=ExportFormat(export_format),
        max_records=request.max_records,
    )

    # Enqueue to ARQ
    await job_manager.enqueue(
        "export_audit_logs",
        job_id=str(job_id),
        params=task_params.to_dict(),
    )

    # Log the export request
    audit_repo = AuditLogRepositoryImpl(container.session())
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.AUDIT_LOG_EXPORTED,
        entity_type=EntityType.AUDIT_LOG,
        entity_id=job_id,
        description=f"Async export requested ({export_format.upper()})",
        metadata={
            "export_format": export_format.upper(),
            "export_type": "GDPR_EXPORT" if request.user_id else "AUDIT_EXPORT",
            "job_id": str(job_id),
            "async": True,
        },
    )

    return ExportJobResponse(
        job_id=job_id,
        status="pending",
        message="Export job created. Poll /logs/export/{job_id}/status for progress.",
    )


@router.get("/logs/export/{job_id}/status", response_model=ExportJobStatusResponse)
async def get_export_status(
    job_id: UUID = Path(..., description="Export job ID"),
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Get export job status with progress.

    Poll this endpoint to track export progress.
    When status is 'completed', use the download_url to get the file.

    Requires: Authentication (JWT token or API key via X-API-Key header)
    Requires: Admin permissions
    """
    from intric.audit.infrastructure.export_job_manager import ExportJobManager
    from intric.roles.permissions import Permission, validate_permission

    current_user = container.user()

    # Validate admin permissions
    validate_permission(current_user, Permission.ADMIN)

    # Get job status from Redis
    redis = container.redis_client()
    export_job_manager = ExportJobManager(redis)

    job = await export_job_manager.get_job(current_user.tenant_id, job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Export job not found or expired",
        )

    # Build download URL if completed
    download_url = None
    if job.status.value == "completed" and job.file_path:
        download_url = f"/api/v1/audit/logs/export/{job_id}/download"

    return ExportJobStatusResponse(
        job_id=job.job_id,
        status=job.status.value,
        progress=job.progress,
        total_records=job.total_records,
        processed_records=job.processed_records,
        format=job.format,
        file_size_bytes=job.file_size_bytes,
        error_message=job.error_message,
        download_url=download_url,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        expires_at=job.expires_at,
    )


@router.get("/logs/export/{job_id}/download")
async def download_export(
    job_id: UUID = Path(..., description="Export job ID"),
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Download completed export file.

    Only available when job status is 'completed'.
    Files are auto-deleted after 24 hours.

    Requires: Authentication (JWT token or API key via X-API-Key header)
    Requires: Admin permissions
    """
    import os

    from fastapi.responses import FileResponse

    from intric.audit.infrastructure.export_job_manager import ExportJobManager
    from intric.roles.permissions import Permission, validate_permission

    current_user = container.user()

    # Validate admin permissions
    validate_permission(current_user, Permission.ADMIN)

    # Get job from Redis
    redis = container.redis_client()
    export_job_manager = ExportJobManager(redis)

    job = await export_job_manager.get_job(current_user.tenant_id, job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Export job not found or expired",
        )

    if job.status.value != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Export job is not completed. Current status: {job.status.value}",
        )

    if not job.file_path or not os.path.exists(job.file_path):
        raise HTTPException(
            status_code=404,
            detail="Export file not found. It may have been cleaned up.",
        )

    # Generate filename
    timestamp = job.created_at.strftime("%Y-%m-%d")
    extension = "csv" if job.format == "csv" else "jsonl"
    filename = f"audit_logs_{timestamp}.{extension}"

    # Determine media type
    media_type = "text/csv" if job.format == "csv" else "application/x-ndjson"

    return FileResponse(
        path=job.file_path,
        filename=filename,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Total-Records": str(job.total_records),
        },
    )


@router.post("/logs/export/{job_id}/cancel")
async def cancel_export(
    job_id: UUID = Path(..., description="Export job ID"),
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Cancel an in-progress export.

    Only works for jobs in 'pending' or 'processing' state.
    The worker will stop processing and clean up the partial file.

    Requires: Authentication (JWT token or API key via X-API-Key header)
    Requires: Admin permissions
    """
    from intric.audit.infrastructure.export_job_manager import ExportJobManager
    from intric.roles.permissions import Permission, validate_permission

    current_user = container.user()

    # Validate admin permissions
    validate_permission(current_user, Permission.ADMIN)

    # Get job manager
    redis = container.redis_client()
    export_job_manager = ExportJobManager(redis)

    # Try to cancel
    success = await export_job_manager.set_cancelled(current_user.tenant_id, job_id)

    if not success:
        # Check if job exists
        job = await export_job_manager.get_job(current_user.tenant_id, job_id)
        if not job:
            raise HTTPException(
                status_code=404,
                detail="Export job not found or expired",
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Job in '{job.status.value}' state cannot be cancelled. "
                       f"Only 'pending' or 'processing' jobs can be cancelled.",
            )

    return {"status": "cancellation_requested", "message": "Export job cancellation requested"}


@router.get("/retention-policy", response_model=RetentionPolicyResponse)
async def get_retention_policy(
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Get the current retention policy for your tenant.

    Returns audit log retention policy configuration.

    Requires: Authentication (JWT token or API key via X-API-Key header)
    Requires: Admin permissions
    """
    from intric.audit.application.retention_service import RetentionService
    from intric.roles.permissions import Permission, validate_permission

    current_user = container.user()
    session = container.session()

    # Validate admin permissions
    validate_permission(current_user, Permission.ADMIN)

    retention_service = RetentionService(session)
    policy = await retention_service.get_policy(current_user.tenant_id)

    # Map to response model (convert from RetentionPolicyModel to RetentionPolicyResponse)
    return RetentionPolicyResponse.model_validate(policy.model_dump())


@router.put("/retention-policy", response_model=RetentionPolicyResponse)
async def update_retention_policy(
    request: RetentionPolicyUpdateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Update the audit log retention policy for your tenant.

    Configure audit log retention for compliance and security tracking.

    Audit Log Retention:
    - Minimum: 1 day (Recommended: 90+ days for compliance)
    - Maximum: 2555 days (~7 years, Swedish statute of limitations)
    - Default: 365 days (Swedish Arkivlagen)

    Note: Conversation retention is configured at the Assistant, App, or Space level.
    Tenant-level conversation retention has been removed to prevent accidental data loss.

    The system automatically runs a daily job to delete audit logs older than
    the retention period.

    Requires: Authentication (JWT token or API key via X-API-Key header)
    Requires: Admin permissions
    """
    from intric.audit.application.retention_service import RetentionService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.roles.permissions import Permission, validate_permission

    current_user = container.user()
    session = container.session()

    # Validate admin permissions
    validate_permission(current_user, Permission.ADMIN)

    retention_service = RetentionService(session)

    # Get old policy for change tracking
    old_policy = await retention_service.get_policy(current_user.tenant_id)

    # Update policy
    policy = await retention_service.update_policy(
        tenant_id=current_user.tenant_id,
        retention_days=request.retention_days,
        # Conversation retention removed from API - only settable at Assistant/App/Space level
    )

    # Audit logging for retention policy change
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.TENANT_SETTINGS_UPDATED,
        entity_type=EntityType.TENANT_SETTINGS,
        entity_id=current_user.tenant_id,
        description=f"Updated audit log retention policy from {old_policy.retention_days} to {policy.retention_days} days",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "tenant_id": str(current_user.tenant_id),
                "policy_type": "audit_log_retention",
            },
            "changes": {
                "retention_days": {
                    "old": old_policy.retention_days,
                    "new": policy.retention_days,
                }
            },
        },
    )

    # Map to response model (convert from RetentionPolicyModel to RetentionPolicyResponse)
    return RetentionPolicyResponse.model_validate(policy.model_dump())
