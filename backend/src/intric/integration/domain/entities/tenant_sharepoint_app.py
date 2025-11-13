from datetime import datetime
from typing import Optional
from uuid import UUID

from intric.base.base_entity import Entity


class TenantSharePointApp(Entity):
    """Azure AD application credentials for organization-wide SharePoint access.

    Enables SharePoint integration without person-dependency using application
    permissions (client credentials flow) instead of delegated user permissions.

    One app per tenant, shared across all shared/organization space integrations.
    """

    def __init__(
        self,
        tenant_id: UUID,
        client_id: str,
        client_secret: str,  # Decrypted in memory, encrypted at rest
        tenant_domain: str,
        is_active: bool = True,
        certificate_path: Optional[str] = None,
        created_by: Optional[UUID] = None,
        id: Optional[UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.certificate_path = certificate_path
        self.tenant_domain = tenant_domain
        self.is_active = is_active
        self.created_by = created_by

    def deactivate(self) -> None:
        """Deactivate the app (emergency shutoff)."""
        self.is_active = False

    def activate(self) -> None:
        """Reactivate the app."""
        self.is_active = True

    def update_credentials(
        self, client_id: str, client_secret: str, tenant_domain: str
    ) -> None:
        """Update app credentials."""
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_domain = tenant_domain
