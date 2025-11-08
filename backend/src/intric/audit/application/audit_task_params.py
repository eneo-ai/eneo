"""Task parameters for audit logging ARQ worker."""

from datetime import datetime
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
