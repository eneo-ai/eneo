import logging
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional, Any
from uuid import UUID, uuid4

from sqlalchemy import and_, update, select, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from intric.completion_models.constants import ENTITY_TABLE_MAP, ENTITY_TYPES
from intric.completion_models.domain.completion_model_migration_history_repo import (
    CompletionModelMigrationHistoryRepo,
)
from intric.completion_models.application.completion_model_usage_service import (
    CompletionModelUsageService,
)
from intric.completion_models.presentation.completion_model_models import (
    MigrationResult,
    ValidationResult,
)
from intric.events import (
    ModelMigrationStarted,
    ModelMigrationCompleted,
    ModelMigrationFailed,
    get_event_publisher,
)
from intric.main.exceptions import ValidationException
from intric.main.config import get_settings
from intric.roles.permissions import Permission, validate_permissions

if TYPE_CHECKING:
    from intric.completion_models.domain.completion_model_repo import CompletionModelRepository
    from intric.users.user import User


class CompletionModelMigrationService:
    """Service for migrating completion model usage between models."""

    def __init__(
        self,
        session: AsyncSession,
        completion_model_repo: "CompletionModelRepository",
        usage_service: CompletionModelUsageService,
    ):
        self.session = session
        self.completion_model_repo = completion_model_repo
        self.usage_service = usage_service
        self.migration_history_repo = CompletionModelMigrationHistoryRepo(session)
        self.logger = logging.getLogger(__name__)
        self.event_publisher = get_event_publisher()
        self.settings = get_settings()

    async def migrate_model_usage(
        self,
        from_model_id: UUID,
        to_model_id: UUID,
        entity_types: Optional[List[str]] = None,
        user: "User" = None,
        confirm_migration: bool = False,
    ) -> MigrationResult:
        """Execute model migration with full safety checks and observability."""
        start_time = datetime.utcnow()
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
            }
        )
        
        # Validate and normalize entity_types
        if entity_types is not None:
            # Add debugging to catch the "string" issue
            self.logger.debug(f"Raw entity_types received: {entity_types} (type: {type(entity_types)})")
            
            # Handle case where a string is passed instead of a list
            if isinstance(entity_types, str):
                self.logger.warning(f"entity_types is a string instead of list: '{entity_types}'. Converting to list.")
                entity_types = [entity_types]
            
            # Validate entity types
            if not isinstance(entity_types, list):
                raise ValidationException(f"entity_types must be a list of strings, got {type(entity_types)}")
            
            # Check for invalid entity types
            invalid_types = [t for t in entity_types if t not in ENTITY_TYPES and t != "spaces"]
            if invalid_types:
                raise ValidationException(f"Invalid entity types: {invalid_types}. Valid types are: {ENTITY_TYPES + ['spaces']}")
            
            self.logger.debug(f"Validated entity_types: {entity_types}")
        
        final_entity_types = entity_types or ENTITY_TYPES
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
            
            # For single-tenant deployment, we still check if models are enabled for the tenant
            # This is done through CompletionModelSettings
            from intric.database.tables.ai_models_table import CompletionModelSettings
            
            from_settings_stmt = select(CompletionModelSettings).where(
                and_(
                    CompletionModelSettings.completion_model_id == from_model_id,
                    CompletionModelSettings.tenant_id == user.tenant_id,
                    CompletionModelSettings.is_enabled == True
                )
            )
            from_settings = await self.session.execute(from_settings_stmt)
            if not from_settings.scalar_one_or_none():
                raise ValidationException(
                    f"Source model not available: The model '{from_model.name}' is not enabled for your organization. "
                    f"Please contact your administrator to enable this model."
                )
            
            to_settings_stmt = select(CompletionModelSettings).where(
                and_(
                    CompletionModelSettings.completion_model_id == to_model_id,
                    CompletionModelSettings.tenant_id == user.tenant_id,
                    CompletionModelSettings.is_enabled == True
                )
            )
            to_settings = await self.session.execute(to_settings_stmt)
            if not to_settings.scalar_one_or_none():
                raise ValidationException(
                    f"Target model not available: The model '{to_model.name}' is not enabled for your organization. "
                    f"Please contact your administrator to enable this model."
                )
            
            self.logger.info(
                "Model validation successful",
                extra={
                    "from_model": from_model.name,
                    "to_model": to_model.name,
                    "tenant_id": str(user.tenant_id)
                }
            )
            
        except ValidationException:
            # Re-raise validation exceptions with their descriptive messages
            raise
        except Exception as e:
            self.logger.error(
                "Error validating models",
                extra={
                    "from_model_id": str(from_model_id),
                    "to_model_id": str(to_model_id),
                    "error": str(e)
                }
            )
            raise ValidationException(
                f"Model validation failed: Unable to verify model availability. "
                f"Please try again or contact support if the issue persists."
            )
        
        # Count affected entities first for the event
        affected_count = await self._count_affected_entities(
            from_model_id, final_entity_types, user.tenant_id
        )
        
        # Create migration history record with started_at timestamp
        migration_history = await self.migration_history_repo.create_migration_history(
            migration_id=migration_id,
            tenant_id=user.tenant_id,
            from_model_id=from_model_id,
            to_model_id=to_model_id,
            initiated_by=user.id,
            status="in_progress",
            entity_types=entity_types,
            affected_count=affected_count,
            started_at=start_time,
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
                from_model_id, to_model_id
            )
            
            # Only fail if there are compatibility issues AND user hasn't confirmed
            if not validation_result.compatible and not confirm_migration:
                # Update migration history with validation failure
                duration = (datetime.utcnow() - start_time).total_seconds()
                await self.migration_history_repo.update_migration_history(
                    migration_id=migration_id,
                    tenant_id=user.tenant_id,
                    status="failed",
                    migrated_count=0,
                    failed_count=0,
                    duration_seconds=duration,
                    completed_at=datetime.utcnow(),
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
                    }
                )
            
            # Step 2: Execute migration transactionally
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
                        }
                    )
                    
                    # Recalculate within the existing transaction
                    await self.usage_service.recalculate_all_usage_stats_in_transaction(user.tenant_id)
                    auto_recalculated = True
                    
                    self.logger.info(
                        "Auto-recalculation completed successfully",
                        extra={"migration_id": str(migration_id)}
                    )
                    
                except Exception as e:
                    self.logger.error(
                        "Auto-recalculation failed, manual recalculation required",
                        extra={
                            "migration_id": str(migration_id),
                            "error": str(e),
                            "error_type": type(e).__name__,
                        }
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
                    }
                )
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            self.logger.info(
                "Model migration completed successfully",
                extra={
                    "migration_id": str(migration_id),
                    "migrated_count": result["total"],
                    "duration_seconds": duration,
                    "details": result,
                    "auto_recalculated": auto_recalculated,
                    "requires_manual_recalculation": requires_manual_recalculation,
                }
            )
            
            # Update migration history with success
            await self.migration_history_repo.update_migration_history(
                migration_id=migration_id,
                tenant_id=user.tenant_id,
                status="completed",
                migrated_count=result["total"],
                failed_count=0,
                duration_seconds=duration,
                completed_at=datetime.utcnow(),
                warnings=validation_result.warnings if validation_result.warnings else None,
                migration_details=result,
            )
            
            # Publish migration completed event
            await self.event_publisher.publish(
                ModelMigrationCompleted(
                    migration_id=migration_id,
                    migrated_count=result["total"],
                    duration_seconds=duration,
                    timestamp=datetime.utcnow(),
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
                }
            )
            
            # Update migration history with failure
            duration = (datetime.utcnow() - start_time).total_seconds()
            await self.migration_history_repo.update_migration_history(
                migration_id=migration_id,
                tenant_id=user.tenant_id,
                status="failed",
                migrated_count=0,
                failed_count=affected_count,
                duration_seconds=duration,
                completed_at=datetime.utcnow(),
                error_message=str(e),
            )
            
            # Publish migration failed event
            await self.event_publisher.publish(
                ModelMigrationFailed(
                    migration_id=migration_id,
                    error_message=f"Database error: {str(e)}",
                    timestamp=datetime.utcnow(),
                )
            )
            
            raise ValidationException(f"Migration failed due to database error: {str(e)}")
        except Exception as e:
            self.logger.error(
                "Unexpected error during model migration",
                extra={
                    "migration_id": str(migration_id),
                    "error": str(e),
                    "error_type": "unexpected",
                    "from_model_id": str(from_model_id),
                    "to_model_id": str(to_model_id),
                }
            )
            
            # Update migration history with failure
            duration = (datetime.utcnow() - start_time).total_seconds()
            await self.migration_history_repo.update_migration_history(
                migration_id=migration_id,
                tenant_id=user.tenant_id,
                status="failed",
                migrated_count=0,
                failed_count=affected_count,
                duration_seconds=duration,
                completed_at=datetime.utcnow(),
                error_message=str(e),
            )
            
            # Publish migration failed event
            await self.event_publisher.publish(
                ModelMigrationFailed(
                    migration_id=migration_id,
                    error_message=f"Unexpected error: {str(e)}",
                    timestamp=datetime.utcnow(),
                )
            )
            
            raise ValidationException(f"Migration failed: {str(e)}")

    async def _validate_migration_compatibility(
        self, from_model_id: UUID, to_model_id: UUID
    ) -> ValidationResult:
        """Check if models are compatible for migration."""
        from_model = await self.completion_model_repo.one(model_id=from_model_id)
        to_model = await self.completion_model_repo.one(model_id=to_model_id)
        
        issues = []
        
        # Check if target model is deprecated
        if to_model.is_deprecated:
            issues.append("Target model is deprecated")
        
        # Check token limits
        if from_model.token_limit > to_model.token_limit:
            issues.append(f"Target model has lower token limit: {to_model.token_limit}")
        
        # Check model family compatibility
        if from_model.family != to_model.family:
            issues.append(f"Different model families: {from_model.family} → {to_model.family}")
        
        # Check vision support
        if from_model.vision and not to_model.vision:
            issues.append("Target model lacks vision support")
        
        # Check reasoning support
        if from_model.reasoning and not to_model.reasoning:
            issues.append("Target model lacks reasoning support")
        
        return ValidationResult(
            compatible=len(issues) == 0,
            warnings=issues,
            requires_confirmation=len(issues) > 0,
        )

    async def _count_affected_entities(
        self, from_model_id: UUID, entity_types: List[str], tenant_id: UUID
    ) -> int:
        """Count how many entities would be affected by the migration."""
        total_count = 0
        
        for entity_type in entity_types:
            count = await self._count_entities_by_type(entity_type, from_model_id, tenant_id)
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
            self.logger.warning(f"Entity type {entity_type} not found in ENTITY_TABLE_MAP")
            return 0
        
        table = ENTITY_TABLE_MAP[entity_type]
        
        # Build tenant-aware filtering condition
        tenant_condition = self._build_tenant_filter_condition(table, entity_type, tenant_id)
        
        # Build query using SQLAlchemy Core to prevent SQL injection
        stmt = select(func.count()).select_from(table).where(
            and_(
                table.completion_model_id == model_id,
                tenant_condition,
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
        entity_types: List[str],
        tenant_id: UUID,
    ) -> dict:
        """Execute migration with savepoint-based rollback capability."""
        results = {}
        
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
                
                # Commit all changes
                await savepoint.commit()
                
                return results
                
            except Exception as e:
                # Automatic rollback to savepoint
                await savepoint.rollback()
                raise e

    def _build_tenant_filter_condition(self, table: Any, entity_type: str, tenant_id: UUID):
        """Build appropriate tenant filtering condition based on entity type."""
        from intric.database.tables.users_table import Users
        
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
            return True
        elif entity_type == "spaces":
            # Spaces have direct tenant_id field
            return table.tenant_id == tenant_id
        else:
            self.logger.warning(f"Unknown entity type for tenant filtering: {entity_type}")
            return True

    async def _migrate_entity_type(
        self, entity_type: str, from_model_id: UUID, to_model_id: UUID, tenant_id: UUID
    ) -> int:
        """Migrate entities of a specific type from one model to another."""
        self.logger.debug(f"Migrating entity_type={entity_type}, from_model_id={from_model_id}, to_model_id={to_model_id}, tenant_id={tenant_id}")
        
        # Handle spaces separately due to many-to-many relationship
        if entity_type == "spaces":
            return await self._migrate_spaces(from_model_id, to_model_id, tenant_id)
        
        if entity_type not in ENTITY_TABLE_MAP:
            self.logger.warning(f"Entity type {entity_type} not found in ENTITY_TABLE_MAP")
            return 0
        
        table = ENTITY_TABLE_MAP[entity_type]
        
        # Build tenant-aware filtering condition
        tenant_condition = self._build_tenant_filter_condition(table, entity_type, tenant_id)
        
        # Update all entities of this type
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
        
        self.logger.info(f"Migrated {migrated_count} {entity_type} entities from {from_model_id} to {to_model_id}")
        
        return migrated_count

    async def _migrate_spaces(
        self, from_model_id: UUID, to_model_id: UUID, tenant_id: UUID
    ) -> int:
        """Migrate spaces from one model to another in the many-to-many relationship."""
        from intric.database.tables.spaces_table import Spaces, SpacesCompletionModels
        
        self.logger.debug(f"Migrating spaces many-to-many relationship from {from_model_id} to {to_model_id} for tenant {tenant_id}")
        
        # Update the many-to-many relationship table
        # This changes which model is available in each space
        stmt = (
            update(SpacesCompletionModels)
            .where(
                and_(
                    SpacesCompletionModels.completion_model_id == from_model_id,
                    SpacesCompletionModels.space_id.in_(
                        select(Spaces.id).where(Spaces.tenant_id == tenant_id)
                    ),
                )
            )
            .values(completion_model_id=to_model_id)
        )
        
        self.logger.debug(f"Executing spaces migration query: {stmt}")
        
        result = await self.session.execute(stmt)
        migrated_count = result.rowcount or 0
        
        self.logger.info(f"Migrated {migrated_count} space-model associations from {from_model_id} to {to_model_id}")
        
        return migrated_count
