"""
FastAPI router for tenant credential management.

This module provides endpoints for system administrators to manage
tenant-specific LLM provider API credentials.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from intric.authentication import auth
from intric.main.config import Settings, get_settings
from intric.main.container.container import Container
from intric.main.exceptions import NotFoundException
from intric.server.dependencies.container import get_container
from intric.tenants.provider_field_config import PROVIDER_REQUIRED_FIELDS


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
Provider = Literal["openai", "anthropic", "azure", "berget", "gdm", "mistral", "ovhcloud", "gemini", "cohere"]


class SetCredentialRequest(BaseModel):
    """
    Request model for setting tenant API credentials.

    Provider-specific field requirements:
    - OpenAI, Anthropic, Mistral, Berget, GDM, OVHCloud: api_key only
    - vLLM: api_key + endpoint (required)
    - Azure: api_key + endpoint + api_version (required)

    Example for OpenAI:
        {
            "api_key": "sk-proj-abc123..."
        }

    Example for Azure:
        {
            "api_key": "abc123...",
            "endpoint": "https://my-resource.openai.azure.com",
            "api_version": "2024-02-15-preview"
        }

    Example for vLLM:
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

    Returns the tenant ID, provider, masked API key (last 4 chars for verification),
    and confirmation message. Sensitive data (api_key, endpoint, api_version) are
    not returned for security.

    Example:
        {
            "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
            "provider": "openai",
            "masked_key": "...xyz9",
            "message": "API credential for openai set successfully",
            "set_at": "2025-10-22T10:00:00+00:00"
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
    "System admin only. Provider-specific fields are validated: "
    "OpenAI/Anthropic require api_key only; vLLM requires api_key and endpoint; "
    "Azure requires api_key, endpoint, and api_version.",
)
async def set_tenant_credential(
    tenant_id: UUID,
    provider: Provider,
    request: SetCredentialRequest,
    container: Container = Depends(get_container()),
) -> SetCredentialResponse:
    """
    Set or update tenant API credentials for a specific provider.

    Validates provider-specific field requirements:
    - OpenAI, Anthropic, Mistral, Berget, OVHCloud: api_key (required)
    - vLLM: api_key + endpoint (both required when credentials enabled)
    - Azure: api_key + endpoint + api_version (all required)

    Args:
        tenant_id: UUID of the tenant
        provider: LLM provider name (openai, anthropic, azure, berget, mistral, ovhcloud, vllm)
        request: Credential data including required fields per provider
        container: Dependency injection container

    Returns:
        SetCredentialResponse with masked key and confirmation message

    Raises:
        HTTPException 404: Tenant not found
        HTTPException 422: Validation error with field-level error messages
    """
    tenant_service = container.tenant_service()
    settings = get_settings()

    try:
        result = await tenant_service.set_credential(
            tenant_id=tenant_id,
            provider=provider,
            api_key=request.api_key,
            endpoint=request.endpoint,
            api_version=request.api_version,
            deployment_name=request.deployment_name,
            strict_mode=settings.tenant_credentials_enabled,
        )

        return SetCredentialResponse(
            tenant_id=result["tenant_id"],
            provider=result["provider"],
            masked_key=result["masked_key"],
            message=f"API credential for {provider} set successfully",
            set_at=result["set_at"],
        )
    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        # Parse validation errors from service
        error_message = str(e)
        if "Credential validation failed" in error_message:
            errors = error_message.split(": ", 1)[1].split("; ") if ": " in error_message else [error_message]
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "credential_validation_failed",
                    "message": f"Credential validation failed for provider '{provider}'",
                    "errors": errors,
                    "provider_requirements": {
                        k: list(v) for k, v in PROVIDER_REQUIRED_FIELDS.items()
                    },
                },
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
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
    tenant_service = container.tenant_service()

    try:
        result = await tenant_service.delete_credential(
            tenant_id=tenant_id,
            provider=provider,
        )

        return DeleteCredentialResponse(
            tenant_id=result["tenant_id"],
            provider=result["provider"],
            message=f"API credential for {provider} deleted successfully",
        )
    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
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
    tenant_service = container.tenant_service()

    try:
        credentials_data = await tenant_service.list_credentials(tenant_id)

        credentials = [
            CredentialInfo(
                provider=cred["provider"],
                masked_key=cred["masked_key"],
                configured_at=cred["configured_at"],
                encryption_status=cred["encryption_status"],
                config=cred["config"],
            )
            for cred in credentials_data
        ]

        return ListCredentialsResponse(credentials=credentials)
    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
