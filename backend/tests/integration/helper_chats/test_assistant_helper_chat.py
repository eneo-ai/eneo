"""The helper chat on an assistant: who gets one, who reaches it, what its
tools read, propose and change, and what happens to it when the assistant
goes or moves."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
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
from eneo.database.tables.capabilities_table import SpaceCapabilities
from eneo.database.tables.document_templates_table import DocumentTemplates
from eneo.database.tables.helper_chats_table import HelperChats
from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    SpacesMCPServers,
)
from eneo.database.tables.prompts_table import Prompts, PromptsAssistants
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.websites_table import Websites
from eneo.helper_chats.personas.assistant import ASSISTANT_INSTRUCTIONS
from eneo.helper_chats.personas.shared import PROPOSING
from eneo.internal_mcp import assistant_settings
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.services.service import DatastoreResult
from eneo.sessions.session import SessionAdd
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


# The tools every turn of the chat gets, whatever its row holds: the reads,
# the proposal and publishing, never a direct change.
_TURN_TOOLS = [
    "propose_changes",
    "publish_assistant",
    "read_assistant",
    "read_options",
    "read_prompt_history",
]


async def test_a_chat_is_opened_once_with_the_assistants_persona_and_no_mode(
    client, setup: Setup, db_container
):
    available = await client.get(setup.url + "availability", headers=setup.headers)
    assert available.status_code == 200, available.text
    assert available.json() == {"available": True, "reason": None}

    chat = await _open(client, setup)

    assert chat == await _open(client, setup)
    assert chat["target_id"] == setup.assistant_id
    assert chat["assistant_id"] != setup.assistant_id
    assert "editing" not in chat
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


async def test_the_person_changes_model_and_conversation_of_their_chat_but_no_mode(
    client, setup: Setup, db_container
):
    chat = await _open(client, setup)
    url = setup.url + chat["session_id"] + "/"

    # A request that names a mode is not one the chat takes.
    for editing in (True, False):
        mode = await client.patch(url, headers=setup.headers, json={"editing": editing})
        assert mode.status_code == 422, mode.text
    async with db_container() as container:
        stored = await container.session().scalar(
            sa.select(HelperChats.editing).where(
                HelperChats.session_id == UUID(chat["session_id"])
            )
        )
    assert stored is False

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
        "change": await client.patch(
            url, headers=headers, json={"completion_model_id": None}
        ),
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


# --- Fresh starts and earlier conversations ---------------------------------


async def _ask_in(
    db_container,
    tenant_id: UUID,
    *,
    session_id: str,
    assistant_id: str,
    question: str,
    age: timedelta = timedelta(0),
) -> None:
    """A question in the conversation, asked ``age`` ago."""
    async with db_container() as container:
        await container.session().execute(
            sa.insert(Questions).values(
                question=question,
                answer="Svar.",
                num_tokens_question=4,
                num_tokens_answer=1,
                session_id=UUID(session_id),
                tenant_id=tenant_id,
                assistant_id=UUID(assistant_id),
                created_at=datetime.now(timezone.utc) - age,
            )
        )


async def _open_fresh(client, setup: Setup, headers=None) -> dict:
    opened = await client.post(
        setup.url,
        headers=headers or setup.headers,
        params={"fresh_start": True},
    )
    assert opened.status_code == 200, opened.text
    return opened.json()


def _answer_without_a_model(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ask(self, question, completion_service, references_service, **kwargs):
        model = kwargs.get("completion_model_override") or self.completion_model
        return (
            CompletionModelResponse(
                completion=Completion(text="Svar."), model=model, total_token_count=1
            ),
            DatastoreResult(chunks=[], no_duplicate_chunks=[], info_blobs=[]),
        )

    monkeypatch.setattr(Assistant, "ask", ask)


async def test_a_fresh_opening_leaves_a_conversation_with_a_question_for_a_new_one(
    client, setup: Setup, db_container, admin_user, monkeypatch: pytest.MonkeyPatch
):
    chat = await _open(client, setup)
    # An empty conversation is kept, however often the chat is opened afresh.
    assert (await _open_fresh(client, setup))["session_id"] == chat["session_id"]
    chosen = await client.patch(
        setup.url + chat["session_id"] + "/",
        headers=setup.headers,
        json={"completion_model_id": chat["default_completion_model_id"]},
    )
    assert chosen.status_code == 200, chosen.text
    await _ask_in(
        db_container,
        admin_user.tenant_id,
        session_id=chat["session_id"],
        assistant_id=chat["assistant_id"],
        question="Vad gör assistenten?",
    )
    entries: list[dict] = []
    log_async = AuditService.log_async

    async def record(self, **kwargs):
        entries.append(kwargs)
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)

    fresh = await _open_fresh(client, setup)

    assert fresh["session_id"] != chat["session_id"]
    assert fresh["assistant_id"] == chat["assistant_id"]
    assert fresh["completion_model_id"] == chat["default_completion_model_id"]
    assert [entry["action"] for entry in entries] == [
        ActionType.HELPER_CHAT_CONVERSATION_STARTED
    ]
    assert entries[0]["metadata"]["extra"] == {
        "session_id": fresh["session_id"],
        "previous_session_id": chat["session_id"],
        "reason": "fresh_start",
    }
    # The new conversation is empty, so opening afresh again keeps it, and
    # an opening without a fresh start resumes it.
    assert (await _open_fresh(client, setup))["session_id"] == fresh["session_id"]
    assert (await _open(client, setup))["session_id"] == fresh["session_id"]

    _answer_without_a_model(monkeypatch)
    turn = f"/api/v1/assistants/{chat['assistant_id']}/sessions/"
    earlier = await client.post(
        turn + chat["session_id"] + "/",
        headers=setup.headers,
        json={"question": "Fortsätt.", "stream": False},
    )
    current = await client.post(
        turn + fresh["session_id"] + "/",
        headers=setup.headers,
        json={"question": "Börja om.", "stream": False},
    )
    assert earlier.status_code == 404, earlier.text
    assert current.status_code == 200, current.text
    async with db_container() as container:
        kept = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(Questions)
            .where(Questions.session_id == UUID(chat["session_id"]))
        )
    assert kept == 1


async def test_the_person_lists_their_conversations_that_hold_a_question(
    client, setup: Setup, db_container, admin_user
):
    chat = await _open(client, setup)
    long_question = "Hjälp mig skriva\n  @[Instruktioner](setting:prompt). " + (
        "Mer text. " * 40
    )
    await _ask_in(
        db_container,
        admin_user.tenant_id,
        session_id=chat["session_id"],
        assistant_id=chat["assistant_id"],
        question=long_question,
        age=timedelta(hours=2),
    )
    await _ask_in(
        db_container,
        admin_user.tenant_id,
        session_id=chat["session_id"],
        assistant_id=chat["assistant_id"],
        question="En följdfråga.",
        age=timedelta(hours=1),
    )
    second = await _open_fresh(client, setup)
    await _ask_in(
        db_container,
        admin_user.tenant_id,
        session_id=second["session_id"],
        assistant_id=second["assistant_id"],
        question="Vilken modell passar?",
    )
    # The person's own conversation with the assistant itself is not the chat's.
    async with db_container() as container:
        own = await container.session_repo().add(
            SessionAdd(
                name="Egen",
                user_id=admin_user.id,
                assistant_id=UUID(setup.assistant_id),
            )
        )
    await _ask_in(
        db_container,
        admin_user.tenant_id,
        session_id=str(own.id),
        assistant_id=setup.assistant_id,
        question="Hej assistenten.",
    )

    listed = await client.get(setup.url + "conversations/", headers=setup.headers)

    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert [(item["session_id"], item["current"]) for item in items] == [
        (second["session_id"], True),
        (chat["session_id"], False),
    ]
    assert items[0]["title"] == "Vilken modell passar?"
    title = items[1]["title"]
    assert title.startswith("Hjälp mig skriva @[Instruktioner](setting:prompt). Mer")
    assert len(title) <= 200
    # Its last question is the follow-up, asked an hour ago.
    last_asked = datetime.fromisoformat(items[1]["last_asked_at"])
    hours_ago = (datetime.now(timezone.utc) - last_asked) / timedelta(hours=1)
    assert 0.5 < hours_ago < 1.5

    # A fresh opening leaves the empty conversation out of the list.
    third = await _open_fresh(client, setup)
    again = (
        await client.get(setup.url + "conversations/", headers=setup.headers)
    ).json()["items"]
    assert third["session_id"] not in {item["session_id"] for item in again}
    assert [item["current"] for item in again] == [False, False]


async def test_an_earlier_conversation_is_read_and_listed_by_its_person_alone(
    client, setup: Setup, db_container, admin_user, other_tenant_headers
):
    chat = await _open(client, setup)
    await _ask_in(
        db_container,
        admin_user.tenant_id,
        session_id=chat["session_id"],
        assistant_id=chat["assistant_id"],
        question="Vad heter assistenten?",
    )
    await _open_fresh(client, setup)
    conversation = f"/api/v1/conversations/{chat['session_id']}/"

    read = await client.get(conversation, headers=setup.headers)

    assert read.status_code == 200, read.text
    assert [message["question"] for message in read.json()["messages"]] == [
        "Vad heter assistenten?"
    ]
    colleague = await _member_headers(
        db_container, admin_user.tenant_id, setup.space_id, SpaceRoleValue.ADMIN
    )
    refused = {
        who: await client.get(conversation, headers=headers)
        for who, headers in [("colleague", colleague), ("other", other_tenant_headers)]
    }
    assert {who: response.status_code for who, response in refused.items()} == {
        "colleague": 403,
        "other": 403,
    }, {who: response.text for who, response in refused.items()}
    assert "Vad heter" not in "".join(response.text for response in refused.values())
    # Without a chat of their own the colleague has no list; with one, it
    # holds none of the person's conversations.
    no_chat = await client.get(setup.url + "conversations/", headers=colleague)
    assert no_chat.status_code == 404, no_chat.text
    await _open(client, replace(setup, headers=colleague))
    their_list = await client.get(setup.url + "conversations/", headers=colleague)
    assert their_list.status_code == 200, their_list.text
    assert their_list.json()["items"] == []
    other_tenant = await client.get(
        setup.url + "conversations/", headers=other_tenant_headers
    )
    assert other_tenant.status_code == 403, other_tenant.text


async def test_the_list_answers_like_the_opening_for_someone_who_may_not_edit(
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

    listed = await client.get(setup.url + "conversations/", headers=viewer)
    opened = await client.post(setup.url, headers=viewer)

    assert _body(listed) == _body(opened)
    assert listed.json()["code"] == "helper_chat_no_edit_rights"


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
    assert attached == [{"assistant": _TURN_TOOLS}]


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


async def _left_in_edit_mode(db_container, chat: dict, tenant_id: UUID) -> None:
    """The chat's row in edit mode, its last question and mode change long
    past the pause."""
    long_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    async with db_container() as container:
        session = container.session()
        model_id = await session.scalar(
            sa.select(Assistants.completion_model_id).where(
                Assistants.id == UUID(chat["assistant_id"])
            )
        )
        await session.execute(
            sa.insert(Questions).values(
                question="Byt namn på assistenten.",
                answer="Klart.",
                num_tokens_question=4,
                num_tokens_answer=1,
                session_id=UUID(chat["session_id"]),
                tenant_id=tenant_id,
                assistant_id=UUID(chat["assistant_id"]),
                completion_model_id=model_id,
                created_at=long_ago,
            )
        )
        await session.execute(
            sa.update(HelperChats)
            .where(HelperChats.session_id == UUID(chat["session_id"]))
            .values(editing=True, mode_changed_at=long_ago)
        )


async def test_a_chat_whose_row_holds_edit_mode_is_one_like_any_other(
    client, setup: Setup, db_container, admin_user, monkeypatch: pytest.MonkeyPatch
):
    chat = await _open(client, setup)
    await _left_in_edit_mode(db_container, chat, admin_user.tenant_id)
    audited: list[ActionType] = []
    log_async = AuditService.log_async

    async def record(self, **kwargs):
        audited.append(kwargs["action"])
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)
    turns: list[tuple[str, list[str]]] = []

    async def ask(self, question, completion_service, references_service, **kwargs):
        turns.extend(
            (kwargs.get("prompt_addendum") or "", sorted(t.name for t in server.tools))
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

    opened = await _open(client, setup)
    asked = await client.post(
        f"/api/v1/assistants/{chat['assistant_id']}/sessions/{chat['session_id']}/",
        headers=setup.headers,
        json={"question": "Byt namn på assistenten.", "stream": False},
    )

    assert "editing" not in opened
    assert opened["session_id"] == chat["session_id"]
    assert asked.status_code == 200, asked.text
    assert turns == [(PROPOSING, _TURN_TOOLS)]
    # The pause leaves the row alone: there is no mode to leave.
    assert not [action for action in audited if action.value.endswith("mode_changed")]
    async with db_container() as container:
        stored = await container.session().scalar(
            sa.select(HelperChats.editing).where(
                HelperChats.session_id == UUID(chat["session_id"])
            )
        )
    assert stored is True


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


# --- Proposing changes -------------------------------------------------------

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_INSTRUCTIONS = "Du är ärendehjälpen.\nSvara sakligt och hänvisa till rutinerna."


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


async def test_a_person_who_lost_their_edit_rights_is_refused_a_proposal(
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

    result = await assistant_settings.propose_changes(
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
    ctx = await _ctx(
        db_container,
        admin_user,
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )
    stored = await _stored(db_container, setup.assistant_id)
    stranger = str(uuid4())

    result = await assistant_settings.propose_changes(
        ctx, changes={"completion_model": {"id": stranger}}
    )

    assert result.isError
    assert "does not offer that model" in result.content[0].text
    assert _UUID.search(result.content[0].text) is None
    assert await _stored(db_container, setup.assistant_id) == stored


async def test_instructions_a_policy_sets_are_not_proposed(
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
    ctx = await _ctx(
        db_container,
        admin_user,
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )
    stored = await _stored(db_container, default_id)

    result = await assistant_settings.propose_changes(
        ctx, changes={"prompt": {"text": "Egna instruktioner."}}
    )

    assert result.isError
    assert result.content[0].text.startswith(
        "An organisation policy sets the instructions for this assistant"
    )
    assert await _stored(db_container, default_id) == stored


# --- Knowledge, tools, functions, ranking, template, retention, insights ------


@dataclass(frozen=True)
class Offered:
    """What the space offers beyond what a new space has, and the secrets
    its server and website hold."""

    groups: tuple[str, str]
    website_id: str
    server_id: str
    tools: dict[str, str]
    ranker_id: str
    template_id: str
    secrets: tuple[str, ...]


@pytest.fixture
async def offered(
    client, setup: Setup, db_container, admin_user, rerank_model_factory
) -> Offered:
    """Two collections, a website with a password in its address, an MCP
    server with a sign-in token and two tools, a ready web search provider
    the space offers, a result ranking model and a document template."""
    groups: list[str] = []
    embedding_model_id = None
    for name in ("Rutiner", "Gamla rutiner"):
        created = await client.post(
            f"/api/v1/spaces/{setup.space_id}/knowledge/groups/",
            headers=setup.headers,
            json={"name": name},
        )
        assert created.status_code == 201, created.text
        groups.append(created.json()["id"])
        embedding_model_id = created.json()["embedding_model"]["id"]
    token, url_key = f"tok-{uuid4().hex}", f"key-{uuid4().hex}"
    password = f"pw-{uuid4().hex}"
    async with db_container() as container:
        session = container.session()
        website = Websites(
            name="Intranätet",
            url=f"https://reader:{password}@intra.example.org/docs",
            download_files=False,
            crawl_type="crawl",
            update_interval="never",
            size=0,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=UUID(embedding_model_id),
            space_id=UUID(setup.space_id),
        )
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name="Ärendesystemet",
            description="Läser ärenden.",
            http_url=f"https://cases.example.org/mcp?key={url_key}",
            http_auth_type="bearer",
            http_auth_config_schema={"token": token},
            is_enabled=True,
        )
        search = MCPServers(
            tenant_id=admin_user.tenant_id,
            name="Webbsökningen",
            purpose="web_search",
            http_url="https://search.example.org/mcp",
            http_auth_type="none",
            is_enabled=True,
        )
        session.add_all([website, server, search])
        await session.flush()
        tools = {
            name: MCPServerTools(
                mcp_server_id=row.id,
                name=name,
                description=name,
                input_schema={"type": "object"},
                is_enabled_by_default=True,
                requires_approval=False,
                removed_from_remote=False,
            )
            for row, name in (
                (server, "search_cases"),
                (server, "create_case"),
                (search, "search"),
            )
        }
        session.add_all(tools.values())
        session.add(
            SpacesMCPServers(space_id=UUID(setup.space_id), mcp_server_id=server.id)
        )
        await session.execute(
            sa.delete(SpaceCapabilities).where(
                SpaceCapabilities.space_id == UUID(setup.space_id)
            )
        )
        session.add(
            SpaceCapabilities(space_id=UUID(setup.space_id), purpose="web_search")
        )
        template = DocumentTemplates(
            tenant_id=admin_user.tenant_id,
            name="Kommunmall",
            filename="kommunmall.docx",
            content=b"docx",
            sha256="0" * 64,
            size_bytes=4,
            syntax="none",
            placeholders=[],
            checks={},
            status="ready",
            is_default=False,
        )
        session.add(template)
        ranker = await rerank_model_factory(session, "Rankaren")
        await session.flush()
        offered = Offered(
            groups=(groups[0], groups[1]),
            website_id=str(website.id),
            server_id=str(server.id),
            tools={name: str(tool.id) for name, tool in tools.items()},
            ranker_id=str(ranker.id),
            template_id=str(template.id),
            secrets=(token, url_key, password, "cases.example.org", "reader"),
        )
    return offered


def _added_settings(assistant: dict) -> dict:
    """The settings beside the base ones, as the assistant endpoint gives
    them."""
    return {
        "groups": sorted(item["id"] for item in assistant["groups"]),
        "websites": sorted(item["id"] for item in assistant["websites"]),
        "mcp_servers": sorted(item["id"] for item in assistant["mcp_servers"]),
        "mcp_tools": sorted(
            (item["tool_id"], item["is_enabled"]) for item in assistant["mcp_tools"]
        ),
        "enabled_capabilities": sorted(assistant["enabled_capabilities"]),
        "rerank_model_id": assistant["rerank_model_id"],
        "document_template": assistant["document_template"],
        "data_retention_days": assistant["data_retention_days"],
        "insight_enabled": assistant["insight_enabled"],
    }


def _every_added_setting(offered: Offered, insight_enabled: bool) -> dict:
    return {
        "groups": {"add": [{"id": offered.groups[0]}, {"id": offered.groups[1]}]},
        "websites": {"add": [{"id": offered.website_id}]},
        "mcp_servers": {"add": [{"id": offered.server_id}]},
        "mcp_tools": {
            "add": [{"tool_id": offered.tools["create_case"], "is_enabled": False}]
        },
        "enabled_capabilities": {"add": ["web_search"]},
        "rerank_model_id": offered.ranker_id,
        "document_template": {"mode": "selected", "template_id": offered.template_id},
        "data_retention_days": 30,
        "insight_enabled": insight_enabled,
    }


def _expected(before: dict, offered: Offered, insight_enabled: bool) -> dict:
    return {
        "groups": sorted(offered.groups),
        "websites": [offered.website_id],
        "mcp_servers": sorted({*before["mcp_servers"], offered.server_id}),
        "mcp_tools": [(offered.tools["create_case"], False)],
        "enabled_capabilities": sorted({*before["enabled_capabilities"], "web_search"}),
        "rerank_model_id": offered.ranker_id,
        "document_template": {"mode": "selected", "template_id": offered.template_id},
        "data_retention_days": 30,
        "insight_enabled": insight_enabled,
    }


def _holds_no_secret(result, offered: Offered) -> None:
    told = result.content[0].text + json.dumps(result.structuredContent)
    for secret in offered.secrets:
        assert secret not in told


async def _knowledge_and_a_server(
    client, setup: Setup, db_container, admin_user, offered: Offered
) -> str:
    """Give the assistant the first collection and another MCP server the
    space offers, so it has both knowledge and an MCP server, which the
    editor keeps changeable on both sides; returns the server's id."""
    async with db_container() as container:
        server_id = await container.session().scalar(
            sa.insert(MCPServers)
            .values(
                tenant_id=admin_user.tenant_id,
                name="Diariet",
                http_url="https://archive.example.org/mcp",
                http_auth_type="none",
                is_enabled=True,
            )
            .returning(MCPServers.id)
        )
        await container.session().execute(
            sa.insert(SpacesMCPServers).values(
                space_id=UUID(setup.space_id), mcp_server_id=server_id
            )
        )
    await _saved(
        client,
        setup,
        {
            "groups": [{"id": offered.groups[0]}],
            "mcp_servers": [{"id": str(server_id)}],
        },
    )
    return str(server_id)


async def test_the_added_settings_are_proposed_without_a_write_and_applied_as_a_save(
    client, setup: Setup, db_container, admin_user, offered: Offered, queued
):
    # Knowledge and MCP servers are added in one change only to an assistant
    # that has both already.
    await _knowledge_and_a_server(client, setup, db_container, admin_user, offered)
    before = _added_settings(await _read(client, setup))
    insight = not before["insight_enabled"]
    chat = await _open(client, setup)
    ctx = await _ctx(
        db_container,
        admin_user,
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )
    stored = await _stored(db_container, setup.assistant_id)
    queued.clear()

    result = await assistant_settings.propose_changes(
        ctx, changes=_every_added_setting(offered, insight)
    )

    assert not result.isError, result.content[0].text
    assert await _stored(db_container, setup.assistant_id) == stored
    assert _added_settings(await _read(client, setup)) == before
    assert queued == []
    _holds_no_secret(result, offered)
    assert _UUID.search(result.content[0].text) is None
    proposal = result.structuredContent["proposal"]
    assert {change["field"] for change in proposal["changes"]} == {
        "groups",
        "websites",
        "rerank_model_id",
        "mcp_servers",
        "mcp_tools",
        "enabled_capabilities",
        "document_template",
        "data_retention_days",
        "insight_enabled",
    }
    tools = next(
        change for change in proposal["changes"] if change["field"] == "mcp_tools"
    )
    assert tools["after"] == [
        {"id": offered.tools["create_case"], "name": "create_case", "is_enabled": False}
    ]

    applied = await _saved(client, setup, proposal["update"])
    assert _added_settings(applied) == _expected(before, offered, insight)


async def test_what_the_space_does_not_offer_is_refused_by_the_proposal(
    client, setup: Setup, db_container, admin_user, offered: Offered
):
    async with db_container() as container:
        outside = await container.session().scalar(
            sa.insert(MCPServers)
            .values(
                tenant_id=admin_user.tenant_id,
                name="Utanför",
                http_url="https://outside.example.org/mcp",
                http_auth_type="none",
                is_enabled=True,
            )
            .returning(MCPServers.id)
        )
        await container.session().execute(
            sa.delete(SpaceCapabilities).where(
                SpaceCapabilities.space_id == UUID(setup.space_id)
            )
        )
    chat = await _open(client, setup)
    ctx = await _ctx(
        db_container,
        admin_user,
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )
    stored = await _stored(db_container, setup.assistant_id)
    stranger = str(uuid4())

    for changes, refusal in (
        ({"groups": {"add": [{"id": stranger}]}}, "does not offer that collection"),
        ({"mcp_servers": {"add": [{"id": str(outside)}]}}, "that MCP server"),
        (
            {
                "mcp_tools": {
                    "add": [{"tool_id": offered.tools["search"], "is_enabled": False}]
                }
            },
            "not a tool of the assistant's MCP servers",
        ),
        ({"enabled_capabilities": {"add": ["web_search"]}}, "not offer web search"),
        ({"rerank_model_id": stranger}, "cannot use that result ranking model"),
        (
            {"document_template": {"mode": "selected", "template_id": stranger}},
            "no such document template",
        ),
    ):
        result = await assistant_settings.propose_changes(ctx, changes=changes)

        assert result.isError, changes
        assert refusal in result.content[0].text
        assert _UUID.search(result.content[0].text) is None
    assert await _stored(db_container, setup.assistant_id) == stored


async def test_the_editors_rules_are_named_and_refused_by_the_proposal(
    client, setup: Setup, db_container, admin_user, offered: Offered, queued
):
    await _saved(client, setup, {"groups": [{"id": offered.groups[0]}]})
    chat = await _open(client, setup)
    ctx = await _ctx(
        db_container,
        admin_user,
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )
    before = await _read(client, setup)
    stored = await _stored(db_container, setup.assistant_id)
    queued.clear()
    propose = assistant_settings.propose_changes

    read = await assistant_settings.read_assistant(ctx)
    assert not read.isError, read.content[0].text
    assert (
        "- MCP servers: none can be added while the assistant has knowledge"
        in read.content[0].text
    )
    add_server = {"mcp_servers": {"add": [{"id": offered.server_id}]}}
    result = await propose(ctx, changes=add_server)
    assert result.isError
    assert result.content[0].text.startswith(
        "Knowledge and MCP servers are not combined on one assistant, and this "
        "one has knowledge, so no MCP server can be added to it."
    )
    # Knowledge that goes in the same change makes way for the server.
    swapped = await propose(ctx, changes={**add_server, "groups": []})
    assert not swapped.isError, swapped.content[0].text
    assert swapped.structuredContent["proposal"]["update"] == {
        "groups": [],
        "mcp_servers": [{"id": offered.server_id}],
    }

    # The model the assistant answers with stops calling tools.
    async with db_container() as container:
        await container.session().execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == UUID(before["completion_model"]["id"]))
            .values(supports_tool_calling=False)
        )
    read = await assistant_settings.read_assistant(ctx, section="tools")
    assert (
        "cannot use tools, so no MCP server or function can be turned on"
        in read.content[0].text
    )
    result = await propose(
        ctx, changes={"enabled_capabilities": {"add": ["web_search"]}}
    )
    assert result.isError
    assert "cannot use tools, so web search cannot be switched on" in (
        result.content[0].text
    )

    assert await _stored(db_container, setup.assistant_id) == stored
    assert _added_settings(await _read(client, setup)) == _added_settings(before)
    assert queued == []


async def _person_ctx(db_container, chat: dict) -> SimpleNamespace:
    """The tool context of the person whose chat ``chat`` is."""
    async with db_container() as container:
        person = await container.session().scalar(
            sa.select(Sessions.user_id).where(Sessions.id == UUID(chat["session_id"]))
        )
        email = (await container.user_repo().get_user_by_id(person)).email
    return await _ctx(
        db_container,
        SimpleNamespace(email=email),
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )


async def test_what_an_editors_role_withholds_is_named_and_refused_by_the_proposal(
    client, setup: Setup, db_container, admin_user, queued
):
    colleague = await _member_headers(
        db_container, admin_user.tenant_id, setup.space_id, SpaceRoleValue.EDITOR
    )
    chat = await _open(client, replace(setup, headers=colleague))
    ctx = await _person_ctx(db_container, chat)
    before = await _read(client, setup)
    stored = await _stored(db_container, setup.assistant_id)
    queued.clear()

    read = await assistant_settings.read_assistant(ctx)
    assert not read.isError, read.content[0].text
    text = read.content[0].text
    assert "Not the person's to change (their role does not allow it):" in text
    others = "someone with more rights in the space, such as its administrators, can"
    assert f"- conversation retention: {others}" in text
    assert f"- insights (turning them on or off): {others}" in text
    # An editor publishes assistants in a shared space.
    assert "- publishing" not in text

    for changes, what in (
        ({"data_retention_days": 30}, "how long conversations are kept"),
        (
            {"insight_enabled": not before["insight_enabled"]},
            "whether insights are on",
        ),
    ):
        result = await assistant_settings.propose_changes(ctx, changes=changes)

        assert result.isError
        assert result.content[0].text.startswith(
            f"The person's role does not let them change {what}; {others}."
        )

    assert await _stored(db_container, setup.assistant_id) == stored
    after = await _read(client, setup)
    assert (after["data_retention_days"], after["insight_enabled"]) == (
        before["data_retention_days"],
        before["insight_enabled"],
    )
    assert queued == []


async def test_publishing_and_insights_are_refused_in_a_personal_space(
    client, setup: Setup, db_container, admin_user, queued
):
    async with db_container() as container:
        personal = await container.space_init_service().get_personal_space()
    created = await client.post(
        "/api/v1/assistants/",
        headers=setup.headers,
        json={"name": "Min egen", "space_id": str(personal.id)},
    )
    assert created.status_code == 200, created.text
    own = Setup(
        headers=setup.headers,
        space_id=str(personal.id),
        assistant_id=created.json()["id"],
        url=f"/api/v1/assistants/{created.json()['id']}/helper-chat/",
    )
    chat = await _open(client, own)
    ctx = await _ctx(
        db_container,
        admin_user,
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )
    before = await _read(client, own)
    stored = await _stored(db_container, own.assistant_id)
    queued.clear()

    read = await assistant_settings.read_assistant(ctx, section="access")
    text = read.content[0].text
    assert "- insights (turning them on or off): not used in a personal space" in text
    assert (
        "- publishing (publishing or unpublishing it): not used in a personal space"
        in (text)
    )
    assert "- conversation retention" not in text

    published = await assistant_settings.publish_assistant(ctx, published=True)
    assert published.isError
    assert published.content[0].text == (
        "An assistant in a personal space is not published. Nothing was changed."
    )
    result = await assistant_settings.propose_changes(
        ctx, changes={"insight_enabled": not before["insight_enabled"]}
    )
    assert result.isError
    assert result.content[0].text == (
        "Insights are not used for an assistant in a personal space. "
        "Nothing was changed."
    )

    assert await _stored(db_container, own.assistant_id) == stored
    after = await _read(client, own)
    assert (after["published"], after["insight_enabled"]) == (
        before["published"],
        before["insight_enabled"],
    )
    assert queued == []


async def test_publishing_from_the_chat_is_audited_as_the_person(
    client, setup: Setup, db_container, admin_user, queued
):
    chat = await _open(client, setup)
    ctx = await _ctx(
        db_container,
        admin_user,
        assistant_id=chat["assistant_id"],
        session_id=chat["session_id"],
    )
    assert (await _read(client, setup))["published"] is False
    stored = await _stored(db_container, setup.assistant_id)
    queued.clear()

    result = await assistant_settings.publish_assistant(ctx, published=True)

    assert not result.isError, result.content[0].text
    assert result.structuredContent == {
        "target_id": setup.assistant_id,
        "changes": [{"field": "published", "before": False, "after": True}],
        "undo": None,
    }
    assert (await _read(client, setup))["published"] is True
    new_entries = (await _stored(db_container, setup.assistant_id)).audit[
        len(stored.audit) :
    ]
    assert [entry[:3] for entry in new_entries] == [
        (ActionType.ASSISTANT_PUBLISHED.value, admin_user.id, "user")
    ]
    assert new_entries[0][3]["extra"] == {
        "published": True,
        "action": "published",
        "origin": "helper_chat",
        "session_id": chat["session_id"],
    }
    assert queued == []

    again = await assistant_settings.publish_assistant(ctx, published=True)
    assert again.isError
    assert again.content[0].text == (
        "The assistant is already published. Nothing was changed."
    )


async def test_a_person_who_lost_their_edit_rights_is_refused_unpublishing(
    client, setup: Setup, db_container, admin_user, queued
):
    # Published, so the person still reads the assistant once they view only.
    await client.post(
        f"/api/v1/assistants/{setup.assistant_id}/publish/",
        headers=setup.headers,
        params={"published": True},
    )
    colleague = await _member_headers(
        db_container, admin_user.tenant_id, setup.space_id, SpaceRoleValue.EDITOR
    )
    chat = await _open(client, replace(setup, headers=colleague))
    ctx = await _person_ctx(db_container, chat)
    async with db_container() as container:
        person = await container.session().scalar(
            sa.select(Sessions.user_id).where(Sessions.id == UUID(chat["session_id"]))
        )
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
    stored = await _stored(db_container, setup.assistant_id)
    queued.clear()

    result = await assistant_settings.publish_assistant(ctx, published=False)

    assert result.isError
    assert result.content[0].text == (
        "You do not have permission to edit this assistant."
    )
    assert await _stored(db_container, setup.assistant_id) == stored
    assert (await _read(client, setup))["published"] is True
    assert queued == []
