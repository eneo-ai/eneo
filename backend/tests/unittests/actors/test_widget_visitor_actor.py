from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from eneo.actors import SpaceAction, SpaceActor, SpaceResourceType
from eneo.actors.actors.space_actor import SpaceAccessFacts


def _facts(space_id):
    # A shared space (the only kind that can hold a widget's assistant).
    return SpaceAccessFacts(
        id=space_id,
        user_id=None,
        tenant_space_id=uuid4(),
        members={},
        group_members={},
        default_assistant_id=None,
        assistant_ids=frozenset(),
        app_ids=frozenset(),
    )


def _visitor(space_id):
    # Mirrors the synthetic visitor UserInDB: no permissions, no membership,
    # only `active_widget` pointing at the widget's space.
    return SimpleNamespace(
        id=uuid4(),
        permissions=set(),
        user_groups_ids=set(),
        active_api_key=None,
        active_widget=SimpleNamespace(space_id=space_id),
    )


def test_visitor_may_read_published_assistants_in_the_widget_space_only():
    space_id = uuid4()
    actor = SpaceActor(_visitor(space_id), _facts(space_id))

    assert actor.can_perform_action(
        action=SpaceAction.READ,
        resource_type=SpaceResourceType.ASSISTANT,
        resource=MagicMock(published=True),
    )
    assert not actor.can_perform_action(
        action=SpaceAction.READ,
        resource_type=SpaceResourceType.ASSISTANT,
        resource=MagicMock(published=False),
    )

    elsewhere = SpaceActor(_visitor(space_id), _facts(uuid4()))
    assert not elsewhere.can_perform_action(
        action=SpaceAction.READ,
        resource_type=SpaceResourceType.ASSISTANT,
        resource=MagicMock(published=True),
    )


def test_visitor_can_do_nothing_else():
    space_id = uuid4()
    actor = SpaceActor(_visitor(space_id), _facts(space_id))

    # Reading the space itself is what a viewer role means; it exposes no
    # data on the anonymous surface because no route serves it there.
    assert actor.can_perform_action(
        action=SpaceAction.READ, resource_type=SpaceResourceType.SPACE
    )
    for action in (SpaceAction.CREATE, SpaceAction.EDIT, SpaceAction.DELETE):
        assert not actor.can_perform_action(
            action=action, resource_type=SpaceResourceType.ASSISTANT
        )
    assert not actor.can_perform_action(
        action=SpaceAction.READ,
        resource_type=SpaceResourceType.APP,
        resource=MagicMock(published=True),
    )
    assert not actor.can_perform_action(
        action=SpaceAction.READ, resource_type=SpaceResourceType.COLLECTION
    )
