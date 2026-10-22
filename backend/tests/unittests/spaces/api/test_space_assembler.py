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
from eneo.roles.permissions import Permission
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


@pytest.mark.parametrize("kind", ["personal", "shared", "organization", "unlinked"])
def test_public_space_exposes_organization_identity_without_organization_membership(
    kind: str, space_assembler: SpaceAssembler
):
    organization_id = uuid4()
    space_id = organization_id if kind == "organization" else uuid4()
    parent_id = organization_id if kind in {"personal", "shared"} else None
    space = Space(
        id=space_id,
        tenant_id=TEST_UUID,
        tenant_space_id=parent_id,
        user_id=TEST_UUID if kind in {"personal", "unlinked"} else None,
        name=TEST_NAME,
        description=None,
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        mcp_servers=[],
        default_assistant=None,
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
    )

    public_space = space_assembler.from_space_to_model(space)

    expected_id = None if kind == "unlinked" else organization_id
    assert public_space.organization_space_id == expected_id
    assert public_space.model_dump(mode="json")["organization_space_id"] == (
        str(expected_id) if expected_id is not None else None
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


@pytest.mark.parametrize(
    "user_permissions, expected_for_organization_item",
    [
        ([], [ResourcePermission.READ]),
        (
            [Permission.ADMIN],
            [
                ResourcePermission.READ,
                ResourcePermission.EDIT,
                ResourcePermission.DELETE,
            ],
        ),
    ],
    ids=["editor", "admin"],
)
def test_items_from_the_organization_app_offer_changes_to_admins_only(
    space: Space,
    space_assembler: SpaceAssembler,
    user_permissions: list[Permission],
    expected_for_organization_item: list[ResourcePermission],
):
    """The integration service refuses anyone else a rename, sync or delete."""
    space_assembler.user.permissions = user_permissions
    actor = space_assembler.actor_manager.get_space_actor_from_space.return_value
    actor.get_integrations_permissions.return_value = [
        ResourcePermission.READ,
        ResourcePermission.EDIT,
        ResourcePermission.DELETE,
    ]
    organization_item = MagicMock(space_id=space.id)
    organization_item.user_integration.auth_type = "tenant_app"
    personal_item = MagicMock(space_id=space.id)
    personal_item.user_integration.auth_type = "user_oauth"
    space.integration_knowledge_list = [organization_item, personal_item]

    space_assembler._set_permissions_on_resources(space)

    assert organization_item.permissions == expected_for_organization_item
    assert personal_item.permissions == [
        ResourcePermission.READ,
        ResourcePermission.EDIT,
        ResourcePermission.DELETE,
    ]


@pytest.mark.parametrize("user_permissions", [[], [Permission.ADMIN]])
@pytest.mark.parametrize("auth_type", ["user_oauth", "tenant_app"])
def test_items_of_another_space_offer_no_changes(
    space: Space,
    space_assembler: SpaceAssembler,
    user_permissions: list[Permission],
    auth_type: str,
):
    """Inherited and distributed items are renamed, synced and deleted only
    from the space that owns them; the service refuses it here."""
    space_assembler.user.permissions = user_permissions
    actor = space_assembler.actor_manager.get_space_actor_from_space.return_value
    actor.get_integrations_permissions.return_value = [
        ResourcePermission.READ,
        ResourcePermission.EDIT,
        ResourcePermission.DELETE,
    ]
    distributed = MagicMock(space_id=uuid4())
    distributed.user_integration.auth_type = auth_type
    space.integration_knowledge_list = [distributed]

    space_assembler._set_permissions_on_resources(space)

    assert distributed.permissions == [ResourcePermission.READ]


@pytest.mark.parametrize(
    "level, expected",
    [
        ("read", [ResourcePermission.READ]),
        (
            "write",
            [
                ResourcePermission.READ,
                ResourcePermission.EDIT,
                ResourcePermission.DELETE,
            ],
        ),
    ],
)
def test_an_api_key_caps_what_each_item_offers(
    space: Space, space_assembler: SpaceAssembler, level: str, expected: list
):
    space_assembler.user.permissions = []
    space_assembler.user.active_api_key = MagicMock(
        resource_permissions={
            "assistants": "read",
            "apps": "read",
            "spaces": "read",
            "knowledge": level,
        }
    )
    actor = space_assembler.actor_manager.get_space_actor_from_space.return_value
    actor.get_integrations_permissions.return_value = [
        ResourcePermission.READ,
        ResourcePermission.EDIT,
        ResourcePermission.DELETE,
    ]
    own = MagicMock(space_id=space.id)
    own.user_integration.auth_type = "user_oauth"
    space.integration_knowledge_list = [own]

    assert (
        space_assembler.integration_item_permissions(
            own, space_id=space.id, actor=actor
        )
        == expected
    )


def test_served_items_are_capped_like_collections_and_websites(
    space_assembler: SpaceAssembler,
):
    space_assembler.user.active_api_key = MagicMock(
        resource_permissions={"knowledge": "read"}
    )
    item = MagicMock(
        permissions=[
            ResourcePermission.READ,
            ResourcePermission.EDIT,
            ResourcePermission.DELETE,
        ]
    )
    knowledge = MagicMock()
    knowledge.integration_knowledge_list.items = [item]

    space_assembler._apply_api_key_resource_caps(MagicMock(), knowledge)

    assert item.permissions == [ResourcePermission.READ]


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
            tenant_id=uuid4(),
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
