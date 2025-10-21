"""
FastAPI router for tenant credential management.

This module provides endpoints for system administrators to manage
tenant-specific LLM provider API credentials.
"""

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from intric.authentication import auth
from intric.main.config import Settings, get_settings
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.tenants.masking import mask_api_key


def check_feature_enabled(
    settings: Settings = Depends(get_settings),
) -> None:
    """Verify tenant credentials feature is enabled.

    Raises:
        HTTPException: 404 if feature disabled
    """
    if not settings.tenant_credentials_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "feature_disabled",
                "message": "Tenant-specific credentials are not enabled on this installation",
                "hint": "Contact system administrator to enable TENANT_CREDENTIALS_ENABLED",
            },
        )


router = APIRouter(
    prefix="/tenants",
    dependencies=[
        Depends(auth.authenticate_super_api_key),
        Depends(check_feature_enabled),
    ],
)

# Provider enum - supported LLM providers
Provider = Literal["openai", "anthropic", "azure", "berget", "mistral", "ovhcloud", "vllm"]


class SetCredentialRequest(BaseModel):
    """
    Request model for setting tenant API credentials.

    For Azure provider, all four fields (api_key, endpoint, api_version, deployment_name)
    are required. For other providers, only api_key is required.

    Example for OpenAI:
        {
            "api_key": "sk-proj-abc123..."
        }

    Example for Azure:
        {
            "api_key": "abc123...",
            "endpoint": "https://my-resource.openai.azure.com",
            "api_version": "2024-02-15-preview",
            "deployment_name": "gpt-4"
        }

    Example for VLLM:
        {
            "api_key": "vllm-secret-key",
            "endpoint": "http://tenant-vllm:8000"
        }
    """

    api_key: str = Field(..., min_length=8, description="API key for the provider")
    endpoint: str | None = Field(
        None, description="Azure OpenAI endpoint (required for Azure provider)"
    )
    api_version: str | None = Field(
        None, description="Azure OpenAI API version (required for Azure provider)"
    )
    deployment_name: str | None = Field(
        None, description="Azure OpenAI deployment name (required for Azure provider)"
    )

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Trim whitespace from API key."""
        return v.strip()


class SetCredentialResponse(BaseModel):
    """
    Response model for setting tenant API credentials.

    Example:
        {
            "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
            "provider": "openai",
            "masked_key": "...xyz9",
            "message": "API credential for openai set successfully"
        }
    """

    tenant_id: UUID
    provider: str
    masked_key: str
    message: str
    set_at: datetime


class DeleteCredentialResponse(BaseModel):
    """
    Response model for deleting tenant API credentials.

    Example:
        {
            "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
            "provider": "anthropic",
            "message": "API credential for anthropic deleted successfully"
        }
    """

    tenant_id: UUID
    provider: str
    message: str


class CredentialInfo(BaseModel):
    """
    Information about a configured credential.

    Example:
        {
            "provider": "openai",
            "masked_key": "...xyz9",
            "configured_at": "2025-10-07T12:34:56.789Z",
            "encryption_status": "encrypted",
            "config": {
                "endpoint": "https://my-resource.openai.azure.com",
                "api_version": "2024-02-15-preview"
            }
        }
    """

    provider: str = Field(
        ..., description="LLM provider name", examples=["openai", "azure"]
    )
    masked_key: str = Field(
        ...,
        description="Last 4 characters of API key for identification",
        examples=["...xyz9", "...abc1"],
    )
    configured_at: datetime | None = Field(
        None, description="Timestamp when credential was last updated"
    )
    encryption_status: Literal["encrypted", "plaintext"] = Field(
        ...,
        description="Encryption status of stored credential. "
        "'encrypted' = secure at rest (Fernet encryption), "
        "'plaintext' = needs migration for security compliance",
        examples=["encrypted"],
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific configuration (e.g., Azure endpoint, api_version)",
        examples=[
            {
                "endpoint": "https://sweden.openai.azure.com/",
                "api_version": "2024-02-15-preview",
                "deployment_name": "gpt-4-sweden",
            }
        ],
    )


class ListCredentialsResponse(BaseModel):
    """
    Response model for listing tenant credentials.

    Example:
        {
            "credentials": [
                {
                    "provider": "openai",
                    "masked_key": "...xyz9",
                    "configured_at": "2025-10-07T12:34:56.789Z",
                    "encryption_status": "encrypted",
                    "config": {}
                },
                {
                    "provider": "azure",
                    "masked_key": "...abc3",
                    "configured_at": "2025-10-07T12:45:00.123Z",
                    "encryption_status": "plaintext",
                    "config": {
                        "endpoint": "https://my-resource.openai.azure.com",
                        "api_version": "2024-02-15-preview",
                        "deployment_name": "gpt-4"
                    }
                }
            ]
        }
    """

    credentials: list[CredentialInfo]


@router.put(
    "/{tenant_id}/credentials/{provider}",
    response_model=SetCredentialResponse,
    status_code=status.HTTP_200_OK,
    summary="Set tenant API credential",
    description="Set or update API credentials for a specific LLM provider for a tenant. "
    "System admin only. For Azure provider, all four fields (api_key, endpoint, "
    "api_version, deployment_name) are required.",
)
async def set_tenant_credential(
    tenant_id: UUID,
    provider: Provider,
    request: SetCredentialRequest,
    container: Container = Depends(get_container()),
) -> SetCredentialResponse:
    """
    Set or update tenant API credentials for a specific provider.

    Args:
        tenant_id: UUID of the tenant
        provider: LLM provider name (openai, anthropic, azure, berget, mistral, ovhcloud)
        request: Credential data including api_key and optional Azure fields
        container: Dependency injection container

    Returns:
        SetCredentialResponse with masked key and confirmation message

    Raises:
        HTTPException 404: Tenant not found
        HTTPException 400: Invalid request (e.g., missing Azure fields)
    """
    tenant_repo = container.tenant_repo()
    settings = get_settings()

    # Validate tenant exists
    tenant = await tenant_repo.get(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    # Azure-specific validation
    if provider == "azure":
        if not all([request.endpoint, request.api_version, request.deployment_name]):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Azure provider requires: api_key, endpoint, api_version, deployment_name",
            )

    if provider == "vllm" and settings.tenant_credentials_enabled:
        if not request.endpoint:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="VLLM provider requires both api_key and endpoint when tenant credentials are enabled",
            )

    # Build credential dict
    credential: dict[str, Any] = {"api_key": request.api_key}

    if request.endpoint:
        credential["endpoint"] = request.endpoint
    if request.api_version:
        credential["api_version"] = request.api_version
    if request.deployment_name:
        credential["deployment_name"] = request.deployment_name

    # Update credential and retrieve latest tenant snapshot
    updated_tenant = await tenant_repo.update_api_credential(
        tenant_id=tenant_id,
        provider=provider,
        credential=credential,
    )

    provider_key = provider.lower()
    stored_credential = (
        updated_tenant.api_credentials.get(provider_key, {})
        if updated_tenant and updated_tenant.api_credentials
        else {}
    )

    timestamp_raw = (
        stored_credential.get("set_at")
        if isinstance(stored_credential, dict)
        else None
    )

    try:
        set_at = (
            datetime.fromisoformat(timestamp_raw)
            if timestamp_raw
            else datetime.now(timezone.utc)
        )
        if set_at.tzinfo is None:
            set_at = set_at.replace(tzinfo=timezone.utc)
    except ValueError:
        set_at = datetime.now(timezone.utc)

    masked_key = mask_api_key(request.api_key)

    return SetCredentialResponse(
        tenant_id=tenant_id,
        provider=provider,
        masked_key=masked_key,
        message=f"API credential for {provider} set successfully",
        set_at=set_at,
    )


@router.delete(
    "/{tenant_id}/credentials/{provider}",
    response_model=DeleteCredentialResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete tenant API credential",
    description="Delete API credentials for a specific LLM provider for a tenant. "
    "System admin only.",
)
async def delete_tenant_credential(
    tenant_id: UUID,
    provider: Provider,
    container: Container = Depends(get_container()),
) -> DeleteCredentialResponse:
    """
    Delete tenant API credentials for a specific provider.

    Args:
        tenant_id: UUID of the tenant
        provider: LLM provider name (openai, anthropic, azure, berget, mistral, ovhcloud)
        container: Dependency injection container

    Returns:
        DeleteCredentialResponse with confirmation message

    Raises:
        HTTPException 404: Tenant not found
    """
    tenant_repo = container.tenant_repo()

    # Validate tenant exists
    tenant = await tenant_repo.get(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    # Delete credential
    await tenant_repo.delete_api_credential(tenant_id=tenant_id, provider=provider)

    return DeleteCredentialResponse(
        tenant_id=tenant_id,
        provider=provider,
        message=f"API credential for {provider} deleted successfully",
    )


@router.get(
    "/{tenant_id}/credentials",
    response_model=ListCredentialsResponse,
    status_code=status.HTTP_200_OK,
    summary="List tenant API credentials",
    description="List all configured API credentials for a tenant with masked keys and encryption status. "
    "Shows last 4 characters of API key for verification and encryption state for security auditing. "
    "System admin only.",
)
async def list_tenant_credentials(
    tenant_id: UUID,
    container: Container = Depends(get_container()),
) -> ListCredentialsResponse:
    """
    List all configured API credentials for a tenant.

    Returns masked keys, encryption status, and provider-specific configuration
    (without sensitive data).

    Args:
        tenant_id: UUID of the tenant
        container: Dependency injection container

    Returns:
        ListCredentialsResponse with list of configured credentials including encryption status

    Raises:
        HTTPException 404: Tenant not found
    """
    tenant_repo = container.tenant_repo()

    # Validate tenant exists
    tenant = await tenant_repo.get(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    # Get credentials with metadata (masked keys + encryption status)
    credentials_metadata = await tenant_repo.get_api_credentials_with_metadata(
        tenant_id
    )

    # Build credential info list
    credentials: list[CredentialInfo] = []
    tenant_credentials = tenant.api_credentials or {}

    for provider, metadata in credentials_metadata.items():
        credential_data = tenant_credentials.get(provider, {})
        config: dict[str, Any] = {}
        configured_at: datetime = tenant.updated_at

        if isinstance(credential_data, dict):
            config = {
                k: v
                for k, v in credential_data.items()
                if k not in {"api_key", "encrypted_at", "set_at"}
            }

            timestamp_candidate = metadata.get("set_at") or credential_data.get("set_at")
            if not timestamp_candidate:
                timestamp_candidate = credential_data.get("encrypted_at")

            if isinstance(timestamp_candidate, str):
                try:
                    configured_at = datetime.fromisoformat(timestamp_candidate)
                except ValueError:
                    configured_at = tenant.updated_at

        credentials.append(
            CredentialInfo(
                provider=provider,
                masked_key=metadata["masked_key"],
                configured_at=configured_at,
                encryption_status=metadata["encryption_status"],
                config=config,
            )
        )

    return ListCredentialsResponse(credentials=credentials)
