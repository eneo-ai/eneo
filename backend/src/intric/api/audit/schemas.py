"""Pydantic schemas for audit API."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome


class AuditLogCreate(BaseModel):
    """Schema for creating an audit log."""

    tenant_id: UUID
    actor_id: UUID
    actor_type: ActorType = ActorType.USER
    action: ActionType
    entity_type: EntityType
    entity_id: UUID
    description: str = Field(min_length=1, max_length=500)
    metadata: dict = Field(default_factory=dict)
    outcome: Outcome = Outcome.SUCCESS
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[UUID] = None
    error_message: Optional[str] = None


class AuditLogResponse(BaseModel):
    """Schema for audit log response."""

    id: UUID
    tenant_id: UUID
    actor_id: UUID
    actor_type: ActorType
    action: ActionType
    entity_type: EntityType
    entity_id: UUID
    timestamp: datetime
    description: str
    metadata: dict
    outcome: Outcome
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[UUID] = None
    error_message: Optional[str] = None
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AuditLogListRequest(BaseModel):
    """Schema for listing audit logs."""

    actor_id: Optional[UUID] = None
    action: Optional[ActionType] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=1000)


class AuditLogListResponse(BaseModel):
    """Schema for audit log list response."""

    logs: list[AuditLogResponse]
    total_count: int
    page: int
    page_size: int
    total_pages: int


class AuditLogExportRequest(BaseModel):
    """Schema for exporting audit logs."""

    user_id: Optional[UUID] = None
    actor_id: Optional[UUID] = None
    action: Optional[ActionType] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
