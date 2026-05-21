# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from intric.main.container.container import Container
from intric.main.models import PaginatedResponse
from intric.prompt_library.presentation.prompt_library_models import (
    PromptLibraryEntryCreate,
    PromptLibraryEntryPublic,
    PromptLibraryEntrySparse,
    PromptLibraryEntryUpdate,
)
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()

_ContainerWithUser = Annotated[Container, Depends(get_container(with_user=True))]


@router.get(
    "/",
    response_model=PaginatedResponse[PromptLibraryEntrySparse],
    responses=responses.get_responses([403]),
)
async def list_prompt_library_entries(container: _ContainerWithUser):
    service = container.prompt_library_service()
    entries = await service.list_entries()
    return PaginatedResponse(
        items=[
            container.prompt_library_assembler().to_sparse(entry) for entry in entries
        ]
    )


@router.post(
    "/",
    response_model=PromptLibraryEntryPublic,
    responses=responses.get_responses([400, 403]),
    status_code=201,
)
async def create_prompt_library_entry(
    payload: PromptLibraryEntryCreate,
    container: _ContainerWithUser,
):
    service = container.prompt_library_service()
    entry = await service.create_entry(
        name=payload.name,
        description=payload.description,
        text=payload.text,
    )
    return container.prompt_library_assembler().to_public(entry)


@router.get(
    "/{id}/",
    response_model=PromptLibraryEntryPublic,
    responses=responses.get_responses([403, 404]),
)
async def get_prompt_library_entry(id: UUID, container: _ContainerWithUser):
    service = container.prompt_library_service()
    entry = await service.get_entry(id)
    return container.prompt_library_assembler().to_public(entry)


@router.put(
    "/{id}/",
    response_model=PromptLibraryEntryPublic,
    responses=responses.get_responses([400, 403, 404]),
)
async def update_prompt_library_entry(
    id: UUID,
    payload: PromptLibraryEntryUpdate,
    container: _ContainerWithUser,
):
    service = container.prompt_library_service()
    entry = await service.update_entry(
        id,
        name=payload.name,
        description=payload.description,
        text=payload.text,
    )
    return container.prompt_library_assembler().to_public(entry)


@router.delete(
    "/{id}/",
    status_code=204,
    responses=responses.get_responses([403, 404, 409]),
)
async def delete_prompt_library_entry(id: UUID, container: _ContainerWithUser):
    service = container.prompt_library_service()
    await service.delete_entry(id)
