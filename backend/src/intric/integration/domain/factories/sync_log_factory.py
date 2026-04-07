from datetime import datetime
from typing import cast
from uuid import UUID

from intric.database.tables.sync_log_table import SyncLog as SyncLogDBModel
from intric.integration.domain.entities.sync_log import SyncLog


class SyncLogFactory:
    """Factory for creating SyncLog domain entities from database records."""

    @staticmethod
    def create_from_db(record: SyncLogDBModel) -> SyncLog:
        """Convert database record to domain entity."""
        return SyncLog(
            id=cast(UUID, record.id),
            created_at=cast(datetime | None, record.created_at),
            updated_at=cast(datetime | None, record.updated_at),
            integration_knowledge_id=cast(UUID, record.integration_knowledge_id),
            sync_type=cast(str, record.sync_type),
            status=cast(str, record.status),
            error_message=cast(str | None, record.error_message),
            metadata=cast(dict, record.sync_metadata),
            started_at=cast(datetime, record.started_at),
            completed_at=cast(datetime | None, record.completed_at),
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
