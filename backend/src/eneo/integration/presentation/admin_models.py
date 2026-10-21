from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eneo.observability.error_text import user_visible_error


def _empty_uuid_list() -> list[UUID]:
    return []


def _empty_failed_list() -> list[dict[str, Any]]:
    return []


class TenantSharePointAppCreate(BaseModel):
    """Request model for creating/updating tenant SharePoint app credentials."""

    client_id: str = Field(
        ...,
        description="Microsoft Entra ID Application (Client) ID",
        json_schema_extra={"example": "12345678-1234-1234-1234-123456789012"},
    )
    client_secret: str = Field(
        ...,
        description="Microsoft Entra ID Application Client Secret",
        json_schema_extra={"example": "abc123~xyz789"},
    )
    tenant_domain: str = Field(
        ...,
        description="Microsoft Entra ID Tenant Domain (e.g., contoso.onmicrosoft.com)",
        json_schema_extra={"example": "contoso.onmicrosoft.com"},
    )
    certificate_path: Optional[str] = Field(
        None,
        description="Optional path to certificate for certificate-based authentication",
    )


class TenantSharePointAppPublic(BaseModel):
    """Response model for tenant SharePoint app (secret masked)."""

    id: UUID
    tenant_id: UUID
    client_id: str
    client_secret_masked: str = Field(
        ...,
        description="Masked client secret (last 4 chars visible)",
        json_schema_extra={"example": "********xyz789"},
    )
    tenant_domain: str
    is_active: bool
    auth_method: str = Field(
        ...,
        description="Authentication method: 'tenant_app' or 'service_account'",
        json_schema_extra={"example": "service_account"},
    )
    service_account_email: Optional[str] = Field(
        None,
        description="Email of the service account (only for service_account auth method)",
    )
    certificate_path: Optional[str]
    auth_status: Literal["ok", "error", "unknown"] = Field(
        "unknown",
        description=(
            "Credential health: 'error' when the latest token acquisition or "
            "refresh failed, 'ok' after a success, 'unknown' before either."
        ),
    )
    last_auth_error: Optional[str] = Field(
        None, description="Message from the most recent credential failure"
    )
    last_auth_error_at: Optional[datetime] = None
    last_auth_success_at: Optional[datetime] = None
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    # Failures stored before credential errors were cleaned may hold URLs or host names.
    @field_validator("last_auth_error")
    @classmethod
    def _clean_auth_error(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else user_visible_error(value)

    model_config = ConfigDict(from_attributes=True)


class TenantAppTestResult(BaseModel):
    """Result of testing tenant app credentials."""

    success: bool
    error_message: Optional[str] = None
    details: Optional[str] = Field(
        None,
        description="Additional details about the test (e.g., token acquired successfully)",
    )


class TenantAppMigrationRequest(BaseModel):
    """Request to migrate existing integrations to tenant app auth."""

    tenant_id: UUID = Field(..., description="Tenant ID to migrate integrations for")
    dry_run: bool = Field(
        False,
        description="If true, returns what would be migrated without making changes",
    )


class TenantAppMigrationResult(BaseModel):
    """Result of migration operation."""

    dry_run: bool
    total_integrations_found: int
    migrated: list[UUID] = Field(
        default_factory=_empty_uuid_list,
        description="List of integration IDs successfully migrated",
    )
    failed: list[dict[str, Any]] = Field(
        default_factory=_empty_failed_list,
        description="List of failed migrations with error details",
    )
    skipped: list[dict[str, Any]] = Field(
        default_factory=_empty_failed_list,
        description="List of integrations skipped (e.g., already using tenant app)",
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
        ..., description="True if subscription has already expired"
    )
    expires_in_hours: int = Field(
        ..., description="Hours until expiration (0 if already expired)"
    )
    consecutive_renewal_failures: int = Field(
        ..., description="Consecutive failed renewal attempts"
    )
    last_renewal_failed_at: Optional[datetime] = Field(
        None, description="Most recent failed renewal attempt timestamp"
    )
    last_renewal_error: Optional[str] = Field(
        None, description="Most recent renewal failure message"
    )
    last_webhook_received_at: Optional[datetime] = Field(
        None, description="Most recent valid webhook received for this subscription"
    )

    # Failures stored before renewal errors were cleaned may hold URLs or host names.
    @field_validator("last_renewal_error")
    @classmethod
    def _clean_renewal_error(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else user_visible_error(value)

    owner_email: Optional[str] = Field(
        None,
        description="Email of subscription owner (None for organization integrations)",
    )
    owner_type: str = Field(..., description="Type of owner: 'user' or 'organization'")

    model_config = ConfigDict(from_attributes=True)


class SubscriptionRenewalResult(BaseModel):
    """Result of subscription renewal operation."""

    total_subscriptions: int = Field(
        ..., description="Total number of subscriptions found"
    )
    expired_count: int = Field(..., description="Number of expired subscriptions")
    recreated: int = Field(
        default=0, description="Number of subscriptions successfully recreated"
    )
    failed: int = Field(
        default=0, description="Number of subscriptions that failed to recreate"
    )
    errors: list[str] = Field(
        default_factory=list, description="Error messages for failed renewals"
    )


# Service Account OAuth Models


class ServiceAccountAuthStart(BaseModel):
    """Request model to start service account OAuth flow."""

    redirect_uri: str | None = Field(
        default=None, description="An exact operator-registered OAuth callback URL."
    )

    client_id: str = Field(
        ...,
        description="Microsoft Entra ID Application (Client) ID",
        json_schema_extra={"example": "12345678-1234-1234-1234-123456789012"},
    )
    client_secret: str = Field(
        ...,
        description="Microsoft Entra ID Application Client Secret",
        json_schema_extra={"example": "abc123~xyz789"},
    )
    tenant_domain: str = Field(
        ...,
        description="Microsoft Entra ID Tenant Domain (e.g., contoso.onmicrosoft.com)",
        json_schema_extra={"example": "contoso.onmicrosoft.com"},
    )


class ServiceAccountReauthStart(BaseModel):
    """Request model to restart the service account sign-in with stored credentials."""

    redirect_uri: str | None = Field(
        default=None, description="An exact operator-registered OAuth callback URL."
    )


class ServiceAccountAuthStartResponse(BaseModel):
    """Response with OAuth URL for service account login."""

    auth_url: str = Field(
        ...,
        description="Microsoft OAuth authorization URL. Redirect the admin to this URL.",
    )
    state: str = Field(..., description="OAuth state parameter for CSRF protection")


class ServiceAccountAuthCallback(BaseModel):
    """Request model for service account OAuth callback."""

    auth_code: str = Field(
        ..., description="OAuth authorization code from Microsoft callback"
    )
    # The issued state is token_urlsafe(32), 43 characters.
    state: str = Field(
        ..., max_length=256, description="OAuth state parameter for verification"
    )
