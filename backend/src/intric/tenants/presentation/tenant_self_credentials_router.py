"""
FastAPI router for tenant self-service credential management.

This module provides endpoints for tenant administrators to manage
their own tenant's LLM provider API credentials.
"""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from intric.authentication.auth_dependencies import require_permission
from intric.main.config import Settings, get_settings
from intric.main.container.container import Container
from intric.main.exceptions import NotFoundException
from intric.roles.permissions import Permission
from intric.server.dependencies.container import get_container
from intric.tenants.provider_field_config import PROVIDER_REQUIRED_FIELDS


def check_feature_enabled(
    settings: Settings = Depends(get_settings),
) -> None:
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
        Depends(require_permission(Permission.ADMIN)),
    ],
)

Provider = Literal["openai", "anthropic", "azure", "berget", "gdm", "mistral", "ovhcloud", "vllm"]


class SetCredentialRequest(BaseModel):
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
        return v.strip()


class SetCredentialResponse(BaseModel):
    provider: str
    masked_key: str
    message: str
    set_at: datetime


class CredentialInfo(BaseModel):
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
    tenant_service = container.tenant_service()
    settings = get_settings()
    user = container.user()
    tenant_id = user.tenant_id

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
            provider=result["provider"],
            masked_key=result["masked_key"],
            message=f"API credential for {provider} set successfully",
            set_at=result["set_at"],
        )
    except ValueError as e:
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
    tenant_service = container.tenant_service()
    user = container.user()
    tenant_id = user.tenant_id

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
