"""
FastAPI router for tenant self-service credential management.

This module provides endpoints for tenant administrators to manage
their own tenant's LLM provider API credentials.
"""

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from intric.main.config import Settings, get_settings
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.tenants.masking import mask_api_key

# Provider-specific required fields for strict mode validation
PROVIDER_REQUIRED_FIELDS = {
    "openai": {"api_key"},
    "anthropic": {"api_key"},
    "azure": {"api_key", "endpoint", "api_version", "deployment_name"},
    "berget": {"api_key"},
    "gdm": {"api_key"},
    "mistral": {"api_key"},
    "ovhcloud": {"api_key"},
    "vllm": {"api_key", "endpoint"},
}


def validate_provider_credentials(
    provider: str, request_data: "SetCredentialRequest", strict_mode: bool
) -> list[str]:
    """
    Validate credentials against provider-specific requirements.

    Args:
        provider: LLM provider name
        request_data: Credential request with fields
        strict_mode: Whether tenant_credentials_enabled (strict mode)

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    provider_lower = provider.lower()

    # Get required fields for this provider
    required_fields = PROVIDER_REQUIRED_FIELDS.get(provider_lower, {"api_key"})

    # Check each required field
    for field in required_fields:
        value = getattr(request_data, field, None)
        if not value or (isinstance(value, str) and not value.strip()):
            errors.append(f"Field '{field}' is required for provider '{provider}'")

    # Additional validation: api_key minimum length
    if request_data.api_key and len(request_data.api_key.strip()) < 8:
        errors.append("API key must be at least 8 characters long")

    return errors


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
    prefix="/credentials",
    dependencies=[
        Depends(check_feature_enabled),
    ],
)

# Provider enum - supported LLM providers
Provider = Literal["openai", "anthropic", "azure", "berget", "gdm", "mistral", "ovhcloud", "vllm"]


class SetCredentialRequest(BaseModel):
    """
    Request model for setting tenant API credentials.

    Provider-specific field requirements:
    - OpenAI, Anthropic, Mistral, Berget, GDM, OVHCloud: api_key only
    - vLLM: api_key + endpoint (required)
    - Azure: api_key + endpoint + api_version + deployment_name (required)

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

    Returns the provider, masked API key (last 4 chars for verification),
    and confirmation message.

    Example:
        {
            "provider": "openai",
            "masked_key": "...xyz9",
            "message": "API credential for openai set successfully",
            "set_at": "2025-10-22T10:00:00+00:00"
        }
    """

    provider: str
    masked_key: str
    message: str
    set_at: datetime


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
                "api_version": "2024-02-15-preview",
                "deployment_name": "gpt-4"
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
                }
            ]
        }
    """

    credentials: list[CredentialInfo]


@router.put(
    "/{provider}",
    response_model=SetCredentialResponse,
    status_code=status.HTTP_200_OK,
    summary="Set API credential for current tenant",
    description="Set or update API credentials for a specific LLM provider. "
    "Tenant admin only. Provider-specific fields are validated.",
)
async def set_credential(
    provider: Provider,
    request: SetCredentialRequest,
    container: Container = Depends(get_container(with_user=True)),
) -> SetCredentialResponse:
    """
    Set or update tenant API credentials for a specific provider.

    The current user must be authenticated and part of a tenant.
    Validates provider-specific field requirements.

    Args:
        provider: LLM provider name
        request: Credential data including required fields per provider
        container: Dependency injection container with authenticated user

    Returns:
        SetCredentialResponse with masked key and confirmation message

    Raises:
        HTTPException 422: Validation error with field-level error messages
    """
    tenant_repo = container.tenant_repo()
    settings = get_settings()

    # Get tenant ID from authenticated user in container
    user = container.user()
    tenant_id = user.tenant_id

    # Provider-specific field validation
    validation_errors = validate_provider_credentials(
        provider, request, settings.tenant_credentials_enabled
    )

    if validation_errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "credential_validation_failed",
                "message": f"Credential validation failed for provider '{provider}'",
                "errors": validation_errors,
                "provider_requirements": {
                    "openai": ["api_key"],
                    "anthropic": ["api_key"],
                    "azure": ["api_key", "endpoint", "api_version", "deployment_name"],
                    "berget": ["api_key"],
                    "gdm": ["api_key"],
                    "mistral": ["api_key"],
                    "ovhcloud": ["api_key"],
                    "vllm": ["api_key", "endpoint"],
                },
            },
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
        provider=provider,
        masked_key=masked_key,
        message=f"API credential for {provider} set successfully",
        set_at=set_at,
    )


@router.get(
    "/",
    response_model=ListCredentialsResponse,
    status_code=status.HTTP_200_OK,
    summary="List API credentials for current tenant",
    description="List all configured API credentials with masked keys and encryption status. "
    "Tenant admin only.",
)
async def list_credentials(
    container: Container = Depends(get_container(with_user=True)),
) -> ListCredentialsResponse:
    """
    List all configured API credentials for the current user's tenant.

    Returns masked keys, encryption status, and provider-specific configuration
    (without sensitive data).

    Args:
        container: Dependency injection container with authenticated user

    Returns:
        ListCredentialsResponse with list of configured credentials
    """
    tenant_repo = container.tenant_repo()
    user = container.user()
    tenant_id = user.tenant_id

    # Validate tenant exists
    tenant = await tenant_repo.get(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
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
