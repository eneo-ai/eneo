from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import get_current_active_user
from eneo.image_models.presentation.image_model_models import (
    ImageModelPublic,
    ImageModelUpdate,
)
from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse, is_provided
from eneo.roles.permissions import Permission, validate_permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.users.user import UserInDB

CurrentUser = Annotated[UserInDB, Depends(get_current_active_user)]

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedResponse[ImageModelPublic],
    responses=responses.get_responses([403]),
    description="List all image models for the tenant.",
)
async def get_image_models(
    user: CurrentUser,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    validate_permission(user, Permission.ADMIN)

    service = container.image_model_crud_service()
    models = await service.get_image_models()

    return PaginatedResponse(
        items=[ImageModelPublic.from_domain(model) for model in models]
    )


@router.post(
    "/{id}/",
    response_model=ImageModelPublic,
    responses=responses.get_responses([403, 404]),
    description="Update org settings for an image model.",
)
async def update_image_model(
    id: UUID,
    update_flags: ImageModelUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.image_model_crud_service()
    user = container.user()

    validate_permission(user, Permission.ADMIN)

    old_model = await container.image_model_repo().one(model_id=id)

    image_model = await service.update_image_model(
        model_id=id,
        is_org_enabled=update_flags.is_org_enabled,
        is_org_default=update_flags.is_org_default,
        security_classification=update_flags.security_classification,
    )

    # One API call = one audit entry carrying every changed field.
    changes: dict[str, object] = {}
    if is_provided(update_flags.is_org_enabled):
        if old_model.is_org_enabled != image_model.is_org_enabled:
            changes["is_org_enabled"] = {
                "old": old_model.is_org_enabled,
                "new": image_model.is_org_enabled,
            }
    if is_provided(update_flags.is_org_default):
        if old_model.is_org_default != image_model.is_org_default:
            changes["is_org_default"] = {
                "old": old_model.is_org_default,
                "new": image_model.is_org_default,
            }
    if is_provided(update_flags.security_classification):
        old_sc_name = (
            old_model.security_classification.name
            if old_model.security_classification
            else None
        )
        new_sc_name = (
            image_model.security_classification.name
            if image_model.security_classification
            else None
        )
        if old_sc_name != new_sc_name:
            changes["security_classification"] = {
                "old": old_sc_name,
                "new": new_sc_name,
            }

    if changes:
        audit_service = container.audit_service()
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.IMAGE_MODEL_UPDATED,
            entity_type=EntityType.IMAGE_MODEL,
            entity_id=id,
            description=f"Updated settings for {image_model.name}",
            metadata=AuditMetadata.standard(
                actor=user,
                target=image_model,
                changes=changes,
            ),
        )

    return ImageModelPublic.from_domain(image_model)
