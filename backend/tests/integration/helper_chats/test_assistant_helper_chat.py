"""The helper chat on an assistant: who gets one, who reaches it, what its
tools read, propose and change, and what happens to it when the assistant
goes or moves."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
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
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import AssistantMCPServers, Assistants
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
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


async def test_what_the_person_does_with_their_chat_is_audited_in_their_name(
    client, setup: Setup, admin_user, monkeypatch: pytest.MonkeyPatch
):
    entries: list[dict] = []
    log_async = AuditService.log_async

    async def record(self, **kwargs):
        entries.append(kwargs)
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)

    chat = await _open(client, setup)
    url = setup.url + chat["session_id"] + "/"
    editing = await client.patch(url, headers=setup.headers, json={"editing": True})
    assert editing.status_code == 200, editing.text
    chosen = await client.patch(
        url,
        headers=setup.headers,
        json={"completion_model_id": chat["default_completion_model_id"]},
    )
    assert chosen.status_code == 200, chosen.text
    started = await client.post(url + "conversations/", headers=setup.headers)
    assert started.status_code == 200, started.text

    about_the_chat = [
        entry for entry in entries if entry["action"].value.startswith("helper_chat_")
    ]
    assert [entry["action"] for entry in about_the_chat] == [
        ActionType.HELPER_CHAT_CREATED,
        ActionType.HELPER_CHAT_MODE_CHANGED,
        ActionType.HELPER_CHAT_MODEL_CHANGED,
        ActionType.HELPER_CHAT_CONVERSATION_STARTED,
    ]
    # Each entry is the person's own and names the assistant the chat is about.
    for entry in about_the_chat:
        assert entry["actor_id"] == admin_user.id
        assert entry["entity_type"] == EntityType.ASSISTANT
        assert entry["entity_id"] == UUID(setup.assistant_id)


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
    assert attached == [
        {"assistant": ["propose_changes", "read_assistant", "read_options"]}
    ]


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


async def test_a_turn_in_edit_mode_gets_the_tool_that_changes_the_assistant(
    client, setup: Setup, monkeypatch: pytest.MonkeyPatch
):
    chat = await _open(client, setup)
    await _edit_mode(client, setup, chat)
    attached: list[list[str]] = []

    async def ask(self, question, completion_service, references_service, **kwargs):
        attached.extend(
            sorted(tool.name for tool in server.tools)
            for server in kwargs.get("internal_mcp_servers") or []
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
        json={"question": "Byt namn på assistenten.", "stream": False},
    )

    assert asked.status_code == 200, asked.text
    assert attached == [
        ["propose_changes", "read_assistant", "read_options", "update_assistant"]
    ]


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


# --- Proposing and making changes --------------------------------------------

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_INSTRUCTIONS = "Du är ärendehjälpen.\nSvara sakligt och hänvisa till rutinerna."


async def _edit_mode(client, setup: Setup, chat: dict, headers=None) -> None:
    changed = await client.patch(
        setup.url + chat["session_id"] + "/",
        headers=headers or setup.headers,
        json={"editing": True},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["editing"] is True


async def _saved(client, setup: Setup, values: dict) -> dict:
    saved = await client.post(
        f"/api/v1/assistants/{setup.assistant_id}/", headers=setup.headers, json=values
    )
    assert saved.status_code == 200, saved.text
    return saved.json()


def _settings(assistant: dict) -> dict:
    """What the chat may change, as the assistant endpoint gives it."""
    return {
        "name": assistant["name"],
        "description": assistant["description"],
        "prompt": (assistant["prompt"] or {}).get("text"),
        "knowledge_mode": assistant["knowledge_mode"],
        "inline_file_text": assistant["inline_file_text"],
    }


async def _read(client, setup: Setup) -> dict:
    read = await client.get(
        f"/api/v1/assistants/{setup.assistant_id}/", headers=setup.headers
    )
    assert read.status_code == 200, read.text
    return read.json()


@dataclass(frozen=True)
class Stored:
    """An assistant as the database holds it: its row, its versions of the
    instructions and its audit entries."""

    row: tuple
    prompts: list[tuple]
    audit: list[tuple]


async def _stored(db_container, assistant_id: str) -> Stored:
    target = UUID(assistant_id)
    async with db_container() as container:
        session = container.session()
        row = (
            await session.execute(
                sa.select(
                    Assistants.name,
                    Assistants.description,
                    Assistants.knowledge_mode,
                    Assistants.inline_file_text,
                    Assistants.completion_model_kwargs,
                    Assistants.updated_at,
                ).where(Assistants.id == target)
            )
        ).one()
        prompts = (
            await session.execute(
                sa.select(
                    Prompts.text, Prompts.description, PromptsAssistants.is_selected
                )
                .join(PromptsAssistants, PromptsAssistants.prompt_id == Prompts.id)
                .where(PromptsAssistants.assistant_id == target)
                .order_by(Prompts.created_at)
            )
        ).all()
        audit = (
            await session.execute(
                sa.select(
                    AuditLogTable.action,
                    AuditLogTable.actor_id,
                    AuditLogTable.actor_type,
                    AuditLogTable.log_metadata,
                )
                .where(AuditLogTable.entity_id == target)
                .order_by(AuditLogTable.timestamp)
            )
        ).all()
    return Stored(
        row=tuple(row),
        prompts=[tuple(prompt) for prompt in prompts],
        audit=[tuple(entry) for entry in audit],
    )


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, UUID]]:
    """The audit entries queued for the worker, as (action, entity)."""
    entries: list[tuple[str, UUID]] = []
    log_async = AuditService.log_async

    async def record(self, **kwargs):
        entries.append((kwargs["action"].value, kwargs["entity_id"]))
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)
    return entries


def _updated(queued: list[tuple[str, UUID]], assistant_id: str) -> list:
    return [
        entry
        for entry in queued
        if entry == (ActionType.ASSISTANT_UPDATED.value, UUID(assistant_id))
    ]


async def test_a_change_in_edit_mode_is_saved_and_audited_with_the_person_as_actor(
    client, setup: Setup, db_container, admin_user, queued
):
    before = _settings(
        await _saved(
            client,
            setup,
            {"description": "Hjälper handläggare.", "prompt": {"text": _INSTRUCTIONS}},
        )
    )
    chat = await _open(client, setup)
    await _edit_mode(client, setup, chat)
    ctx = await _ctx(
        db_container,
        admin_user,
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )
    stored = await _stored(db_container, setup.assistant_id)
    queued.clear()
    mode = "inject" if before["knowledge_mode"] == "tool" else "tool"
    new_instructions = "Du är ärendestödet.\nSvara kort, på svenska."

    result = await assistant_settings.update_assistant(
        ctx,
        changes={
            "name": "Ärendestödet",
            "description": None,
            "prompt": {
                "text": new_instructions,
                "description": "Kortare svar, ändrat med hjälpassistenten",
            },
            "knowledge_mode": mode,
            "inline_file_text": not before["inline_file_text"],
        },
    )

    assert not result.isError, result.content[0].text
    content = result.structuredContent
    assert content["target_id"] == setup.assistant_id
    assert content["changes"] == [
        {"field": "name", "before": "Ärendehjälpen", "after": "Ärendestödet"},
        {"field": "description", "before": "Hjälper handläggare.", "after": None},
        {"field": "prompt", "before": _INSTRUCTIONS, "after": new_instructions},
        {"field": "knowledge_mode", "before": before["knowledge_mode"], "after": mode},
        {
            "field": "inline_file_text",
            "before": before["inline_file_text"],
            "after": not before["inline_file_text"],
        },
    ]
    text = result.content[0].text
    assert text.startswith('Saved: name (from "Ärendehjälpen" to "Ärendestödet")')
    assert _UUID.search(text) is None
    for long_text in (_INSTRUCTIONS, new_instructions, "Svara kort"):
        assert long_text not in text

    after = await _read(client, setup)
    assert _settings(after) == {
        "name": "Ärendestödet",
        "description": None,
        "prompt": new_instructions,
        "knowledge_mode": mode,
        "inline_file_text": not before["inline_file_text"],
    }
    saved = await _stored(db_container, setup.assistant_id)
    assert saved.prompts[len(stored.prompts) :] == [
        (new_instructions, "Kortare svar, ändrat med hjälpassistenten", True)
    ]
    # One entry, the one a person's own save writes, saved with the change.
    new_entries = saved.audit[len(stored.audit) :]
    assert [entry[:3] for entry in new_entries] == [
        (ActionType.ASSISTANT_UPDATED.value, admin_user.id, "user")
    ]
    extra = new_entries[0][3]["extra"]
    assert extra["origin"] == "helper_chat"
    assert extra["session_id"] == chat["session_id"]
    assert _updated(queued, setup.assistant_id) == []

    undone = await _saved(client, setup, content["undo"])
    assert _settings(undone) == before


async def test_in_view_mode_a_direct_change_is_refused_and_nothing_is_written(
    client, setup: Setup, db_container, admin_user, queued
):
    chat = await _open(client, setup)
    ctx = await _ctx(
        db_container,
        admin_user,
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )
    stored = await _stored(db_container, setup.assistant_id)
    queued.clear()

    result = await assistant_settings.update_assistant(
        ctx, changes={"name": "Ärendestödet", "prompt": {"text": "Ny text."}}
    )

    assert result.isError
    assert result.content[0].text.startswith("Turn on edit mode")
    assert await _stored(db_container, setup.assistant_id) == stored
    assert _updated(queued, setup.assistant_id) == []


async def test_a_person_who_lost_their_edit_rights_is_refused_a_change(
    client, setup: Setup, db_container, admin_user, queued
):
    await client.post(
        f"/api/v1/assistants/{setup.assistant_id}/publish/",
        headers=setup.headers,
        params={"published": True},
    )
    colleague = await _member_headers(
        db_container, admin_user.tenant_id, setup.space_id, SpaceRoleValue.EDITOR
    )
    chat = await _open(client, replace(setup, headers=colleague))
    await _edit_mode(client, setup, chat, headers=colleague)
    async with db_container() as container:
        person = await container.session().scalar(
            sa.select(Sessions.user_id).where(Sessions.id == UUID(chat["session_id"]))
        )
        email = (await container.user_repo().get_user_by_id(person)).email
        await container.session().execute(
            sa.text(
                "UPDATE spaces_users SET role = :role "
                "WHERE space_id = :space_id AND user_id = :user_id"
            ),
            {
                "role": SpaceRoleValue.VIEWER.value,
                "space_id": setup.space_id,
                "user_id": str(person),
            },
        )
    ctx = await _ctx(
        db_container,
        SimpleNamespace(email=email),
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )
    stored = await _stored(db_container, setup.assistant_id)
    queued.clear()

    result = await assistant_settings.update_assistant(
        ctx, changes={"name": "Ärendestödet"}
    )

    assert result.isError
    assert result.content[0].text == (
        "You do not have permission to edit this assistant."
    )
    assert await _stored(db_container, setup.assistant_id) == stored
    assert _updated(queued, setup.assistant_id) == []


async def test_a_proposal_writes_nothing_and_applying_it_is_the_persons_save(
    client, setup: Setup, db_container, admin_user, queued, monkeypatch
):
    before = _settings(await _saved(client, setup, {"prompt": {"text": _INSTRUCTIONS}}))
    chat = await _open(client, setup)
    ctx = await _ctx(
        db_container,
        admin_user,
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )
    written: list[object] = []
    log = AuditService.log

    async def record(self, **kwargs):
        written.append(kwargs["action"])
        return await log(self, **kwargs)

    monkeypatch.setattr(AuditService, "log", record)
    stored = await _stored(db_container, setup.assistant_id)
    queued.clear()
    new_instructions = "Du är ärendestödet.\nSvara kort."

    result = await assistant_settings.propose_changes(
        ctx,
        changes={
            "name": "Ärendestödet",
            "prompt": {"text": new_instructions, "description": "Kortare svar"},
            "inline_file_text": not before["inline_file_text"],
        },
    )

    assert not result.isError, result.content[0].text
    assert await _stored(db_container, setup.assistant_id) == stored
    assert queued == [] and written == []
    content = result.structuredContent
    assert content["target_id"] == setup.assistant_id
    assert content["proposal"] == {
        "changes": [
            {"field": "name", "before": "Ärendehjälpen", "after": "Ärendestödet"},
            {"field": "prompt", "before": _INSTRUCTIONS, "after": new_instructions},
            {
                "field": "inline_file_text",
                "before": before["inline_file_text"],
                "after": not before["inline_file_text"],
            },
        ],
        "update": {
            "name": "Ärendestödet",
            "prompt": {"text": new_instructions, "description": "Kortare svar"},
            "inline_file_text": not before["inline_file_text"],
        },
    }
    text = result.content[0].text
    assert text.startswith("Proposed, nothing saved:")
    assert _UUID.search(text) is None and "Svara kort" not in text

    applied = await _saved(client, setup, content["proposal"]["update"])
    assert _settings(applied) == {
        **before,
        "name": "Ärendestödet",
        "prompt": new_instructions,
        "inline_file_text": not before["inline_file_text"],
    }
    assert applied["prompt"]["description"] == "Kortare svar"


async def test_a_change_the_space_cannot_take_is_refused_without_naming_it(
    client, setup: Setup, db_container, admin_user
):
    chat = await _open(client, setup)
    await _edit_mode(client, setup, chat)
    ctx = await _ctx(
        db_container,
        admin_user,
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )
    stored = await _stored(db_container, setup.assistant_id)
    stranger = str(uuid4())

    for tool in (
        assistant_settings.propose_changes,
        assistant_settings.update_assistant,
    ):
        result = await tool(ctx, changes={"completion_model": {"id": stranger}})

        assert result.isError
        assert "does not offer that model" in result.content[0].text
        assert _UUID.search(result.content[0].text) is None
    assert await _stored(db_container, setup.assistant_id) == stored


async def test_instructions_a_policy_sets_are_neither_changed_nor_proposed(
    client, setup: Setup, db_container, admin_user
):
    entry = await client.post(
        "/api/v1/admin/prompt-library/",
        headers=setup.headers,
        json={"name": "Organisationens chatt", "text": "Svara enligt policyn."},
    )
    assert entry.status_code == 201, entry.text
    policy = await client.put(
        "/api/v1/admin/governance-policy/",
        headers=setup.headers,
        json={
            "prompt_enforcement": {
                "enabled": True,
                "prompt_library_id": entry.json()["id"],
            }
        },
    )
    assert policy.status_code == 200, policy.text
    async with db_container() as container:
        personal = await container.space_init_service().get_personal_space()
        assert personal.default_assistant is not None
        default_id = str(personal.default_assistant.id)
    governed = Setup(
        headers=setup.headers,
        space_id=str(personal.id),
        assistant_id=default_id,
        url=f"/api/v1/assistants/{default_id}/helper-chat/",
    )
    chat = await _open(client, governed)
    await _edit_mode(client, governed, chat)
    ctx = await _ctx(
        db_container,
        admin_user,
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )
    stored = await _stored(db_container, default_id)

    for tool in (
        assistant_settings.propose_changes,
        assistant_settings.update_assistant,
    ):
        result = await tool(ctx, changes={"prompt": {"text": "Egna instruktioner."}})

        assert result.isError
        assert result.content[0].text.startswith(
            "An organisation policy sets the instructions for this assistant"
        )
    assert await _stored(db_container, default_id) == stored
