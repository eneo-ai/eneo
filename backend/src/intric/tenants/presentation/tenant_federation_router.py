# backend/src/intric/tenants/presentation/tenant_federation_router.py

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from intric.authentication import auth
from intric.main.config import Settings, get_settings, validate_public_origin
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.server.dependencies.container import get_container

logger = get_logger(__name__)


def check_feature_enabled(settings: Settings = Depends(get_settings)) -> None:
    """Verify federation feature is enabled."""
    if not settings.federation_per_tenant_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Federation per tenant is not enabled",
        )


router = APIRouter(
    prefix="/tenants",
    dependencies=[
        Depends(auth.authenticate_super_api_key),
        Depends(check_feature_enabled),
    ],
)


class SetFederationRequest(BaseModel):
    """Request model for setting tenant federation config."""

    provider: str = Field(
        ...,
        description="Identity provider label (e.g., 'mobilityguard', 'entra_id', 'okta', 'auth0')",
    )
    discovery_endpoint: str = Field(
        ...,
        description="OIDC discovery endpoint URL",
        examples=[
            "https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration"
        ],
    )
    client_id: str = Field(..., description="OAuth client ID")
    client_secret: str = Field(..., min_length=8, description="OAuth client secret")
    allowed_domains: list[str] = Field(
        default_factory=list,
        description=(
            "Email domain whitelist for user authentication (e.g., ['sundsvall.se', 'ange.se']). "
            "Only users with emails from these domains can log into this tenant. "
            "Leave empty to allow all domains (not recommended for production)"
        ),
        examples=[["sundsvall.se", "ange.se"]],
    )
    canonical_public_origin: str | None = Field(
        None,
        description=(
            "Tenant's public URL (e.g., https://sundsvall.eneo.se). "
            "Used to construct redirect_uri for IdP. "
            "Must match the redirect_uri registered in your IdP application. "
            "Required for multi-tenant federation"
        ),
        examples=["https://sundsvall.eneo.se"],
    )
    redirect_path: str | None = Field(
        None,
        description=(
            "Optional custom callback path (defaults to '/auth/callback'). "
            "Most deployments can omit this field and use the default"
        ),
        examples=["/auth/callback"],
    )
    slug: str | None = Field(
        None,
        description=(
            "URL-safe tenant identifier for federation routing (e.g., 'sundsvall'). "
            "Required for tenant to appear in login selector. "
            "Auto-generated from tenant name if omitted. "
            "Must be lowercase alphanumeric + hyphens, max 63 chars."
        ),
        examples=["sundsvall", "goteborg", "region-norr"],
        max_length=63,
        pattern=r"^[a-z0-9-]+$",
    )

    @field_validator("client_secret")
    @classmethod
    def validate_client_secret(cls, v: str) -> str:
        """Trim whitespace from client secret."""
        return v.strip()

    @field_validator("allowed_domains")
    @classmethod
    def validate_allowed_domains(cls, v: list[str]) -> list[str]:
        """Validate domain format."""
        import re

        domain_pattern = r"^[a-z0-9]+([\-\.]{1}[a-z0-9]+)*\.[a-z]{2,}$"
        for domain in v:
            if not re.match(domain_pattern, domain.lower()):
                raise ValueError(f"Invalid domain format: {domain}")
        return [d.lower() for d in v]

    @field_validator("canonical_public_origin")
    @classmethod
    def validate_canonical_public_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_public_origin(value)

    @field_validator("redirect_path")
    @classmethod
    def validate_redirect_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value.startswith("/"):
            raise ValueError("redirect_path must start with /")
        return value

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        """Validate and normalize slug."""
        if value is None:
            return None
        import re

        value = value.strip().lower()
        if not value:
            return None

        # Validate format (already enforced by pattern, but explicit validation here)
        if not re.match(r"^[a-z0-9-]+$", value):
            raise ValueError(
                "Slug must contain only lowercase letters, numbers, and hyphens"
            )
        if value.startswith("-") or value.endswith("-"):
            raise ValueError("Slug cannot start or end with a hyphen")
        if len(value) > 63:
            raise ValueError("Slug cannot exceed 63 characters")

        return value

    model_config = {
        "json_schema_extra": {
            "example": {
                "provider": "entra_id",
                "slug": "sundsvall",
                "canonical_public_origin": "https://sundsvall.eneo.se",
                "discovery_endpoint": "https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration",
                "client_id": "abc123-def456-ghi789",
                "client_secret": "your-secret-value",
                "allowed_domains": ["sundsvall.se", "ange.se"],
            }
        }
    }


class SetFederationResponse(BaseModel):
    """Response model for setting federation config."""

    tenant_id: UUID
    provider: str
    masked_secret: str
    message: str
    slug: str | None = Field(
        None,
        description="Effective slug (custom or auto-generated) for this tenant",
    )


class DeleteFederationResponse(BaseModel):
    """Response model for deleting federation config."""

    tenant_id: UUID
    message: str


class FederationInfo(BaseModel):
    """Information about configured federation."""

    provider: str
    client_id: str
    masked_secret: str
    issuer: Optional[str] = None
    allowed_domains: list[str]
    configured_at: datetime
    encryption_status: Literal["encrypted", "plaintext"]


@router.put(
    "/{tenant_id}/federation",
    response_model=SetFederationResponse,
    status_code=status.HTTP_200_OK,
    summary="Set tenant federation config",
    description="""Configure custom OIDC identity provider for a tenant.

**What this endpoint does:**
- Validates the IdP's OIDC discovery endpoint
- Encrypts and stores client_secret (Fernet encryption)
- Sets or auto-generates tenant slug (required for frontend login selector)
- Returns the effective slug in the response

**Field Guide:**
- `provider`: IdP type (e.g., 'entra_id', 'auth0', 'mobilityguard', 'okta')
- `slug`: Optional. Tenant identifier for routing. Auto-generated from tenant name if omitted
- `canonical_public_origin`: Tenant's public URL. Used to construct redirect_uri for IdP
- `discovery_endpoint`: OIDC .well-known/openid-configuration URL from your IdP
- `client_id` & `client_secret`: OAuth credentials from IdP application registration
- `allowed_domains`: Email domain whitelist (e.g., ["sundsvall.se", "ange.se"])
- `redirect_path`: Optional. Callback path (defaults to "/auth/callback")
""",
)
async def set_tenant_federation(
    tenant_id: UUID,
    request: SetFederationRequest,
    container: Container = Depends(get_container()),
) -> SetFederationResponse:
    """
    Configure custom identity provider for tenant.

    Args:
        tenant_id: UUID of the tenant
        request: Federation configuration
        container: Dependency injection container

    Returns:
        SetFederationResponse with masked secret and confirmation

    Raises:
        HTTPException 404: Tenant not found
        HTTPException 400: Invalid configuration
    """
    tenant_repo = container.tenant_repo()
    encryption_service = container.encryption_service()

    # Validate tenant exists
    tenant = await tenant_repo.get(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    # Handle slug assignment
    effective_slug = None
    if request.slug:
        # User provided custom slug - validate uniqueness
        normalized_slug = request.slug.strip().lower()
        old_slug = tenant.slug  # Capture before update

        # Check uniqueness (only if different from current slug)
        if old_slug != normalized_slug:
            existing = await tenant_repo.get_by_slug(normalized_slug)
            if existing and existing.id != tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Slug '{normalized_slug}' is already in use by another tenant. Please choose a different slug.",
                )

            # Update slug
            await tenant_repo.update_slug(tenant_id, normalized_slug)
            logger.warning(
                f"Tenant slug changed from '{old_slug}' to '{normalized_slug}'",
                extra={
                    "tenant_id": str(tenant_id),
                    "tenant_name": tenant.name,
                    "old_slug": old_slug,
                    "new_slug": normalized_slug,
                    "action": "slug_updated_via_federation_config",
                },
            )
            effective_slug = normalized_slug
        else:
            # Slug unchanged
            effective_slug = normalized_slug
    elif not tenant.slug:
        # No slug provided and tenant doesn't have one - auto-generate
        effective_slug = await tenant_repo.generate_slug_for_tenant(tenant_id)
        logger.info(
            f"Auto-generated slug '{effective_slug}' for tenant {tenant.name}",
            extra={
                "tenant_id": str(tenant_id),
                "tenant_name": tenant.name,
                "slug": effective_slug,
                "action": "slug_auto_generated",
            },
        )
    else:
        # No slug provided but tenant already has one - keep existing
        effective_slug = tenant.slug

    # Fetch OIDC discovery to validate config
    import aiohttp
    from intric.main.aiohttp_client import aiohttp_client

    logger.info(
        "Validating OIDC discovery endpoint",
        extra={
            "tenant_id": str(tenant_id),
            "tenant_name": tenant.name,
            "discovery_endpoint": request.discovery_endpoint,
            "provider": request.provider,
        },
    )

    try:
        async with aiohttp_client().get(request.discovery_endpoint) as resp:
            if resp.status != 200:
                # Capture IdP error response for debugging
                try:
                    error_body = await resp.json()
                except Exception:
                    error_body = await resp.text()

                logger.error(
                    f"Discovery endpoint validation failed: HTTP {resp.status}",
                    extra={
                        "tenant_id": str(tenant_id),
                        "tenant_name": tenant.name,
                        "discovery_endpoint": request.discovery_endpoint,
                        "http_status": resp.status,
                        "error_response": error_body,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to fetch discovery endpoint: HTTP {resp.status}",
                )
            discovery = await resp.json()
    except aiohttp.ClientError as e:
        logger.error(
            "Failed to connect to discovery endpoint",
            extra={
                "tenant_id": str(tenant_id),
                "tenant_name": tenant.name,
                "discovery_endpoint": request.discovery_endpoint,
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch discovery endpoint: {str(e)}",
        )

    # Extract endpoints from discovery
    issuer = discovery.get("issuer")
    authorization_endpoint = discovery.get("authorization_endpoint")
    token_endpoint = discovery.get("token_endpoint")
    userinfo_endpoint = discovery.get("userinfo_endpoint")
    jwks_uri = discovery.get("jwks_uri")
    token_auth_methods_supported_raw = discovery.get(
        "token_endpoint_auth_methods_supported", []
    )
    if isinstance(token_auth_methods_supported_raw, list):
        token_auth_methods_supported = token_auth_methods_supported_raw
    elif token_auth_methods_supported_raw:
        token_auth_methods_supported = [token_auth_methods_supported_raw]
    else:
        token_auth_methods_supported = []

    if not all([issuer, authorization_endpoint, token_endpoint, jwks_uri]):
        # Log full discovery response for debugging missing fields
        logger.error(
            "Discovery endpoint missing required OIDC fields",
            extra={
                "tenant_id": str(tenant_id),
                "tenant_name": tenant.name,
                "discovery_endpoint": request.discovery_endpoint,
                "has_issuer": bool(issuer),
                "has_authorization_endpoint": bool(authorization_endpoint),
                "has_token_endpoint": bool(token_endpoint),
                "has_jwks_uri": bool(jwks_uri),
                "discovery_keys": list(discovery.keys()),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Discovery endpoint missing required fields",
        )

    logger.debug(
        "Discovery endpoint validated successfully",
        extra={
            "tenant_id": str(tenant_id),
            "tenant_name": tenant.name,
            "issuer": issuer,
            "authorization_endpoint": authorization_endpoint,
            "token_endpoint": token_endpoint,
            "jwks_uri": jwks_uri,
            "token_endpoint_auth_methods_supported": token_auth_methods_supported,
        },
    )

    def _select_token_auth_method(methods: list[str]) -> str:
        normalized = [str(m).lower() for m in methods if m]
        if "client_secret_post" in normalized:
            return "client_secret_post"
        if "client_secret_basic" in normalized:
            return "client_secret_basic"
        return normalized[0] if normalized else "client_secret_post"

    token_endpoint_auth_method = _select_token_auth_method(token_auth_methods_supported)

    # Encrypt client_secret
    encrypted_secret = encryption_service.encrypt(request.client_secret)

    # Build federation config
    federation_config = {
        "provider": request.provider,
        "issuer": issuer,
        "discovery_endpoint": request.discovery_endpoint,
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
        "userinfo_endpoint": userinfo_endpoint,
        "jwks_uri": jwks_uri,
        "client_id": request.client_id,
        "client_secret": encrypted_secret,
        "scopes": ["openid", "email", "profile"],
        "allowed_domains": request.allowed_domains,
        "token_endpoint_auth_method": token_endpoint_auth_method,
        "token_endpoint_auth_methods_supported": token_auth_methods_supported,
        "claims_mapping": {
            "email": "email",
            "username": "sub",
            "name": "name",
        },
        "encrypted_at": datetime.now(timezone.utc).isoformat(),
    }

    if request.canonical_public_origin:
        federation_config["canonical_public_origin"] = request.canonical_public_origin

    if request.redirect_path:
        federation_config["redirect_path"] = request.redirect_path

    # Save to database
    await tenant_repo.update_federation_config(
        tenant_id=tenant_id,
        federation_config=federation_config,
    )

    logger.info(
        f"Federation config set for tenant {tenant.name} (provider: {request.provider})",
        extra={
            "tenant_id": str(tenant_id),
            "tenant_name": tenant.name,
            "provider": request.provider,
            "issuer": issuer,
            "client_id": request.client_id,
            "allowed_domains": request.allowed_domains,
            "endpoints_configured": {
                "authorization": authorization_endpoint,
                "token": token_endpoint,
                "userinfo": userinfo_endpoint,
                "jwks": jwks_uri,
            },
        },
    )

    # Mask secret
    masked_secret = (
        f"...{request.client_secret[-4:]}" if len(request.client_secret) > 4 else "***"
    )

    return SetFederationResponse(
        tenant_id=tenant_id,
        provider=request.provider,
        masked_secret=masked_secret,
        message=f"Federation config for {request.provider} set successfully",
        slug=effective_slug,
    )


@router.delete(
    "/{tenant_id}/federation",
    response_model=DeleteFederationResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete tenant federation config",
    description="Remove custom identity provider for tenant. System admin only.",
)
async def delete_tenant_federation(
    tenant_id: UUID,
    container: Container = Depends(get_container()),
) -> DeleteFederationResponse:
    """Delete federation config for tenant (revert to global IdP)."""
    tenant_repo = container.tenant_repo()

    # Validate tenant exists
    tenant = await tenant_repo.get(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    # Delete federation config
    await tenant_repo.delete_federation_config(tenant_id=tenant_id)

    logger.info(f"Federation config deleted for tenant {tenant.name}")

    return DeleteFederationResponse(
        tenant_id=tenant_id,
        message="Federation config deleted successfully",
    )


@router.get(
    "/{tenant_id}/federation",
    response_model=FederationInfo,
    status_code=status.HTTP_200_OK,
    summary="Get tenant federation config",
    description="View federation config with masked secrets. System admin only.",
)
async def get_tenant_federation(
    tenant_id: UUID,
    container: Container = Depends(get_container()),
) -> FederationInfo:
    """Get federation config for tenant (masked secrets)."""
    tenant_repo = container.tenant_repo()

    # Validate tenant exists
    tenant = await tenant_repo.get(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    # Get config with metadata
    metadata = await tenant_repo.get_federation_config_with_metadata(tenant_id)
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No federation config found for tenant",
        )

    return FederationInfo(
        provider=metadata["provider"],
        client_id=metadata["client_id"],
        masked_secret=metadata["masked_secret"],
        issuer=metadata.get("issuer"),
        allowed_domains=metadata.get("allowed_domains", []),
        configured_at=datetime.fromisoformat(metadata["encrypted_at"])
        if metadata.get("encrypted_at")
        else tenant.updated_at,
        encryption_status=metadata["encryption_status"],
    )


@router.post(
    "/{tenant_id}/federation/test",
    status_code=status.HTTP_200_OK,
    summary="Test tenant federation config",
    description="Test connection to tenant's IdP. System admin only.",
)
async def test_tenant_federation(
    tenant_id: UUID,
    container: Container = Depends(get_container()),
):
    """
    Test federation config by fetching discovery endpoint.

    Returns:
        Success message if discovery endpoint is reachable and valid

    Raises:
        HTTPException 404: Tenant not found or no config
        HTTPException 500: Discovery endpoint unreachable or invalid
    """
    tenant_repo = container.tenant_repo()

    # Validate tenant exists
    tenant = await tenant_repo.get(tenant_id)
    if not tenant or not tenant.federation_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No federation config found for tenant",
        )

    discovery_endpoint = tenant.federation_config.get("discovery_endpoint")
    if not discovery_endpoint:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No discovery endpoint in federation config",
        )

    # Test connection
    import aiohttp
    from intric.main.aiohttp_client import aiohttp_client

    logger.info(
        f"Testing federation config for tenant {tenant.name}",
        extra={
            "tenant_id": str(tenant_id),
            "tenant_name": tenant.name,
            "discovery_endpoint": discovery_endpoint,
        },
    )

    try:
        async with aiohttp_client().get(discovery_endpoint) as resp:
            if resp.status != 200:
                # Capture error response
                try:
                    error_body = await resp.json()
                except Exception:
                    error_body = await resp.text()

                logger.error(
                    f"Test failed: Discovery endpoint returned HTTP {resp.status}",
                    extra={
                        "tenant_id": str(tenant_id),
                        "tenant_name": tenant.name,
                        "discovery_endpoint": discovery_endpoint,
                        "http_status": resp.status,
                        "error_response": error_body,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Discovery endpoint returned HTTP {resp.status}",
                )
            discovery = await resp.json()

            # Validate required fields
            required = [
                "issuer",
                "authorization_endpoint",
                "token_endpoint",
                "jwks_uri",
            ]
            missing = [f for f in required if f not in discovery]
            if missing:
                logger.error(
                    "Test failed: Discovery endpoint missing required fields",
                    extra={
                        "tenant_id": str(tenant_id),
                        "tenant_name": tenant.name,
                        "discovery_endpoint": discovery_endpoint,
                        "missing_fields": missing,
                        "discovery_keys": list(discovery.keys()),
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Discovery endpoint missing required fields: {missing}",
                )
    except aiohttp.ClientError as e:
        logger.error(
            "Test failed: Could not connect to discovery endpoint",
            extra={
                "tenant_id": str(tenant_id),
                "tenant_name": tenant.name,
                "discovery_endpoint": discovery_endpoint,
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect to discovery endpoint: {str(e)}",
        )

    logger.info(
        f"Federation test successful for tenant {tenant.name}",
        extra={
            "tenant_id": str(tenant_id),
            "tenant_name": tenant.name,
            "issuer": discovery["issuer"],
            "endpoints_validated": {
                "authorization": discovery.get("authorization_endpoint"),
                "token": discovery.get("token_endpoint"),
                "jwks": discovery.get("jwks_uri"),
            },
        },
    )

    return {
        "success": True,
        "message": "Federation config is valid and IdP is reachable",
        "issuer": discovery["issuer"],
    }
