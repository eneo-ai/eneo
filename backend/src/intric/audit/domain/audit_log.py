"""Audit log domain model."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.constants import (
    MAX_DESCRIPTION_LENGTH,
    MAX_ERROR_MESSAGE_LENGTH,
    MAX_USER_AGENT_LENGTH,
)
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome


@dataclass
class AuditLog:
    """Immutable record of a business action performed in the system.

    This is the core domain model for audit logging. All audit logs are immutable
    once created to ensure audit trail integrity. The model enforces key invariants:
    - Failure outcomes require an error message
    - Description must be non-empty and within length limits
    - Error messages and user agents have maximum length constraints

    Attributes:
        id: Unique identifier for this audit log
        tenant_id: Tenant that owns this audit log (multi-tenancy isolation)
        actor_id: User/API key ID (optional for system actions or deleted actors)
        actor_type: Type of actor (USER, SYSTEM, API_KEY)
        action: Type of action performed (see ActionType enum)
        entity_type: Type of entity affected (see EntityType enum)
        entity_id: ID of the entity affected
        timestamp: When the action occurred (timezone-aware UTC)
        description: Human-readable description of what happened
        metadata: Additional context (actor snapshot, target snapshot, changes)
        outcome: Whether the action succeeded or failed
        ip_address: Client IP address (optional, for forensics)
        user_agent: Client user agent (optional, for forensics)
        request_id: Request correlation ID (optional, for tracing)
        error_message: Error details if outcome is FAILURE
        deleted_at: Soft delete timestamp (for retention policies)
        created_at: Record creation timestamp
        updated_at: Record last update timestamp
    """

    id: UUID
    tenant_id: UUID
    actor_id: Optional[UUID]
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
        """Validate domain invariants.

        Raises:
            ValueError: If any invariant is violated
        """
        # Outcome validation
        if self.outcome == Outcome.FAILURE and not self.error_message:
            raise ValueError("error_message required when outcome is failure")

        # Description validation
        if not self.description or not self.description.strip():
            raise ValueError("description must not be empty")
        if len(self.description) > MAX_DESCRIPTION_LENGTH:
            raise ValueError(
                f"description must not exceed {MAX_DESCRIPTION_LENGTH} characters "
                f"(got {len(self.description)})"
            )

        # Error message validation
        if self.error_message and len(self.error_message) > MAX_ERROR_MESSAGE_LENGTH:
            raise ValueError(
                f"error_message must not exceed {MAX_ERROR_MESSAGE_LENGTH} characters "
                f"(got {len(self.error_message)})"
            )

        # User agent validation
        if self.user_agent and len(self.user_agent) > MAX_USER_AGENT_LENGTH:
            # Truncate instead of raising (user agents can be very long)
            object.__setattr__(
                self, "user_agent", self.user_agent[:MAX_USER_AGENT_LENGTH]
            )
