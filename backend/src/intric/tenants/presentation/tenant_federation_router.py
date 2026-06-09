# backend/src/intric/tenants/presentation/tenant_federation_router.py

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional, Self, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator

# Audit logging - module level imports for consistency
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.authentication import auth
from intric.main.config import (
    Settings,
    get_settings,
    validate_public_origin,
    validate_redirect_path,
    validate_redirect_uri,
)
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

logger = get_logger(__name__)


def check_feature_enabled(settings: Annotated[Settings, Depends(get_settings)]) -> None:
    """Verify federation feature is enabled."""
    if not settings.federation_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Federation is not enabled",
        )


router = APIRouter(
    prefix="/tenants",
    dependencies=[
        Depends(auth.authenticate_super_api_key),
        Depends(check_feature_enabled),
    ],
    responses=responses.get_responses([401]),
)


DEFAULT_FEDERATION_SCOPES = ["openid", "email", "profile"]
DEFAULT_CLAIMS_MAPPING = {
    "email": "email",
    "username": "sub",
    "name": "name",
}


class FederationRequestBase(BaseModel):
    """Shared fields and validation for federation write operations."""

    provider: str | None = Field(
        None,
        description="Identity provider label (e.g., 'mobilityguard', 'entra_id', 'okta', 'auth0')",
    )
    discovery_endpoint: str | None = Field(
        None,
        description="OIDC discovery endpoint URL",
        examples=[
            "https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration"
        ],
    )
    client_id: str | None = Field(None, description="OAuth client ID")
    client_secret: str | None = Field(
        None, min_length=8, description="OAuth client secret"
    )
    allowed_domains: list[str] | None = Field(
        None,
        description="Email domains allowed for this tenant (e.g., ['stockholm.se'])",
        examples=[["stockholm.se", "stockholm.gov.se"]],
    )
    canonical_public_origin: str | None = Field(
        None,
        description=(
            "Canonical public origin for this tenant (e.g., https://tenant.eneo.se). "
            "Required when federation is enabled to construct redirect_uri"
        ),
        examples=["https://stockholm.eneo.se"],
    )
    redirect_path: str | None = Field(
        None,
        description="Optional custom redirect path starting with /",
        examples=["/auth/callback"],
    )
    additional_redirect_uris: list[str] | None = Field(
        None,
        description=(
            "Additional fully-qualified redirect URIs for OIDC flows. "
            "Use when the tenant is accessed through multiple origins. "
            "Each URI must also be registered in the upstream Identity Provider."
        ),
        examples=[["https://qwerty.sundsvall.se/api/eneo/login/callback"]],
    )

    @field_validator("client_secret")
    @classmethod
    def validate_client_secret(cls, v: str | None) -> str | None:
        """Trim whitespace from client secret."""
        if v is None:
            return None
        return v.strip()

    @field_validator("allowed_domains")
    @classmethod
    def validate_allowed_domains(cls, v: list[str] | None) -> list[str] | None:
        """Validate domain format."""
        if v is None:
            return None
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
        return validate_redirect_path(value)

    @field_validator("additional_redirect_uris")
    @classmethod
    def validate_additional_redirect_uris(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if value is None:
            return None
        validated = [validate_redirect_uri(uri) for uri in value]
        return [uri for uri in validated if uri is not None]


class SetFederationRequest(FederationRequestBase):
    """Request model for providing a full tenant federation config."""

    # Pydantic field narrowing: required fields in subclass override optional fields in base.
    # pyright: ignore[reportIncompatibleVariableOverride] applies per-field below.
    provider: str = Field(  # pyright: ignore[reportIncompatibleVariableOverride]
        ...,
        description="Identity provider label (e.g., 'mobilityguard', 'entra_id', 'okta', 'auth0')",
    )
    discovery_endpoint: str = Field(  # pyright: ignore[reportIncompatibleVariableOverride]
        ...,
        description="OIDC discovery endpoint URL",
        examples=[
            "https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration"
        ],
    )
    client_id: str = Field(..., description="OAuth client ID")  # pyright: ignore[reportIncompatibleVariableOverride]
    client_secret: str = Field(..., min_length=8, description="OAuth client secret")  # pyright: ignore[reportIncompatibleVariableOverride]
    allowed_domains: list[str] = Field(  # pyright: ignore[reportIncompatibleVariableOverride]
        default_factory=list,
        description="Email domains allowed for this tenant (e.g., ['stockholm.se'])",
        examples=[["stockholm.se", "stockholm.gov.se"]],
    )


class PatchFederationRequest(FederationRequestBase):
    """Request model for partially updating the current tenant federation config."""

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> Self:
        invalid_null_fields = [
            field
            for field in (
                "provider",
                "discovery_endpoint",
                "client_id",
                "client_secret",
            )
            if field in self.model_fields_set and getattr(self, field) is None
        ]
        if invalid_null_fields:
            raise ValueError(
                f"PATCH does not allow null for: {', '.join(invalid_null_fields)}"
            )
        return self


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
    additional_redirect_uris: list[str]
    configured_at: datetime
    encryption_status: Literal["encrypted", "plaintext"]


def _mask_secret(secret: str) -> str:
    return f"...{secret[-4:]}" if len(secret) > 4 else "***"


def _select_token_auth_method(methods: list[str]) -> str:
    normalized = [str(m).lower() for m in methods if m]
    if "client_secret_post" in normalized:
        return "client_secret_post"
    if "client_secret_basic" in normalized:
        return "client_secret_basic"
    return normalized[0] if normalized else "client_secret_post"


async def _fetch_discovery_metadata(
    *,
    tenant_id: UUID,
    tenant_name: str,
    discovery_endpoint: str,
    provider: str,
) -> dict[str, Any]:
    """Fetch and validate discovery metadata for a federation configuration."""
    import aiohttp

    from intric.main.aiohttp_client import aiohttp_client

    logger.info(
        "Validating OIDC discovery endpoint",
        extra={
            "tenant_id": str(tenant_id),
            "tenant_name": tenant_name,
            "discovery_endpoint": discovery_endpoint,
            "provider": provider,
        },
    )

    try:
        async with aiohttp_client().get(discovery_endpoint) as resp:
            if resp.status != 200:
                try:
                    error_body = await resp.json()
                except Exception:
                    error_body = await resp.text()

                logger.error(
                    f"Discovery endpoint validation failed: HTTP {resp.status}",
                    extra={
                        "tenant_id": str(tenant_id),
                        "tenant_name": tenant_name,
                        "discovery_endpoint": discovery_endpoint,
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
                "tenant_name": tenant_name,
                "discovery_endpoint": discovery_endpoint,
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch discovery endpoint: {str(e)}",
        )

    # resp.json() returns Any; cast to typed dict at the HTTP boundary.
    discovery_doc: dict[str, object] = (
        cast(dict[str, object], discovery) if isinstance(discovery, dict) else {}
    )

    def _str_field(key: str) -> str | None:
        v = discovery_doc.get(key)
        return v if isinstance(v, str) else None

    issuer = _str_field("issuer")
    authorization_endpoint = _str_field("authorization_endpoint")
    token_endpoint = _str_field("token_endpoint")
    userinfo_endpoint = _str_field("userinfo_endpoint")
    jwks_uri = _str_field("jwks_uri")
    methods_raw: object = (
        discovery_doc.get("token_endpoint_auth_methods_supported") or []
    )
    if isinstance(methods_raw, list):
        methods_list: list[object] = cast(list[object], methods_raw)
        token_auth_methods_supported: list[str] = [str(m) for m in methods_list if m]
    elif methods_raw:
        token_auth_methods_supported = [str(methods_raw)]
    else:
        token_auth_methods_supported = []

    if not all([issuer, authorization_endpoint, token_endpoint, jwks_uri]):
        logger.error(
            "Discovery endpoint missing required OIDC fields",
            extra={
                "tenant_id": str(tenant_id),
                "tenant_name": tenant_name,
                "discovery_endpoint": discovery_endpoint,
                "has_issuer": bool(issuer),
                "has_authorization_endpoint": bool(authorization_endpoint),
                "has_token_endpoint": bool(token_endpoint),
                "has_jwks_uri": bool(jwks_uri),
                "discovery_keys": list(discovery_doc.keys()),
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
            "tenant_name": tenant_name,
            "issuer": issuer,
            "authorization_endpoint": authorization_endpoint,
            "token_endpoint": token_endpoint,
            "jwks_uri": jwks_uri,
            "token_endpoint_auth_methods_supported": token_auth_methods_supported,
        },
    )

    return {
        "issuer": issuer,
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
        "userinfo_endpoint": userinfo_endpoint,
        "jwks_uri": jwks_uri,
        "token_endpoint_auth_method": _select_token_auth_method(
            token_auth_methods_supported
        ),
        "token_endpoint_auth_methods_supported": token_auth_methods_supported,
    }


def _build_full_federation_config(
    request: SetFederationRequest,
    *,
    encrypted_secret: str,
    discovery_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Construct a complete federation config for PUT semantics."""
    federation_config = {
        "provider": request.provider,
        "discovery_endpoint": request.discovery_endpoint,
        "client_id": request.client_id,
        "client_secret": encrypted_secret,
        "scopes": DEFAULT_FEDERATION_SCOPES.copy(),
        "allowed_domains": request.allowed_domains,
        "claims_mapping": DEFAULT_CLAIMS_MAPPING.copy(),
        "encrypted_at": datetime.now(timezone.utc).isoformat(),
    }
    federation_config.update(discovery_metadata)

    if request.canonical_public_origin:
        federation_config["canonical_public_origin"] = request.canonical_public_origin

    if request.redirect_path:
        federation_config["redirect_path"] = request.redirect_path

    if request.additional_redirect_uris is not None:
        federation_config["additional_redirect_uris"] = request.additional_redirect_uris

    return federation_config


def _merge_federation_config(
    existing_config: dict[str, Any],
    updates: dict[str, Any],
    *,
    encrypted_secret: str | None,
    discovery_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge PATCH updates into an existing federation config."""
    merged = existing_config.copy()

    for field in ("provider", "client_id", "discovery_endpoint"):
        if field in updates:
            merged[field] = updates[field]

    if "allowed_domains" in updates:
        merged["allowed_domains"] = updates["allowed_domains"] or []

    for field in (
        "canonical_public_origin",
        "redirect_path",
        "additional_redirect_uris",
    ):
        if field not in updates:
            continue
        value = updates[field]
        if value is None:
            merged.pop(field, None)
        else:
            merged[field] = value

    if encrypted_secret is not None:
        merged["client_secret"] = encrypted_secret
        merged["encrypted_at"] = datetime.now(timezone.utc).isoformat()

    if discovery_metadata is not None:
        merged.update(discovery_metadata)

    merged.setdefault("scopes", DEFAULT_FEDERATION_SCOPES.copy())
    merged.setdefault("claims_mapping", DEFAULT_CLAIMS_MAPPING.copy())
    merged.setdefault("allowed_domains", [])

    return merged


async def _log_federation_update(
    *,
    container: Container,
    tenant_id: UUID,
    tenant_name: str,
    provider: str,
    issuer: str | None,
    client_id: str,
    allowed_domains: list[str],
    description: str,
) -> None:
    """Write the standard audit event for federation changes."""
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=tenant_id,
        actor_id=None,
        actor_type=ActorType.SYSTEM,
        action=ActionType.FEDERATION_UPDATED,
        entity_type=EntityType.FEDERATION_CONFIG,
        entity_id=tenant_id,
        description=description,
        metadata={
            "actor": {"type": "sysadmin", "via": "eneo_super_api_key"},
            "target": {
                "tenant_id": str(tenant_id),
                "tenant_name": tenant_name,
                "provider": provider,
                "issuer": issuer,
                "client_id": client_id,
                "allowed_domains": allowed_domains,
            },
        },
    )


@router.put(
    "/{tenant_id}/federation",
    response_model=SetFederationResponse,
    status_code=status.HTTP_200_OK,
    summary="Provide tenant federation config",
    description=(
        "Provide a new full federation configuration for the tenant. "
        "This replaces the current setup and requires all required fields. "
        "System admin only."
    ),
    responses=responses.get_responses([400, 404]),
)
async def set_tenant_federation(
    tenant_id: UUID,
    request: SetFederationRequest,
    container: Annotated[Container, Depends(get_container())],
) -> SetFederationResponse:
    """
    Provide a full federation configuration for a tenant.

    Args:
        tenant_id: UUID of the tenant
        request: Complete federation configuration
        container: Dependency injection container

    Returns:
        SetFederationResponse with masked secret and confirmation

    Raises:
        HTTPException 404: Tenant not found
        HTTPException 400: Invalid configuration
    """
    tenant_repo = container.tenant_repo()
    tenant_service = container.tenant_service()
    encryption_service = container.encryption_service()

    tenant = await tenant_service.get_tenant_by_id(tenant_id)
    assert tenant is not None

    discovery_metadata = await _fetch_discovery_metadata(
        tenant_id=tenant_id,
        tenant_name=tenant.name,
        discovery_endpoint=request.discovery_endpoint,
        provider=request.provider,
    )

    encrypted_secret = encryption_service.encrypt(request.client_secret)
    federation_config = _build_full_federation_config(
        request,
        encrypted_secret=encrypted_secret,
        discovery_metadata=discovery_metadata,
    )

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
            "issuer": federation_config.get("issuer"),
            "client_id": request.client_id,
            "allowed_domains": request.allowed_domains,
            "endpoints_configured": {
                "authorization": federation_config.get("authorization_endpoint"),
                "token": federation_config.get("token_endpoint"),
                "userinfo": federation_config.get("userinfo_endpoint"),
                "jwks": federation_config.get("jwks_uri"),
            },
        },
    )

    await _log_federation_update(
        container=container,
        tenant_id=tenant_id,
        tenant_name=tenant.name,
        provider=request.provider,
        issuer=federation_config.get("issuer"),
        client_id=request.client_id,
        allowed_domains=request.allowed_domains,
        description=f"Sysadmin replaced federation config for tenant {tenant.name}",
    )

    return SetFederationResponse(
        tenant_id=tenant_id,
        provider=request.provider,
        masked_secret=_mask_secret(request.client_secret),
        message=f"Federation config for {request.provider} replaced successfully",
    )


@router.patch(
    "/{tenant_id}/federation",
    response_model=SetFederationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update current tenant federation config",
    description=(
        "Update the current tenant federation setup without resending every field. "
        "Only provided fields are changed; omitted fields stay unchanged. "
        "PATCH requires an existing federation config. System admin only."
    ),
    responses=responses.get_responses([400, 404]),
)
async def patch_tenant_federation(
    tenant_id: UUID,
    request: PatchFederationRequest,
    container: Annotated[Container, Depends(get_container())],
) -> SetFederationResponse:
    """Partially update the current federation config for a tenant."""
    tenant_repo = container.tenant_repo()
    tenant_service = container.tenant_service()
    encryption_service = container.encryption_service()

    tenant = await tenant_service.get_tenant_by_id(tenant_id)
    assert tenant is not None
    existing_config = tenant.federation_config or {}
    if not existing_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No federation config found for tenant",
        )

    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field must be provided for patch",
        )

    provider = updates.get("provider") or existing_config.get("provider") or "unknown"

    discovery_metadata = None
    if "discovery_endpoint" in updates:
        discovery_metadata = await _fetch_discovery_metadata(
            tenant_id=tenant_id,
            tenant_name=tenant.name,
            discovery_endpoint=updates["discovery_endpoint"],
            provider=provider,
        )

    plaintext_secret: str | None = None
    encrypted_secret: str | None = None
    if "client_secret" in updates:
        secret_raw: object = updates["client_secret"]
        plaintext_secret = (
            secret_raw if isinstance(secret_raw, str) else str(secret_raw)
        )
        encrypted_secret = encryption_service.encrypt(plaintext_secret)

    federation_config = _merge_federation_config(
        existing_config,
        updates,
        encrypted_secret=encrypted_secret,
        discovery_metadata=discovery_metadata,
    )

    await tenant_repo.update_federation_config(
        tenant_id=tenant_id,
        federation_config=federation_config,
    )

    logger.info(
        f"Federation config patched for tenant {tenant.name} (provider: {federation_config.get('provider')})",
        extra={
            "tenant_id": str(tenant_id),
            "tenant_name": tenant.name,
            "provider": federation_config.get("provider"),
            "issuer": federation_config.get("issuer"),
            "client_id": federation_config.get("client_id"),
            "allowed_domains": federation_config.get("allowed_domains", []),
            "updated_fields": sorted(updates.keys()),
        },
    )

    await _log_federation_update(
        container=container,
        tenant_id=tenant_id,
        tenant_name=tenant.name,
        provider=federation_config["provider"],
        issuer=federation_config.get("issuer"),
        client_id=federation_config["client_id"],
        allowed_domains=federation_config.get("allowed_domains", []),
        description=f"Sysadmin patched federation config for tenant {tenant.name}",
    )

    if plaintext_secret is not None:
        masked_secret = _mask_secret(plaintext_secret)
    else:
        existing_secret = existing_config.get("client_secret", "")
        if existing_secret.startswith("enc:"):
            try:
                existing_secret = encryption_service.decrypt(existing_secret)
            except ValueError:
                pass
        masked_secret = _mask_secret(existing_secret)

    return SetFederationResponse(
        tenant_id=tenant_id,
        provider=federation_config["provider"],
        masked_secret=masked_secret,
        message=f"Federation config for {federation_config['provider']} updated successfully",
    )


@router.delete(
    "/{tenant_id}/federation",
    response_model=DeleteFederationResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete tenant federation config",
    description="Remove custom identity provider for tenant. System admin only.",
    responses=responses.get_responses([404]),
)
async def delete_tenant_federation(
    tenant_id: UUID,
    container: Annotated[Container, Depends(get_container())],
) -> DeleteFederationResponse:
    """Delete federation config for tenant (revert to global IdP)."""
    tenant_repo = container.tenant_repo()
    tenant_service = container.tenant_service()

    # Validate tenant exists (raises NotFoundException if not found)
    tenant = await tenant_service.get_tenant_by_id(tenant_id)
    assert tenant is not None

    # Delete federation config
    await tenant_repo.delete_federation_config(tenant_id=tenant_id)

    # Audit logging (sysadmin operation - system actor)
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=tenant_id,
        actor_id=None,
        actor_type=ActorType.SYSTEM,
        action=ActionType.FEDERATION_UPDATED,
        entity_type=EntityType.FEDERATION_CONFIG,
        entity_id=tenant_id,
        description=f"Sysadmin deleted federation config for tenant {tenant.name}",
        metadata={
            "actor": {"type": "sysadmin", "via": "eneo_super_api_key"},
            "target": {
                "tenant_id": str(tenant_id),
                "tenant_name": tenant.name,
                "action": "deleted",
            },
        },
    )

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
    responses=responses.get_responses([404]),
)
async def get_tenant_federation(
    tenant_id: UUID,
    container: Annotated[Container, Depends(get_container())],
) -> FederationInfo:
    """Get federation config for tenant (masked secrets)."""
    tenant_repo = container.tenant_repo()
    tenant_service = container.tenant_service()

    # Validate tenant exists (raises NotFoundException if not found)
    tenant = await tenant_service.get_tenant_by_id(tenant_id)
    assert tenant is not None

    # Get config with metadata
    metadata = await tenant_repo.get_federation_config_with_metadata(tenant_id)
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No federation config found for tenant",
        )

    configured_at: datetime
    if metadata.get("encrypted_at"):
        configured_at = datetime.fromisoformat(metadata["encrypted_at"])
    else:
        configured_at = tenant.updated_at or datetime.now(timezone.utc)

    return FederationInfo(
        provider=metadata["provider"],
        client_id=metadata["client_id"],
        masked_secret=metadata["masked_secret"],
        issuer=metadata.get("issuer"),
        allowed_domains=metadata.get("allowed_domains", []),
        additional_redirect_uris=metadata.get("additional_redirect_uris", []),
        configured_at=configured_at,
        encryption_status=metadata["encryption_status"],
    )


@router.post(
    "/{tenant_id}/federation/test",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="Test tenant federation config",
    description="Test connection to tenant's IdP. System admin only.",
    responses=responses.get_responses([400, 404, 500]),
)
async def test_tenant_federation(
    tenant_id: UUID,
    container: Annotated[Container, Depends(get_container())],
):
    """
    Test federation config by fetching discovery endpoint.

    Returns:
        Success message if discovery endpoint is reachable and valid

    Raises:
        HTTPException 404: Tenant not found or no config
        HTTPException 500: Discovery endpoint unreachable or invalid
    """
    tenant_service = container.tenant_service()

    # Validate tenant exists (raises NotFoundException if not found)
    tenant = await tenant_service.get_tenant_by_id(tenant_id)
    assert tenant is not None
    if not tenant.federation_config:
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
