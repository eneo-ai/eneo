from fastapi import APIRouter, Depends, Request

from intric.authentication.auth_dependencies import get_scope_filter
from intric.dashboard.api.dashboard_models import Dashboard
from intric.main.container.container import Container
from intric.server import protocol
from intric.server.dependencies.container import get_container

router = APIRouter()


@router.get("/", response_model=Dashboard)
async def get_dashboard(
    request: Request,
    only_published: bool = False,
    container: Container = Depends(get_container(with_user=True)),
):
    space_service = container.space_service()
    assembler = container.space_assembler()

    spaces = await space_service.get_spaces(
        include_personal=not only_published, include_applications=True
    )
    # Defensive normalization: service can return sparse entries for inaccessible
    # personal/shared spaces; dashboard assembler expects concrete space objects.
    spaces = [space for space in spaces if space is not None]

    # Scope filtering: space-scoped key should only see its scoped space.
    scope_filter = get_scope_filter(request)
    if scope_filter.space_id is not None:
        spaces = [
            space
            for space in spaces
            if space.id == scope_filter.space_id
        ]

    space_models = [
        assembler.from_space_to_dashboard_model(space, only_published=only_published)
        for space in spaces
    ]

    return Dashboard(spaces=protocol.to_paginated_response(space_models))
