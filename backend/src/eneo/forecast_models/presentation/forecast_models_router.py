from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

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
    # One call = one audit entry with every changed field, written by the
    # service from the row it locked.
    model = await container.forecast_model_crud_service().update_forecast_model(
        model_id=id,
        is_org_enabled=update.is_org_enabled,
        security_classification=update.security_classification,
        display_name=update.display_name,
    )
    return ForecastModelPublic.from_domain(model)
