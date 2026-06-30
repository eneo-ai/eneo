"""Completion-model migration service.

Thin subclass of the shared `BaseModelMigrationService`. All orchestration
(history, events, savepoint execution, generic entity repoint, spaces) lives in
the base; this class supplies only the completion-specific parts:

  - compatibility rules (token limits, family, vision/reasoning/tool-calling,
    security classification)
  - the assistant special-case (enable target on spaces + reset kwargs)
  - usage-stats recalculation after a successful migration
"""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from eneo.ai_models.migration.base_migration_service import (
    BaseModelMigrationService,
)
from eneo.completion_models.application.completion_model_usage_service import (
    CompletionModelUsageService,
)
from eneo.completion_models.constants import (
    ENTITY_TABLE_MAP,
    MIGRATABLE_ENTITY_TYPES,
)
from eneo.completion_models.domain.completion_model_migration_history_repo import (
    CompletionModelMigrationHistoryRepo,
)
from eneo.completion_models.presentation.completion_model_models import (
    ValidationResult,
)
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.spaces_table import SpacesCompletionModels

if TYPE_CHECKING:
    from eneo.completion_models.domain.completion_model_repo import (
        CompletionModelRepository,
    )


class CompletionModelMigrationService(BaseModelMigrationService):
    """Service for migrating completion model usage between models."""

    def __init__(
        self,
        session: AsyncSession,
        completion_model_repo: "CompletionModelRepository",
        usage_service: CompletionModelUsageService,
    ):
        super().__init__(session)
        self.model_repo = completion_model_repo
        self.usage_service = usage_service
        self.history_repo = CompletionModelMigrationHistoryRepo(session)
        self._model_table = CompletionModels
        self._fk_column = "completion_model_id"
        self._spaces_link_table = SpacesCompletionModels
        self._entity_table_map = ENTITY_TABLE_MAP
        self._migratable_entity_types = list(MIGRATABLE_ENTITY_TYPES)

    # ------------------------------------------------------------ compat rules
    async def _validate_migration_compatibility(
        self, from_model_id: UUID, to_model_id: UUID, tenant_id: UUID
    ) -> ValidationResult:
        from_model = await self.model_repo.one(model_id=from_model_id)
        to_model = await self.model_repo.one(model_id=to_model_id)
        self._ensure_source_model_not_already_migrated(from_model)

        issues: list[str] = []
        issue_codes: list[str] = []
        blockers: list[str] = []
        blocker_codes: list[str] = []

        if to_model.is_effectively_deprecated:
            issues.append("Target model is deprecated")
            issue_codes.append("target_deprecated")

        if from_model.max_input_tokens > to_model.max_input_tokens:
            issues.append(
                f"Target model has lower input token limit: {to_model.max_input_tokens}"
            )
            issue_codes.append(f"lower_token_limit:{to_model.max_input_tokens}")

        if from_model.family != to_model.family:
            issues.append(
                f"Different model families: {from_model.family} → {to_model.family}"
            )
            issue_codes.append(
                f"different_family:{from_model.family}:{to_model.family}"
            )

        if from_model.vision and not to_model.vision:
            issues.append("Target model lacks vision support")
            issue_codes.append("lacks_vision")

        if from_model.reasoning and not to_model.reasoning:
            issues.append("Target model lacks reasoning support")
            issue_codes.append("lacks_reasoning")

        if from_model.supports_tool_calling and not to_model.supports_tool_calling:
            issues.append("Target model lacks tool calling support")
            issue_codes.append("lacks_tool_calling")

        target_level = (
            to_model.security_classification.security_level
            if to_model.security_classification
            else 0
        )
        insufficient_spaces = await self._count_spaces_with_insufficient_classification(
            from_model_id, target_level, tenant_id
        )
        if insufficient_spaces > 0:
            target_name = (
                to_model.security_classification.name
                if to_model.security_classification
                else "none"
            )
            blockers.append(
                f"Target model classification is too low for {insufficient_spaces} spaces that require {target_name} or higher"
            )
            blocker_codes.append(
                f"security_classification_insufficient:{insufficient_spaces}:{target_name}"
            )

        info_warnings = [
            "Assistant model parameters (kwargs) will be reset to defaults"
        ]
        info_codes = ["kwargs_reset"]

        if blockers:
            return ValidationResult(
                compatible=False,
                warnings=blockers + issues + info_warnings,
                warning_codes=blocker_codes + issue_codes + info_codes,
                requires_confirmation=True,
            )

        return ValidationResult(
            compatible=len(issues) == 0,
            warnings=issues + info_warnings,
            warning_codes=issue_codes + info_codes,
            requires_confirmation=len(issues) > 0,
        )

    # --------------------------------------------------------- special entities
    def _special_entity_migrators(self) -> dict[str, Any]:
        return {"assistants": self._migrate_assistants_with_kwargs}

    async def _migrate_assistants_with_kwargs(
        self,
        from_model_id: UUID,
        to_model_id: UUID,
        tenant_id: UUID,
        table: Any,
        tenant_condition: ColumnElement[bool],
    ) -> int:
        from sqlalchemy import update

        await self._ensure_target_model_enabled_on_spaces(
            from_model_id, to_model_id, tenant_id
        )

        stmt = (
            update(table)
            .where(
                and_(
                    table.completion_model_id == from_model_id,
                    tenant_condition,
                )
            )
            .values(
                completion_model_id=to_model_id,
                completion_model_kwargs={},
            )
        )
        result = await self.session.execute(stmt)
        migrated_count = result.rowcount or 0
        self.logger.info(
            f"Migrated {migrated_count} assistants from {from_model_id} to {to_model_id}, kwargs reset"
        )
        return migrated_count

    async def _ensure_target_model_enabled_on_spaces(
        self, from_model_id: UUID, to_model_id: UUID, tenant_id: UUID
    ) -> None:
        from sqlalchemy import and_ as sa_and
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert

        from eneo.database.tables.spaces_table import Spaces, SpacesCompletionModels

        spaces_with_source_model_stmt = (
            select(SpacesCompletionModels.space_id)
            .select_from(SpacesCompletionModels)
            .join(Spaces, SpacesCompletionModels.space_id == Spaces.id)
            .where(
                sa_and(
                    SpacesCompletionModels.completion_model_id == from_model_id,
                    Spaces.tenant_id == tenant_id,
                )
            )
        )
        result = await self.session.execute(spaces_with_source_model_stmt)
        space_ids = [row.space_id for row in result.fetchall()]
        if not space_ids:
            return

        for space_id in space_ids:
            insert_stmt = insert(SpacesCompletionModels).values(
                space_id=space_id, completion_model_id=to_model_id
            )
            insert_stmt = insert_stmt.on_conflict_do_nothing()
            await self.session.execute(insert_stmt)

    # ------------------------------------------------------------- after-hook
    async def _after_execute(
        self, migration_id: UUID, migrated_count: int, tenant_id: UUID
    ) -> tuple[bool, bool]:
        threshold = self.settings.migration_auto_recalc_threshold
        if migrated_count <= threshold:
            try:
                await self.usage_service.recalculate_all_usage_stats_in_transaction(
                    tenant_id
                )
                return (True, False)
            except Exception as e:
                self.logger.error(
                    "Auto-recalculation failed, manual recalculation required",
                    extra={"migration_id": str(migration_id), "error": str(e)},
                )
                return (False, True)
        return (False, True)
