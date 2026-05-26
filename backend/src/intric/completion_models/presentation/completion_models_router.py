# MIT License

import logging
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

# Audit logging - module level imports for consistency
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.auth_dependencies import get_current_active_user
from intric.completion_models.presentation import (
    CompletionModelPublic,
    CompletionModelUpdateFlags,
)
from intric.completion_models.presentation.completion_model_models import (
    MigrationResult,
    ModelMigrationHistory,
    ModelMigrationRequest,
    ModelUsageStatistics,
    ModelUsageSummary,
    ValidationResult,
)
from intric.completion_models.presentation.completion_model_models import (
    PaginatedResponse as ModelUsagePaginatedResponse,
)
from intric.database.database import AsyncSession
from intric.main.container.container import Container
from intric.main.exceptions import ValidationException
from intric.main.models import PaginatedResponse, is_provided
from intric.roles.permissions import Permission, validate_permission
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.users.user import UserInDB

router = APIRouter()
logger = logging.getLogger(__name__)


class ModelUsageDetailsQuery(BaseModel):
    entity_type: str | None = None
    cursor: str | None = None
    limit: int = 50


class PaginationQuery(BaseModel):
    limit: int = 50
    offset: int = 0


def get_model_usage_details_query(request: Request) -> ModelUsageDetailsQuery:
    params = request.query_params
    return ModelUsageDetailsQuery(
        entity_type=params.get("entity_type") or None,
        cursor=params.get("cursor") or None,
        limit=int(params.get("limit", 50)),
    )


def get_pagination_query(request: Request) -> PaginationQuery:
    params = request.query_params
    return PaginationQuery(
        limit=int(params.get("limit", 50)),
        offset=int(params.get("offset", 0)),
    )


@router.get(
    "/",
    response_model=PaginatedResponse[CompletionModelPublic],
)
async def get_completion_models(
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    validate_permission(user, Permission.ADMIN)

    service = container.completion_model_crud_service()
    assembler = container.completion_model_assembler()

    models = await service.get_completion_models()

    return assembler.from_completion_models_to_models(models)


@router.post(
    "/{id}/",
    response_model=CompletionModelPublic,
    responses=responses.get_responses([404]),
)
async def update_completion_model(
    id: UUID,
    update_flags: CompletionModelUpdateFlags,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.completion_model_crud_service()
    assembler = container.completion_model_assembler()
    user = container.user()

    # Validate admin permissions first
    validate_permission(user, Permission.ADMIN)

    # Get old state for change tracking (bypass access check since admin is already validated)
    completion_model_repo = container.completion_model_repo2()
    old_model = await completion_model_repo.one(model_id=id)

    # Update model
    completion_model = await service.update_completion_model(
        model_id=id,
        is_org_enabled=update_flags.is_org_enabled,
        is_org_default=update_flags.is_org_default,
        security_classification=update_flags.security_classification,
    )

    # Build consolidated changes dict (one API call = one audit log)
    changes: dict[str, object] = {}

    # Track is_org_enabled changes
    if is_provided(update_flags.is_org_enabled):
        if old_model.is_org_enabled != completion_model.is_org_enabled:
            changes["is_org_enabled"] = {
                "old": old_model.is_org_enabled,
                "new": completion_model.is_org_enabled,
            }

    # Track is_org_default changes
    if is_provided(update_flags.is_org_default):
        if old_model.is_org_default != completion_model.is_org_default:
            changes["is_org_default"] = {
                "old": old_model.is_org_default,
                "new": completion_model.is_org_default,
            }

    # Track security classification changes
    if is_provided(update_flags.security_classification):
        old_sc_name = (
            old_model.security_classification.name
            if old_model.security_classification
            else None
        )
        new_sc_name = (
            completion_model.security_classification.name
            if completion_model.security_classification
            else None
        )
        if old_sc_name != new_sc_name:
            changes["security_classification"] = {
                "old": old_sc_name,
                "new": new_sc_name,
            }

    # Only log if there were actual changes (ONE entry with all changes)
    if changes:
        audit_service = container.audit_service()
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.COMPLETION_MODEL_UPDATED,
            entity_type=EntityType.COMPLETION_MODEL,
            entity_id=id,
            description=f"Updated settings for {completion_model.name}",
            metadata=AuditMetadata.standard(
                actor=user,
                target=completion_model,
                changes=changes,
            ),
        )

    return assembler.from_completion_model_to_model(completion_model=completion_model)


@router.get(
    "/{model_id}/usage",
    response_model=ModelUsageStatistics,
    responses=responses.get_responses([404]),
)
async def get_model_usage(
    model_id: UUID,
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> ModelUsageStatistics:
    """Get usage statistics for a specific model (pre-aggregated for performance)"""
    validate_permission(user, Permission.ADMIN)
    service = container.completion_model_usage_service()
    return await service.get_model_usage_statistics(model_id, user.tenant_id)


@router.get(
    "/{model_id}/usage/details",
    response_model=ModelUsagePaginatedResponse,
    responses=responses.get_responses([404]),
)
async def get_model_usage_details(
    model_id: UUID,
    query: Annotated[ModelUsageDetailsQuery, Depends(get_model_usage_details_query)],
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> ModelUsagePaginatedResponse | None:
    """Get detailed list of entities using this model with cursor pagination."""
    validate_permission(user, Permission.ADMIN)
    service = container.completion_model_usage_service()
    return await service.get_model_usage_details(
        model_id, user.tenant_id, query.entity_type, query.cursor, query.limit
    )


@router.get(
    "/{model_id}/migration-validate",
    response_model=ValidationResult,
    responses=responses.get_responses([400, 404]),
)
async def validate_migration(
    model_id: UUID,
    to_model_id: UUID = Query(..., description="Target model ID"),
    user: UserInDB = Depends(get_current_active_user),
    container: Container = Depends(get_container(with_user=True)),
) -> ValidationResult:
    """Validate migration compatibility without executing. Used for preflight checks."""
    validate_permission(user, Permission.ADMIN)
    migration_service = container.completion_model_migration_service()
    return await migration_service.validate_migration(
        from_model_id=model_id,
        to_model_id=to_model_id,
        tenant_id=user.tenant_id,
    )


@router.post(
    "/{model_id}/migrate",
    response_model=MigrationResult,
    responses=responses.get_responses([400, 403, 404]),
)
async def migrate_model_usage(
    model_id: UUID,
    migration_request: ModelMigrationRequest,
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    container: Annotated[
        Container, Depends(get_container(with_user=True, with_transaction=False))
    ],
) -> MigrationResult:
    """Migrate all usage from one model to another.

    Source/target validity, same-model rejection, tenant ownership and
    entity-type whitelisting all live in
    `CompletionModelMigrationService.migrate_model_usage` — the router
    only enforces admin permission and persists the audit log on success.
    """
    validate_permission(user, Permission.ADMIN)

    session = cast(AsyncSession, container.session())
    migration_service = container.completion_model_migration_service()
    migration_error: ValidationException | None = None
    result: MigrationResult | None = None

    async with session.begin():
        try:
            result = await migration_service.migrate_model_usage(
                from_model_id=model_id,
                to_model_id=migration_request.to_model_id,
                entity_types=migration_request.entity_types,
                user=user,
                confirm_migration=migration_request.confirm_migration,
            )
        except ValidationException as exc:
            # The service records validation/security/database failures in
            # migration_history before raising. Catch inside the transaction so
            # that failure record commits, then re-raise after the block exits.
            migration_error = exc

    if migration_error is not None:
        raise migration_error

    assert result is not None

    # Audit happens after the service returns so it captures the actual
    # migrated/failed counts. A failed audit must not break the user-facing
    # response — the migration already committed.
    try:
        async with session.begin():
            audit_service = container.audit_service()
            completion_model_repo = container.completion_model_repo2()
            from_model = await completion_model_repo.one(model_id=model_id)
            to_model = await completion_model_repo.one(
                model_id=migration_request.to_model_id
            )
            to_model_label = (
                to_model.name if to_model else str(migration_request.to_model_id)
            )
            await audit_service.log_async(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action=ActionType.COMPLETION_MODEL_MIGRATED,
                entity_type=EntityType.COMPLETION_MODEL,
                entity_id=model_id,
                description=(
                    f"Migrated model usage from {from_model.name} to "
                    f"{to_model_label} "
                    f"({result.migrated_count} entities)"
                ),
                metadata=AuditMetadata.standard(
                    actor=user,
                    target=from_model,
                    changes={
                        "from_model_id": str(model_id),
                        "to_model_id": str(migration_request.to_model_id),
                        "migrated_count": result.migrated_count,
                        "failed_count": result.failed_count,
                        "duration": result.duration,
                        "details": result.details,
                        "warnings": result.warnings,
                    },
                ),
            )
    except Exception as audit_err:
        logger.warning("Failed to create audit log for migration: %s", audit_err)

    return result


@router.get(
    "/usage-summary",
    response_model=list[ModelUsageSummary],
)
async def get_all_models_usage_summary(
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> list[ModelUsageSummary]:
    """Get usage summary for all models (optimized with pre-aggregation)."""
    validate_permission(user, Permission.ADMIN)
    service = container.completion_model_usage_service()
    return await service.get_all_models_usage_summary(user.tenant_id)


@router.get(
    "/{model_id}/migration-history",
    response_model=list[ModelMigrationHistory],
    responses=responses.get_responses([404]),
)
async def get_model_migration_history(
    model_id: UUID,
    query: Annotated[PaginationQuery, Depends(get_pagination_query)],
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> list[ModelMigrationHistory]:
    """Get migration history for a specific live model (from or to this model)"""
    validate_permission(user, Permission.ADMIN)
    service = container.completion_model_migration_history_service()
    return await service.get_migration_history_for_model(
        model_id, user.tenant_id, query.limit, query.offset
    )


@router.get(
    "/migration-history",
    response_model=list[ModelMigrationHistory],
)
async def get_all_migration_history(
    query: Annotated[PaginationQuery, Depends(get_pagination_query)],
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> list[ModelMigrationHistory]:
    """Get all migration history for the tenant"""
    validate_permission(user, Permission.ADMIN)
    service = container.completion_model_migration_history_service()
    return await service.get_migration_history_for_tenant(
        user.tenant_id, query.limit, query.offset
    )


@router.get(
    "/migration-history/{migration_id}",
    response_model=ModelMigrationHistory,
    responses=responses.get_responses([404]),
)
async def get_migration_history_by_id(
    migration_id: UUID,
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> ModelMigrationHistory:
    """Get a specific migration history record by ID"""
    validate_permission(user, Permission.ADMIN)
    service = container.completion_model_migration_history_service()
    history = await service.get_migration_history_by_id(migration_id, user.tenant_id)

    if not history:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Migration history not found")

    return history
