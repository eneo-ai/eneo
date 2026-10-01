# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import Annotated

from fastapi import APIRouter, Depends

from eneo.authentication.endpoint_access import Authentication, endpoint_access
from eneo.main.container.container import Container
from eneo.roles.permissions import Permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.storage.presentation.storage_models import StorageInfoModel, StorageModel

router = APIRouter()


@router.get(
    "/",
    response_model=StorageModel,
    description="Get aggregated storage usage for the tenant.",
    responses=responses.get_responses([403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def get_storage(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> StorageModel:
    service = container.storage_service()
    assembler = container.storage_assembler()

    storage_info = await service.get_storage_info()
    model = assembler.from_storage_to_model(storage=storage_info)

    return model


@router.get(
    "/spaces/",
    response_model=StorageInfoModel,
    description="Get per-space storage usage breakdown for the tenant.",
    responses=responses.get_responses([403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="This operation requires Permission.ADMIN before accessing tenant resources.",
)
async def get_spaces(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> StorageInfoModel:
    service = container.storage_service()
    assembler = container.storage_assembler()

    storage_info = await service.get_storage_info()
    model = assembler.from_storage_info_to_model(storage=storage_info)

    return model
