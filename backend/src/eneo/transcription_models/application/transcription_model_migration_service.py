"""Transcription-model migration service.

Thin subclass of the shared `BaseModelMigrationService`. Transcription is the
simplest model type to migrate — it produces no stored/indexed data, so a
migration just repoints references (`apps.transcription_model_id` and the
`spaces_transcription_models` many-to-many) and marks the source migrated.

Compatibility rules are minimal compared to completion: there are no token
limits / vision / reasoning / tool-calling to compare. The only checks are a
deprecated-target warning and the (shared) security-classification blocker.
"""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.ai_models.migration.base_migration_service import (
    BaseModelMigrationService,
)
from eneo.ai_models.migration.model_migration_history_repo import (
    ModelMigrationHistoryRepo,
)
from eneo.completion_models.presentation.completion_model_models import (
    ValidationResult,
)
from eneo.database.tables.ai_models_table import TranscriptionModels
from eneo.database.tables.app_table import Apps
from eneo.database.tables.spaces_table import SpacesTranscriptionModels
from eneo.database.tables.transcription_model_migration_history_table import (
    TranscriptionModelMigrationHistory,
)

if TYPE_CHECKING:
    from eneo.transcription_models.domain.transcription_model_repo import (
        TranscriptionModelRepository,
    )


class TranscriptionModelMigrationService(BaseModelMigrationService):
    """Service for migrating transcription model usage between models."""

    def __init__(
        self,
        session: AsyncSession,
        transcription_model_repo: "TranscriptionModelRepository",
    ):
        super().__init__(session)
        self.model_repo = transcription_model_repo
        self.history_repo = ModelMigrationHistoryRepo(
            session, TranscriptionModelMigrationHistory
        )
        self._model_table = TranscriptionModels
        self._fk_column = "transcription_model_id"
        self._spaces_link_table = SpacesTranscriptionModels
        self._entity_table_map = {"apps": Apps}
        self._migratable_entity_types = ["apps", "spaces"]

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

        if blockers:
            return ValidationResult(
                compatible=False,
                warnings=blockers + issues,
                warning_codes=blocker_codes + issue_codes,
                requires_confirmation=True,
            )

        return ValidationResult(
            compatible=len(issues) == 0,
            warnings=issues,
            warning_codes=issue_codes,
            requires_confirmation=len(issues) > 0,
        )
