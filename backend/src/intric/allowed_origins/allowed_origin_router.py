from typing import Annotated

from fastapi import APIRouter, Depends

from intric.allowed_origins.allowed_origin_models import AllowedOriginPublic
from intric.main.container.container import Container
from intric.main.models import PaginatedResponse
from intric.server import protocol
from intric.server.dependencies.container import get_container

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[AllowedOriginPublic])
async def get_origins(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.allowed_origin_service()

    allowed_origins = await service.get()

    return protocol.to_paginated_response(allowed_origins)
