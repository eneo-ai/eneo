from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.model_providers.domain.connection_check import (
    ConnectionCheckError,
    ConnectionCheckStatus,
)

_KEY_EXPIRES_ON_DESCRIPTION = (
    "Date the API key stops working, entered by an admin so the key can be "
    "renewed in time. Few providers report key expiry through their API, so "
    "Eneo stores this date as given and does not verify it."
)


class ModelProviderCreate(BaseModel):
    """Request model for creating a model provider."""

    name: str = Field(..., description="User-defined name for this provider instance")
    provider_type: str = Field(
        ..., description="Provider type: openai, azure, or anthropic"
    )
    credentials: dict[str, Any] = Field(
        ..., description="Provider credentials (will be encrypted)"
    )
    config: dict[str, Any] = Field(
        default_factory=dict, description="Additional configuration"
    )
    is_active: bool = Field(default=True, description="Whether the provider is active")
    key_expires_on: date | None = Field(
        default=None, description=_KEY_EXPIRES_ON_DESCRIPTION
    )


class ModelProviderUpdate(BaseModel):
    """Request model for updating a model provider."""

    name: Optional[str] = Field(
        None, description="User-defined name for this provider instance"
    )
    credentials: Optional[dict[str, Any]] = Field(
        None, description="Provider credentials (will be encrypted)"
    )
    config: Optional[dict[str, Any]] = Field(
        None, description="Additional configuration"
    )
    is_active: Optional[bool] = Field(
        None, description="Whether the provider is active"
    )
    key_expires_on: date | None = Field(
        default=None,
        description=(
            f"{_KEY_EXPIRES_ON_DESCRIPTION} Send null to remove the date; "
            "leave the field out to keep it."
        ),
    )


class ValidateModelRequest(BaseModel):
    """Request model for validating a model against a provider."""

    model_name: str = Field(..., description="Model name to validate")
    model_type: str = Field(
        default="completion",
        description="Model type: completion, embedding, transcription, or image",
    )


class FavoriteProvidersUpdate(BaseModel):
    """Request model for updating tenant's favorite provider types."""

    providers: list[str] = Field(
        ..., description="Ordered list of provider type strings to pin as favorites"
    )


class ConnectionCheckPublic(BaseModel):
    """The latest connection check: an authenticated call to the provider."""

    status: ConnectionCheckStatus
    checked_at: datetime
    error: ConnectionCheckError | None = Field(
        default=None,
        description=(
            "Why the check failed; set only when status is failed. A fixed "
            "category, never text from the provider's response."
        ),
    )


class ModelProviderPublic(BaseModel):
    """Public response model for a model provider (without credentials)."""

    id: UUID
    tenant_id: UUID
    name: str
    provider_type: str
    config: dict[str, Any]
    is_active: bool
    masked_api_key: str | None = None
    key_expires_on: date | None = Field(
        default=None, description=_KEY_EXPIRES_ON_DESCRIPTION
    )
    connection_check: ConnectionCheckPublic | None = Field(
        default=None,
        description=(
            "Result of the latest connection check; null until one runs and "
            "again after the credentials or endpoint change."
        ),
    )
    connection_check_supported: bool = Field(
        default=False,
        description=(
            "Whether POST /{provider_id}/connection-check/ can check this "
            "provider: Eneo knows a cheap authenticated call for its type, or "
            "it has an OpenAI-compatible endpoint."
        ),
    )
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
