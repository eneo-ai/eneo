from datetime import datetime
from typing import Optional
from uuid import UUID

from intric.base.base_entity import Entity


# Auth method constants
AUTH_METHOD_TENANT_APP = "tenant_app"
AUTH_METHOD_SERVICE_ACCOUNT = "service_account"


class TenantSharePointApp(Entity):
    """Azure AD application credentials for organization-wide SharePoint access.

    Supports two authentication methods:
    - tenant_app: Application permissions using client credentials flow (Sites.Read.All)
    - service_account: Delegated permissions using a dedicated service account with
      OAuth refresh token flow. Recommended for granular access control.

    One app per tenant, shared across all shared/organization space integrations.
    """

    def __init__(
        self,
        tenant_id: UUID,
        client_id: str,
        client_secret: str,  # Decrypted in memory, encrypted at rest
        tenant_domain: str,
        is_active: bool = True,
        auth_method: str = AUTH_METHOD_TENANT_APP,
        certificate_path: Optional[str] = None,
        service_account_refresh_token: Optional[str] = None,  # Decrypted in memory
        service_account_email: Optional[str] = None,
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
        self.auth_method = auth_method
        self.service_account_refresh_token = service_account_refresh_token
        self.service_account_email = service_account_email
        self.created_by = created_by

    def is_service_account(self) -> bool:
        """Check if this app uses service account authentication."""
        return self.auth_method == AUTH_METHOD_SERVICE_ACCOUNT

    def is_tenant_app(self) -> bool:
        """Check if this app uses tenant app (application permissions) authentication."""
        return self.auth_method == AUTH_METHOD_TENANT_APP

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

    def update_service_account(
        self, refresh_token: str, email: str
    ) -> None:
        """Update service account credentials."""
        self.auth_method = AUTH_METHOD_SERVICE_ACCOUNT
        self.service_account_refresh_token = refresh_token
        self.service_account_email = email

    def update_refresh_token(self, refresh_token: str) -> None:
        """Update the service account refresh token (called after token refresh)."""
        self.service_account_refresh_token = refresh_token
