import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, select, true, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from intric.completion_models.application.completion_model_usage_service import (
    CompletionModelUsageService,
)
from intric.completion_models.constants import (
    ENTITY_TABLE_MAP,
    MIGRATABLE_ENTITY_TYPES,
    singular_entity_type,
)
from intric.completion_models.domain.completion_model_migration_history_repo import (
    CompletionModelMigrationHistoryRepo,
)
from intric.completion_models.presentation.completion_model_models import (
    MigrationResult,
    ValidationResult,
)
from intric.events import (
    ModelMigrationCompleted,
    ModelMigrationFailed,
    ModelMigrationStarted,
    get_event_publisher,
)
from intric.main.config import get_settings
from intric.main.exceptions import ValidationException

if TYPE_CHECKING:
    from intric.completion_models.domain.completion_model_repo import (
        CompletionModelRepository,
    )
    from intric.users.user import UserInDB


class CompletionModelMigrationService:
    """Service for migrating completion model usage between models."""

    def __init__(
        self,
        session: AsyncSession,
        completion_model_repo: "CompletionModelRepository",
        usage_service: CompletionModelUsageService,
    ):
        super().__init__()
        self.session = session
        self.completion_model_repo = completion_model_repo
        self.usage_service = usage_service
        self.migration_history_repo = CompletionModelMigrationHistoryRepo(session)
        self.logger = logging.getLogger(__name__)
        self.event_publisher = get_event_publisher()
        self.settings = get_settings()

    async def validate_migration(
        self,
        from_model_id: UUID,
        to_model_id: UUID,
        tenant_id: UUID,
    ) -> ValidationResult:
        """Validate migration compatibility without executing. Used for preflight checks."""
        return await self._validate_migration_compatibility(
            from_model_id, to_model_id, tenant_id
        )

    async def migrate_model_usage(
        self,
        from_model_id: UUID,
        to_model_id: UUID,
        entity_types: list[str] | str | None = None,
        *,
        user: "UserInDB",
        confirm_migration: bool = False,
    ) -> MigrationResult:
        """Execute model migration with full safety checks and observability."""
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
            },
        )

        normalized_entity_types: list[str] | None
        if isinstance(entity_types, str):
            normalized_entity_types = [entity_types]
        else:
            normalized_entity_types = entity_types

        # Validate and normalize entity_types
        if normalized_entity_types is not None:
            # Check for invalid entity types
            invalid_types = [
                t for t in normalized_entity_types if t not in MIGRATABLE_ENTITY_TYPES
            ]
            if invalid_types:
                raise ValidationException(
                    f"Invalid entity types: {invalid_types}. Valid types are: {MIGRATABLE_ENTITY_TYPES}"
                )

            self.logger.debug(f"Validated entity_types: {normalized_entity_types}")

        final_entity_types: list[str] = normalized_entity_types or list(
            MIGRATABLE_ENTITY_TYPES
        )
        # Coupling note: if "assistants" is in final_entity_types but "spaces"
        # is not, _migrate_assistants_with_kwargs enables the target on the
        # spaces those assistants live on (so the new model can run) but the
        # source model is *not* removed from SpacesCompletionModels. Front-
        # filters on `migrated_to_model_id` hide it from the space-settings
        # picker, so the dangling row is cosmetic rather than functional —
        # cleanup-worker removes it when the source model is hard-deleted.
        # API callers that want a clean SpacesCompletionModels state should
        # include "spaces" in entity_types (the frontend passes undefined,
        # which expands to all MIGRATABLE_ENTITY_TYPES, so this is satisfied
        # by default).
        self.logger.debug(f"Final entity_types for migration: {final_entity_types}")

        # Validate models exist and belong to tenant
        try:
            from_model = await self.completion_model_repo.one(model_id=from_model_id)
            if not from_model:
                raise ValidationException(
                    f"Source model not found: The completion model with ID '{from_model_id}' does not exist. "
                    f"Please verify the model ID and try again."
                )

            to_model = await self.completion_model_repo.one(model_id=to_model_id)
            if not to_model:
                raise ValidationException(
                    f"Target model not found: The completion model with ID '{to_model_id}' does not exist. "
                    f"Please verify the model ID and try again."
                )

            # Check if models are the same
            if from_model_id == to_model_id:
                raise ValidationException(
                    f"Invalid migration: Source and target models are the same ('{from_model.name}'). "
                    f"Migration requires different source and target models."
                )

            self._ensure_source_model_not_already_migrated(from_model)

            # For single-tenant deployment, check if models are enabled for the tenant
            # Settings are now stored directly on the model table
            from intric.database.tables.ai_models_table import CompletionModels

            from_model_stmt = select(CompletionModels).where(
                and_(
                    CompletionModels.id == from_model_id,
                    CompletionModels.tenant_id == user.tenant_id,
                    CompletionModels.is_enabled == True,
                )
            )
            from_model_result = await self.session.execute(from_model_stmt)
            if not from_model_result.scalar_one_or_none():
                raise ValidationException(
                    f"Source model not available: The model '{from_model.name}' is not enabled for your organization. "
                    f"Please contact your administrator to enable this model."
                )

            to_model_stmt = select(CompletionModels).where(
                and_(
                    CompletionModels.id == to_model_id,
                    CompletionModels.tenant_id == user.tenant_id,
                    CompletionModels.is_enabled == True,
                )
            )
            to_model_result = await self.session.execute(to_model_stmt)
            if not to_model_result.scalar_one_or_none():
                raise ValidationException(
                    f"Target model not available: The model '{to_model.name}' is not enabled for your organization. "
                    f"Please contact your administrator to enable this model."
                )

            self.logger.info(
                "Model validation passed",
                extra={
                    "from_model": from_model.name,
                    "to_model": to_model.name,
                    "tenant_id": str(user.tenant_id),
                },
            )

        except ValidationException as ve:
            # WARNING (not INFO): a rejected migration is an admin action
            # the system blocked — operators alarm on this level.
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
                "Model validation failed: Unable to verify model availability. "
                "Please try again or contact support if the issue persists."
            )

        # Count affected entities first for the event
        affected_count = await self._count_affected_entities(
            from_model_id, final_entity_types, user.tenant_id
        )
        self.logger.info(
            f"Affected entities counted: {affected_count}",
            extra={"migration_id": str(migration_id), "affected_count": affected_count},
        )

        # Create migration history record with started_at timestamp
        await self.migration_history_repo.create_migration_history(
            migration_id=migration_id,
            tenant_id=user.tenant_id,
            from_model_id=from_model_id,
            to_model_id=to_model_id,
            from_model_name=from_model.name,
            to_model_name=to_model.name,
            from_provider_type=from_model.provider_type,
            to_provider_type=to_model.provider_type,
            initiated_by=user.id,
            status="in_progress",
            entity_types=normalized_entity_types,
            affected_count=affected_count,
            started_at=start_time,
        )
        self.logger.info(
            f"Migration history record created (migration_id={migration_id})",
        )

        # Publish migration started event
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

        # Step 1: Validation
        try:
            validation_result = await self._validate_migration_compatibility(
                from_model_id, to_model_id, user.tenant_id
            )
            self.logger.info(
                f"Migration compatibility check: compatible={validation_result.compatible}, "
                f"warnings={validation_result.warnings}, confirm_migration={confirm_migration}",
                extra={"migration_id": str(migration_id)},
            )

            # Security blockers cannot be overridden with confirm_migration
            has_blockers = any(
                w.startswith("security_classification_insufficient")
                for w in validation_result.warning_codes
            )

            if has_blockers:
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                await self.migration_history_repo.update_migration_history(
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

            # Other compatibility issues can be overridden with confirm_migration
            if not validation_result.compatible and not confirm_migration:
                # Update migration history with validation failure
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                await self.migration_history_repo.update_migration_history(
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

            # Log warnings if user confirmed despite compatibility issues
            if not validation_result.compatible and confirm_migration:
                self.logger.warning(
                    f"User confirmed migration despite compatibility issues: {', '.join(validation_result.warnings)}",
                    extra={
                        "migration_id": str(migration_id),
                        "from_model_id": str(from_model_id),
                        "to_model_id": str(to_model_id),
                        "warnings": validation_result.warnings,
                    },
                )

            # Step 2: Execute migration transactionally
            self.logger.info(
                f"Executing migration for entity_types={final_entity_types}",
                extra={"migration_id": str(migration_id)},
            )
            result = await self._execute_migration_transactionally(
                from_model_id, to_model_id, final_entity_types, user.tenant_id
            )

            # Step 3: Auto-recalculate usage statistics if within threshold
            auto_recalculated = False
            requires_manual_recalculation = False

            migrated_count = result["total"]
            threshold = self.settings.migration_auto_recalc_threshold

            if migrated_count <= threshold:
                try:
                    self.logger.info(
                        f"Auto-recalculating usage stats for migration (count: {migrated_count} <= threshold: {threshold})",
                        extra={
                            "migration_id": str(migration_id),
                            "migrated_count": migrated_count,
                            "threshold": threshold,
                        },
                    )

                    # Recalculate within the existing transaction
                    await self.usage_service.recalculate_all_usage_stats_in_transaction(
                        user.tenant_id
                    )
                    auto_recalculated = True

                    self.logger.info(
                        "Auto-recalculation completed successfully",
                        extra={"migration_id": str(migration_id)},
                    )

                except Exception as e:
                    self.logger.error(
                        "Auto-recalculation failed, manual recalculation required",
                        extra={
                            "migration_id": str(migration_id),
                            "error": str(e),
                            "error_type": type(e).__name__,
                        },
                    )
                    # Don't fail the migration if recalculation fails
                    requires_manual_recalculation = True
            else:
                requires_manual_recalculation = True
                self.logger.info(
                    f"Migration count exceeds threshold, manual recalculation required (count: {migrated_count} > threshold: {threshold})",
                    extra={
                        "migration_id": str(migration_id),
                        "migrated_count": migrated_count,
                        "threshold": threshold,
                    },
                )

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()

            self.logger.info(
                f"Migration completed: migrated_count={result['total']}, "
                f"duration={duration:.2f}s, details={result}",
                extra={
                    "migration_id": str(migration_id),
                    "migrated_count": result["total"],
                    "duration_seconds": duration,
                    "details": result,
                    "auto_recalculated": auto_recalculated,
                    "requires_manual_recalculation": requires_manual_recalculation,
                },
            )

            # Update migration history with success
            await self.migration_history_repo.update_migration_history(
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

            # Publish migration completed event
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
            # Re-raise validation errors as they are already handled above
            raise
        except SQLAlchemyError as e:
            self.logger.error(
                "Database error during model migration",
                extra={
                    "migration_id": str(migration_id),
                    "error": str(e),
                    "error_type": "database",
                    "from_model_id": str(from_model_id),
                    "to_model_id": str(to_model_id),
                },
            )

            # Update migration history with failure.
            #
            # KNOWN EDGE CASE: at "true" DB failures (deadlock, connection
            # loss) the outer transaction is already aborted in PG's view, so
            # the SELECT inside update_migration_history will itself fail
            # with InFailedSqlTransactionError and the row never lands.
            # Validation / app-level SQLAlchemyError paths still persist
            # correctly because their session is reusable. A proper fix
            # would route this write through a separate session, but that
            # requires reworking DI to expose a sessionmaker here; left as
            # a follow-up so we don't risk new bugs in the happy path.
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            await self.migration_history_repo.update_migration_history(
                migration_id=migration_id,
                tenant_id=user.tenant_id,
                status="failed",
                migrated_count=0,
                failed_count=affected_count,
                duration_seconds=duration,
                completed_at=datetime.now(timezone.utc),
                error_message=str(e),
            )

            # Publish migration failed event
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
                extra={
                    "migration_id": str(migration_id),
                    "error": str(e),
                    "error_type": "unexpected",
                    "from_model_id": str(from_model_id),
                    "to_model_id": str(to_model_id),
                },
            )

            # Update migration history with failure
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            await self.migration_history_repo.update_migration_history(
                migration_id=migration_id,
                tenant_id=user.tenant_id,
                status="failed",
                migrated_count=0,
                failed_count=affected_count,
                duration_seconds=duration,
                completed_at=datetime.now(timezone.utc),
                error_message=str(e),
            )

            # Publish migration failed event
            await self.event_publisher.publish(
                ModelMigrationFailed(
                    migration_id=migration_id,
                    error_message=f"Unexpected error: {str(e)}",
                    timestamp=datetime.now(timezone.utc),
                )
            )

            raise ValidationException(f"Migration failed: {str(e)}")

    @staticmethod
    def _ensure_source_model_not_already_migrated(from_model: Any) -> None:
        if getattr(from_model, "migrated_to_model_id", None) is not None:
            raise ValidationException(
                f"Source model '{from_model.name}' has already been migrated. "
                f"A model can only be migrated once."
            )

    async def _validate_migration_compatibility(
        self, from_model_id: UUID, to_model_id: UUID, tenant_id: UUID
    ) -> ValidationResult:
        """Check if models are compatible for migration."""
        from_model = await self.completion_model_repo.one(model_id=from_model_id)
        to_model = await self.completion_model_repo.one(model_id=to_model_id)
        self._ensure_source_model_not_already_migrated(from_model)

        issues: list[str] = []  # Human-readable
        issue_codes: list[str] = []  # Machine-readable
        blockers: list[str] = []
        blocker_codes: list[str] = []

        # Check if target model is deprecated
        if to_model.is_effectively_deprecated:
            issues.append("Target model is deprecated")
            issue_codes.append("target_deprecated")

        # Check token limits
        if from_model.max_input_tokens > to_model.max_input_tokens:
            issues.append(
                f"Target model has lower input token limit: {to_model.max_input_tokens}"
            )
            issue_codes.append(f"lower_token_limit:{to_model.max_input_tokens}")

        # Check model family compatibility
        if from_model.family != to_model.family:
            issues.append(
                f"Different model families: {from_model.family} → {to_model.family}"
            )
            issue_codes.append(
                f"different_family:{from_model.family}:{to_model.family}"
            )

        # Check vision support
        if from_model.vision and not to_model.vision:
            issues.append("Target model lacks vision support")
            issue_codes.append("lacks_vision")

        # Check reasoning support
        if from_model.reasoning and not to_model.reasoning:
            issues.append("Target model lacks reasoning support")
            issue_codes.append("lacks_reasoning")

        # Check tool calling support
        if from_model.supports_tool_calling and not to_model.supports_tool_calling:
            issues.append("Target model lacks tool calling support")
            issue_codes.append("lacks_tool_calling")

        # Security classification check — this is a blocker, not a warning
        insufficient_spaces = await self._check_security_classification_compatibility(
            from_model_id, to_model, tenant_id
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

        # Kwargs reset is informational, not a compatibility issue
        info_warnings = [
            "Assistant model parameters (kwargs) will be reset to defaults"
        ]
        info_codes = ["kwargs_reset"]

        # Blockers prevent migration entirely (confirm cannot override)
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

    async def _check_security_classification_compatibility(
        self, from_model_id: UUID, to_model: Any, tenant_id: UUID
    ) -> int:
        """Count spaces where target model doesn't meet the security classification requirement."""
        from intric.database.tables.security_classifications_table import (
            SecurityClassification as SecurityClassifications,
        )
        from intric.database.tables.spaces_table import Spaces, SpacesCompletionModels

        # Get target model's security level (0 if no classification)
        target_level = (
            to_model.security_classification.security_level
            if to_model.security_classification
            else 0
        )

        # Find spaces that have the source model AND a security classification
        # higher than the target model's level
        stmt = (
            select(func.count(Spaces.id))
            .select_from(Spaces)
            .join(SpacesCompletionModels, SpacesCompletionModels.space_id == Spaces.id)
            .join(
                SecurityClassifications,
                SecurityClassifications.id == Spaces.security_classification_id,
                isouter=False,
            )
            .where(
                and_(
                    SpacesCompletionModels.completion_model_id == from_model_id,
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
        """Count how many entities would be affected by the migration."""
        total_count = 0

        for entity_type in entity_types:
            count = await self._count_entities_by_type(
                entity_type, from_model_id, tenant_id
            )
            total_count += count

        return total_count

    async def _count_entities_by_type(
        self, entity_type: str, model_id: UUID, tenant_id: UUID
    ) -> int:
        """Count entities of a specific type using the model."""
        # Handle spaces separately due to many-to-many relationship
        if entity_type == "spaces":
            return await self._count_spaces(model_id, tenant_id)

        if entity_type not in ENTITY_TABLE_MAP:
            self.logger.warning(
                f"Entity type {entity_type} not found in ENTITY_TABLE_MAP"
            )
            return 0

        table = ENTITY_TABLE_MAP[entity_type]

        # Build tenant-aware filtering condition
        tenant_condition = self._build_tenant_filter_condition(
            table, entity_type, tenant_id
        )

        # Build query using SQLAlchemy Core to prevent SQL injection
        stmt = (
            select(func.count())
            .select_from(table)
            .where(
                and_(
                    table.completion_model_id == model_id,
                    tenant_condition,
                )
            )
        )

        result = await self.session.execute(stmt)

        return result.scalar_one()

    async def _count_spaces(self, model_id: UUID, tenant_id: UUID) -> int:
        """Count spaces that have access to a specific model."""
        from intric.database.tables.spaces_table import Spaces, SpacesCompletionModels

        stmt = (
            select(func.count(SpacesCompletionModels.space_id))
            .select_from(SpacesCompletionModels)
            .join(Spaces, SpacesCompletionModels.space_id == Spaces.id)
            .where(
                and_(
                    SpacesCompletionModels.completion_model_id == model_id,
                    Spaces.tenant_id == tenant_id,
                )
            )
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
        """Execute migration with savepoint-based rollback capability."""
        results: dict[str, int] = {}

        async with self.session.begin_nested() as savepoint:  # Savepoint for rollback
            try:
                # Migrate each entity type
                for entity_type in entity_types:
                    count = await self._migrate_entity_type(
                        entity_type, from_model_id, to_model_id, tenant_id
                    )
                    results[entity_type] = count

                # Calculate total
                results["total"] = sum(results.values())

                # Mark source model as migrated (stays in DB for historical
                # question references and token usage analytics)
                from intric.database.tables.ai_models_table import CompletionModels

                mark_stmt = (
                    update(CompletionModels)
                    .where(CompletionModels.id == from_model_id)
                    .values(migrated_to_model_id=to_model_id)
                )
                await self.session.execute(mark_stmt)

                self.logger.info(
                    f"Marked source model {from_model_id} as migrated to {to_model_id}"
                )

                # Commit all changes
                await savepoint.commit()

                return results

            except Exception as e:
                # Automatic rollback to savepoint
                await savepoint.rollback()
                raise e

    def _build_tenant_filter_condition(
        self, table: Any, entity_type: str, tenant_id: UUID
    ) -> ColumnElement[bool]:
        """Build appropriate tenant filtering condition based on entity type."""
        from intric.database.tables.users_table import Users

        entity_type = singular_entity_type(entity_type)

        if entity_type in {"app", "question"}:
            # Direct tenant_id field
            return table.tenant_id == tenant_id
        elif entity_type in {"assistant", "service"}:
            # Via user relationship - need to join with Users table
            return table.user_id.in_(
                select(Users.id).where(Users.tenant_id == tenant_id)
            )
        elif entity_type in {"assistant_template", "app_template"}:
            # Global entities - no tenant filtering needed
            return true()
        elif entity_type == "spaces":
            # Spaces have direct tenant_id field
            return table.tenant_id == tenant_id
        else:
            self.logger.warning(
                f"Unknown entity type for tenant filtering: {entity_type}"
            )
            return true()

    async def _migrate_entity_type(
        self, entity_type: str, from_model_id: UUID, to_model_id: UUID, tenant_id: UUID
    ) -> int:
        """Migrate entities of a specific type from one model to another."""
        self.logger.debug(
            f"Migrating entity_type={entity_type}, from_model_id={from_model_id}, to_model_id={to_model_id}, tenant_id={tenant_id}"
        )

        # Handle spaces separately due to many-to-many relationship
        if entity_type == "spaces":
            return await self._migrate_spaces(from_model_id, to_model_id, tenant_id)

        if entity_type not in ENTITY_TABLE_MAP:
            self.logger.warning(
                f"Entity type {entity_type} not found in ENTITY_TABLE_MAP"
            )
            return 0

        table: Any = ENTITY_TABLE_MAP[entity_type]

        # Build tenant-aware filtering condition
        tenant_condition = self._build_tenant_filter_condition(
            table, entity_type, tenant_id
        )

        # For assistants, we need to handle completion_model_kwargs specially
        if entity_type == "assistants":
            return await self._migrate_assistants_with_kwargs(
                from_model_id, to_model_id, tenant_id, table, tenant_condition
            )

        # Update all entities of this type (non-assistant entities)
        stmt = (
            update(table)
            .where(
                and_(
                    table.completion_model_id == from_model_id,
                    tenant_condition,
                )
            )
            .values(completion_model_id=to_model_id)
        )

        self.logger.debug(f"Executing migration query for {entity_type}: {stmt}")

        result = await self.session.execute(stmt)
        migrated_count = result.rowcount or 0

        self.logger.info(
            f"Migrated {migrated_count} {entity_type} entities from {from_model_id} to {to_model_id}"
        )

        return migrated_count

    async def _migrate_assistants_with_kwargs(
        self,
        from_model_id: UUID,
        to_model_id: UUID,
        tenant_id: UUID,
        table: Any,
        tenant_condition: ColumnElement[bool],
    ) -> int:
        """Migrate assistants and handle their completion_model_kwargs properly."""
        self.logger.debug(
            f"Migrating assistants with kwargs handling from {from_model_id} to {to_model_id} for tenant {tenant_id}"
        )

        # First, enable the target model on spaces where the source model is enabled
        await self._ensure_target_model_enabled_on_spaces(
            from_model_id, to_model_id, tenant_id
        )

        # Update assistants: change model and reset kwargs to avoid incompatibility
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
                completion_model_kwargs={},  # Reset kwargs to avoid parameter incompatibilities
            )
        )

        self.logger.debug(
            f"Executing assistant migration query with kwargs reset: {stmt}"
        )

        result = await self.session.execute(stmt)
        migrated_count = result.rowcount or 0

        self.logger.info(
            f"Migrated {migrated_count} assistants from {from_model_id} to {to_model_id}, kwargs reset to avoid incompatibilities"
        )

        return migrated_count

    async def _ensure_target_model_enabled_on_spaces(
        self, from_model_id: UUID, to_model_id: UUID, tenant_id: UUID
    ) -> None:
        """Enable target model on spaces where source model is enabled."""
        from sqlalchemy.dialects.postgresql import insert

        from intric.database.tables.spaces_table import Spaces, SpacesCompletionModels

        self.logger.debug(
            f"Ensuring target model {to_model_id} is enabled on spaces where source model {from_model_id} is enabled for tenant {tenant_id}"
        )

        # Find all spaces in the tenant that have the source model enabled
        spaces_with_source_model_stmt = (
            select(SpacesCompletionModels.space_id)
            .select_from(SpacesCompletionModels)
            .join(Spaces, SpacesCompletionModels.space_id == Spaces.id)
            .where(
                and_(
                    SpacesCompletionModels.completion_model_id == from_model_id,
                    Spaces.tenant_id == tenant_id,
                )
            )
        )

        result = await self.session.execute(spaces_with_source_model_stmt)
        space_ids = [row.space_id for row in result.fetchall()]

        if not space_ids:
            self.logger.debug(
                f"No spaces found with source model {from_model_id} enabled for tenant {tenant_id}"
            )
            return

        self.logger.info(
            f"Found {len(space_ids)} spaces with source model {from_model_id} enabled: {space_ids}, enabling target model {to_model_id}"
        )

        # Enable target model on all those spaces (using INSERT ... ON CONFLICT DO NOTHING to avoid duplicates)
        for space_id in space_ids:
            insert_stmt = insert(SpacesCompletionModels).values(
                space_id=space_id, completion_model_id=to_model_id
            )
            # Use ON CONFLICT DO NOTHING to handle cases where target model is already enabled
            insert_stmt = insert_stmt.on_conflict_do_nothing()

            await self.session.execute(insert_stmt)

        self.logger.info(
            f"Successfully enabled target model {to_model_id} on {len(space_ids)} spaces {space_ids} for tenant {tenant_id}"
        )

    async def _migrate_spaces(
        self, from_model_id: UUID, to_model_id: UUID, tenant_id: UUID
    ) -> int:
        """Migrate spaces from one model to another in the many-to-many relationship."""
        from sqlalchemy.dialects.postgresql import insert

        from intric.database.tables.spaces_table import Spaces, SpacesCompletionModels

        self.logger.debug(
            f"Migrating spaces many-to-many relationship from {from_model_id} to {to_model_id} for tenant {tenant_id}"
        )

        # First, find all spaces in the tenant that have the source model enabled
        spaces_with_source_model_stmt = (
            select(SpacesCompletionModels.space_id)
            .select_from(SpacesCompletionModels)
            .join(Spaces, SpacesCompletionModels.space_id == Spaces.id)
            .where(
                and_(
                    SpacesCompletionModels.completion_model_id == from_model_id,
                    Spaces.tenant_id == tenant_id,
                )
            )
        )

        result = await self.session.execute(spaces_with_source_model_stmt)
        space_ids = [row.space_id for row in result.fetchall()]

        if not space_ids:
            self.logger.debug(
                f"No spaces found with source model {from_model_id} enabled for tenant {tenant_id}"
            )
            return 0

        self.logger.info(
            f"Found {len(space_ids)} spaces with source model {from_model_id}: {space_ids}"
        )

        # Step 1: Ensure target model is enabled on all these spaces (INSERT with ON CONFLICT DO NOTHING)
        for space_id in space_ids:
            insert_stmt = insert(SpacesCompletionModels).values(
                space_id=space_id, completion_model_id=to_model_id
            )
            insert_stmt = insert_stmt.on_conflict_do_nothing()
            await self.session.execute(insert_stmt)

        self.logger.info(
            f"Enabled target model {to_model_id} on {len(space_ids)} spaces: {space_ids}"
        )

        # Step 2: Remove the old model relationships
        delete_stmt = delete(SpacesCompletionModels).where(
            and_(
                SpacesCompletionModels.completion_model_id == from_model_id,
                SpacesCompletionModels.space_id.in_(space_ids),
            )
        )

        self.logger.info(
            f"Removing old relationships for source model {from_model_id} on spaces: {space_ids}"
        )
        delete_result = await self.session.execute(delete_stmt)
        migrated_count = delete_result.rowcount or 0

        self.logger.info(
            f"Migrated {migrated_count} space-model associations from {from_model_id} to {to_model_id} (removed old relationships)"
        )

        return migrated_count
