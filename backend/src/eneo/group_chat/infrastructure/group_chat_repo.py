"""Group chat persistence owns chat rows and explicit member-list replacements."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.association_writes import replace_association_values
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.group_chats_table import (
    GroupChatsAssistantsMapping,
    GroupChatsTable,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.group_chat.domain.entities.group_chat import GroupChat
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.main.models import NOT_PROVIDED, NotProvided, is_provided


class GroupChatRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, chat: GroupChat) -> None:
        await self.session.execute(
            sa.insert(GroupChatsTable).values(
                id=chat.id,
                space_id=chat.space_id,
                user_id=chat.user_id,
                name=chat.name,
                type="group-chat",
                allow_mentions=chat.allow_mentions,
                show_response_label=chat.show_response_label,
                published=chat.published,
                insight_enabled=chat.insight_enabled,
                metadata_json=chat.metadata_json,
                icon_id=chat.icon_id,
            )
        )
        if chat.assistants:
            await self.update(
                chat.id,
                chat.space_id,
                members={
                    member.assistant.id: member.user_description
                    for member in chat.assistants
                },
            )

    async def update(
        self,
        chat_id: UUID,
        space_id: UUID,
        *,
        name: str | None = None,
        allow_mentions: bool | None = None,
        show_response_label: bool | None = None,
        published: bool | None = None,
        insight_enabled: bool | None = None,
        metadata_json: dict[str, object] | None | NotProvided = NOT_PROVIDED,
        icon_id: UUID | None | NotProvided = NOT_PROVIDED,
        members: dict[UUID, str | None] | None = None,
    ) -> None:
        if members is not None:
            # Assistant moves lock source/destination Spaces first. Take that
            # same lock before checking seats so a moved member cannot be
            # reinserted into its former Space by a concurrent replacement.
            await self.session.scalar(
                sa.select(Spaces.id)
                .where(
                    Spaces.id == space_id,
                )
                .with_for_update()
            )
        found = await self.session.scalar(
            sa.select(GroupChatsTable.id)
            .where(
                GroupChatsTable.id == chat_id,
                GroupChatsTable.space_id == space_id,
            )
            .with_for_update()
        )
        if found is None:
            raise NotFoundException("Group chat not found")
        values: dict[str, object] = {
            key: value
            for key, value in {
                "name": name,
                "allow_mentions": allow_mentions,
                "show_response_label": show_response_label,
                "published": published,
                "insight_enabled": insight_enabled,
            }.items()
            if value is not None
        }
        if is_provided(metadata_json):
            values["metadata_json"] = metadata_json
        if is_provided(icon_id):
            values["icon_id"] = icon_id
        if values:
            await self.session.execute(
                sa.update(GroupChatsTable)
                .where(
                    GroupChatsTable.id == chat_id,
                    GroupChatsTable.space_id == space_id,
                )
                .values(**values)
            )
        if members is not None:
            found_ids = set(
                await self.session.scalars(
                    sa.select(Assistants.id).where(
                        Assistants.id.in_(members),
                        Assistants.space_id == space_id,
                    )
                )
            )
            if members.keys() - found_ids:
                raise BadRequestException("Group chat members must belong to its space")
            await replace_association_values(
                self.session,
                GroupChatsAssistantsMapping,
                GroupChatsAssistantsMapping.group_chat_id,
                chat_id,
                GroupChatsAssistantsMapping.assistant_id,
                GroupChatsAssistantsMapping.user_description,
                members,
            )

    async def delete(self, chat_id: UUID, space_id: UUID) -> None:
        await self.session.execute(
            sa.delete(GroupChatsTable).where(
                GroupChatsTable.id == chat_id,
                GroupChatsTable.space_id == space_id,
            )
        )
