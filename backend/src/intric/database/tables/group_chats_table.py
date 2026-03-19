# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.assistant_table import Assistants
from intric.database.tables.base_class import BaseCrossReference, BasePublic
from intric.database.tables.icons_table import Icons
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.users_table import Users


class GroupChatsTable(BasePublic):
    __tablename__ = "group_chats"  # type: ignore[assignment]

    name: Mapped[str] = mapped_column()
    allow_mentions: Mapped[bool] = mapped_column(Boolean, default=False)
    show_response_label: Mapped[bool] = mapped_column(Boolean, default=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    insight_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # TODO: refactor since this is a somewhat weird solution having a
    # type column. The reason is bc front-end wants a non-nullable
    # "type" field in a bunch of models. Thus a field with a default
    # value cannot be used. Just adding it to all constructors and
    # factories => issues with model validation.
    # This was quickest, simplest solution.
    type: Mapped[str] = mapped_column(default="group-chat")
    icon_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Icons.id, ondelete="SET NULL"), nullable=True
    )

    space_id: Mapped[UUID] = mapped_column(ForeignKey(Spaces.id, ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="CASCADE"))
    group_chat_assistants: Mapped[list["GroupChatsAssistantsMapping"]] = relationship(
        viewonly=True
    )


class GroupChatsAssistantsMapping(BaseCrossReference):
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey(GroupChatsTable.id, ondelete="CASCADE"), primary_key=True
    )
    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Assistants.id, ondelete="CASCADE"), primary_key=True
    )
    user_description: Mapped[str | None] = mapped_column(nullable=True)
    user_description: Mapped[str | None] = mapped_column(nullable=True)
