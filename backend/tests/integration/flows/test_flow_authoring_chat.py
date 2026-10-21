"""Adopted REST and loopback authoring share transactions and revision fences."""

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.flows.application.flow_authoring_chat import load_authoring_chat
from eneo.internal_mcp import flows
from eneo.main.exceptions import NotFoundException


@pytest.fixture
async def enabled_flow(db_container, admin_user, client, flow_process_auth_headers):
    async with db_container() as container:
        flag = await container.feature_flag_repo().one(name="flows_core")
        await container.feature_flag_service().enable_tenant(
            flag.feature_id, admin_user.tenant_id
        )
        await container.session().execute(
            sa.update(CompletionModels)
            .where(CompletionModels.tenant_id == admin_user.tenant_id)
            .values(supports_tool_calling=True)
        )
    headers = dict(flow_process_auth_headers)
    space_response = await client.post(
        "/api/v1/spaces/", headers=headers, json={"name": "Flow authoring adoption"}
    )
    assert space_response.status_code == 201, space_response.text
    flow_response = await client.post(
        "/api/v1/flows/",
        headers=headers,
        json={
            "space_id": space_response.json()["id"],
            "name": "Adopted flow",
            "steps": [],
        },
    )
    assert flow_response.status_code == 201, flow_response.text
    return flow_response.json(), headers


async def test_chat_bootstrap_is_idempotent_scoped_and_initially_read_only(
    client, enabled_flow, db_container
):
    flow, headers = enabled_flow
    url = f"/api/v1/flows/{flow['id']}/authoring-chat/"
    first = await client.post(url, headers=headers)
    assert first.status_code == 200, first.text
    second = await client.post(url, headers=headers)
    assert second.status_code == 200, second.text
    assert first.json() == second.json()
    chat = first.json()
    assert chat["editing"] is False
    async with db_container() as container:
        loaded = await load_authoring_chat(
            container,
            session_id=UUID(chat["session_id"]),
            assistant_id=UUID(chat["assistant_id"]),
            flow_id=UUID(flow["id"]),
        )
        assert str(loaded.flow_id) == flow["id"]
        with pytest.raises(NotFoundException):
            await load_authoring_chat(
                container, session_id=UUID(chat["session_id"]), assistant_id=uuid4()
            )
        with pytest.raises(NotFoundException):
            await load_authoring_chat(
                container, session_id=UUID(chat["session_id"]), flow_id=uuid4()
            )
    mode = await client.patch(
        url + chat["session_id"] + "/",
        headers=headers,
        json={"expected_revision": flow["draft_revision"], "editing": True},
    )
    assert mode.status_code == 200, mode.text
    assert mode.json()["editing"] is True


async def test_failed_joint_edit_rolls_back_assistant_and_revision(
    client, enabled_flow
):
    flow, headers = enabled_flow
    base = f"/api/v1/flows/{flow['id']}"
    assistant = await client.post(
        base + "/assistants/", headers=headers, json={"name": "Original assistant"}
    )
    assert assistant.status_code == 201, assistant.text
    assistant_id = assistant.json()["id"]
    before = await client.get(base + "/", headers=headers)
    revision = before.json()["draft_revision"]
    response = await client.patch(
        base + "/editor/",
        headers=headers,
        json={
            "expected_revision": revision,
            "definition": {
                "steps": [
                    {
                        "assistant_id": str(uuid4()),
                        "step_order": 1,
                        "input_source": "flow_input",
                        "input_type": "text",
                        "output_mode": "compose_text",
                        "output_type": "text",
                    }
                ]
            },
            "assistants": [
                {"assistant_id": assistant_id, "changes": {"name": "Must roll back"}}
            ],
        },
    )
    assert response.status_code in {400, 404}, response.text
    after = await client.get(base + "/", headers=headers)
    assert after.json()["draft_revision"] == revision
    current_assistant = await client.get(
        base + f"/assistants/{assistant_id}/", headers=headers
    )
    assert current_assistant.json()["name"] == "Original assistant"
    success = await client.patch(
        base + "/editor/",
        headers=headers,
        json={
            "expected_revision": revision,
            "definition": {"description": "Saved once"},
            "assistants": [
                {"assistant_id": assistant_id, "changes": {"name": "Saved assistant"}}
            ],
        },
    )
    assert success.status_code == 200, success.text
    assert success.json()["draft_revision"] == revision + 1
    stale = await client.patch(
        base + "/editor/",
        headers=headers,
        json={
            "expected_revision": revision,
            "definition": {"description": "Must not overwrite"},
        },
    )
    assert stale.status_code == 400, stale.text
    assert stale.json()["code"] == "stale_revision"


async def test_new_step_and_its_prompt_are_saved_in_one_revision(client, enabled_flow):
    flow, headers = enabled_flow
    base = f"/api/v1/flows/{flow['id']}"
    response = await client.patch(
        base + "/editor/",
        headers=headers,
        json={
            "expected_revision": flow["draft_revision"],
            "definition": {},
            "new_steps": [
                {
                    "name": "A new step",
                    "configuration": {
                        "input_source": "flow_input",
                        "input_type": "text",
                        "output_mode": "compose_text",
                        "output_type": "text",
                    },
                    "assistant": {"prompt": {"text": "Saved atomically"}},
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["draft_revision"] == flow["draft_revision"] + 1
    assert len(saved["steps"]) == 1
    step = saved["steps"][0]
    assistant = await client.get(
        base + f"/assistants/{step['assistant_id']}/", headers=headers
    )
    assert assistant.status_code == 200, assistant.text
    assert assistant.json()["prompt"]["text"] == "Saved atomically"


def _loopback_ctx(token: str) -> SimpleNamespace:
    """The slice of a FastMCP ``Context`` the loopback foundation reads."""
    request = SimpleNamespace(headers={"authorization": f"Bearer {token}"})
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


def _page(result) -> dict:
    return json.loads(result.content[0].text)


async def _chat_token(db_container, admin_user, chat: dict, *, session_id=None) -> str:
    async with db_container() as container:
        user = await container.user_repo().get_user_by_email(admin_user.email)
        return container.auth_service().create_scoped_mcp_token(
            user,
            assistant_id=UUID(chat["assistant_id"]),
            session_id=session_id or UUID(chat["session_id"]),
        )


async def test_flow_tools_act_on_the_chats_flow_only_in_edit_mode(
    client, enabled_flow, db_container, admin_user
):
    flow, headers = enabled_flow
    url = f"/api/v1/flows/{flow['id']}/authoring-chat/"
    chat = (await client.post(url, headers=headers)).json()
    ctx = _loopback_ctx(await _chat_token(db_container, admin_user, chat))

    read = await flows.read_flow(ctx)
    assert not read.isError
    assert read.structuredContent == {
        "flow_id": flow["id"],
        "draft_revision": flow["draft_revision"],
    }
    assert flow["name"] in _page(read)["content"]

    refused = await flows.update_flow_settings(
        ctx, flow["draft_revision"], {"description": "Via chat"}
    )
    assert refused.isError
    assert "edit mode" in _page(refused)["message"]

    mode = await client.patch(
        url + chat["session_id"] + "/",
        headers=headers,
        json={"expected_revision": flow["draft_revision"], "editing": True},
    )
    assert mode.status_code == 200, mode.text

    saved = await flows.update_flow_settings(
        ctx, flow["draft_revision"], {"description": "Via chat"}
    )
    assert not saved.isError, saved.content[0].text
    current = (await client.get(f"/api/v1/flows/{flow['id']}/", headers=headers)).json()
    assert current["description"] == "Via chat"
    assert current["draft_revision"] == flow["draft_revision"] + 1

    stale = await flows.update_flow_settings(
        ctx, flow["draft_revision"], {"description": "Overwrite"}
    )
    assert stale.isError
    assert _page(stale)["code"] == "stale_revision"


async def test_a_token_for_another_chat_reaches_no_flow(
    client, enabled_flow, db_container, admin_user
):
    flow, headers = enabled_flow
    chat = (
        await client.post(
            f"/api/v1/flows/{flow['id']}/authoring-chat/", headers=headers
        )
    ).json()
    ctx = _loopback_ctx(
        await _chat_token(db_container, admin_user, chat, session_id=uuid4())
    )

    result = await flows.read_flow(ctx)

    assert result.isError
    assert flow["name"] not in result.content[0].text
