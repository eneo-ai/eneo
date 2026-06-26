from typing import cast

from intric.database.tables.sync_log_table import SyncLog as SyncLogDBModel
from intric.integration.domain.entities.sync_log import SyncLog
from intric.integration.domain.value_objects import SyncMetadata


class SyncLogFactory:
    """Factory for creating SyncLog domain entities from database records."""

    @staticmethod
    def create_from_db(record: SyncLogDBModel) -> SyncLog:
        """Convert database record to domain entity."""
        # sync_metadata comes from JSON column — cast to SyncMetadata for type safety
        raw_metadata = record.sync_metadata
        metadata: SyncMetadata | None = (
            cast(SyncMetadata, raw_metadata) if isinstance(raw_metadata, dict) else None
        )
        return SyncLog(
            id=record.id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            integration_knowledge_id=record.integration_knowledge_id,
            sync_type=record.sync_type,
            status=record.status,
            error_message=record.error_message,
            metadata=metadata,
            started_at=record.started_at,
            completed_at=record.completed_at,
        )

    @staticmethod
    def to_db(entity: SyncLog) -> SyncLogDBModel:
        """Convert domain entity to database record."""
        return SyncLogDBModel(
            **dict(  # type: ignore[arg-type]
                id=entity.id,
                created_at=entity.created_at,
                updated_at=entity.updated_at,
                integration_knowledge_id=entity.integration_knowledge_id,
                sync_type=entity.sync_type,
                status=entity.status,
                error_message=entity.error_message,
                sync_metadata=entity.metadata,
                started_at=entity.started_at,
                completed_at=entity.completed_at,
            )
        )
