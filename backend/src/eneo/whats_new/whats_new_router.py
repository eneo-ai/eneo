from typing import Annotated

from fastapi import APIRouter, Depends

from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.whats_new.whats_new_models import WhatsNewSeenPublic, WhatsNewSeenUpdate

router = APIRouter()


@router.get(
    "/seen/",
    response_model=WhatsNewSeenPublic,
    description="Get the newest release the current user has opened on the What's new page.",
    responses=responses.get_responses([403]),
)
async def get_whats_new_seen(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    return await container.whats_new_service().get_seen()


@router.put(
    "/seen/",
    response_model=WhatsNewSeenPublic,
    description="Record that the current user has opened the What's new page for a release.",
    responses=responses.get_responses([403]),
)
async def mark_whats_new_seen(
    data: WhatsNewSeenUpdate,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    return await container.whats_new_service().mark_seen(data.version)
