from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import ModelKwargs
from intric.assistants.api.assistant_models import AssistantType, DefaultAssistant
from intric.files.file_models import FileRestrictions, Limit
from intric.questions.question import UseTools
from intric.spaces.api.space_assembler import SpaceAssembler
from intric.spaces.api.space_models import SpaceMember, SpaceRoleValue
from intric.spaces.space import Space
from tests.fixtures import (
    TEST_EMBEDDING_MODEL,
    TEST_MODEL_CHATGPT,
    TEST_MODEL_GPT4,
    TEST_USER,
    TEST_UUID,
)

TEST_NAME = "test_name"


TEST_DEFAULT_ASSISTANT = DefaultAssistant(
    id=TEST_UUID,
    name=TEST_NAME,
    space_id=TEST_UUID,
    completion_model_kwargs=ModelKwargs(),
    logging_enabled=False,
    attachments=[],
    allowed_attachments=FileRestrictions(
        accepted_file_types=[], limit=Limit(max_files=0, max_size=0)
    ),
    groups=[],
    websites=[],
    integration_knowledge_list=[],
    mcp_servers=[],
    completion_model=TEST_MODEL_CHATGPT,
    user=TEST_USER,
    tools=UseTools(assistants=[]),
    type=AssistantType.DEFAULT_ASSISTANT,
    insight_enabled=False,
)


@pytest.fixture
def space_assembler():
    assistant_assembler = MagicMock()
    assistant_assembler.from_assistant_to_default_assistant_model.return_value = (
        TEST_DEFAULT_ASSISTANT
    )
    return SpaceAssembler(
        MagicMock(),
        assistant_assembler=assistant_assembler,
        completion_model_assembler=MagicMock(),
        actor_manager=MagicMock(),
    )


@pytest.fixture
def space():
    space = MagicMock(
        id=TEST_UUID,
        user_id=None,
        tenant_id=TEST_UUID,
        description=None,
        embedding_models=[],
        completion_models=[],
        assistants=[],
        services=[],
        websites=[],
        groups=[],
        members={},
        security_classification=None,
        icon_id=None,
    )
    space.name = TEST_NAME

    return space


def test_from_personal_space_to_model_sets_personal(
    space: Space, space_assembler: SpaceAssembler
):
    space.user_id = TEST_UUID

    space_public = space_assembler.from_space_to_model(space)

    assert space_public.personal


def test_space_members_ordering(space: Space, space_assembler: SpaceAssembler):
    admin = SpaceMember(
        id=TEST_UUID,
        email="admin@example.com",
        username="admin",
        role=SpaceRoleValue.ADMIN,
    )
    editor = SpaceMember(
        id=uuid4(),
        email="editor@example.com",
        username="editor",
        role=SpaceRoleValue.EDITOR,
    )
    editor_2 = SpaceMember(
        id=uuid4(),
        email="editor2@example.com",
        username="editor2",
        role=SpaceRoleValue.EDITOR,
    )

    space.members = {admin.id: admin, editor.id: editor, editor_2.id: editor_2}

    space_assembler.user = MagicMock(id=editor_2.id)
    space_public = space_assembler.from_space_to_model(space)

    assert space_public.members.items == [editor_2, admin, editor]


def test_only_org_enabled_completion_models_are_returned(
    space: Space, space_assembler: SpaceAssembler
):
    space.completion_models = [TEST_MODEL_GPT4]

    space_public = space_assembler.from_space_to_model(space)

    assert space_public.completion_models == []


def test_only_org_enabled_embedding_models_are_returned(
    space: Space, space_assembler: SpaceAssembler
):
    space.embedding_models = [TEST_EMBEDDING_MODEL]

    space_public = space_assembler.from_space_to_model(space)

    assert space_public.embedding_models == []


def test_no_applications_included_in_space_sparse(
    space: Space, space_assembler: SpaceAssembler
):
    space_sparse = space_assembler.from_space_to_sparse_model(space, include_applications=False)

    assert space_sparse.applications == None


def test_applications_included_in_space_sparse(
    space: Space, space_assembler: SpaceAssembler
):
    space_sparse = space_assembler.from_space_to_sparse_model(space, include_applications=True)

    assert space_sparse.applications != None