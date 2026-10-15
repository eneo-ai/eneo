from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import get_current_active_user
from eneo.authentication.endpoint_access import Authentication, endpoint_access
from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse, is_provided
from eneo.rerank_models.presentation.rerank_model_models import (
    RerankModelPublic,
    RerankModelUpdate,
)
from eneo.roles.permissions import Permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.users.user import UserInDB

CurrentUser = Annotated[UserInDB, Depends(get_current_active_user)]

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedResponse[RerankModelPublic],
    responses=responses.get_responses([403]),
    description="List all rerank models for the tenant.",
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def get_rerank_models(
    user: CurrentUser,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.rerank_model_crud_service()
    models = await service.get_rerank_models()

    return PaginatedResponse(
        items=[RerankModelPublic.from_domain(model) for model in models]
    )


@router.post(
    "/{id}/",
    response_model=RerankModelPublic,
    responses=responses.get_responses([403, 404]),
    description="Update org settings for a rerank model.",
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def update_rerank_model(
    id: UUID,
    update_flags: RerankModelUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.rerank_model_crud_service()
    user = container.user()

    old_model = await container.rerank_model_repo().one(model_id=id)

    rerank_model = await service.update_rerank_model(
        model_id=id,
        is_org_enabled=update_flags.is_org_enabled,
        is_org_default=update_flags.is_org_default,
        security_classification=update_flags.security_classification,
    )

    # One API call = one audit entry carrying every changed field.
    changes: dict[str, object] = {}
    if is_provided(update_flags.is_org_enabled):
        if old_model.is_org_enabled != rerank_model.is_org_enabled:
            changes["is_org_enabled"] = {
                "old": old_model.is_org_enabled,
                "new": rerank_model.is_org_enabled,
            }
    if is_provided(update_flags.is_org_default):
        if old_model.is_org_default != rerank_model.is_org_default:
            changes["is_org_default"] = {
                "old": old_model.is_org_default,
                "new": rerank_model.is_org_default,
            }
    if is_provided(update_flags.security_classification):
        old_sc_name = (
            old_model.security_classification.name
            if old_model.security_classification
            else None
        )
        new_sc_name = (
            rerank_model.security_classification.name
            if rerank_model.security_classification
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
            action=ActionType.RERANK_MODEL_UPDATED,
            entity_type=EntityType.RERANK_MODEL,
            entity_id=id,
            description=f"Updated settings for {rerank_model.name}",
            metadata=AuditMetadata.standard(
                actor=user,
                target=rerank_model,
                changes=changes,
            ),
        )

    return RerankModelPublic.from_domain(rerank_model)
