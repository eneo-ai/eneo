from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ModelProviderCreate(BaseModel):
    """Request model for creating a model provider."""

    name: str = Field(..., description="User-defined name for this provider instance")
    provider_type: str = Field(..., description="Provider type: openai, azure, or anthropic")
    credentials: dict[str, Any] = Field(..., description="Provider credentials (will be encrypted)")
    config: dict[str, Any] = Field(default_factory=dict, description="Additional configuration")
    is_active: bool = Field(default=True, description="Whether the provider is active")


class ModelProviderUpdate(BaseModel):
    """Request model for updating a model provider."""

    name: Optional[str] = Field(None, description="User-defined name for this provider instance")
    provider_type: Optional[str] = Field(None, description="Provider type: openai, azure, or anthropic")
    credentials: Optional[dict[str, Any]] = Field(None, description="Provider credentials (will be encrypted)")
    config: Optional[dict[str, Any]] = Field(None, description="Additional configuration")
    is_active: Optional[bool] = Field(None, description="Whether the provider is active")


class ModelProviderPublic(BaseModel):
    """Public response model for a model provider (without credentials)."""

    id: UUID
    tenant_id: UUID
    name: str
    provider_type: str
    config: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
