# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import Annotated

from fastapi import APIRouter, Depends

from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.storage.presentation.storage_models import StorageInfoModel, StorageModel

router = APIRouter()


@router.get("/", response_model=StorageModel)
async def get_storage(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> StorageModel:
    service = container.storage_service()
    assembler = container.storage_assembler()

    storage_info = await service.get_storage_info()
    model = assembler.from_storage_to_model(storage=storage_info)

    return model


@router.get("/spaces/", response_model=StorageInfoModel)
async def get_spaces(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> StorageInfoModel:
    service = container.storage_service()
    assembler = container.storage_assembler()

    storage_info = await service.get_storage_info()
    model = assembler.from_storage_info_to_model(storage=storage_info)

    return model
