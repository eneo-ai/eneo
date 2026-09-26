"""RecentConversationsService: which partners' conversations are listed.

The service must authorize each partner exactly like its own history does
(AssistantService._authorize_read_assistant, GroupChatService.get_group_chat)
through SpaceActor, and read conversations only for the partners that pass.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.actors import ActorFactory, ActorManager
from eneo.actors.actors.space_actor import SpaceAccessFacts, SpaceRoleFact
from eneo.conversations.application.recent_conversations_service import (
    RecentConversationsService,
)
from eneo.conversations.conversations_router import (
    list_recent_conversations,
)
from eneo.conversations.conversations_router import router as conversations_router
from eneo.roles.permissions import Permission
from eneo.sessions.sessions_repo import ChatPartnerAccess, RecentSessionRow

CHAT_PERMISSIONS = {
    Permission.ASSISTANTS,
    Permission.GROUP_CHATS,
    Permission.PERSONAL_CHAT,
}
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
ORG_SPACE_ID = uuid4()


def _user(permissions=CHAT_PERMISSIONS, group_ids: frozenset[UUID] = frozenset()):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=set(permissions),
        user_groups_ids=set(group_ids),
        active_api_key=None,
    )


def _space(
    *,
    owner_id: UUID | None = None,
    organization: bool = False,
    member: tuple[UUID, str] | None = None,
    group: tuple[UUID, str] | None = None,
    default_assistant_id: UUID | None = None,
) -> SpaceAccessFacts:
    return SpaceAccessFacts(
        id=uuid4(),
        user_id=owner_id,
        tenant_space_id=None if organization or owner_id else ORG_SPACE_ID,
        members={member[0]: SpaceRoleFact(id=member[0], role=member[1])}
        if member
        else {},
        group_members={group[0]: SpaceRoleFact(id=group[0], role=group[1])}
        if group
        else {},
        default_assistant_id=default_assistant_id,
        assistant_ids=frozenset(),
        app_ids=frozenset(),
    )


def _assistant(space: SpaceAccessFacts, *, assistant_id: UUID | None = None, name="A"):
    return ChatPartnerAccess(
        assistant_id=assistant_id or uuid4(),
        group_chat_id=None,
        name=name,
        published=False,
        space_name="Space",
        space=space,
    )


def _group_chat(space: SpaceAccessFacts, *, published: bool, name="G"):
    return ChatPartnerAccess(
        assistant_id=None,
        group_chat_id=uuid4(),
        name=name,
        published=published,
        space_name="Space",
        space=space,
    )


def _personal_chat(user) -> ChatPartnerAccess:
    assistant_id = uuid4()
    space = _space(owner_id=user.id, default_assistant_id=assistant_id)
    return _assistant(space, assistant_id=assistant_id, name="Personal")


def _row(partner: ChatPartnerAccess, *, minutes_ago: int = 0) -> RecentSessionRow:
    at = NOW - timedelta(minutes=minutes_ago)
    return RecentSessionRow(
        id=uuid4(),
        name=f"Conversation with {partner.name}",
        created_at=at - timedelta(days=1),
        last_activity_at=at,
        assistant_id=partner.assistant_id,
        group_chat_id=partner.group_chat_id,
    )


def _service(user, partners: list[ChatPartnerAccess], rows: list[RecentSessionRow]):
    repo = SimpleNamespace(
        get_chat_partners_of_user=AsyncMock(return_value=partners),
        get_recent_for_user=AsyncMock(return_value=rows),
    )
    service = RecentConversationsService(
        user=user,  # pyright: ignore[reportArgumentType]
        session_repo=repo,  # pyright: ignore[reportArgumentType]
        actor_manager=ActorManager(user=user, factory=ActorFactory()),  # pyright: ignore[reportArgumentType]
    )
    return service, repo


async def _listed_partner_ids(user, partners: list[ChatPartnerAccess]) -> set[UUID]:
    """The partners whose conversations the service asks the repo for."""
    service, repo = _service(user, partners, rows=[])
    await service.list_recent(limit=20)
    if not repo.get_recent_for_user.await_count:
        return set()
    kwargs = repo.get_recent_for_user.await_args.kwargs
    return set(kwargs["assistant_ids"]) | set(kwargs["group_chat_ids"])


async def test_the_personal_chat_needs_the_personal_chat_permission():
    user = _user()
    personal = _personal_chat(user)
    assert await _listed_partner_ids(user, [personal]) == {personal.id}

    without = _user(permissions=CHAT_PERMISSIONS - {Permission.PERSONAL_CHAT})
    assert await _listed_partner_ids(without, [_personal_chat(without)]) == set()


async def test_other_personal_space_assistants_need_the_assistants_permission():
    user = _user(permissions={Permission.PERSONAL_CHAT})
    personal = _personal_chat(user)
    other = _assistant(personal.space)

    assert await _listed_partner_ids(user, [personal, other]) == {personal.id}


async def test_someone_elses_personal_space_is_never_listed():
    user = _user()
    stranger = _user()

    assert await _listed_partner_ids(user, [_personal_chat(stranger)]) == set()


@pytest.mark.parametrize(
    ("role", "permissions", "listed"),
    [
        ("viewer", CHAT_PERMISSIONS, True),
        ("editor", CHAT_PERMISSIONS, True),
        (None, CHAT_PERMISSIONS, False),
        ("viewer", CHAT_PERMISSIONS - {Permission.ASSISTANTS}, False),
    ],
)
async def test_a_space_assistant_follows_membership_and_permission(
    role, permissions, listed
):
    user = _user(permissions=permissions)
    space = _space(member=(user.id, role) if role else None)
    assistant = _assistant(space)

    expected = {assistant.id} if listed else set()
    assert await _listed_partner_ids(user, [assistant]) == expected


async def test_a_role_through_a_user_group_counts():
    group_id = uuid4()
    user = _user(group_ids=frozenset({group_id}))
    assistant = _assistant(_space(group=(group_id, "viewer")))
    unrelated = _assistant(_space(group=(uuid4(), "admin")))

    assert await _listed_partner_ids(user, [assistant, unrelated]) == {assistant.id}


@pytest.mark.parametrize(
    ("role", "published", "permissions", "listed"),
    [
        ("viewer", True, CHAT_PERMISSIONS, True),
        ("viewer", False, CHAT_PERMISSIONS, False),
        ("editor", False, CHAT_PERMISSIONS, True),
        ("editor", True, CHAT_PERMISSIONS - {Permission.GROUP_CHATS}, False),
    ],
)
async def test_group_chats_are_published_ones_for_viewers(
    role, published, permissions, listed
):
    user = _user(permissions=permissions)
    group_chat = _group_chat(_space(member=(user.id, role)), published=published)

    expected = {group_chat.id} if listed else set()
    assert await _listed_partner_ids(user, [group_chat]) == expected


@pytest.mark.parametrize(("role", "listed"), [("editor", False), ("admin", True)])
async def test_the_organisation_space_is_for_its_admins(role, listed):
    user = _user()
    assistant = _assistant(_space(organization=True, member=(user.id, role)))

    expected = {assistant.id} if listed else set()
    assert await _listed_partner_ids(user, [assistant]) == expected


def test_the_route_is_matched_before_the_conversation_route():
    # "/{session_id}/" would take "recent" as a session id and reject it.
    paths = [
        route.path
        for route in conversations_router.routes
        if "GET" in getattr(route, "methods", set())
    ]
    assert paths.index("/recent/") < paths.index("/{session_id}/")


async def test_the_route_lists_through_the_container_service():
    recent = [SimpleNamespace(id=uuid4())]
    service = SimpleNamespace(list_recent=AsyncMock(return_value=recent))
    container = SimpleNamespace(recent_conversations_service=lambda: service)

    response = await list_recent_conversations(
        container=container,  # pyright: ignore[reportArgumentType]
        limit=7,
    )

    service.list_recent.assert_awaited_once_with(limit=7)
    assert response.items == recent


async def test_nothing_to_open_skips_the_conversation_query():
    user = _user(permissions=set())
    service, repo = _service(user, [_personal_chat(user)], rows=[])

    assert await service.list_recent(limit=5) == []
    repo.get_recent_for_user.assert_not_awaited()


async def test_lists_rows_in_repo_order_labelled_with_partner_and_space():
    user = _user()
    personal = _personal_chat(user)
    shared_default_id = uuid4()
    shared = _space(member=(user.id, "editor"), default_assistant_id=shared_default_id)
    space_chat = _assistant(shared, assistant_id=shared_default_id, name="Upphandling")
    assistant = _assistant(shared, name="Avtalsgranskaren")
    group_chat = _group_chat(shared, published=False, name="Inköpsrådet")
    hidden = _assistant(_space(), name="Hidden")
    partners = [personal, space_chat, assistant, group_chat, hidden]
    rows = [
        _row(group_chat, minutes_ago=1),
        _row(personal, minutes_ago=2),
        _row(assistant, minutes_ago=3),
        _row(space_chat, minutes_ago=4),
    ]
    service, repo = _service(user, partners, rows)

    recent = await service.list_recent(limit=7)

    repo.get_chat_partners_of_user.assert_awaited_once_with(
        user_id=user.id, tenant_id=user.tenant_id, user_group_ids=user.user_groups_ids
    )
    query = repo.get_recent_for_user.await_args.kwargs
    assert query["user_id"] == user.id
    assert query["limit"] == 7
    assert set(query["assistant_ids"]) == {personal.id, space_chat.id, assistant.id}
    assert query["group_chat_ids"] == [group_chat.id]

    assert [item.id for item in recent] == [row.id for row in rows]
    assert [(item.partner.type, item.partner.name) for item in recent] == [
        ("group-chat", "Inköpsrådet"),
        ("default-assistant", "Personal"),
        ("assistant", "Avtalsgranskaren"),
        ("default-assistant", "Upphandling"),
    ]
    first, personal_item = recent[0], recent[1]
    assert first.partner.id == group_chat.id
    assert first.last_activity_at == rows[0].last_activity_at
    assert first.created_at == rows[0].created_at
    assert (first.space.id, first.space.personal, first.space.organization) == (
        shared.id,
        False,
        False,
    )
    assert personal_item.space.id == personal.space.id
    assert personal_item.space.personal is True
