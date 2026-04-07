# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from intric.main.container.container import Container
from intric.prompts.api.prompt_models import PromptPublic, PromptUpdateRequest
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()

_ContainerWithUser = Annotated[Container, Depends(get_container(with_user=True))]


@router.get(
    "/{id}/",
    response_model=PromptPublic,
    responses=responses.get_responses([400, 403, 404]),
)
async def get_prompt(id: UUID, container: _ContainerWithUser):
    service = container.prompt_service()
    assembler = container.prompt_assembler()

    prompt = await service.get_prompt(id)
    return assembler.from_prompt_to_model(prompt)


@router.patch(
    "/{id}/",
    response_model=PromptPublic,
    responses=responses.get_responses([400, 403, 404]),
)
async def update_prompt_description(
    id: UUID,
    prompt: PromptUpdateRequest,
    container: _ContainerWithUser,
):
    service = container.prompt_service()
    assembler = container.prompt_assembler()

    updated = await service.update_prompt_description(
        id=id, description=prompt.description
    )
    return assembler.from_prompt_to_model(updated)


@router.delete(
    "/{id}/",
    status_code=204,
    responses=responses.get_responses([403, 404]),
)
async def delete_prompt(
    id: UUID,
    container: _ContainerWithUser,
):
    service = container.prompt_service()

    await service.delete_prompt(id=id)
