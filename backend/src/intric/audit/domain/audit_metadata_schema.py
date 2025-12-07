"""Pydantic schemas for standardized audit log metadata.

These schemas ensure consistency across all audit log entries and prevent
"structure drift" where different parts of the codebase emit slightly
different metadata formats.

Usage:
    from intric.audit.domain.audit_metadata_schema import (
        AuditMetadata, AuditActor, AuditTarget, AuditChange
    )

    metadata = AuditMetadata(
        actor=AuditActor(id=str(user.id), name=user.username, email=user.email),
        target=AuditTarget(id=str(space.id), name=space.name),
        changes={"name": AuditChange(old=old_name, new=new_name)}
    )

    await audit_service.log_async(..., metadata=metadata.to_dict())
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class AuditActor(BaseModel):
    """Actor who performed the action.

    Stores snapshot of actor details at the time of the action.
    This ensures audit logs remain accurate even if the user is
    later deleted or renamed.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: Optional[str] = None
    email: Optional[str] = None
    type: Optional[str] = None  # e.g., "user", "system", "api_key"
    via: Optional[str] = None  # e.g., "web", "api", "cron_job"


class AuditTarget(BaseModel):
    """Target entity affected by the action.

    Stores snapshot of target details at the time of the action.
    Allows extra fields for context-specific data (e.g., space_name
    for member operations, model_name for model changes).
    """

    model_config = ConfigDict(extra="allow")

    id: str
    name: Optional[str] = None


class AuditChange(BaseModel):
    """A single field change with old and new values.

    Used to track what changed in update operations.
    Both old and new can be any JSON-serializable value.
    """

    model_config = ConfigDict(extra="forbid")

    old: Any
    new: Any


class AuditMetadata(BaseModel):
    """Standardized audit log metadata schema.

    All audit logs should follow this pattern to ensure consistency
    and make logs useful for debugging and incident tracking.

    Structure:
        {
            "actor": {"id": "...", "name": "...", "email": "..."},
            "target": {"id": "...", "name": "...", ...extra context},
            "changes": {"field_name": {"old": ..., "new": ...}}
        }
    """

    model_config = ConfigDict(extra="forbid")

    actor: AuditActor
    target: AuditTarget
    changes: Dict[str, AuditChange] = Field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dict for JSONB storage.

        Excludes None values for optional fields (actor.email, target.name, etc.)
        but PRESERVES None in changes because None is semantically meaningful
        (e.g., old=None means "was previously unset").
        """
        result = self.model_dump(exclude_none=True)
        # Restore None values in changes that were incorrectly excluded
        if self.changes:
            result["changes"] = {
                key: {"old": change.old, "new": change.new}
                for key, change in self.changes.items()
            }
        return result

    @classmethod
    def create_simple(
        cls,
        actor_id: str,
        target_id: str,
        actor_name: Optional[str] = None,
        actor_email: Optional[str] = None,
        target_name: Optional[str] = None,
        **target_extra: Any,
    ) -> "AuditMetadata":
        """Convenience factory for simple audit entries without changes.

        Args:
            actor_id: UUID string of the actor
            target_id: UUID string of the target entity
            actor_name: Optional actor display name
            actor_email: Optional actor email
            target_name: Optional target display name
            **target_extra: Additional context for target (e.g., space_name)

        Returns:
            AuditMetadata instance ready for to_dict()
        """
        target_data = {"id": target_id, "name": target_name, **target_extra}
        return cls(
            actor=AuditActor(id=actor_id, name=actor_name, email=actor_email),
            target=AuditTarget(**target_data),
        )
