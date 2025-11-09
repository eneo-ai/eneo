"""Audit logging worker task."""

from sqlalchemy.exc import IntegrityError

from intric.audit.application.audit_task_params import AuditLogTaskParams
from intric.audit.domain.audit_log import AuditLog
from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from intric.database.database import AsyncSession
from intric.main.logging import get_logger

logger = get_logger(__name__)


async def log_audit_event_task(
    job_id: str,
    params: dict,
    session: AsyncSession,
) -> dict:
    """
    Worker task to persist audit log to database.

    Args:
        job_id: ARQ job ID
        params: Audit log parameters (validated into AuditLogTaskParams)
        session: Database session

    Returns:
        Dictionary with job result (audit_log_id)
    """
    # Validate params
    task_params = AuditLogTaskParams(**params)

    # Create audit log
    audit_log = AuditLog(
        id=task_params.entity_id,  # Reuse for simplicity, or generate new
        tenant_id=task_params.tenant_id,
        actor_id=task_params.actor_id,
        actor_type=task_params.actor_type,
        action=task_params.action,
        entity_type=task_params.entity_type,
        entity_id=task_params.entity_id,
        timestamp=task_params.timestamp,
        description=task_params.description,
        metadata=task_params.metadata,
        outcome=task_params.outcome,
        ip_address=task_params.ip_address,
        user_agent=task_params.user_agent,
        request_id=task_params.request_id,
        error_message=task_params.error_message,
    )

    # Persist to database
    repository = AuditLogRepositoryImpl(session)

    try:
        created_log = await repository.create(audit_log)
    except IntegrityError as e:
        error_detail = str(e)
        # Gracefully handle case where tenant doesn't exist (during registration or after deletion)
        if "audit_logs_tenant_id_fkey" in error_detail:
            logger.warning(
                f"Skipping audit log for non-existent tenant. "
                f"tenant_id={audit_log.tenant_id}, action={audit_log.action.value}, "
                f"entity_type={audit_log.entity_type.value}. "
                f"Tenant may have been deleted or not yet created."
            )
            return {"audit_log_id": None, "skipped": True, "reason": "tenant_not_found"}
        # Re-raise other integrity errors (actor_id FK, unique constraints, etc.)
        raise

    logger.info(
        "Audit log created",
        extra={
            "job_id": job_id,
            "audit_log_id": str(created_log.id),
            "tenant_id": str(created_log.tenant_id),
            "action": created_log.action.value,
        },
    )

    return {"audit_log_id": str(created_log.id)}
