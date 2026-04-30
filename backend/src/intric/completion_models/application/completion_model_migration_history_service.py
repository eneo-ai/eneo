"""Service for completion model migration history operations."""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intric.completion_models.domain.completion_model_migration_history_repo import (
    CompletionModelMigrationHistoryRepo,
)
from intric.completion_models.presentation.completion_model_models import (
    ModelMigrationHistory,
)
from intric.database.tables.ai_models_table import CompletionModels
from intric.database.tables.completion_model_migration_history_table import (
    CompletionModelMigrationHistory,
)
from intric.database.tables.users_table import Users


class CompletionModelMigrationHistoryService:
    """Service for managing completion model migration history."""

    def __init__(self, session: AsyncSession):
        super().__init__()
        self.session = session
        self.repo = CompletionModelMigrationHistoryRepo(session)

    async def get_migration_history_for_model(
        self,
        model_id: UUID,
        tenant_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ModelMigrationHistory]:
        """Get migration history for a specific live model with names and user info."""
        migration_records = await self.repo.get_migration_history_for_model(
            model_id, tenant_id, limit, offset
        )

        return await self._convert_to_public_models(migration_records)

    async def get_migration_history_for_tenant(
        self,
        tenant_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ModelMigrationHistory]:
        """Get all migration history for a tenant with model names and user info."""
        migration_records = await self.repo.get_migration_history_for_tenant(
            tenant_id, limit, offset
        )

        return await self._convert_to_public_models(migration_records)

    async def get_migration_history_by_id(
        self,
        migration_id: UUID,
        tenant_id: UUID,
    ) -> ModelMigrationHistory | None:
        """Get a specific migration history record by ID."""
        migration_record = await self.repo.get_migration_history_by_id(
            migration_id, tenant_id
        )

        if migration_record:
            converted = await self._convert_to_public_models([migration_record])
            return converted[0] if converted else None

        return None

    async def _convert_to_public_models(
        self, migration_records: list[CompletionModelMigrationHistory]
    ) -> list[ModelMigrationHistory]:
        """Convert database records to public API models with names populated."""
        if not migration_records:
            return []

        # Extract unique IDs for batch queries
        model_ids: set[UUID] = set()
        user_ids: set[UUID] = set()

        for record in migration_records:
            from_model_id = cast(UUID | None, record.from_model_id)
            to_model_id = cast(UUID | None, record.to_model_id)
            if from_model_id is not None:
                model_ids.add(from_model_id)
            if to_model_id is not None:
                model_ids.add(to_model_id)
            user_ids.add(cast(UUID, record.initiated_by))

        # Batch fetch model names
        model_names = await self._get_model_names(list(model_ids))

        # Batch fetch user names
        user_names = await self._get_user_names(list(user_ids))

        # Convert to public models
        public_models: list[ModelMigrationHistory] = []
        for record in migration_records:
            from_model_id = cast(UUID | None, record.from_model_id)
            to_model_id = cast(UUID | None, record.to_model_id)
            initiated_by = cast(UUID, record.initiated_by)
            migrated_count = cast(int, record.migrated_count)
            status = cast(str, record.status)
            started_at = cast(datetime | None, record.started_at)
            completed_at = cast(datetime | None, record.completed_at)
            duration_seconds = cast(
                float | None, getattr(record, "duration_seconds", None)
            )
            error_message = cast(str | None, record.error_message)
            stored_from_name = cast(
                str | None, getattr(record, "from_model_name", None)
            )
            stored_to_name = cast(str | None, getattr(record, "to_model_name", None))
            migration_details = cast(
                dict[str, int] | None, getattr(record, "migration_details", None)
            )
            warnings = cast(list[str] | None, getattr(record, "warnings", None))

            # Use stored names first, fall back to live lookup
            from_model_name = stored_from_name or (
                model_names.get(from_model_id, "Deleted model")
                if from_model_id is not None
                else "Deleted model"
            )
            to_model_name = stored_to_name or (
                model_names.get(to_model_id, "Deleted model")
                if to_model_id is not None
                else "Deleted model"
            )
            initiated_by_name = user_names.get(initiated_by, "Unknown User")

            public_model = ModelMigrationHistory(
                id=record.id,
                from_model_id=from_model_id,
                from_model_name=from_model_name,
                to_model_id=to_model_id,
                to_model_name=to_model_name,
                migrated_count=migrated_count,
                status=status,
                initiated_by_id=initiated_by,
                initiated_by_name=initiated_by_name,
                started_at=started_at,
                completed_at=completed_at,
                duration=duration_seconds,
                error_message=error_message,
                migration_details=migration_details,
                warnings=warnings,
            )
            public_models.append(public_model)

        return public_models

    async def _get_model_names(self, model_ids: list[UUID]) -> dict[UUID, str]:
        """Get model names for given IDs."""
        if not model_ids:
            return {}

        stmt = select(CompletionModels.id, CompletionModels.name).where(
            CompletionModels.id.in_(model_ids)
        )

        result = await self.session.execute(stmt)
        return {row.id: row.name for row in result.fetchall()}

    async def _get_user_names(self, user_ids: list[UUID]) -> dict[UUID, str]:
        """Get user names for given IDs."""
        if not user_ids:
            return {}

        stmt = select(Users.id, Users.email).where(
            Users.id.in_(user_ids), Users.deleted_at.is_(None)
        )

        result = await self.session.execute(stmt)
        return {row.id: row.email for row in result.fetchall()}

    async def count_migration_history_for_model(
        self,
        model_id: UUID,
        tenant_id: UUID,
    ) -> int:
        """Count migration history records for a specific model."""
        return await self.repo.count_migration_history_for_model(model_id, tenant_id)

    async def count_migration_history_for_tenant(
        self,
        tenant_id: UUID,
    ) -> int:
        """Count all migration history records for a tenant."""
        return await self.repo.count_migration_history_for_tenant(tenant_id)
