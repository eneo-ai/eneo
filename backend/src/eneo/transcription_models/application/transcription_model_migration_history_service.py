"""Service for transcription model migration history operations.

Thin subclass of the shared `ModelMigrationHistoryService`, bound to the
transcription history table and model table.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.ai_models.migration.model_migration_history_repo import (
    ModelMigrationHistoryRepo,
)
from eneo.ai_models.migration.model_migration_history_service import (
    ModelMigrationHistoryService,
)
from eneo.database.tables.ai_models_table import TranscriptionModels
from eneo.database.tables.transcription_model_migration_history_table import (
    TranscriptionModelMigrationHistory,
)


class TranscriptionModelMigrationHistoryService(ModelMigrationHistoryService):
    """Service for managing transcription model migration history."""

    def __init__(self, session: AsyncSession):
        super().__init__(
            session,
            ModelMigrationHistoryRepo(session, TranscriptionModelMigrationHistory),
            TranscriptionModels,
        )
