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
