from typing import Annotated

from fastapi import APIRouter, Depends

from eneo.allowed_origins.allowed_origin_models import AllowedOriginPublic
from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse
from eneo.server import protocol
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedResponse[AllowedOriginPublic],
    description="List the tenant's allowed CORS origins.",
    responses=responses.get_responses([403]),
)
async def get_origins(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.allowed_origin_service()

    allowed_origins = await service.get()

    return protocol.to_paginated_response(allowed_origins)
