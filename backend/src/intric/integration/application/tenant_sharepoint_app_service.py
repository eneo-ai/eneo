import logging
from typing import Optional
from uuid import UUID

from intric.integration.domain.entities.tenant_sharepoint_app import TenantSharePointApp
from intric.integration.domain.repositories.tenant_sharepoint_app_repo import (
    TenantSharePointAppRepository
)

logger = logging.getLogger(__name__)


class TenantSharePointAppService:
    """Service for managing tenant SharePoint application credentials."""

    def __init__(self, tenant_app_repo: TenantSharePointAppRepository):
        self.tenant_app_repo = tenant_app_repo

    async def get_active_app_for_tenant(
        self,
        tenant_id: UUID
    ) -> Optional[TenantSharePointApp]:
        """Get the active SharePoint app configuration for a tenant.

        Returns None if no app is configured or if the app is deactivated.
        """
        app = await self.tenant_app_repo.get_by_tenant(tenant_id)

        if app and not app.is_active:
            logger.warning(f"SharePoint app for tenant {tenant_id} is deactivated")
            return None

        return app

    async def configure_tenant_app(
        self,
        tenant_id: UUID,
        client_id: str,
        client_secret: str,
        tenant_domain: str,
        created_by: UUID,
        certificate_path: Optional[str] = None,
    ) -> TenantSharePointApp:
        """Configure or update the SharePoint app for a tenant.

        If an app already exists, updates it. Otherwise, creates a new one.

        Args:
            tenant_id: The tenant ID
            client_id: Azure AD application (client) ID
            client_secret: Azure AD application client secret
            tenant_domain: Azure AD tenant domain (e.g., "contoso.onmicrosoft.com")
            created_by: User ID of the admin configuring the app
            certificate_path: Optional path to certificate for cert-based auth

        Returns:
            The configured tenant SharePoint app
        """
        # Check if app already exists
        existing_app = await self.tenant_app_repo.get_by_tenant(tenant_id)

        if existing_app:
            logger.info(f"Updating existing SharePoint app for tenant {tenant_id}")
            existing_app.update_credentials(
                client_id=client_id,
                client_secret=client_secret,
                tenant_domain=tenant_domain
            )
            if certificate_path:
                existing_app.certificate_path = certificate_path

            existing_app.activate()  # Ensure it's active after update
            return await self.tenant_app_repo.update(existing_app)
        else:
            logger.info(f"Creating new SharePoint app for tenant {tenant_id}")
            new_app = TenantSharePointApp(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret,
                tenant_domain=tenant_domain,
                certificate_path=certificate_path,
                created_by=created_by,
                is_active=True
            )
            return await self.tenant_app_repo.create(new_app)

    async def deactivate_app(
        self,
        tenant_id: UUID
    ) -> bool:
        """Deactivate the SharePoint app for a tenant (emergency shutoff).

        This prevents the app from being used for authentication without deleting
        the credentials, allowing for quick reactivation if needed.

        Returns:
            True if deactivated, False if not found
        """
        logger.warning(f"Deactivating SharePoint app for tenant {tenant_id}")
        return await self.tenant_app_repo.deactivate(tenant_id)

    async def delete_app(
        self,
        tenant_id: UUID
    ) -> bool:
        """Delete the SharePoint app configuration for a tenant.

        WARNING: This will break all integrations using this app for authentication.
        Use deactivate_app() for a safer emergency shutoff.

        Returns:
            True if deleted, False if not found
        """
        app = await self.tenant_app_repo.get_by_tenant(tenant_id)
        if not app:
            return False

        logger.warning(f"Deleting SharePoint app for tenant {tenant_id}")
        return await self.tenant_app_repo.delete(app.id)
