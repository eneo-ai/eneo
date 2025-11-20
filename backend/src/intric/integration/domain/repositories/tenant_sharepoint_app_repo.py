from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from intric.integration.domain.entities.tenant_sharepoint_app import TenantSharePointApp


class TenantSharePointAppRepository(ABC):
    """Repository for managing tenant SharePoint application credentials."""

    @abstractmethod
    async def get_by_tenant(
        self,
        tenant_id: UUID
    ) -> "Optional[TenantSharePointApp]":
        """Get the SharePoint app configuration for a tenant.

        Returns None if no app is configured for this tenant.
        """
        ...

    @abstractmethod
    async def get_by_id(
        self,
        app_id: UUID
    ) -> "Optional[TenantSharePointApp]":
        """Get SharePoint app by ID."""
        ...

    @abstractmethod
    async def create(
        self,
        app: "TenantSharePointApp"
    ) -> "TenantSharePointApp":
        """Create a new tenant SharePoint app configuration.

        Raises:
            ValueError: If app already exists for this tenant
        """
        ...

    @abstractmethod
    async def update(
        self,
        app: "TenantSharePointApp"
    ) -> "TenantSharePointApp":
        """Update an existing tenant SharePoint app configuration."""
        ...

    @abstractmethod
    async def delete(
        self,
        app_id: UUID
    ) -> bool:
        """Delete a tenant SharePoint app configuration.

        Returns:
            True if deleted, False if not found
        """
        ...

    @abstractmethod
    async def deactivate(
        self,
        tenant_id: UUID
    ) -> bool:
        """Deactivate the SharePoint app for a tenant (emergency shutoff).

        Returns:
            True if deactivated, False if not found
        """
        ...
