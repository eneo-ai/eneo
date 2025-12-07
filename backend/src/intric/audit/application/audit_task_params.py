"""Task parameters for audit logging ARQ worker."""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome


class AuditLogTaskParams(BaseModel):
    """Parameters for async audit log creation."""

    tenant_id: UUID
    actor_id: UUID
    actor_type: ActorType = ActorType.USER
    action: ActionType
    entity_type: EntityType
    entity_id: UUID
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    description: str = Field(min_length=1, max_length=500)
    metadata: dict = Field(default_factory=dict)
    outcome: Outcome = Outcome.SUCCESS
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[UUID] = None
    error_message: Optional[str] = None


class ExportFormat(str, Enum):
    """Supported export file formats."""

    CSV = "csv"
    JSONL = "jsonl"


class AuditExportTaskParams(BaseModel):
    """Parameters for async audit log export job.

    Attributes:
        tenant_id: Tenant ID for multi-tenant isolation
        user_id: For GDPR export (user as actor OR target)
        actor_id: Filter by actor who performed actions
        action: Filter by action type
        from_date: Filter from date (inclusive)
        to_date: Filter to date (inclusive)
        format: Export format (csv or jsonl)
        max_records: Maximum records to export (None for unlimited)
    """

    tenant_id: UUID
    user_id: Optional[UUID] = None  # GDPR export filter
    actor_id: Optional[UUID] = None
    action: Optional[str] = None  # ActionType value as string
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    format: ExportFormat = ExportFormat.CSV
    max_records: Optional[int] = Field(default=None, ge=1)

    def to_dict(self) -> dict:
        """Convert to dict for ARQ job serialization."""
        return {
            "tenant_id": str(self.tenant_id),
            "user_id": str(self.user_id) if self.user_id else None,
            "actor_id": str(self.actor_id) if self.actor_id else None,
            "action": self.action,
            "from_date": self.from_date.isoformat() if self.from_date else None,
            "to_date": self.to_date.isoformat() if self.to_date else None,
            "format": self.format.value,
            "max_records": self.max_records,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AuditExportTaskParams":
        """Create from dict received by ARQ worker."""
        return cls(
            tenant_id=UUID(data["tenant_id"]),
            user_id=UUID(data["user_id"]) if data.get("user_id") else None,
            actor_id=UUID(data["actor_id"]) if data.get("actor_id") else None,
            action=data.get("action"),
            from_date=datetime.fromisoformat(data["from_date"]) if data.get("from_date") else None,
            to_date=datetime.fromisoformat(data["to_date"]) if data.get("to_date") else None,
            format=ExportFormat(data.get("format", "csv")),
            max_records=data.get("max_records"),
        )
