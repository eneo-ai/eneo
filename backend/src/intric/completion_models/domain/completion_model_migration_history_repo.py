"""Repository for completion model migration history operations.

Thin wrapper over the shared `ModelMigrationHistoryRepo`, bound to the
completion history table. All CRUD lives in the shared base so completion and
transcription stay in lockstep.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from intric.ai_models.migration.model_migration_history_repo import (
    ModelMigrationHistoryRepo,
)
from intric.database.tables.completion_model_migration_history_table import (
    CompletionModelMigrationHistory,
)


class CompletionModelMigrationHistoryRepo(ModelMigrationHistoryRepo):
    """Repository for managing completion model migration history."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, CompletionModelMigrationHistory)
