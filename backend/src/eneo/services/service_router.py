from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.services.service import (
    RunService,
    ServiceCreatePublic,
    ServiceOutput,
    ServicePublicWithUser,
    ServiceRun,
    ServiceUpdatePublic,
)
from eneo.services.service_factory import get_runner_from_service
from eneo.services.service_protocol import from_domain_service, to_question
from eneo.services.service_runner import ServiceRunner
from eneo.spaces.api.space_models import TransferApplicationRequest

router = APIRouter()


@router.post(
    "/",
    response_model=ServicePublicWithUser,
    responses=responses.get_responses([400, 403, 404]),
    description="Create a service.",
)
async def create_service(
    service_model: ServiceCreatePublic,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Create a service.

    `json_schema` is required if `output_validation` is 'json'.

    Conversely, `json_schema` is not evaluated if `output_format` is not 'json'.

    if `output_format` is omitted, the output will not be formatted."""
    service_service = container.service_service()

    service_in_db = await service_service.create_service(service_model)

    assert service_in_db is not None, "Service must exist after creation"
    return from_domain_service(
        service_in_db, show_pricing=container.user().can_view_model_pricing
    )


@router.get(
    "/",
    response_model=PaginatedResponse[ServicePublicWithUser],
    responses=responses.get_responses([]),
    description="List services, optionally filtered by name.",
)
async def get_services(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    name: str | None = None,
):
    service_service = container.service_service()
    services = await service_service.get_services(name)

    return {
        "count": len(services),
        "items": [
            from_domain_service(
                service, show_pricing=container.user().can_view_model_pricing
            )
            for service in services
            if service is not None
        ],
    }


@router.get(
    "/{id}/",
    response_model=ServicePublicWithUser,
    responses=responses.get_responses([403, 404]),
)
async def get_service(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service_service = container.service_service()

    service, permissions = await service_service.get_service(service_id=id)

    return from_domain_service(
        service=service,
        permissions=permissions,
        show_pricing=container.user().can_view_model_pricing,
    )


@router.post(
    "/{id}/",
    response_model=ServicePublicWithUser,
    responses=responses.get_responses([400, 403, 404]),
    description="Update a service. Omitted fields are not updated.",
)
async def update_service(
    id: UUID,
    service_model: ServiceUpdatePublic,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Omitted fields are not updated"""

    service_service = container.service_service()

    service, permissions = await service_service.update_service(service_model, id)

    assert service is not None, "Service must exist after update"
    return from_domain_service(
        service,
        permissions=permissions,
        show_pricing=container.user().can_view_model_pricing,
    )


@router.delete(
    "/{id}/",
    status_code=204,
    responses=responses.get_responses([403, 404]),
    description="Delete a service.",
)
async def delete_service(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service_service = container.service_service()
    await service_service.delete_service(id)


@router.post(
    "/{id}/run/",
    response_model=ServiceOutput,
    responses=responses.get_responses([400, 403, 404]),
    description="Run a service. The output schema depends on the service's output validation.",
)
async def run_service(
    input: RunService,
    service_runner: Annotated[ServiceRunner, Depends(get_runner_from_service)],
):
    """The schema of the output will be depending on the output validation of the service"""
    output = await service_runner.run(input=input.input, file_ids=input.files)

    return ServiceOutput(output=output.result, files=output.files)


@router.get(
    "/{id}/run/",
    response_model=PaginatedResponse[ServiceRun],
    responses=responses.get_responses([403, 404]),
)
async def get_service_runs(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service_service = container.service_service()
    service, runs = await service_service.get_service_runs(id)

    return {
        "count": len(runs),
        "items": [
            to_question(
                run, service, show_pricing=container.user().can_view_model_pricing
            )
            for run in runs
        ],
    }


@router.post(
    "/{id}/transfer/",
    status_code=204,
    responses=responses.get_responses([400, 403, 404]),
    description="Transfer a service to another space.",
)
async def transfer_service_to_space(
    id: UUID,
    transfer_req: TransferApplicationRequest,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service_service = container.service_service()

    await service_service.move_service_to_space(
        service_id=id,
        space_id=transfer_req.target_space_id,
        move_resources=transfer_req.move_resources,
    )
