"""Generic migration-history read service shared by completion and transcription.

Maps history DB rows to the `ModelMigrationHistory` presentation model,
resolving model and initiator names. Parameterized by the history repo and the
model table (for name lookup); everything else is identical across model types.
"""

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intric.ai_models.migration.model_migration_history_repo import (
    ModelMigrationHistoryRepo,
)
from intric.completion_models.presentation.completion_model_models import (
    ModelMigrationHistory,
)
from intric.database.tables.users_table import Users


class ModelMigrationHistoryService:
    """Read/format migration history for one model type."""

    def __init__(
        self,
        session: AsyncSession,
        repo: ModelMigrationHistoryRepo,
        model_table: Any,
    ):
        self.session = session
        self.repo = repo
        self._model_table = model_table

    async def get_migration_history_for_model(
        self, model_id: UUID, tenant_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[ModelMigrationHistory]:
        records = await self.repo.get_migration_history_for_model(
            model_id, tenant_id, limit, offset
        )
        return await self._convert_to_public_models(records)

    async def get_migration_history_for_tenant(
        self, tenant_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[ModelMigrationHistory]:
        records = await self.repo.get_migration_history_for_tenant(
            tenant_id, limit, offset
        )
        return await self._convert_to_public_models(records)

    async def get_migration_history_by_id(
        self, migration_id: UUID, tenant_id: UUID
    ) -> ModelMigrationHistory | None:
        record = await self.repo.get_migration_history_by_id(migration_id, tenant_id)
        if record:
            converted = await self._convert_to_public_models([record])
            return converted[0] if converted else None
        return None

    async def count_migration_history_for_model(
        self, model_id: UUID, tenant_id: UUID
    ) -> int:
        return await self.repo.count_migration_history_for_model(model_id, tenant_id)

    async def count_migration_history_for_tenant(self, tenant_id: UUID) -> int:
        return await self.repo.count_migration_history_for_tenant(tenant_id)

    async def _convert_to_public_models(
        self, records: list[Any]
    ) -> list[ModelMigrationHistory]:
        if not records:
            return []

        model_ids: set[UUID] = set()
        user_ids: set[UUID] = set()
        for record in records:
            from_model_id = cast(UUID | None, record.from_model_id)
            to_model_id = cast(UUID | None, record.to_model_id)
            if from_model_id is not None:
                model_ids.add(from_model_id)
            if to_model_id is not None:
                model_ids.add(to_model_id)
            user_ids.add(cast(UUID, record.initiated_by))

        model_names = await self._get_model_names(list(model_ids))
        user_names = await self._get_user_names(list(user_ids))

        public_models: list[ModelMigrationHistory] = []
        for record in records:
            from_model_id = cast(UUID | None, record.from_model_id)
            to_model_id = cast(UUID | None, record.to_model_id)
            initiated_by = cast(UUID, record.initiated_by)
            stored_from_name = cast(
                str | None, getattr(record, "from_model_name", None)
            )
            stored_to_name = cast(str | None, getattr(record, "to_model_name", None))

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

            public_models.append(
                ModelMigrationHistory(
                    id=record.id,
                    from_model_id=from_model_id,
                    from_model_name=from_model_name,
                    to_model_id=to_model_id,
                    to_model_name=to_model_name,
                    migrated_count=cast(int, record.migrated_count),
                    status=cast(str, record.status),
                    initiated_by_id=initiated_by,
                    initiated_by_name=user_names.get(initiated_by, "Unknown User"),
                    started_at=cast(datetime | None, record.started_at),
                    completed_at=cast(datetime | None, record.completed_at),
                    duration=cast(
                        float | None, getattr(record, "duration_seconds", None)
                    ),
                    error_message=cast(str | None, record.error_message),
                    migration_details=cast(
                        dict[str, int] | None,
                        getattr(record, "migration_details", None),
                    ),
                    warnings=cast(list[str] | None, getattr(record, "warnings", None)),
                )
            )

        return public_models

    async def _get_model_names(self, model_ids: list[UUID]) -> dict[UUID, str]:
        if not model_ids:
            return {}
        stmt = select(self._model_table.id, self._model_table.name).where(
            self._model_table.id.in_(model_ids)
        )
        result = await self.session.execute(stmt)
        return {row.id: row.name for row in result.fetchall()}

    async def _get_user_names(self, user_ids: list[UUID]) -> dict[UUID, str]:
        if not user_ids:
            return {}
        stmt = select(Users.id, Users.email).where(
            Users.id.in_(user_ids), Users.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return {row.id: row.email for row in result.fetchall()}
