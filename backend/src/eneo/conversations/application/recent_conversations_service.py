# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import TYPE_CHECKING, Literal

from eneo.conversations.conversation_models import (
    RecentConversation,
    RecentConversationPartner,
    RecentConversationSpace,
)

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.actors import ActorManager
    from eneo.sessions.sessions_repo import (
        ChatPartnerAccess,
        RecentSessionRow,
        SessionRepository,
    )
    from eneo.users.user import UserInDB


class RecentConversationsService:
    """The caller's own latest conversations with every partner they can open.

    A conversation is listed only while its assistant or group chat passes the
    read check of its own history (``GET /conversations/`` with an
    ``assistant_id`` or ``group_chat_id``): one that became unreachable (the
    user left the space, a permission was revoked, a group chat was
    unpublished for a viewer) drops out. Partners are authorized before the
    conversations are read, so hidden rows never eat into the limit.
    """

    def __init__(
        self,
        user: "UserInDB",
        session_repo: "SessionRepository",
        actor_manager: "ActorManager",
    ) -> None:
        super().__init__()
        self.user = user
        self.session_repo = session_repo
        self.actor_manager = actor_manager

    async def list_recent(self, limit: int) -> list[RecentConversation]:
        partners = await self.session_repo.get_chat_partners_of_user(
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
            user_group_ids=self.user.user_groups_ids,
        )
        readable = {
            partner.id: partner for partner in partners if self._can_open(partner)
        }
        if not readable:
            return []

        rows = await self.session_repo.get_recent_for_user(
            user_id=self.user.id,
            assistant_ids=[
                partner.assistant_id
                for partner in readable.values()
                if partner.assistant_id is not None
            ],
            group_chat_ids=[
                partner.group_chat_id
                for partner in readable.values()
                if partner.group_chat_id is not None
            ],
            limit=limit,
        )
        return [
            _to_recent_conversation(row, readable[_partner_id(row)]) for row in rows
        ]

    def _can_open(self, partner: "ChatPartnerAccess") -> bool:
        actor = self.actor_manager.get_space_actor(partner.space)
        if partner.group_chat_id is not None:
            # GroupChatService.get_group_chat: viewers read published ones only.
            return actor.can_read_group_chat(group_chat=partner)
        # AssistantService._authorize_read_assistant: the personal chat (the
        # personal space's own assistant) is gated by PERSONAL_CHAT, every
        # other assistant by the space's assistant read permission.
        if (
            partner.space.is_personal()
            and _partner_type(partner) == "default-assistant"
        ):
            return actor.can_read_default_assistant()
        return actor.can_read_assistants()


def _partner_type(
    partner: "ChatPartnerAccess",
) -> Literal["assistant", "default-assistant", "group-chat"]:
    if partner.group_chat_id is not None:
        return "group-chat"
    if partner.assistant_id == partner.space.default_assistant_id:
        return "default-assistant"
    return "assistant"


def _partner_id(row: "RecentSessionRow") -> "UUID":
    partner_id = row.group_chat_id or row.assistant_id
    assert partner_id is not None
    return partner_id


def _to_recent_conversation(
    row: "RecentSessionRow", partner: "ChatPartnerAccess"
) -> RecentConversation:
    space_id = partner.space.id
    assert space_id is not None
    return RecentConversation(
        id=row.id,
        name=row.name,
        created_at=row.created_at,
        last_activity_at=row.last_activity_at,
        partner=RecentConversationPartner(
            type=_partner_type(partner), id=partner.id, name=partner.name
        ),
        space=RecentConversationSpace(
            id=space_id,
            name=partner.space_name,
            personal=partner.space.is_personal(),
            organization=partner.space.is_organization(),
        ),
    )
