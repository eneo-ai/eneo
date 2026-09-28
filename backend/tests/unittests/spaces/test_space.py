from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.spaces.space import UNAUTHORIZED_EXCEPTION_MESSAGE, Space, SpaceRoleValue


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
        MagicMock(created_at=datetime(2024, 1, 3 - i), can_access=True)
        for i in range(3)
    ]
    space.embedding_models = embedding_models

    embedding_model = space.get_latest_embedding_model()

    assert embedding_model == embedding_models[0]


def test_get_latest_available_embedding_model_when_not_ordered(space: Space):
    embedding_models = [
        MagicMock(created_at=datetime(2024, 1, 3 - i), can_access=True)
        for i in range(3)
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
    completion_models = [
        MagicMock(created_at=datetime(2024, 1, 3 - i)) for i in range(3)
    ]
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

    # Disable access - a space holding models but none usable raises rather
    # than reporting no default
    default_model.can_access = False
    with pytest.raises(BadRequestException):
        space.get_default_completion_model()

    non_default_model = MagicMock()
    non_default_model.is_org_default = False
    non_default_model.can_access = True
    non_default_model.created_at = datetime.now()
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


def test_remove_assistant_removes_group_chat_membership_by_id(space: Space):
    assistant = MagicMock(id=uuid4())
    other_assistant = MagicMock(id=uuid4())
    group_chat_assistant = SimpleNamespace(assistant=assistant)
    other_group_chat_assistant = SimpleNamespace(assistant=other_assistant)
    group_chat = SimpleNamespace(
        assistants=[group_chat_assistant, other_group_chat_assistant]
    )

    space.assistants = [assistant]
    space.group_chats = [group_chat]

    space.remove_assistant(assistant)

    assert space.assistants == []
    assert group_chat.assistants == [other_group_chat_assistant]


# Group Member Tests


def test_add_group_member(space: Space):
    group = MagicMock(id=uuid4())

    space.add_group_member(group)

    assert group.id in space.group_members
    assert space.group_members[group.id] == group


def test_add_group_member_already_exists(space: Space):
    group_id = uuid4()
    space.group_members = {group_id: MagicMock(id=group_id)}

    with pytest.raises(BadRequestException, match="already a member"):
        space.add_group_member(MagicMock(id=group_id))


def test_cannot_add_group_member_to_personal_space(space: Space):
    space.user_id = MagicMock()  # Makes it a personal space

    with pytest.raises(BadRequestException, match="personal spaces"):
        space.add_group_member(MagicMock(id=uuid4()))


def test_remove_group_member(space: Space):
    group_id = uuid4()
    space.group_members = {group_id: MagicMock(id=group_id)}

    space.remove_group_member(group_id)

    assert group_id not in space.group_members


def test_remove_group_member_not_exists(space: Space):
    space.group_members = {}

    with pytest.raises(BadRequestException, match="not a member"):
        space.remove_group_member(uuid4())


def test_change_group_member_role(space: Space):
    group_id = uuid4()
    space.group_members = {group_id: MagicMock(id=group_id, role=SpaceRoleValue.ADMIN)}

    space.change_group_member_role(group_id, SpaceRoleValue.VIEWER)

    assert space.group_members[group_id].role == SpaceRoleValue.VIEWER


def test_change_group_member_role_not_exists(space: Space):
    space.group_members = {}

    with pytest.raises(BadRequestException, match="not a member"):
        space.change_group_member_role(uuid4(), SpaceRoleValue.ADMIN)


def test_get_group_member(space: Space):
    group_id = uuid4()
    group = MagicMock(id=group_id)
    space.group_members = {group_id: group}

    result = space.get_group_member(group_id)

    assert result == group


def _classification(level: int):
    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )

    return SecurityClassification(
        tenant_id=uuid4(),
        name=f"K{level}",
        description="",
        security_level=level,
        security_enabled=True,
    )


def _model(level: int):
    return SimpleNamespace(
        id=uuid4(),
        can_access=True,
        is_deprecated=False,
        security_classification=_classification(level),
    )


def _space_with(classification, completion_models):
    return Space(
        id=None,
        tenant_id=None,
        tenant_space_id=None,
        user_id=None,
        name=MagicMock(),
        description=None,
        embedding_models=[],
        completion_models=completion_models,
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
        security_classification=classification,
    )


def test_a_hydrated_model_list_is_held_to_the_spaces_classification():
    # A stored list can outlive a reclassification; the space owns the rule, so
    # a model below its level is not usable anywhere the list is read.
    allowed = _model(3)
    below = _model(1)
    space = _space_with(_classification(3), [allowed, below])
    assert [model.id for model in space.completion_models] == [allowed.id]


def test_adding_a_model_below_the_spaces_classification_is_refused():
    space = _space_with(_classification(3), [])
    with pytest.raises(BadRequestException):
        space.add_completion_model(_model(1))
    assert space.completion_models == []
    at_level = _model(3)
    space.add_completion_model(at_level)
    assert [model.id for model in space.completion_models] == [at_level.id]


def _space_with_models(
    classification, *, completion=(), embedding=(), transcription=()
):
    return Space(
        id=None,
        tenant_id=None,
        tenant_space_id=None,
        user_id=None,
        name=MagicMock(),
        description=None,
        embedding_models=list(embedding),
        completion_models=list(completion),
        transcription_models=list(transcription),
        mcp_servers=[],
        default_assistant=MagicMock(),
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
        security_classification=classification,
    )


_KINDS = ("completion", "embedding", "transcription")


def _usable(space, kind):
    return [model.id for model in getattr(space, f"{kind}_models")]


def _linked(space, kind):
    return [model.id for model in getattr(space, f"linked_{kind}_models")]


def _below(space, kind):
    return [model.id for model in getattr(space, f"{kind}_models_below_classification")]


@pytest.mark.parametrize("kind", _KINDS)
def test_a_model_below_the_spaces_classification_stays_linked_but_unusable(kind):
    # Lowering a model's classification must not drop it from the space as a
    # side effect of the next save; it stays linked, is not usable here, and is
    # reported so an admin can decide.
    allowed, below = _model(3), _model(1)
    space = _space_with_models(_classification(3), **{kind: [allowed, below]})

    assert _usable(space, kind) == [allowed.id]
    assert _linked(space, kind) == [allowed.id, below.id]
    assert _below(space, kind) == [below.id]


@pytest.mark.parametrize("kind", _KINDS)
def test_resubmitting_the_linked_list_keeps_a_model_below_the_classification(kind):
    allowed, below, other = _model(3), _model(1), _model(4)
    space = _space_with_models(_classification(3), **{kind: [allowed, below]})

    space.update(**{f"{kind}_models": [allowed, below, other]})

    assert _usable(space, kind) == [allowed.id, other.id]
    assert _linked(space, kind) == [allowed.id, other.id, below.id]
    assert _below(space, kind) == [below.id]


@pytest.mark.parametrize("kind", _KINDS)
def test_leaving_a_model_below_the_classification_out_removes_it(kind):
    allowed, below = _model(3), _model(1)
    space = _space_with_models(_classification(3), **{kind: [allowed, below]})

    space.update(**{f"{kind}_models": [allowed]})

    assert _linked(space, kind) == [allowed.id]
    assert _below(space, kind) == []


@pytest.mark.parametrize("kind", _KINDS)
def test_a_new_link_to_a_model_below_the_classification_is_refused(kind):
    allowed, below = _model(3), _model(1)
    space = _space_with_models(_classification(3), **{kind: [allowed]})

    with pytest.raises(BadRequestException):
        space.update(**{f"{kind}_models": [allowed, below]})
    assert _linked(space, kind) == [allowed.id]


def test_adding_a_linked_model_below_the_classification_stays_refused():
    below = _model(1)
    space = _space_with_models(_classification(3), completion=[below])

    with pytest.raises(BadRequestException):
        space.add_completion_model(below)
    assert space.completion_models == []
    assert _below(space, "completion") == [below.id]


def test_a_linked_model_below_the_classification_cannot_be_used():
    from eneo.main.exceptions import ModelNotAvailableException

    below = _model(1)
    space = _space_with_models(_classification(3), completion=[below])
    assistant = SimpleNamespace(
        completion_model=below,
        collections=[],
        websites=[],
        integration_knowledge_list=[],
    )

    assert not space.is_completion_model_in_space(below.id)
    assert not space.is_completion_model_available(below.id)
    with pytest.raises(ModelNotAvailableException):
        space.can_ask_assistant(assistant)
    with pytest.raises(NotFoundException):
        space.get_completion_model(below.id)


@pytest.mark.parametrize("kind", _KINDS)
def test_lowering_the_spaces_classification_makes_a_linked_model_usable_again(
    kind,
):
    allowed, below = _model(3), _model(1)
    space = _space_with_models(_classification(3), **{kind: [allowed, below]})

    space.update(security_classification=_classification(1))

    assert _usable(space, kind) == [allowed.id, below.id]
    assert _below(space, kind) == []


@pytest.mark.parametrize("kind", _KINDS)
def test_raising_the_spaces_classification_removes_models_below_it_as_on_develop(
    kind,
):
    # Changing the space's classification is the admin's explicit, previewed
    # decision; develop removes the models it no longer allows.
    low, below, high = _model(2), _model(1), _model(5)
    space = _space_with_models(_classification(2), **{kind: [low, below, high]})

    space.update(security_classification=_classification(3))

    assert _linked(space, kind) == [high.id]
    assert _below(space, kind) == []


@pytest.mark.parametrize("kind", _KINDS)
def test_restating_the_same_classification_keeps_a_linked_model_below_it(kind):
    # An idempotent PATCH that resends the space's classification is not a
    # change, so it must not remove anything.
    level = _classification(3)
    allowed, below = _model(3), _model(1)
    space = _space_with_models(level, **{kind: [allowed, below]})

    space.update(security_classification=level)

    assert _linked(space, kind) == [allowed.id, below.id]
    assert _below(space, kind) == [below.id]


@pytest.mark.parametrize("kind", _KINDS)
def test_a_linked_model_below_the_classification_stays_even_if_disabled(kind):
    # Keeping an existing link grants nothing, so a model the tenant has
    # also disabled can still be resubmitted with the linked list.
    allowed, below = _model(3), _model(1)
    below.can_access = False
    space = _space_with_models(_classification(3), **{kind: [allowed, below]})

    space.update(**{f"{kind}_models": [allowed, below]})

    assert _linked(space, kind) == [allowed.id, below.id]
    assert _below(space, kind) == [below.id]


@pytest.mark.parametrize("kind", _KINDS)
def test_another_classification_at_the_same_level_removes_nothing(kind):
    # Eligibility depends on the level alone, so a classification with the
    # same level is not a change that may remove links.
    allowed, below = _model(3), _model(1)
    space = _space_with_models(_classification(3), **{kind: [allowed, below]})

    space.update(security_classification=_classification(3))

    assert _linked(space, kind) == [allowed.id, below.id]
    assert _below(space, kind) == [below.id]


@pytest.mark.parametrize("kind", _KINDS)
def test_a_linked_compatible_model_the_tenant_disabled_stays_linked(kind):
    # Keeping an existing link grants no use, so a model the tenant disabled
    # can be resubmitted with the linked list; it stays unusable.
    allowed, disabled = _model(3), _model(4)
    disabled.can_access = False
    space = _space_with_models(_classification(3), **{kind: [allowed, disabled]})

    space.update(**{f"{kind}_models": [allowed, disabled]})

    assert _linked(space, kind) == [allowed.id, disabled.id]


@pytest.mark.parametrize("kind", _KINDS)
def test_a_new_link_to_a_disabled_model_is_still_refused(kind):
    allowed, disabled = _model(3), _model(4)
    disabled.can_access = False
    space = _space_with_models(_classification(3), **{kind: [allowed]})

    with pytest.raises(UnauthorizedException):
        space.update(**{f"{kind}_models": [allowed, disabled]})


@pytest.mark.parametrize("kind", _KINDS)
def test_an_unrelated_save_changes_no_links(kind):
    allowed, below = _model(3), _model(1)
    space = _space_with_models(_classification(3), **{kind: [allowed, below]})

    space.update(name="Renamed")

    assert space.link_changes(kind) == (set(), set())


@pytest.mark.parametrize("kind", _KINDS)
def test_a_model_list_edit_records_only_what_it_added_and_removed(kind):
    kept, dropped, added = _model(3), _model(1), _model(4)
    space = _space_with_models(_classification(3), **{kind: [kept, dropped]})

    space.update(**{f"{kind}_models": [kept, added]})

    assert space.link_changes(kind) == ({added.id}, {dropped.id})


@pytest.mark.parametrize("kind", _KINDS)
def test_a_level_change_records_the_links_it_removes(kind):
    low, high = _model(2), _model(5)
    space = _space_with_models(_classification(2), **{kind: [low, high]})

    space.update(security_classification=_classification(3))

    assert space.link_changes(kind) == (set(), {low.id})
