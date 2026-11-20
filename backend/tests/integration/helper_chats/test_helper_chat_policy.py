"""The organisation's settings for the helper chat on assistants: who reads and
changes them, what a change is audited as, and what the switch and the
guidance do to the chats."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.assistants.assistant import Assistant
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.prompts_table import Prompts, PromptsAssistants
from eneo.helper_chats.personas.assistant import ASSISTANT_INSTRUCTIONS
from eneo.helper_chats.personas.organisation_guidance import (
    ORGANISATION_GUIDANCE_INTRODUCTION,
)
from eneo.internal_mcp import assistant_settings
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserAdd, UserState
from tests.integration.helper_chats.conftest import Setup, loopback_ctx, open_chat

_POLICY_URL = "/api/v1/settings/helper-chat-policy"
_DEFAULTS = {
    "enabled": True,
    "guidance": "",
    "guidance_max_length": 4000,
    "completion_model_id": None,
}


@pytest.fixture
async def member_headers(db_container, admin_user) -> dict[str, str]:
    """A person of the same organisation who is not an administrator."""
    async with db_container() as container:
        suffix = uuid4().hex[:8]
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"helper-chat-policy-member-{suffix}",
                permissions=[Permission.ASSISTANTS],
                tenant_id=admin_user.tenant_id,
            )
        )
        user = await container.user_repo().add(
            UserAdd(
                email=f"helper-chat-policy-member-{suffix}@example.com",
                username=f"helper_chat_policy_member_{suffix}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
        token = container.auth_service().create_access_token_for_user(user)
    return {"Authorization": f"Bearer {token}"}


async def _patch(client, headers: dict[str, str], body: dict) -> dict:
    saved = await client.patch(_POLICY_URL, headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    return saved.json()


async def _persona(db_container, chat: dict) -> str | None:
    """The instructions the chat's own assistant answers with."""
    async with db_container() as container:
        return await container.session().scalar(
            sa.select(Prompts.text)
            .join(PromptsAssistants, PromptsAssistants.prompt_id == Prompts.id)
            .where(
                PromptsAssistants.assistant_id == UUID(chat["assistant_id"]),
                PromptsAssistants.is_selected.is_(True),
            )
        )


async def test_the_settings_have_their_defaults_until_an_administrator_saves_them(
    client, setup: Setup
):
    read = await client.get(_POLICY_URL, headers=setup.headers)
    assert read.status_code == 200, read.text
    assert read.json() == _DEFAULTS

    saved = await _patch(
        client,
        setup.headers,
        {"enabled": False, "guidance": "  Tilltala alltid personen med du.\n"},
    )

    expected = {
        **_DEFAULTS,
        "enabled": False,
        "guidance": "Tilltala alltid personen med du.",
    }
    assert saved == expected
    assert (await client.get(_POLICY_URL, headers=setup.headers)).json() == expected
    # A field left out keeps its value.
    assert await _patch(client, setup.headers, {"enabled": True}) == {
        **expected,
        "enabled": True,
    }


async def test_the_guidance_is_capped_at_its_maximum_length(client, setup: Setup):
    longest = "x" * 4000

    saved = await _patch(client, setup.headers, {"guidance": f"\n{longest}  "})
    refused = await client.patch(
        _POLICY_URL, headers=setup.headers, json={"guidance": longest + "x"}
    )
    nothing = await client.patch(_POLICY_URL, headers=setup.headers, json={})

    assert saved["guidance"] == longest
    assert refused.status_code == 422, refused.text
    assert nothing.status_code == 400, nothing.text
    assert nothing.json()["code"] == "helper_chat_policy_invalid_payload"
    assert (await client.get(_POLICY_URL, headers=setup.headers)).json()[
        "guidance"
    ] == longest


async def test_only_an_administrator_reads_and_changes_the_settings_of_their_own(
    client, setup: Setup, member_headers, other_tenant_headers
):
    read = await client.get(_POLICY_URL, headers=member_headers)
    changed = await client.patch(
        _POLICY_URL, headers=member_headers, json={"enabled": False}
    )
    assert read.status_code == 403, read.text
    assert changed.status_code == 403, changed.text

    # Another organisation's administrator changes their own settings only.
    theirs = await _patch(
        client, other_tenant_headers, {"enabled": False, "guidance": "Ange källan."}
    )
    assert theirs["enabled"] is False
    assert (await client.get(_POLICY_URL, headers=setup.headers)).json() == _DEFAULTS
    assert (await client.get(_POLICY_URL, headers=other_tenant_headers)).json() == (
        theirs
    )
    # And the chats of this organisation stay on.
    assert (await client.get(setup.url + "availability", headers=setup.headers)).json()[
        "available"
    ] is True


async def test_a_change_is_audited_with_the_administrator_as_actor(
    client, setup: Setup, admin_user, queued
):
    queued.clear()

    await _patch(
        client, setup.headers, {"enabled": False, "guidance": "Ange alltid källan."}
    )

    assert len(queued) == 1
    entry = queued[0]
    assert entry["action"] == ActionType.TENANT_SETTINGS_UPDATED
    assert entry["user"].id == admin_user.id
    assert entry["tenant_id"] == admin_user.tenant_id
    assert entry["entity_type"] == EntityType.TENANT_SETTINGS
    assert entry["entity_id"] == admin_user.tenant_id
    assert entry["metadata"] == {
        "setting": "helper_chat_policy",
        "changes": {
            "enabled": {"old": True, "new": False},
            "guidance": {"old": "", "new": "Ange alltid källan."},
        },
    }


async def test_the_default_model_is_the_one_every_helper_chat_shares(
    client,
    setup: Setup,
    db_container,
    admin_user,
    completion_model_factory,
    queued,
):
    space = await client.get(f"/api/v1/spaces/{setup.space_id}/", headers=setup.headers)
    assert space.status_code == 200, space.text
    async with db_container() as container:
        session = container.session()
        strong = await completion_model_factory(session, f"strong-{uuid4().hex[:6]}")
        plain = await completion_model_factory(session, f"plain-{uuid4().hex[:6]}")
        await session.execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == strong.id)
            .values(supports_tool_calling=True, max_input_tokens=128_000)
        )
        strong_id, plain_id = str(strong.id), str(plain.id)
    linked = await client.patch(
        f"/api/v1/spaces/{setup.space_id}/",
        headers=setup.headers,
        json={
            "completion_models": [
                *({"id": model["id"]} for model in space.json()["completion_models"]),
                {"id": strong_id},
            ]
        },
    )
    assert linked.status_code == 200, linked.text
    assert (await open_chat(client, setup))["default_completion_model_id"] != strong_id
    queued.clear()

    saved = await _patch(client, setup.headers, {"completion_model_id": strong_id})

    assert saved == {**_DEFAULTS, "completion_model_id": strong_id}
    assert (await open_chat(client, setup))["default_completion_model_id"] == strong_id
    assert queued[0]["metadata"]["changes"] == {
        "completion_model_id": {"old": None, "new": strong_id}
    }
    # It is the flow chat's default too: one value for every helper chat.
    async with db_container() as container:
        tenant = await container.tenant_repo().get(admin_user.tenant_id)
    assert tenant.flow_settings["authoring_chat"] == {"completion_model_id": strong_id}

    without_tools = await client.patch(
        _POLICY_URL, headers=setup.headers, json={"completion_model_id": plain_id}
    )
    unknown = await client.patch(
        _POLICY_URL, headers=setup.headers, json={"completion_model_id": str(uuid4())}
    )
    assert without_tools.status_code == 400, without_tools.text
    assert without_tools.json()["code"] == "helper_chat_policy_model_without_tools"
    assert unknown.status_code == 400, unknown.text
    assert unknown.json()["code"] == "helper_chat_policy_model_unavailable"

    cleared = await _patch(client, setup.headers, {"completion_model_id": None})
    assert cleared == _DEFAULTS


async def test_turned_off_no_chat_is_opened_or_continued_until_it_is_on_again(
    client, setup: Setup, db_container, admin_user, monkeypatch: pytest.MonkeyPatch
):
    chat = await open_chat(client, setup)
    url = setup.url + chat["session_id"] + "/"
    asked: list[str] = []

    async def ask(self, question, *args, **kwargs):
        asked.append(question)
        raise AssertionError("A turn of a chat turned off reached the model.")

    monkeypatch.setattr(Assistant, "ask", ask)
    await _patch(client, setup.headers, {"enabled": False})

    available = await client.get(setup.url + "availability", headers=setup.headers)
    assert available.status_code == 200, available.text
    assert available.json() == {"available": False, "reason": "disabled"}
    refused = {
        "open": await client.post(setup.url, headers=setup.headers),
        "change": await client.patch(
            url, headers=setup.headers, json={"completion_model_id": None}
        ),
        "new conversation": await client.post(
            url + "conversations/", headers=setup.headers
        ),
        "turn": await client.post(
            f"/api/v1/assistants/{chat['assistant_id']}/sessions/{chat['session_id']}/",
            headers=setup.headers,
            json={"question": "Vad heter assistenten?", "stream": False},
        ),
    }
    assert {call: (r.status_code, r.json()["code"]) for call, r in refused.items()} == (
        dict.fromkeys(refused, (403, "helper_chat_disabled"))
    )
    assert asked == []
    async with db_container() as container:
        user = await container.user_repo().get_user_by_email(admin_user.email)
        token = container.auth_service().create_scoped_mcp_token(
            user,
            assistant_id=UUID(chat["assistant_id"]),
            session_id=UUID(chat["session_id"]),
        )
    tool = await assistant_settings.read_assistant(loopback_ctx(token))
    assert tool.isError
    assert "turned off" in tool.content[0].text
    assert "Ärendehjälpen" not in tool.content[0].text

    await _patch(client, setup.headers, {"enabled": True})

    reopened = await open_chat(client, setup)
    assert reopened["session_id"] == chat["session_id"]
    assert (await client.get(setup.url + "availability", headers=setup.headers)).json()[
        "available"
    ] is True


async def test_the_guidance_reaches_the_persona_the_next_time_the_chat_is_opened(
    client, setup: Setup, db_container
):
    chat = await open_chat(client, setup)
    assert await _persona(db_container, chat) == ASSISTANT_INSTRUCTIONS
    guidance = "Tilltala alltid personen med du.\nAnge alltid källan."

    await _patch(client, setup.headers, {"guidance": guidance})

    # An open chat keeps the persona it was given until it is opened again.
    assert await _persona(db_container, chat) == ASSISTANT_INSTRUCTIONS
    await open_chat(client, setup)
    persona = await _persona(db_container, chat)
    assert persona == (
        ASSISTANT_INSTRUCTIONS
        + "\n"
        + ORGANISATION_GUIDANCE_INTRODUCTION
        + "\n"
        + guidance
        + "\n"
    )

    # Without guidance the persona is the code's own again, to the byte.
    await _patch(client, setup.headers, {"guidance": ""})
    await open_chat(client, setup)
    assert await _persona(db_container, chat) == ASSISTANT_INSTRUCTIONS
