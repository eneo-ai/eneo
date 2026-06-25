import logging
from typing import Annotated, cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query

# Audit logging - module level imports for consistency
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.auth_dependencies import get_current_active_user
from intric.completion_models.presentation.completion_model_models import (
    MigrationResult,
    ModelMigrationHistory,
    ModelMigrationRequest,
    ValidationResult,
)
from intric.database.database import AsyncSession
from intric.database.tables.app_table import Apps
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.users_table import Users
from intric.main.container.container import Container
from intric.main.exceptions import ValidationException
from intric.main.models import PaginatedResponse, is_provided
from intric.roles.permissions import Permission, validate_permission
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.transcription_models.presentation.transcription_model_models import (
    TranscriptionModelPublic,
    TranscriptionModelUpdate,
    TranscriptionModelUsageDetails,
    TranscriptionModelUsageStats,
    TranscriptionUsageEntity,
)
from intric.users.user import UserInDB

CurrentUser = Annotated[UserInDB, Depends(get_current_active_user)]

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedResponse[TranscriptionModelPublic],
    responses=responses.get_responses([403]),
    description="List all transcription models for the tenant.",
)
async def get_transcription_models(
    user: CurrentUser,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    validate_permission(user, Permission.ADMIN)

    service = container.transcription_model_crud_service()

    models = await service.get_transcription_models()

    return PaginatedResponse(
        items=[TranscriptionModelPublic.from_domain(model) for model in models]
    )


@router.post(
    "/{id}/",
    response_model=TranscriptionModelPublic,
    responses=responses.get_responses([403, 404]),
    description="Update org settings for a transcription model.",
)
async def update_transcription_model(
    id: UUID,
    update_flags: TranscriptionModelUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.transcription_model_crud_service()
    user = container.user()

    # Validate admin permissions first
    validate_permission(user, Permission.ADMIN)

    # Get old state for change tracking (bypass access check since admin is already validated)
    transcription_model_repo = container.transcription_model_repo()
    old_model = await transcription_model_repo.one(model_id=id)

    # Update model
    transcription_model = await service.update_transcription_model(
        model_id=id,
        is_org_enabled=update_flags.is_org_enabled,
        is_org_default=update_flags.is_org_default,
        security_classification=update_flags.security_classification,
    )

    # Build consolidated changes dict (one API call = one audit log)
    changes: dict[str, object] = {}

    # Track is_org_enabled changes
    if is_provided(update_flags.is_org_enabled):
        if old_model.is_org_enabled != transcription_model.is_org_enabled:
            changes["is_org_enabled"] = {
                "old": old_model.is_org_enabled,
                "new": transcription_model.is_org_enabled,
            }

    # Track is_org_default changes
    if is_provided(update_flags.is_org_default):
        if old_model.is_org_default != transcription_model.is_org_default:
            changes["is_org_default"] = {
                "old": old_model.is_org_default,
                "new": transcription_model.is_org_default,
            }

    # Track security classification changes
    if is_provided(update_flags.security_classification):
        old_sc_name = (
            old_model.security_classification.name
            if old_model.security_classification
            else None
        )
        new_sc_name = (
            transcription_model.security_classification.name
            if transcription_model.security_classification
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
            action=ActionType.TRANSCRIPTION_MODEL_UPDATED,
            entity_type=EntityType.TRANSCRIPTION_MODEL,
            entity_id=id,
            description=f"Updated settings for {transcription_model.name}",
            metadata=AuditMetadata.standard(
                actor=user,
                target=transcription_model,
                changes=changes,
            ),
        )

    return TranscriptionModelPublic.from_domain(transcription_model)


@router.get(
    "/{model_id}/usage",
    response_model=TranscriptionModelUsageStats,
    responses=responses.get_responses([403, 404]),
    description="Count apps and spaces that would be moved by migrating this model.",
)
async def get_transcription_model_usage(
    model_id: UUID,
    user: CurrentUser,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> TranscriptionModelUsageStats:
    """Live impact counts for the migrate dialog (transcription has no
    pre-aggregated usage-stats table, so these are computed on demand)."""
    validate_permission(user, Permission.ADMIN)
    service = container.transcription_model_migration_service()
    counts = await service.count_affected_per_type(model_id, user.tenant_id)
    return TranscriptionModelUsageStats(
        model_id=model_id,
        apps_count=counts.get("apps", 0),
        spaces_count=counts.get("spaces", 0),
        total_count=counts.get("total", 0),
    )


@router.get(
    "/{model_id}/usage/details",
    response_model=TranscriptionModelUsageDetails,
    responses=responses.get_responses([403, 404]),
    description="List apps using this transcription model (for the migrate dialog).",
)
async def get_transcription_model_usage_details(
    model_id: UUID,
    user: CurrentUser,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    limit: int = Query(100, ge=1, le=500),
) -> TranscriptionModelUsageDetails:
    """Per-entity usage so the migrate dialog can use the same impact table as
    completion. Transcription's only direct reference is apps; spaces are a
    many-to-many shown via the aggregate /usage count."""
    validate_permission(user, Permission.ADMIN)
    session = cast(AsyncSession, container.session())

    where = sa.and_(
        Apps.transcription_model_id == model_id,
        Apps.tenant_id == user.tenant_id,
    )
    rows = (
        await session.execute(
            sa.select(
                Apps.id,
                Apps.name,
                Spaces.name.label("space_name"),
                Users.username.label("owner_name"),
            )
            .select_from(Apps)
            .join(Spaces, Apps.space_id == Spaces.id, isouter=True)
            .join(Users, Apps.user_id == Users.id, isouter=True)
            .where(where)
            .limit(limit)
        )
    ).all()
    total = (
        await session.execute(sa.select(sa.func.count()).select_from(Apps).where(where))
    ).scalar_one()

    items = [
        TranscriptionUsageEntity(
            entity_id=row.id,
            entity_name=row.name,
            entity_type="app",
            space_name=row.space_name,
            owner_name=row.owner_name,
        )
        for row in rows
    ]
    return TranscriptionModelUsageDetails(items=items, total=total)


@router.get(
    "/{model_id}/migration-validate",
    response_model=ValidationResult,
    responses=responses.get_responses([403, 404]),
    description="Validate transcription migration compatibility without executing.",
)
async def validate_transcription_migration(
    model_id: UUID,
    user: CurrentUser,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    to_model_id: UUID = Query(..., description="Target model ID"),
) -> ValidationResult:
    """Validate transcription migration compatibility without executing."""
    validate_permission(user, Permission.ADMIN)
    migration_service = container.transcription_model_migration_service()
    return await migration_service.validate_migration(
        model_id, to_model_id, user.tenant_id
    )


@router.post(
    "/{model_id}/migrate",
    response_model=MigrationResult,
    responses=responses.get_responses([403, 404]),
    description="Migrate all usage from one transcription model to another.",
)
async def migrate_transcription_model_usage(
    model_id: UUID,
    migration_request: ModelMigrationRequest,
    user: CurrentUser,
    container: Annotated[
        Container, Depends(get_container(with_user=True, with_transaction=False))
    ],
) -> MigrationResult:
    """Migrate all usage from one transcription model to another.

    Validity, same-model rejection, tenant ownership and entity-type
    whitelisting all live in the shared migration engine; the router only
    enforces admin permission and writes the audit log on success.
    """
    validate_permission(user, Permission.ADMIN)

    session = cast(AsyncSession, container.session())
    migration_service = container.transcription_model_migration_service()
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
                force_override=migration_request.force_override,
            )
        except ValidationException as exc:
            # The engine records the failure in migration_history before raising;
            # catch inside the transaction so that record commits, then re-raise.
            migration_error = exc

    if migration_error is not None:
        raise migration_error

    assert result is not None

    try:
        async with session.begin():
            audit_service = container.audit_service()
            repo = container.transcription_model_repo()
            from_model = await repo.one(model_id=model_id)
            to_model = await repo.one(model_id=migration_request.to_model_id)
            to_model_label = (
                to_model.name if to_model else str(migration_request.to_model_id)
            )
            await audit_service.log_async(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action=ActionType.TRANSCRIPTION_MODEL_MIGRATED,
                entity_type=EntityType.TRANSCRIPTION_MODEL,
                entity_id=model_id,
                description=(
                    f"Migrated model usage from {from_model.name} to "
                    f"{to_model_label} ({result.migrated_count} entities)"
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
        logger.warning(
            "Failed to create audit log for transcription migration: %s", audit_err
        )

    return result


@router.get(
    "/migration-history",
    response_model=list[ModelMigrationHistory],
    responses=responses.get_responses([400, 403]),
    description="List all transcription migration history for the tenant.",
)
async def get_all_transcription_migration_history(
    user: CurrentUser,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ModelMigrationHistory]:
    """Get all transcription migration history for the tenant."""
    validate_permission(user, Permission.ADMIN)
    service = container.transcription_model_migration_history_service()
    return await service.get_migration_history_for_tenant(user.tenant_id, limit, offset)


@router.get(
    "/migration-history/{migration_id}",
    response_model=ModelMigrationHistory,
    responses=responses.get_responses([403, 404]),
    description="Get a specific transcription migration history record by ID.",
)
async def get_transcription_migration_history_by_id(
    migration_id: UUID,
    user: CurrentUser,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> ModelMigrationHistory:
    """Get a specific transcription migration history record by ID."""
    validate_permission(user, Permission.ADMIN)
    service = container.transcription_model_migration_history_service()
    history = await service.get_migration_history_by_id(migration_id, user.tenant_id)
    if not history:
        raise HTTPException(status_code=404, detail="Migration history not found")
    return history


@router.get(
    "/{model_id}/migration-history",
    response_model=list[ModelMigrationHistory],
    responses=responses.get_responses([403, 404]),
    description="Get migration history for a specific transcription model.",
)
async def get_transcription_model_migration_history(
    model_id: UUID,
    user: CurrentUser,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ModelMigrationHistory]:
    """Get migration history for a specific transcription model (from or to)."""
    validate_permission(user, Permission.ADMIN)
    service = container.transcription_model_migration_history_service()
    return await service.get_migration_history_for_model(
        model_id, user.tenant_id, limit, offset
    )
