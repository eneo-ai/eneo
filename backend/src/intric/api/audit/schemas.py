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
    actor_id: Optional[UUID] = None
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
    actor_id: Optional[UUID] = None
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


class ExportJobRequest(BaseModel):
    """Schema for requesting async audit log export."""

    user_id: Optional[UUID] = Field(None, description="User ID for GDPR export")
    actor_id: Optional[UUID] = Field(None, description="Filter by actor")
    action: Optional[ActionType] = Field(None, description="Filter by action type")
    from_date: Optional[datetime] = Field(None, description="Filter from date")
    to_date: Optional[datetime] = Field(None, description="Filter to date")
    format: str = Field("csv", description="Export format: csv or jsonl")
    max_records: Optional[int] = Field(
        None, ge=1, description="Maximum records to export"
    )


class ExportJobResponse(BaseModel):
    """Schema for export job creation response."""

    job_id: UUID
    status: str = Field(
        description="Job status: pending, processing, completed, failed, cancelled"
    )
    message: Optional[str] = Field(None, description="Status message")


class ExportJobStatusResponse(BaseModel):
    """Schema for export job status response."""

    job_id: UUID
    status: str = Field(
        description="Job status: pending, processing, completed, failed, cancelled"
    )
    progress: int = Field(ge=0, le=100, description="Progress percentage")
    total_records: int = Field(ge=0, description="Total records to export")
    processed_records: int = Field(ge=0, description="Records processed so far")
    format: str = Field(description="Export format: csv or jsonl")
    file_size_bytes: Optional[int] = Field(
        None, description="File size in bytes (when completed)"
    )
    error_message: Optional[str] = Field(
        None, description="Error message (when failed)"
    )
    download_url: Optional[str] = Field(
        None, description="Download URL (when completed)"
    )
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    expires_at: datetime


class AccessJustificationRequest(BaseModel):
    """Schema for creating audit access session with justification."""

    category: str = Field(
        min_length=1, max_length=100, description="Justification category"
    )
    description: str = Field(
        min_length=10, max_length=500, description="Detailed access reason"
    )


class AccessJustificationResponse(BaseModel):
    """Schema for access session creation response."""

    status: str = Field(
        default="session_created", description="Status of session creation"
    )
    message: Optional[str] = Field(
        default=None, description="Additional message if needed"
    )
