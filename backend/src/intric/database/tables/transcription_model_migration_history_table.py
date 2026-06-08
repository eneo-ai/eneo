"""Database table for transcription model migration history.

Mirrors `completion_model_migration_history` column-for-column so the shared
`ModelMigrationHistoryRepo` can operate on either table. Only the foreign keys
differ (they point at `transcription_models`).
"""

from typing import Optional

from sqlalchemy import JSON, TIMESTAMP, Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from intric.database.tables.base_class import BasePublic


class TranscriptionModelMigrationHistory(BasePublic):
    """Table for tracking transcription model migration history."""

    __tablename__ = "transcription_model_migration_history"  # type: ignore[assignment]

    migration_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_model_id = Column(
        UUID(as_uuid=True),
        ForeignKey("transcription_models.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    to_model_id = Column(
        UUID(as_uuid=True),
        ForeignKey("transcription_models.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    from_model_name = Column(String(255), nullable=True)
    to_model_name = Column(String(255), nullable=True)
    from_provider_type = Column(String(255), nullable=True)
    to_provider_type = Column(String(255), nullable=True)
    initiated_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(50), nullable=False, index=True)
    entity_types = Column(JSON, nullable=True)
    affected_count = Column(Integer, nullable=False, default=0)
    migrated_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    warnings = Column(JSON, nullable=True)
    migration_details = Column(JSON, nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
