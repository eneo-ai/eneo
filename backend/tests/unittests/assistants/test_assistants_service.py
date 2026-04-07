from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
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
    await setup.service.update_assistant(
        assistant_id=TEST_UUID, icon_id=uuid4()
    )

    space.is_completion_model_in_space.assert_not_called()


async def test_update_assistant_completion_model_in_space(setup: Setup):
    space = MagicMock()
    space.is_completion_model_in_space.return_value = True
    setup.service.space_service.get_space.return_value = space
    setup.service.repo.update.return_value = MagicMock(prompt="new prompt!", id=uuid4())

    await setup.service.update_assistant(TEST_UUID)


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
    space.get_completion_model.return_value = template_model

    created_assistant = MagicMock(id=uuid4())
    refreshed_space = MagicMock()
    refreshed_space.get_assistant.return_value = created_assistant

    setup.service.assistant_template_service.get_assistant_template.return_value = template
    setup.service.file_service.get_file_infos.return_value = []
    setup.service.factory.create_assistant.return_value = created_assistant
    setup.service.space_repo.update.return_value = refreshed_space

    await setup.service._create_from_template(
        space=space,
        template_data=template_data,
        completion_model=fallback_model,
    )

    expected_model = template_model if template_in_space else fallback_model
    assert setup.service.factory.create_assistant.call_args.kwargs["completion_model"] == expected_model


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

    setup.service.assistant_template_service.get_assistant_template.return_value = template
    setup.service.file_service.get_file_infos.return_value = []
    setup.service.factory.create_assistant.return_value = created_assistant
    setup.service.space_repo.update.return_value = refreshed_space

    await setup.service._create_from_template(
        space=MagicMock(id=uuid4()),
        template_data=template_data,
        completion_model=fallback_model,
    )

    assert setup.service.factory.create_assistant.call_args.kwargs["completion_model"] == fallback_model


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

    with pytest.raises(BadRequestException, match="Knowledge and MCP servers cannot both be active"):
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

    with pytest.raises(BadRequestException, match="Knowledge and MCP servers cannot both be active"):
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

    with pytest.raises(BadRequestException, match="Knowledge and MCP servers cannot both be active"):
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
