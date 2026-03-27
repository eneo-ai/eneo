# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.


from fastapi import APIRouter, Depends

from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.storage.presentation.storage_models import StorageInfoModel, StorageModel

router = APIRouter()


@router.get("/", response_model=StorageModel)
async def get_storage(container: Container = Depends(get_container(with_user=True))):
    service = container.storage_service()
    assembler = container.storage_assembler()

    storage_info = await service.get_storage_info()
    model = assembler.from_storage_to_model(storage=storage_info)

    return model


@router.get("/spaces/", response_model=StorageInfoModel)
async def get_spaces(container: Container = Depends(get_container(with_user=True))):
    service = container.storage_service()
    assembler = container.storage_assembler()

    storage_info = await service.get_storage_info()
    model = assembler.from_storage_info_to_model(storage=storage_info)

    return model
