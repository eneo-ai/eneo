# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Annotated

from fastapi import APIRouter, Depends

from intric.main.container.container import Container
from intric.personal_chat_policy.domain.personal_chat_policy import (
    PolicyCompletionModel,
)
from intric.personal_chat_policy.presentation.personal_chat_policy_models import (
    PersonalChatPolicyPublic,
    PersonalChatPolicyUpdate,
)
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()

_ContainerWithUser = Annotated[Container, Depends(get_container(with_user=True))]


@router.get(
    "/",
    response_model=PersonalChatPolicyPublic,
    responses=responses.get_responses([403]),
)
async def get_personal_chat_policy(container: _ContainerWithUser):
    service = container.personal_chat_policy_service()
    assembler = container.personal_chat_policy_assembler()
    policy = await service.get_policy()
    return assembler.to_public(policy)


@router.put(
    "/",
    response_model=PersonalChatPolicyPublic,
    responses=responses.get_responses([400, 403]),
)
async def update_personal_chat_policy(
    payload: PersonalChatPolicyUpdate,
    container: _ContainerWithUser,
):
    service = container.personal_chat_policy_service()
    assembler = container.personal_chat_policy_assembler()

    models_restriction = None
    if payload.models_restriction is not None:
        models_restriction = (
            payload.models_restriction.enabled,
            [
                PolicyCompletionModel(
                    completion_model_id=m.completion_model_id,
                    is_default=m.is_default,
                )
                for m in payload.models_restriction.models
            ],
        )

    mcp_restriction = None
    if payload.mcp_restriction is not None:
        mcp_restriction = (
            payload.mcp_restriction.enabled,
            list(payload.mcp_restriction.server_ids),
        )

    prompt_enforcement = None
    if payload.prompt_enforcement is not None:
        prompt_enforcement = (
            payload.prompt_enforcement.enabled,
            payload.prompt_enforcement.prompt_library_id,
        )

    policy = await service.update_policy(
        models_restriction=models_restriction,
        mcp_restriction=mcp_restriction,
        prompt_enforcement=prompt_enforcement,
    )
    return assembler.to_public(policy)
