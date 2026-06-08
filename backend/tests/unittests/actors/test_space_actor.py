from unittest.mock import MagicMock

import pytest

from intric.actors import SpaceAction, SpaceActor, SpaceResourceType
from intric.modules.module import Modules
from intric.roles.permissions import Permission

# All tenant-level permissions — test users should have these by default
# so tests focus on space-role logic, not tenant-permission blocking
ALL_PERMISSIONS = set(Permission)


# Mocking external dependencies
class MockUser:
    def __init__(
        self, id, permissions=None, modules=None, role=None, user_groups_ids=None
    ):
        self.id = id
        if permissions is None:
            self.permissions = {Permission.SHARED_SPACES}
        else:
            self.permissions = permissions
        self.modules = modules or []
        self.role = role
        self.user_groups_ids = user_groups_ids or set()
        # Matches UserInDB shape — always defined, None for token auth, set for
        # API-key auth. The consolidated is_service_api_key helper reads this.
        self.active_api_key = None


class MockGroupMember:
    def __init__(self, id, role):
        self.id = id
        self.role = role


class MockSpace:
    def __init__(
        self,
        user_id,
        personal=False,
        members=None,
        tenant_space_id=None,
        id=None,
        group_members=None,
    ):
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
    return MockUser(id=2, role=MockSpaceRole.VIEWER, permissions=ALL_PERMISSIONS)


@pytest.fixture
def editor_user():
    return MockUser(id=3, role=MockSpaceRole.EDITOR, permissions=ALL_PERMISSIONS)


@pytest.fixture
def admin_user():
    return MockUser(id=4, role=MockSpaceRole.ADMIN, permissions=ALL_PERMISSIONS)


@pytest.fixture
def organization_space():
    return MockSpace(user_id=None, personal=False, tenant_space_id=None, id="org-1")


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

    owner_user.permissions.add(MockPermission.SERVICES)
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
    owner_user.permissions.add(MockPermission.SERVICES)
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
    return MockUser(id=10, user_groups_ids={100}, permissions=ALL_PERMISSIONS)


@pytest.fixture
def multi_group_user():
    """A user who is a member of multiple groups."""
    return MockUser(id=11, user_groups_ids={100, 200, 300}, permissions=ALL_PERMISSIONS)


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


# ---------------------------------------------------------------------------
# Service API key role derivation
# ---------------------------------------------------------------------------


class MockServiceKey:
    """Minimal stand-in for ApiKeyV2InDB used by SpaceActor."""

    def __init__(self, scope_type, scope_id, permission, ownership="service"):
        self.scope_type = scope_type
        self.scope_id = scope_id
        self.permission = permission
        self.ownership = ownership


class MockServiceUser(MockUser):
    def __init__(self, active_api_key, **kwargs):
        super().__init__(**kwargs)
        self.active_api_key = active_api_key


class MockAssistant:
    def __init__(self, id):
        self.id = id


class MockApp:
    def __init__(self, id):
        self.id = id


class MockSpaceWithResources(MockSpace):
    def __init__(self, *, assistants=None, apps=None, **kwargs):
        super().__init__(**kwargs)
        self.assistants = assistants or []
        self.apps = apps or []


def test_service_key_tenant_scoped_grants_viewer():
    key = MockServiceKey("tenant", None, "read")
    user = MockServiceUser(id=99, active_api_key=key)
    space = MockSpace(user_id=None, personal=False, tenant_space_id="org-1", id="s1")
    actor = SpaceActor(user, space)
    assert actor.can_read_space()


def test_service_key_tenant_scoped_admin_grants_edit():
    key = MockServiceKey("tenant", None, "admin")
    user = MockServiceUser(id=99, active_api_key=key)
    space = MockSpace(user_id=None, personal=False, tenant_space_id="org-1", id="s1")
    actor = SpaceActor(user, space)
    assert actor.can_edit_space()


def test_service_key_space_scoped_matching():
    key = MockServiceKey("space", "s1", "read")
    user = MockServiceUser(id=99, active_api_key=key)
    space = MockSpace(user_id=None, personal=False, tenant_space_id="org-1", id="s1")
    actor = SpaceActor(user, space)
    assert actor.can_read_space()


def test_service_key_space_scoped_non_matching():
    key = MockServiceKey("space", "s1", "read")
    user = MockServiceUser(id=99, active_api_key=key)
    space = MockSpace(user_id=None, personal=False, tenant_space_id="org-1", id="other")
    actor = SpaceActor(user, space)
    assert not actor.can_read_space()


def test_service_key_assistant_scoped_matching():
    key = MockServiceKey("assistant", "asst-1", "write")
    user = MockServiceUser(id=99, active_api_key=key)
    space = MockSpaceWithResources(
        user_id=None,
        personal=False,
        tenant_space_id="org-1",
        id="s1",
        assistants=[MockAssistant("asst-1")],
    )
    actor = SpaceActor(user, space)
    assert actor.can_read_space()
    assert actor.can_read_assistants()


def test_service_key_assistant_scoped_non_matching():
    key = MockServiceKey("assistant", "asst-other", "write")
    user = MockServiceUser(id=99, active_api_key=key)
    space = MockSpaceWithResources(
        user_id=None,
        personal=False,
        tenant_space_id="org-1",
        id="s1",
        assistants=[MockAssistant("asst-1")],
    )
    actor = SpaceActor(user, space)
    assert not actor.can_read_space()


def test_service_key_tenant_scoped_write_grants_editor():
    """Write permission → EDITOR: can CRUD resources but NOT edit space."""
    key = MockServiceKey("tenant", None, "write")
    user = MockServiceUser(id=99, active_api_key=key)
    space = MockSpace(user_id=None, personal=False, tenant_space_id="org-1", id="s1")
    actor = SpaceActor(user, space)
    assert actor.can_read_space()
    assert actor.can_read_assistants()
    assert actor.can_create_assistants()
    assert actor.can_edit_assistants()
    assert actor.can_delete_assistants()
    assert not actor.can_edit_space()
    assert not actor.can_delete_space()


def test_service_key_app_scoped_matching():
    key = MockServiceKey("app", "app-1", "write")
    user = MockServiceUser(id=99, active_api_key=key)
    space = MockSpaceWithResources(
        user_id=None,
        personal=False,
        tenant_space_id="org-1",
        id="s1",
        apps=[MockApp("app-1")],
    )
    actor = SpaceActor(user, space)
    assert actor.can_read_space()
    assert actor.can_read_apps()


def test_service_key_app_scoped_non_matching():
    key = MockServiceKey("app", "app-other", "write")
    user = MockServiceUser(id=99, active_api_key=key)
    space = MockSpaceWithResources(
        user_id=None,
        personal=False,
        tenant_space_id="org-1",
        id="s1",
        apps=[MockApp("app-1")],
    )
    actor = SpaceActor(user, space)
    assert not actor.can_read_space()


def test_user_key_does_not_trigger_service_role():
    """A user key (ownership=user) with active_api_key set must NOT derive a
    synthetic role — it should fall through to normal membership checks."""
    key = MockServiceKey("tenant", None, "admin", ownership="user")
    user = MockServiceUser(id=99, active_api_key=key)
    space = MockSpace(user_id=None, personal=False, tenant_space_id="org-1", id="s1")
    actor = SpaceActor(user, space)
    # User has no membership → should be denied even though key has admin
    assert not actor.can_read_space()


def test_service_key_no_key_returns_none():
    """Regular user without active_api_key — actor should fall through."""
    user = MockUser(id=99)
    space = MockSpace(user_id=None, personal=False, tenant_space_id="org-1", id="s1")
    actor = SpaceActor(user, space)
    # No membership, no service key → can_read_space should be False
    assert not actor.can_read_space()


# ---------------------------------------------------------------------------
# User-owned key caps membership role (defense in depth)
# ---------------------------------------------------------------------------


def test_user_key_read_caps_admin_member_to_viewer():
    """A user-owned read key held by a space admin must behave as a viewer."""
    admin_user = MockUser(id=42, role="admin")
    key = MockServiceKey("tenant", None, "read", ownership="user")
    user = MockServiceUser(id=42, active_api_key=key, role="admin")
    space = MockSpace(
        user_id=None,
        personal=False,
        tenant_space_id="org-1",
        id="s1",
        members={admin_user.id: admin_user},
    )
    space.members = {user.id: MockUser(id=user.id, role="admin")}
    actor = SpaceActor(user, space)
    assert actor.can_read_space()
    assert not actor.can_edit_space()
    assert not actor.can_delete_space()
    assert not actor.can_create_assistants()
    assert not actor.can_edit_assistants()
    assert not actor.can_delete_assistants()


def test_user_key_admin_does_not_upgrade_viewer_member():
    """A user-owned admin key held by a viewer must still behave as a viewer."""
    key = MockServiceKey("tenant", None, "admin", ownership="user")
    user = MockServiceUser(id=42, active_api_key=key, role="viewer")
    space = MockSpace(
        user_id=None,
        personal=False,
        tenant_space_id="org-1",
        id="s1",
        members={user.id: MockUser(id=user.id, role="viewer")},
    )
    actor = SpaceActor(user, space)
    assert actor.can_read_space()
    assert not actor.can_edit_space()
    assert not actor.can_create_assistants()


def test_user_key_admin_matches_admin_member():
    """Admin user + admin key → admin (min preserves the shared level)."""
    key = MockServiceKey("tenant", None, "admin", ownership="user")
    user = MockServiceUser(id=42, active_api_key=key, role="admin")
    space = MockSpace(
        user_id=None,
        personal=False,
        tenant_space_id="org-1",
        id="s1",
        members={user.id: MockUser(id=user.id, role="admin")},
    )
    actor = SpaceActor(user, space)
    assert actor.can_read_space()
    assert actor.can_edit_space()
    assert actor.can_delete_space()


def test_user_key_scope_not_covering_space_denies_access():
    """A user-owned key scoped to space-B must not grant access to space-A,
    even when the user has direct admin membership in space-A. The credential
    in hand does not extend to space-A."""
    key = MockServiceKey("space", "space-B", "admin", ownership="user")
    user = MockServiceUser(id=42, active_api_key=key, role="admin")
    space_a = MockSpace(
        user_id=None,
        personal=False,
        tenant_space_id="org-1",
        id="space-A",
        members={user.id: MockUser(id=user.id, role="admin")},
    )
    actor = SpaceActor(user, space_a)
    assert not actor.can_read_space()


def test_bearer_user_without_key_keeps_full_membership_role():
    """Bearer-auth flows leave active_api_key unset — no cap, full role."""
    user = MockUser(id=42, role="admin")
    space = MockSpace(
        user_id=None,
        personal=False,
        tenant_space_id="org-1",
        id="s1",
        members={user.id: MockUser(id=user.id, role="admin")},
    )
    actor = SpaceActor(user, space)
    assert actor.can_read_space()
    assert actor.can_edit_space()
    assert actor.can_delete_space()


def test_personal_space_owner_with_read_key_can_still_read():
    """Personal space owner with a user-owned read key must retain READ
    actions (reading resources, asking assistants). Owner-only read actions
    should pass; mutating actions must be filtered out."""
    key = MockServiceKey("space", "personal-s1", "read", ownership="user")
    user = MockServiceUser(
        id=42,
        active_api_key=key,
        permissions=[
            Permission.ASSISTANTS,
            Permission.APPS,
            Permission.COLLECTIONS,
        ],
    )
    space = MockSpace(user_id=42, personal=True, id="personal-s1")
    actor = SpaceActor(user, space)
    assert actor.can_read_space()
    assert actor.can_read_assistants()
    assert actor.can_read_apps()
    assert actor.can_read_collections()
    assert not actor.can_edit_space()
    assert not actor.can_delete_space()
    assert not actor.can_create_assistants()
    assert not actor.can_edit_assistants()
    assert not actor.can_delete_assistants()


def test_personal_space_owner_with_write_key_can_edit_but_not_delete():
    """Personal space owner + write key → can read/create/edit/publish but
    DELETE requires admin at the HTTP layer, so it must be filtered too."""
    key = MockServiceKey("space", "personal-s1", "write", ownership="user")
    user = MockServiceUser(
        id=42,
        active_api_key=key,
        permissions=[
            Permission.ASSISTANTS,
            Permission.APPS,
            Permission.COLLECTIONS,
        ],
    )
    space = MockSpace(user_id=42, personal=True, id="personal-s1")
    actor = SpaceActor(user, space)
    assert actor.can_read_assistants()
    assert actor.can_create_assistants()
    assert actor.can_edit_assistants()
    assert not actor.can_delete_assistants()


# Integration Knowledge Permission Tests - Shared Spaces


def test_viewer_cannot_create_integration_knowledge_in_shared_space(
    viewer_user: MockUser, shared_space: MockSpace
):
    """Viewers should only be able to read integration knowledge, not create."""
    actor = SpaceActor(viewer_user, shared_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.CREATE,
            resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
        )
        is False
    )


def test_viewer_cannot_edit_integration_knowledge_in_shared_space(
    viewer_user: MockUser, shared_space: MockSpace
):
    actor = SpaceActor(viewer_user, shared_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.EDIT,
            resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
        )
        is False
    )


def test_viewer_cannot_delete_integration_knowledge_in_shared_space(
    viewer_user: MockUser, shared_space: MockSpace
):
    actor = SpaceActor(viewer_user, shared_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.DELETE,
            resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
        )
        is False
    )


def test_viewer_can_read_integration_knowledge_in_shared_space(
    viewer_user: MockUser, shared_space: MockSpace
):
    actor = SpaceActor(viewer_user, shared_space)
    assert actor.can_perform_action(
        action=SpaceAction.READ,
        resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
    )


def test_editor_can_create_integration_knowledge_in_shared_space(
    editor_user: MockUser, shared_space: MockSpace
):
    actor = SpaceActor(editor_user, shared_space)
    assert actor.can_perform_action(
        action=SpaceAction.CREATE,
        resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
    )


def test_editor_can_delete_integration_knowledge_in_shared_space(
    editor_user: MockUser, shared_space: MockSpace
):
    actor = SpaceActor(editor_user, shared_space)
    assert actor.can_perform_action(
        action=SpaceAction.DELETE,
        resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
    )


def test_admin_can_create_integration_knowledge_in_shared_space(
    admin_user: MockUser, shared_space: MockSpace
):
    actor = SpaceActor(admin_user, shared_space)
    assert actor.can_perform_action(
        action=SpaceAction.CREATE,
        resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
    )


def test_admin_can_delete_integration_knowledge_in_shared_space(
    admin_user: MockUser, shared_space: MockSpace
):
    actor = SpaceActor(admin_user, shared_space)
    assert actor.can_perform_action(
        action=SpaceAction.DELETE,
        resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
    )


# Integration Knowledge Permission Tests - Organization Spaces


def test_viewer_cannot_create_integration_knowledge_in_org_space(
    viewer_user: MockUser, organization_space: MockSpace
):
    organization_space.members = {viewer_user.id: viewer_user}
    actor = SpaceActor(viewer_user, organization_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.CREATE,
            resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
        )
        is False
    )


def test_viewer_cannot_delete_integration_knowledge_in_org_space(
    viewer_user: MockUser, organization_space: MockSpace
):
    organization_space.members = {viewer_user.id: viewer_user}
    actor = SpaceActor(viewer_user, organization_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.DELETE,
            resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
        )
        is False
    )


def test_viewer_cannot_read_integration_knowledge_in_org_space(
    viewer_user: MockUser, organization_space: MockSpace
):
    """Org spaces only grant permissions to admins, not viewers."""
    organization_space.members = {viewer_user.id: viewer_user}
    actor = SpaceActor(viewer_user, organization_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.READ,
            resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
        )
        is False
    )


def test_admin_can_read_integration_knowledge_in_org_space(
    admin_user: MockUser, organization_space: MockSpace
):
    organization_space.members = {admin_user.id: admin_user}
    actor = SpaceActor(admin_user, organization_space)
    assert actor.can_perform_action(
        action=SpaceAction.READ,
        resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
    )


def test_admin_can_create_integration_knowledge_in_org_space(
    admin_user: MockUser, organization_space: MockSpace
):
    organization_space.members = {admin_user.id: admin_user}
    actor = SpaceActor(admin_user, organization_space)
    assert actor.can_perform_action(
        action=SpaceAction.CREATE,
        resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
    )


# Integration Knowledge Permission Tests - Group Membership


def test_group_viewer_cannot_create_integration_knowledge(
    group_member_user: MockUser, space_with_group_viewer: MockSpace
):
    """Viewer via group membership should not be able to create integration knowledge."""
    actor = SpaceActor(group_member_user, space_with_group_viewer)
    assert (
        actor.can_perform_action(
            action=SpaceAction.CREATE,
            resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
        )
        is False
    )


def test_group_editor_can_create_integration_knowledge(
    group_member_user: MockUser, space_with_group_editor: MockSpace
):
    """Editor via group membership should be able to create integration knowledge."""
    actor = SpaceActor(group_member_user, space_with_group_editor)
    assert actor.can_perform_action(
        action=SpaceAction.CREATE,
        resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
    )


def test_group_admin_can_create_integration_knowledge(
    group_member_user: MockUser, space_with_group_admin: MockSpace
):
    """Admin via group membership should be able to create integration knowledge."""
    actor = SpaceActor(group_member_user, space_with_group_admin)
    assert actor.can_perform_action(
        action=SpaceAction.CREATE,
        resource_type=SpaceResourceType.INTEGRATION_KNOWLEDGE,
    )


# shared_spaces tenant permission — gates space CREATION only, not viewing.
# Membership alone is the authoritative read/edit gate on a shared space.


def _permissions_without_shared_spaces():
    return {p for p in ALL_PERMISSIONS if p != Permission.SHARED_SPACES}


def test_member_without_shared_spaces_can_read_shared_space(
    shared_space: MockSpace,
):
    """A direct member of a shared space retains access even without the
    tenant-level `shared_spaces` permission — the permission gates creation
    only. This is the post-narrowing semantic (April 2026)."""
    user = MockUser(
        id=42,
        role=MockSpaceRole.ADMIN,
        permissions=_permissions_without_shared_spaces(),
    )
    shared_space.members = {user.id: user}
    actor = SpaceActor(user, shared_space)
    assert actor.can_perform_action(
        action=SpaceAction.READ, resource_type=SpaceResourceType.SPACE
    )


def test_non_member_without_shared_spaces_has_no_role_on_shared_space(
    shared_space: MockSpace,
):
    """A non-member still cannot access a shared space regardless of the
    tenant permission — the permission was never the authorizer; membership is."""
    user = MockUser(
        id=43,
        role=MockSpaceRole.ADMIN,
        permissions=_permissions_without_shared_spaces(),
    )
    actor = SpaceActor(user, shared_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.READ, resource_type=SpaceResourceType.SPACE
        )
        is False
    )


def test_admin_without_shared_spaces_retains_org_space_access(
    organization_space: MockSpace,
):
    """Org-space access is governed by ORG_SPACE_PERMISSIONS, not shared_spaces.
    A tenant admin who opts out of Delat participation must still manage the hub."""
    admin = MockUser(
        id=99,
        role=MockSpaceRole.ADMIN,
        permissions=_permissions_without_shared_spaces(),
    )
    organization_space.members = {admin.id: admin}
    actor = SpaceActor(admin, organization_space)
    assert actor.can_perform_action(
        action=SpaceAction.READ, resource_type=SpaceResourceType.SPACE
    )


def test_viewer_without_shared_spaces_has_no_org_space_access(
    organization_space: MockSpace,
):
    """Viewer role has no org-space permissions regardless of shared_spaces."""
    viewer = MockUser(
        id=100,
        role=MockSpaceRole.VIEWER,
        permissions=_permissions_without_shared_spaces(),
    )
    organization_space.members = {viewer.id: viewer}
    actor = SpaceActor(viewer, organization_space)
    assert (
        actor.can_perform_action(
            action=SpaceAction.READ, resource_type=SpaceResourceType.SPACE
        )
        is False
    )


# Resource tenant-permission gate applies to shared spaces too — regression
# guard for the bug where the gate was scoped to `is_personal()` only, letting
# any EDITOR/ADMIN member create websites in a shared space even when their
# role lacked the `websites` tenant permission (fixed in #348). READ stays
# exempt so distributed knowledge remains visible.


def _permissions_without_websites():
    return {p for p in ALL_PERMISSIONS if p != Permission.WEBSITES}


def test_editor_without_websites_cannot_create_website_in_shared_space(
    shared_space: MockSpace,
):
    user = MockUser(
        id=50,
        role=MockSpaceRole.EDITOR,
        permissions=_permissions_without_websites(),
    )
    shared_space.members = {user.id: user}
    actor = SpaceActor(user, shared_space)
    assert actor.can_create_websites() is False


def test_admin_without_websites_cannot_create_website_in_shared_space(
    shared_space: MockSpace,
):
    user = MockUser(
        id=51,
        role=MockSpaceRole.ADMIN,
        permissions=_permissions_without_websites(),
    )
    shared_space.members = {user.id: user}
    actor = SpaceActor(user, shared_space)
    assert actor.can_create_websites() is False
    assert actor.can_edit_websites() is False
    assert actor.can_delete_websites() is False


def test_editor_without_websites_can_still_read_websites_in_shared_space(
    shared_space: MockSpace,
):
    """READ is exempt from the tenant gate so members keep seeing distributed
    web knowledge even when their role omits the `websites` permission."""
    user = MockUser(
        id=52,
        role=MockSpaceRole.EDITOR,
        permissions=_permissions_without_websites(),
    )
    shared_space.members = {user.id: user}
    actor = SpaceActor(user, shared_space)
    assert actor.can_read_websites() is True


def test_editor_with_websites_can_create_website_in_shared_space(
    shared_space: MockSpace,
):
    """Counterpart: the gate must not over-block — an EDITOR member whose role
    includes `websites` retains full CRUD."""
    user = MockUser(
        id=53,
        role=MockSpaceRole.EDITOR,
        permissions=ALL_PERMISSIONS,
    )
    shared_space.members = {user.id: user}
    actor = SpaceActor(user, shared_space)
    assert actor.can_create_websites() is True


def test_owner_without_websites_cannot_create_website_in_personal_space(
    personal_space: MockSpace,
):
    """The same tenant gate also covers personal spaces."""
    owner = MockUser(id=54, permissions=_permissions_without_websites())
    personal_space.user_id = owner.id
    actor = SpaceActor(owner, personal_space)
    assert actor.can_create_websites() is False


# --- Personal chat (default assistant) permission ------------------------------
# The personal chat is the personal space's default assistant. It is gated by
# its own PERSONAL_CHAT permission, decoupled from ASSISTANTS, so a baseline role
# can grant the chat without granting management of assistants — and vice versa.


def test_owner_cannot_read_personal_default_assistant_without_personal_chat(
    personal_space: MockSpace,
):
    owner = MockUser(id=60, permissions={Permission.ASSISTANTS})
    personal_space.user_id = owner.id
    actor = SpaceActor(owner, personal_space)
    assert actor.can_read_default_assistant() is False
    assert actor.can_edit_default_assistant() is False


def test_owner_can_read_personal_default_assistant_with_personal_chat(
    personal_space: MockSpace,
):
    owner = MockUser(id=61, permissions={Permission.PERSONAL_CHAT})
    personal_space.user_id = owner.id
    actor = SpaceActor(owner, personal_space)
    assert actor.can_read_default_assistant() is True
    assert actor.can_edit_default_assistant() is True


def test_personal_chat_is_decoupled_from_assistants(personal_space: MockSpace):
    """PERSONAL_CHAT alone unlocks the chat; ASSISTANTS is not required."""
    owner = MockUser(id=62, permissions={Permission.PERSONAL_CHAT})
    personal_space.user_id = owner.id
    actor = SpaceActor(owner, personal_space)
    assert actor.can_read_default_assistant() is True
    assert actor.can_read_assistants() is False


def test_assistants_permission_does_not_grant_personal_chat(
    personal_space: MockSpace,
):
    """ASSISTANTS manages assistants but does not unlock the personal chat."""
    owner = MockUser(id=63, permissions={Permission.ASSISTANTS})
    personal_space.user_id = owner.id
    actor = SpaceActor(owner, personal_space)
    assert actor.can_read_assistants() is True
    assert actor.can_read_default_assistant() is False


def test_personal_chat_does_not_gate_shared_space_default_assistant(
    shared_space: MockSpace,
):
    """The PERSONAL_CHAT gate applies only to the personal space. A shared-space
    member reads that space's default assistant via space membership, regardless
    of the PERSONAL_CHAT permission."""
    member = MockUser(id=64, role=MockSpaceRole.EDITOR, permissions=set())
    shared_space.members = {member.id: member}
    actor = SpaceActor(member, shared_space)
    assert actor.can_read_default_assistant() is True
