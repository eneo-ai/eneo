"""Pydantic schemas for retention policy API."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RetentionPolicyResponse(BaseModel):
    """Schema for retention policy response."""

    tenant_id: UUID
    retention_days: int = Field(ge=1, le=2555, description="Days to retain audit logs (1-2555). Recommended: 90+")
    last_purge_at: Optional[datetime] = None
    purge_count: int
    created_at: datetime
    updated_at: datetime

    # Conversation history retention
    conversation_retention_enabled: bool = Field(
        description="Whether tenant-wide conversation retention is enabled as a fallback policy"
    )
    conversation_retention_days: Optional[int] = Field(
        None,
        ge=1,
        le=2555,
        description="Days to retain conversation history when enabled (1-2555). Only applies when enabled."
    )


class RetentionPolicyUpdateRequest(BaseModel):
    """Schema for updating retention policy."""

    retention_days: int = Field(
        ge=1,
        le=2555,
        description="Days to retain audit logs (1 day minimum, 2555 days/7 years maximum). Recommended: 90+ days for compliance",
    )

    conversation_retention_enabled: Optional[bool] = Field(
        None,
        description="Enable tenant-wide conversation retention policy. Acts as fallback when space/assistant/app have no policy."
    )
    conversation_retention_days: Optional[int] = Field(
        None,
        ge=1,
        le=2555,
        description="Days to retain conversation history when enabled (1-2555). Required when conversation_retention_enabled is True."
    )
