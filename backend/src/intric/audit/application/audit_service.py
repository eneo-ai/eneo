"""Audit logging service."""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from intric.audit.application.audit_config_service import AuditConfigService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.audit_log import AuditLog
from intric.audit.domain.category_mappings import get_category_for_action
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome
from intric.audit.domain.repositories.audit_log_repository import AuditLogRepository
from intric.jobs.job_manager import job_manager


def _sanitize_csv_cell(value: str) -> str:
    """
    Prevent CSV injection attacks.

    Prefixes values starting with special characters (=, +, -, @, tab, carriage return)
    with a single quote to prevent formula execution in Excel and other spreadsheet software.

    Args:
        value: Cell value to sanitize

    Returns:
        Sanitized cell value
    """
    if value and value[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + value
    return value


class AuditService:
    """Service for audit logging operations."""

    def __init__(
        self,
        repository: AuditLogRepository,
        audit_config_service: Optional[AuditConfigService] = None,
    ):
        self.repository = repository
        self.audit_config_service = audit_config_service

    async def log(
        self,
        tenant_id: UUID,
        actor_id: UUID,
        action: ActionType,
        entity_type: EntityType,
        entity_id: UUID,
        description: str,
        metadata: dict,
        outcome: Outcome = Outcome.SUCCESS,
        actor_type: ActorType = ActorType.USER,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[UUID] = None,
        error_message: Optional[str] = None,
    ) -> AuditLog:
        """
        Create an audit log entry.

        Args:
            tenant_id: Tenant ID
            actor_id: User who performed the action
            action: Type of action performed
            entity_type: Type of entity affected
            entity_id: ID of affected entity
            description: Human-readable description
            metadata: Additional context (actor/target snapshots, changes)
            outcome: Success or failure
            actor_type: Type of actor (user, system, api_key)
            ip_address: Client IP address
            user_agent: Client user agent
            request_id: Request correlation ID
            error_message: Error details if outcome is failure

        Returns:
            Created audit log (or None if category is disabled)

        Raises:
            ValueError: If outcome is failure but no error_message provided
        """
        # Check if category is enabled (uses Redis cache for <1ms overhead)
        if self.audit_config_service:
            category = get_category_for_action(action.value)
            enabled = await self.audit_config_service.is_category_enabled(
                tenant_id, category
            )
            if not enabled:
                # Category disabled - skip logging
                return None

        audit_log = AuditLog(
            id=uuid4(),
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            timestamp=datetime.now(timezone.utc),
            description=description,
            metadata=metadata,
            outcome=outcome,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            error_message=error_message,
        )

        return await self.repository.create(audit_log)

    async def get_logs(
        self,
        tenant_id: UUID,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[AuditLog], int]:
        """
        Get audit logs for a tenant with optional filters.

        Args:
            tenant_id: Tenant ID
            actor_id: Filter by actor
            action: Filter by action type
            from_date: Filter from date
            to_date: Filter to date
            page: Page number (1-indexed)
            page_size: Number of logs per page

        Returns:
            Tuple of (logs, total_count)
        """
        return await self.repository.get_logs(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            from_date=from_date,
            to_date=to_date,
            page=page,
            page_size=page_size,
        )

    async def get_user_logs(
        self,
        tenant_id: UUID,
        user_id: UUID,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[AuditLog], int]:
        """
        Get all logs where user is actor OR target (GDPR Article 15 export).

        Args:
            tenant_id: Tenant ID
            user_id: User ID to search for
            from_date: Filter from date
            to_date: Filter to date
            page: Page number (1-indexed)
            page_size: Number of logs per page

        Returns:
            Tuple of (logs, total_count)
        """
        return await self.repository.get_user_logs(
            tenant_id=tenant_id,
            user_id=user_id,
            from_date=from_date,
            to_date=to_date,
            page=page,
            page_size=page_size,
        )

    async def export_csv(
        self,
        tenant_id: UUID,
        user_id: Optional[UUID] = None,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        max_records: Optional[int] = None,
    ) -> str:
        """
        Export audit logs to CSV format with streaming support.

        This method fetches logs in batches of 1000 records to prevent memory exhaustion,
        allowing export of millions of audit logs. For very large exports (>100k records),
        consider using date filters or the export_csv_stream method for HTTP streaming.

        Args:
            tenant_id: Tenant ID
            user_id: Filter for GDPR export (user as actor OR target)
            actor_id: Filter by actor
            action: Filter by action type
            from_date: Filter from date
            to_date: Filter to date
            max_records: Maximum number of records to export (None for unlimited)

        Returns:
            CSV string with audit logs
        """
        import csv
        from io import StringIO

        output = StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            "Timestamp",
            "Actor ID",
            "Actor Type",
            "Action",
            "Entity Type",
            "Entity ID",
            "Description",
            "Outcome",
            "Error Message",
            "Metadata",
        ])

        # Stream logs in batches
        page = 1
        page_size = 1000
        total_exported = 0

        while True:
            # Get batch
            if user_id:
                logs, total_count = await self.get_user_logs(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    from_date=from_date,
                    to_date=to_date,
                    page=page,
                    page_size=page_size,
                )
            else:
                logs, total_count = await self.get_logs(
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    action=action,
                    from_date=from_date,
                    to_date=to_date,
                    page=page,
                    page_size=page_size,
                )

            # No more logs
            if not logs:
                break

            # Write rows (with CSV injection protection)
            for log in logs:
                writer.writerow([
                    log.timestamp.isoformat(),
                    str(log.actor_id),
                    log.actor_type.value,
                    log.action.value,
                    log.entity_type.value,
                    str(log.entity_id),
                    _sanitize_csv_cell(log.description),
                    log.outcome.value,
                    _sanitize_csv_cell(log.error_message or ""),
                    _sanitize_csv_cell(str(log.metadata)),
                ])
                total_exported += 1

                # Check max_records limit
                if max_records and total_exported >= max_records:
                    return output.getvalue()

            # Check if we've reached the end
            if page * page_size >= total_count:
                break

            page += 1

        return output.getvalue()

    async def export_jsonl(
        self,
        tenant_id: UUID,
        user_id: Optional[UUID] = None,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        max_records: Optional[int] = None,
    ) -> str:
        """
        Export audit logs to JSON Lines (JSONL) format.

        JSONL is ideal for large exports as it:
        - Maintains data types (no string conversion)
        - Streams efficiently line-by-line
        - Is machine-readable and easily parsable
        - Works well with log analysis tools (jq, grep, etc.)

        Args:
            tenant_id: Tenant ID
            user_id: Filter for GDPR export (user as actor OR target)
            actor_id: Filter by actor
            action: Filter by action type
            from_date: Filter from date
            to_date: Filter to date
            max_records: Maximum number of records to export (None for unlimited)

        Returns:
            JSONL string with one JSON object per line
        """
        import json
        from io import StringIO

        output = StringIO()
        page = 1
        page_size = 1000
        total_exported = 0

        while True:
            # Get batch
            if user_id:
                logs, total_count = await self.get_user_logs(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    from_date=from_date,
                    to_date=to_date,
                    page=page,
                    page_size=page_size,
                )
            else:
                logs, total_count = await self.get_logs(
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    action=action,
                    from_date=from_date,
                    to_date=to_date,
                    page=page,
                    page_size=page_size,
                )

            # No more logs
            if not logs:
                break

            # Write JSON lines
            for log in logs:
                log_dict = {
                    "id": str(log.id),
                    "tenant_id": str(log.tenant_id),
                    "timestamp": log.timestamp.isoformat(),
                    "actor_id": str(log.actor_id),
                    "actor_type": log.actor_type.value,
                    "action": log.action.value,
                    "entity_type": log.entity_type.value,
                    "entity_id": str(log.entity_id),
                    "description": log.description,
                    "outcome": log.outcome.value,
                    "metadata": log.metadata,
                    "ip_address": log.ip_address,
                    "user_agent": log.user_agent,
                    "request_id": str(log.request_id) if log.request_id else None,
                    "error_message": log.error_message,
                }
                output.write(json.dumps(log_dict) + "\n")
                total_exported += 1

                # Check max_records limit
                if max_records and total_exported >= max_records:
                    return output.getvalue()

            # Check if we've reached the end
            if page * page_size >= total_count:
                break

            page += 1

        return output.getvalue()

    async def log_async(
        self,
        tenant_id: UUID,
        actor_id: UUID,
        action: ActionType,
        entity_type: EntityType,
        entity_id: UUID,
        description: str,
        metadata: dict,
        outcome: Outcome = Outcome.SUCCESS,
        actor_type: ActorType = ActorType.USER,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[UUID] = None,
        error_message: Optional[str] = None,
    ) -> Optional[UUID]:
        """
        Asynchronously create an audit log entry via ARQ worker.

        This method enqueues the audit log to Redis for async processing,
        returning immediately (<10ms latency). The ARQ worker will persist
        the log to PostgreSQL in the background.

        NOTE: If audit category configuration is enabled and the category
        for this action is disabled, returns None and skips logging.

        Args:
            tenant_id: Tenant ID
            actor_id: User who performed the action
            action: Type of action performed
            entity_type: Type of entity affected
            entity_id: ID of affected entity
            description: Human-readable description
            metadata: Additional context (actor/target snapshots, changes)
            outcome: Success or failure
            actor_type: Type of actor (user, system, api_key)
            ip_address: Client IP address
            user_agent: Client user agent
            request_id: Request correlation ID
            error_message: Error details if outcome is failure

        Returns:
            Job ID for tracking the async operation, or None if category disabled

        Raises:
            ValueError: If outcome is failure but no error_message provided
        """
        # Check if category is enabled (uses Redis cache for <1ms overhead)
        if self.audit_config_service:
            category = get_category_for_action(action.value)
            enabled = await self.audit_config_service.is_category_enabled(
                tenant_id, category
            )
            if not enabled:
                # Category disabled - skip logging
                return None

        # Validate
        if outcome == Outcome.FAILURE and not error_message:
            raise ValueError("error_message required when outcome is failure")

        # Create job ID
        job_id = uuid4()

        # Prepare params for ARQ worker
        params = {
            "tenant_id": str(tenant_id),
            "actor_id": str(actor_id),
            "actor_type": actor_type.value,
            "action": action.value,
            "entity_type": entity_type.value,
            "entity_id": str(entity_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "description": description,
            "metadata": metadata,
            "outcome": outcome.value,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "request_id": str(request_id) if request_id else None,
            "error_message": error_message,
        }

        # Enqueue to ARQ
        await job_manager.enqueue("log_audit_event", job_id, params)

        return job_id
