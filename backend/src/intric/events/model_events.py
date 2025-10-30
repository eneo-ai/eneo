"""Domain events for completion model operations."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID


# Base class for all domain events
@dataclass
class DomainEvent:
    """Base class for domain events."""
    pass


@dataclass
class ModelMigrationStarted(DomainEvent):
    """Emitted when a model migration begins."""
    migration_id: UUID
    from_model_id: UUID
    to_model_id: UUID
    affected_count: int
    initiated_by: UUID
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ModelMigrationCompleted(DomainEvent):
    """Emitted when a model migration completes successfully."""
    migration_id: UUID
    migrated_count: int
    duration_seconds: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ModelMigrationFailed(DomainEvent):
    """Emitted when a model migration fails."""
    migration_id: UUID
    error_message: str
    failed_at_entity: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ModelUsageStatsUpdated(DomainEvent):
    """Emitted when usage statistics are updated."""
    model_id: Optional[UUID]  # None means all models
    tenant_id: UUID
    update_type: str  # 'incremental' or 'full'
    timestamp: datetime = field(default_factory=datetime.utcnow)