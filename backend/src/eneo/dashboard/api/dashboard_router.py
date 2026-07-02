from typing import Annotated

from fastapi import APIRouter, Depends, Request

from eneo.authentication.auth_dependencies import get_scope_filter
from eneo.dashboard.api.dashboard_models import Dashboard
from eneo.main.container.container import Container
from eneo.server import protocol
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()
with_user_container = get_container(with_user=True)


@router.get(
    "/",
    response_model=Dashboard,
    description="Get the current user's dashboard (spaces and published applications).",
    responses=responses.get_responses([]),
)
async def get_dashboard(
    request: Request,
    container: Annotated[Container, Depends(with_user_container)],
    only_published: bool = False,
):
    space_service = container.space_service()
    assembler = container.space_assembler()

    spaces = await space_service.get_spaces(
        include_personal=not only_published, include_applications=True
    )
    # Scope filtering: space-scoped key should only see its scoped space.
    scope_filter = get_scope_filter(request)
    scope_space_id = getattr(scope_filter, "space_id", None)
    if scope_space_id is not None:
        spaces = [space for space in spaces if space.id == scope_space_id]

    space_models = [
        assembler.from_space_to_dashboard_model(space, only_published=only_published)
        for space in spaces
    ]

    return Dashboard(spaces=protocol.to_paginated_response(space_models))
