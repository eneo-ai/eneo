"""Service for completion model migration history operations.

Thin subclass of the shared `ModelMigrationHistoryService`, bound to the
completion history repo and model table.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from intric.ai_models.migration.model_migration_history_service import (
    ModelMigrationHistoryService,
)
from intric.completion_models.domain.completion_model_migration_history_repo import (
    CompletionModelMigrationHistoryRepo,
)
from intric.database.tables.ai_models_table import CompletionModels


class CompletionModelMigrationHistoryService(ModelMigrationHistoryService):
    """Service for managing completion model migration history."""

    def __init__(self, session: AsyncSession):
        super().__init__(
            session, CompletionModelMigrationHistoryRepo(session), CompletionModels
        )
