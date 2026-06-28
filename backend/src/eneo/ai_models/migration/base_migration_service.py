"""Generic model-migration engine shared by completion and transcription.

The orchestration (validate → history → events → savepoint execute → history →
events), the per-entity repoint logic, spaces many-to-many handling, counting
and tenant filtering are all identical across model types and live here. Each
model type subclasses and supplies only its specifics:

  - the model table, the FK column name, the spaces link table, the entity map
    and migratable entity-type list (instance attributes set in `__init__`)
  - `_validate_migration_compatibility` (the model-specific compatibility rules)
  - `_special_entity_migrators` (e.g. completion's assistant kwargs reset)
  - `_after_execute` (e.g. completion's usage-stats recalculation)

Behavioural note: this began as a straight extraction of the original
`CompletionModelMigrationService` (orchestration, repoint logic and validation
messages are byte-for-byte preserved). One behaviour was intentionally changed
for *both* model types when partial migrations were hardened: the source is
latched (`migrated_to_model_id`) only once no migratable surface still
references it (see `_has_remaining_source_references`) rather than
unconditionally after every run, and a partial migration to a different target
than an earlier completed one is rejected (see the split-target guard in
`_ensure_partial_migrations_keep_same_target`). The full-migration path the
frontend uses (entity_types omitted → all surfaces in one call) latches exactly
as before.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, select, true, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from eneo.ai_models.migration.model_migration_history_repo import (
    ModelMigrationHistoryRepo,
)
from eneo.completion_models.presentation.completion_model_models import (
    MigrationResult,
    ValidationResult,
)
from eneo.events import (
    ModelMigrationCompleted,
    ModelMigrationFailed,
    ModelMigrationStarted,
    get_event_publisher,
)
from eneo.main.config import get_settings
from eneo.main.exceptions import ValidationException


class BaseModelMigrationService:
    """Shared engine for migrating model usage between models of one type."""

    # Embedding migration is intentionally not wired up on this engine yet.
    # Completion and transcription migrations only *repoint* references (an FK
    # swap plus the spaces many-to-many), which is exactly what the generic
    # logic below does. Embedding is fundamentally different: the stored vectors
    # in collections, websites, integration_knowledge and info_blob_chunks were
    # produced by the old model, so switching embedding models means
    # *re-embedding* all of that knowledge — not just repointing it. The thinking
    # is that an embedding subclass would keep the same orchestration here but add
    # a re-embed step (recompute + replace vectors per knowledge source, ideally
    # as a background job since it can be large/slow), most naturally as an
    # `_after_execute` override, instead of treating it as a pure reference swap.

    # --- model-specific configuration (set by subclass __init__) -----------
    model_repo: Any
    history_repo: ModelMigrationHistoryRepo
    _model_table: Any
    _fk_column: str
    _spaces_link_table: Any
    _entity_table_map: dict[str, Any]
    _migratable_entity_types: list[str]

    def __init__(self, session: AsyncSession):
        self.session = session
        self.logger = logging.getLogger(self.__class__.__module__)
        self.event_publisher = get_event_publisher()
        self.settings = get_settings()

    # ------------------------------------------------------------------ hooks
    async def _validate_migration_compatibility(
        self, from_model_id: UUID, to_model_id: UUID, tenant_id: UUID
    ) -> ValidationResult:
        raise NotImplementedError

    def _special_entity_migrators(self) -> dict[str, Any]:
        """entity_type -> async handler(from_id, to_id, tenant_id, table, tenant_condition).

        Override for model-specific repoint logic (e.g. completion's assistant
        kwargs reset). Default: none.
        """
        return {}

    async def _after_execute(
        self, migration_id: UUID, migrated_count: int, tenant_id: UUID
    ) -> tuple[bool, bool]:
        """Hook run after a successful transactional migration. Returns
        (auto_recalculated, requires_manual_recalculation). Default: no-op."""
        return (False, False)

    @staticmethod
    def _is_blocker_code(code: str) -> bool:
        # Security classification mismatches cannot be overridden with confirm.
        return code.startswith("security_classification_insufficient")

    # ------------------------------------------------------------------ public
    async def validate_migration(
        self, from_model_id: UUID, to_model_id: UUID, tenant_id: UUID
    ) -> ValidationResult:
        return await self._validate_migration_compatibility(
            from_model_id, to_model_id, tenant_id
        )

    async def count_affected_per_type(
        self, model_id: UUID, tenant_id: UUID
    ) -> dict[str, int]:
        """Per-entity-type count of what a migration would move, plus a "total".

        Powers the migrate dialog's impact preview for model types that have no
        dedicated usage-stats service (e.g. transcription)."""
        counts: dict[str, int] = {}
        for entity_type in self._migratable_entity_types:
            counts[entity_type] = await self._count_entities_by_type(
                entity_type, model_id, tenant_id
            )
        counts["total"] = sum(counts.values())
        return counts

    async def migrate_model_usage(
        self,
        from_model_id: UUID,
        to_model_id: UUID,
        entity_types: list[str] | str | None = None,
        *,
        user: Any,
        confirm_migration: bool = False,
        force_override: bool = False,
    ) -> MigrationResult:
        start_time = datetime.now(timezone.utc)
        migration_id = uuid4()

        self.logger.info(
            "Starting model migration",
            extra={
                "migration_id": str(migration_id),
                "from_model_id": str(from_model_id),
                "to_model_id": str(to_model_id),
                "tenant_id": str(user.tenant_id),
                "user_id": str(user.id),
                "entity_types": entity_types,
                "confirm_migration": confirm_migration,
                "force_override": force_override,
            },
        )

        normalized_entity_types: list[str] | None
        if isinstance(entity_types, str):
            normalized_entity_types = [entity_types]
        else:
            normalized_entity_types = entity_types

        if normalized_entity_types is not None:
            invalid_types = [
                t
                for t in normalized_entity_types
                if t not in self._migratable_entity_types
            ]
            if invalid_types:
                raise ValidationException(
                    f"Invalid entity types: {invalid_types}. "
                    f"Valid types are: {self._migratable_entity_types}"
                )

        final_entity_types: list[str] = normalized_entity_types or list(
            self._migratable_entity_types
        )

        # Validate models exist and belong to tenant
        try:
            from_model = await self.model_repo.one(model_id=from_model_id)
            if not from_model:
                raise ValidationException(
                    f"Source model not found: model with ID '{from_model_id}' does not exist."
                )
            to_model = await self.model_repo.one(model_id=to_model_id)
            if not to_model:
                raise ValidationException(
                    f"Target model not found: model with ID '{to_model_id}' does not exist."
                )
            if from_model_id == to_model_id:
                raise ValidationException(
                    f"Invalid migration: source and target models are the same ('{from_model.name}')."
                )

            self._ensure_source_model_not_already_migrated(from_model)
            await self._ensure_partial_migrations_keep_same_target(
                from_model_id, to_model_id, user.tenant_id
            )

            from_enabled = await self.session.execute(
                select(self._model_table).where(
                    and_(
                        self._model_table.id == from_model_id,
                        self._model_table.tenant_id == user.tenant_id,
                        self._model_table.is_enabled == True,  # noqa: E712
                    )
                )
            )
            if not from_enabled.scalar_one_or_none():
                raise ValidationException(
                    f"Source model not available: '{from_model.name}' is not enabled for your organization."
                )

            to_enabled = await self.session.execute(
                select(self._model_table).where(
                    and_(
                        self._model_table.id == to_model_id,
                        self._model_table.tenant_id == user.tenant_id,
                        self._model_table.is_enabled == True,  # noqa: E712
                    )
                )
            )
            if not to_enabled.scalar_one_or_none():
                raise ValidationException(
                    f"Target model not available: '{to_model.name}' is not enabled for your organization."
                )

        except ValidationException as ve:
            self.logger.warning(
                f"Migration validation rejected: {ve}",
                extra={
                    "from_model_id": str(from_model_id),
                    "to_model_id": str(to_model_id),
                },
            )
            raise
        except Exception as e:
            self.logger.error(
                "Error validating models",
                extra={
                    "from_model_id": str(from_model_id),
                    "to_model_id": str(to_model_id),
                    "error": str(e),
                },
            )
            raise ValidationException(
                "Model validation failed: unable to verify model availability."
            )

        affected_count = await self._count_affected_entities(
            from_model_id, final_entity_types, user.tenant_id
        )

        await self.history_repo.create_migration_history(
            migration_id=migration_id,
            tenant_id=user.tenant_id,
            from_model_id=from_model_id,
            to_model_id=to_model_id,
            from_model_name=from_model.name,
            to_model_name=to_model.name,
            from_provider_type=getattr(from_model, "provider_type", None),
            to_provider_type=getattr(to_model, "provider_type", None),
            initiated_by=user.id,
            status="in_progress",
            entity_types=normalized_entity_types,
            affected_count=affected_count,
            started_at=start_time,
        )

        await self.event_publisher.publish(
            ModelMigrationStarted(
                migration_id=migration_id,
                from_model_id=from_model_id,
                to_model_id=to_model_id,
                affected_count=affected_count,
                initiated_by=user.id,
                timestamp=start_time,
            )
        )

        try:
            validation_result = await self._validate_migration_compatibility(
                from_model_id, to_model_id, user.tenant_id
            )

            # Security blockers cannot be overridden with confirm_migration —
            # only the explicit force_override escape hatch bypasses them.
            has_blockers = any(
                self._is_blocker_code(code) for code in validation_result.warning_codes
            )

            if has_blockers and not force_override:
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                await self.history_repo.update_migration_history(
                    migration_id=migration_id,
                    tenant_id=user.tenant_id,
                    status="failed",
                    migrated_count=0,
                    failed_count=0,
                    duration_seconds=duration,
                    completed_at=datetime.now(timezone.utc),
                    error_message=f"Migration blocked: {', '.join(validation_result.warnings)}",
                    warnings=validation_result.warnings,
                )
                raise ValidationException(
                    f"Migration blocked by security classification: {', '.join(validation_result.warnings)}"
                )

            if has_blockers and force_override:
                self.logger.warning(
                    f"User force-overrode security classification blocker: {', '.join(validation_result.warnings)}",
                    extra={
                        "migration_id": str(migration_id),
                        "from_model_id": str(from_model_id),
                        "to_model_id": str(to_model_id),
                        "force_override": True,
                        "warnings": validation_result.warnings,
                    },
                )

            if not validation_result.compatible and not confirm_migration:
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                await self.history_repo.update_migration_history(
                    migration_id=migration_id,
                    tenant_id=user.tenant_id,
                    status="failed",
                    migrated_count=0,
                    failed_count=0,
                    duration_seconds=duration,
                    completed_at=datetime.now(timezone.utc),
                    error_message=f"Migration has compatibility issues: {', '.join(validation_result.warnings)}. Set confirm_migration=true to proceed anyway.",
                    warnings=validation_result.warnings,
                )
                raise ValidationException(
                    f"Migration has compatibility issues: {', '.join(validation_result.warnings)}. Set confirm_migration=true to proceed anyway."
                )

            if not validation_result.compatible and confirm_migration:
                self.logger.warning(
                    f"User confirmed migration despite compatibility issues: {', '.join(validation_result.warnings)}",
                    extra={"migration_id": str(migration_id)},
                )

            result = await self._execute_migration_transactionally(
                from_model_id, to_model_id, final_entity_types, user.tenant_id
            )

            migrated_count = result["total"]
            (
                auto_recalculated,
                requires_manual_recalculation,
            ) = await self._after_execute(migration_id, migrated_count, user.tenant_id)

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()

            await self.history_repo.update_migration_history(
                migration_id=migration_id,
                tenant_id=user.tenant_id,
                status="completed",
                migrated_count=result["total"],
                failed_count=0,
                duration_seconds=duration,
                completed_at=datetime.now(timezone.utc),
                warnings=validation_result.warnings
                if validation_result.warnings
                else None,
                migration_details=result,
            )

            await self.event_publisher.publish(
                ModelMigrationCompleted(
                    migration_id=migration_id,
                    migrated_count=result["total"],
                    duration_seconds=duration,
                    timestamp=datetime.now(timezone.utc),
                )
            )

            return MigrationResult(
                success=True,
                migrated_count=result["total"],
                failed_count=0,
                details=result,
                duration=duration,
                migration_id=migration_id,
                warnings=validation_result.warnings,
                auto_recalculated=auto_recalculated,
                requires_manual_recalculation=requires_manual_recalculation,
            )

        except ValidationException:
            raise
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error during model migration",
                extra={"migration_id": str(migration_id), "error": str(e)},
            )
            # Known gap: if the error aborted the surrounding transaction, this
            # "failed" history UPDATE runs in a poisoned session and itself
            # raises InFailedSqlTransactionError, so the failure row may not
            # persist. Fixing it properly needs a separate session for the
            # failure write; tracked as a follow-up.
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            await self.history_repo.update_migration_history(
                migration_id=migration_id,
                tenant_id=user.tenant_id,
                status="failed",
                migrated_count=0,
                failed_count=affected_count,
                duration_seconds=duration,
                completed_at=datetime.now(timezone.utc),
                error_message=str(e),
            )
            await self.event_publisher.publish(
                ModelMigrationFailed(
                    migration_id=migration_id,
                    error_message=f"Database error: {str(e)}",
                    timestamp=datetime.now(timezone.utc),
                )
            )
            raise ValidationException(
                f"Migration failed due to database error: {str(e)}"
            )
        except Exception as e:
            self.logger.error(
                "Unexpected error during model migration",
                extra={"migration_id": str(migration_id), "error": str(e)},
            )
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            await self.history_repo.update_migration_history(
                migration_id=migration_id,
                tenant_id=user.tenant_id,
                status="failed",
                migrated_count=0,
                failed_count=affected_count,
                duration_seconds=duration,
                completed_at=datetime.now(timezone.utc),
                error_message=str(e),
            )
            await self.event_publisher.publish(
                ModelMigrationFailed(
                    migration_id=migration_id,
                    error_message=f"Unexpected error: {str(e)}",
                    timestamp=datetime.now(timezone.utc),
                )
            )
            raise ValidationException(f"Migration failed: {str(e)}")

    # --------------------------------------------------------------- internals
    @staticmethod
    def _ensure_source_model_not_already_migrated(from_model: Any) -> None:
        if getattr(from_model, "migrated_to_model_id", None) is not None:
            raise ValidationException(
                f"Source model '{from_model.name}' has already been migrated. "
                f"A model can only be migrated once."
            )

    async def _count_spaces_with_insufficient_classification(
        self, from_model_id: UUID, target_level: int, tenant_id: UUID
    ) -> int:
        """Count spaces holding the source model whose required security level
        exceeds the target model's level. Shared by subclass compat checks."""
        from eneo.database.tables.security_classifications_table import (
            SecurityClassification as SecurityClassifications,
        )
        from eneo.database.tables.spaces_table import Spaces

        link = self._spaces_link_table
        link_fk = getattr(link, self._fk_column)
        stmt = (
            select(func.count(Spaces.id))
            .select_from(Spaces)
            .join(link, link.space_id == Spaces.id)
            .join(
                SecurityClassifications,
                SecurityClassifications.id == Spaces.security_classification_id,
                isouter=False,
            )
            .where(
                and_(
                    link_fk == from_model_id,
                    Spaces.tenant_id == tenant_id,
                    SecurityClassifications.security_level > target_level,
                )
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def _count_affected_entities(
        self, from_model_id: UUID, entity_types: list[str], tenant_id: UUID
    ) -> int:
        total_count = 0
        for entity_type in entity_types:
            total_count += await self._count_entities_by_type(
                entity_type, from_model_id, tenant_id
            )
        return total_count

    async def _count_entities_by_type(
        self, entity_type: str, model_id: UUID, tenant_id: UUID
    ) -> int:
        if entity_type == "spaces":
            return await self._count_spaces(model_id, tenant_id)

        if entity_type not in self._entity_table_map:
            self.logger.warning(f"Entity type {entity_type} not in entity table map")
            return 0

        table = self._entity_table_map[entity_type]
        tenant_condition = self._build_tenant_filter_condition(
            table, entity_type, tenant_id
        )
        stmt = (
            select(func.count())
            .select_from(table)
            .where(
                and_(
                    getattr(table, self._fk_column) == model_id,
                    tenant_condition,
                )
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def _count_spaces(self, model_id: UUID, tenant_id: UUID) -> int:
        from eneo.database.tables.spaces_table import Spaces

        link = self._spaces_link_table
        link_fk = getattr(link, self._fk_column)
        stmt = (
            select(func.count(link.space_id))
            .select_from(link)
            .join(Spaces, link.space_id == Spaces.id)
            .where(and_(link_fk == model_id, Spaces.tenant_id == tenant_id))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def _execute_migration_transactionally(
        self,
        from_model_id: UUID,
        to_model_id: UUID,
        entity_types: list[str],
        tenant_id: UUID,
    ) -> dict[str, int]:
        results: dict[str, int] = {}
        async with self.session.begin_nested() as savepoint:
            try:
                for entity_type in entity_types:
                    results[entity_type] = await self._migrate_entity_type(
                        entity_type, from_model_id, to_model_id, tenant_id
                    )
                results["total"] = sum(results.values())

                # `migrated_to_model_id` is a one-way latch. Full migrations
                # usually clear everything in one call; deliberate partial API
                # calls may clear the source over several calls. Latch only when
                # no migratable surface still references the source.
                if not await self._has_remaining_source_references(
                    from_model_id, tenant_id
                ):
                    await self._mark_source_migrated(from_model_id, to_model_id)

                await savepoint.commit()
                return results
            except Exception as e:
                await savepoint.rollback()
                raise e

    def _build_tenant_filter_condition(
        self, table: Any, entity_type: str, tenant_id: UUID
    ) -> ColumnElement[bool]:
        from eneo.database.tables.users_table import Users

        if entity_type in {"apps", "questions"}:
            return table.tenant_id == tenant_id
        elif entity_type in {"assistants", "services"}:
            return table.user_id.in_(
                select(Users.id).where(Users.tenant_id == tenant_id)
            )
        elif entity_type in {"assistant_templates", "app_templates"}:
            # Templates carry their own tenant_id and soft-delete marker. Scope
            # strictly to this tenant and skip soft-deleted rows so a migration
            # never counts or rebinds another tenant's or an already-deleted
            # template. Keep in sync with the usage service's copy.
            return and_(
                table.tenant_id == tenant_id,
                table.deleted_at.is_(None),
            )
        elif entity_type == "spaces":
            return table.tenant_id == tenant_id
        else:
            self.logger.warning(
                f"Unknown entity type for tenant filtering: {entity_type}"
            )
            return true()

    async def _ensure_partial_migrations_keep_same_target(
        self, from_model_id: UUID, to_model_id: UUID, tenant_id: UUID
    ) -> None:
        """Prevent split-target partial migrations for the same source model."""
        stmt = (
            select(self.history_repo.table.to_model_id)
            .where(
                self.history_repo.table.tenant_id == tenant_id,
                self.history_repo.table.from_model_id == from_model_id,
                self.history_repo.table.status == "completed",
                self.history_repo.table.to_model_id != to_model_id,
            )
            .limit(1)
        )
        previous_target = (await self.session.execute(stmt)).scalar_one_or_none()
        if previous_target is not None:
            raise ValidationException(
                "Source model has completed partial migration history to a "
                "different target. Complete remaining references to the original "
                "target before using another target model."
            )

    async def _has_remaining_source_references(
        self, from_model_id: UUID, tenant_id: UUID
    ) -> bool:
        remaining = await self._count_affected_entities(
            from_model_id, list(self._migratable_entity_types), tenant_id
        )
        return remaining > 0

    async def _mark_source_migrated(
        self, from_model_id: UUID, to_model_id: UUID
    ) -> None:
        stmt = (
            update(self._model_table)
            .where(self._model_table.id == from_model_id)
            .values(migrated_to_model_id=to_model_id)
        )
        await self.session.execute(stmt)

    async def _migrate_entity_type(
        self, entity_type: str, from_model_id: UUID, to_model_id: UUID, tenant_id: UUID
    ) -> int:
        if entity_type == "spaces":
            return await self._migrate_spaces(from_model_id, to_model_id, tenant_id)

        if entity_type not in self._entity_table_map:
            self.logger.warning(f"Entity type {entity_type} not in entity table map")
            return 0

        table: Any = self._entity_table_map[entity_type]
        tenant_condition = self._build_tenant_filter_condition(
            table, entity_type, tenant_id
        )

        special = self._special_entity_migrators()
        if entity_type in special:
            return await special[entity_type](
                from_model_id, to_model_id, tenant_id, table, tenant_condition
            )

        stmt = (
            update(table)
            .where(
                and_(
                    getattr(table, self._fk_column) == from_model_id,
                    tenant_condition,
                )
            )
            .values(**{self._fk_column: to_model_id})
        )
        result = await self.session.execute(stmt)
        migrated_count = result.rowcount or 0
        self.logger.info(
            f"Migrated {migrated_count} {entity_type} from {from_model_id} to {to_model_id}"
        )
        return migrated_count

    async def _migrate_spaces(
        self, from_model_id: UUID, to_model_id: UUID, tenant_id: UUID
    ) -> int:
        from sqlalchemy.dialects.postgresql import insert

        from eneo.database.tables.spaces_table import Spaces

        link = self._spaces_link_table
        link_fk_col = self._fk_column
        link_fk = getattr(link, link_fk_col)

        spaces_with_source_stmt = (
            select(link.space_id)
            .select_from(link)
            .join(Spaces, link.space_id == Spaces.id)
            .where(and_(link_fk == from_model_id, Spaces.tenant_id == tenant_id))
        )
        result = await self.session.execute(spaces_with_source_stmt)
        space_ids = [row.space_id for row in result.fetchall()]
        if not space_ids:
            return 0

        for space_id in space_ids:
            insert_stmt = insert(link).values(
                **{"space_id": space_id, link_fk_col: to_model_id}
            )
            insert_stmt = insert_stmt.on_conflict_do_nothing()
            await self.session.execute(insert_stmt)

        delete_stmt = delete(link).where(
            and_(link_fk == from_model_id, link.space_id.in_(space_ids))
        )
        delete_result = await self.session.execute(delete_stmt)
        migrated_count = delete_result.rowcount or 0
        self.logger.info(
            f"Migrated {migrated_count} space associations from {from_model_id} to {to_model_id}"
        )
        return migrated_count
