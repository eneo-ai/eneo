# backend/src/eneo/tenants/presentation/tenant_federation_router.py
"""The operator's door to tenant federation (super API key).

The operator registers, replaces, patches, tests and deletes a tenant's IdP.
TenantFederationService owns the rules, the lock and the audit; org admins edit
through tenant_self_federation_router.
"""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from eneo.authentication import auth
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.main.config import Settings, get_settings
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.tenants.tenant_federation_service import (
    PatchFederationRequest,
    SetFederationRequest,
)

__all__ = ["PatchFederationRequest", "SetFederationRequest", "router"]


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

# Writes commit before the response, so the settings and their audit row are
# both stored or both absent.
_WriteContainer = Annotated[
    Container, Depends(get_container(transaction_scope="function"))
]


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
@endpoint_access(
    authentication=Authentication.SYSADMIN,
    authorization=Authorization.SYSADMIN,
    reason="Deployment administration requires the configured super API key.",
)
async def set_tenant_federation(
    tenant_id: UUID,
    request: SetFederationRequest,
    container: _WriteContainer,
) -> SetFederationResponse:
    """Provide a full federation configuration for a tenant."""
    tenant = await container.tenant_service().get_tenant_by_id(tenant_id)
    assert tenant is not None

    await container.tenant_federation_service().replace(tenant, request)

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
@endpoint_access(
    authentication=Authentication.SYSADMIN,
    authorization=Authorization.SYSADMIN,
    reason="Deployment administration requires the configured super API key.",
)
async def patch_tenant_federation(
    tenant_id: UUID,
    request: PatchFederationRequest,
    container: _WriteContainer,
) -> SetFederationResponse:
    """Partially update the current federation config for a tenant."""
    tenant = await container.tenant_service().get_tenant_by_id(tenant_id)
    assert tenant is not None

    federation_config = await container.tenant_federation_service().patch(
        tenant, request
    )

    if request.client_secret is not None:
        masked_secret = _mask_secret(request.client_secret)
    else:
        existing_secret = federation_config.get("client_secret", "")
        if existing_secret.startswith("enc:"):
            try:
                existing_secret = container.encryption_service().decrypt(
                    existing_secret
                )
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
@endpoint_access(
    authentication=Authentication.SYSADMIN,
    authorization=Authorization.SYSADMIN,
    reason="Deployment administration requires the configured super API key.",
)
async def delete_tenant_federation(
    tenant_id: UUID,
    container: _WriteContainer,
) -> DeleteFederationResponse:
    """Delete federation config for tenant (revert to global IdP)."""
    tenant = await container.tenant_service().get_tenant_by_id(tenant_id)
    assert tenant is not None

    await container.tenant_federation_service().delete(tenant)

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
@endpoint_access(
    authentication=Authentication.SYSADMIN,
    authorization=Authorization.SYSADMIN,
    reason="Deployment administration requires the configured super API key.",
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
@endpoint_access(
    authentication=Authentication.SYSADMIN,
    authorization=Authorization.SYSADMIN,
    reason="Deployment administration requires the configured super API key.",
)
async def test_tenant_federation(
    tenant_id: UUID,
    container: Annotated[Container, Depends(get_container())],
) -> dict[str, Any]:
    """Test federation config by fetching the stored discovery endpoint."""
    tenant = await container.tenant_service().get_tenant_by_id(tenant_id)
    assert tenant is not None

    return await container.tenant_federation_service().test_connection(tenant)
