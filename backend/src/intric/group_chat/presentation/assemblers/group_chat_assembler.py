# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import TYPE_CHECKING

from intric.files.file_models import FileRestrictions, Limit
from intric.group_chat.presentation.models import (
    GroupChatAssistantPublic,
    GroupChatPublic,
    GroupChatTools,
)

if TYPE_CHECKING:
    from intric.group_chat.domain.entities.group_chat import (
        GroupChat,
        GroupChatAssistant,
    )
    from intric.main.models import ResourcePermission


class GroupChatAssembler:
    @staticmethod
    def _assemble_group_chat_assistant(
        assistant: "GroupChatAssistant",
    ) -> GroupChatAssistantPublic:
        return GroupChatAssistantPublic(
            id=assistant.assistant.id,
            handle=assistant.assistant.name,
            default_description=assistant.assistant.description,
            user_description=assistant.user_description,
        )

    @classmethod
    def _assemble_tools(cls, assistants: list["GroupChatAssistant"]) -> GroupChatTools:
        group_chat_assistants = []
        if len(assistants) > 0:
            group_chat_assistants = [
                cls._assemble_group_chat_assistant(assistant=assistant)
                for assistant in assistants
            ]

        return GroupChatTools(assistants=group_chat_assistants)

    @classmethod
    def from_domain_to_model(
        cls,
        group_chat: "GroupChat",
        permissions: list["ResourcePermission"] = None,
    ) -> GroupChatPublic:
        permissions = permissions or []

        # Create empty FileRestrictions
        empty_allowed_attachments = FileRestrictions(
            accepted_file_types=[], limit=Limit(max_files=0, max_size=0)
        )

        return GroupChatPublic(
            created_at=group_chat.created_at,
            updated_at=group_chat.updated_at,
            name=group_chat.name,
            id=group_chat.id,
            space_id=group_chat.space_id,
            allow_mentions=group_chat.allow_mentions,
            show_response_label=group_chat.show_response_label,
            published=group_chat.published,
            insight_enabled=group_chat.insight_enabled,
            tools=cls._assemble_tools(assistants=group_chat.assistants),
            permissions=permissions,
            attachments=[],  # Hard-coded empty list
            allowed_attachments=empty_allowed_attachments,  # Hard-coded empty restrictions
            type=group_chat.type,
            metadata_json=group_chat.metadata_json,
            icon_id=group_chat.icon_id,
        )

    @classmethod
    def to_paginated_response():
        pass
