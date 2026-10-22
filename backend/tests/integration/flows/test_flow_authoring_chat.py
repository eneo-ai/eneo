"""Adopted REST and loopback authoring share transactions and revision fences."""

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.prompts_table import Prompts, PromptsAssistants
from eneo.flows.application.flow_authoring_chat import (
    AUTHORING_INSTRUCTIONS,
    load_authoring_chat,
)
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


async def test_reopening_a_chat_gives_it_the_current_instructions_once(
    client, enabled_flow, db_container
):
    flow, headers = enabled_flow
    url = f"/api/v1/flows/{flow['id']}/authoring-chat/"
    chat = (await client.post(url, headers=headers)).json()
    assistant_id = UUID(chat["assistant_id"])

    async def prompts() -> tuple[str, int]:
        async with db_container() as container:
            rows = (
                await container.session().execute(
                    sa.select(Prompts.text, PromptsAssistants.is_selected)
                    .join(PromptsAssistants, PromptsAssistants.prompt_id == Prompts.id)
                    .where(PromptsAssistants.assistant_id == assistant_id)
                )
            ).all()
        return next(text for text, selected in rows if selected), len(rows)

    selected, _ = await prompts()
    async with db_container() as container:
        # A chat created before the instructions last changed.
        await container.session().execute(
            sa.update(Prompts).where(Prompts.text == selected).values(text="Old.")
        )
    _, before = await prompts()

    assert (await client.post(url, headers=headers)).status_code == 200
    selected, refreshed = await prompts()
    assert selected == AUTHORING_INSTRUCTIONS
    assert refreshed == before + 1

    assert (await client.post(url, headers=headers)).status_code == 200
    assert await prompts() == (AUTHORING_INSTRUCTIONS, refreshed)


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


def _new_step(name: str, prompt: str, *, input_source: str) -> dict:
    return {
        "name": name,
        "configuration": {
            "input_source": input_source,
            "input_type": "text",
            "output_mode": "compose_text",
            "output_type": "text",
        },
        "assistant": {"prompt": {"text": prompt}},
    }


async def _prompt(client, base: str, headers, step: dict) -> str:
    response = await client.get(
        base + f"/assistants/{step['assistant_id']}/", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["prompt"]["text"]


async def test_reordered_steps_keep_reading_the_steps_they_read(client, enabled_flow):
    flow, headers = enabled_flow
    base = f"/api/v1/flows/{flow['id']}"
    created = await client.patch(
        base + "/editor/",
        headers=headers,
        json={
            "expected_revision": flow["draft_revision"],
            "definition": {},
            "new_steps": [
                _new_step("Collect", "Collect the facts.", input_source="flow_input"),
                _new_step(
                    "Write",
                    "Write from {{step_1.output}}.",
                    input_source="previous_step",
                ),
            ],
        },
    )
    assert created.status_code == 200, created.text
    collect, write = created.json()["steps"]

    inserted = await client.patch(
        base + "/editor/",
        headers=headers,
        json={
            "expected_revision": created.json()["draft_revision"],
            "definition": {},
            "new_steps": [
                _new_step("Greet", "Greet the reader.", input_source="flow_input")
            ],
            "step_edits": [
                {
                    "step_id": collect["id"],
                    "changes": {"input_source": "previous_step"},
                }
            ],
            "step_order": [
                {"new_step": 0},
                {"step_id": collect["id"]},
                {"step_id": write["id"]},
            ],
        },
    )

    assert inserted.status_code == 200, inserted.text
    saved = inserted.json()
    assert saved["draft_revision"] == created.json()["draft_revision"] + 1
    assert [step["user_description"] for step in saved["steps"]] == [
        "Greet",
        "Collect",
        "Write",
    ]
    assert await _prompt(client, base, headers, saved["steps"][2]) == (
        "Write from {{step_2.output}}."
    )

    refused = await client.patch(
        base + "/editor/",
        headers=headers,
        json={
            "expected_revision": saved["draft_revision"],
            "definition": {},
            "step_order": [
                {"step_id": saved["steps"][0]["id"]},
                {"step_id": write["id"]},
            ],
        },
    )

    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "flow_step_read_lost_producer"
    current = (await client.get(base + "/", headers=headers)).json()
    assert current["draft_revision"] == saved["draft_revision"]
    assert len(current["steps"]) == 3


async def test_chat_moves_and_removes_steps_through_the_same_rules(
    client, enabled_flow, db_container, admin_user
):
    flow, headers = enabled_flow
    base = f"/api/v1/flows/{flow['id']}"
    created = await client.patch(
        base + "/editor/",
        headers=headers,
        json={
            "expected_revision": flow["draft_revision"],
            "definition": {},
            "new_steps": [
                _new_step("Collect", "Collect the facts.", input_source="flow_input"),
                _new_step("Check", "Check the facts.", input_source="previous_step"),
                _new_step("Draft", "Draft a text.", input_source="previous_step"),
                _new_step(
                    "Write",
                    "Write from {{step_2.output}}.",
                    input_source="previous_step",
                ),
            ],
        },
    )
    assert created.status_code == 200, created.text
    collect, check, draft, write = created.json()["steps"]
    revision = created.json()["draft_revision"]
    url = base + "/authoring-chat/"
    chat = (await client.post(url, headers=headers)).json()
    mode = await client.patch(
        url + chat["session_id"] + "/",
        headers=headers,
        json={"expected_revision": revision, "editing": True},
    )
    assert mode.status_code == 200, mode.text
    ctx = _loopback_ctx(await _chat_token(db_container, admin_user, chat))

    refused = await flows.remove_step(ctx, revision, UUID(check["id"]))
    assert refused.isError
    assert _page(refused)["code"] == "flow_step_read_lost_producer"

    moved = await flows.move_step(ctx, revision, UUID(draft["id"]), 2)
    assert not moved.isError, moved.content[0].text
    revision += 1
    order = json.loads(_page(moved)["content"])["steps"]
    assert [item["step_id"] for item in order] == [
        collect["id"],
        draft["id"],
        check["id"],
        write["id"],
    ]
    assert await _prompt(client, base, headers, write) == (
        "Write from {{step_3.output}}."
    )

    removed = await flows.remove_step(ctx, revision, UUID(draft["id"]))
    assert not removed.isError, removed.content[0].text
    revision += 1
    current = (await client.get(base + "/", headers=headers)).json()
    assert [step["id"] for step in current["steps"]] == [
        collect["id"],
        check["id"],
        write["id"],
    ]
    assert await _prompt(client, base, headers, write) == (
        "Write from {{step_2.output}}."
    )

    ahead = await flows.move_step(ctx, revision, UUID(write["id"]), 2)
    assert ahead.isError
    assert _page(ahead)["code"] == "flow_step_read_lost_producer"


async def _editing_chat(client, db_container, admin_user, base, headers, revision):
    url = base + "/authoring-chat/"
    chat = (await client.post(url, headers=headers)).json()
    mode = await client.patch(
        url + chat["session_id"] + "/",
        headers=headers,
        json={"expected_revision": revision, "editing": True},
    )
    assert mode.status_code == 200, mode.text
    return _loopback_ctx(await _chat_token(db_container, admin_user, chat))


def _record_audit(monkeypatch: pytest.MonkeyPatch) -> list[ActionType]:
    actions: list[ActionType] = []
    log_async = AuditService.log_async

    async def record(self: AuditService, **kwargs):
        actions.append(kwargs["action"])
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)
    return actions


async def test_chat_renames_carry_reads_and_a_refused_edit_audits_nothing(
    client, enabled_flow, db_container, admin_user, monkeypatch: pytest.MonkeyPatch
):
    flow, headers = enabled_flow
    base = f"/api/v1/flows/{flow['id']}"
    created = await client.patch(
        base + "/editor/",
        headers=headers,
        json={
            "expected_revision": flow["draft_revision"],
            "definition": {
                "metadata_json": {
                    "form_schema": {"fields": [{"name": "kommun", "type": "text"}]}
                }
            },
            "new_steps": [
                _new_step("Collect", "Collect the facts.", input_source="flow_input"),
                _new_step(
                    "Write",
                    "Write from {{ Collect }} for {{ flow_input.kommun }}.",
                    input_source="previous_step",
                ),
            ],
        },
    )
    assert created.status_code == 200, created.text
    collect, write = created.json()["steps"]
    revision = created.json()["draft_revision"]
    ctx = await _editing_chat(client, db_container, admin_user, base, headers, revision)
    audited = _record_audit(monkeypatch)

    # Write reads Collect by its name, which this edit takes away.
    refused = await flows.update_step(
        ctx,
        revision,
        UUID(collect["id"]),
        {"user_description": None},
        {"prompt": {"text": "Never saved."}},
    )
    assert refused.isError
    assert _page(refused)["code"] == "flow_step_read_lost_producer"
    assert audited == []
    assert await _prompt(client, base, headers, collect) == "Collect the facts."

    renamed = await flows.update_step(
        ctx, revision, UUID(collect["id"]), {"user_description": "Facts"}
    )
    assert not renamed.isError, renamed.content[0].text
    revision += 1
    assert await _prompt(client, base, headers, write) == (
        "Write from {{ Facts }} for {{ flow_input.kommun }}."
    )

    field_renamed = await flows.update_flow_settings(
        ctx,
        revision,
        {
            "metadata_json": {
                "form_schema": {"fields": [{"name": "ort", "type": "text"}]}
            },
            "form_field_renames": {"kommun": "ort"},
        },
    )
    assert not field_renamed.isError, field_renamed.content[0].text
    revision += 1
    assert await _prompt(client, base, headers, write) == (
        "Write from {{ Facts }} for {{ flow_input.ort }}."
    )

    removed = await flows.update_flow_settings(
        ctx, revision, {"metadata_json": {"form_schema": {"fields": []}}}
    )
    assert removed.isError
    assert _page(removed)["code"] == "flow_form_field_still_read"


async def test_chat_edit_of_a_shared_assistant_gives_the_step_its_own_copy(
    client, enabled_flow, db_container, admin_user
):
    flow, headers = enabled_flow
    base = f"/api/v1/flows/{flow['id']}"
    created = await client.patch(
        base + "/editor/",
        headers=headers,
        json={
            "expected_revision": flow["draft_revision"],
            "definition": {},
            "new_steps": [
                _new_step("Collect", "Shared prompt.", input_source="flow_input"),
                _new_step("Check", "Own prompt.", input_source="previous_step"),
            ],
        },
    )
    assert created.status_code == 200, created.text
    collect, check = created.json()["steps"]
    step_keys = {
        "id",
        "assistant_id",
        "step_order",
        "user_description",
        "input_source",
        "input_type",
        "output_mode",
        "output_type",
    }
    sharing = await client.patch(
        base + "/",
        headers=headers,
        json={
            "expected_revision": created.json()["draft_revision"],
            "steps": [
                {key: collect[key] for key in step_keys},
                {
                    **{key: check[key] for key in step_keys},
                    "assistant_id": collect["assistant_id"],
                },
            ],
        },
    )
    assert sharing.status_code == 200, sharing.text
    revision = sharing.json()["draft_revision"]
    ctx = await _editing_chat(client, db_container, admin_user, base, headers, revision)

    result = await flows.update_step(
        ctx,
        revision,
        UUID(check["id"]),
        {},
        {"prompt": {"text": "Only for Check."}},
    )

    assert not result.isError, result.content[0].text
    copy_id = json.loads(_page(result)["content"])["assistant_id"]
    assert copy_id != collect["assistant_id"]
    current = (await client.get(base + "/", headers=headers)).json()
    assert current["draft_revision"] == revision + 1
    assert [step["assistant_id"] for step in current["steps"]] == [
        collect["assistant_id"],
        copy_id,
    ]
    assert await _prompt(client, base, headers, collect) == "Shared prompt."
    assert await _prompt(client, base, headers, current["steps"][1]) == (
        "Only for Check."
    )
