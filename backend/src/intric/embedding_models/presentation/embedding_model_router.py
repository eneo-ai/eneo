from uuid import UUID

from fastapi import APIRouter, Depends

from intric.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelPublic,
    EmbeddingModelUpdate,
)
from intric.main.container.container import Container
from intric.main.models import NOT_PROVIDED, PaginatedResponse
from intric.roles.permissions import Permission, validate_permission
from intric.authentication.auth_dependencies import get_current_active_user
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.users.user import UserInDB

# Audit logging - module level imports for consistency
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[EmbeddingModelPublic])
async def get_embedding_models(
    user: UserInDB = Depends(get_current_active_user),
    container: Container = Depends(get_container(with_user=True)),
):
    validate_permission(user, Permission.ADMIN)

    service = container.embedding_model_crud_service()
    models = await service.get_embedding_models()

    return PaginatedResponse(items=[EmbeddingModelPublic.from_domain(model) for model in models])


@router.get(
    "/{id}/",
    response_model=EmbeddingModelPublic,
    responses=responses.get_responses([404]),
)
async def get_embedding_model(
    id: UUID,
    user: UserInDB = Depends(get_current_active_user),
    container: Container = Depends(get_container(with_user=True)),
):
    validate_permission(user, Permission.ADMIN)

    service = container.embedding_model_crud_service()
    model = await service.get_embedding_model(model_id=id)

    return EmbeddingModelPublic.from_domain(model)


@router.post(
    "/{id}/",
    response_model=EmbeddingModelPublic,
    responses=responses.get_responses([404]),
)
async def update_embedding_model(
    id: UUID,
    update: EmbeddingModelUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.embedding_model_crud_service()
    user = container.user()

    # Validate admin permissions first
    validate_permission(user, Permission.ADMIN)

    # Get old state for change tracking (bypass access check since admin is already validated)
    embedding_model_repo = container.embedding_model_repo2()
    old_model = await embedding_model_repo.one(model_id=id)

    # Update model
    model = await service.update_embedding_model(
        model_id=id,
        is_org_enabled=update.is_org_enabled,
        security_classification=update.security_classification,
    )

    # Build consolidated changes dict (one API call = one audit log)
    changes = {}

    # Track is_org_enabled changes
    if update.is_org_enabled is not NOT_PROVIDED:
        if old_model.is_org_enabled != model.is_org_enabled:
            changes["is_org_enabled"] = {
                "old": old_model.is_org_enabled,
                "new": model.is_org_enabled,
            }

    # Track security classification changes
    if update.security_classification is not NOT_PROVIDED:
        old_sc_name = old_model.security_classification.name if old_model.security_classification else None
        new_sc_name = model.security_classification.name if model.security_classification else None
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
            actor_id=user.id,
            action=ActionType.EMBEDDING_MODEL_UPDATED,
            entity_type=EntityType.EMBEDDING_MODEL,
            entity_id=id,
            description=f"Updated settings for {model.name}",
            metadata=AuditMetadata.standard(
                actor=user,
                target=model,
                changes=changes,
            ),
        )

    return EmbeddingModelPublic.from_domain(model)
