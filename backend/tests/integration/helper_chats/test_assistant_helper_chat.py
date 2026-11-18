"""The helper chat on an assistant: who gets one, who reaches it, what its
tools read, and what happens to it when the assistant goes or moves."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg2
import pytest
import sqlalchemy as sa

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
)
from eneo.assistants.assistant import Assistant
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import AssistantMCPServers, Assistants
from eneo.database.tables.helper_chats_table import HelperChats
from eneo.database.tables.mcp_server_table import MCPServers, SpacesMCPServers
from eneo.database.tables.prompts_table import Prompts, PromptsAssistants
from eneo.database.tables.sessions_table import Sessions
from eneo.helper_chats.personas.assistant import ASSISTANT_INSTRUCTIONS
from eneo.internal_mcp import assistant_settings
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.services.service import DatastoreResult
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.users.user import UserAdd, UserState
from init_db import add_tenant_user


@dataclass(frozen=True)
class Setup:
    headers: dict[str, str]
    space_id: str
    assistant_id: str
    url: str


@pytest.fixture
async def setup(client, db_container, admin_user, patch_auth_service_jwt) -> Setup:
    async with db_container() as container:
        # The chat's instructions need a model that calls tools and has room.
        await container.session().execute(
            sa.update(CompletionModels)
            .where(CompletionModels.tenant_id == admin_user.tenant_id)
            .values(supports_tool_calling=True, max_input_tokens=128_000)
        )
        token = container.auth_service().create_access_token_for_user(admin_user)
    headers = {"Authorization": f"Bearer {token}"}
    space = await client.post(
        "/api/v1/spaces/",
        headers=headers,
        json={"name": f"helper-chat-{uuid4().hex[:8]}"},
    )
    assert space.status_code == 201, space.text
    assistant = await client.post(
        "/api/v1/assistants/",
        headers=headers,
        json={"name": "Ärendehjälpen", "space_id": space.json()["id"]},
    )
    assert assistant.status_code == 200, assistant.text
    assistant_id = assistant.json()["id"]
    return Setup(
        headers=headers,
        space_id=space.json()["id"],
        assistant_id=assistant_id,
        url=f"/api/v1/assistants/{assistant_id}/helper-chat/",
    )


async def _member_headers(
    db_container, tenant_id: UUID, space_id: str, role: SpaceRoleValue
) -> dict[str, str]:
    """Another person of the tenant, in the space with ``role``."""
    async with db_container() as container:
        suffix = uuid4().hex[:8]
        created = await container.role_repo().create_role(
            RoleCreate(
                name=f"helper-chat-member-{suffix}",
                permissions=[Permission.ASSISTANTS],
                tenant_id=tenant_id,
            )
        )
        user = await container.user_repo().add(
            UserAdd(
                email=f"helper-chat-member-{suffix}@example.com",
                username=f"helper_chat_member_{suffix}",
                state=UserState.ACTIVE,
                tenant_id=tenant_id,
                roles=[ModelId(id=created.id)],
            )
        )
        await container.session().execute(
            sa.text(
                "INSERT INTO spaces_users (space_id, user_id, role) "
                "VALUES (:space_id, :user_id, :role)"
            ),
            {"space_id": space_id, "user_id": str(user.id), "role": role.value},
        )
        token = container.auth_service().create_access_token_for_user(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def other_tenant_headers(db_container, test_settings) -> dict[str, str]:
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    add_tenant_user(
        conn,
        tenant_name="helper_chat_tenant_2",
        quota_limit=1000000,
        user_name="helper_chat_user_2",
        user_email="helper-chat-2@example.com",
        user_password="TenantFixturePass123!",
    )
    conn.close()
    async with db_container() as container:
        user = await container.user_repo().get_user_by_email(
            "helper-chat-2@example.com"
        )
        token = container.auth_service().create_access_token_for_user(user)
    return {"Authorization": f"Bearer {token}"}


def _body(response) -> tuple[int, dict]:
    """The status and body, without the request's own id."""
    body = response.json() if response.content else {}
    body.pop("request_id", None)
    return response.status_code, body


async def _open(client, setup: Setup) -> dict:
    opened = await client.post(setup.url, headers=setup.headers)
    assert opened.status_code == 200, opened.text
    return opened.json()


async def test_a_chat_is_opened_once_in_view_mode_with_the_assistants_persona(
    client, setup: Setup, db_container
):
    available = await client.get(setup.url + "availability", headers=setup.headers)
    assert available.status_code == 200, available.text
    assert available.json() == {"available": True, "reason": None}

    chat = await _open(client, setup)

    assert chat == await _open(client, setup)
    assert chat["target_id"] == setup.assistant_id
    assert chat["assistant_id"] != setup.assistant_id
    assert chat["editing"] is False
    assert chat["default_completion_model_id"] is not None
    async with db_container() as container:
        hidden = await container.session().scalar(
            sa.select(Assistants.hidden).where(
                Assistants.id == UUID(chat["assistant_id"])
            )
        )
        persona = await container.session().scalar(
            sa.select(Prompts.text)
            .join(PromptsAssistants, PromptsAssistants.prompt_id == Prompts.id)
            .where(
                PromptsAssistants.assistant_id == UUID(chat["assistant_id"]),
                PromptsAssistants.is_selected.is_(True),
            )
        )
    assert hidden is True
    assert persona == ASSISTANT_INSTRUCTIONS


async def test_the_person_changes_mode_model_and_conversation_of_their_chat(
    client, setup: Setup
):
    chat = await _open(client, setup)
    url = setup.url + chat["session_id"] + "/"

    editing = await client.patch(url, headers=setup.headers, json={"editing": True})
    assert editing.status_code == 200, editing.text
    assert editing.json()["editing"] is True

    refused = await client.patch(
        url, headers=setup.headers, json={"completion_model_id": str(uuid4())}
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "helper_chat_model_not_in_space"

    started = await client.post(url + "conversations/", headers=setup.headers)
    assert started.status_code == 200, started.text
    assert started.json()["session_id"] != chat["session_id"]
    assert started.json()["assistant_id"] == chat["assistant_id"]


async def _cannot_reach(client, setup: Setup, chat: dict, headers) -> None:
    url = setup.url + chat["session_id"] + "/"
    hidden = f"/api/v1/assistants/{chat['assistant_id']}/"
    responses = {
        "change": await client.patch(url, headers=headers, json={"editing": True}),
        "new conversation": await client.post(url + "conversations/", headers=headers),
        "turn": await client.post(
            hidden + f"sessions/{chat['session_id']}/",
            headers=headers,
            json={"question": "Vad heter assistenten?", "stream": False},
        ),
        "read its assistant": await client.get(hidden, headers=headers),
    }
    assert {call: response.status_code for call, response in responses.items()} == (
        dict.fromkeys(responses, 404)
    ), {call: response.text for call, response in responses.items()}


async def test_the_chat_is_the_persons_alone(
    client, setup: Setup, db_container, admin_user, other_tenant_headers
):
    chat = await _open(client, setup)
    colleague = await _member_headers(
        db_container, admin_user.tenant_id, setup.space_id, SpaceRoleValue.ADMIN
    )

    await _cannot_reach(client, setup, chat, colleague)
    await _cannot_reach(client, setup, chat, other_tenant_headers)

    # The colleague may edit the assistant too and gets a chat of their own.
    theirs = await client.post(setup.url, headers=colleague)
    assert theirs.status_code == 200, theirs.text
    assert theirs.json()["assistant_id"] != chat["assistant_id"]
    assert (await _open(client, setup))["session_id"] == chat["session_id"]


async def test_the_persons_turn_reaches_the_model_with_the_assistant_tools(
    client, setup: Setup, monkeypatch: pytest.MonkeyPatch
):
    chat = await _open(client, setup)
    attached: list[dict[str, list[str]]] = []

    async def ask(self, question, completion_service, references_service, **kwargs):
        attached.append(
            {
                server.name: sorted(tool.name for tool in server.tools)
                for server in kwargs.get("internal_mcp_servers") or []
            }
        )
        model = kwargs.get("completion_model_override") or self.completion_model
        return (
            CompletionModelResponse(
                completion=Completion(text="Svar."), model=model, total_token_count=1
            ),
            DatastoreResult(chunks=[], no_duplicate_chunks=[], info_blobs=[]),
        )

    monkeypatch.setattr(Assistant, "ask", ask)

    asked = await client.post(
        f"/api/v1/assistants/{chat['assistant_id']}/sessions/{chat['session_id']}/",
        headers=setup.headers,
        json={"question": "Vilken modell svarar assistenten med?", "stream": False},
    )

    assert asked.status_code == 200, asked.text
    assert attached == [{"assistant": ["read_assistant", "read_options"]}]


async def test_a_person_who_may_not_edit_gets_the_answer_a_missing_assistant_gets(
    client, setup: Setup, db_container, admin_user
):
    published = await client.post(
        f"/api/v1/assistants/{setup.assistant_id}/publish/",
        headers=setup.headers,
        params={"published": True},
    )
    assert published.status_code == 200, published.text
    viewer = await _member_headers(
        db_container, admin_user.tenant_id, setup.space_id, SpaceRoleValue.VIEWER
    )
    readable = await client.get(
        f"/api/v1/assistants/{setup.assistant_id}/", headers=viewer
    )
    assert readable.status_code == 200, readable.text
    missing_url = f"/api/v1/assistants/{uuid4()}/helper-chat/"

    for headers, url in [(viewer, setup.url), (setup.headers, missing_url)]:
        available = await client.get(url + "availability", headers=headers)
        assert available.json() == {"available": False, "reason": "no_edit_rights"}
    refused = await client.post(setup.url, headers=viewer)
    missing = await client.post(missing_url, headers=setup.headers)

    assert _body(refused) == _body(missing)
    assert refused.status_code == 403
    assert refused.json()["code"] == "helper_chat_no_edit_rights"
    async with db_container() as container:
        chats = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(HelperChats)
            .where(HelperChats.target_id == UUID(setup.assistant_id))
        )
    assert chats == 0


async def test_a_chats_own_assistant_gets_no_chat_and_another_person_no_hint_of_it(
    client, setup: Setup, db_container, admin_user
):
    chat = await _open(client, setup)
    own = f"/api/v1/assistants/{chat['assistant_id']}/helper-chat/"
    colleague = await _member_headers(
        db_container, admin_user.tenant_id, setup.space_id, SpaceRoleValue.ADMIN
    )

    available = await client.get(own + "availability", headers=setup.headers)
    refused = await client.post(own, headers=setup.headers)

    assert available.json() == {"available": False, "reason": "not_supported"}
    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "helper_chat_not_supported"
    theirs = await client.get(own + "availability", headers=colleague)
    assert theirs.json() == {"available": False, "reason": "no_edit_rights"}


def _loopback_ctx(token: str) -> SimpleNamespace:
    """The slice of a FastMCP ``Context`` the loopback foundation reads."""
    request = SimpleNamespace(headers={"authorization": f"Bearer {token}"})
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


async def _ctx(
    db_container, admin_user, *, assistant_id, session_id
) -> SimpleNamespace:
    async with db_container() as container:
        user = await container.user_repo().get_user_by_email(admin_user.email)
        token = container.auth_service().create_scoped_mcp_token(
            user, assistant_id=UUID(assistant_id), session_id=UUID(session_id)
        )
    return _loopback_ctx(token)


async def test_the_tools_find_the_assistant_through_the_chat_only(
    client, setup: Setup, db_container, admin_user
):
    chat = await _open(client, setup)
    own = await _ctx(
        db_container,
        admin_user,
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )

    read = await assistant_settings.read_assistant(own)
    assert not read.isError, read.content[0].text
    assert "Name: Ärendehjälpen" in read.content[0].text
    assert read.structuredContent["assistant_id"] == setup.assistant_id

    for session_id in [str(uuid4()), setup.assistant_id]:
        stray = await _ctx(
            db_container,
            admin_user,
            assistant_id=chat["assistant_id"],
            session_id=session_id,
        )
        refused = await assistant_settings.read_assistant(stray)
        assert refused.isError
        assert "Ärendehjälpen" not in refused.content[0].text


async def test_what_the_tools_read_holds_no_credential(
    client, setup: Setup, db_container, admin_user
):
    token, url_key = f"tok-{uuid4().hex}", f"key-{uuid4().hex}"
    async with db_container() as container:
        server_id = await container.session().scalar(
            sa.insert(MCPServers)
            .values(
                tenant_id=admin_user.tenant_id,
                name="Ärendesystemet",
                description="Läser ärenden.",
                http_url=f"https://cases.example.org/mcp?key={url_key}",
                http_auth_type="bearer",
                http_auth_config_schema={"token": token},
            )
            .returning(MCPServers.id)
        )
        await container.session().execute(
            sa.insert(SpacesMCPServers).values(
                space_id=UUID(setup.space_id), mcp_server_id=server_id
            )
        )
        await container.session().execute(
            sa.insert(AssistantMCPServers).values(
                assistant_id=UUID(setup.assistant_id), mcp_server_id=server_id
            )
        )
    key = await client.post(
        "/api/v1/api-keys",
        headers=setup.headers,
        json={
            "name": "Ärendehjälpens nyckel",
            "key_type": "sk_",
            "permission": "read",
            "scope_type": "assistant",
            "scope_id": setup.assistant_id,
        },
    )
    assert key.status_code == 201, key.text
    secret = key.json()["secret"]
    chat = await _open(client, setup)
    ctx = await _ctx(
        db_container,
        admin_user,
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )

    texts = []
    for tool in (assistant_settings.read_assistant, assistant_settings.read_options):
        offset = 0
        while offset is not None:
            result = await tool(ctx, section="all", offset=offset)
            assert not result.isError, result.content[0].text
            texts.append(result.content[0].text)
            offset = result.structuredContent["next_offset"]
    read = "\n".join(texts)

    assert "Ärendesystemet" in read
    for value in (token, url_key, secret, secret[:12], "cases.example.org"):
        assert value not in read


async def _rows(db_container, chat: dict) -> tuple[int, int, int]:
    async with db_container() as container:
        session = container.session()

        async def count(table, condition) -> int:
            return await session.scalar(
                sa.select(sa.func.count()).select_from(table).where(condition)
            )

        return (
            await count(Assistants, Assistants.id == UUID(chat["assistant_id"])),
            await count(Sessions, Sessions.assistant_id == UUID(chat["assistant_id"])),
            await count(HelperChats, HelperChats.target_id == UUID(chat["target_id"])),
        )


async def test_deleting_the_assistant_removes_the_chats_on_it(
    client, setup: Setup, db_container
):
    chat = await _open(client, setup)
    started = await client.post(
        setup.url + chat["session_id"] + "/conversations/", headers=setup.headers
    )
    assert started.status_code == 200, started.text
    assert await _rows(db_container, chat) == (1, 2, 1)

    deleted = await client.delete(
        f"/api/v1/assistants/{setup.assistant_id}/", headers=setup.headers
    )

    assert deleted.status_code == 204, deleted.text
    assert await _rows(db_container, chat) == (0, 0, 0)


async def test_moving_the_assistant_to_another_space_leaves_its_chats_behind(
    client, setup: Setup, db_container
):
    chat = await _open(client, setup)
    other_space = await client.post(
        "/api/v1/spaces/",
        headers=setup.headers,
        json={"name": f"helper-chat-moved-{uuid4().hex[:8]}"},
    )
    assert other_space.status_code == 201, other_space.text

    moved = await client.post(
        f"/api/v1/assistants/{setup.assistant_id}/transfer/",
        headers=setup.headers,
        json={"target_space_id": other_space.json()["id"]},
    )

    assert moved.status_code == 204, moved.text
    assert await _rows(db_container, chat) == (0, 0, 0)
    reopened = await _open(client, setup)
    assert reopened["assistant_id"] != chat["assistant_id"]
    async with db_container() as container:
        space_id = await container.session().scalar(
            sa.select(Assistants.space_id).where(
                Assistants.id == UUID(reopened["assistant_id"])
            )
        )
    assert str(space_id) == other_space.json()["id"]
