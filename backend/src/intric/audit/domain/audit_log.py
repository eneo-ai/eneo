"""Audit log domain model."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome


@dataclass
class AuditLog:
    """Immutable record of a business action performed in the system."""

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
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        """Validate invariants."""
        if self.outcome == Outcome.FAILURE and not self.error_message:
            raise ValueError("error_message required when outcome is failure")
