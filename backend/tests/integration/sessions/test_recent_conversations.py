"""GET /conversations/recent/: the caller's latest conversations everywhere.

Pins the three rules of the recent list against a real database:

* ownership: only the caller's own conversations, never another user's in
  the same assistant;
* ordering: latest activity (the latest question, or the creation of a
  conversation without one) first, with the limit applied after it;
* access: a conversation is listed exactly when its own history
  (``GET /conversations/?assistant_id=`` / ``?group_chat_id=``) opens for the
  caller, so leaving a space, the organisation space's admin-only rule and
  unpublished group chats for viewers hide it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.group_chats_table import GroupChatsTable
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces, SpacesUserGroups, SpacesUsers
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import usergroups_users_table
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserInDB, UserState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NOW = datetime.now(timezone.utc)


@pytest.fixture
async def member(db_container, admin_user) -> UserInDB:
    """A user who may chat (assistants, group chats, personal chat) but is no admin."""
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"chat-{uuid4().hex[:8]}",
                permissions=[
                    Permission.ASSISTANTS,
                    Permission.GROUP_CHATS,
                    Permission.PERSONAL_CHAT,
                ],
                tenant_id=admin_user.tenant_id,
            )
        )
        return await container.user_repo().add(
            UserAdd(
                email=f"recent-{uuid4().hex[:8]}@example.com",
                username=f"recent_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )


async def _token(db_container, user: UserInDB) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(user)


async def _org_space(db, tenant_id: UUID) -> UUID:
    space_id = await db.scalar(
        sa.select(Spaces.id).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    assert space_id is not None, "add_tenant_user seeds the organisation space"
    return space_id


async def _space(
    db,
    *,
    tenant_id: UUID,
    name: str,
    owner_id: UUID | None = None,
    org_space_id: UUID | None = None,
) -> UUID:
    space_id = uuid4()
    await db.execute(
        sa.insert(Spaces).values(
            id=space_id,
            name=name,
            tenant_id=tenant_id,
            user_id=owner_id,
            tenant_space_id=org_space_id,
        )
    )
    return space_id


async def _assistant(
    db,
    *,
    space_id: UUID,
    owner_id: UUID,
    name: str,
    is_default: bool = False,
) -> UUID:
    assistant_id = uuid4()
    await db.execute(
        sa.insert(Assistants).values(
            id=assistant_id,
            name=name,
            user_id=owner_id,
            space_id=space_id,
            logging_enabled=False,
            is_default=is_default,
            published=True,
        )
    )
    return assistant_id


async def _group_chat(
    db, *, space_id: UUID, owner_id: UUID, name: str, published: bool
) -> UUID:
    group_chat_id = uuid4()
    await db.execute(
        sa.insert(GroupChatsTable).values(
            id=group_chat_id,
            name=name,
            user_id=owner_id,
            space_id=space_id,
            allow_mentions=False,
            show_response_label=False,
            published=published,
            insight_enabled=False,
            type="group-chat",
        )
    )
    return group_chat_id


async def _conversation(
    db,
    *,
    user: UserInDB,
    name: str,
    created: timedelta,
    asked: list[timedelta] | None = None,
    assistant_id: UUID | None = None,
    group_chat_id: UUID | None = None,
) -> UUID:
    """A conversation created `created` ago with questions asked `asked` ago."""
    session_id = uuid4()
    await db.execute(
        sa.insert(Sessions).values(
            id=session_id,
            name=name,
            user_id=user.id,
            assistant_id=assistant_id,
            group_chat_id=group_chat_id,
            created_at=NOW - created,
            updated_at=NOW - created,
        )
    )
    for ago in asked or []:
        await db.execute(
            sa.insert(Questions).values(
                id=uuid4(),
                tenant_id=user.tenant_id,
                session_id=session_id,
                assistant_id=assistant_id,
                question="question",
                answer="answer",
                num_tokens_question=1,
                num_tokens_answer=1,
                created_at=NOW - ago,
                updated_at=NOW - ago,
            )
        )
    return session_id


async def _member_of(db, *, space_id: UUID, user_id: UUID, role: str) -> None:
    await db.execute(
        sa.insert(SpacesUsers).values(space_id=space_id, user_id=user_id, role=role)
    )


@dataclass(frozen=True)
class Scenario:
    personal_space: UUID
    shared_space: UUID
    group_space: UUID
    personal_chat: UUID
    viewer_assistant: UUID
    published_group_chat: UUID
    unpublished_group_chat: UUID
    left_space_assistant: UUID
    org_assistant: UUID
    group_role_assistant: UUID
    # Conversation ids, in the order the recent list must return them.
    listed: tuple[UUID, ...]
    hidden: tuple[UUID, ...]


async def _scenario(db_container, admin_user: UserInDB, member: UserInDB) -> Scenario:
    async with db_container() as container:
        db = container.session()
        tenant_id = member.tenant_id
        org_space = await _org_space(db, tenant_id)

        personal_space = await _space(
            db, tenant_id=tenant_id, name="Personal", owner_id=member.id
        )
        personal_chat = await _assistant(
            db,
            space_id=personal_space,
            owner_id=member.id,
            name="Personal assistant",
            is_default=True,
        )

        # A shared space the member views.
        shared_space = await _space(
            db, tenant_id=tenant_id, name="Upphandling", org_space_id=org_space
        )
        await _member_of(db, space_id=shared_space, user_id=member.id, role="viewer")
        viewer_assistant = await _assistant(
            db, space_id=shared_space, owner_id=admin_user.id, name="Avtalsgranskaren"
        )
        published_group_chat = await _group_chat(
            db,
            space_id=shared_space,
            owner_id=admin_user.id,
            name="Inköpsrådet",
            published=True,
        )
        unpublished_group_chat = await _group_chat(
            db,
            space_id=shared_space,
            owner_id=admin_user.id,
            name="Utkast",
            published=False,
        )

        # A space the member has left, and the organisation space (admins only).
        left_space = await _space(
            db, tenant_id=tenant_id, name="Lämnad", org_space_id=org_space
        )
        left_space_assistant = await _assistant(
            db, space_id=left_space, owner_id=admin_user.id, name="Gammal"
        )
        org_assistant = await _assistant(
            db, space_id=org_space, owner_id=admin_user.id, name="Organisationen"
        )

        # A space the member reaches through a user group only.
        group_id = uuid4()
        await db.execute(
            sa.insert(UserGroups).values(
                id=group_id, name=f"grupp-{group_id.hex[:8]}", tenant_id=tenant_id
            )
        )
        await db.execute(
            sa.insert(usergroups_users_table).values(
                user_id=member.id, user_group_id=group_id
            )
        )
        group_space = await _space(
            db, tenant_id=tenant_id, name="Socialtjänst", org_space_id=org_space
        )
        await db.execute(
            sa.insert(SpacesUserGroups).values(
                space_id=group_space, user_group_id=group_id, role="editor"
            )
        )
        group_role_assistant = await _assistant(
            db, space_id=group_space, owner_id=admin_user.id, name="Handläggaren"
        )

        old_but_active = await _conversation(
            db,
            user=member,
            name="Old, asked a minute ago",
            created=timedelta(days=30),
            asked=[timedelta(days=30), timedelta(minutes=1)],
            assistant_id=personal_chat,
        )
        in_group_space = await _conversation(
            db,
            user=member,
            name="Through the group",
            created=timedelta(minutes=5),
            asked=[timedelta(minutes=4)],
            assistant_id=group_role_assistant,
        )
        never_asked = await _conversation(
            db,
            user=member,
            name="Created an hour ago",
            created=timedelta(hours=1),
            assistant_id=viewer_assistant,
        )
        in_group_chat = await _conversation(
            db,
            user=member,
            name="Group chat",
            created=timedelta(days=2),
            asked=[timedelta(hours=3)],
            group_chat_id=published_group_chat,
        )
        hidden = (
            await _conversation(
                db,
                user=member,
                name="Unpublished group chat",
                created=timedelta(seconds=30),
                asked=[timedelta(seconds=20)],
                group_chat_id=unpublished_group_chat,
            ),
            await _conversation(
                db,
                user=member,
                name="Left space",
                created=timedelta(seconds=30),
                asked=[timedelta(seconds=20)],
                assistant_id=left_space_assistant,
            ),
            await _conversation(
                db,
                user=member,
                name="Organisation",
                created=timedelta(seconds=30),
                asked=[timedelta(seconds=20)],
                assistant_id=org_assistant,
            ),
            # Someone else's conversation with the same assistant.
            await _conversation(
                db,
                user=admin_user,
                name="Not mine",
                created=timedelta(seconds=10),
                asked=[timedelta(seconds=5)],
                assistant_id=viewer_assistant,
            ),
        )

    return Scenario(
        personal_space=personal_space,
        shared_space=shared_space,
        group_space=group_space,
        personal_chat=personal_chat,
        viewer_assistant=viewer_assistant,
        published_group_chat=published_group_chat,
        unpublished_group_chat=unpublished_group_chat,
        left_space_assistant=left_space_assistant,
        org_assistant=org_assistant,
        group_role_assistant=group_role_assistant,
        listed=(old_but_active, in_group_space, never_asked, in_group_chat),
        hidden=hidden,
    )


async def test_lists_own_conversations_the_user_can_open_latest_activity_first(
    client, db_container, admin_user, member, patch_auth_service_jwt
):
    scenario = await _scenario(db_container, admin_user, member)
    headers = {"Authorization": f"Bearer {await _token(db_container, member)}"}

    response = await client.get("/api/v1/conversations/recent/", headers=headers)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [UUID(item["id"]) for item in items] == list(scenario.listed)
    personal, via_group, viewer, group_chat = items
    assert personal["partner"] == {
        "type": "default-assistant",
        "id": str(scenario.personal_chat),
        "name": "Personal assistant",
    }
    assert personal["space"] == {
        "id": str(scenario.personal_space),
        "name": "Personal",
        "personal": True,
        "organization": False,
    }
    # Activity is the latest question, not the creation of the conversation.
    assert datetime.fromisoformat(personal["last_activity_at"]) > NOW - timedelta(
        minutes=2
    )
    assert datetime.fromisoformat(personal["created_at"]) < NOW - timedelta(days=29)
    assert via_group["partner"]["type"] == "assistant"
    assert via_group["space"]["id"] == str(scenario.group_space)
    # Without questions a conversation's activity is its creation.
    assert viewer["last_activity_at"] == viewer["created_at"]
    assert viewer["partner"] == {
        "type": "assistant",
        "id": str(scenario.viewer_assistant),
        "name": "Avtalsgranskaren",
    }
    assert viewer["space"] == {
        "id": str(scenario.shared_space),
        "name": "Upphandling",
        "personal": False,
        "organization": False,
    }
    assert group_chat["partner"] == {
        "type": "group-chat",
        "id": str(scenario.published_group_chat),
        "name": "Inköpsrådet",
    }


async def test_lists_exactly_the_partners_whose_history_opens(
    client, db_container, admin_user, member, patch_auth_service_jwt
):
    """The recent list and the per-partner history authorize the same way."""
    scenario = await _scenario(db_container, admin_user, member)
    headers = {"Authorization": f"Bearer {await _token(db_container, member)}"}

    recent = await client.get("/api/v1/conversations/recent/", headers=headers)
    assert recent.status_code == 200, recent.text
    listed_partners = {item["partner"]["id"] for item in recent.json()["items"]}

    partners = {
        scenario.personal_chat: "assistant_id",
        scenario.viewer_assistant: "assistant_id",
        scenario.group_role_assistant: "assistant_id",
        scenario.left_space_assistant: "assistant_id",
        scenario.org_assistant: "assistant_id",
        scenario.published_group_chat: "group_chat_id",
        scenario.unpublished_group_chat: "group_chat_id",
    }
    for partner_id, param in partners.items():
        history = await client.get(
            "/api/v1/conversations/",
            params={param: str(partner_id)},
            headers=headers,
        )
        assert history.status_code in (200, 403), history.text
        assert (history.status_code == 200) == (str(partner_id) in listed_partners), (
            f"{param}={partner_id}: history {history.status_code}, "
            f"listed={str(partner_id) in listed_partners}"
        )
    assert len(listed_partners) == 4


async def test_limit_applies_after_ordering_and_is_bounded(
    client, db_container, admin_user, member, patch_auth_service_jwt
):
    scenario = await _scenario(db_container, admin_user, member)
    headers = {"Authorization": f"Bearer {await _token(db_container, member)}"}

    response = await client.get(
        "/api/v1/conversations/recent/", params={"limit": 2}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert [UUID(item["id"]) for item in response.json()["items"]] == list(
        scenario.listed[:2]
    )

    for limit in (0, 51):
        rejected = await client.get(
            "/api/v1/conversations/recent/", params={"limit": limit}, headers=headers
        )
        assert rejected.status_code == 422, rejected.text


async def test_is_empty_without_conversations(
    client, db_container, member, patch_auth_service_jwt
):
    headers = {"Authorization": f"Bearer {await _token(db_container, member)}"}

    response = await client.get("/api/v1/conversations/recent/", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "count": 0}


async def test_rejects_api_keys(client, admin_user_api_key):
    response = await client.get(
        "/api/v1/conversations/recent/",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 403, response.text
    assert "session_auth_required" in response.text
