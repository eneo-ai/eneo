from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from intric.main.exceptions import BadRequestException, NotFoundException, UnauthorizedException
from intric.spaces.space import UNAUTHORIZED_EXCEPTION_MESSAGE, Space, SpaceRoleValue


@pytest.fixture
def space():
    return Space(
        id=None,
        tenant_id=None,
        tenant_space_id=None,
        user_id=None,
        name=MagicMock(),
        description=None,
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        mcp_servers=[],
        default_assistant=MagicMock(),
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
    )


def test_get_latest_available_embedding_model(space: Space):
    embedding_models = [
        MagicMock(created_at=datetime(2024, 1, 3 - i), can_access=True) for i in range(3)
    ]
    space.embedding_models = embedding_models

    embedding_model = space.get_latest_embedding_model()

    assert embedding_model == embedding_models[0]


def test_get_latest_available_embedding_model_when_not_ordered(space: Space):
    embedding_models = [
        MagicMock(created_at=datetime(2024, 1, 3 - i), can_access=True) for i in range(3)
    ]
    embedding_models = list(reversed(embedding_models))
    space.embedding_models = embedding_models

    embedding_model = space.get_latest_embedding_model()

    assert embedding_model == embedding_models[2]


def test_set_embedding_model_when_all_are_not_accessible(space: Space):
    embedding_models = [
        MagicMock(created_at=datetime(2024, 1, 3), can_access=False),
        MagicMock(created_at=datetime(2024, 1, 2), can_access=True),
        MagicMock(created_at=datetime(2024, 1, 1), can_access=True),
    ]

    with pytest.raises(UnauthorizedException):
        space.embedding_models = embedding_models


def test_space_update_embedding_model_no_acces(space: Space):
    embedding_model = MagicMock(can_access=False)

    with pytest.raises(UnauthorizedException, match=UNAUTHORIZED_EXCEPTION_MESSAGE):
        space.embedding_models = [embedding_model]


def test_space_update_embedding_models(space: Space):
    embedding_model = MagicMock(can_access=True)

    space.embedding_models = [embedding_model]

    assert space.embedding_models == [embedding_model]


def test_space_update_completion_models_no_access(space: Space):
    completion_model = MagicMock(can_access=False)

    with pytest.raises(UnauthorizedException, match=UNAUTHORIZED_EXCEPTION_MESSAGE):
        space.completion_models = [completion_model]


def test_space_update_completion_models(space: Space):
    completion_model = MagicMock(can_access=True)

    space.completion_models = [completion_model]

    assert space.completion_models == [completion_model]


def test_get_latest_completion_model(space: Space):
    completion_models = [MagicMock(created_at=datetime(2024, 1, 3 - i)) for i in range(3)]
    completion_models = list(reversed(completion_models))

    space.completion_models = completion_models

    assert space.get_latest_completion_model() == completion_models[2]


def test_get_latest_completion_model_none(space: Space):
    space.completion_models = []

    assert space.get_latest_completion_model() is None


def test_get_default_model(space: Space):
    default_model = MagicMock()
    default_model.is_org_default = True
    default_model.can_access = True
    space.completion_models = [default_model]
    assert space.get_default_completion_model() is not None

    # Disable access
    default_model.can_access = False
    with pytest.raises(NotFoundException):
        space.get_default_completion_model()

    non_default_model = MagicMock()
    non_default_model.is_org_default = False
    non_default_model.can_access = True
    space.completion_models = [non_default_model]
    assert space.get_default_completion_model() is not None


def test_is_completion_model_in_space(space: Space):
    completion_model = MagicMock(id=uuid4())
    space.completion_models = [completion_model]

    assert space.is_completion_model_in_space(completion_model.id)


def test_is_completion_model_not_in_space(space: Space):
    assert not space.is_completion_model_in_space(uuid4())


def test_is_group_in_space(space: Space):
    group = MagicMock(id=uuid4())
    space.collections = [group]

    assert space.is_group_in_space(group.id)


def test_is_group_not_in_space(space: Space):
    assert not space.is_group_in_space(uuid4())


def test_is_website_in_space(space: Space):
    website = MagicMock(id=uuid4())
    space.websites = [website]

    assert space.is_website_in_space(website.id)


def test_is_website_not_in_space(space: Space):
    assert not space.is_website_in_space(uuid4())


def test_is_integration_knowledge_in_space(space: Space):
    knowledge = MagicMock(id=uuid4())
    space.integration_knowledge_list = [knowledge]

    assert space.is_integration_knowledge_in_space(knowledge.id)


def test_is_integration_knowledge_not_in_space(space: Space):
    assert not space.is_integration_knowledge_in_space(uuid4())


def test_add_user_that_already_exists(space: Space):
    space.members = {"admin1": MagicMock(id="admin1", role=SpaceRoleValue.ADMIN)}

    with pytest.raises(BadRequestException):
        space.add_member(MagicMock(id="admin1"))


def test_add_user(space: Space):
    user = MagicMock()
    space.add_member(user)

    assert user in space.members.values()


def test_remove_user(space: Space):
    space.members = {12: MagicMock()}

    space.remove_member(12)

    assert space.members == {}


def test_remove_user_if_user_does_not_exist(space: Space):
    space.members = {}

    with pytest.raises(BadRequestException):
        space.remove_member("UUID")


def test_change_role_of_user(space: Space):
    space.members = {12: MagicMock(role=SpaceRoleValue.ADMIN)}

    space.change_member_role(12, SpaceRoleValue.EDITOR)

    assert space.get_member(12).role == SpaceRoleValue.EDITOR


def test_change_role_of_user_to_same(space: Space):
    space.members = {12: MagicMock(role=SpaceRoleValue.ADMIN)}

    space.change_member_role(12, SpaceRoleValue.ADMIN)

    assert space.get_member(12).role == SpaceRoleValue.ADMIN


def test_change_role_of_user_if_user_not_exist(space: Space):
    space.members = {}

    with pytest.raises(BadRequestException):
        space.change_member_role("UUID", SpaceRoleValue.ADMIN)


def test_add_member_in_personal_space(space: Space):
    space.user_id = MagicMock()

    with pytest.raises(BadRequestException):
        space.add_member(MagicMock())


def test_cannot_change_description_of_personal_space(space: Space):
    space.user_id = MagicMock()

    with pytest.raises(BadRequestException):
        space.update(description="new description")


def test_cannot_change_name_of_personal_space(space: Space):
    space.user_id = MagicMock()

    with pytest.raises(BadRequestException):
        space.update(name="new name")


def test_cannot_change_completion_models_of_personal_space(space: Space):
    space.user_id = MagicMock()

    with pytest.raises(BadRequestException):
        space.update(completion_models=[MagicMock()])
