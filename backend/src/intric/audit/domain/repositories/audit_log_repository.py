"""Audit log repository interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
from uuid import UUID

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.audit_log import AuditLog


class AuditLogRepository(ABC):
    """Repository interface for audit log persistence."""

    @abstractmethod
    async def create(self, audit_log: AuditLog) -> AuditLog:
        """Create a new audit log entry."""
        pass

    @abstractmethod
    async def get_by_id(self, audit_log_id: UUID, tenant_id: UUID) -> Optional[AuditLog]:
        """Get audit log by ID with tenant isolation."""
        pass

    @abstractmethod
    async def get_logs(
        self,
        tenant_id: UUID,
        actor_id: Optional[UUID] = None,
        action: Optional[ActionType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        search: Optional[str] = None,
        include_deleted: bool = False,
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
            search: Search entity names in description (case-insensitive ILIKE)
            include_deleted: Include soft-deleted logs
            page: Page number (1-indexed)
            page_size: Number of logs per page

        Returns:
            Tuple of (logs, total_count)
        """
        pass

    @abstractmethod
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
        Get all logs where user is actor OR target (GDPR export).

        Returns:
            Tuple of (logs, total_count)
        """
        pass

    @abstractmethod
    async def soft_delete_by_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
    ) -> int:
        """
        Permanently delete all logs for a user (GDPR Article 17 - Right to Erasure).

        This is a HARD delete - logs are permanently removed and cannot be recovered.

        Returns:
            Number of logs deleted
        """
        pass

    @abstractmethod
    async def soft_delete_old_logs(
        self,
        tenant_id: UUID,
        retention_days: int,
    ) -> int:
        """
        Permanently delete logs older than retention period.

        This is a HARD delete - logs are permanently removed and cannot be recovered.
        Ensures compliance with data retention regulations.

        Returns:
            Number of logs deleted
        """
        pass
