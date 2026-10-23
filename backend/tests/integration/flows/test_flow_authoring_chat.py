"""Adopted REST and loopback authoring share transactions and revision fences."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
)
from eneo.assistants.assistant import Assistant
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.flow_authoring_chats_table import FlowAuthoringChats
from eneo.database.tables.prompts_table import Prompts, PromptsAssistants
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassifications,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.application.flow_authoring_chat import (
    AUTHORING_INSTRUCTIONS,
    load_authoring_chat,
)
from eneo.internal_mcp import flows
from eneo.main.exceptions import NotFoundException
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.services.service import DatastoreResult
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.users.user import UserAdd, UserState


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


async def test_run_tools_reach_the_chats_flow(
    client, enabled_flow, db_container, admin_user
):
    flow, headers = enabled_flow
    chat = (
        await client.post(
            f"/api/v1/flows/{flow['id']}/authoring-chat/", headers=headers
        )
    ).json()
    ctx = _loopback_ctx(await _chat_token(db_container, admin_user, chat))

    result = await flows.read_run(ctx, uuid4())

    assert result.isError
    page = json.loads(result.content[0].text)
    assert page["errors"] is None, page
    assert "not found" in page["message"].lower()


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
    # The change is judged against the suggestions: a rename introduces none.
    assert _page(renamed)["introduced_suggestions"] == []
    assert isinstance(_page(renamed)["suggestion_count"], int)
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


# --- The chat's model -------------------------------------------------------


_REASONING_LEVELS: dict[str, object] = {
    "temperature": {"supported": False},
    "top_p": {"supported": False},
    "reasoning_effort": {
        "supported": True,
        "control": "select",
        "options": ["low", "medium", "high"],
    },
    "verbosity": {"supported": False},
    "presence_penalty": {"supported": False},
    "frequency_penalty": {"supported": False},
    "top_k": {"supported": False},
}


@dataclass(frozen=True)
class ModelChoices:
    flow: dict
    headers: dict[str, str]
    chat: dict
    url: str
    space_default_id: str
    strong_id: str
    without_tools_id: str
    outside_id: str


async def _space_model_ids(client, headers, space_id: str) -> list[str]:
    space = await client.get(f"/api/v1/spaces/{space_id}/", headers=headers)
    assert space.status_code == 200, space.text
    return [model["id"] for model in space.json()["completion_models"]]


async def _assistant_model(db_container, assistant_id: str) -> tuple[UUID, dict]:
    async with db_container() as container:
        row = (
            await container.session().execute(
                sa.select(
                    Assistants.completion_model_id,
                    Assistants.completion_model_kwargs,
                ).where(Assistants.id == UUID(assistant_id))
            )
        ).one()
    return row.completion_model_id, dict(row.completion_model_kwargs or {})


@pytest.fixture
async def model_choices(
    client, enabled_flow, db_container, completion_model_factory
) -> ModelChoices:
    flow, headers = enabled_flow
    space_id = flow["space_id"]
    before = await _space_model_ids(client, headers, space_id)
    async with db_container() as container:
        session = container.session()
        strong = await completion_model_factory(
            session, f"strong-{uuid4().hex[:6]}", reasoning=True
        )
        without_tools = await completion_model_factory(
            session, f"plain-{uuid4().hex[:6]}"
        )
        outside = await completion_model_factory(session, f"outside-{uuid4().hex[:6]}")
        await session.execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id.in_([strong.id, outside.id]))
            .values(supports_tool_calling=True)
        )
        await session.execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == strong.id)
            .values(model_kwargs_capabilities=_REASONING_LEVELS)
        )
        ids = (str(strong.id), str(without_tools.id), str(outside.id))
    linked = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        headers=headers,
        json={
            "completion_models": [
                {"id": model_id} for model_id in [*before, ids[0], ids[1]]
            ]
        },
    )
    assert linked.status_code == 200, linked.text
    url = f"/api/v1/flows/{flow['id']}/authoring-chat/"
    opened = await client.post(url, headers=headers)
    assert opened.status_code == 200, opened.text
    chat = opened.json()
    assert chat["completion_model_id"] is None
    assert chat["default_completion_model_id"] in before
    return ModelChoices(
        flow=flow,
        headers=headers,
        chat=chat,
        url=url,
        space_default_id=chat["default_completion_model_id"],
        strong_id=ids[0],
        without_tools_id=ids[1],
        outside_id=ids[2],
    )


async def test_a_chosen_model_reaches_the_chats_assistant_and_null_returns_to_the_default(
    client, model_choices: ModelChoices, db_container, monkeypatch: pytest.MonkeyPatch
):
    setup = model_choices
    url = setup.url + setup.chat["session_id"] + "/"
    audited = _record_audit(monkeypatch)

    chosen = await client.patch(
        url, headers=setup.headers, json={"completion_model_id": setup.strong_id}
    )

    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["completion_model_id"] == setup.strong_id
    assert chosen.json()["session_id"] == setup.chat["session_id"]
    model_id, _ = await _assistant_model(db_container, setup.chat["assistant_id"])
    assert str(model_id) == setup.strong_id
    assert audited == [ActionType.FLOW_AUTHORING_CHAT_MODEL_CHANGED]

    reopened = await client.post(setup.url, headers=setup.headers)
    assert reopened.json()["completion_model_id"] == setup.strong_id

    returned = await client.patch(
        url, headers=setup.headers, json={"completion_model_id": None}
    )

    assert returned.status_code == 200, returned.text
    assert returned.json()["completion_model_id"] is None
    model_id, _ = await _assistant_model(db_container, setup.chat["assistant_id"])
    assert str(model_id) == setup.space_default_id


async def test_a_reasoning_effort_the_model_offers_reaches_the_assistant(
    client, model_choices: ModelChoices, db_container
):
    setup = model_choices
    url = setup.url + setup.chat["session_id"] + "/"
    model = await client.get(
        f"/api/v1/spaces/{setup.flow['space_id']}/", headers=setup.headers
    )
    strong = next(
        item
        for item in model.json()["completion_models"]
        if item["id"] == setup.strong_id
    )
    offered = strong["supported_model_kwargs"]["reasoning_effort"]["options"]
    assert offered, strong["supported_model_kwargs"]

    chosen = await client.patch(
        url,
        headers=setup.headers,
        json={"completion_model_id": setup.strong_id, "reasoning_effort": offered[0]},
    )

    assert chosen.status_code == 200, chosen.text
    _, kwargs = await _assistant_model(db_container, setup.chat["assistant_id"])
    assert kwargs.get("reasoning_effort") == offered[0]

    refused = await client.patch(
        url, headers=setup.headers, json={"reasoning_effort": "not-a-level"}
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "flow_authoring_reasoning_effort_unsupported"


@pytest.mark.parametrize(
    ("model", "code"),
    [
        ("outside_id", "flow_authoring_model_not_in_space"),
        ("without_tools_id", "flow_authoring_model_without_tools"),
    ],
)
async def test_a_model_the_chat_cannot_use_is_refused_and_changes_nothing(
    client,
    model_choices: ModelChoices,
    db_container,
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    code: str,
):
    setup = model_choices
    audited = _record_audit(monkeypatch)

    refused = await client.patch(
        setup.url + setup.chat["session_id"] + "/",
        headers=setup.headers,
        json={"completion_model_id": getattr(setup, model)},
    )

    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == code
    assert audited == []
    model_id, _ = await _assistant_model(db_container, setup.chat["assistant_id"])
    assert str(model_id) == setup.space_default_id


async def _member_headers(db_container, admin_user, space_id: str) -> dict[str, str]:
    """A second person who may edit the flow's space, with their own token."""
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"flow-chat-member-{uuid4().hex[:8]}",
                permissions=[
                    Permission.FLOWS_MANAGE,
                    Permission.FLOWS_RUN,
                    Permission.ASSISTANTS,
                ],
                tenant_id=admin_user.tenant_id,
            )
        )
        user = await container.user_repo().add(
            UserAdd(
                email=f"flow-chat-member-{uuid4().hex[:8]}@example.com",
                username=f"flow_chat_member_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
        await container.session().execute(
            sa.text(
                "INSERT INTO spaces_users (space_id, user_id, role) "
                "VALUES (:space_id, :user_id, :role)"
            ),
            {
                "space_id": space_id,
                "user_id": str(user.id),
                "role": SpaceRoleValue.ADMIN.value,
            },
        )
        token = container.auth_service().create_access_token_for_user(user)
    return {"Authorization": f"Bearer {token}"}


async def test_another_persons_chat_cannot_be_changed(
    client, model_choices: ModelChoices, db_container, admin_user
):
    setup = model_choices
    other = await _member_headers(db_container, admin_user, setup.flow["space_id"])
    url = setup.url + setup.chat["session_id"] + "/"

    changed = await client.patch(
        url, headers=other, json={"completion_model_id": setup.strong_id}
    )
    restarted = await client.post(url + "conversations/", headers=other)

    assert changed.status_code == 404, changed.text
    assert restarted.status_code == 404, restarted.text
    mine = (await client.post(setup.url, headers=setup.headers)).json()
    assert mine["session_id"] == setup.chat["session_id"]
    assert mine["completion_model_id"] is None


async def test_a_model_below_the_spaces_classification_is_refused(
    client, enabled_flow, db_container, admin_user, completion_model_factory
):
    _, headers = enabled_flow
    tenant_id = admin_user.tenant_id
    async with db_container() as container:
        session = container.session()
        high = SecurityClassifications(
            tenant_id=tenant_id, name=f"high-{uuid4().hex[:6]}", security_level=20
        )
        session.add(high)
        await session.flush()
        lowered = await completion_model_factory(session, f"lowered-{uuid4().hex[:6]}")
        kept = await completion_model_factory(session, f"kept-{uuid4().hex[:6]}")
        await session.execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id.in_([lowered.id, kept.id]))
            .values(security_classification_id=high.id, supports_tool_calling=True)
        )
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(security_enabled=True)
        )
        high_id, lowered_id, kept_id = high.id, lowered.id, kept.id
    space = await client.post(
        "/api/v1/spaces/", headers=headers, json={"name": f"classified-{uuid4().hex}"}
    )
    assert space.status_code == 201, space.text
    space_id = space.json()["id"]
    classified = await client.patch(
        f"/api/v1/spaces/{space_id}/",
        headers=headers,
        json={
            "completion_models": [{"id": str(lowered_id)}, {"id": str(kept_id)}],
            "security_classification": {"id": str(high_id)},
        },
    )
    assert classified.status_code == 200, classified.text
    async with db_container() as container:
        session = container.session()
        low = SecurityClassifications(
            tenant_id=tenant_id, name=f"low-{uuid4().hex[:6]}", security_level=1
        )
        session.add(low)
        await session.flush()
        await session.execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == lowered_id)
            .values(security_classification_id=low.id)
        )
    flow = await client.post(
        "/api/v1/flows/",
        headers=headers,
        json={"space_id": space_id, "name": "Classified flow", "steps": []},
    )
    assert flow.status_code == 201, flow.text
    url = f"/api/v1/flows/{flow.json()['id']}/authoring-chat/"
    chat = (await client.post(url, headers=headers)).json()
    assert chat["default_completion_model_id"] == str(kept_id)

    refused = await client.patch(
        url + chat["session_id"] + "/",
        headers=headers,
        json={"completion_model_id": str(lowered_id)},
    )

    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "flow_authoring_model_below_classification"


# --- The organisation's default ---------------------------------------------

_POLICY_URL = "/api/v1/settings/flow-authoring-chat-policy"


async def test_the_organisation_default_is_the_chats_model_until_the_person_chooses(
    client, model_choices: ModelChoices, db_container, monkeypatch: pytest.MonkeyPatch
):
    setup = model_choices
    audited = _record_audit(monkeypatch)

    saved = await client.patch(
        _POLICY_URL,
        headers=setup.headers,
        json={"completion_model_id": setup.strong_id},
    )

    assert saved.status_code == 200, saved.text
    assert saved.json() == {"completion_model_id": setup.strong_id}
    assert audited == [ActionType.TENANT_SETTINGS_UPDATED]
    read = await client.get(_POLICY_URL, headers=setup.headers)
    assert read.json() == {"completion_model_id": setup.strong_id}

    reopened = (await client.post(setup.url, headers=setup.headers)).json()
    assert reopened["default_completion_model_id"] == setup.strong_id
    model_id, _ = await _assistant_model(db_container, setup.chat["assistant_id"])
    assert str(model_id) == setup.strong_id

    # A default the space does not allow leaves the chat on the space's own.
    outside = await client.patch(
        _POLICY_URL,
        headers=setup.headers,
        json={"completion_model_id": setup.outside_id},
    )
    assert outside.status_code == 200, outside.text
    reopened = (await client.post(setup.url, headers=setup.headers)).json()
    assert reopened["default_completion_model_id"] == setup.space_default_id
    model_id, _ = await _assistant_model(db_container, setup.chat["assistant_id"])
    assert str(model_id) == setup.space_default_id

    cleared = await client.patch(
        _POLICY_URL, headers=setup.headers, json={"completion_model_id": None}
    )
    assert cleared.json() == {"completion_model_id": None}


async def test_a_new_chat_starts_on_the_organisation_default(
    client, model_choices: ModelChoices, db_container
):
    setup = model_choices
    saved = await client.patch(
        _POLICY_URL,
        headers=setup.headers,
        json={"completion_model_id": setup.strong_id},
    )
    assert saved.status_code == 200, saved.text
    flow = await client.post(
        "/api/v1/flows/",
        headers=setup.headers,
        json={"space_id": setup.flow["space_id"], "name": "Second flow", "steps": []},
    )
    assert flow.status_code == 201, flow.text

    chat = (
        await client.post(
            f"/api/v1/flows/{flow.json()['id']}/authoring-chat/",
            headers=setup.headers,
        )
    ).json()

    assert chat["default_completion_model_id"] == setup.strong_id
    model_id, _ = await _assistant_model(db_container, chat["assistant_id"])
    assert str(model_id) == setup.strong_id


async def test_a_default_without_tools_is_refused(client, model_choices: ModelChoices):
    setup = model_choices

    refused = await client.patch(
        _POLICY_URL,
        headers=setup.headers,
        json={"completion_model_id": setup.without_tools_id},
    )
    unknown = await client.patch(
        _POLICY_URL, headers=setup.headers, json={"completion_model_id": str(uuid4())}
    )

    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "flow_authoring_model_without_tools"
    assert unknown.status_code == 400, unknown.text
    assert unknown.json()["code"] == "flow_authoring_model_unavailable"
    read = await client.get(_POLICY_URL, headers=setup.headers)
    assert read.json() == {"completion_model_id": None}


# --- Conversations ----------------------------------------------------------


async def _add_question(
    db_container, chat: dict, tenant_id: UUID, *, age: timedelta
) -> None:
    """A question in the chat's current conversation, asked ``age`` ago."""
    model_id, _ = await _assistant_model(db_container, chat["assistant_id"])
    async with db_container() as container:
        await container.session().execute(
            sa.insert(Questions).values(
                question="Lägg till ett steg.",
                answer="Klart.",
                num_tokens_question=4,
                num_tokens_answer=1,
                session_id=UUID(chat["session_id"]),
                tenant_id=tenant_id,
                assistant_id=UUID(chat["assistant_id"]),
                completion_model_id=model_id,
                created_at=datetime.now(timezone.utc) - age,
            )
        )


async def _set_mode_changed(db_container, chat: dict, *, age: timedelta) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(FlowAuthoringChats)
            .where(FlowAuthoringChats.session_id == UUID(chat["session_id"]))
            .values(mode_changed_at=datetime.now(timezone.utc) - age)
        )


async def _set_editing(client, setup: ModelChoices, chat: dict, editing: bool) -> dict:
    current = await client.get(
        f"/api/v1/flows/{setup.flow['id']}/", headers=setup.headers
    )
    response = await client.patch(
        setup.url + chat["session_id"] + "/",
        headers=setup.headers,
        json={
            "expected_revision": current.json()["draft_revision"],
            "editing": editing,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _capture_model_history(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Answer every turn without a provider; record the history it was given."""
    histories: list[list[str]] = []

    async def ask(self, question, completion_service, references_service, **kwargs):
        session = kwargs.get("session")
        histories.append(
            [item.question for item in (session.questions if session else [])]
        )
        model = kwargs.get("completion_model_override") or self.completion_model
        return (
            CompletionModelResponse(
                completion=Completion(text="Svar."), model=model, total_token_count=1
            ),
            DatastoreResult(chunks=[], no_duplicate_chunks=[], info_blobs=[]),
        )

    monkeypatch.setattr(Assistant, "ask", ask)
    return histories


async def test_edit_mode_after_a_pause_starts_a_new_conversation_the_model_sees_alone(
    client,
    model_choices: ModelChoices,
    db_container,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
):
    setup = model_choices
    chat = setup.chat
    await _add_question(
        db_container, chat, admin_user.tenant_id, age=timedelta(hours=2)
    )
    await _set_mode_changed(db_container, chat, age=timedelta(hours=2))
    audited = _record_audit(monkeypatch)

    editing = await _set_editing(client, setup, chat, True)

    assert editing["editing"] is True
    assert editing["session_id"] != chat["session_id"]
    assert audited == [
        ActionType.FLOW_AUTHORING_CONVERSATION_STARTED,
        ActionType.FLOW_AUTHORING_MODE_CHANGED,
    ]
    histories = _capture_model_history(monkeypatch)
    asked = await client.post(
        f"/api/v1/assistants/{chat['assistant_id']}/sessions/{editing['session_id']}/",
        headers=setup.headers,
        json={"question": "Vad gör flödet?", "stream": False},
    )
    assert asked.status_code == 200, asked.text
    assert histories == [[]]
    old = await client.post(
        f"/api/v1/assistants/{chat['assistant_id']}/sessions/{chat['session_id']}/",
        headers=setup.headers,
        json={"question": "Fortsätt.", "stream": False},
    )
    assert old.status_code == 404, old.text
    assert len(histories) == 1
    async with db_container() as container:
        kept = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(Questions)
            .where(Questions.session_id == UUID(chat["session_id"]))
        )
    assert kept == 1


async def test_edit_mode_within_the_pause_keeps_the_conversation(
    client, model_choices: ModelChoices, db_container, admin_user
):
    setup = model_choices
    chat = setup.chat
    await _add_question(
        db_container, chat, admin_user.tenant_id, age=timedelta(minutes=5)
    )

    on = await _set_editing(client, setup, chat, True)
    off = await _set_editing(client, setup, on, False)
    again = await _set_editing(client, setup, off, True)

    assert on["session_id"] == off["session_id"] == again["session_id"]
    assert again["session_id"] == chat["session_id"]


async def test_an_empty_conversation_is_kept_however_long_the_pause(
    client, model_choices: ModelChoices, db_container
):
    setup = model_choices
    chat = setup.chat
    await _set_mode_changed(db_container, chat, age=timedelta(days=2))

    editing = await _set_editing(client, setup, chat, True)

    assert editing["session_id"] == chat["session_id"]


async def test_a_new_conversation_on_request_leaves_other_peoples_chats_alone(
    client,
    model_choices: ModelChoices,
    db_container,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
):
    setup = model_choices
    other = await _member_headers(db_container, admin_user, setup.flow["space_id"])
    their_flow = await client.post(
        "/api/v1/flows/",
        headers=other,
        json={"space_id": setup.flow["space_id"], "name": "Their flow", "steps": []},
    )
    assert their_flow.status_code == 201, their_flow.text
    their_url = f"/api/v1/flows/{their_flow.json()['id']}/authoring-chat/"
    theirs = await client.post(their_url, headers=other)
    assert theirs.status_code == 200, theirs.text
    audited = _record_audit(monkeypatch)

    started = await client.post(
        setup.url + setup.chat["session_id"] + "/conversations/", headers=setup.headers
    )

    assert started.status_code == 200, started.text
    new = started.json()
    assert new["session_id"] != setup.chat["session_id"]
    assert new["assistant_id"] == setup.chat["assistant_id"]
    assert audited == [ActionType.FLOW_AUTHORING_CONVERSATION_STARTED]
    reopened = (await client.post(setup.url, headers=setup.headers)).json()
    assert reopened["session_id"] == new["session_id"]
    still_theirs = (await client.post(their_url, headers=other)).json()
    assert still_theirs["session_id"] == theirs.json()["session_id"]
    with pytest.raises(NotFoundException):
        async with db_container() as container:
            await load_authoring_chat(
                container, session_id=UUID(setup.chat["session_id"])
            )
