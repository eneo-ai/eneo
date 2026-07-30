from typing import Annotated

from fastapi import APIRouter, Depends

from eneo.limits.limit import Limits
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()
with_user_container = get_container(with_user=True)


@router.get(
    "/",
    response_model=Limits,
    description="Get configured upload and AI Builder input limits.",
    responses=responses.get_responses([]),
)
async def get_limits(container: Annotated[Container, Depends(with_user_container)]):
    service = container.limit_service()
    return await service.get_limits()
