from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

# Audit logging - module level imports for consistency
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import get_current_active_user
from eneo.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelPublic,
    EmbeddingModelUpdate,
)
from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse, is_provided
from eneo.roles.permissions import Permission, validate_permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.users.user import UserInDB

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedResponse[EmbeddingModelPublic],
    description="List all embedding models for the tenant.",
    responses=responses.get_responses([403]),
)
async def get_embedding_models(
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    validate_permission(user, Permission.ADMIN)

    service = container.embedding_model_crud_service()
    models = await service.get_embedding_models()

    return PaginatedResponse(
        items=[EmbeddingModelPublic.from_domain(model) for model in models]
    )


@router.get(
    "/{id}/",
    response_model=EmbeddingModelPublic,
    responses=responses.get_responses([403, 404]),
)
async def get_embedding_model(
    id: UUID,
    user: Annotated[UserInDB, Depends(get_current_active_user)],
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    validate_permission(user, Permission.ADMIN)

    service = container.embedding_model_crud_service()
    model = await service.get_embedding_model(model_id=id)

    return EmbeddingModelPublic.from_domain(model)


@router.post(
    "/{id}/",
    response_model=EmbeddingModelPublic,
    description="Update an embedding model's settings.",
    responses=responses.get_responses([403, 404]),
)
async def update_embedding_model(
    id: UUID,
    update: EmbeddingModelUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
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
    changes: dict[str, object] = {}

    # Track is_org_enabled changes
    if is_provided(update.is_org_enabled):
        if old_model.is_org_enabled != model.is_org_enabled:
            changes["is_org_enabled"] = {
                "old": old_model.is_org_enabled,
                "new": model.is_org_enabled,
            }

    # Track security classification changes
    if is_provided(update.security_classification):
        old_sc_name = (
            old_model.security_classification.name
            if old_model.security_classification
            else None
        )
        new_sc_name = (
            model.security_classification.name
            if model.security_classification
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
