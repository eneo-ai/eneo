# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Union

from intric.base.base_entity import Entity
from intric.main.models import NOT_PROVIDED, NotProvided

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from intric.assistants.assistant import Assistant


# maybe over engineered
@dataclass
class GroupChatAssistantData:
    id: "UUID"
    user_description: Optional[str] = None


class GroupChatAssistant:
    def __init__(
        self,
        assistant: "Assistant",
        user_description: Optional[str] = None,
    ):
        self.assistant = assistant
        self.user_description = user_description

    def update(self, user_description: Optional[str] = None):
        # Allow explicitly setting to None to clear the description
        self.user_description = user_description
        return self


class GroupChat(Entity):
    def __init__(
        self,
        id: Optional["UUID"],
        created_at: Optional["datetime"],
        updated_at: Optional["datetime"],
        user_id: "UUID",
        space_id: "UUID",
        name: str,
        assistants: list[GroupChatAssistant],
        allow_mentions: bool,
        show_response_label: bool,
        published: bool,
        insight_enabled: bool = False,
        metadata_json: Optional[dict] = None,
        icon_id: Optional["UUID"] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.user_id = user_id
        self.space_id = space_id
        self.name = name
        self.assistants = assistants
        self.allow_mentions = allow_mentions
        self.show_response_label = show_response_label
        self.published = published
        self.insight_enabled = insight_enabled
        self.type = "group-chat"
        self._metadata_json = metadata_json
        self.icon_id = icon_id

    @classmethod
    def create(
        cls,
        name: str,
        space_id: "UUID",
        user_id: "UUID",
    ) -> "GroupChat":
        return cls(
            id=None,
            created_at=None,
            updated_at=None,
            user_id=user_id,
            space_id=space_id,
            name=name,
            assistants=[],
            allow_mentions=False,
            show_response_label=False,
            published=False,
        )

    @property
    def metadata_json(self) -> Optional[dict]:
        return self._metadata_json

    @metadata_json.setter
    def metadata_json(self, metadata_json: Optional[dict]):
        self._metadata_json = metadata_json

    @property
    def assistant_ids(self) -> list["UUID"]:
        assistant_ids = []
        for group_chat_assistant in self.assistants:
            assistant_ids.append(group_chat_assistant.assistant.id)
        return assistant_ids

    def get_assistant_by_id(self, assistant_id: "UUID") -> Optional[GroupChatAssistant]:
        """Get an assistant in this group chat by ID"""
        return next((a for a in self.assistants if a.assistant.id == assistant_id), None)

    def get_assistants(self):
        return [assistant.assistant for assistant in self.assistants]

    def update(
        self,
        name: Optional[str] = None,
        allow_mentions: Optional[bool] = None,
        show_response_label: Optional[bool] = None,
        published: Optional[bool] = None,
        new_assistants: Optional[list[GroupChatAssistant]] = None,
        insight_enabled: Optional[bool] = None,
        metadata_json: Union[dict, None, NotProvided] = NOT_PROVIDED,
        icon_id: Union["UUID", None, NotProvided] = NOT_PROVIDED,
    ):
        if name is not None:
            self.name = name
        if allow_mentions is not None:
            self.allow_mentions = allow_mentions
        if show_response_label is not None:
            self.show_response_label = show_response_label
        if published is not None:
            self.published = published
        if new_assistants is not None:
            self.assistants = new_assistants
        if insight_enabled is not None:
            self.insight_enabled = insight_enabled
        if metadata_json is not NOT_PROVIDED:
            self.metadata_json = metadata_json
        if icon_id is not NOT_PROVIDED:
            self.icon_id = icon_id

        return self
