from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.actors.actors.space_actor import SpaceAccessFacts
from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.api.assistant_models import AssistantType, DefaultAssistant
from eneo.files.file_models import FileRestrictions, Limit
from eneo.main.models import ResourcePermission
from eneo.questions.question import UseTools
from eneo.spaces.api.space_assembler import SpaceAssembler
from eneo.spaces.api.space_models import SpaceMember, SpaceRoleValue
from eneo.spaces.space import Space
from eneo.spaces.space_applications_projection import (
    AssistantApplicationsProjection,
    SpaceApplicationsProjection,
)
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
    user = MagicMock(active_api_key=None)
    return SpaceAssembler(
        user,
        assistant_assembler=assistant_assembler,
        completion_model_assembler=MagicMock(),
        actor_manager=MagicMock(),
    )


def test_space_exposes_skill_permissions_for_session_user(
    space: Space, space_assembler: SpaceAssembler
):
    actor = space_assembler.actor_manager.get_space_actor_from_space.return_value
    actor.can_read_skills.return_value = True
    actor.can_create_skills.return_value = True
    actor.can_edit_skills.return_value = True
    actor.can_delete_skills.return_value = False

    space_public = space_assembler.from_space_to_model(space)

    assert space_public.skill_permissions == [
        ResourcePermission.READ,
        ResourcePermission.CREATE,
        ResourcePermission.EDIT,
    ]


def test_space_hides_skill_permissions_from_api_keys(
    space: Space, space_assembler: SpaceAssembler
):
    space_assembler.user.active_api_key = MagicMock()
    actor = space_assembler.actor_manager.get_space_actor_from_space.return_value
    actor.can_read_skills.return_value = True
    actor.can_create_skills.return_value = True
    actor.can_edit_skills.return_value = True
    actor.can_delete_skills.return_value = True

    space_public = space_assembler.from_space_to_model(space)

    assert space_public.skill_permissions == []


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
    space_sparse = space_assembler.from_space_to_sparse_model(
        space, include_applications=False
    )

    assert space_sparse.applications == None


def test_applications_included_in_space_sparse(
    space: Space, space_assembler: SpaceAssembler
):
    space_sparse = space_assembler.from_space_to_sparse_model(
        space, include_applications=True
    )

    assert space_sparse.applications != None


def test_from_applications_projection_maps_authorized_sparse_items(
    space_assembler: SpaceAssembler,
):
    assistant_id = uuid4()
    now = datetime.now(UTC)
    projection = SpaceApplicationsProjection(
        access=SpaceAccessFacts(
            id=uuid4(),
            user_id=None,
            tenant_space_id=uuid4(),
            members={},
            group_members={},
            default_assistant_id=None,
            assistant_ids=frozenset({assistant_id}),
            app_ids=frozenset(),
        ),
        assistants=(
            AssistantApplicationsProjection(
                id=assistant_id,
                created_at=now,
                updated_at=now,
                name="Sparse assistant",
                completion_model_kwargs=ModelKwargs(),
                logging_enabled=True,
                user_id=uuid4(),
                published=True,
                description=None,
                metadata_json=None,
                icon_id=None,
                completion_model_id=None,
                insight_enabled=False,
            ),
        ),
        group_chats=(),
        apps=(),
        services=(),
    )
    actor = space_assembler.actor_manager.get_space_actor.return_value
    actor.can_read_assistant.return_value = True
    actor.get_assistant_permissions.return_value = [ResourcePermission.READ]

    applications = space_assembler.from_applications_projection(projection)

    assert [assistant.id for assistant in applications.assistants.items] == [
        assistant_id
    ]
    assert applications.assistants.items[0].permissions == [ResourcePermission.READ]
    space_assembler.actor_manager.get_space_actor.assert_called_once_with(
        projection.access
    )
