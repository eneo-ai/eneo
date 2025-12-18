from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TenantSharePointAppCreate(BaseModel):
    """Request model for creating/updating tenant SharePoint app credentials."""

    client_id: str = Field(
        ...,
        description="Azure AD Application (Client) ID",
        example="12345678-1234-1234-1234-123456789012"
    )
    client_secret: str = Field(
        ...,
        description="Azure AD Application Client Secret",
        example="abc123~xyz789"
    )
    tenant_domain: str = Field(
        ...,
        description="Azure AD Tenant Domain (e.g., contoso.onmicrosoft.com)",
        example="contoso.onmicrosoft.com"
    )
    certificate_path: Optional[str] = Field(
        None,
        description="Optional path to certificate for certificate-based authentication"
    )


class TenantSharePointAppPublic(BaseModel):
    """Response model for tenant SharePoint app (secret masked)."""

    id: UUID
    tenant_id: UUID
    client_id: str
    client_secret_masked: str = Field(
        ...,
        description="Masked client secret (last 4 chars visible)",
        example="********xyz789"
    )
    tenant_domain: str
    is_active: bool
    auth_method: str = Field(
        ...,
        description="Authentication method: 'tenant_app' or 'service_account'",
        example="service_account"
    )
    service_account_email: Optional[str] = Field(
        None,
        description="Email of the service account (only for service_account auth method)"
    )
    certificate_path: Optional[str]
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TenantAppTestResult(BaseModel):
    """Result of testing tenant app credentials."""

    success: bool
    error_message: Optional[str] = None
    details: Optional[str] = Field(
        None,
        description="Additional details about the test (e.g., token acquired successfully)"
    )


class TenantAppMigrationRequest(BaseModel):
    """Request to migrate existing integrations to tenant app auth."""

    tenant_id: UUID = Field(
        ...,
        description="Tenant ID to migrate integrations for"
    )
    dry_run: bool = Field(
        False,
        description="If true, returns what would be migrated without making changes"
    )


class TenantAppMigrationResult(BaseModel):
    """Result of migration operation."""

    dry_run: bool
    total_integrations_found: int
    migrated: list[UUID] = Field(
        default_factory=list,
        description="List of integration IDs successfully migrated"
    )
    failed: list[dict] = Field(
        default_factory=list,
        description="List of failed migrations with error details"
    )
    skipped: list[dict] = Field(
        default_factory=list,
        description="List of integrations skipped (e.g., already using tenant app)"
    )


class SharePointSubscriptionPublic(BaseModel):
    """Public representation of a SharePoint subscription."""

    id: UUID
    user_integration_id: UUID
    site_id: str
    subscription_id: str
    drive_id: str
    expires_at: datetime
    created_at: datetime
    is_expired: bool = Field(
        ...,
        description="True if subscription has already expired"
    )
    expires_in_hours: int = Field(
        ...,
        description="Hours until expiration (0 if already expired)"
    )
    owner_email: Optional[str] = Field(
        None,
        description="Email of subscription owner (None for organization integrations)"
    )
    owner_type: str = Field(
        ...,
        description="Type of owner: 'user' or 'organization'"
    )

    class Config:
        from_attributes = True


class SubscriptionRenewalResult(BaseModel):
    """Result of subscription renewal operation."""

    total_subscriptions: int = Field(
        ...,
        description="Total number of subscriptions found"
    )
    expired_count: int = Field(
        ...,
        description="Number of expired subscriptions"
    )
    recreated: int = Field(
        default=0,
        description="Number of subscriptions successfully recreated"
    )
    failed: int = Field(
        default=0,
        description="Number of subscriptions that failed to recreate"
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Error messages for failed renewals"
    )


# Service Account OAuth Models

class ServiceAccountAuthStart(BaseModel):
    """Request model to start service account OAuth flow."""

    client_id: str = Field(
        ...,
        description="Azure AD Application (Client) ID",
        example="12345678-1234-1234-1234-123456789012"
    )
    client_secret: str = Field(
        ...,
        description="Azure AD Application Client Secret",
        example="abc123~xyz789"
    )
    tenant_domain: str = Field(
        ...,
        description="Azure AD Tenant Domain (e.g., contoso.onmicrosoft.com)",
        example="contoso.onmicrosoft.com"
    )


class ServiceAccountAuthStartResponse(BaseModel):
    """Response with OAuth URL for service account login."""

    auth_url: str = Field(
        ...,
        description="Microsoft OAuth authorization URL. Redirect the admin to this URL."
    )
    state: str = Field(
        ...,
        description="OAuth state parameter for CSRF protection"
    )


class ServiceAccountAuthCallback(BaseModel):
    """Request model for service account OAuth callback."""

    auth_code: str = Field(
        ...,
        description="OAuth authorization code from Microsoft callback"
    )
    state: str = Field(
        ...,
        description="OAuth state parameter for verification"
    )
    client_id: str = Field(
        ...,
        description="Azure AD Application (Client) ID (must match auth/start)"
    )
    client_secret: str = Field(
        ...,
        description="Azure AD Application Client Secret (must match auth/start)"
    )
    tenant_domain: str = Field(
        ...,
        description="Azure AD Tenant Domain (must match auth/start)"
    )
