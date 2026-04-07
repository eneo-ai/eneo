# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from datetime import datetime
from typing import Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from intric.files.file_models import FilePublic, FileRestrictions
from intric.main.models import (
    NOT_PROVIDED,
    NotProvided,
    ResourcePermission,
    ResourcePermissionsMixin,
)
from intric.questions.question import (
    ToolAssistant,
)  # NOTE: Do I want to import this or should it be a class here?


# Input models
class GroupChatCreate(BaseModel):
    """
    Attributes:
        name: str
    """

    name: str


class GroupChatAssistantUpdateSchema(BaseModel):
    id: UUID
    user_description: Optional[str] = Field(  # type: ignore[call-overload]
        description=(
            "Custom description provided by the user. "
            "Cannot be null if 'description' of assistant is null."
        ),
        example="My custom AI assistant description",
    )


class GroupChatUpdateTools(BaseModel):
    assistants: list[GroupChatAssistantUpdateSchema]


class GroupChatUpdateSchema(BaseModel):
    name: Optional[str] = Field(
        default=None, title="Name", description="The name of the group chat."
    )
    space_id: Optional[UUID] = None
    tools: Optional[GroupChatUpdateTools] = Field(
        default=None,
        description="Tools available in the group chat.",
    )
    allow_mentions: Optional[bool] = Field(
        default=None,
        description="Indicates if mentions are allowed.",
    )
    show_response_label: Optional[bool] = Field(
        default=None,
        description="Indicates if the response label should be shown.",
    )

    insight_enabled: Optional[bool] = Field(
        default=None,
        description=(
            "Whether insights are enabled for this group chat. If enabled, users with "
            "appropriate permissions can see all sessions for this group chat."
        ),
    )
    metadata_json: Optional[dict] = Field(  # type: ignore[assignment]
        default=NOT_PROVIDED,
        description="Metadata for the group chat.",
    )
    icon_id: Union[UUID, None, NotProvided] = Field(
        default=NOT_PROVIDED,
        description="Icon ID referencing an uploaded icon. Set to null to remove.",
    )


# Presentation
class GroupChatSparse(ResourcePermissionsMixin):
    created_at: datetime
    updated_at: datetime
    name: str
    id: UUID
    user_id: UUID
    published: bool
    type: Literal["group-chat"]
    metadata_json: Optional[dict]
    icon_id: Optional[UUID] = None


class GroupChatAssistantPublic(ToolAssistant):
    default_description: Optional[str]
    user_description: Optional[str]

    @model_validator(mode="after")
    def validate_descriptions(self) -> "GroupChatAssistantPublic":
        if self.default_description is None and self.user_description is None:
            raise ValueError(
                "Both default_description and user_description cannot be null"
            )
        return self


class GroupChatTools(BaseModel):
    assistants: list[GroupChatAssistantPublic]


class GroupChatPublic(BaseModel):
    """
    Represents a group chat of assistants.

    Attributes:
        created_at: datetime
        updated_at: datetime
        name: str
        id: UUID
        space_id: UUID
        allow_mentions: bool
        show_response_label: bool
        tools: GroupChatTools
        insight_enabled: bool
        attachments: list[FilePublic]
        allowed_attachments: FileRestrictions
        type: str
    """

    created_at: datetime
    updated_at: datetime
    name: str
    id: UUID
    space_id: UUID
    allow_mentions: bool
    show_response_label: bool
    published: bool
    insight_enabled: bool = Field(
        description=(
            "Whether insights are enabled for this group chat. If enabled, users with "
            "appropriate permissions can see all sessions for this group chat."
        ),
    )
    tools: GroupChatTools
    attachments: list[FilePublic]
    allowed_attachments: FileRestrictions
    type: Literal["group-chat"]
    # NOTE: Atm, the front-end does not check this list for permissions regarding group chats.
    # Instead it checks against assistant permissions.
    permissions: list[ResourcePermission]
    metadata_json: Optional[dict]
    icon_id: Optional[UUID] = None
