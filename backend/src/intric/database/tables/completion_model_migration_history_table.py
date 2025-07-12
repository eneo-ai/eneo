"""Database table for completion model migration history."""

from sqlalchemy import Column, String, Text, JSON, Integer, Float, ForeignKey, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from intric.database.tables.base_class import BasePublic


class CompletionModelMigrationHistory(BasePublic):
    """Table for tracking completion model migration history."""
    
    __tablename__ = "completion_model_migration_history"
    
    migration_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    from_model_id = Column(UUID(as_uuid=True), ForeignKey("completion_models.id", ondelete="CASCADE"), nullable=False, index=True)
    to_model_id = Column(UUID(as_uuid=True), ForeignKey("completion_models.id", ondelete="CASCADE"), nullable=False, index=True)
    initiated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    entity_types = Column(JSON, nullable=True)
    affected_count = Column(Integer, nullable=False, default=0)
    migrated_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    duration_seconds = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    warnings = Column(JSON, nullable=True)
    migration_details = Column(JSON, nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)