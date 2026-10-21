from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.endpoint_access import Authentication, endpoint_access
from eneo.forecast_models.presentation.forecast_model_models import (
    ForecastModelPublic,
    ForecastModelUpdate,
)
from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse
from eneo.roles.permissions import Permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

ContainerDep = Annotated[Container, Depends(get_container(with_user=True))]

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedResponse[ForecastModelPublic],
    responses=responses.get_responses([403]),
    description="List the tenant's forecast models.",
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def get_forecast_models(container: ContainerDep):
    models = await container.forecast_model_crud_service().get_forecast_models()
    return PaginatedResponse(
        items=[ForecastModelPublic.from_domain(model) for model in models]
    )


@router.post(
    "/{id}/",
    response_model=ForecastModelPublic,
    responses=responses.get_responses([400, 403, 404, 409]),
    description=(
        "Turn a forecast model on or off, set its security classification or "
        "rename it. Fields left out keep their value."
    ),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def update_forecast_model(
    id: UUID, update: ForecastModelUpdate, container: ContainerDep
):
    user = container.user()
    old_model = await container.forecast_model_repo().one(id)

    model = await container.forecast_model_crud_service().update_forecast_model(
        model_id=id,
        is_org_enabled=update.is_org_enabled,
        security_classification=update.security_classification,
        display_name=update.display_name,
    )

    # One API call = one audit entry carrying every changed field.
    changes: dict[str, object] = {}
    if old_model.is_org_enabled != model.is_org_enabled:
        changes["is_org_enabled"] = {
            "old": old_model.is_org_enabled,
            "new": model.is_org_enabled,
        }
    old_sc = old_model.security_classification
    new_sc = model.security_classification
    if (old_sc.id if old_sc else None) != (new_sc.id if new_sc else None):
        changes["security_classification"] = {
            "old": old_sc.name if old_sc else None,
            "new": new_sc.name if new_sc else None,
        }
    if old_model.nickname != model.nickname:
        changes["display_name"] = {"old": old_model.nickname, "new": model.nickname}

    if changes:
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.FORECAST_MODEL_UPDATED,
            entity_type=EntityType.FORECAST_MODEL,
            entity_id=id,
            description=f"Updated settings for forecast model {model.nickname}",
            metadata=AuditMetadata.standard(actor=user, target=model, changes=changes),
        )

    return ForecastModelPublic.from_domain(model)
