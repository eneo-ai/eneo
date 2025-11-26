"""Pydantic schemas for retention policy API."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RetentionPolicyResponse(BaseModel):
    """Schema for audit log retention policy response.

    Note: Conversation retention is configured at the Assistant, App, or Space level,
    not at the tenant level, to prevent accidental data loss.
    """

    tenant_id: UUID
    retention_days: int = Field(ge=1, le=2555, description="Days to retain audit logs (1-2555). Recommended: 90+")
    last_purge_at: Optional[datetime] = None
    purge_count: int
    created_at: datetime
    updated_at: datetime


class RetentionPolicyUpdateRequest(BaseModel):
    """Schema for updating audit log retention policy.

    Note: Conversation retention is configured at the Assistant, App, or Space level,
    not at the tenant level, to prevent accidental data loss.
    """

    retention_days: int = Field(
        ge=1,
        le=2555,
        description="Days to retain audit logs (1 day minimum, 2555 days/7 years maximum). Recommended: 90+ days for compliance",
    )
