from unittest.mock import MagicMock

import pytest

from intric.actors import SpaceAction, SpaceActor, SpaceResourceType
from intric.modules.module import Modules


# Mocking external dependencies
class MockUser:
    def __init__(self, id, permissions=None, modules=None, role=None, user_groups_ids=None):
        self.id = id
        self.permissions = permissions or []
        self.modules = modules or []
        self.role = role
        self.user_groups_ids = user_groups_ids or set()


class MockGroupMember:
    def __init__(self, id, role):
        self.id = id
        self.role = role


class MockSpace:
    def __init__(self, user_id, personal=False, members=None, tenant_space_id=None, id=None, group_members=None):
        self.user_id = user_id
        self.personal = personal
        self.members = members or {}
        self.group_members = group_members or {}
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
    owner_user.modules.append(Modules.INTRIC_APPLICATIONS)
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


def test_owner_can_not_create_services_without_applications_modules(
    owner_user: MockUser, personal_space: MockSpace
):
    owner_user.permissions.append(MockPermission.SERVICES)
    actor = SpaceActor(owner_user, personal_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.CREATE, resource_type=SpaceResourceType.SERVICE
        )
        is False
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
    owner_user.modules.append(Modules.INTRIC_APPLICATIONS)
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
    viewer_user.modules.append(Modules.INTRIC_APPLICATIONS)
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


# Group Membership Tests


@pytest.fixture
def group_member_user():
    """A user who is a member of group 100."""
    return MockUser(id=10, user_groups_ids={100})


@pytest.fixture
def multi_group_user():
    """A user who is a member of multiple groups."""
    return MockUser(id=11, user_groups_ids={100, 200, 300})


@pytest.fixture
def space_with_group_admin(organization_space):
    """A space with a group that has admin role."""
    return MockSpace(
        user_id=None,
        personal=False,
        tenant_space_id=organization_space.id,
        members={},
        group_members={100: MockGroupMember(id=100, role="admin")},
        id="space-with-group-admin",
    )


@pytest.fixture
def space_with_group_editor(organization_space):
    """A space with a group that has editor role."""
    return MockSpace(
        user_id=None,
        personal=False,
        tenant_space_id=organization_space.id,
        members={},
        group_members={100: MockGroupMember(id=100, role="editor")},
        id="space-with-group-editor",
    )


@pytest.fixture
def space_with_group_viewer(organization_space):
    """A space with a group that has viewer role."""
    return MockSpace(
        user_id=None,
        personal=False,
        tenant_space_id=organization_space.id,
        members={},
        group_members={100: MockGroupMember(id=100, role="viewer")},
        id="space-with-group-viewer",
    )


@pytest.fixture
def space_with_multiple_groups(organization_space):
    """A space with multiple groups at different roles."""
    return MockSpace(
        user_id=None,
        personal=False,
        tenant_space_id=organization_space.id,
        members={},
        group_members={
            100: MockGroupMember(id=100, role="viewer"),
            200: MockGroupMember(id=200, role="editor"),
            300: MockGroupMember(id=300, role="admin"),
        },
        id="space-with-multiple-groups",
    )


def test_user_can_access_space_via_group_membership(
    group_member_user: MockUser, space_with_group_admin: MockSpace
):
    """Test that a user can access a space through group membership."""
    actor = SpaceActor(group_member_user, space_with_group_admin)
    assert actor.can_perform_action(
        action=SpaceAction.READ, resource_type=SpaceResourceType.SPACE
    )


def test_group_admin_can_edit_space(
    group_member_user: MockUser, space_with_group_admin: MockSpace
):
    """Test that a user with admin role via group can edit the space."""
    actor = SpaceActor(group_member_user, space_with_group_admin)
    assert actor.can_perform_action(
        action=SpaceAction.EDIT, resource_type=SpaceResourceType.SPACE
    )


def test_group_editor_cannot_edit_space(
    group_member_user: MockUser, space_with_group_editor: MockSpace
):
    """Test that a user with editor role via group cannot edit the space."""
    actor = SpaceActor(group_member_user, space_with_group_editor)
    assert (
        actor.can_perform_action(
            action=SpaceAction.EDIT, resource_type=SpaceResourceType.SPACE
        )
        is False
    )


def test_group_viewer_can_only_read(
    group_member_user: MockUser, space_with_group_viewer: MockSpace
):
    """Test that a user with viewer role via group can only read."""
    actor = SpaceActor(group_member_user, space_with_group_viewer)

    # Can read the space
    assert actor.can_perform_action(
        action=SpaceAction.READ, resource_type=SpaceResourceType.SPACE
    )

    # Cannot create or edit
    assert (
        actor.can_perform_action(
            action=SpaceAction.CREATE, resource_type=SpaceResourceType.ASSISTANT
        )
        is False
    )


def test_highest_role_is_used_with_multiple_groups(
    multi_group_user: MockUser, space_with_multiple_groups: MockSpace
):
    """Test that when a user is in multiple groups, the highest role is used."""
    # User is in groups 100 (viewer), 200 (editor), 300 (admin)
    actor = SpaceActor(multi_group_user, space_with_multiple_groups)

    # Should have admin privileges (highest role)
    assert actor.can_perform_action(
        action=SpaceAction.EDIT, resource_type=SpaceResourceType.SPACE
    )
    assert actor.can_perform_action(
        action=SpaceAction.DELETE, resource_type=SpaceResourceType.SPACE
    )


def test_direct_membership_overrides_group_membership(organization_space):
    """Test that direct membership with higher role takes precedence."""
    # User is a direct viewer but group admin
    user = MockUser(id=20, role="viewer", user_groups_ids={100})
    space = MockSpace(
        user_id=None,
        personal=False,
        tenant_space_id=organization_space.id,
        members={20: MockUser(id=20, role="viewer")},
        group_members={100: MockGroupMember(id=100, role="admin")},
        id="space-mixed",
    )

    actor = SpaceActor(user, space)

    # Should have admin privileges (highest from group)
    assert actor.can_perform_action(
        action=SpaceAction.EDIT, resource_type=SpaceResourceType.SPACE
    )


def test_user_without_membership_cannot_access(
    group_member_user: MockUser, shared_space: MockSpace
):
    """Test that a user without any membership cannot access the space."""
    # User is only in group 100, but shared_space has no group members
    actor = SpaceActor(group_member_user, shared_space)

    # Should not have any access (user 10 is not a direct member or in any group)
    assert (
        actor.can_perform_action(
            action=SpaceAction.READ, resource_type=SpaceResourceType.SPACE
        )
        is False
    )


def test_group_admin_can_manage_group_members(
    group_member_user: MockUser, space_with_group_admin: MockSpace
):
    """Test that admin via group can manage group members."""
    actor = SpaceActor(group_member_user, space_with_group_admin)

    assert actor.can_perform_action(
        action=SpaceAction.READ, resource_type=SpaceResourceType.GROUP_MEMBER
    )
    assert actor.can_perform_action(
        action=SpaceAction.CREATE, resource_type=SpaceResourceType.GROUP_MEMBER
    )
    assert actor.can_perform_action(
        action=SpaceAction.EDIT, resource_type=SpaceResourceType.GROUP_MEMBER
    )
    assert actor.can_perform_action(
        action=SpaceAction.DELETE, resource_type=SpaceResourceType.GROUP_MEMBER
    )


def test_group_editor_cannot_manage_group_members(
    group_member_user: MockUser, space_with_group_editor: MockSpace
):
    """Test that editor via group cannot manage group members."""
    actor = SpaceActor(group_member_user, space_with_group_editor)

    # Editors have no group member permissions
    assert (
        actor.can_perform_action(
            action=SpaceAction.CREATE, resource_type=SpaceResourceType.GROUP_MEMBER
        )
        is False
    )
    assert (
        actor.can_perform_action(
            action=SpaceAction.DELETE, resource_type=SpaceResourceType.GROUP_MEMBER
        )
        is False
    )
