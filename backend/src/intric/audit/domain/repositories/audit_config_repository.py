"""Audit category configuration repository interface."""

from abc import ABC, abstractmethod
from uuid import UUID


class AuditConfigRepository(ABC):
    """Repository interface for audit category configuration."""

    @abstractmethod
    async def find_by_tenant(self, tenant_id: UUID) -> list[tuple[str, bool]]:
        """
        Get all category configurations for a tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            List of tuples (category, enabled) for all 7 categories
        """
        pass

    @abstractmethod
    async def find_by_tenant_and_category(
        self, tenant_id: UUID, category: str
    ) -> tuple[str, bool] | None:
        """
        Get configuration for a specific category.

        Args:
            tenant_id: Tenant identifier
            category: Category name

        Returns:
            Tuple of (category, enabled) or None if not found
        """
        pass

    @abstractmethod
    async def update(self, tenant_id: UUID, category: str, enabled: bool) -> None:
        """
        Update or insert category configuration (upsert).

        Args:
            tenant_id: Tenant identifier
            category: Category name
            enabled: New enabled state
        """
        pass
