from unittest.mock import MagicMock

import pytest

from intric.actors import SpaceAction, SpaceActor, SpaceResourceType


# Mocking external dependencies
class MockUser:
    def __init__(self, id, permissions=None, role=None):
        self.id = id
        self.permissions = permissions or []
        self.role = role


class MockSpace:
    def __init__(self, user_id, personal=False, members=None, tenant_space_id=None, id=None):
        self.user_id = user_id
        self.personal = personal
        self.members = members or {}
        self.tenant_space_id = tenant_space_id
        self.id = id or "space-mock"

    def is_personal(self):
        return self.personal
    
    # Shared = saknar user_id men tenant_space_id är satt (pekar på org-space)
    def is_shared(self):
        return (self.user_id is None) and (self.tenant_space_id is not None)
    
    # Org = saknar både user_id och tenant_space_id
    def is_organization(self):
        return (self.user_id is None) and (self.tenant_space_id is None)
    

class MockSpaceRole:
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class MockPermission:
    ASSISTANTS = "assistants"
    GROUP_CHATS = "group_chats"
    COLLECTIONS = "collections"
    WEBSITES = "websites"
    SERVICES = "services"


@pytest.fixture()
def owner_user():
    return MockUser(id=1)


@pytest.fixture
def viewer_user():
    return MockUser(id=2, role=MockSpaceRole.VIEWER)


@pytest.fixture
def editor_user():
    return MockUser(id=3, role=MockSpaceRole.EDITOR)


@pytest.fixture
def admin_user():
    return MockUser(id=4, role=MockSpaceRole.ADMIN)

@pytest.fixture
def organization_space():
    return MockSpace(
        user_id=None, 
        personal=False, 
        tenant_space_id=None,
        id="org-1"
    )

@pytest.fixture
def personal_space(organization_space, owner_user):
    return MockSpace(
        user_id=owner_user.id, 
        personal=True,
        tenant_space_id=organization_space.id,
        id="personal-1",
    )


@pytest.fixture
def shared_space(organization_space, viewer_user, editor_user, admin_user):
    return MockSpace(
        user_id=None,
        personal=False,
        tenant_space_id=organization_space.id,
        members={user.id: user for user in [viewer_user, editor_user, admin_user]},
        id="shared-1",
    )


def test_owner_can_read_personal_space(owner_user: MockUser, personal_space: MockSpace):
    actor = SpaceActor(owner_user, personal_space)
    assert actor.can_perform_action(
        action=SpaceAction.READ, resource_type=SpaceResourceType.SPACE
    )


def test_owner_cannot_edit_personal_space(
    owner_user: MockUser, personal_space: MockSpace
):
    actor = SpaceActor(owner_user, personal_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.EDIT, resource_type=SpaceResourceType.SPACE
        )
        is False
    )


def test_admin_can_edit_shared_space(admin_user: MockUser, shared_space: MockSpace):
    actor = SpaceActor(admin_user, shared_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.EDIT, resource_type=SpaceResourceType.SPACE
        )
        is True
    )


def test_editor_cannot_edit_shared_space(
    editor_user: MockUser, shared_space: MockSpace
):
    actor = SpaceActor(editor_user, shared_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.EDIT, resource_type=SpaceResourceType.SPACE
        )
        is False
    )


def test_viewer_cannot_edit_shared_space(
    editor_user: MockUser, shared_space: MockSpace
):
    actor = SpaceActor(editor_user, shared_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.EDIT, resource_type=SpaceResourceType.SPACE
        )
        is False
    )


def test_owner_can_not_create_services_without_services_permission(
    owner_user: MockUser, personal_space: MockSpace
):
    actor = SpaceActor(owner_user, personal_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.CREATE, resource_type=SpaceResourceType.SERVICE
        )
        is False
    )

    owner_user.permissions.append(MockPermission.SERVICES)
    actor = SpaceActor(owner_user, personal_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.CREATE, resource_type=SpaceResourceType.SERVICE
        )
        is True
    )


def test_no_one_can_publish_apps_in_personal_space(
    owner_user: MockUser, personal_space: MockSpace
):
    actor = SpaceActor(owner_user, personal_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.PUBLISH, resource_type=SpaceResourceType.APP
        )
        is False
    )


def test_no_one_can_publish_services_in_personal_space(
    owner_user: MockUser, personal_space: MockSpace
):
    actor = SpaceActor(owner_user, personal_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.PUBLISH, resource_type=SpaceResourceType.SERVICE
        )
        is False
    )


def test_viewers_can_only_read_published_resources(
    viewer_user: MockUser, shared_space: MockSpace
):
    resource = MagicMock(published=False)
    viewer = SpaceActor(viewer_user, shared_space)

    assert (
        viewer.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.ASSISTANT,
            resource=resource,
        )
        is False
    )
    assert (
        viewer.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.APP,
            resource=resource,
        )
        is False
    )

    # Test with published resources
    published_resource = MagicMock(published=True)

    assert (
        viewer.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.ASSISTANT,
            resource=published_resource,
        )
        is True
    )
    assert (
        viewer.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.APP,
            resource=published_resource,
        )
        is True
    )
