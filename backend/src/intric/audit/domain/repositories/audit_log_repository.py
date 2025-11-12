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
        include_deleted: bool = False,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[AuditLog], int]:
        """
        Get audit logs for a tenant with optional filters.

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
        Soft delete all logs for a user (GDPR erasure).

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
        Soft delete logs older than retention period.

        Returns:
            Number of logs deleted
        """
        pass
