"""Every save of a flow is a revision: listed, read, restored, frozen by publish."""

import pytest

from eneo.database.tables.sessions_table import Sessions
from eneo.flows.definition import ComposeStep, FlowDefinition, LlmStep
from eneo.main.exceptions import BadRequestException, NotFoundException
from tests.integration.flows.conftest import topic_field


def _two_steps(model_id) -> FlowDefinition:
    return FlowDefinition(
        form_fields=[topic_field()],
        steps=[
            LlmStep(
                key="draft",
                name="Draft",
                prompt="draft",
                input="{{form.topic}}",
                model_id=model_id,
            ),
            ComposeStep(key="wrap", name="Wrap", template="Done: {{previous}}"),
        ],
    )


async def test_history_keeps_every_change_and_restores_an_earlier_revision(
    db_container, member_space, completion_model_factory, provider
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "flow-revisions-model")
        space = await member_space(session, "Revisions Space", [model.id])
        flow_service = container.flow_service()

        created = await flow_service.create_flow(
            space_id=space.id,
            name="Brief",
            description="First description",
            definition=_two_steps(model.id),
            channel="mcp",
        )
        assert created.revision == 1
        wrap_id = created.definition.steps[1].id

        # A change: the wrap step goes, a new step comes, the draft prompt changes.
        changed = await flow_service.update_flow(
            created.id,
            name="Weekly brief",
            definition=FlowDefinition(
                form_fields=created.definition.form_fields,
                steps=[
                    LlmStep(
                        key="draft",
                        name="Draft",
                        prompt="draft carefully",
                        input="{{form.topic}}",
                        model_id=model.id,
                    ),
                    ComposeStep(
                        key="sign", name="Sign off", template="-- {{previous}}"
                    ),
                ],
            ),
            channel="mcp",
            note="Sign off instead of wrapping",
        )
        assert changed.revision == 2

        # The same content again keeps no revision.
        unchanged = await flow_service.update_flow(
            created.id,
            name="Weekly brief",
            definition=changed.definition,
            channel="mcp",
        )
        assert unchanged.revision == 2

        revisions, total = await flow_service.list_revisions(created.id)
        assert total == 2
        assert [r.revision for r in revisions] == [2, 1]
        latest, first = revisions
        assert latest.name == "Weekly brief"
        assert latest.channel == "mcp"
        assert latest.note == "Sign off instead of wrapping"
        assert latest.created_by_user_id is not None
        assert latest.published_version is None
        assert latest.changes.is_initial is False
        assert latest.changes.name_changed is True
        assert latest.changes.description_changed is False
        assert latest.changes.form_fields_changed is False
        assert latest.changes.steps_added == ["Sign off"]
        assert latest.changes.steps_removed == ["Wrap"]
        assert latest.changes.steps_changed == ["Draft"]
        assert first.changes.is_initial is True
        assert first.note is None

        detail = await flow_service.get_revision(created.id, 1)
        assert detail.name == "Brief"
        assert detail.description == "First description"
        assert [step.key for step in detail.definition.steps] == ["draft", "wrap"]
        assert detail.definition.steps[1].id == wrap_id

        # Publishing freezes the current revision on the version.
        published = await flow_service.publish_flow(created.id)
        assert published.published_version == 1
        revisions, _ = await flow_service.list_revisions(created.id)
        assert revisions[0].published_version == 1
        assert revisions[1].published_version is None

        # Restoring revision 1 is revision 3; the step that was removed in
        # between keeps the id it had, the draft kept its id throughout.
        restored = await flow_service.restore_revision(created.id, 1)
        assert restored.revision == 3
        assert restored.name == "Brief"
        assert restored.description == "First description"
        assert [step.key for step in restored.definition.steps] == ["draft", "wrap"]
        assert restored.definition.steps[1].id == wrap_id
        assert restored.definition.steps[0].id == created.definition.steps[0].id
        assert restored.has_unpublished_changes is True

        revisions, total = await flow_service.list_revisions(created.id)
        assert total == 3
        assert [r.revision for r in revisions] == [3, 2, 1]
        assert revisions[0].note == "Restored revision 1"
        assert revisions[0].channel == "api"
        assert revisions[0].changes.steps_added == ["Wrap"]
        assert revisions[0].changes.steps_removed == ["Sign off"]
        assert revisions[0].changes.steps_changed == ["Draft"]

        page, total = await flow_service.list_revisions(created.id, limit=1, offset=1)
        assert total == 3
        assert [r.revision for r in page] == [2]
        # The oldest row on a page still compares against the revision before it.
        assert page[0].changes.steps_removed == ["Wrap"]

        with pytest.raises(NotFoundException):
            await flow_service.get_revision(created.id, 9)
        with pytest.raises(NotFoundException):
            await flow_service.restore_revision(created.id, 9)


async def test_a_flow_starts_empty_and_its_chat_fills_it_in(
    db_container,
    member_space,
    completion_model_factory,
    provider,
    admin_user,
    monkeypatch,
):
    """REST creates the empty draft and binds the chat; the chat's tools then
    edit and publish it without naming a flow id."""
    from contextlib import asynccontextmanager

    from eneo.internal_mcp import flows as flows_mcp
    from eneo.internal_mcp.foundation import ToolContext
    from eneo.main.exceptions import FlowConversationConflictException

    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "flow-draft-model")
        space = await member_space(session, "Draft Space", [model.id])
        authoring = await container.flow_authoring_assistant_service().get_or_create(
            space.id
        )
        chat = Sessions(
            user_id=admin_user.id,
            name="Flows chat",
            assistant_id=authoring.assistant_id,
        )
        other_chat = Sessions(
            user_id=admin_user.id,
            name="Other chat",
            assistant_id=authoring.assistant_id,
        )
        session.add_all([chat, other_chat])
        await session.flush()
        flow_service = container.flow_service()

        draft = await flow_service.create_draft(space_id=space.id, name=None)
        assert draft.name == "Nytt flöde"
        assert draft.definition.steps == [] and draft.definition.form_fields == []
        assert draft.revision == 1
        assert draft.conversation_id is None
        with pytest.raises(BadRequestException, match="at least one step"):
            await flow_service.publish_flow(draft.id)

        assert await flow_service.flow_for_conversation(chat.id) is None
        bound = await flow_service.bind_conversation(draft.id, chat.id)
        assert bound.conversation_id == chat.id
        # Idempotent for the same chat, a conflict for another.
        assert (await flow_service.bind_conversation(draft.id, chat.id)).revision == 1
        with pytest.raises(FlowConversationConflictException):
            await flow_service.bind_conversation(draft.id, other_chat.id)
        assert (await flow_service.flow_for_conversation(chat.id)).id == draft.id

        @asynccontextmanager
        async def tool_context(_ctx):
            yield ToolContext(
                container=container,
                user=admin_user,
                assistant_id=authoring.assistant_id,
                session_id=chat.id,
            )

        monkeypatch.setattr(flows_mcp, "internal_tool_context", tool_context)

        # The chat's write tools wait for the person to enter edit mode.
        refused = await flows_mcp.update_flow(ctx=object(), name="Brief")
        assert refused.content[0].text.startswith(
            "Could not update flow: The flow is shown in view mode."
        )
        assert (await flow_service.enter_edit_mode(draft.id)).editing is True

        result = await flows_mcp.update_flow(
            ctx=object(),
            name="Brief",
            form_fields=[topic_field()],
            steps=[
                LlmStep(
                    key="draft",
                    name="Draft",
                    prompt="draft",
                    input="{{form.topic}}",
                    model_id=model.id,
                )
            ],
            note="First steps",
        )
        assert result.structuredContent["flow_id"] == str(draft.id), result.content
        assert result.structuredContent["flow"] is not None, result.content
        assert result.structuredContent["flow"]["revision"] == 2

        published = await flows_mcp.publish_flow(ctx=object())
        assert published.structuredContent["published_version"] == 1

        revisions, total = await flow_service.list_revisions(draft.id)
        assert total == 2
        assert revisions[0].note == "First steps"
        assert revisions[0].channel == "mcp"
        assert revisions[0].published_version == 1
        assert revisions[0].changes.steps_added == ["Draft"]

        await flow_service.delete_flow(draft.id)
        assert await flow_service.flow_for_conversation(chat.id) is None


@pytest.fixture
async def chat_authored(db_container, member_space, completion_model_factory, provider):
    """A flow the chat saved (revision 1, channel mcp) in a space the admin
    user edits; returned as the ids the HTTP cases need."""
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "flow-patch-model")
        space = await member_space(session, "Patch Space", [model.id])
        flow = await container.flow_service().create_flow(
            space_id=space.id,
            name="Brief",
            description=None,
            definition=_two_steps(model.id),
            channel="mcp",
        )
        # Read inside the session: the row detaches when it closes.
        model_id = model.id
    return {"flow": flow, "model_id": model_id}


async def test_the_panel_saves_through_patch_as_api_revisions_keeping_step_ids(
    client, chat_authored, flows_enabled, bearer
):
    flow = chat_authored["flow"]
    url = f"/api/v1/flows/{flow.id}/"
    assert (await client.post(f"{url}edit-mode/", headers=bearer)).status_code == 200

    definition = (await client.get(url, headers=bearer)).json()["definition"]
    definition["steps"][0]["prompt"] = "draft carefully"
    saved = await client.patch(
        url,
        json={"definition": definition, "note": "Sharper draft prompt"},
        headers=bearer,
    )

    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["revision"] == 2
    assert body["editing"] is True
    assert body["definition"]["steps"][0]["prompt"] == "draft carefully"
    assert [step["id"] for step in body["definition"]["steps"]] == [
        str(step.id) for step in flow.definition.steps
    ]
    history = (await client.get(f"{url}revisions/", headers=bearer)).json()["items"]
    assert [(r["revision"], r["channel"]) for r in history] == [(2, "api"), (1, "mcp")]
    assert history[0]["note"] == "Sharper draft prompt"
    assert history[0]["changes"]["steps_changed"] == ["Draft"]

    # Name and description alone are a revision too; a no-op save is not.
    renamed = await client.patch(url, json={"name": "Weekly brief"}, headers=bearer)
    assert renamed.status_code == 200 and renamed.json()["revision"] == 3
    same = await client.patch(url, json={"name": "Weekly brief"}, headers=bearer)
    assert same.status_code == 200 and same.json()["revision"] == 3
    unknown = await client.patch(url, json={"colour": "blue"}, headers=bearer)
    assert unknown.status_code == 422


async def test_a_definition_with_problems_is_refused_with_the_problems_listed(
    client, chat_authored, flows_enabled, bearer
):
    flow = chat_authored["flow"]
    url = f"/api/v1/flows/{flow.id}/"
    await client.post(f"{url}edit-mode/", headers=bearer)
    definition = (await client.get(url, headers=bearer)).json()["definition"]
    definition["steps"][1]["template"] = "Done: {{steps.nope}}"

    refused = await client.patch(url, json={"definition": definition}, headers=bearer)

    assert refused.status_code == 422, refused.text
    body = refused.json()
    assert body["code"] == "flow_definition_problems"
    assert body["message"].startswith("The flow definition has problems:\n- ")
    assert body["details"]["problems"] == [
        "step 'wrap' template: {{steps.nope}} must name an earlier step"
    ]
    # Nothing was kept.
    assert (await client.get(url, headers=bearer)).json()["revision"] == 1


async def test_step_origins_tell_which_steps_the_panel_changed_since_the_chat(
    client, db_container, chat_authored, flows_enabled, bearer
):
    flow = chat_authored["flow"]
    url = f"/api/v1/flows/{flow.id}/"

    # The chat saves again (revision 2), then the panel changes one step.
    async with db_container() as container:
        await container.flow_service().update_flow(
            flow.id,
            definition=FlowDefinition(
                form_fields=flow.definition.form_fields,
                steps=[
                    LlmStep(
                        key="draft",
                        name="Draft",
                        prompt="draft, chat style",
                        input="{{form.topic}}",
                        model_id=chat_authored["model_id"],
                    ),
                    flow.definition.steps[1],
                ],
            ),
            channel="mcp",
            note="Chat style",
        )
    await client.post(f"{url}edit-mode/", headers=bearer)
    definition = (await client.get(url, headers=bearer)).json()["definition"]
    definition["steps"][0]["prompt"] = "draft, panel style"
    saved = await client.patch(url, json={"definition": definition}, headers=bearer)
    assert saved.status_code == 200, saved.text

    origins = {o["key"]: o for o in saved.json()["step_origins"]}
    assert set(origins) == {"draft", "wrap"}
    assert (origins["draft"]["revision"], origins["draft"]["channel"]) == (3, "api")
    assert origins["draft"]["assistant_revision"] == 2
    assert origins["draft"]["changed_by_user_id"] is not None
    assert origins["draft"]["changed_at"] is not None
    assert (origins["wrap"]["revision"], origins["wrap"]["channel"]) == (1, "mcp")
    assert origins["wrap"]["assistant_revision"] is None

    # Restoring the chat's version is an api save (the origin); the chat's
    # older, different version is what remains to go back to.
    restored = await client.post(f"{url}revisions/2/restore/", headers=bearer)
    assert restored.status_code == 200, restored.text
    origins = {o["key"]: o for o in restored.json()["step_origins"]}
    assert (origins["draft"]["revision"], origins["draft"]["channel"]) == (4, "api")
    assert origins["draft"]["assistant_revision"] == 1
