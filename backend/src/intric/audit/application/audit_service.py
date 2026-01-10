"""Audit logging service.

This service handles core audit logging operations:
- Creating audit log entries (sync and async)
- Querying audit logs with filters
- GDPR user log retrieval

Export functionality has been extracted to AuditExportService.
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from intric.audit.application.audit_config_service import AuditConfigService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.audit_log import AuditLog
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome
from intric.audit.domain.repositories.audit_log_repository import AuditLogRepository
from intric.jobs.job_manager import job_manager

if TYPE_CHECKING:
    from intric.feature_flag.feature_flag_service import FeatureFlagService

logger = logging.getLogger(__name__)


class AuditService:
    """Service for audit logging operations."""

    def __init__(
        self,
        repository: AuditLogRepository,
        audit_config_service: Optional[AuditConfigService] = None,
        feature_flag_service: Optional["FeatureFlagService"] = None,
    ):
        self.repository = repository
        self.audit_config_service = audit_config_service
        self.feature_flag_service = feature_flag_service

    async def _should_log_action(self, tenant_id: UUID, action: ActionType) -> bool:
        """
        Check if an action should be logged based on audit configuration.

        Implements 2-stage filtering:
        1. Global audit_logging_enabled feature flag (kill switch)
        2. Action-level configuration (3-level: global → category → action override)

        Args:
            tenant_id: Tenant ID
            action: Action type to check

        Returns:
            True if action should be logged, False otherwise
        """
        # Stage 1: Check global feature flag
        if self.feature_flag_service:
            try:
                audit_logging_enabled = await self.feature_flag_service.check_is_feature_enabled(
                    feature_name="audit_logging_enabled",
                    tenant_id=tenant_id
                )
                if not audit_logging_enabled:
                    # Global audit logging disabled - skip logging entirely
                    return False
            except Exception as e:
                # Graceful degradation: if flag service unavailable, continue logging
                logger.warning(f"Failed to check audit_logging_enabled flag: {e}")

        # Stage 2: Check action-level configuration
        if self.audit_config_service:
            enabled = await self.audit_config_service.is_action_enabled(
                tenant_id, action.value
            )
            if not enabled:
                # Action disabled (by category or by action override) - skip logging
                return False

        return True

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
            Created audit log (or None if action is disabled)

        Raises:
            ValueError: If outcome is failure but no error_message provided
        """
        # Check if action should be logged based on configuration
        should_log = await self._should_log_action(tenant_id, action)
        if not should_log:
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
        actions: Optional[list[ActionType]] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[AuditLog], int]:
        """
        Get audit logs for a tenant with optional filters.

        Args:
            tenant_id: Tenant ID
            actor_id: Filter by actor
            action: Filter by single action type (deprecated, use actions)
            actions: Filter by multiple action types
            from_date: Filter from date
            to_date: Filter to date
            search: Search entity names in description (min 3 chars, case-insensitive)
            page: Page number (1-indexed)
            page_size: Number of logs per page

        Returns:
            Tuple of (logs, total_count)
        """
        return await self.repository.get_logs(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            actions=actions,
            from_date=from_date,
            to_date=to_date,
            search=search,
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

        NOTE: If audit logging is globally disabled or the action is disabled
        (by category or action override), returns None and skips logging.

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
            Job ID for tracking the async operation, or None if action disabled

        Raises:
            ValueError: If outcome is failure but no error_message provided
        """
        # Check if action should be logged based on configuration
        should_log = await self._should_log_action(tenant_id, action)
        if not should_log:
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
