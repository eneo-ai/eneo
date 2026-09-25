from typing import Annotated

from fastapi import APIRouter, Depends

from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.whats_new.whats_new_models import WhatsNewStatePublic, WhatsNewVersionUpdate

router = APIRouter()


@router.get(
    "/state/",
    response_model=WhatsNewStatePublic,
    description="Get which releases the current user has seen and been told about.",
    responses=responses.get_responses([403]),
)
async def get_whats_new_state(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    return await container.whats_new_service().get_state()


@router.put(
    "/seen/",
    response_model=WhatsNewStatePublic,
    description="Record that the current user has opened the What's new page for a release.",
    responses=responses.get_responses([403]),
)
async def mark_whats_new_seen(
    data: WhatsNewVersionUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    return await container.whats_new_service().mark_seen(data.version)


@router.put(
    "/announced/",
    response_model=WhatsNewStatePublic,
    description="Record that the current user has been shown the announcement for a release.",
    responses=responses.get_responses([403]),
)
async def mark_whats_new_announced(
    data: WhatsNewVersionUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    return await container.whats_new_service().mark_announced(data.version)


@router.delete(
    "/state/",
    response_model=WhatsNewStatePublic,
    description="Development only: forget the current user's What's new markers so the announcement and dot return.",
    responses=responses.get_responses([403, 404]),
)
async def reset_whats_new_state(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    return await container.whats_new_service().reset_state()
