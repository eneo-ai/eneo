# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from uuid import UUID

from fastapi import APIRouter, Depends

from intric.group_chat.domain.entities.group_chat import GroupChatAssistantData
from intric.group_chat.presentation.models import GroupChatPublic, GroupChatUpdateSchema
from intric.main.container.container import Container
from intric.main.models import NOT_PROVIDED
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()


@router.patch(
    "/{id}/",
    response_model=GroupChatPublic,
    description="Updates an existing group chat. Omitted fields are not updated",
    status_code=200,
    responses=responses.get_responses([400, 403, 404]),
)
async def update_group_chat(
    id: UUID,
    group_chat_upd: GroupChatUpdateSchema,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.group_chat_service()
    assembler = container.group_chat_assembler()

    assistants = None
    if group_chat_upd.tools is not None:
        # If tools.assistants exists in the request (even as empty list),
        # we'll pass it through to update the assistants
        if group_chat_upd.tools.assistants is not None:
            assistants = [
                GroupChatAssistantData(
                    id=assistant.id,
                    user_description=assistant.user_description,
                )
                for assistant in group_chat_upd.tools.assistants
            ]

    # Handle icon_id: check if it was provided in the request
    request_dict = group_chat_upd.model_dump(exclude_unset=True)
    icon_id = NOT_PROVIDED
    if "icon_id" in request_dict:
        icon_id = group_chat_upd.icon_id

    # Omitted fields not updated
    updated_group_chat = await service.update_group_chat(
        id=id,
        name=group_chat_upd.name,
        current_assistants=assistants,
        allow_mentions=group_chat_upd.allow_mentions,
        show_response_label=group_chat_upd.show_response_label,
        insight_enabled=group_chat_upd.insight_enabled,
        metadata_json=group_chat_upd.metadata_json,
        icon_id=icon_id,
    )
    return assembler.from_domain_to_model(
        group_chat=updated_group_chat, permissions=updated_group_chat.permissions
    )


@router.get(
    "/{id}/",
    response_model=GroupChatPublic,
    description="""Get an existing group chat by its ID.""",
    status_code=200,
    responses=responses.get_responses([404]),
)
async def get_group_chat(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.group_chat_service()
    assembler = container.group_chat_assembler()

    group_chat = await service.get_group_chat(group_chat_id=id)

    return assembler.from_domain_to_model(
        group_chat=group_chat, permissions=group_chat.permissions
    )


@router.delete(
    "/{id}/",
    description=""" Delete an existing group chat by its ID.""",
    status_code=204,
    responses=responses.get_responses([403, 404]),
)
async def delete_group_chat(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.group_chat_service()

    await service.delete_group_chat(group_chat_id=id)


@router.post(
    "/{id}/publish/",
    response_model=GroupChatPublic,
    responses=responses.get_responses([403, 404]),
)
async def publish_group_chat(
    id: UUID,
    published: bool,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.group_chat_service()
    assembler = container.group_chat_assembler()

    group_chat = await service.publish_group_chat(group_chat_id=id, publish=published)

    return assembler.from_domain_to_model(
        group_chat=group_chat, permissions=group_chat.permissions
    )
