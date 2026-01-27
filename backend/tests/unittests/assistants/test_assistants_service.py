from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from intric.assistants.api.assistant_models import (
    AskAssistant,
    AssistantBase,
    AssistantCreatePublic,
    AssistantUpdatePublic,
)
from intric.assistants.assistant_service import AssistantService
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.main.models import ModelId
from intric.prompts.api.prompt_models import PromptCreate
from pydantic import ValidationError
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
    user = TEST_USER
    auth_service = MagicMock()
    assistant = AssistantCreatePublic(
        name="test_name",
        prompt=PromptCreate(text="test_prompt"),
        space_id=TEST_UUID,
        completion_model=ModelId(id=TEST_MODEL_GPT4.id),
    )

    space_repo = AsyncMock()
    space_repo.get_space_by_assistant.return_value = MagicMock()

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


async def test_ask_assistant_model():
    files_number = get_settings().max_in_question + 1
    files = [ModelId(id=uuid4()) for _ in range(files_number)]

    with pytest.raises(ValidationError):
        AskAssistant(question="test", files=files)


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
        await setup.service.update_assistant(TEST_UUID)


async def test_update_assistant_completion_model_in_space(setup: Setup):
    space = MagicMock()
    space.is_completion_model_in_space.return_value = True
    setup.service.space_service.get_space.return_value = space
    setup.service.repo.update.return_value = MagicMock(prompt="new prompt!", id=uuid4())

    await setup.service.update_assistant(TEST_UUID)


async def test_error_when_assistant_cannot_be_used_in_space(setup: Setup):
    assistant = MagicMock(completion_model_id=uuid4(), space_id=uuid4())
    space = MagicMock()
    space.get_assistant.return_value = assistant
    space.can_ask_assistant.return_value = False
    setup.service.space_repo.get_space_by_assistant.return_value = space

    with pytest.raises(UnauthorizedException):
        await setup.service.ask(question="hello", assistant_id=MagicMock())
