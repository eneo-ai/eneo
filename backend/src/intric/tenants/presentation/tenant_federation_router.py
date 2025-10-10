# backend/src/intric/tenants/presentation/tenant_federation_router.py

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from intric.authentication import auth
from intric.main.config import Settings, get_settings
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
    tags=["tenant-federation"],
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
        description="Email domains allowed for this tenant (e.g., ['stockholm.se'])",
        examples=[["stockholm.se", "stockholm.gov.se"]],
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


class SetFederationResponse(BaseModel):
    """Response model for setting federation config."""

    tenant_id: UUID
    provider: str
    masked_secret: str
    message: str


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
    description="Configure custom identity provider for tenant. System admin only.",
)
async def set_tenant_federation(
    tenant_id: UUID,
    request: SetFederationRequest,
    container: Container = Depends(get_container),
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
        },
    )

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
        "claims_mapping": {
            "email": "email",
            "username": "sub",
            "name": "name",
        },
        "encrypted_at": datetime.now(timezone.utc).isoformat(),
    }

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
    container: Container = Depends(get_container),
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
    container: Container = Depends(get_container),
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
    container: Container = Depends(get_container),
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
