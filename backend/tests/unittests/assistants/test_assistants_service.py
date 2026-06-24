from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import ModelKwargs
from intric.assistants.api.assistant_models import (
    AssistantBase,
    AssistantCreatePublic,
    AssistantUpdatePublic,
)
from intric.assistants.assistant_service import AssistantService
from intric.main.exceptions import (
    BadRequestException,
    ModelNotAvailableException,
    UnauthorizedException,
)
from intric.main.models import ModelId
from intric.prompts.api.prompt_models import PromptCreate
from tests.fixtures import (
    TEST_ASSISTANT,
    TEST_COLLECTION,
    TEST_MODEL_GPT4,
    TEST_USER,
    TEST_UUID,
)


@dataclass
class Setup:
    assistant: AssistantBase
    service: AssistantService
    group_service: AsyncMock


@pytest.fixture(name="setup")
def setup_fixture():
    repo = AsyncMock()
    # repo.session.execute() is used by MCP validation; return an object whose
    # fetchall() yields an empty list so the set comprehension works.
    mock_db_result = MagicMock()
    mock_db_result.fetchall.return_value = []
    repo.session.execute = AsyncMock(return_value=mock_db_result)
    user = TEST_USER
    auth_service = MagicMock()
    assistant = AssistantCreatePublic(
        name="test_name",
        prompt=PromptCreate(text="test_prompt"),
        space_id=TEST_UUID,
        completion_model=ModelId(id=TEST_MODEL_GPT4.id),
    )

    space_repo = AsyncMock()
    mock_assistant = MagicMock()
    mock_assistant.mcp_servers = []
    mock_assistant.collections = []
    mock_assistant.websites = []
    mock_assistant.integration_knowledge_list = []
    mock_assistant.has_knowledge.return_value = False
    mock_assistant.has_mcp.return_value = False
    mock_space = MagicMock()
    mock_space.get_assistant.return_value = mock_assistant
    space_repo.get_space_by_assistant.return_value = mock_space

    # The helper-assistant guard checks both repos before every ``ask``;
    # default them to "not a helper" so non-guard tests in this file don't
    # incidentally trip the 403 path.
    role_repo_mock = AsyncMock()
    role_repo_mock.exists_active_for_assistant.return_value = False
    history_repo_mock = AsyncMock()
    history_repo_mock.exists_for_assistant.return_value = False

    service = AssistantService(
        repo=repo,
        space_repo=space_repo,
        user=user,
        auth_service=auth_service,
        service_repo=AsyncMock(),
        step_repo=AsyncMock(),
        completion_model_crud_service=AsyncMock(),
        space_service=AsyncMock(),
        factory=MagicMock(),
        prompt_service=AsyncMock(),
        file_service=AsyncMock(),
        assistant_template_service=AsyncMock(),
        session_service=AsyncMock(),
        actor_manager=MagicMock(),
        integration_knowledge_repo=AsyncMock(),
        completion_service=AsyncMock(),
        references_service=AsyncMock(),
        icon_repo=AsyncMock(),
        org_space_assistant_role_repo=role_repo_mock,
        help_assistant_assignment_history_repo=history_repo_mock,
    )

    setup = Setup(assistant=assistant, service=service, group_service=AsyncMock())

    return setup


@pytest.fixture
async def assistant_service():
    return AssistantService(
        repo=AsyncMock(),
        user=MagicMock(id=uuid4()),
        auth_service=MagicMock(),
        service_repo=AsyncMock(),
        step_repo=AsyncMock(),
        completion_model_crud_service=AsyncMock(),
        space_service=AsyncMock(),
        factory=AsyncMock(),
        prompt_repo=AsyncMock(),
        integration_knowledge_repo=AsyncMock(),
        icon_repo=AsyncMock(),
    )


def with_two_different_groups(setup: Setup, attr: str, value_1: Any, value_2: Any):
    collection_1 = deepcopy(TEST_COLLECTION)
    collection_2 = deepcopy(TEST_COLLECTION)

    setattr(collection_1, attr, value_1)
    setattr(collection_2, attr, value_2)

    assistant = deepcopy(TEST_ASSISTANT)
    assistant.collections = [collection_1, collection_2]

    setup.service.repo.add.return_value = assistant
    setup.service.repo.update.return_value = assistant
    setup.service.user.id = 1
    setup.service.user.tenant_id = 1


async def test_update_space_assistant_not_member(setup: Setup):
    assistant_update = AssistantUpdatePublic(name="new name!")

    actor = MagicMock()
    actor.can_edit_assistants.return_value = False
    setup.service.actor_manager.get_space_actor_from_space.return_value = actor

    with pytest.raises(UnauthorizedException):
        await setup.service.update_assistant(assistant_update, TEST_UUID)


async def test_update_space_assistant_member(setup: Setup):
    assistant_update = AssistantUpdatePublic(name="new name!")

    await setup.service.update_assistant(assistant_update, TEST_UUID)


async def test_is_help_assistant_true_when_active_role_exists(setup: Setup):
    assistant_id = uuid4()
    role_repo = setup.service.org_space_assistant_role_repo
    role_repo.exists_active_for_assistant.return_value = True

    assert await setup.service.is_help_assistant(assistant_id) is True
    role_repo.exists_active_for_assistant.assert_awaited_once_with(assistant_id)


async def test_is_help_assistant_false_when_no_active_role(setup: Setup):
    assistant_id = uuid4()
    role_repo = setup.service.org_space_assistant_role_repo
    role_repo.exists_active_for_assistant.return_value = False

    assert await setup.service.is_help_assistant(assistant_id) is False


async def test_delete_space_assistant_not_member(setup: Setup):
    actor = MagicMock()
    actor.can_delete_assistants.return_value = False
    setup.service.actor_manager.get_space_actor_from_space.return_value = actor

    with pytest.raises(UnauthorizedException):
        await setup.service.delete_assistant(TEST_UUID)


async def test_delete_space_assistant_member(setup: Setup):
    await setup.service.delete_assistant(TEST_UUID)


async def test_update_assistant_completion_model_not_in_space(setup: Setup):
    space = MagicMock()
    space.is_completion_model_in_space.return_value = False
    setup.service.space_repo.get_space_by_assistant.return_value = space

    with pytest.raises(
        BadRequestException,
        match="Completion model is not in space.",
    ):
        await setup.service.update_assistant(
            assistant_id=TEST_UUID, completion_model_id=uuid4()
        )


async def test_partial_update_skips_completion_model_validation(setup: Setup):
    """Partial updates (e.g. icon_id) should not fail when completion model is stale."""
    space = MagicMock()
    space.is_completion_model_in_space.return_value = False
    setup.service.space_repo.get_space_by_assistant.return_value = space

    # Should NOT raise — we're only changing icon_id, not completion model
    await setup.service.update_assistant(assistant_id=TEST_UUID, icon_id=uuid4())

    space.is_completion_model_in_space.assert_not_called()


async def test_update_assistant_completion_model_in_space(setup: Setup):
    space = MagicMock()
    space.is_completion_model_in_space.return_value = True
    setup.service.space_service.get_space.return_value = space
    setup.service.repo.update.return_value = MagicMock(prompt="new prompt!", id=uuid4())

    await setup.service.update_assistant(TEST_UUID)


async def test_update_assistant_persists_empty_prompt_to_clear_it(setup: Setup):
    # Regression: clearing the prompt textarea in the assistant edit page and
    # pressing Save used to silently keep the old prompt because the service
    # treated ``prompt.text == ""`` as "no prompt update" (truthy guard). An
    # empty string here is a deliberate "clear the prompt" action, so the
    # service must call create_prompt with the empty string just like it
    # would for any other value.
    await setup.service.update_assistant(
        assistant_id=TEST_UUID,
        prompt=PromptCreate(text="", description=""),
    )

    setup.service.prompt_service.create_prompt.assert_awaited_once()
    create_args = setup.service.prompt_service.create_prompt.await_args
    # text is the first positional arg; description the second.
    assert create_args.args[0] == ""
    assert create_args.args[1] == ""


async def test_update_assistant_skips_prompt_creation_when_field_omitted(setup: Setup):
    # Counterpart to the regression above — make sure the fix did not flip
    # the other behaviour. A partial update that does NOT touch the prompt
    # (``prompt=None``, the field's default) must NOT create a new prompt
    # version, otherwise every unrelated edit (e.g. just renaming the
    # assistant) would pollute the prompt history.
    await setup.service.update_assistant(assistant_id=TEST_UUID, name="renamed")

    setup.service.prompt_service.create_prompt.assert_not_awaited()


def configure_personal_default_assistant(
    setup: Setup, *, can_manage_assistants: bool = False
):
    assistant = setup.service.space_repo.get_space_by_assistant.return_value.get_assistant.return_value
    assistant.id = TEST_UUID
    assistant.collections = []
    assistant.websites = []
    assistant.integration_knowledge_list = []

    space = setup.service.space_repo.get_space_by_assistant.return_value
    space.is_personal.return_value = True
    space.default_assistant = MagicMock(id=TEST_UUID)
    space.get_assistant.return_value = assistant
    space.is_completion_model_available.return_value = True
    space.is_completion_model_in_space.return_value = True
    setup.service.space_repo.update.return_value = space

    actor = MagicMock()
    actor.can_edit_default_assistant.return_value = True
    actor.can_edit_assistants.return_value = can_manage_assistants
    actor.can_toggle_insight.return_value = True
    actor.get_assistant_permissions.return_value = []
    setup.service.actor_manager.get_space_actor_from_space.return_value = actor

    return assistant, space


async def test_personal_chat_can_change_personal_default_completion_model(setup: Setup):
    assistant, space = configure_personal_default_assistant(setup)
    completion_model_id = uuid4()
    completion_model = MagicMock(id=completion_model_id)
    space.get_completion_model.return_value = completion_model

    await setup.service.update_assistant(
        assistant_id=TEST_UUID,
        completion_model_id=completion_model_id,
    )

    assistant.update.assert_called_once()
    assert assistant.update.call_args.kwargs["completion_model"] == completion_model


@pytest.mark.parametrize(
    "update",
    [
        {"name": "Renamed"},
        {"prompt": PromptCreate(text="Changed prompt")},
        {"completion_model_kwargs": ModelKwargs()},
        {"logging_enabled": False},
        {"groups": []},
        {"websites": []},
        {"integration_knowledge_ids": []},
        {"mcp_server_ids": []},
        {"mcp_tools": []},
        {"attachment_ids": []},
        {"description": None},
        {"insight_enabled": False},
        {"data_retention_days": None},
        {"metadata_json": {}},
        {"icon_id": uuid4()},
    ],
)
async def test_personal_chat_cannot_change_extended_default_assistant_fields(
    setup: Setup, update: dict[str, Any]
):
    assistant, _ = configure_personal_default_assistant(setup)

    with pytest.raises(
        UnauthorizedException,
        match="only allows changing the personal assistant's completion model",
    ):
        await setup.service.update_assistant(assistant_id=TEST_UUID, **update)

    assistant.update.assert_not_called()


async def test_assistant_managers_can_edit_extended_personal_default_fields(
    setup: Setup,
):
    assistant, _ = configure_personal_default_assistant(
        setup, can_manage_assistants=True
    )

    await setup.service.update_assistant(
        assistant_id=TEST_UUID,
        name="Renamed",
    )

    assert assistant.update.call_args.kwargs["name"] == "Renamed"


@pytest.mark.parametrize("template_in_space", [True, False])
async def test_create_from_template_prefers_template_model_when_available(
    setup: Setup,
    template_in_space: bool,
):
    fallback_model = MagicMock(id=uuid4())
    template_model = MagicMock(id=uuid4())
    template = MagicMock(
        completion_model=template_model,
        completion_model_kwargs={},
        prompt_text=None,
        name="Template",
        description="Description",
    )
    template.validate_assistant_wizard_data = MagicMock()

    template_data = MagicMock(id=uuid4())
    template_data.get_ids_by_type.return_value = []

    space = MagicMock()
    space.id = uuid4()
    space.is_completion_model_in_space.return_value = template_in_space
    space.is_completion_model_available.return_value = template_in_space
    space.get_completion_model.return_value = template_model

    created_assistant = MagicMock(id=uuid4())
    refreshed_space = MagicMock()
    refreshed_space.get_assistant.return_value = created_assistant

    setup.service.assistant_template_service.get_assistant_template.return_value = (
        template
    )
    setup.service.file_service.get_file_infos.return_value = []
    setup.service.factory.create_assistant.return_value = created_assistant
    setup.service.space_repo.update.return_value = refreshed_space

    await setup.service._create_from_template(
        space=space,
        template_data=template_data,
        completion_model=fallback_model,
    )

    expected_model = template_model if template_in_space else fallback_model
    assert (
        setup.service.factory.create_assistant.call_args.kwargs["completion_model"]
        == expected_model
    )


async def test_create_from_template_keeps_fallback_when_template_has_no_model(
    setup: Setup,
):
    fallback_model = MagicMock(id=uuid4())
    template = MagicMock(
        completion_model=None,
        completion_model_kwargs={},
        prompt_text=None,
        name="Template",
        description="Description",
    )
    template.validate_assistant_wizard_data = MagicMock()

    template_data = MagicMock(id=uuid4())
    template_data.get_ids_by_type.return_value = []

    created_assistant = MagicMock(id=uuid4())
    refreshed_space = MagicMock()
    refreshed_space.get_assistant.return_value = created_assistant

    setup.service.assistant_template_service.get_assistant_template.return_value = (
        template
    )
    setup.service.file_service.get_file_infos.return_value = []
    setup.service.factory.create_assistant.return_value = created_assistant
    setup.service.space_repo.update.return_value = refreshed_space

    await setup.service._create_from_template(
        space=MagicMock(id=uuid4()),
        template_data=template_data,
        completion_model=fallback_model,
    )

    assert (
        setup.service.factory.create_assistant.call_args.kwargs["completion_model"]
        == fallback_model
    )


async def test_update_rejects_adding_mcp_when_knowledge_exists(setup: Setup):
    """Cannot add MCP servers when assistant already has knowledge."""
    assistant = MagicMock()
    assistant.has_knowledge.return_value = True
    assistant.has_mcp.return_value = False
    assistant.mcp_servers = []

    space = MagicMock()
    space.get_assistant.return_value = assistant
    setup.service.space_repo.get_space_by_assistant.return_value = space

    mcp_id = uuid4()
    # Mock DB to return the MCP server as tenant-enabled and space-assigned
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [(mcp_id,)]
    setup.service.repo.session.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(
        BadRequestException, match="Knowledge and MCP servers cannot both be active"
    ):
        await setup.service.update_assistant(
            assistant_id=TEST_UUID,
            mcp_server_ids=[mcp_id],
        )


async def test_update_rejects_adding_knowledge_when_mcp_exists(setup: Setup):
    """Cannot add knowledge when assistant already has MCP servers."""
    assistant = MagicMock()
    assistant.has_knowledge.return_value = False
    assistant.has_mcp.return_value = True
    assistant.mcp_servers = [MagicMock()]

    # After update() is called with groups, has_knowledge should return True
    assistant.update.side_effect = lambda **kwargs: setattr(
        assistant, "has_knowledge", MagicMock(return_value=True)
    )

    space = MagicMock()
    space.get_assistant.return_value = assistant
    setup.service.space_repo.get_space_by_assistant.return_value = space

    with pytest.raises(
        BadRequestException, match="Knowledge and MCP servers cannot both be active"
    ):
        await setup.service.update_assistant(
            assistant_id=TEST_UUID,
            groups=[uuid4()],
        )


async def test_update_rejects_keeping_both_when_legacy_assistant(setup: Setup):
    """Legacy edge case: assistant has both, updating MCP with non-empty list is still rejected."""
    assistant = MagicMock()
    assistant.has_knowledge.return_value = True
    assistant.has_mcp.return_value = True
    assistant.mcp_servers = [MagicMock()]

    space = MagicMock()
    space.get_assistant.return_value = assistant
    setup.service.space_repo.get_space_by_assistant.return_value = space

    mcp_id = uuid4()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [(mcp_id,)]
    setup.service.repo.session.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(
        BadRequestException, match="Knowledge and MCP servers cannot both be active"
    ):
        await setup.service.update_assistant(
            assistant_id=TEST_UUID,
            mcp_server_ids=[mcp_id],
        )


async def test_update_allows_removing_mcp_when_both_exist(setup: Setup):
    """Legacy edge case: assistant has both, user removes MCP to resolve conflict."""
    assistant = MagicMock()
    assistant.has_knowledge.return_value = True
    assistant.has_mcp.return_value = True

    space = MagicMock()
    space.get_assistant.return_value = assistant
    setup.service.space_repo.get_space_by_assistant.return_value = space

    # Removing all MCP servers should succeed
    await setup.service.update_assistant(
        assistant_id=TEST_UUID,
        mcp_server_ids=[],
    )


async def test_update_allows_removing_knowledge_when_both_exist(setup: Setup):
    """Legacy edge case: assistant has both, user removes knowledge to resolve conflict."""
    assistant = MagicMock()
    assistant.has_knowledge.return_value = True
    assistant.has_mcp.return_value = True

    space = MagicMock()
    space.get_assistant.return_value = assistant
    setup.service.space_repo.get_space_by_assistant.return_value = space

    # Removing all knowledge should succeed (has_knowledge returns False after update)
    assistant.update.side_effect = lambda **kwargs: setattr(
        assistant, "has_knowledge", MagicMock(return_value=False)
    )
    await setup.service.update_assistant(
        assistant_id=TEST_UUID,
        groups=[],
        websites=[],
        integration_knowledge_ids=[],
    )


async def test_error_when_assistant_cannot_be_used_in_space(setup: Setup):
    assistant = MagicMock(completion_model_id=uuid4(), space_id=uuid4())
    space = MagicMock()
    space.get_assistant.return_value = assistant
    space.can_ask_assistant.side_effect = ModelNotAvailableException(
        "The selected AI model is not available in this space."
    )
    setup.service.space_repo.get_space_by_assistant.return_value = space

    with pytest.raises(ModelNotAvailableException):
        await setup.service.ask(question="hello", assistant_id=MagicMock())


async def test_publish_assistant_unauthorized_has_actionable_message(setup: Setup):
    space = MagicMock()
    space.get_assistant.return_value = MagicMock()
    setup.service.space_repo.get_space_by_assistant.return_value = space

    actor = MagicMock()
    actor.can_publish_assistants.return_value = False
    setup.service.actor_manager.get_space_actor_from_space.return_value = actor

    with pytest.raises(UnauthorizedException) as exc_info:
        await setup.service.publish_assistant(TEST_UUID, True)

    assert "Publishing assistants" in str(exc_info.value)


def _mock_file(file_type, parent_file_id=None):
    return MagicMock(id=uuid4(), file_type=file_type, parent_file_id=parent_file_id)


async def test_vision_derivatives_expand_completion_files_and_attachments(
    setup: Setup,
):
    from intric.files.file_models import FileType

    pdf = _mock_file(FileType.TEXT)
    derived = _mock_file(FileType.IMAGE, parent_file_id=pdf.id)
    attachment = _mock_file(FileType.TEXT)
    attachment_image = _mock_file(FileType.IMAGE, parent_file_id=attachment.id)
    assistant = MagicMock()
    assistant.attachments = [attachment]
    session = MagicMock(questions=[])
    setup.service.file_service.with_derived_images.side_effect = [
        [attachment, attachment_image],
        [pdf, derived],
    ]

    result = await setup.service._with_vision_derivatives(
        files=[pdf],
        session=session,
        assistant=assistant,
        completion_model=MagicMock(vision=True),
    )

    assert result == [pdf, derived]
    assert assistant.attachments == [attachment, attachment_image]


async def test_vision_derivatives_skip_everything_without_vision(setup: Setup):
    from intric.files.file_models import FileType

    pdf = _mock_file(FileType.TEXT)
    assistant = MagicMock()
    session = MagicMock(questions=[])

    result = await setup.service._with_vision_derivatives(
        files=[pdf],
        session=session,
        assistant=assistant,
        completion_model=MagicMock(vision=False),
    )

    assert result == [pdf]
    setup.service.file_service.with_derived_images.assert_not_awaited()
    setup.service.file_service.get_derived_images.assert_not_awaited()


async def test_vision_derivatives_gate_on_effective_model_not_configured(
    setup: Setup,
):
    """Governance can steer to a different model than the assistant's own —
    derived images must follow the model that actually answers."""
    from intric.files.file_models import FileType

    pdf = _mock_file(FileType.TEXT)
    derived = _mock_file(FileType.IMAGE, parent_file_id=pdf.id)
    assistant = MagicMock()
    assistant.completion_model.vision = False  # configured model lacks vision
    assistant.attachments = []
    session = MagicMock(questions=[])
    setup.service.file_service.with_derived_images.return_value = [pdf, derived]

    result = await setup.service._with_vision_derivatives(
        files=[pdf],
        session=session,
        assistant=assistant,
        completion_model=MagicMock(vision=True),  # policy-enforced model has it
    )

    assert result == [pdf, derived]


async def test_history_derivatives_attach_to_their_own_question(setup: Setup):
    from intric.files.file_models import FileType

    pdf_one = _mock_file(FileType.TEXT)
    pdf_two = _mock_file(FileType.TEXT)
    derived_one = _mock_file(FileType.IMAGE, parent_file_id=pdf_one.id)
    derived_two = _mock_file(FileType.IMAGE, parent_file_id=pdf_two.id)
    question_one = MagicMock(files=[pdf_one])
    question_two = MagicMock(files=[pdf_two])
    session = MagicMock(questions=[question_one, question_two])
    setup.service.file_service.get_derived_images.return_value = [
        derived_one,
        derived_two,
    ]

    await setup.service._attach_history_derivatives(session=session)

    assert question_one.files == [pdf_one, derived_one]
    assert question_two.files == [pdf_two, derived_two]
    (_, kwargs) = setup.service.file_service.get_derived_images.await_args
    assert set(kwargs["parent_ids"]) == {pdf_one.id, pdf_two.id}


async def test_history_derivatives_do_not_duplicate_present_images(setup: Setup):
    from intric.files.file_models import FileType

    pdf = _mock_file(FileType.TEXT)
    derived = _mock_file(FileType.IMAGE, parent_file_id=pdf.id)
    question = MagicMock(files=[pdf, derived])
    session = MagicMock(questions=[question])
    setup.service.file_service.get_derived_images.return_value = [derived]

    await setup.service._attach_history_derivatives(session=session)

    assert question.files == [pdf, derived]
