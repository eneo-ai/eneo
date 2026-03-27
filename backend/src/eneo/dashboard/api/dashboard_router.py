from fastapi import APIRouter, Depends

from eneo.dashboard.api.dashboard_models import Dashboard
from eneo.main.container.container import Container
from eneo.server import protocol
from eneo.server.dependencies.container import get_container

router = APIRouter()


@router.get("/", response_model=Dashboard)
async def get_dashboard(
    only_published: bool = False,
    container: Container = Depends(get_container(with_user=True)),
):
    space_service = container.space_service()
    assembler = container.space_assembler()

    spaces = await space_service.get_spaces(
        include_personal=not only_published, include_applications=True
    )

    space_models = [
        assembler.from_space_to_dashboard_model(space, only_published=only_published)
        for space in spaces
    ]

    return Dashboard(spaces=protocol.to_paginated_response(space_models))
